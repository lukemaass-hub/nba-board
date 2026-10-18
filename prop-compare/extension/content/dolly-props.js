// Reads OUR player-points prices straight off the Dolly Market Manager screen, the same way the
// In-Play Trading Guard's flip-guard.js reads Trading / OF: find the column headers by their
// on-screen text ("Selection", "Trading", "OF"), then read the cells under them on the same row.
// Read-only: no requests, nothing clicked or typed. Answers the dashboard's DOLLY_READ message.
// Like the guard, a collapsed market panel can't be read (Dolly doesn't render its rows).
(() => {
  if (window.__propCompareDolly) return;
  window.__propCompareDolly = true;

  const pnum = (s) => { const m = String(s ?? '').replace('−', '-').trim().match(/^[+-]?\d+(?:\.\d+)?$/); return m ? parseFloat(m[0]) : null; };
  const ownText = (el) => { let t = ''; for (const n of el.childNodes) if (n.nodeType === 3) t += n.textContent; return t.trim(); };
  const strip = (s) => s.replace(/[^A-Za-z ]/g, '').trim();   // drops sort-arrow glyphs ("OF ↑↓" / "OFswap_vert")
  const HEADS = new Set(['Selection', 'Trading', 'OF', 'App']);
  const SKIP = new Set(['SCRIPT', 'STYLE', 'NOSCRIPT', 'SVG', 'PATH', 'IMG', 'TEMPLATE']);
  const B = 6;   // row index bucket height (px)

  // ONE pass over the page: every element is measured at most once (Dolly has thousands of cells;
  // re-measuring per row is what froze it in v0.11). Only text leaves, inputs and header candidates
  // are measured at all. Row position = middle of the FIRST text line, so a wrapped name lines up.
  function snapshot() {
    const sy = window.scrollY;
    const heads = { Selection: [], Trading: [], OF: [], App: [] }, texts = [], nums = new Map();
    const addNum = (x, y, v) => { const k = Math.floor(y / B); (nums.get(k) || nums.set(k, []).get(k)).push({ x, y, v }); };
    for (const el of document.body.getElementsByTagName('*')) {
      if (SKIP.has(el.tagName.toUpperCase())) continue;
      const kids = el.children.length;
      if (el.tagName === 'INPUT') {
        const v = pnum(el.value);
        if (v == null) continue;
        const r = el.getBoundingClientRect(); if (!r.width) continue;
        addNum(r.left + r.width / 2, r.top + Math.min(r.height, 24) / 2 + sy, v);
        continue;
      }
      let t = null, head = null;
      if (!kids) { t = (el.textContent || '').replace(/\s+/g, ' ').trim(); if (!t) continue; if (t.length < 24 && HEADS.has(strip(t))) head = strip(t); }
      else if (kids <= 3) { const o = ownText(el); if (o && o.length < 24 && HEADS.has(strip(o))) head = strip(o); else continue; }
      else continue;
      const r = el.getBoundingClientRect(); if (!r.width || !r.height) continue;
      const x = r.left + r.width / 2, y = r.top + Math.min(r.height, 24) / 2 + sy;
      if (head) { heads[head].push({ x, y, left: r.left }); continue; }
      const v = pnum(t);
      if (v != null) addNum(x, y, v); else texts.push({ t, x, y, left: r.left });
    }
    return { heads, texts, nums };
  }
  function cellAt(nums, x, y) {   // the closest number in that column on that row
    let best = null, bd = 14;
    for (let k = Math.floor((y - 14) / B); k <= Math.floor((y + 14) / B); k++)
      for (const n of nums.get(k) || []) { const d = Math.abs(n.y - y); if (Math.abs(n.x - x) < 55 && d < bd) { bd = d; best = n.v; } }
    return best;
  }

  function readTables() {
    const { heads, texts, nums } = snapshot();
    const sels = heads.Selection.slice().sort((a, b) => a.y - b.y);
    const tables = [];
    let unread = 0, unreadSample = [];
    sels.forEach((h, idx) => {
      const near = (list) => list.find(t => Math.abs(t.y - h.y) < 16);
      const tH = near(heads.Trading), oH = near(heads.OF), aH = near(heads.App);
      if (!tH && !oH && !aH) return;
      const nextY = sels[idx + 1]?.y ?? Infinity;
      let title = '', ty = -Infinity;
      const rows = [], seenRow = new Set();
      let seen = 0;
      for (const l of texts) {
        if (l.y < h.y - 6 && l.y > h.y - 160 && l.y > ty && !HEADS.has(strip(l.t))) { title = l.t; ty = l.y; }
        if (l.y <= h.y + 6 || l.y >= nextY - 6 || Math.abs(l.left - h.left) > 60) continue;
        const rk = Math.round(l.y / 10);
        if (seenRow.has(rk)) continue;
        seenRow.add(rk); seen++;
        const q = parseSel(l.t, title);
        if (!q) { if (/point/i.test(l.t) && !NOT_POINTS.test(l.t)) { unread++; if (unreadSample.length < 4) unreadSample.push(l.t); } continue; }
        // only points rows get their prices read
        const trading = tH ? cellAt(nums, tH.x, l.y) : null, app = aH ? cellAt(nums, aH.x, l.y) : null, of = oH ? cellAt(nums, oH.x, l.y) : null;
        if (trading == null && app == null && of == null) continue;
        rows.push({ y: l.y, sel: l.t, q, trading, app, of });
      }
      tables.push({ title, seen, rows });
    });
    const hc = Object.fromEntries(Object.entries(heads).map(([k, v]) => [k.toLowerCase(), v.length]));
    return { tables, heads: hc, unread, unreadSample };
  }

  // ------------------------------------------------------------ rows -> quotes
  const NOT_POINTS = /\b(rebounds?|assists?|threes?|three-pointers?|3pt|steals?|blocks?|combos?|pra|pts \+|double|first|quarter|half|1st|2nd|3rd|4th|team|race|margin|odd|even|spread|money ?line|handicap)\b/i;
  const american = (d) => !(d > 1) ? null : d >= 2 ? `+${Math.round((d - 1) * 100)}` : String(Math.round(-100 / (d - 1)));

  const titleCase = (n) => n === n.toUpperCase() ? n.toLowerCase().replace(/(^|[\s'-])([a-z])/g, (m, p, c) => p + c.toUpperCase()).replace(/\b(Ii|Iii|Iv)\b/g, (m) => m.toUpperCase()) : n;

  // One selection row -> { player, kind, line, side } or null. Dolly writes e.g.
  //   "DUNCAN ROBINSON TO SCORE 5+ POINTS"            (alternate points: over N-0.5)
  //   "DUNCAN ROBINSON OVER 12.5 POINTS" / "... UNDER 12.5"   (player total points)
  function parseSel(sel, title) {
    const t = sel.replace(/\s+/g, ' ').trim();
    if (NOT_POINTS.test(t)) return null;
    let m = t.match(/^(.+?)\s+to score\s+(\d+)\s*\+\s*(?:points|pts)?$/i);
    if (m) return { player: titleCase(m[1]), kind: 'alt', line: parseInt(m[2], 10) - 0.5, side: 'over' };
    m = t.match(/^(.+?)\s+(over|under)\s+(\d+(?:\.\d+)?)\s*(?:total\s+)?(?:points|pts)?$/i);
    if (m && (/point|pts/i.test(t) || /point/i.test(title))) return { player: titleCase(m[1]), kind: 'ou', line: parseFloat(m[3]), side: m[2].toLowerCase() };
    if (!/point/i.test(title) || NOT_POINTS.test(title) || /^(game\s+)?total points$/i.test(title)) return null;
    m = t.match(/^(.+?)\s+(\d+)\s*\+$/);
    if (m) return { player: titleCase(m[1]), kind: 'alt', line: parseInt(m[2], 10) - 0.5, side: 'over' };
    const altN = (title.match(/(\d+)\s*\+\s*points/i) || [])[1];
    if (altN && !/\d/.test(t)) return { player: titleCase(t), kind: 'alt', line: parseInt(altN, 10) - 0.5, side: 'over' };
    return null;
  }

  function toQuotes(tables) {
    const out = [];
    for (const t of tables) for (const r of t.rows) {
      // ours = the price on offer: Trading when a trader has typed one, else App
      const ours = r.trading > 1 ? r.trading : r.app;
      for (const [book, d, src] of [['OURS', ours, r.trading > 1 ? 'Trading' : 'App'], ['OF', r.of, 'OF']])
        if (d > 1) out.push({ book, ...r.q, american: american(d), decimal: d, src });
    }
    return out;
  }

  function teams() {
    const m = (document.title || '').match(/(.+?)\s+(?:v|vs\.?|@)\s+(.+?)(?:\s+[-|–]|$)/i);
    if (m) return [m[1].trim(), m[2].trim()];
    const els = document.body.getElementsByTagName('*');
    for (let i = 0; i < els.length && i < 4000; i++) {
      const el = els[i];
      if (el.children.length) continue;
      const x = (el.textContent || '').trim().match(/^([A-Za-z0-9 .'&-]{3,40})\s+(?:v|vs\.?|@)\s+([A-Za-z0-9 .'&-]{3,40})$/i);
      if (x) return [x[1].trim(), x[2].trim()];
    }
    return [];
  }

  chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
    if (msg?.type !== 'DOLLY_READ') return false;
    if (window.top === window && !/market-manager/.test(location.href)) { sendResponse({ ok: false, error: 'not a Market Manager page' }); return false; }
    try {
      const t0 = performance.now();
      const { tables, heads, unread, unreadSample } = readTables();
      const quotes = toQuotes(tables);
      // in a sub-frame, only answer if this frame actually holds the market table
      if (window.top !== window && !heads.selection) return false;
      sendResponse({ unread, unreadSample, frame: window.top === window ? 'top' : location.href, readMs: Math.round(performance.now() - t0),
        ok: true, at: Date.now(), url: location.href, fixtureId: (location.pathname.match(/\/fixture\/(\d+)/) || [])[1] || null,
        teams: teams(), quotes, heads, hidden: document.hidden,
        tables: tables.map(t => ({ title: t.title, rows: t.seen, points: t.rows.length, sample: t.rows.slice(0, 2).map(r => `${r.sel} | App ${r.app ?? '–'} | Trading ${r.trading ?? '–'} | OF ${r.of ?? '–'}`) })).slice(0, 12),
      });
    } catch (e) { sendResponse({ ok: false, error: String(e.message || e) }); }
    return false;
  });
})();
