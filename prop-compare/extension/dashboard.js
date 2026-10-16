import { fdGames, fdPointsTabs, fdQuotes, dkGames, dkQuotes, isBackingOff, setDkHost } from './lib/books.js';
import * as books from './lib/books.js';
import { sameGame, teamNick } from './lib/match.js';
import { ourGames, ourQuotes, parseOurSlate, testOurEvent, DEFAULT_SLATE_PARAMS, DEFAULT_CARDPACK_QUERY } from './lib/ours.js';
import * as ours from './lib/ours.js';
import { BOOKS, alignTick, buildRows, marketLabel, tickToRecords, toCsv, CSV_HEADERS, etTime } from './lib/compare.js';
import { saveTick, ticksFor } from './lib/store.js';
import { renderChart } from './lib/chart.js';

// DK player-points subcategory ids are guesses until checked in a real browser (DK blocks
// non-browser traffic, so they couldn't be verified while building). Edit them in Settings.
const DEFAULTS = {
  pollSeconds: 15, alignToleranceMs: 2000, fdState: 'az', dkSite: 'US-CO-SB', dkLeague: '42648',
  dkGameSubcat: '4511', dkSubcats: '12488, 16413, 16477', sheetsUrl: '', autoSheet: false,
};
const SERIES = [{ book: 'DK', name: 'DK', long: 'DraftKings', color: '#3987e5' }, { book: 'FD', name: 'FD', long: 'FanDuel', color: '#d95926' },
  { book: 'OURS', name: 'Ours', long: 'Ours', color: '#199e70' }];
const GAP_SERIES = [{ book: 'OURS_DK', name: 'vs DK', long: 'Ours − DraftKings', color: '#3987e5' }, { book: 'OURS_FD', name: 'vs FD', long: 'Ours − FanDuel', color: '#d95926' }];
const BOOK_NAME = { DK: 'DraftKings', FD: 'FanDuel', OURS: 'Ours' };
const REPROBE_EVERY = 20;   // pulls; re-try DK subcategories that returned nothing

const $ = (id) => document.getElementById(id);
let settings = { ...DEFAULTS };
let games = [];                 // [{ key, name, fd, dk }]
let run = null;                 // active game run state
let history = [];               // ticks of the shown game (oldest first)
let selectedKey = null;
const diag = { fdGames: '', dkGames: [], ourGames: '', lastTick: null, errors: [] };

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
// DK ids: what background.js saw DraftKings' own page use comes first, then Settings.
let learned = { host: null, site: null, leagues: {}, subs: {}, events: {}, urls: [] };
const uniq = (a) => [...new Set(a.filter(Boolean).map(String))];
const learnedPointSubs = () => Object.entries(learned.subs || {})
  .filter(([, v]) => /point/i.test(v.page || '') && !/combo|\+|rebound|assist/i.test(v.page || '')).map(([k]) => k);
const subIds = () => uniq([...learnedPointSubs(), ...String(settings.dkSubcats).split(/[\s,]+/)]);
const dkSite = () => learned.site || settings.dkSite;
const dkLeagues = () => uniq([...Object.keys(learned.leagues || {}), settings.dkLeague]);
// Our feed: slate requests ("cardpacks") and event pages seen on our own sportsbook site.
let oursLearned = { cardpacks: [], events: {}, query: null, urls: [] };
async function loadLearned() {
  ({ dkLearned: learned = learned, oursLearned = oursLearned } = await chrome.storage.local.get(['dkLearned', 'oursLearned']));
  setDkHost(learned.host);
}
let relearnTimer = null;
chrome.storage.onChanged.addListener((ch) => {
  if (ch.oursLearned) {
    oursLearned = ch.oursLearned.newValue || oursLearned; renderDiag();
    if (!run && !games.some(g => g.ours)) { clearTimeout(relearnTimer); relearnTimer = setTimeout(loadGames, 3000); }
  }
  if (!ch.dkLearned) return;
  learned = ch.dkLearned.newValue || learned; setDkHost(learned.host); renderDiag();
  // new DK ids seen and DK has no games yet: reload the list (not while a game is running)
  if (!run && !games.some(g => g.dk)) { clearTimeout(relearnTimer); relearnTimer = setTimeout(loadGames, 3000); }
});

