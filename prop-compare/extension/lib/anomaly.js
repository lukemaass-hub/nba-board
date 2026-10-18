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

/** One log row per anomaly per pull: the time of that pull and that pull's prices. */
export function anomalyRows(found, tick, teamFn = () => '') {
  return found.map(a => ({
    id: `${tick.gameKey}|${tick.id}|${a.key}`, gameKey: tick.gameKey, game: tick.game, t: tick.t, tickId: tick.id,
    key: a.key, player: a.player, team: teamFn(a.player) || '', kind: a.kind, line: a.line, side: a.side, why: a.why,
    ours: a.ours, dk: a.dk, fd: a.fd, avg: a.avg, pct: a.pct, pctDk: a.pctDk, pctFd: a.pctFd, size: a.size,
  }));
}

export const ANOMALY_HEADERS = ['time_mt', 'pull', 'game', 'team', 'player', 'market', 'line', 'side', 'why',
  'ours', 'dk', 'fd', 'dk_fd_avg', 'pct_off_avg', 'pct_off_dk', 'pct_off_fd'];

export function anomalyRecord(e, marketLabel) {
  const pct = (v) => v == null ? '' : v.toFixed(1);
  return [mtTime(e.t), e.tickId, e.game, e.team, e.player, marketLabel(e), e.line, e.side, e.why || '',
    e.ours, e.dk ?? '', e.fd ?? '', e.avg ?? '', pct(e.pct), pct(e.pctDk), pct(e.pctFd)];
}
