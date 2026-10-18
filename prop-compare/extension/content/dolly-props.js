// Reads OUR in-app player-points prices (the "App" column) off the Dolly Market Manager screen.
// Read-only: nothing is clicked, typed, changed or sent anywhere. Layout-free: it never measures
// the page (measuring forces Dolly to recalculate its whole layout, which froze it in v0.11/0.12).
// It walks the page's text in order, keeps track of the market heading it is under (PLAYER TOTAL
// POINTS, ALTERNATE PLAYER POINTS, ...), reads each points selection ("JORDAN WALSH OVER 0.5",
// "DUNCAN ROBINSON TO SCORE 5+ POINTS"), and takes that row's App cell (see appPrice).
// Runs only when the dashboard asks (DOLLY_READ), once per pull.
(() => {
  if (window.__propCompareDolly) return;
  window.__propCompareDolly = true;

  const PRICE = /^\d+\.\d+$/;
  // a selection row's label: "JORDAN WALSH OVER 0.5" / "... UNDER 0.5" (under its market heading),
  // or "DUNCAN ROBINSON TO SCORE 5+ POINTS"
  const OU = /^(.+?)\s+(over|under)\s+(\d+(?:\.\d+)?)(?:\s+(?:total\s+)?(?:points|pts))?$/i;
  const ALT = /^(.+?)\s+to score\s+(\d+)\s*\+\s*(?:points|pts)?$/i;
  const SEL = /\s(over|under)\s+\d+(\.\d+)?$|\sto (score|get|record)\s+\d+\s*\+/i;
  // market headings, e.g. "PLAYER TOTAL POINTS", "ALTERNATE PLAYER POINTS", "PLAYER REBOUNDS"
  const MARKET = /^(alternate\s+)?player\s+[a-z0-9' +&-]+$/i;
  const POINTS_MARKET = (m) => /\bpoints\b/i.test(m) && !/three|rebound|assist|steal|block|combo|\+|&/i.test(m);
  const titleCase = (n) => n === n.toUpperCase() ? n.toLowerCase().replace(/(^|[\s'-])([a-z])/g, (m, p, c) => p + c.toUpperCase()).replace(/\b(Ii|Iii|Iv)\b/g, (m) => m.toUpperCase()) : n;
  const american = (d) => !(d > 1) ? null : d >= 2 ? `+${Math.round((d - 1) * 100)}` : String(Math.round(-100 / (d - 1)));

  function parseSel(t, market) {
    let m = t.match(ALT);
    if (m) return { player: titleCase(m[1]), kind: 'alt', line: parseInt(m[2], 10) - 0.5, side: 'over' };
    m = t.match(OU);
    if (m && (POINTS_MARKET(market) || /\b(points|pts)$/i.test(t))) return { player: titleCase(m[1]), kind: 'ou', line: parseFloat(m[3]), side: m[2].toLowerCase() };
    return null;
  }

  // App price for the row holding this selection label. The row's prices shown as text are, in
  // order: AF (e.g. 1.00, may be blank), App, OF; Hard / Soft / Trading are input boxes (not text).
  // So with three numbers App is the 2nd, with two (AF blank) it is the 1st.
  function appPrice(labelEl) {
    let row = labelEl;
    for (let i = 0; i < 8 && row.parentElement; i++) {
      row = row.parentElement;
      const w = document.createTreeWalker(row, NodeFilter.SHOW_TEXT);
      let n, labels = 0;
      const nums = [];
      while ((n = w.nextNode())) {
        const s = n.nodeValue.replace(/\s+/g, ' ').trim();
        if (!s) continue;
        if (SEL.test(s)) { if (++labels > 1) return null; }   // climbed past the row into the table
        else if (PRICE.test(s)) nums.push(parseFloat(s));
      }
      if (nums.length >= 2) return nums.length >= 3 ? nums[1] : nums[0];
    }
    return null;
  }

  function read() {
    const quotes = [], sample = [], markets = [];
    let rows = 0, market = '';
    const w = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
    let n;
    while ((n = w.nextNode())) {
      const s = n.nodeValue.replace(/\s+/g, ' ').trim();
      if (s.length < 8 || s.length > 80) continue;
      if (MARKET.test(s) && s === s.toUpperCase() && !SEL.test(s)) { market = s; if (markets.length < 12 && !markets.includes(s)) markets.push(s); continue; }
      if (!SEL.test(s)) continue;
      rows++;
      const q = parseSel(s, market);
      if (!q) continue;
      const d = appPrice(n.parentElement);
      if (!(d > 1)) continue;
      if (sample.length < 3) sample.push(`${market}: ${s} → App ${d}`);
      quotes.push({ book: 'OURS', ...q, american: american(d), decimal: d });
    }
    return { quotes, rows, sample, markets };
  }

  function teams() {
    const m = (document.title || '').match(/(.+?)\s+(?:v|vs\.?|@)\s+(.+?)(?:\s+[-|–]|$)/i);
    return m ? [m[1].trim(), m[2].trim()] : [];
  }

  chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
    if (msg?.type !== 'DOLLY_READ') return false;
    if (window.top === window && !/market-manager/.test(location.href)) { sendResponse({ ok: false, error: 'not a Market Manager page' }); return false; }
    try {
      const t0 = performance.now();
      const r = read();
      if (window.top !== window && !r.quotes.length) return false;   // sub-frames answer only if they hold the prices
      sendResponse({ ok: true, version: chrome.runtime.getManifest().version, at: Date.now(), readMs: Math.round(performance.now() - t0), url: location.href,
        frame: window.top === window ? 'top' : location.href, teams: teams(), hidden: document.hidden, ...r });
    } catch (e) { sendResponse({ ok: false, error: String(e.message || e) }); }
    return false;
  });
})();