// ---------------------------------------------------------------- lights + diagnostics
function light(book, cls, text) { const l = $(`light-${book}`); l.className = `light ${cls}`; l.querySelector('b').textContent = text; }
function logErr(msg) { diag.errors.unshift(`${etTime(Date.now())}  ${msg}`); diag.errors.length = Math.min(diag.errors.length, 30); renderDiag(); }
function renderDiag() {
  const lines = [];
  lines.push(`FanDuel games: ${diag.fdGames}`);
  lines.push('DraftKings games (tried league / subcategory → result):');
  for (const t of diag.dkGames) lines.push(`   ${t.league} / ${t.subId} → ${t.status === 'ok' ? `${t.events} games` : t.status}`);
  const ls = Object.entries(learned.subs || {});
  lines.push(`\nLearned from your DraftKings tabs: ${ls.length ? '' : 'nothing yet. Open a game\'s Player Points tab on sportsbook.draftkings.com.'}`);
  if (ls.length) {
    lines.push(`   site ${learned.site || '?'}, API host ${learned.host || '?'}, leagues ${Object.keys(learned.leagues || {}).join(', ') || '—'}`);
    for (const [k, v] of ls) lines.push(`   subcategory ${k}  (${v.page || 'page unknown'})${learnedPointSubs().includes(k) ? '  ← used for points' : ''}`);
    for (const [k, v] of Object.entries(learned.events || {})) lines.push(`   event ${k}  ${v.name || ''}`);
  }
  if (!learnedPointSubs().length && learned.urls?.length) {
    lines.push('   Last DraftKings page requests seen (send a screenshot of this if DK stays red):');
    for (const x of learned.urls.slice(0, 8)) lines.push(`     ${decodeURIComponent(x).replace(/^https:\/\/[^/]+/, '').slice(0, 220)}`);
  }
  lines.push(`   DK ids in use: site ${dkSite()}, leagues ${dkLeagues().join(', ')}, points subcategories ${subIds().join(', ')}`);
  lines.push(`\nOur prices: ${diag.ourGames}`);
  const np = Object.keys(oursLearned.portal || {}).length;
  lines.push(`   Trading portal: ${np ? `${np} game rows read` : 'nothing yet. Open trading.1.betfanatics.com/trading/portal and show tonight\'s NBA games.'}`);
  lines.push(`   Our sportsbook site: ${oursLearned.cardpacks.length} slate request(s), ${Object.keys(oursLearned.events).length} event page(s) seen`);
  for (const g of games.filter(x => x.ours)) lines.push(`   ${g.name} → our event ${g.ours.eventId}${g.ours.fromPortal ? `  (portal row: ${g.ours.name.slice(0, 90)})` : ''}`);
  for (const c of oursLearned.cardpacks.slice(0, 4)) lines.push(`   slate paths ${c.paths.join(', ')}  (${(c.page || '').replace(/^https?:\/\//, '').slice(0, 80)})`);
  if (run) {
    lines.push(`\nRunning: ${run.game.name}`);
    lines.push(`   FD event ${run.game.fd?.eventId ?? '—'}, tabs: ${run.fdTabs?.join(', ') || '—'}`);
    lines.push(`   DK event ${run.game.dk?.eventId ?? '— (no DK match)'}`);
    if (run.dkPerSub) for (const [k, v] of Object.entries(run.dkPerSub)) lines.push(`   DK subcategory ${k} → ${typeof v === 'number' ? `${v} prices` : v}`);
    lines.push(`   Our event ${run.oursId || '— (none: type it in "Our event id")'}`);
    if (run.ourTypes) lines.push(`   Our market codes in this game: ${Object.entries(run.ourTypes).map(([k, v]) => `${k}${v ? ` (${v})` : ''}`).sort().join('  ·  ').slice(0, 1500)}`);
    if (run.ourUnread?.length) lines.push(`   Our points markets we could not read (send a screenshot): ${JSON.stringify(run.ourUnread).slice(0, 1200)}`);
  }
  if (diag.lastTick) {
    const t = diag.lastTick;
    lines.push(`\nLast pull #${t.id}: ${t.aligned ? 'aligned' : 'NOT aligned'}${t.spreadMs != null ? `, books answered ${t.spreadMs} ms apart` : ''}`);
    for (const b of BOOKS) lines.push(`   ${b}: ${t.used[b] ? `used (${t.ms[b]} ms, ${t.counts[b]} prices)` : (t.errors[b] || 'not used')}`);
  }
  if (books.lastDkSample) lines.push('\nDraftKings answer we could not read (send a screenshot):', JSON.stringify(books.lastDkSample).slice(0, 1500));
  if (diag.errors.length) lines.push('\nRecent problems:', ...diag.errors.map(e => `   ${e}`));
  $('diag').textContent = lines.join('\n');
  const dkOk = run?.dkPerSub && Object.values(run.dkPerSub).some(v => typeof v === 'number' && v > 0);
  $('diag-summary').textContent = run ? (dkOk ? '' : '· DK has no prices yet: open this for details') : '';
}

