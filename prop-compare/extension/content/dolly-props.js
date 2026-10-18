// Reads OUR player-points prices straight off the Dolly Market Manager screen, the same way the
// In-Play Trading Guard's flip-guard.js reads Trading / OF: find the column headers by their
// on-screen text ("Selection", "Trading", "OF"), then read the cells under them on the same row.
// Read-only: no requests, nothing clicked or typed. Answers the dashboard's DOLLY_READ message.
// Like the guard, a collapsed market panel can't be read (Dolly doesn't render its rows).
(() => {
  if (window.__propCompareDolly) return;
  window.__propCompareDolly = true;

  const rect = (el) => el.getBoundingClientRect();
  const cx = (el) => { const r = rect(el); return r.left + r.width / 2; };
  // row position = middle of the FIRST line of the box, so a name that wraps onto two lines still lines up with its row
  const cy = (el) => { const r = rect(el); return r.top + Math.min(r.height, 24) / 2 + window.scrollY; };
  const vis = (el) => { const r = rect(el); return r.width > 0 && r.height > 0; };
  const pnum = (s) => { const m = String(s ?? '').replace('−', '-').trim().match(/^[+-]?\d+(?:\.\d+)?$/); return m ? parseFloat(m[0]) : null; };
  const ownText = (el) => { let t = ''; for (const n of el.childNodes) if (n.nodeType === 3) t += n.textContent; return t.replace(/\s+/g, ' ').trim(); };
  const strip = (s) => s.replace(/[^A-Za-z ]/g, '').trim();   // drops sort-arrow glyphs ("OF ↑↓" / "OFswap_vert")

  // headers: an element whose own text is the header, or a small box whose whole text is (a header
  // with a sort icon, "Selection ↑↓", can keep its words in a child element)
  function heads(txt) {
    const hits = [];
    for (const el of document.body.getElementsByTagName('*')) {
      if (!vis(el)) continue;
      if (strip(ownText(el)) === txt || (el.children.length <= 3 && strip(el.textContent || '') === txt && rect(el).width < 260)) hits.push(el);
    }
    return hits.filter(el => !hits.some(o => o !== el && el.contains(o)));
  }
  function leaves() {
    const out = [];
    for (const el of document.body.getElementsByTagName('*')) {
      if (el.children.length || !vis(el)) continue;
      const t = (el.textContent || '').replace(/\s+/g, ' ').trim();
      if (t) out.push({ el, t, x: cx(el), y: cy(el), left: rect(el).left });
    }
    return out;
  }
  // a numeric cell (an <input> or text) under column x on row y
  function cellAt(x, y, inputs, leafs) {   // the closest cell on that row, never just the first one found
    const c = [];
    for (const n of inputs) if (Math.abs(cx(n) - x) < 55 && Math.abs(cy(n) - y) < 14) c.push({ d: Math.abs(cy(n) - y), v: pnum(n.value) });
    for (const n of leafs) if (Math.abs(n.x - x) < 55 && Math.abs(n.y - y) < 14 && pnum(n.t) != null) c.push({ d: Math.abs(n.y - y), v: pnum(n.t) });
    c.sort((a, b) => a.d - b.d);
    return c.length ? c[0].v : null;
  }

  function readTables() {
    const sel = heads('Selection'), tr = heads('Trading'), of = heads('OF'), app = heads('App');
    const all = leaves(), inputs = [...document.querySelectorAll('input')].filter(vis);
    const tables = [];
    const selSorted = sel.map(h => ({ h, y: cy(h) })).sort((a, b) => a.y - b.y);
    selSorted.forEach(({ h, y: hy }, idx) => {
      const near = (list) => list.find(t => Math.abs(cy(t) - hy) < 16);
      const tH = near(tr), oH = near(of), aH = near(app);
      if (!tH && !oH && !aH) return;
      const nextY = selSorted[idx + 1]?.y ?? Infinity;
      const left = rect(h).left, tX = tH ? cx(tH) : null, oX = oH ? cx(oH) : null, aX = aH ? cx(aH) : null;
      // market title: the closest text above the header row
      const above = all.filter(l => l.y < hy - 6 && l.y > hy - 160 && pnum(l.t) == null && !/^(selection|trading|of|af|app|hard|soft|pricing|active|displayed|suspension|result|uncertainty)$/i.test(l.t));
      const title = above.sort((a, b) => b.y - a.y)[0]?.t || '';
      const rows = [];
      for (const l of all) {
        if (l.y <= hy + 6 || l.y >= nextY - 6 || Math.abs(l.left - left) > 60 || pnum(l.t) != null) continue;
        if (rows.some(r => Math.abs(r.y - l.y) < 10)) continue;
        const trading = tX != null ? cellAt(tX, l.y, inputs, all) : null, ofv = oX != null ? cellAt(oX, l.y, inputs, all) : null;
        const appv = aX != null ? cellAt(aX, l.y, inputs, all) : null;
        if (trading == null && ofv == null && appv == null) continue;   // a label (e.g. the next market's title), not a selection
        rows.push({ y: l.y, sel: l.t, trading, app: appv, of: ofv });
      }
      tables.push({ title, rows: rows.sort((a, b) => a.y - b.y) });
    });
    return { tables, heads: { selection: sel.length, trading: tr.length, of: of.length, app: app.length } };
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
    let unread = 0;
    for (const t of tables) for (const r of t.rows) {
      const q = parseSel(r.sel, t.title);
      if (!q) { if (/point/i.test(r.sel)) unread++; continue; }
      // ours = the price on offer: Trading when a trader has typed one, else App
      const ours = r.trading > 1 ? r.trading : r.app;
      for (const [book, d, src] of [['OURS', ours, r.trading > 1 ? 'Trading' : 'App'], ['OF', r.of, 'OF']])
        if (d > 1) out.push({ book, ...q, american: american(d), decimal: d, src });
    }
    return { quotes: out, unread };
  }

  function teams() {
    const m = (document.title || '').match(/(.+?)\s+(?:v|vs\.?|@)\s+(.+?)(?:\s+[-|–]|$)/i);
    if (m) return [m[1].trim(), m[2].trim()];
    for (const l of leaves()) {
      const x = l.t.match(/^([A-Za-z0-9 .'&-]{3,40})\s+(?:v|vs\.?|@)\s+([A-Za-z0-9 .'&-]{3,40})$/i);
      if (x) return [x[1].trim(), x[2].trim()];
    }
    return [];
  }

  chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
    if (msg?.type !== 'DOLLY_READ') return false;
    if (window.top === window && !/market-manager/.test(location.href)) { sendResponse({ ok: false, error: 'not a Market Manager page' }); return false; }
    try {
      const { tables, heads } = readTables();
      const { quotes, unread } = toQuotes(tables);
      // in a sub-frame, only answer if this frame actually holds the market table
      if (window.top !== window && !heads.selection && !heads.trading && !heads.of) return false;
      sendResponse({ unread, frame: window.top === window ? 'top' : location.href,
        ok: true, at: Date.now(), url: location.href, fixtureId: (location.pathname.match(/\/fixture\/(\d+)/) || [])[1] || null,
        teams: teams(), quotes, heads, hidden: document.hidden,
        tables: tables.map(t => ({ title: t.title, rows: t.rows.length, sample: t.rows.slice(0, 3).map(r => `${r.sel} | App ${r.app ?? '–'} | Trading ${r.trading ?? '–'} | OF ${r.of ?? '–'}`) })).slice(0, 12),
      });
    } catch (e) { sendResponse({ ok: false, error: String(e.message || e) }); }
    return false;
  });
})();
