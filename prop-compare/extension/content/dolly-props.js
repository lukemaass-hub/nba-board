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
  const cy = (el) => { const r = rect(el); return r.top + r.height / 2 + window.scrollY; };
  const vis = (el) => { const r = rect(el); return r.width > 0 && r.height > 0; };
  const pnum = (s) => { const m = String(s ?? '').replace('−', '-').trim().match(/^[+-]?\d+(?:\.\d+)?$/); return m ? parseFloat(m[0]) : null; };
  const ownText = (el) => { let t = ''; for (const n of el.childNodes) if (n.nodeType === 3) t += n.textContent; return t.replace(/\s+/g, ' ').trim(); };
  const strip = (s) => s.replace(/[^A-Za-z ]/g, '').trim();   // drops sort-arrow glyphs ("OF ↑↓" / "OFswap_vert")

  function heads(txt) {
    const hits = [];
    for (const el of document.body.getElementsByTagName('*')) if (vis(el) && strip(ownText(el)) === txt) hits.push(el);
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
  function cellAt(x, y, inputs, leafs) {
    const i = inputs.find(n => Math.abs(cx(n) - x) < 55 && Math.abs(cy(n) - y) < 16);
    if (i && pnum(i.value) != null) return pnum(i.value);
    const l = leafs.find(n => Math.abs(n.x - x) < 55 && Math.abs(n.y - y) < 16 && pnum(n.t) != null);
    return l ? pnum(l.t) : null;
  }

  function readTables() {
    const sel = heads('Selection'), tr = heads('Trading'), of = heads('OF');
    const all = leaves(), inputs = [...document.querySelectorAll('input')].filter(vis);
    const tables = [];
    const selSorted = sel.map(h => ({ h, y: cy(h) })).sort((a, b) => a.y - b.y);
    selSorted.forEach(({ h, y: hy }, idx) => {
      const tH = tr.find(t => Math.abs(cy(t) - hy) < 14), oH = of.find(o => Math.abs(cy(o) - hy) < 14);
      if (!tH && !oH) return;
      const nextY = selSorted[idx + 1]?.y ?? Infinity;
      const left = rect(h).left, tX = tH ? cx(tH) : null, oX = oH ? cx(oH) : null;
      // market title: the closest text above the header row
      const above = all.filter(l => l.y < hy - 6 && l.y > hy - 160 && pnum(l.t) == null && !/^(selection|trading|of|af|app|hard|soft|pricing|active|displayed|suspension|result|uncertainty)$/i.test(l.t));
      const title = above.sort((a, b) => b.y - a.y)[0]?.t || '';
      const rows = [];
      for (const l of all) {
        if (l.y <= hy + 6 || l.y >= nextY - 6 || Math.abs(l.left - left) > 40 || pnum(l.t) != null) continue;
        if (rows.some(r => Math.abs(r.y - l.y) < 10)) continue;
        const trading = tX != null ? cellAt(tX, l.y, inputs, all) : null, ofv = oX != null ? cellAt(oX, l.y, inputs, all) : null;
        if (trading == null && ofv == null) continue;   // a label (e.g. the next market's title), not a selection
        rows.push({ y: l.y, sel: l.t, trading, of: ofv });
      }
      tables.push({ title, rows: rows.sort((a, b) => a.y - b.y) });
    });
    return { tables, heads: { selection: sel.length, trading: tr.length, of: of.length } };
  }

  // ------------------------------------------------------------ rows -> quotes
  const NOT_POINTS = /rebound|assist|three|3pt|steal|block|combo|pra|\+ ?(reb|ast)|double|first|quarter|half|1st|2nd|3rd|4th|team|race|margin|odd|even|spread|money|handicap/i;
  const american = (d) => !(d > 1) ? null : d >= 2 ? `+${Math.round((d - 1) * 100)}` : String(Math.round(-100 / (d - 1)));

  function toQuotes(tables) {
    const out = [];
    for (const t of tables) {
      if (!/point/i.test(t.title) || NOT_POINTS.test(t.title) || /^(game\s+)?total points$/i.test(t.title)) continue;
      const altN = (t.title.match(/(\d+)\s*\+\s*points/i) || [])[1];
      for (const r of t.rows) {
        let player = null, kind = null, line = null, side = null;
        const a = r.sel.match(/^(.+?)\s+(\d+)\s*\+$/);
        const ou = r.sel.match(/^(.*?)\s*\b(over|under)\b\s*([\d.]+)?\s*$/i);
        if (altN) { player = r.sel.replace(/\s+\d+\s*\+$/, '').trim(); kind = 'alt'; line = parseInt(altN, 10) - 0.5; side = 'over'; }
        else if (a) { player = a[1].trim(); kind = 'alt'; line = parseInt(a[2], 10) - 0.5; side = 'over'; }
        else if (ou) {
          side = ou[2].toLowerCase(); kind = 'ou';
          player = ou[1].replace(/\s*[-–:]\s*$/, '').trim() || t.title.replace(/\s*(player\s+)?(total\s+)?points?.*$/i, '').trim();
          line = ou[3] ? parseFloat(ou[3]) : parseFloat((t.title.match(/(\d+\.5)/) || [])[1]);
        }
        if (!player || !kind || !Number.isFinite(line)) continue;
        for (const [book, d] of [['OURS', r.trading], ['OF', r.of]])
          if (d > 1) out.push({ book, player, kind, line, side, american: american(d), decimal: d });
      }
    }
    return out;
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
    if (!/market-manager/.test(location.href)) { sendResponse({ ok: false, error: 'not a Market Manager page' }); return false; }
    try {
      const { tables, heads } = readTables();
      const quotes = toQuotes(tables);
      sendResponse({
        ok: true, at: Date.now(), url: location.href, fixtureId: (location.pathname.match(/\/fixture\/(\d+)/) || [])[1] || null,
        teams: teams(), quotes, heads, hidden: document.hidden,
        tables: tables.map(t => ({ title: t.title, rows: t.rows.length, sample: t.rows.slice(0, 3).map(r => `${r.sel} | ${r.trading ?? '–'} | ${r.of ?? '–'}`) })).slice(0, 12),
      });
    } catch (e) { sendResponse({ ok: false, error: String(e.message || e) }); }
    return false;
  });
})();
