import { fdGames, fdPointsTabs, fdQuotes, dkGames, dkQuotes, isBackingOff } from './lib/books.js';
import { sameGame } from './lib/match.js';
import { alignTick, buildRows, marketLabel, tickToRecords, toCsv, CSV_HEADERS, etTime } from './lib/compare.js';
import { saveTick, ticksFor } from './lib/store.js';
import { renderChart } from './lib/chart.js';

// DK player-points subcategory ids are guesses until checked in a real browser (DK blocks
// non-browser traffic, so they couldn't be verified while building). Edit them in Settings.
const DEFAULTS = {
  pollSeconds: 15, alignToleranceMs: 2000, fdState: 'az', dkSite: 'US-CO-SB', dkLeague: '42648',
  dkGameSubcat: '4511', dkSubcats: '12488, 16413, 16477', sheetsUrl: '', autoSheet: false,
};
const SERIES = [{ book: 'DK', name: 'DK', color: '#3987e5' }, { book: 'FD', name: 'FD', color: '#d95926' }];
const REPROBE_EVERY = 20;   // pulls; re-try DK subcategories that returned nothing

const $ = (id) => document.getElementById(id);
let settings = { ...DEFAULTS };
let games = [];                 // [{ key, name, fd, dk }]
let run = null;                 // active game run state
let history = [];               // ticks of the shown game (oldest first)
let selectedKey = null;
const diag = { fdGames: '', dkGames: [], lastTick: null, errors: [] };

// ---------------------------------------------------------------- settings
async function loadSettings() {
  const { settings: s } = await chrome.storage.local.get('settings');
  settings = { ...DEFAULTS, ...(s || {}) };
  const f = $('settings');
  for (const [k, v] of Object.entries(settings)) { const i = f.elements[k]; if (!i) continue; if (i.type === 'checkbox') i.checked = !!v; else i.value = v; }
}
$('settings').addEventListener('submit', async (e) => {
  e.preventDefault();
  const f = e.target, s = {};
  for (const k of Object.keys(DEFAULTS)) { const i = f.elements[k]; s[k] = i.type === 'checkbox' ? i.checked : i.type === 'number' ? Number(i.value) : i.value.trim(); }
  s.pollSeconds = Math.max(5, s.pollSeconds || 15);
  settings = s; await chrome.storage.local.set({ settings });
  $('saved').textContent = run ? 'Saved. Press Stop then Start to use the new settings.' : 'Saved.';
  setTimeout(() => { $('saved').textContent = ''; }, 5000);
});
const subIds = () => String(settings.dkSubcats).split(/[\s,]+/).filter(Boolean);

// ---------------------------------------------------------------- lights + diagnostics
function light(book, cls, text) { const l = $(`light-${book}`); l.className = `light ${cls}`; l.querySelector('b').textContent = text; }
function logErr(msg) { diag.errors.unshift(`${etTime(Date.now())}  ${msg}`); diag.errors.length = Math.min(diag.errors.length, 30); renderDiag(); }
function renderDiag() {
  const lines = [];
  lines.push(`FanDuel games: ${diag.fdGames}`);
  lines.push('DraftKings games (tried subcategory → result):');
  for (const t of diag.dkGames) lines.push(`   ${t.subId} → ${t.status === 'ok' ? `${t.events} games` : t.status}`);
  if (run) {
    lines.push(`\nRunning: ${run.game.name}`);
    lines.push(`   FD event ${run.game.fd?.eventId ?? '—'}, tabs: ${run.fdTabs?.join(', ') || '—'}`);
    lines.push(`   DK event ${run.game.dk?.eventId ?? '— (no DK match)'}`);
    if (run.dkPerSub) for (const [k, v] of Object.entries(run.dkPerSub)) lines.push(`   DK subcategory ${k} → ${typeof v === 'number' ? `${v} prices` : v}`);
  }
  if (diag.lastTick) {
    const t = diag.lastTick;
    lines.push(`\nLast pull #${t.id}: ${t.aligned ? 'aligned' : 'NOT aligned'}${t.spreadMs != null ? `, books answered ${t.spreadMs} ms apart` : ''}`);
    for (const b of ['DK', 'FD']) lines.push(`   ${b}: ${t.used[b] ? `used (${t.ms[b]} ms, ${t.counts[b]} prices)` : (t.errors[b] || 'not used')}`);
  }
  if (diag.errors.length) lines.push('\nRecent problems:', ...diag.errors.map(e => `   ${e}`));
  $('diag').textContent = lines.join('\n');
  const dkOk = run?.dkPerSub && Object.values(run.dkPerSub).some(v => typeof v === 'number' && v > 0);
  $('diag-summary').textContent = run ? (dkOk ? '' : '· DK has no prices yet: open this for details') : '';
}

