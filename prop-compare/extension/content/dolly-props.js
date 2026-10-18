// Reads OUR in-app player-points prices (the "App" column) off the Dolly Market Manager screen.
// Read-only: nothing is clicked, typed, changed or sent anywhere. Layout-free: it never measures
// the page (measuring forces Dolly to recalculate its whole layout, which froze it in v0.11/0.12).
// It walks the page's text, finds each points selection ("DUNCAN ROBINSON TO SCORE 5+ POINTS"),
// climbs to that selection's row, and takes the row's App cell: the first decimal price shown as
// text in the row (Hard / Soft / Trading are input boxes, so their numbers aren't text).
// Runs only when the dashboard asks (DOLLY_READ), once per pull.
(() => {
  if (window.__propCompareDolly) return;
  window.__propCompareDolly = true;

  const PRICE = /^\d+\.\d+$/;
  const LABEL = /\bpoints?\b|\bto (score|get|record)\b/i;
  const NOT_POINTS = /\b(rebounds?|assists?|threes?|three-pointers?|3pt|steals?|blocks?|combos?|double|first|quarter|half|1st|2nd|3rd|4th|team)\b/i;
  const titleCase = (n) => n === n.toUpperCase() ? n.toLowerCase().replace(/(^|[\s'-])([a-z])/g, (m, p, c) => p + c.toUpperCase()).replace(/\b(Ii|Iii|Iv)\b/g, (m) => m.toUpperCase()) : n;
  const american = (d) => !(d > 1) ? null : d >= 2 ? `+${Math.round((d - 1) * 100)}` : String(Math.round(-100 / (d - 1)));

  // "X TO SCORE 5+ POINTS" -> alt over 4.5; "X OVER 24.5 POINTS" / "X UNDER 24.5 POINTS" -> over/under
  function parseSel(t) {
    if (NOT_POINTS.test(t)) return null;
    let m = t.match(/^(.+?)\s+to score\s+(\d+)\s*\+\s*(?:points|pts)?$/i);
    if (m) return { player: titleCase(m[1]), kind: 'alt', line: parseInt(m[2], 10) - 0.5, side: 'over' };
    m = t.match(/^(.+?)\s+(over|under)\s+(\d+(?:\.\d+)?)\s*(?:total\s+)?(?:points|pts)$/i);
    if (m) return { player: titleCase(m[1]), kind: 'ou', line: parseFloat(m[3]), side: m[2].toLowerCase() };
    return null;
  }

  // the App price for the row holding this selection label
  function appPrice(labelEl) {
    let row = labelEl;
    for (let i = 0; i < 8 && row.parentElement; i++) {
      row = row.parentElement;
      // the row = the first ancestor that also holds a price, while holding only this one label
      const w = document.createTreeWalker(row, NodeFilter.SHOW_TEXT);
      let n, price = null, labels = 0;
      while ((n = w.nextNode())) {
        const s = n.nodeValue.trim();
        if (!s) continue;
        if (LABEL.test(s)) { if (++labels > 1) return null; }   // climbed past the row into the table
        else if (price == null && PRICE.test(s)) price = parseFloat(s);
      }
      if (price != null) return price;
    }
    return null;
  }

  function read() {
    const quotes = [], sample = [];
    let rows = 0;
    const w = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
    let n;
    while ((n = w.nextNode())) {
      const s = n.nodeValue.replace(/\s+/g, ' ').trim();
      if (s.length < 12 || s.length > 80 || !LABEL.test(s)) continue;
      rows++;
      const q = parseSel(s);
      if (!q) continue;
      const d = appPrice(n.parentElement);
      if (!(d > 1)) continue;
      if (sample.length < 3) sample.push(`${s} → App ${d}`);
      quotes.push({ book: 'OURS', ...q, american: american(d), decimal: d });
    }
    return { quotes, rows, sample };
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
      sendResponse({ ok: true, at: Date.now(), readMs: Math.round(performance.now() - t0), url: location.href,
        frame: window.top === window ? 'top' : location.href, teams: teams(), hidden: document.hidden, ...r });
    } catch (e) { sendResponse({ ok: false, error: String(e.message || e) }); }
    return false;
  });
})();