// ---------------------------------------------------------------- games
async function loadGames() {
  $('game').innerHTML = '<option>Loading games…</option>';
  const [fd, dk] = await Promise.allSettled([fdGames(settings.fdState), dkGames(dkSite(), dkLeagues(), uniq([...learnedPointSubs(), settings.dkGameSubcat, ...subIds()]))]);
  const fdList = fd.status === 'fulfilled' ? fd.value : [];
  const dkRes = dk.status === 'fulfilled' ? dk.value : { games: [], tried: [{ subId: '-', status: String(dk.reason?.message || dk.reason) }] };
  diag.fdGames = fd.status === 'fulfilled' ? `${fdList.length} found` : `failed: ${fd.reason?.message || fd.reason}`;
  diag.dkGames = dkRes.tried;
  light('FD', fd.status === 'fulfilled' && fdList.length ? 'ok' : 'bad', fd.status === 'fulfilled' ? `${fdList.length} games` : 'error');
  light('DK', dkRes.games.length ? 'ok' : 'bad', dkRes.games.length ? `${dkRes.games.length} games` : 'no games (see Diagnostics)');

  games = [];
  for (const g of fdList) games.push({ key: `fd${g.eventId}`, name: g.name, startTime: g.startTime, fd: g, dk: null });
  // DK events seen in the user's own DK tabs count too (they may be missing from the slate call)
  for (const [eventId, v] of Object.entries(learned.events || {})) {
    if (!v.name || dkRes.games.some(d => d.eventId === eventId)) continue;
    const [away, home] = v.name.split(' @ ');
    if (away && home) dkRes.games.push({ eventId, name: v.name, away, home, startTime: null, learned: true });
  }
  // Pair DK and FD games: same teams, then closest start time (the same matchup comes up on several
  // dates). A DK event you opened on DraftKings wins over one only found in the slate.
  const pairs = [];
  for (const d of dkRes.games) for (const g of games) {
    if (!g.fd || !sameGame([d.away, d.home], [g.fd.away, g.fd.home])) continue;
    const gap = d.startTime && g.startTime ? Math.abs(d.startTime - g.startTime) : null;
    if (gap != null && gap > 18 * 3600_000) continue;            // different day: not the same game
    const seen = learned.events?.[d.eventId]?.at || 0;
    pairs.push({ d, g, score: (gap ?? 6 * 3600_000) - (seen ? 1e12 + seen : 0) });
  }
  pairs.sort((a, b) => a.score - b.score);
  const usedDk = new Set();
  for (const { d, g } of pairs) {
    if (g.dk || usedDk.has(d.eventId)) continue;
    g.dk = d; usedDk.add(d.eventId); if (!g.startTime) g.startTime = d.startTime;
  }
  for (const d of dkRes.games) if (!usedDk.has(d.eventId) && d.startTime && d.startTime < Date.now() + 36 * 3600_000 || d.learned && !usedDk.has(d.eventId))
    games.push({ key: `dk${d.eventId}`, name: d.name, startTime: d.startTime, fd: null, dk: d });
  await attachOurGames();
  games.sort((a, b) => (a.startTime || 0) - (b.startTime || 0));

  const sel = $('game'); sel.textContent = '';
  if (!games.length) { const o = document.createElement('option'); o.textContent = 'No games found: see Diagnostics'; sel.appendChild(o); }
  const dfmt = new Intl.DateTimeFormat('en-US', { timeZone: 'America/New_York', weekday: 'short', month: 'numeric', day: 'numeric', hour: 'numeric', minute: '2-digit' });
  for (const g of games) {
    const o = document.createElement('option'); o.value = g.key;
    const books = [g.dk && 'DK', g.fd && 'FD', g.ours && 'Ours'].filter(Boolean).join(' + ');
    o.textContent = `${g.startTime ? dfmt.format(g.startTime) : ''}  ${g.name}  (${books})`;
    sel.appendChild(o);
  }
  if (run) sel.value = run.game.key;
  renderDiag();
}
$('refresh').addEventListener('click', loadGames);