// ---------------------------------------------------------------- games
async function loadGames() {
  $('game').innerHTML = '<option>Loading games…</option>';
  const [fd, dk] = await Promise.allSettled([fdGames(settings.fdState), dkGames(settings.dkSite, settings.dkLeague, [settings.dkGameSubcat, ...subIds()])]);
  const fdList = fd.status === 'fulfilled' ? fd.value : [];
  const dkRes = dk.status === 'fulfilled' ? dk.value : { games: [], tried: [{ subId: '-', status: String(dk.reason?.message || dk.reason) }] };
  diag.fdGames = fd.status === 'fulfilled' ? `${fdList.length} found` : `failed: ${fd.reason?.message || fd.reason}`;
  diag.dkGames = dkRes.tried;
  light('FD', fd.status === 'fulfilled' && fdList.length ? 'ok' : 'bad', fd.status === 'fulfilled' ? `${fdList.length} games` : 'error');
  light('DK', dkRes.games.length ? 'ok' : 'bad', dkRes.games.length ? `${dkRes.games.length} games` : 'no games (see Diagnostics)');

  games = [];
  for (const g of fdList) games.push({ key: `fd${g.eventId}`, name: g.name, startTime: g.startTime, fd: g, dk: dkRes.games.find(d => sameGame([d.away, d.home], [g.away, g.home])) || null });
  for (const d of dkRes.games) if (!games.some(g => g.dk === d)) games.push({ key: `dk${d.eventId}`, name: d.name, startTime: d.startTime, fd: null, dk: d });
  games.sort((a, b) => (a.startTime || 0) - (b.startTime || 0));

  const sel = $('game'); sel.textContent = '';
  if (!games.length) { const o = document.createElement('option'); o.textContent = 'No games found: see Diagnostics'; sel.appendChild(o); }
  const dfmt = new Intl.DateTimeFormat('en-US', { timeZone: 'America/New_York', weekday: 'short', month: 'numeric', day: 'numeric', hour: 'numeric', minute: '2-digit' });
  for (const g of games) {
    const o = document.createElement('option'); o.value = g.key;
    const books = g.fd && g.dk ? 'DK + FD' : g.fd ? 'FD only' : 'DK only';
    o.textContent = `${g.startTime ? dfmt.format(g.startTime) : ''}  ${g.name}  (${books})`;
    sel.appendChild(o);
  }
  if (run) sel.value = run.game.key;
  renderDiag();
}
$('refresh').addEventListener('click', loadGames);
$('game').addEventListener('change', async () => { if (run) return; const g = games.find(x => x.key === $('game').value); if (g) await showGame(g); });

async function showGame(g) {
  history = await ticksFor(g.key); selectedKey = null;
  renderTable(); renderSelected();
}

// ---------------------------------------------------------------- run
const worker = new Worker('lib/ticker.js');
worker.onmessage = () => { pull().catch(e => logErr(`pull crashed: ${e.message || e}`)); };

