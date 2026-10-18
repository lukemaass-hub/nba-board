import { fdGames, fdPointsTabs, fdQuotes, dkGames, dkQuotes, isBackingOff, setDkHost } from './lib/books.js';
import * as books from './lib/books.js';
import { sameGame, teamNick } from './lib/match.js';
import { tokenScore } from './lib/match.js';
import { BOOKS, alignTick, buildRows, oddsScale, oddsLabel, marketLabel, tickToRecords, toCsv, toTsv, CSV_HEADERS, mtTime } from './lib/compare.js';
import { gameRosters, teamOf } from './lib/rosters.js';
import { saveTick, ticksFor, saveAnomalies, anomaliesFor } from './lib/store.js';
import { findAnomalies, anomalyRows, anomalyRecord, ANOMALY_HEADERS } from './lib/anomaly.js';
import { renderChart } from './lib/chart.js';

// DK player-points subcategory ids are guesses until checked in a real browser (DK blocks
// non-browser traffic, so they couldn't be verified while building). Edit them in Settings.
const DEFAULTS = {
  pollSeconds: 15, alignToleranceMs: 2000, fdState: 'az', dkSite: 'US-CO-SB', dkLeague: '42648',
  dkGameSubcat: '4511', dkSubcats: '12488, 16413, 16477', dollyEnv: 'test', anomalyPct: 10, anomalyBookPct: 20,
};
const SERIES = [{ book: 'DK', name: 'DK', long: 'DraftKings', color: '#3987e5' }, { book: 'FD', name: 'FD', long: 'FanDuel', color: '#d95926' },
  { book: 'OURS', name: 'Ours', long: 'Ours (app price)', color: '#199e70' }];
import { DOLLY_ENVS, dollyEnv } from './lib/dolly-env.js';
const env = () => DOLLY_ENVS[dollyEnv(settings)];
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
  // Prod Dolly: ask Chrome for access first (must happen right on the click); Test: give prod access back
  const wantProd = e.target.elements.dollyEnv.value === 'prod';
  const prodOrigin = DOLLY_ENVS.prod.origin;
  if (wantProd && !(await chrome.permissions.request({ origins: [prodOrigin] }))) {
    e.target.elements.dollyEnv.value = 'test';
    $('saved').textContent = 'Prod Dolly was not allowed, so Test stays selected.';
  }
  if (!wantProd || e.target.elements.dollyEnv.value === 'test') await chrome.permissions.remove({ origins: [prodOrigin] }).catch(() => false);
  const f = e.target, s = {};
  for (const k of Object.keys(DEFAULTS)) { const i = f.elements[k]; s[k] = i.type === 'checkbox' ? i.checked : i.type === 'number' ? Number(i.value) : i.value.trim(); }
  s.pollSeconds = Math.max(5, s.pollSeconds || 15);
  settings = s; await chrome.storage.local.set({ settings });
  if (!$('saved').textContent) $('saved').textContent = run ? 'Saved. Press Stop then Start to use the new settings.' : 'Saved.';
  showEnv();
  if (env().label === 'PROD' || wantProd) $('saved').textContent += ' Reload the Dolly tab (F5) once so it is read.';
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
async function loadLearned() {
  ({ dkLearned: learned = learned } = await chrome.storage.local.get('dkLearned'));
  setDkHost(learned.host);
}
let relearnTimer = null;
chrome.storage.onChanged.addListener((ch) => {
  if (!ch.dkLearned) return;
  learned = ch.dkLearned.newValue || learned; setDkHost(learned.host); renderDiag();
  // new DK ids seen and DK has no games yet: reload the list (not while a game is running)
  if (!run && !games.some(g => g.dk)) { clearTimeout(relearnTimer); relearnTimer = setTimeout(loadGames, 3000); }
});

