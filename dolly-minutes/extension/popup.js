const $ = (id) => document.getElementById(id);
const t = (ms) => ms ? new Date(ms).toLocaleTimeString('en-US', { timeZone: 'America/Denver' }) + ' MT' : 'never';
async function show() {
  const { settings = {}, expectedMins: S } = await chrome.storage.local.get(['settings', 'expectedMins']);
  $('repo').value = settings.githubRepo || 'lukemaass-hub/nba-board';
  $('token').placeholder = settings.githubToken ? 'saved (type to replace)' : 'github_pat_…';
  $('status').textContent = !settings.githubToken ? 'Add the GitHub key below, then open a Rosters screen in test Dolly.'
    : !S ? 'Waiting for a Rosters screen in test Dolly.'
    : `${Object.keys(S.players).length} players kept (last 3 days)\nLast read: ${t(S.lastRead)}\nLast saved to GitHub: ${t(S.lastUpload)}${S.status ? `\n${S.status}` : ''}`;
}
$('save').addEventListener('click', async () => {
  const { settings = {} } = await chrome.storage.local.get('settings');
  if ($('token').value.trim()) settings.githubToken = $('token').value.trim();
  settings.githubRepo = $('repo').value.trim() || 'lukemaass-hub/nba-board';
  await chrome.storage.local.set({ settings }); $('token').value = ''; show();
});
$('now').addEventListener('click', async () => { $('status').textContent = 'Saving…'; await chrome.runtime.sendMessage({ type: 'EM_SAVE_NOW' }); show(); });
$('capture').addEventListener('click', async () => {
  const btn = $('capture'); btn.textContent = 'Capturing…';
  const { dollySeen = [] } = await chrome.storage.local.get('dollySeen');
  const recent = dollySeen.filter(x => Date.now() - x.at < 30 * 60_000).slice(0, 40);
  const requests = await Promise.all(recent.map(async (x) => {
    if (x.method !== 'GET' && !x.body) return { ...x, answer: '(not repeated: no body recorded)' };
    try {
      const r = await fetch(x.url, { method: x.method, body: x.method === 'GET' ? undefined : x.body, credentials: 'include',
        headers: x.method === 'GET' ? {} : { 'content-type': 'application/json' } });
      return { ...x, status: r.status, answer: (await r.text()).slice(0, 200000) };
    } catch (e) { return { ...x, answer: `(failed: ${e.message || e})` }; }
  }));
  const a = document.createElement('a');
  a.href = URL.createObjectURL(new Blob([JSON.stringify({ captured: new Date().toISOString(), env: 'uat', requests }, null, 1)], { type: 'application/json' }));
  a.download = `dolly-capture-${new Date().toISOString().slice(0, 10)}.json`; a.click();
  btn.textContent = `Saved ${requests.length} requests`;
});
chrome.storage.onChanged.addListener(show);
show();