$('start').addEventListener('click', async () => {
  const g = games.find(x => x.key === $('game').value);
  if (!g) return;
  await showGame(g);
  run = { game: g, busy: false, skipped: 0, nextId: (history.at(-1)?.id || 0) + 1, fdTabs: null, dkActive: null, dkPerSub: null, n: 0 };
  if (g.fd) await findFdTabs(run);
  $('start').disabled = true; $('stop').disabled = false; $('game').disabled = true;
  worker.postMessage({ cmd: 'start', ms: settings.pollSeconds * 1000 });
});
$('stop').addEventListener('click', () => {
  worker.postMessage({ cmd: 'stop' });
  run = null; $('start').disabled = false; $('stop').disabled = true; $('game').disabled = false;
  $('tickinfo').textContent = 'Stopped.'; renderDiag();
});

async function findFdTabs(r) {
  try { r.fdTabs = await fdPointsTabs(settings.fdState, r.game.fd.eventId); }
  catch (e) { r.fdTabs = ['player-points']; logErr(`FD tab lookup: ${e.message}`); }
}

async function fetchBook(book, fn) {
  const sent = performance.now();
  try {
    const out = await fn();
    return { ok: true, at: Date.now(), ms: Math.round(performance.now() - sent), ...out };
  } catch (e) {
    return { ok: false, at: Date.now(), ms: Math.round(performance.now() - sent), error: String(e.message || e) };
  }
}

async function pull() {
  if (!run) return;
  if (run.busy) { run.skipped++; return; }   // the last pull is still waiting on a book
  run.busy = true;
  const r = run, g = r.game, id = r.nextId++, t = Date.now();
  try {
    // DK: the subcategories that returned prices before; all of them at first and every REPROBE_EVERY pulls
    const subs = (!r.dkActive?.length || r.n % REPROBE_EVERY === 0) ? subIds() : r.dkActive;
    if (g.fd && !r.fdTabs?.length && r.n % REPROBE_EVERY === 0 && r.n) await findFdTabs(r);   // FD posts props later
    r.n++;
    const [DK, FD] = await Promise.all([
      !g.dk ? Promise.resolve({ ok: false, error: 'no DK match for this game' })
        : isBackingOff('DK') ? Promise.resolve({ ok: false, error: 'DK backing off after an error' })
        : fetchBook('DK', async () => { const x = await dkQuotes(settings.dkSite, g.dk.eventId, subs); return { quotes: x.quotes, perSub: x.perSub }; }),
      !g.fd ? Promise.resolve({ ok: false, error: 'no FD match for this game' })
        : isBackingOff('FD') ? Promise.resolve({ ok: false, error: 'FD backing off after an error' })
        : !r.fdTabs?.length ? Promise.resolve({ ok: false, error: 'FanDuel has no player points for this game yet (preseason games usually have none)' })
        : fetchBook('FD', async () => ({ quotes: await fdQuotes(settings.fdState, g.fd.eventId, r.fdTabs) })),
    ]);
    if (run !== r) return;   // stopped while waiting

    if (DK.perSub) {
      r.dkPerSub = { ...(r.dkPerSub || {}), ...DK.perSub };
      const good = Object.entries(DK.perSub).filter(([, v]) => typeof v === 'number' && v > 0).map(([k]) => k);
      if (subs.length === subIds().length) r.dkActive = good;   // learn from a full probe
      if (!DK.quotes.length) { DK.ok = false; DK.error = 'DK answered but had no player-points prices (check the subcategory ids)'; }
    }
    const res = { DK, FD };
    const al = alignTick(res, settings.alignToleranceMs);
    const errors = {};
    for (const b of ['DK', 'FD']) {
      if (!res[b].ok) errors[b] = res[b].error;
      else if (!al.used[b]) errors[b] = `answered ${res[b].at - al.firstAt} ms after the other book (limit ${settings.alignToleranceMs}): left out of this pull`;
    }
    const rows = buildRows({ DK: al.used.DK ? DK.quotes : [], FD: al.used.FD ? FD.quotes : [] });
    const tick = {
      gameKey: g.key, game: g.name, id, t, aligned: al.aligned, spreadMs: al.spreadMs, used: al.used,
      at: { DK: DK.at, FD: FD.at }, ms: { DK: DK.ms, FD: FD.ms }, counts: { DK: DK.quotes?.length || 0, FD: FD.quotes?.length || 0 }, errors, rows,
    };
    await saveTick(tick);
    history.push(tick);
    diag.lastTick = tick;

    for (const b of ['DK', 'FD']) {
      if (al.used[b]) light(b, 'ok', `${res[b].ms} ms · ${tick.counts[b]} prices`);
      else light(b, res[b].ok ? 'warn' : 'bad', res[b].ok ? 'late this pull' : 'missing this pull');
      if (errors[b] && (g[b.toLowerCase()])) logErr(`pull #${id} ${b}: ${errors[b]}`);
    }
    const alignedN = history.filter(x => x.aligned).length;
    $('tickinfo').textContent = `Pull #${id} at ${etTime(t).slice(11)} ET · ${alignedN}/${history.length} aligned${r.skipped ? ` · ${r.skipped} skipped (book slower than ${settings.pollSeconds}s)` : ''}`;
    renderTable(); renderSelected(); renderDiag();
    if (settings.autoSheet && settings.sheetsUrl) sendNewTicks(g.key, true);
  } finally { r.busy = false; }
}