// ---------------------------------------------------------------- lights + diagnostics
function light(book, cls, text) { const l = $(`light-${book}`); l.className = `light ${cls}`; l.querySelector('b').textContent = text; }
function logErr(msg) { diag.errors.unshift(`${mtTime(Date.now())}  ${msg}`); diag.errors.length = Math.min(diag.errors.length, 30); renderDiag(); }
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
  lines.push(`\nOur prices (Dolly ${env().label} screen, App column): ${diag.dolly || 'not read yet'}`);
  if (diag.dollyMarkets?.length) lines.push(`   markets seen: ${diag.dollyMarkets.join(' · ')}`);
  for (const x of diag.dollySample || []) lines.push(`   e.g. ${x}`);
  if (run) {
    lines.push(`\nRunning: ${run.game.name}`);
    lines.push(`   FD event ${run.game.fd?.eventId ?? '—'}, tabs: ${run.fdTabs?.join(', ') || '—'}`);
    lines.push(`   DK event ${run.game.dk?.eventId ?? '— (no DK match)'}`);
    if (run.dkPerSub) for (const [k, v] of Object.entries(run.dkPerSub)) lines.push(`   DK subcategory ${k} → ${typeof v === 'number' ? `${v} prices` : v}`);
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
  games.sort((a, b) => (a.startTime || 0) - (b.startTime || 0));

  renderGameList();
  renderDiag();
}
// Games are listed for the day picked in the date box (Mountain Time); the box opens on today.
const mtDay = (ms) => new Intl.DateTimeFormat('en-CA', { timeZone: 'America/Denver' }).format(ms);
const tmt = new Intl.DateTimeFormat('en-US', { timeZone: 'America/Denver', hour: 'numeric', minute: '2-digit' });
function renderGameList() {
  const sel = $('game'), day = $('day').value || mtDay(Date.now());
  const keep = run?.game.key || sel.value;
  sel.textContent = '';
  const list = games.filter(g => g.startTime && mtDay(g.startTime) === day);
  if (!list.length) { const o = document.createElement('option'); o.value = ''; o.textContent = games.length ? 'No games on this day' : 'No games found: see Diagnostics'; sel.appendChild(o); }
  for (const g of list) {
    const o = document.createElement('option'); o.value = g.key;
    const books = [g.dk && 'DK', g.fd && 'FD'].filter(Boolean).join(' + ');
    o.textContent = `${tmt.format(g.startTime)} MT  ${g.name}  (${books})`;
    sel.appendChild(o);
  }
  if (list.some(g => g.key === keep)) sel.value = keep;
}
$('day').value = mtDay(Date.now());
$('day').addEventListener('change', async () => { renderGameList(); const g = games.find(x => x.key === $('game').value); if (g && !run) await showGame(g); });
$('refresh').addEventListener('click', loadGames);

// team buttons: All / away / home (players' teams from ESPN rosters)
let rosters = [], teamPick = 'ALL';
const teamFn = (player) => teamOf(player, rosters);
function renderTeamButtons() {
  const box = $('teams'); box.textContent = '';
  for (const t of [{ abbr: 'ALL', name: 'All' }, ...rosters]) {
    const b = document.createElement('button'); b.type = 'button'; b.textContent = t.abbr === 'ALL' ? 'All' : t.name;
    b.className = t.abbr === teamPick ? 'on' : '';
    b.addEventListener('click', () => { teamPick = t.abbr; renderTeamButtons(); renderTable(); });
    box.appendChild(b);
  }
}
async function loadRosters(g) {
  rosters = []; teamPick = 'ALL'; renderTeamButtons();
  try { rosters = await gameRosters(g.fd?.away || g.dk?.away, g.fd?.home || g.dk?.home); }
  catch (e) { logErr(`team rosters (ESPN): ${e.message || e}`); }
  renderTeamButtons(); renderTable();
}

