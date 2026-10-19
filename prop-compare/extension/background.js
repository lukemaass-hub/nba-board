import { DOLLY_ENVS, dollyEnv } from './lib/dolly-env.js';

// Clicking the toolbar icon opens the dashboard. All polling happens in the dashboard tab
// itself, so closing that tab stops every request to the books.
chrome.action.onClicked.addListener(() => chrome.tabs.create({ url: chrome.runtime.getURL('dashboard.html') }));

// ---------------------------------------------------------------- learn DraftKings ids
// DK's id numbers (league, subcategory, site) can't be checked from outside a browser, and
// guesses go stale. So we watch the requests DraftKings' OWN page makes while the user has
// a DK tab open (read-only: nothing is blocked or changed) and save the ids it uses. Opening
// a game's Player Points tab on DraftKings once is enough.
const learn = async (details) => {
  // only DraftKings' own page: not background requests, not our dashboard (it is a tab too)
  if (details.tabId < 0 || !/^https:\/\/([a-z0-9-]+\.)*draftkings\.com$/.test(details.initiator || '')) return;
  let u; try { u = new URL(details.url); } catch { return; }
  if (!/\/api\//.test(u.pathname)) return;   // keep every API URL (diagnostics), learn ids from sportscontent ones
  const site = (u.pathname.match(/\/sites\/([^/]+)\//) || [])[1] || null;
  const tv = (u.searchParams.get('templateVars') || '').split(',');
  const q = `${u.searchParams.get('marketsQuery') || ''} ${u.searchParams.get('eventsQuery') || ''}`;
  const subs = [...q.matchAll(/(?:subCategoryId eq|s\/Id eq) '(\d+)'/g)].map(m => m[1]);
  const leagues = [...q.matchAll(/leagueId eq '(\d+)'/g)].map(m => m[1]);
  let eventId = null, shown = null;   // shown = the subcategory this request is FOR (the tab on screen)
  if (/\/eventSubcategory\//.test(u.pathname)) { eventId = tv[0]; shown = tv[1] || null; if (shown) subs.push(shown); }
  if (/\/leagueSubcategory\//.test(u.pathname) && tv[0]) { leagues.push(tv[0]); if (new Set(subs).size === 1) shown = subs[0]; }

  const { dkLearned: L = { host: null, site: null, leagues: {}, subs: {}, events: {}, urls: [] } } = await chrome.storage.local.get('dkLearned');
  if (/\/api\/sportscontent\//.test(u.pathname)) { L.host = u.host; if (site) L.site = site; }
  for (const l of leagues) L.leagues[l] = Date.now();
  // remember which page each subcategory came from ("player-points / points"), from the tab's own URL
  let page = '', name = null;
  try {
    const tab = await chrome.tabs.get(details.tabId);
    const tu = new URL(tab.url);
    const onEvent = /\/event\//.test(tu.pathname);
    if (shown && (onEvent ? /eventSubcategory/.test(u.pathname) : /leagueSubcategory/.test(u.pathname)))
      page = [tu.searchParams.get('category'), tu.searchParams.get('subcategory')].filter(Boolean).join(' / ');
    const slug = (tu.pathname.match(/\/event\/([^/]+)\/\d+/) || [])[1];
    if (slug) name = decodeURIComponent(slug).split('-').filter(Boolean).map(w => w === '@' ? '@' : w[0].toUpperCase() + w.slice(1)).join(' ');
  } catch { /* tab closed */ }
  for (const s of subs) L.subs[s] = { at: Date.now(), page: (s === shown && page) || L.subs[s]?.page || '' };
  if (eventId) L.events[eventId] = { at: Date.now(), name: name || L.events[eventId]?.name || null };
  L.urls = [details.url, ...L.urls.filter(x => x !== details.url)].slice(0, 15);
  await chrome.storage.local.set({ dkLearned: L });
};
// serialize writes so two requests in the same instant don't overwrite each other
let chain = Promise.resolve();
chrome.webRequest.onBeforeRequest.addListener(
  (d) => { chain = chain.then(() => learn(d)).catch(() => {}); },
  { urls: ['https://*.draftkings.com/*'], types: ['xmlhttprequest'] },
);

// ---------------------------------------------------------------- Dolly reader: selected environment only
// The read-only Dolly reader (content/dolly-props.js) is loaded ONLY into the Dolly environment
// chosen in Settings. With Test selected nothing is loaded into prod Dolly (and the extension holds
// no prod permission at all); prod needs the user to pick it and grant it.
let syncing = Promise.resolve();
async function syncDollyScript() {
  const { settings } = await chrome.storage.local.get('settings');
  const env = dollyEnv(settings), origin = DOLLY_ENVS[env].origin;
  await chrome.scripting.unregisterContentScripts({ ids: ['dolly-reader'] }).catch(() => {});
  if (!(await chrome.permissions.contains({ origins: [origin] }))) return;   // prod chosen but not granted: load nothing
  await chrome.scripting.registerContentScripts([{ id: 'dolly-reader', matches: [origin], js: ['content/dolly-props.js'],
    allFrames: true, runAt: 'document_idle', persistAcrossSessions: true }]);
}
const resync = () => { syncing = syncing.then(syncDollyScript).catch(() => {}); };
chrome.runtime.onInstalled.addListener(resync);
chrome.runtime.onStartup.addListener(resync);
chrome.storage.onChanged.addListener((ch) => { if (ch.settings) resync(); });
chrome.permissions.onAdded.addListener(resync);
chrome.permissions.onRemoved.addListener(resync);

// ---------------------------------------------------------------- Dolly expected minutes -> nba-board repo
// The Dolly reader sends the Rosters screen's Expected Mins (DOLLY_ROSTERS). We keep the latest per player and
// save them as expected_minutes.json in the nba-board GitHub repo (the daily report reads it). The GitHub key is
// the user's own, limited to that repo, typed into Settings; it never leaves this browser except to GitHub.
const EM_KEY = 'expectedMins', UPLOAD_EVERY_MS = 10 * 60_000;
async function githubSave(players) {
  const { settings = {} } = await chrome.storage.local.get('settings');
  const token = (settings.githubToken || '').trim(), repo = (settings.githubRepo || 'lukemaass-hub/nba-board').trim();
  if (!token) return { ok: false, error: 'no GitHub key in Settings' };
  const url = `https://api.github.com/repos/${repo}/contents/expected_minutes.json`;
  const h = { Authorization: `Bearer ${token}`, Accept: 'application/vnd.github+json', 'X-GitHub-Api-Version': '2022-11-28' };
  const cur = await fetch(`${url}?ref=main`, { headers: h, credentials: 'omit' });
  const sha = cur.ok ? (await cur.json()).sha : undefined;
  const body = { env: 'uat', updated_at: new Date().toISOString(), source: 'Dolly Rosters screen (prop-compare extension)', players };
  const text = JSON.stringify(body, null, 1) + '\n';
  const bytes = new TextEncoder().encode(text);
  let bin = '';
  for (let i = 0; i < bytes.length; i += 0x8000) bin += String.fromCharCode(...bytes.subarray(i, i + 0x8000));   // chunks: big files overflow a single call
  const content = btoa(bin);
  const r = await fetch(url, { method: 'PUT', headers: h, credentials: 'omit',
    body: JSON.stringify({ message: `Dolly expected minutes (${players.length} players)`, content, sha, branch: 'main' }) });
  return r.ok ? { ok: true } : { ok: false, error: `GitHub HTTP ${r.status}: ${(await r.text()).slice(0, 160)}` };
}
let emChain = Promise.resolve();
async function onRosters(msg) {
  const { [EM_KEY]: S = { players: {}, lastUpload: 0, status: '' } } = await chrome.storage.local.get(EM_KEY);
  const at = new Date(msg.at || Date.now()).toISOString();
  for (const p of msg.players) S.players[`${p.teamName}|${p.name}`] = { name: p.name, teamName: p.teamName, expected: p.expected,
    game_date: msg.gameDate || null, fixture: msg.fixtureId || null, at };
  const cutoff = Date.now() - 3 * 86400_000;   // keep three days
  for (const [k, p] of Object.entries(S.players)) if (Date.parse(p.at) < cutoff) delete S.players[k];
  S.lastRead = Date.now(); S.dirty = true;
  if (Date.now() - (S.lastUpload || 0) >= UPLOAD_EVERY_MS) {
    const r = await githubSave(Object.values(S.players)).catch(e => ({ ok: false, error: String(e.message || e) }));
    S.status = r.ok ? `saved ${Object.keys(S.players).length} players to GitHub` : r.error;
    if (r.ok) { S.lastUpload = Date.now(); S.dirty = false; }
  }
  await chrome.storage.local.set({ [EM_KEY]: S });
}
chrome.runtime.onMessage.addListener((msg, sender) => {
  if (msg?.type !== 'DOLLY_ROSTERS' || !Array.isArray(msg.players)) return false;
  emChain = emChain.then(() => onRosters(msg)).catch(() => {});
  return false;
});
// anything read but not yet saved goes out within the next 10 minutes even if Dolly stops sending
chrome.alarms.create('em-upload', { periodInMinutes: 10 });
chrome.alarms.onAlarm.addListener((a) => {
  if (a.name !== 'em-upload') return;
  emChain = emChain.then(async () => {
    const { [EM_KEY]: S } = await chrome.storage.local.get(EM_KEY);
    if (!S?.dirty) return;
    const r = await githubSave(Object.values(S.players)).catch(e => ({ ok: false, error: String(e.message || e) }));
    S.status = r.ok ? `saved ${Object.keys(S.players).length} players to GitHub` : r.error;
    if (r.ok) { S.lastUpload = Date.now(); S.dirty = false; }
    await chrome.storage.local.set({ [EM_KEY]: S });
  }).catch(() => {});
});

// ---------------------------------------------------------------- one-time capture (for the hands-off version)
// To fetch every game's Rosters without the screen open, we need to know which addresses Dolly's own Rosters
// screen loads. While the user has TEST Dolly open, record those addresses (only the test host this extension is
// allowed on). The dashboard's "Capture Dolly data" button saves them, plus their answers, to a file for review.
chrome.webRequest.onBeforeRequest.addListener((d) => {
  if (d.tabId < 0 || /^chrome-extension:/.test(d.initiator || '')) return;
  if (/\.(js|css|png|jpe?g|svg|woff2?|ico|map)(\?|$)/i.test(d.url)) return;
  let body = null;
  try { if (d.requestBody?.raw?.[0]?.bytes) body = new TextDecoder().decode(d.requestBody.raw[0].bytes).slice(0, 4000); } catch { /* binary */ }
  chrome.storage.local.get('dollySeen').then(({ dollySeen = [] }) => {
    const rec = { at: Date.now(), method: d.method, url: d.url, body, type: d.type };
    chrome.storage.local.set({ dollySeen: [rec, ...dollySeen.filter(x => !(x.url === d.url && x.method === d.method))].slice(0, 60) });
  });
}, { urls: ['https://dolly.uat.oddsfactorytrading.bet/*'], types: ['xmlhttprequest'] }, ['requestBody']);
