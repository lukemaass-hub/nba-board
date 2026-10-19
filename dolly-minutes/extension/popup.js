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
chrome.storage.onChanged.addListener(show);
show();