async function showGame(g) {
  loadRosters(g);
  anomalies = await anomaliesFor(g.key); renderAnomalies();
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

// Our prices: ask the open Dolly Market Manager tab(s) to read the screen (content/dolly-props.js).
// The tab for this game is the one whose teams match (the MLB suite's tokenScore), or the only one open.
async function readDolly(g) {
  const E = env();
  if (!(await chrome.permissions.contains({ origins: [E.origin] }))) return { ok: false, error: `Dolly ${E.name} is selected but not allowed: open Settings and click Save settings` };
  const tabs = (await chrome.tabs.query({ url: E.origin })).filter(t => /market-manager/.test(t.url || ''));
  if (!tabs.length) return { ok: false, error: `no Dolly ${E.name} Market Manager tab open` };
  const sent = Date.now();
  // ask every frame of each Dolly tab (the market table may sit in a frame); per tab keep the frame that read most
  const ask = (tabId, frameId) => new Promise(res => chrome.tabs.sendMessage(tabId, { type: 'DOLLY_READ' }, { frameId }, (r) => res(chrome.runtime.lastError ? null : r)));
  const answers = await Promise.all(tabs.map(async (t) => {
    const frames = (await chrome.webNavigation.getAllFrames({ tabId: t.id }).catch(() => null)) || [{ frameId: 0 }];
    const rs = (await Promise.all(frames.map(f => ask(t.id, f.frameId)))).filter(r => r?.ok);
    rs.sort((a, b) => b.quotes.length - a.quotes.length);
    const top = rs.find(r => r.frame === 'top');
    return rs[0] ? { ...rs[0], teams: rs[0].teams?.length ? rs[0].teams : top?.teams, url: top?.url || rs[0].url } : null;
  }));
  const ok = answers.filter(a => a?.ok);
  if (!ok.length) return { ok: false, error: 'Dolly tab did not answer (reload the Dolly tab once after installing the extension)' };
  const want = [g.fd?.away || g.dk?.away, g.fd?.home || g.dk?.home];
  const score = (a) => a.teams?.length === 2 ? Math.min(...want.map(w => Math.max(...a.teams.map(t => tokenScore(w, t))))) : 0;
  const best = ok.length === 1 ? ok[0] : ok.slice().sort((a, b) => score(b) - score(a))[0];
  if (ok.length > 1 && score(best) < 0.5) return { ok: false, error: `${ok.length} Dolly tabs open and none shows ${want.join(' @ ')}` };
  const mine = chrome.runtime.getManifest().version;
  if (best.version !== mine) return { ok: false, error: `the Dolly tab is still running an older copy of the extension (${best.version || 'before 0.14.1'}). Reload the Dolly tab (F5).` };
  diag.dolly = `${tabs.length} ${E.label} Market Manager tab(s); reading ${best.teams?.join(' v ') || best.url} · ${best.rows} selection rows seen, ${best.quotes.length} App prices read in ${best.readMs ?? '?'} ms${best.frame && best.frame !== 'top' ? ' (in a frame)' : ''}${best.hidden ? ' · ⚠ Dolly tab is hidden: keep it in its own window so its prices keep updating' : ''}`;
  diag.dollySample = best.sample || [];
  diag.dollyMarkets = best.markets || [];
  return { ok: true, at: best.at || Date.now(), ms: Date.now() - sent, quotes: best.quotes };
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
    const [DK, FD, DOLLY] = await Promise.all([
      !g.dk ? Promise.resolve({ ok: false, error: 'no DK match for this game' })
        : isBackingOff('DK') ? Promise.resolve({ ok: false, error: 'DK backing off after an error' })
        : fetchBook('DK', async () => { const x = await dkQuotes(dkSite(), g.dk.eventId, subs); return { quotes: x.quotes, perSub: x.perSub }; }),
      !g.fd ? Promise.resolve({ ok: false, error: 'no FD match for this game' })
        : isBackingOff('FD') ? Promise.resolve({ ok: false, error: 'FD backing off after an error' })
        : !r.fdTabs?.length ? Promise.resolve({ ok: false, error: 'FanDuel has no player points for this game yet (preseason games usually have none)' })
        : fetchBook('FD', async () => ({ quotes: await fdQuotes(settings.fdState, g.fd.eventId, r.fdTabs) })),
      readDolly(g).catch(e => ({ ok: false, error: String(e.message || e) })),
    ]);
    if (run !== r) return;   // stopped while waiting

    if (DK.perSub) {
      r.dkPerSub = { ...(r.dkPerSub || {}), ...DK.perSub };
      const good = Object.entries(DK.perSub).filter(([, v]) => typeof v === 'number' && v > 0).map(([k]) => k);
      if (subs.length === subIds().length) r.dkActive = good;   // learn from a full probe
      if (!DK.quotes.length) { DK.ok = false; DK.error = 'DK answered but had no player-points prices (check the subcategory ids)'; }
    }
    const OURS = !DOLLY.ok ? DOLLY : DOLLY.quotes.length ? DOLLY
      : { ok: false, at: DOLLY.at, error: 'Dolly screen showed no player-points App prices (expand ALTERNATE PLAYER POINTS / PLAYER TOTAL POINTS in Dolly; see Diagnostics)' };
    const res = { DK, FD, OURS };
    const expected = [g.dk && 'DK', g.fd && r.fdTabs?.length && 'FD', DOLLY.ok && 'OURS'].filter(Boolean);
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
    // anomalies: our odds vs the DK/FD average, same pull only
    // every pull: each side that is off the market gets its own new row
    const newRows = anomalyRows(findAnomalies(rows, Number(settings.anomalyPct) || 10, Number(settings.anomalyBookPct) || 20), tick, teamFn);
    lastAnomPull = { id, n: newRows.length };
    if (newRows.length) { await saveAnomalies(newRows); anomalies.unshift(...newRows); }
    renderAnomalies();
    diag.lastTick = tick;

    for (const b of BOOKS) {
      if (al.used[b]) light(b, 'ok', `${res[b].ms} ms · ${tick.counts[b]} prices`);
      else light(b, res[b].ok ? 'warn' : 'bad', res[b].ok ? 'late this pull' : 'missing this pull');
      if (errors[b] && (b === 'OURS' || g[b.toLowerCase()])) logErr(`pull #${id} ${b}: ${errors[b]}`);
    }
    const alignedN = history.filter(x => x.aligned).length;
    $('tickinfo').textContent = `Pull #${id} at ${mtTime(t).slice(11)} MT · ${alignedN}/${history.length} aligned${r.skipped ? ` · ${r.skipped} skipped (book slower than ${settings.pollSeconds}s)` : ''}`;
    renderTable(); renderSelected(); renderDiag();
  } finally { r.busy = false; }
}

