// Lines up DK, FD and our quotes taken in the same tick, and works out the gap between them.
//
// Alignment rule (the user's): never compare a price from one moment with a price from
// another. Both books are requested at the same instant each tick; a book's snapshot
// counts only if it answered within `toleranceMs` of the fastest book. A late or failed
// book is "missing" for that tick and is never filled from an earlier tick.

import { playerMatch, playerKey } from './match.js';

export const BOOKS = ['DK', 'FD', 'OURS'];
export const GAPS = [['OURS', 'DK'], ['OURS', 'FD'], ['DK', 'FD']];   // gap = first minus second, in % points
export const gapKey = ([a, b]) => `${a}_${b}`;

/** Decide which books count for this tick.
 *  results: { DK: {ok, at}, FD: {...}, OURS: {...} }; expected = the books this game has.
 *  -> { aligned (every expected book used), used: {book: bool}, spreadMs, firstAt } */
export function alignTick(results, toleranceMs, expected = BOOKS) {
  const ok = BOOKS.filter(b => results[b]?.ok);
  const used = Object.fromEntries(BOOKS.map(b => [b, false]));
  if (!ok.length) return { aligned: false, used, spreadMs: null, firstAt: null };
  const first = Math.min(...ok.map(b => results[b].at));
  for (const b of ok) used[b] = results[b].at - first <= toleranceMs;
  const spreadMs = ok.length > 1 ? Math.max(...ok.map(b => results[b].at)) - first : null;
  return { aligned: expected.length > 1 && expected.every(b => used[b]), used, spreadMs, firstAt: first };
}

/** Two-way no-vig probability of the over; one-sided lines (alt "N+") fall back to plain implied. */
export function overProb(over, under) {
  if (!over?.decimal) return { p: null, novig: false };
  const po = 1 / over.decimal;
  if (under?.decimal) { const pu = 1 / under.decimal; return { p: po / (po + pu), novig: true }; }
  return { p: po, novig: false };
}

/** Rows for the table / export. One row per player + market kind + line.
 *  quotesByBook: { DK: [quote], FD: [...], OURS: [...] } (books not used this tick: [] or missing) */
export function buildRows(quotesByBook) {
  // Canonical player names: FD first (its names are full), then DK, then ours.
  const names = [];
  const canon = (name) => {
    for (const n of names) if (playerMatch(n, name)) return n;
    names.push(name); return name;
  };
  const rows = new Map();
  for (const book of ['FD', 'DK', 'OURS']) {
    for (const q of quotesByBook[book] || []) {
      const player = canon(q.player);
      const key = `${playerKey(player)}|${q.kind}|${q.line}`;
      if (!rows.has(key)) rows.set(key, { key, player, kind: q.kind, line: q.line, books: {} });
      const r = rows.get(key);
      (r.books[book] ||= {})[q.side] = { american: q.american, decimal: q.decimal };
    }
  }
  for (const r of rows.values()) {
    for (const sides of Object.values(r.books)) Object.assign(sides, overProb(sides.over, sides.under));
    // A gap only when both books price it the same way (both no-vig, or both one-sided).
    r.gaps = {};
    for (const pair of GAPS) {
      const x = r.books[pair[0]], y = r.books[pair[1]];
      r.gaps[gapKey(pair)] = (x?.p != null && y?.p != null && x.novig === y.novig) ? (x.p - y.p) * 100 : null;
    }
    r.gapPts = r.gaps.DK_FD;
  }
  return [...rows.values()].sort((a, b) => a.player.localeCompare(b.player) || a.kind.localeCompare(b.kind) || a.line - b.line);
}

export const marketLabel = (r) => r.kind === 'ou' ? `Points O/U ${r.line}` : `${r.line + 0.5}+ points`;

// ---------------------------------------------------------------- export
export const CSV_HEADERS = ['tick_time_et', 'tick_time_utc', 'tick_id', 'aligned', 'spread_ms', 'game', 'player', 'market', 'line',
  'dk_over', 'dk_under', 'dk_over_prob', 'dk_fetched_utc', 'fd_over', 'fd_under', 'fd_over_prob', 'fd_fetched_utc',
  'ours_over', 'ours_under', 'ours_over_prob', 'ours_fetched_utc',
  'prob_kind', 'gap_pts_ours_minus_dk', 'gap_pts_ours_minus_fd', 'gap_pts_dk_minus_fd'];

const etFmt = new Intl.DateTimeFormat('en-US', { timeZone: 'America/New_York', year: 'numeric', month: '2-digit', day: '2-digit',
  hour: '2-digit', minute: '2-digit', second: '2-digit', hourCycle: 'h23' });
export const etTime = (ms) => etFmt.format(new Date(ms)).replace(',', '');
const iso = (ms) => ms ? new Date(ms).toISOString() : '';
const pct = (p) => p == null ? '' : (p * 100).toFixed(2);

/** One flat array per row per tick: what goes to CSV and to Google Sheets. */
export function tickToRecords(tick) {
  const fmt = (g) => g == null ? '' : g.toFixed(2);
  return tick.rows.map(r => {
    const bk = (b) => { const x = r.books[b] || {}; return [x.over?.american ?? '', x.under?.american ?? '', pct(x.p), tick.used[b] ? iso(tick.at?.[b]) : '']; };
    const kind = Object.values(r.books).some(x => x.novig) ? 'no-vig' : 'implied (one-sided)';
    const gaps = r.gaps || { DK_FD: r.gapPts };
    return [etTime(tick.t), iso(tick.t), tick.id, tick.aligned ? 'yes' : 'no', tick.spreadMs ?? '', tick.game, r.player, marketLabel(r), r.line,
      ...bk('DK'), ...bk('FD'), ...bk('OURS'), kind, fmt(gaps.OURS_DK), fmt(gaps.OURS_FD), fmt(gaps.DK_FD)];
  });
}

export function toCsv(rows) {
  const cell = (v) => { const s = String(v ?? ''); return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s; };
  return [CSV_HEADERS, ...rows].map(r => r.map(cell).join(',')).join('\n') + '\n';
}
