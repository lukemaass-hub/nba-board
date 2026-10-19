// NBA board: Dolly expected minutes -> expected_minutes.json in the nba-board repo (read by the daily email).
// ---------------------------------------------------------------- Dolly expected minutes -> nba-board repo
// content.js sends the Rosters screen's Expected Mins (DOLLY_ROSTERS). We keep the latest per player and
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
  const body = { env: 'uat', updated_at: new Date().toISOString(), source: 'Dolly Rosters screen (dolly-minutes extension)', players };
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
chrome.runtime.onMessage.addListener((msg, _s, sendResponse) => {
  if (msg?.type !== 'EM_SAVE_NOW') return false;
  emChain = emChain.then(async () => {
    const { [EM_KEY]: S } = await chrome.storage.local.get(EM_KEY);
    if (!S) return;
    const r = await githubSave(Object.values(S.players)).catch(e => ({ ok: false, error: String(e.message || e) }));
    S.status = r.ok ? `saved ${Object.keys(S.players).length} players to GitHub` : r.error;
    if (r.ok) { S.lastUpload = Date.now(); S.dirty = false; }
    await chrome.storage.local.set({ [EM_KEY]: S });
  }).catch(() => {}).finally(() => sendResponse({ ok: true }));
  return true;
});
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