// ---------------------------------------------------------------- table
// one price per cell: "over / under" for O/U lines, just the price for N+ lines
const odds = (b, kind) => !b ? null : kind === 'alt' ? (b.over?.american ?? null) : `${b.over?.american ?? '–'} / ${b.under?.american ?? '–'}`;

// Every line seen in this game, each book's odds from the last pull that had them. A line that
// came down (a player hit it, so Dolly / the book pulled it) stays, greyed, with when it was last seen.
function mergedRows() {
  const m = new Map();
  for (const t of history) for (const r of t.rows) {
    const cur = m.get(r.key) || { key: r.key, player: r.player, kind: r.kind, line: r.line, books: {}, seen: {} };
    for (const [b, v] of Object.entries(r.books)) { cur.books[b] = v; cur.seen[b] = t.t; }
    cur.diff = r.diff ?? cur.diff;
    m.set(r.key, cur);
  }
  return [...m.values()];
}

function renderTable() {
  const tb = $('table').tBodies[0]; tb.textContent = '';
  const last = history.at(-1);
  $('latest-time').textContent = last ? `· pull #${last.id}, ${mtTime(last.t).slice(11)} MT${last.aligned ? '' : ' (not aligned: a book was missing or late)'}` : '';
  const all = mergedRows();
  $('empty').hidden = !!all.length;
  if (!last) return;
  const q = $('filter').value.trim().toLowerCase();
  const withPrices = BOOKS.filter(b => last.rows.some(r => r.books[b]));
  const multiOnly = $('both-only').checked && withPrices.length > 1;   // with one book in, this would hide everything
  $('both-note').textContent = withPrices.length === 1 ? `Only ${BOOK_NAME[withPrices[0]]} has prices this pull, so all of its lines are shown.` : '';
  let rows = all.filter(r => (!q || r.player.toLowerCase().includes(q)) && (!multiOnly || Object.keys(r.books).length > 1)
    && (teamPick === 'ALL' || teamFn(r.player) === teamPick));
  // default: player A-Z, then line lowest first; or biggest difference between ours and the books
  rows.sort($('sort').value === 'gap' ? (a, b) => (b.diff ?? -1) - (a.diff ?? -1)
    : (a, b) => a.player.localeCompare(b.player) || a.line - b.line || a.kind.localeCompare(b.kind));
  for (const r of rows) {
    const tr = document.createElement('tr'); if (r.key === selectedKey) tr.className = 'sel';
    const team = teamFn(r.player);
    const cells = [[`${r.player}${team ? `  ·  ${team}` : ''}`], [marketLabel(r)], ...['DK', 'FD', 'OURS'].map(b => [odds(r.books[b], r.kind), b])];
    cells.forEach(([c, book], i) => {
      const td = document.createElement('td'); td.textContent = c ?? '–';
      if (i >= 2) td.className = 'num';
      if (c == null) td.classList.add('na');
      if (book && c != null && r.seen[book] < last.t) {   // not in the latest pull: came down
        td.classList.add('gone'); td.title = `No longer offered. Last seen ${mtTime(r.seen[book]).slice(11)} MT`;
        td.textContent = `${c}  (off ${tmt.format(r.seen[book])})`;
      }
      tr.appendChild(td);
    });
    tr.addEventListener('click', () => { selectedKey = r.key; renderTable(); renderSelected(); });
    tb.appendChild(tr);
  }
  if (!rows.length) { $('empty').hidden = false; $('empty').textContent = multiOnly ? 'No line is offered by 2 or more books. Untick "Only lines 2+ books have" to see everything.' : 'No lines for this filter.'; }
}
['filter', 'both-only', 'sort'].forEach(id => $(id).addEventListener('input', renderTable));