// ---------------------------------------------------------------- table
const fmtP = (p) => p == null ? '–' : `${(p * 100).toFixed(1)}%`;
function renderTable() {
  const tb = $('table').tBodies[0]; tb.textContent = '';
  const last = history.at(-1);
  $('latest-time').textContent = last ? `· pull #${last.id}, ${etTime(last.t).slice(11)} ET${last.aligned ? '' : ' (not aligned: one book missing)'}` : '';
  $('empty').hidden = !!last?.rows.length;
  if (!last) return;
  const q = $('filter').value.trim().toLowerCase(), bothOnly = $('both-only').checked;
  let rows = last.rows.filter(r => (!q || r.player.toLowerCase().includes(q)) && (!bothOnly || (r.books.DK && r.books.FD)));
  if ($('sort').value === 'gap') rows = rows.slice().sort((a, b) => Math.abs(b.gapPts ?? -1) - Math.abs(a.gapPts ?? -1));
  for (const r of rows) {
    const tr = document.createElement('tr'); if (r.key === selectedKey) tr.className = 'sel';
    const cells = [r.player, marketLabel(r), r.books.DK?.over?.american, r.books.DK?.under?.american, r.books.FD?.over?.american, r.books.FD?.under?.american,
      fmtP(r.books.DK?.p), fmtP(r.books.FD?.p), r.gapPts == null ? '–' : `${r.gapPts > 0 ? '+' : ''}${r.gapPts.toFixed(1)} pts`];
    cells.forEach((c, i) => {
      const td = document.createElement('td'); td.textContent = c ?? '–';
      if (i >= 2) td.className = 'num';
      if (c == null || c === '–') td.classList.add('na');
      if (i === 8 && r.gapPts != null && Math.abs(r.gapPts) >= 3) td.classList.add('big');
      tr.appendChild(td);
    });
    tr.addEventListener('click', () => { selectedKey = r.key; renderTable(); renderSelected(); });
    tb.appendChild(tr);
  }
  if (!rows.length) { $('empty').hidden = false; $('empty').textContent = bothOnly ? 'No lines both books offer in this pull. Untick "Only lines both books have" to see everything.' : 'No prices in this pull.'; }
}
['filter', 'both-only', 'sort'].forEach(id => $(id).addEventListener('input', renderTable));

// ---------------------------------------------------------------- chart
function renderSelected() {
  const legend = $('legend'); legend.textContent = '';
  if (!selectedKey) { $('chart').textContent = ''; $('chart-title').textContent = 'Click a row below to graph it'; return; }
  const any = history.findLast(t => t.rows.some(r => r.key === selectedKey));
  const row = any?.rows.find(r => r.key === selectedKey);
  $('chart-title').textContent = row ? `${row.player} · ${marketLabel(row)}` : 'Line no longer offered';
  for (const s of SERIES) { const sp = document.createElement('span'); sp.style.setProperty('--c', s.color); sp.textContent = s.book === 'DK' ? 'DraftKings' : 'FanDuel'; legend.appendChild(sp); }
  const points = history.map(t => {
    const r = t.rows.find(x => x.key === selectedKey), values = {};
    for (const s of SERIES) { const b = r?.books[s.book]; values[s.book] = b?.p != null ? { p: b.p, over: b.over?.american, under: b.under?.american } : null; }
    return { t: t.t, id: t.id, aligned: t.aligned, values };
  });
  renderChart($('chart'), $('tooltip'), points, SERIES);
}
window.addEventListener('resize', () => renderSelected());

