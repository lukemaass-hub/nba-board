// Lines up DK, FD and our (Dolly App) odds taken in the same tick.
//
// Alignment rule (the user's): never compare a price from one moment with a price from
// another. Both books are requested at the same instant each tick; a book's snapshot
// counts only if it answered within `toleranceMs` of the fastest book. A late or failed
// book is "missing" for that tick and is never filled from an earlier tick.

import { playerMatch, playerKey } from './match.js';

export const BOOKS = ['DK', 'FD', 'OURS'];   // OURS = the App price on the Dolly Market Manager screen

// American odds on one continuous scale, for graphs and sorting: -110 -> -10, +110 -> +10, -100 / +100 -> 0
// (so the jump between -100 and +100 doesn't distort a line that crosses even money)
export const oddsScale = (a) => { const n = Number(String(a).replace('+', '')); return !Number.isFinite(n) ? null : n >= 100 ? n - 100 : n <= -100 ? n + 100 : 0; };
export const oddsLabel = (v) => v >= 0 ? `+${Math.round(v + 100)}` : String(Math.round(v - 100));

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
  // how far our over price is from each book's, on the continuous odds scale (used for sorting only)
  for (const r of rows.values()) {
    const o = oddsScale(r.books.OURS?.over?.american);
    r.diff = Math.max(...['DK', 'FD'].map(b => { const x = oddsScale(r.books[b]?.over?.american); return o != null && x != null ? Math.abs(o - x) : -1; }));
  }
  return [...rows.values()].sort((a, b) => a.player.localeCompare(b.player) || a.kind.localeCompare(b.kind) || a.line - b.line);
}

export const marketLabel = (r) => r.kind === 'ou' ? `Points O/U ${r.line}` : `${r.line + 0.5}+ points`;

// ---------------------------------------------------------------- export
export const CSV_HEADERS = ['tick_time_mt', 'tick_time_utc', 'tick_id', 'aligned', 'spread_ms', 'game', 'team', 'player', 'market', 'line',
  'dk_over', 'dk_under', 'dk_fetched_utc', 'fd_over', 'fd_under', 'fd_fetched_utc', 'ours_over', 'ours_under', 'ours_fetched_utc'];

const mtFmt = new Intl.DateTimeFormat('en-US', { timeZone: 'America/Denver', year: 'numeric', month: '2-digit', day: '2-digit',
  hour: '2-digit', minute: '2-digit', second: '2-digit', hourCycle: 'h23' });
/** All times are Mountain Time (the user's choice). */
export const mtTime = (ms) => mtFmt.format(new Date(ms)).replace(',', '');
const iso = (ms) => ms ? new Date(ms).toISOString() : '';

/** One flat array per row per tick: what goes to CSV and to Google Sheets. */
export function tickToRecords(tick, teamFn = () => '') {
  return tick.rows.map(r => {
    const bk = (b) => { const x = r.books[b] || {}; return [x.over?.american ?? '', x.under?.american ?? '', tick.used[b] ? iso(tick.at?.[b]) : '']; };
    return [mtTime(tick.t), iso(tick.t), tick.id, tick.aligned ? 'yes' : 'no', tick.spreadMs ?? '', tick.game, teamFn(r.player) || '', r.player, marketLabel(r), r.line,
      ...bk('DK'), ...bk('FD'), ...bk('OURS')];
  });
}

/** Tab-separated text (for pasting into a new Google Sheet). */
export function toTsv(rows) {
  return [CSV_HEADERS, ...rows].map(r => r.map(v => String(v ?? '').replace(/[\t\n]/g, ' ')).join('\t')).join('\n') + '\n';
}

export function toCsv(rows) {
  const cell = (v) => { const s = String(v ?? ''); return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s; };
  return [CSV_HEADERS, ...rows].map(r => r.map(cell).join(',')).join('\n') + '\n';
}