// ---------------------------------------------------------------- anomalies tab
let anomalies = [];
const tsec = new Intl.DateTimeFormat('en-US', { timeZone: 'America/Denver', hour: 'numeric', minute: '2-digit', second: '2-digit' });
const LARGE = 15;   // % off: "large"
let lastAnomPull = null;
const SHOW_MAX = 500;   // rows drawn on screen (the CSV has all of them)
function renderAnomalies() {
  const n = anomalies.length;
  $('tab-anoms').textContent = `Anomalies (${n})`;
  const tb = $('anoms').tBodies[0]; tb.textContent = '';
  $('anoms-empty').hidden = !!n;
  const thr = Number(settings.anomalyPct) || 10, bthr = Number(settings.anomalyBookPct) || 20;
  $('anoms-note').textContent = `A new row every pull for each line where our odds are ${thr}%+ off the DraftKings/FanDuel average, or ${bthr}%+ off either book on its own (by implied chance, same pull only). Newest first. Red = ${LARGE}%+ off; white = flagged but under ${LARGE}%.`
    + (lastAnomPull ? ` Last pull #${lastAnomPull.id}: ${lastAnomPull.n} flagged.` : '') + (n > SHOW_MAX ? ` Showing the newest ${SHOW_MAX} of ${n}; Export has all.` : '');
  const f = (v) => v == null ? '–' : `${v > 0 ? '+' : ''}${v.toFixed(1)}%`;
  for (const e of anomalies.slice(0, SHOW_MAX)) {
    const tr = document.createElement('tr');
    if (Math.abs(e.size) >= LARGE) tr.className = 'large';
    // over/under lines say which side in the market; N+ lines are always the over
    const market = e.kind === 'ou' ? `${marketLabel(e)} ${e.side === 'over' ? 'Over' : 'Under'}` : marketLabel(e);
    const cells = [tsec.format(e.t), `${e.player}${e.team ? `  ·  ${e.team}` : ''}`, market, e.why || '',
      e.ours, e.dk, e.fd, e.avg, f(e.pct), f(e.pctDk), f(e.pctFd)];
    cells.forEach((c, i) => { const td = document.createElement('td'); td.textContent = c ?? '–'; if (i >= 4) td.className = 'num'; tr.appendChild(td); });
    tr.title = 'Click to graph this line';
    tr.addEventListener('click', () => { selectedKey = e.key.replace(/\|(over|under)$/, ''); showTab('live'); renderTable(); renderSelected(); });
    tb.appendChild(tr);
  }
}
function showTab(t) {
  $('view-live').hidden = t !== 'live'; $('view-anoms').hidden = t !== 'anoms';
  $('tab-live').classList.toggle('on', t === 'live'); $('tab-anoms').classList.toggle('on', t === 'anoms');
  if (t === 'live') renderSelected();
}
$('tab-live').addEventListener('click', () => showTab('live'));
$('tab-anoms').addEventListener('click', () => showTab('anoms'));
$('anoms-csv').addEventListener('click', async () => {
  const list = await anomaliesFor(currentGameKey());
  if (!list.length) { alert('No anomalies for this game yet.'); return; }
  const cell = (v) => { const t = String(v ?? ''); return /[",\n]/.test(t) ? `"${t.replace(/"/g, '""')}"` : t; };
  const csv = [ANOMALY_HEADERS, ...list.map(e => anomalyRecord(e, marketLabel))].map(r => r.map(cell).join(',')).join('\n') + '\n';
  const a = document.createElement('a');
  a.href = URL.createObjectURL(new Blob([csv], { type: 'text/csv' }));
  a.download = `prop-compare_anomalies_${list[0].game.replace(/[^A-Za-z0-9]+/g, '-')}.csv`;
  a.click(); setTimeout(() => URL.revokeObjectURL(a.href), 5000);
});

// ---------------------------------------------------------------- charts
function legendFor(el, series) {
  el.textContent = '';
  for (const s of series) { const sp = document.createElement('span'); sp.style.setProperty('--c', s.color); sp.textContent = s.long; el.appendChild(sp); }
}
function renderSelected() {
  if (!selectedKey) { $('chart').textContent = ''; $('legend').textContent = ''; $('chart-title').textContent = 'Click a row below to graph it'; return; }
  const row = mergedRows().find(r => r.key === selectedKey);
  $('chart-title').textContent = row ? `${row.player} · ${marketLabel(row)} · over odds` : 'Line no longer offered';
  const rowsAt = history.map(t => ({ t, r: t.rows.find(x => x.key === selectedKey) }));
  const shown = SERIES.filter(s => rowsAt.some(({ r }) => r?.books[s.book]?.over?.american));
  legendFor($('legend'), shown.length ? shown : SERIES);
  // American odds on one continuous scale (oddsScale), labelled back as American odds
  const points = rowsAt.map(({ t, r }) => {
    const values = {};
    for (const s of SERIES) { const b = r?.books[s.book]; const v = oddsScale(b?.over?.american); values[s.book] = v != null ? { p: v / 100, over: b.over.american, under: b.under?.american } : null; }
    return { t: t.t, id: t.id, aligned: t.aligned, values };
  });
  renderChart($('chart'), $('tooltip'), points, shown.length ? shown : SERIES, {
    clamp: false, fmt: (v) => oddsLabel(v * 100), axisFmt: (v) => oddsLabel(v),
    tipFmt: (s, v) => `${s.name}: over ${v.over ?? '–'}${v.under ? ` · under ${v.under}` : ''}`,
  });
}
window.addEventListener('resize', () => renderSelected());

// ---------------------------------------------------------------- export
function currentGameKey() { return run?.game.key || $('game').value; }
$('csv').addEventListener('click', async () => {
  const key = currentGameKey(); const ticks = await ticksFor(key);
  if (!ticks.length) { alert('Nothing saved for this game yet.'); return; }
  const csv = toCsv(ticks.flatMap(t => tickToRecords(t, teamFn)));
  const a = document.createElement('a');
  a.href = URL.createObjectURL(new Blob([csv], { type: 'text/csv' }));
  a.download = `prop-compare_${ticks[0].game.replace(/[^A-Za-z0-9]+/g, '-')}_${mtTime(ticks[0].t).slice(0, 10).replace(/\//g, '-')}.csv`;
  a.click(); setTimeout(() => URL.revokeObjectURL(a.href), 5000);
});

// New Google Sheet: every pull of this game is copied (tab-separated) and a blank sheet opens
// (sheets.new, in the user's own Google account); one Ctrl+V fills it. Creating the sheet with no
// paste at all would need a Google sign-in app registered for the extension.
$('sheet').addEventListener('click', async () => {
  const key = currentGameKey(); const ticks = await ticksFor(key);
  if (!ticks.length) { alert('Nothing saved for this game yet.'); return; }
  await navigator.clipboard.writeText(toTsv(ticks.flatMap(t => tickToRecords(t, teamFn))));
  window.open('https://sheets.new', '_blank');
  const btn = $('sheet'); btn.textContent = 'Copied: press Ctrl+V in the new sheet';
  setTimeout(() => { btn.textContent = 'New Google Sheet'; }, 8000);
});

// ---------------------------------------------------------------- boot
$('version').textContent = `version ${chrome.runtime.getManifest().version}`;
function showEnv() {
  const L = env().label;
  $('env-label').textContent = L; $('env-light').textContent = L;
  document.body.classList.toggle('prod', L === 'PROD');
}
await loadSettings();
showEnv();
await loadLearned();
await loadGames();
{ const g = games.find(x => x.key === $('game').value); if (g) await showGame(g); }