// Our games: every slate request learned from our site (newest first), plus event pages the
// user opened there (their teams read from the event page itself). Paired with the DK/FD
// game that has the same two team nicknames (order-free: our feed may list home first).
const nickSet = (names) => names.map(teamNick).sort().join('|');
let lastOurEvents = [];
async function attachOurGames() {
  const found = new Map();
  const errs = [];
  for (const c of oursLearned.cardpacks.slice(0, 6)) {
    try { for (const e of await ourGames(c.paths, c.params || DEFAULT_SLATE_PARAMS, c.query || oursLearned.query || DEFAULT_CARDPACK_QUERY)) found.set(e.eventId, e); }
    catch (e) { errs.push(String(e.message || e)); }
  }
  const recent = Object.entries(oursLearned.events).sort((a, b) => b[1].at - a[1].at).slice(0, 10);
  await Promise.all(recent.map(async ([id]) => {
    if (found.has(id)) return;
    try {
      const r = await fetch(`https://content.1.betfanatics.com/page/event/${encodeURIComponent(id)}`, { credentials: 'omit' });
      const ev = parseOurSlate(await r.json()).find(x => x.eventId === id);
      if (ev) found.set(id, ev);
    } catch (e) { errs.push(String(e.message || e)); }
  }));
  lastOurEvents = [...found.values()];
  let n = 0;
  for (const ev of found.values()) {
    const forms = ev.participants;
    if (forms.length !== 2) continue;
    const key = nickSet(forms.map(f => f[0]));
    const cands = games.filter(g => !g.ours && nickSet([g.fd?.away || g.dk?.away, g.fd?.home || g.dk?.home]) === key)
      .filter(g => !ev.startTime || !g.startTime || Math.abs(ev.startTime - g.startTime) < 18 * 3600_000)
      .sort((a, b) => Math.abs((a.startTime || 0) - (ev.startTime || 0)) - Math.abs((b.startTime || 0) - (ev.startTime || 0)));
    if (cands[0]) { cands[0].ours = ev; n++; }
  }
  // Trading-portal rows (content/portal-ids.js): "id + row text". A row matches a game when its
  // text names both teams (by nickname) and, if it shows a date, the game's date.
  const portal = Object.entries(oursLearned.portal || {});
  const dd = (ms) => { const [y, m, d] = new Intl.DateTimeFormat('en-CA', { timeZone: 'America/New_York' }).format(ms).split('-'); return `${d}-${m}-${y}`; };
  const hasWord = (text, w) => new RegExp(`\\b${w.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}\\b`, 'i').test(text);
  for (const g of games) {
    if (g.ours) continue;
    const nicks = [g.fd?.away || g.dk?.away, g.fd?.home || g.dk?.home].map(teamNick);
    const day = g.startTime ? dd(g.startTime) : null;
    const hits = portal.filter(([, v]) => nicks.every(nk => nk && hasWord(v.text, nk)))
      .filter(([, v]) => !day || !/\b\d{2}-\d{2}-\d{4}\b/.test(v.text) || v.text.includes(day))
      .sort((a, b) => Number(!!day && b[1].text.includes(day)) - Number(!!day && a[1].text.includes(day)) || b[1].at - a[1].at);
    if (hits[0]) { g.ours = { eventId: hits[0][0], name: hits[0][1].text, fromPortal: true }; n++; }
  }
  diag.ourGames = `${found.size} of our events found in the feed slate, ${portal.length} trading-portal rows read, ${n} matched to DK/FD games${errs.length ? ` · problems: ${uniq(errs).join('; ')}` : ''}`;
  light('OURS', n ? 'ok' : found.size ? 'warn' : 'bad', n ? `${n} games` : found.size ? 'games found, none matched' : 'no games yet (see Diagnostics)');
}
$('game').addEventListener('change', async () => { if (run) return; const g = games.find(x => x.key === $('game').value); if (g) await showGame(g); });

