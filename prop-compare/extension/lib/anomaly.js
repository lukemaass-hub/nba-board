// Anomalies: our price is far from the market. Checked per side (over / under) on each pull,
// using only odds pulled in that same moment. "% off" compares the chance each price implies:
//   pct vs X = (ours − X) / X × 100
// A side is flagged when EITHER
//   • it is at least `avgPct` off the average of DraftKings and FanDuel (needs both), OR
//   • it is at least `bookPct` off DraftKings or FanDuel on its own (works with just one book),
// so one book being way off on a pull can't hide (or fake) a gap on its own.
// Positive = we imply a HIGHER chance (our odds are shorter); negative = LOWER (we pay more).
import { mtTime } from './compare.js';

export const impliedProb = (american) => {
  const n = Number(String(american ?? '').replace('+', ''));
  if (!Number.isFinite(n) || Math.abs(n) < 100) return null;
  return n > 0 ? 100 / (n + 100) : -n / (-n + 100);
};
export const americanFromProb = (p) => {
  if (!(p > 0 && p < 1)) return null;
  const a = p >= 0.5 ? -Math.round((p / (1 - p)) * 100) : Math.round(((1 - p) / p) * 100);
  return a > 0 ? `+${a}` : String(a);
};

const rel = (po, px) => (po - px) / px * 100;

/** -> [{ key, side, player, kind, line, ours, dk, fd, avg, pct, pctDk, pctFd, why }] for this tick's rows */
export function findAnomalies(rows, avgPct = 10, bookPct = 20) {
  const out = [];
  for (const r of rows) for (const side of ['over', 'under']) {
    const o = r.books.OURS?.[side]?.american, d = r.books.DK?.[side]?.american, f = r.books.FD?.[side]?.american;
    const po = impliedProb(o), pd = impliedProb(d), pf = impliedProb(f);
    if (po == null || (pd == null && pf == null)) continue;
    const avg = pd != null && pf != null ? (pd + pf) / 2 : null;
    const pct = avg != null ? rel(po, avg) : null, pctDk = pd != null ? rel(po, pd) : null, pctFd = pf != null ? rel(po, pf) : null;
    const why = [];
    if (pct != null && Math.abs(pct) >= avgPct) why.push(`${avgPct}%+ off avg`);
    if (pctDk != null && Math.abs(pctDk) >= bookPct) why.push(`${bookPct}%+ off DK`);
    if (pctFd != null && Math.abs(pctFd) >= bookPct) why.push(`${bookPct}%+ off FD`);
    if (!why.length) continue;
    // the size used for "biggest": % off the average when there is one, else the larger single-book gap
    const size = pct ?? [pctDk, pctFd].filter(v => v != null).sort((x, y) => Math.abs(y) - Math.abs(x))[0];
    out.push({ key: `${r.key}|${side}`, side, player: r.player, kind: r.kind, line: r.line, ours: o, dk: d ?? null, fd: f ?? null,
               avg: avg != null ? americanFromProb(avg) : null, pct, pctDk, pctFd, size, why: why.join(', ') });
  }
  return out;
}

/**
 * Turns each pull's anomalies into episodes: one record from the first pull a side is off until the
 * pull it comes back inside the threshold (or the line disappears). The record keeps the odds at the
 * start, the latest odds, and the biggest gap seen.
 *   open: Map key -> episode (mutated);  returns { changed: [episodes to save] }
 */
const snap = (a) => ({ ours: a.ours, dk: a.dk, fd: a.fd, avg: a.avg, pct: a.pct, pctDk: a.pctDk, pctFd: a.pctFd });

export function updateEpisodes(open, found, tick, extra = {}) {
  const changed = [];
  const now = new Map(found.map(a => [a.key, a]));
  for (const a of found) {
    let e = open.get(a.key);
    if (!e) {
      e = { gameKey: tick.gameKey, game: tick.game, key: a.key, player: a.player, team: extra.teamFn?.(a.player) || '', kind: a.kind, line: a.line, side: a.side,
            startT: tick.t, startTick: tick.id, start: snap(a), peakPct: a.size, peakT: tick.t, peak: snap(a), why: a.why, pulls: 0 };
      open.set(a.key, e);
    }
    e.lastT = tick.t; e.lastTick = tick.id; e.pulls++; e.ongoing = true;
    e.latest = snap(a);
    if (!e.why.split(', ').includes(a.why)) e.why = [...new Set([...e.why.split(', '), ...a.why.split(', ')])].join(', ');
    if (Math.abs(a.size) > Math.abs(e.peakPct)) { e.peakPct = a.size; e.peakT = tick.t; e.peak = snap(a); }
    changed.push(e);
  }
  // a side that is no longer off on an ALIGNED pull: the episode ends
  if (tick.aligned) for (const [k, e] of open) if (!now.has(k)) { e.ongoing = false; e.endT = tick.t; open.delete(k); changed.push(e); }
  return { changed };
}

export const ANOMALY_HEADERS = ['start_mt', 'end_mt', 'ongoing', 'pulls', 'game', 'team', 'player', 'market', 'line', 'side', 'why',
  'ours_start', 'dk_start', 'fd_start', 'avg_start', 'pct_off_avg_start', 'pct_off_dk_start', 'pct_off_fd_start',
  'biggest_pct_off', 'biggest_mt', 'ours_latest', 'dk_latest', 'fd_latest', 'pct_off_avg_latest'];

export function anomalyRecord(e, marketLabel) {
  const pct = (v) => v == null ? '' : v.toFixed(1);
  return [mtTime(e.startT), e.endT ? mtTime(e.endT) : '', e.ongoing ? 'yes' : 'no', e.pulls, e.game, e.team, e.player, marketLabel(e), e.line, e.side, e.why || '',
    e.start.ours, e.start.dk ?? '', e.start.fd ?? '', e.start.avg ?? '', pct(e.start.pct), pct(e.start.pctDk), pct(e.start.pctFd),
    pct(e.peakPct), mtTime(e.peakT), e.latest?.ours ?? '', e.latest?.dk ?? '', e.latest?.fd ?? '', pct(e.latest?.pct)];
}
