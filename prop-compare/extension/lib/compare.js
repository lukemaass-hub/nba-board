// Lines up DK and FD quotes taken in the same tick, and works out the gap between them.
//
// Alignment rule (the user's): never compare a price from one moment with a price from
// another. Both books are requested at the same instant each tick; a book's snapshot
// counts only if it answered within `toleranceMs` of the fastest book. A late or failed
// book is "missing" for that tick and is never filled from an earlier tick.

import { playerMatch, playerKey } from './match.js';

export const BOOKS = ['DK', 'FD'];   // "OURS" (Dolly) joins later

/** Decide which books count for this tick.
 *  results: { DK: {ok, at, quotes, error}, FD: {...} }  ->  { aligned, used: {DK: bool, FD: bool}, spreadMs } */
export function alignTick(results, toleranceMs) {
  const ok = BOOKS.filter(b => results[b]?.ok);
  if (!ok.length) return { aligned: false, used: { DK: false, FD: false }, spreadMs: null };
  const first = Math.min(...ok.map(b => results[b].at));
  const used = {};
  for (const b of BOOKS) used[b] = !!results[b]?.ok && results[b].at - first <= toleranceMs;
  const usedAts = BOOKS.filter(b => used[b]).map(b => results[b].at);
  const spreadMs = ok.length > 1 ? Math.max(...ok.map(b => results[b].at)) - first : null;
  return { aligned: BOOKS.every(b => used[b]), used, spreadMs, firstAt: first, lastUsedAt: Math.max(...usedAts) };
}

/** Two-way no-vig probability of the over; one-sided lines (alt "N+") fall back to plain implied. */
export function overProb(over, under) {
  if (!over?.decimal) return { p: null, novig: false };
  const po = 1 / over.decimal;
  if (under?.decimal) { const pu = 1 / under.decimal; return { p: po / (po + pu), novig: true }; }
  return { p: po, novig: false };
}

/** Rows for the table / export. One row per player + market kind + line.
 *  quotesByBook: { DK: [quote], FD: [quote] } (books not used this tick: [] or missing) */
export function buildRows(quotesByBook) {
  // Canonical player names: FD first (its names are full), then any DK-only player.
  const names = [];
  const canon = (name) => {
    for (const n of names) if (playerMatch(n, name)) return n;
    names.push(name); return name;
  };
  const rows = new Map();
  for (const book of ['FD', 'DK']) {
    for (const q of quotesByBook[book] || []) {
      const player = canon(q.player);
      const key = `${playerKey(player)}|${q.kind}|${q.line}`;
      if (!rows.has(key)) rows.set(key, { key, player, kind: q.kind, line: q.line, books: {} });
      const r = rows.get(key);
      (r.books[book] ||= {})[q.side] = { american: q.american, decimal: q.decimal };
    }
  }
  for (const r of rows.values()) {
    for (const [book, sides] of Object.entries(r.books)) Object.assign(sides, overProb(sides.over, sides.under));
    const dk = r.books.DK?.p, fd = r.books.FD?.p;
    // Gap only when both books price it the same way (both no-vig, or both one-sided).
    r.gapPts = (dk != null && fd != null && r.books.DK.novig === r.books.FD.novig) ? (dk - fd) * 100 : null;
  }
  return [...rows.values()].sort((a, b) => a.player.localeCompare(b.player) || a.kind.localeCompare(b.kind) || a.line - b.line);
}

export const marketLabel = (r) => r.kind === 'ou' ? `Points O/U ${r.line}` : `${r.line + 0.5}+ points`;

// ---------------------------------------------------------------- export
export const CSV_HEADERS = ['tick_time_et', 'tick_time_utc', 'tick_id', 'aligned', 'spread_ms', 'game', 'player', 'market', 'line',
  'dk_over', 'dk_under', 'dk_over_prob', 'dk_fetched_utc', 'fd_over', 'fd_under', 'fd_over_prob', 'fd_fetched_utc',
  'prob_kind', 'gap_pts_dk_minus_fd'];

const etFmt = new Intl.DateTimeFormat('en-US', { timeZone: 'America/New_York', year: 'numeric', month: '2-digit', day: '2-digit',
  hour: '2-digit', minute: '2-digit', second: '2-digit', hourCycle: 'h23' });
export const etTime = (ms) => etFmt.format(new Date(ms)).replace(',', '');
const iso = (ms) => ms ? new Date(ms).toISOString() : '';
const pct = (p) => p == null ? '' : (p * 100).toFixed(2);

/** One flat array per row per tick: what goes to CSV and to Google Sheets. */
export function tickToRecords(tick) {
  return tick.rows.map(r => {
    const dk = r.books.DK || {}, fd = r.books.FD || {};
    const kind = (dk.novig || fd.novig) ? 'no-vig' : 'implied (one-sided)';
    return [etTime(tick.t), iso(tick.t), tick.id, tick.aligned ? 'yes' : 'no', tick.spreadMs ?? '', tick.game, r.player, marketLabel(r), r.line,
      dk.over?.american ?? '', dk.under?.american ?? '', pct(dk.p), tick.used.DK ? iso(tick.at.DK) : '',
      fd.over?.american ?? '', fd.under?.american ?? '', pct(fd.p), tick.used.FD ? iso(tick.at.FD) : '',
      kind, r.gapPts == null ? '' : r.gapPts.toFixed(2)];
  });
}

export function toCsv(rows) {
  const cell = (v) => { const s = String(v ?? ''); return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s; };
  return [CSV_HEADERS, ...rows].map(r => r.map(cell).join(',')).join('\n') + '\n';
}