async function showGame(g) {
  $('ours-id').value = g.ours?.eventId || '';
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
  run = { game: g, busy: false, skipped: 0, nextId: (history.at(-1)?.id || 0) + 1, fdTabs: null, dkActive: null, dkPerSub: null, n: 0,
          oursId: $('ours-id').value.trim() || g.ours?.eventId || null, ourTypes: null, ourUnread: null };
  $('ours-id').disabled = true;
  if (g.fd) await findFdTabs(run);
  $('start').disabled = true; $('stop').disabled = false; $('game').disabled = true;
  worker.postMessage({ cmd: 'start', ms: settings.pollSeconds * 1000 });
});
$('stop').addEventListener('click', () => {
  worker.postMessage({ cmd: 'stop' });
  run = null; $('start').disabled = false; $('stop').disabled = true; $('game').disabled = false; $('ours-id').disabled = false;
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
    const [DK, FD, OURS] = await Promise.all([
      !g.dk ? Promise.resolve({ ok: false, error: 'no DK match for this game' })
        : isBackingOff('DK') ? Promise.resolve({ ok: false, error: 'DK backing off after an error' })
        : fetchBook('DK', async () => { const x = await dkQuotes(dkSite(), g.dk.eventId, subs); return { quotes: x.quotes, perSub: x.perSub }; }),
      !g.fd ? Promise.resolve({ ok: false, error: 'no FD match for this game' })
        : isBackingOff('FD') ? Promise.resolve({ ok: false, error: 'FD backing off after an error' })
        : !r.fdTabs?.length ? Promise.resolve({ ok: false, error: 'FanDuel has no player points for this game yet (preseason games usually have none)' })
        : fetchBook('FD', async () => ({ quotes: await fdQuotes(settings.fdState, g.fd.eventId, r.fdTabs) })),
      !r.oursId ? Promise.resolve({ ok: false, error: 'no event of ours for this game' })
        : fetchBook('OURS', async () => { const x = await ourQuotes(r.oursId); return { quotes: x.quotes, types: x.types, unread: x.unread }; }),
    ]);
    if (run !== r) return;   // stopped while waiting

    if (DK.perSub) {
      r.dkPerSub = { ...(r.dkPerSub || {}), ...DK.perSub };
      const good = Object.entries(DK.perSub).filter(([, v]) => typeof v === 'number' && v > 0).map(([k]) => k);
      if (subs.length === subIds().length) r.dkActive = good;   // learn from a full probe
      if (!DK.quotes.length) { DK.ok = false; DK.error = 'DK answered but had no player-points prices (check the subcategory ids)'; }
    }
    if (OURS.types) {
      r.ourTypes = OURS.types; r.ourUnread = OURS.unread;
      if (!OURS.quotes.length) { OURS.ok = false; OURS.error = 'our feed answered but had no player-points prices (see "Our market codes" in Diagnostics)'; }
    }
    const res = { DK, FD, OURS };
    const expected = [g.dk && 'DK', g.fd && r.fdTabs?.length && 'FD', r.oursId && 'OURS'].filter(Boolean);
    const al = alignTick(res, settings.alignToleranceMs, expected);
    const errors = {};
    for (const b of BOOKS) {
      if (!res[b].ok) errors[b] = res[b].error;
      else if (!al.used[b]) errors[b] = `answered ${res[b].at - al.firstAt} ms after the other book (limit ${settings.alignToleranceMs}): left out of this pull`;
    }
    const rows = buildRows(Object.fromEntries(BOOKS.map(b => [b, al.used[b] ? res[b].quotes : []])));
    const tick = {
      gameKey: g.key, game: g.name, id, t, aligned: al.aligned, spreadMs: al.spreadMs, used: al.used,
      at: Object.fromEntries(BOOKS.map(b => [b, res[b].at])), ms: Object.fromEntries(BOOKS.map(b => [b, res[b].ms])),
      counts: Object.fromEntries(BOOKS.map(b => [b, res[b].quotes?.length || 0])), errors, rows,
    };
    await saveTick(tick);
    history.push(tick);
    diag.lastTick = tick;

    for (const b of BOOKS) {
      if (al.used[b]) light(b, 'ok', `${res[b].ms} ms · ${tick.counts[b]} prices`);
      else light(b, res[b].ok ? 'warn' : 'bad', res[b].ok ? 'late this pull' : 'missing this pull');
      if (errors[b] && (b === 'OURS' ? r.oursId : g[b.toLowerCase()])) logErr(`pull #${id} ${b}: ${errors[b]}`);
    }
    const alignedN = history.filter(x => x.aligned).length;
    $('tickinfo').textContent = `Pull #${id} at ${etTime(t).slice(11)} ET · ${alignedN}/${history.length} aligned${r.skipped ? ` · ${r.skipped} skipped (book slower than ${settings.pollSeconds}s)` : ''}`;
    renderTable(); renderSelected(); renderDiag();
    if (settings.autoSheet && settings.sheetsUrl) sendNewTicks(g.key, true);
  } finally { r.busy = false; }
}

