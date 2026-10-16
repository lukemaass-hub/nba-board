// Runs on the trading portal (trading.1.betfanatics.com/trading/portal). Reads each game
// row's event id the same way the MLB suite's nats-portal.js does (the row's data-row-key,
// else a numeric cell title) together with the row's text (teams, date, time), and saves
// them so the dashboard can find our event id for a game without anyone typing it.
// Read-only: nothing on the page is clicked or changed.
(() => {
  const rowsNow = () => {
    const out = {};
    for (const tr of document.querySelectorAll('tr')) {
      let id = tr.dataset?.rowKey;
      if (!id || !/^\d{5,}$/.test(id)) {
        id = null;
        for (const td of tr.querySelectorAll('td')) if (td.title && /^\d{5,}$/.test(td.title.trim())) { id = td.title.trim(); break; }
      }
      const text = (tr.innerText || '').replace(/\s+/g, ' ').trim();
      if (id && text) out[id] = text.slice(0, 240);
    }
    const open = location.pathname.match(/\/trading\/portal\/(\d{5,})/);   // an event page itself
    if (open) out[open[1]] = out[open[1]] || (document.title || 'opened in portal');
    return out;
  };
  let lastSig = '';
  const save = async () => {
    const rows = rowsNow();
    const sig = Object.keys(rows).sort().join(',');
    if (!sig || sig === lastSig) return;
    lastSig = sig;
    const { oursLearned: O = { cardpacks: [], events: {}, query: null, urls: [] } } = await chrome.storage.local.get('oursLearned');
    O.portal = O.portal || {};
    const now = Date.now();
    for (const [id, text] of Object.entries(rows)) O.portal[id] = { text, at: now };
    // keep the newest 400
    O.portal = Object.fromEntries(Object.entries(O.portal).sort((a, b) => b[1].at - a[1].at).slice(0, 400));
    await chrome.storage.local.set({ oursLearned: O });
  };
  setInterval(() => save().catch(() => {}), 3000);
  save().catch(() => {});
})();
