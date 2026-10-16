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

// ---------------------------------------------------------------- learn OUR feed ids
// Same idea for our own sportsbook: while the user browses it, note the slate ("cardpack")
// requests it makes (their paths + query decode from the URL, exactly as the MLB suite builds
// them) and the event pages it opens. The dashboard uses these to find tonight's NBA games.
const learnOurs = async (details) => {
  if (details.tabId < 0 || /^chrome-extension:/.test(details.initiator || '')) return;
  let u; try { u = new URL(details.url); } catch { return; }
  const { oursLearned: O = { cardpacks: [], events: {}, query: null, urls: [] } } = await chrome.storage.local.get('oursLearned');
  let tabUrl = '';
  try { tabUrl = (await chrome.tabs.get(details.tabId)).url || ''; } catch { /* closed */ }
  const cp = u.pathname.match(/\/cardpack\/INS\/([^/?]+)/);
  if (cp) {
    try {
      const b64 = decodeURIComponent(cp[1]);
      const body = JSON.parse(atob(b64));
      if (Array.isArray(body.paths) && body.paths.length) {
        const key = JSON.stringify(body.paths);
        O.cardpacks = [{ paths: body.paths, params: { ...body, paths: undefined }, query: u.search.slice(1), page: tabUrl, at: Date.now() },
          ...O.cardpacks.filter(c => JSON.stringify(c.paths) !== key)].slice(0, 12);
        O.query = u.search.slice(1) || O.query;
      }
    } catch { /* not base64 JSON */ }
  }
  const ev = u.pathname.match(/\/page\/event\/([^/?]+)/);
  if (ev) O.events[decodeURIComponent(ev[1])] = { at: Date.now(), page: tabUrl };
  if (!cp && !ev) return;
  O.urls = [details.url, ...O.urls.filter(x => x !== details.url)].slice(0, 10);
  await chrome.storage.local.set({ oursLearned: O });
};
chrome.webRequest.onBeforeRequest.addListener(
  (d) => { chain = chain.then(() => learnOurs(d)).catch(() => {}); },
  { urls: ['https://*.betfanatics.com/*'], types: ['xmlhttprequest'] },
);

// Our feed can also be fetched from here (how the MLB suite does it), if the dashboard's own request fails.
chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
  if (msg?.type !== 'OURS_FETCH' || !/^https:\/\/content\.1\.betfanatics\.com\//.test(msg.url || '')) return false;
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), 12_000);
  fetch(msg.url, { credentials: 'include', cache: 'no-store', signal: ctrl.signal })
    .then(async (r) => sendResponse({ status: r.status, text: await r.text(), type: r.headers.get('content-type') || '' }))
    .catch((e) => sendResponse({ error: String(e.message || e) }))
    .finally(() => clearTimeout(timer));
  return true;
});