// ---------------------------------------------------------------- table
const fmtP = (p) => p == null ? '–' : `${(p * 100).toFixed(1)}%`;
const fmtG = (g) => g == null ? '–' : `${g > 0 ? '+' : ''}${g.toFixed(1)}`;
const odds = (b) => b ? `${b.over?.american ?? '–'} / ${b.under?.american ?? '–'}` : null;
const bigGap = (r) => Math.max(...['OURS_DK', 'OURS_FD', 'DK_FD'].map(k => Math.abs(r.gaps?.[k] ?? -1)));
function renderTable() {
  const tb = $('table').tBodies[0]; tb.textContent = '';
  const last = history.at(-1);
  $('latest-time').textContent = last ? `· pull #${last.id}, ${etTime(last.t).slice(11)} ET${last.aligned ? '' : ' (not aligned: a book was missing or late)'}` : '';
  $('empty').hidden = !!last?.rows.length;
  if (!last) return;
  const q = $('filter').value.trim().toLowerCase();
  const withPrices = BOOKS.filter(b => last.rows.some(r => r.books[b]));
  const multiOnly = $('both-only').checked && withPrices.length > 1;   // with one book in, this would hide everything
  $('both-note').textContent = withPrices.length === 1 ? `Only ${BOOK_NAME[withPrices[0]]} has prices this pull, so all of its lines are shown.` : '';
  let rows = last.rows.filter(r => (!q || r.player.toLowerCase().includes(q)) && (!multiOnly || Object.keys(r.books).length > 1));
  if ($('sort').value === 'gap') rows = rows.slice().sort((a, b) => bigGap(b) - bigGap(a));
  for (const r of rows) {
    const tr = document.createElement('tr'); if (r.key === selectedKey) tr.className = 'sel';
    const g = r.gaps || {};
    const cells = [r.player, marketLabel(r), odds(r.books.DK), odds(r.books.FD), odds(r.books.OURS),
      fmtP(r.books.DK?.p), fmtP(r.books.FD?.p), fmtP(r.books.OURS?.p), fmtG(g.OURS_DK), fmtG(g.OURS_FD), fmtG(g.DK_FD)];
    cells.forEach((c, i) => {
      const td = document.createElement('td'); td.textContent = c ?? '–';
      if (i >= 2) td.className = 'num';
      if (c == null || c === '–') td.classList.add('na');
      if (i >= 8) { const v = [g.OURS_DK, g.OURS_FD, g.DK_FD][i - 8]; if (v != null && Math.abs(v) >= 3) td.classList.add('big'); }
      tr.appendChild(td);
    });
    tr.addEventListener('click', () => { selectedKey = r.key; renderTable(); renderSelected(); });
    tb.appendChild(tr);
  }
  if (!rows.length) { $('empty').hidden = false; $('empty').textContent = multiOnly ? 'No line is offered by 2 or more books in this pull. Untick "Only lines 2+ books have" to see everything.' : 'No prices in this pull.'; }
}
['filter', 'both-only', 'sort'].forEach(id => $(id).addEventListener('input', renderTable));