// ---------------------------------------------------------------- export
function currentGameKey() { return run?.game.key || $('game').value; }
$('csv').addEventListener('click', async () => {
  const key = currentGameKey(); const ticks = await ticksFor(key);
  if (!ticks.length) { alert('Nothing saved for this game yet.'); return; }
  const csv = toCsv(ticks.flatMap(tickToRecords));
  const a = document.createElement('a');
  a.href = URL.createObjectURL(new Blob([csv], { type: 'text/csv' }));
  a.download = `prop-compare_${ticks[0].game.replace(/[^A-Za-z0-9]+/g, '-')}_${etTime(ticks[0].t).slice(0, 10).replace(/\//g, '-')}.csv`;
  a.click(); setTimeout(() => URL.revokeObjectURL(a.href), 5000);
});

let sheetWarned = false;
async function sendToSheet(records, game, quiet) {
  if (!settings.sheetsUrl) { if (!quiet) alert('Add the Google Sheet web app URL in Settings first (see README).'); return false; }
  const date = new Intl.DateTimeFormat('en-CA', { timeZone: 'America/New_York' }).format(new Date());
  try {
    for (let i = 0; i < records.length; i += 2000) {
      const resp = await fetch(settings.sheetsUrl, {
        method: 'POST', credentials: 'include',
        headers: { 'Content-Type': 'text/plain;charset=utf-8' },    // text/plain avoids a CORS preflight
        body: JSON.stringify({ tab: `${date} ${game}`, headers: CSV_HEADERS, rows: records.slice(i, i + 2000) }),
      });
      const text = await resp.text();
      let ok = false; try { ok = JSON.parse(text).ok === true; } catch { /* Google sign-in page instead of JSON */ }
      if (!ok) throw new Error(`the sheet did not accept the rows (HTTP ${resp.status}). Open the web app URL once in this browser and click Allow, then try again.`);
    }
    return true;
  } catch (e) {
    if (!quiet || !sheetWarned) logErr(`Google Sheet: ${e.message || e}`);
    if (!quiet) alert(`Google Sheet: ${e.message || e}`);
    sheetWarned = true; return false;
  }
}
// Only pulls not sent before go to the sheet, so pressing the button twice (or having
// auto-send on) never writes the same row twice.
let sending = false;
async function sendNewTicks(key, quiet) {
  if (sending) return null;
  sending = true;
  try {
    const { sheetSent = {} } = await chrome.storage.local.get('sheetSent');
    const ticks = (await ticksFor(key)).filter(t => t.id > (sheetSent[key] || 0));
    if (!ticks.length) return 0;
    if (!await sendToSheet(ticks.flatMap(tickToRecords), ticks[0].game, quiet)) return null;
    sheetSent[key] = ticks.at(-1).id; await chrome.storage.local.set({ sheetSent });
    return ticks.length;
  } finally { sending = false; }
}
$('sheet').addEventListener('click', async () => {
  const btn = $('sheet'); btn.disabled = true; btn.textContent = 'Sending…';
  const n = await sendNewTicks(currentGameKey(), false);
  btn.disabled = false;
  btn.textContent = n == null ? 'Send to Google Sheet' : n === 0 ? 'Already up to date' : `Sent ${n} pulls ✓`;
  setTimeout(() => { btn.textContent = 'Send to Google Sheet'; }, 4000);
});

// ---------------------------------------------------------------- boot
await loadSettings();
await loadGames();
if (games[0]) await showGame(games.find(g => g.key === $('game').value) || games[0]);
