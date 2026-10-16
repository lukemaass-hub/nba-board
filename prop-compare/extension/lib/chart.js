// Small SVG line chart: one y-axis (chance of the over, %), time on x, one line per book,
// crosshair + tooltip on hover, direct labels at each line's end. A missing value (book
// late/failed on that pull) breaks the line instead of being bridged.
const NS = 'http://www.w3.org/2000/svg';
const el = (tag, attrs = {}, parent) => { const n = document.createElementNS(NS, tag); for (const [k, v] of Object.entries(attrs)) n.setAttribute(k, v); parent?.appendChild(n); return n; };
const tfmt = new Intl.DateTimeFormat('en-US', { timeZone: 'America/New_York', hour: 'numeric', minute: '2-digit', second: '2-digit' });

/**
 * points: [{ t, id, aligned, values: { DK: {p, over, under} | null, FD: ... } }]   (p in 0..1)
 * series: [{ book, name, color }]
 */
export function renderChart(box, tip, points, series) {
  box.textContent = '';
  tip.hidden = true;
  const W = box.clientWidth || 800, H = box.clientHeight || 300;
  const m = { l: 44, r: 96, t: 10, b: 26 };
  const svg = el('svg', { viewBox: `0 0 ${W} ${H}`, role: 'img' }, box);
  const vals = points.flatMap(pt => series.map(s => pt.values[s.book]?.p).filter(v => v != null));
  if (!vals.length) { const t = el('text', { x: W / 2, y: H / 2, 'text-anchor': 'middle' }, svg); t.textContent = 'No prices for this line yet.'; return; }

  let lo = Math.min(...vals) * 100, hi = Math.max(...vals) * 100;
  const pad = Math.max(1, (hi - lo) * 0.15); lo = Math.max(0, lo - pad); hi = Math.min(100, hi + pad);
  const step = niceStep((hi - lo) / 5); lo = Math.floor(lo / step) * step; hi = Math.ceil(hi / step) * step;
  const t0 = points[0].t, t1 = Math.max(points[points.length - 1].t, t0 + 1000);
  const x = (t) => m.l + (t - t0) / (t1 - t0) * (W - m.l - m.r);
  const y = (p) => m.t + (1 - (p * 100 - lo) / (hi - lo)) * (H - m.t - m.b);

  // recessive grid + axes
  for (let v = lo; v <= hi + 1e-9; v += step) {
    el('line', { x1: m.l, x2: W - m.r, y1: y(v / 100), y2: y(v / 100), stroke: '#2a2a27' }, svg);
    const t = el('text', { x: m.l - 6, y: y(v / 100) + 4, 'text-anchor': 'end' }, svg); t.textContent = `${+v.toFixed(1)}%`;
  }
  const nx = Math.max(2, Math.min(6, Math.floor((W - m.l - m.r) / 110)));
  for (let i = 0; i <= nx; i++) {
    const tt = t0 + (t1 - t0) * i / nx;
    const t = el('text', { x: x(tt), y: H - 8, 'text-anchor': i === 0 ? 'start' : i === nx ? 'end' : 'middle' }, svg); t.textContent = tfmt.format(tt);
  }

  // lines (broken at gaps) + end labels
  const ends = [];
  for (const s of series) {
    let d = '', pen = false, last = null;
    for (const pt of points) {
      const v = pt.values[s.book]?.p;
      if (v == null) { pen = false; continue; }
      d += `${pen ? 'L' : 'M'}${x(pt.t).toFixed(1)},${y(v).toFixed(1)}`; pen = true; last = { t: pt.t, v };
    }
    if (!d) continue;
    el('path', { d, fill: 'none', stroke: s.color, 'stroke-width': 2, 'stroke-linejoin': 'round', 'stroke-linecap': 'round' }, svg);
    // lone points (surrounded by gaps) would be invisible as a path
    points.forEach((pt, i) => {
      const v = pt.values[s.book]?.p;
      if (v != null && points[i - 1]?.values[s.book]?.p == null && points[i + 1]?.values[s.book]?.p == null)
        el('circle', { cx: x(pt.t), cy: y(v), r: 3, fill: s.color }, svg);
    });
    ends.push({ s, yv: y(last.v), x: x(last.t), v: last.v });
  }
  ends.sort((a, b) => a.yv - b.yv);
  for (let i = 1; i < ends.length; i++) if (ends[i].yv - ends[i - 1].yv < 14) ends[i].yv = ends[i - 1].yv + 14;
  for (const e of ends) {
    el('circle', { cx: e.x, cy: y(e.v), r: 4, fill: e.s.color, stroke: '#1a1a19', 'stroke-width': 2 }, svg);
    const t = el('text', { x: W - m.r + 8, y: e.yv + 4, class: 'label' }, svg);
    t.textContent = `${e.s.name} ${(e.v * 100).toFixed(1)}%`;
  }

  // hover layer: crosshair snaps to the nearest pull
  const cross = el('line', { y1: m.t, y2: H - m.b, stroke: '#85857f', 'stroke-dasharray': '3 3', visibility: 'hidden' }, svg);
  const dots = series.map(s => el('circle', { r: 4, fill: s.color, stroke: '#1a1a19', 'stroke-width': 2, visibility: 'hidden' }, svg));
  const hit = el('rect', { x: m.l, y: m.t, width: W - m.l - m.r, height: H - m.t - m.b, fill: 'transparent' }, svg);
  hit.addEventListener('mouseleave', () => { cross.setAttribute('visibility', 'hidden'); dots.forEach(d => d.setAttribute('visibility', 'hidden')); tip.hidden = true; });
  hit.addEventListener('mousemove', (ev) => {
    const r = svg.getBoundingClientRect();
    const mx = (ev.clientX - r.left) * (W / r.width);
    let best = 0, bd = Infinity;
    points.forEach((pt, i) => { const dd = Math.abs(x(pt.t) - mx); if (dd < bd) { bd = dd; best = i; } });
    const pt = points[best], px = x(pt.t);
    cross.setAttribute('x1', px); cross.setAttribute('x2', px); cross.setAttribute('visibility', 'visible');
    tip.textContent = '';
    const head = document.createElement('div'); head.textContent = `${tfmt.format(pt.t)} ET · pull #${pt.id}${pt.aligned ? '' : ' · not aligned'}`; tip.appendChild(head);
    series.forEach((s, i) => {
      const v = pt.values[s.book];
      if (v?.p != null) { dots[i].setAttribute('cx', px); dots[i].setAttribute('cy', y(v.p)); dots[i].setAttribute('visibility', 'visible'); }
      else dots[i].setAttribute('visibility', 'hidden');
      const row = document.createElement('div');
      const sw = document.createElement('span'); sw.className = 'sw'; sw.style.background = s.color; row.appendChild(sw);
      row.appendChild(document.createTextNode(v?.p != null
        ? `${s.name}: ${(v.p * 100).toFixed(1)}%  (${v.over ?? '–'} / ${v.under ?? '–'})`
        : `${s.name}: no price this pull`));
      tip.appendChild(row);
    });
    tip.hidden = false;
    const br = box.getBoundingClientRect(), pr = box.offsetParent.getBoundingClientRect();
    const left = br.left - pr.left + px * (r.width / W);
    tip.style.left = `${Math.min(left + 12, pr.width - tip.offsetWidth - 8)}px`;
    tip.style.top = `${br.top - pr.top + 10}px`;
  });
}

function niceStep(raw) {
  const p = 10 ** Math.floor(Math.log10(raw || 1)), f = raw / p;
  return (f <= 1 ? 1 : f <= 2 ? 2 : f <= 5 ? 5 : 10) * p;
}