// ---------------------------------------------------------------- charts
function legendFor(el, series) {
  el.textContent = '';
  for (const s of series) { const sp = document.createElement('span'); sp.style.setProperty('--c', s.color); sp.textContent = s.long; el.appendChild(sp); }
}
function renderSelected() {
  if (!selectedKey) {
    $('chart').textContent = ''; $('gapchart').textContent = ''; $('legend').textContent = ''; $('gaplegend').textContent = '';
    $('chart-title').textContent = 'Click a row below to graph it'; $('gap-panel').hidden = true; return;
  }
  const any = history.findLast(t => t.rows.some(r => r.key === selectedKey));
  const row = any?.rows.find(r => r.key === selectedKey);
  $('chart-title').textContent = row ? `${row.player} · ${marketLabel(row)}` : 'Line no longer offered';
  const rowsAt = history.map(t => ({ t, r: t.rows.find(x => x.key === selectedKey) }));
  const shown = SERIES.filter(s => rowsAt.some(({ r }) => r?.books[s.book]?.p != null));
  legendFor($('legend'), shown.length ? shown : SERIES);
  const points = rowsAt.map(({ t, r }) => {
    const values = {};
    for (const s of SERIES) { const b = r?.books[s.book]; values[s.book] = b?.p != null ? { p: b.p, over: b.over?.american, under: b.under?.american } : null; }
    return { t: t.t, id: t.id, aligned: t.aligned, values };
  });
  renderChart($('chart'), $('tooltip'), points, shown.length ? shown : SERIES);

  // our gap to each book, in percentage points (0 = same price); only pulls where both were in
  const gapShown = GAP_SERIES.filter(s => rowsAt.some(({ r }) => r?.gaps?.[s.book] != null));
  $('gap-panel').hidden = false;
  legendFor($('gaplegend'), gapShown.length ? gapShown : GAP_SERIES);
  const gpoints = rowsAt.map(({ t, r }) => {
    const values = {};
    for (const s of GAP_SERIES) { const v = r?.gaps?.[s.book]; values[s.book] = v != null ? { p: v / 100 } : null; }
    return { t: t.t, id: t.id, aligned: t.aligned, values };
  });
  renderChart($('gapchart'), $('gaptooltip'), gpoints, gapShown.length ? gapShown : GAP_SERIES, {
    clamp: false, zero: true,
    fmt: (v) => `${v > 0 ? '+' : ''}${(v * 100).toFixed(1)} pts`, axisFmt: (v) => `${v > 0 ? '+' : ''}${+v.toFixed(1)}`,
    tipFmt: (s, v) => `Ours − ${s.book === 'OURS_DK' ? 'DK' : 'FD'}: ${v.p > 0 ? '+' : ''}${(v.p * 100).toFixed(1)} pts`,
    empty: 'Needs our price and a book price on the same pull.',
  });
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

// ---------------------------------------------------------------- our feed test
$('ours-test').addEventListener('click', async () => {
  const id = $('ours-id').value.trim() || games.find(g => g.key === $('game').value)?.ours?.eventId;
  const box = $('ours-box'); box.hidden = false; box.open = true;
  if (!id) { $('ours-out').textContent = 'Type our event id in the box first.'; return; }
  $('ours-summary').textContent = '· asking…'; $('ours-out').textContent = '';
  const r = await testOurEvent(id);
  const L = [`Event id ${id}`, `Address: ${r.url}`, ...(r.tries || []).map(t => `   ${t}`)];
  if (!r.ok) {
    L.push('', `Problem: ${r.error}`);
    if (/HTTP 404/.test(r.error)) {
      L.push('', 'Our feed has no event with this id. Our feed uses its own event id, not Dolly\'s game id',
        '(Dolly ids look like 30 + the Betradar number, e.g. 3073863908).');
      if (/^30\d{7,}$/.test(id)) L.push('This one looks like a Dolly id.');
    }
    const evs = lastOurEvents.slice(0, 40);
    L.push('', evs.length ? 'Events found in our feed (use one of these ids):' : 'No events from our feed found yet. Open our sportsbook site\'s NBA page in this Chrome (no need to click a game), then press ↻ Games and Test ours again.');
    for (const e of evs) L.push(`   ${e.eventId}  ${e.name}  ${e.participants.map(p => p[0]).join(' / ')}`);
    const urls = (oursLearned.urls || []).filter(u => !/\/page\/event\/|\/cardpack\//.test(u)).slice(0, 15);
    if (urls.length) L.push('', 'Other content-feed addresses our sportsbook site asked for:', ...urls.map(u => `   ${decodeURIComponent(u).slice(0, 200)}`));
  }
  else {
    L.push('', `Game in the answer: ${r.event}`, `Markets: ${r.marketCount}   Player-points prices read: ${r.pointsPrices}`);
    if (r.sample.length) L.push(`   e.g. ${r.sample.map(q => `${q.player} ${q.kind === 'alt' ? `${q.line + 0.5}+` : `${q.side} ${q.line}`} ${q.american}`).join(' · ')}`);
    L.push('', 'Market codes in the answer:', ...Object.entries(r.types).sort().map(([k, v]) => `   ${k}  ${v}`));
    if (!r.marketCount) L.push('', `Top-level fields: ${r.topKeys.join(', ')}`);
    if (r.unread?.length) L.push('', `Points markets we could not read: ${JSON.stringify(r.unread).slice(0, 1500)}`);
  }
  $('ours-summary').textContent = r.ok ? `· ${r.pointsPrices} points prices read` : '· failed';
  $('ours-out').textContent = L.join('\n');
});
$('ours-save').addEventListener('click', () => {
  const f = ours.lastFeed;
  if (!f) { alert('Press "Test ours" first.'); return; }
  const a = document.createElement('a');
  a.href = URL.createObjectURL(new Blob([JSON.stringify({ url: f.url, at: new Date(f.at).toISOString(), tries: f.tries, body: f.text }, null, 1)], { type: 'application/json' }));
  a.download = `our-feed-${f.url.split('/').pop()}.json`; a.click();
});

// ---------------------------------------------------------------- boot
await loadSettings();
await loadLearned();
await loadGames();
if (games[0]) await showGame(games.find(g => g.key === $('game').value) || games[0]);
