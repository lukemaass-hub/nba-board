// Name matching shared by every book. Ported from the MLB suite's prop-apply.js
// (surname must match; if BOTH sides give a full first name they must be equal, so
// "Jacob Young" never matches "Jared Young"; initial-only when one side abbreviates),
// plus accent stripping so "Nikola Jokić" matches "Nikola Jokic".

const SUFFIX = new Set(['jr', 'sr', 'ii', 'iii', 'iv', 'v']);

export function norm(s) {
  return String(s || '').normalize('NFD').replace(/[̀-ͯ]/g, '')
    .toLowerCase().replace(/[^a-z0-9 ]/g, ' ').replace(/\s+/g, ' ').trim();
}

export function nameTokens(s) {
  return norm(s).split(' ').filter(t => t && !SUFFIX.has(t));
}

/** Canonical key for a player: full tokens without suffixes ("Jaren Jackson Jr." -> "jaren jackson"). */
export function playerKey(s) {
  return nameTokens(s).join(' ');
}

export function playerMatch(a, b) {
  const na = nameTokens(a), nb = nameTokens(b);
  if (!na.length || !nb.length) return false;
  if (na.join(' ') === nb.join(' ')) return true;
  if (na[na.length - 1] !== nb[nb.length - 1]) return false;   // surname must match
  const fa = na[0], fb = nb[0];
  if (fa.length > 1 && fb.length > 1) return fa === fb;
  return fa[0] === fb[0];
}

// Team matching: nickname is the anchor ("Los Angeles Lakers" vs "LA Lakers" vs "Lakers").
const NICK2 = ['trail blazers'];
export function teamNick(s) {
  const n = norm(s);
  for (const two of NICK2) if (n.endsWith(two)) return two;
  return n.split(' ').pop() || '';
}

/** "Away @ Home" strings (or [away, home] arrays) describe the same game? */
export function sameGame(a, b) {
  const ta = Array.isArray(a) ? a : String(a).split('@');
  const tb = Array.isArray(b) ? b : String(b).split('@');
  if (ta.length !== 2 || tb.length !== 2) return false;
  return teamNick(ta[0]) === teamNick(tb[0]) && teamNick(ta[1]) === teamNick(tb[1]);
}

// The MLB In-Play Suite's team matching, unchanged (background/ml-injector.js).
function normalizeTeam(s) {
  return (s || '')
    .toLowerCase()
    .replace(/\b(fc|sc|cf)\b/g, '')
    .replace(/[^a-z0-9 ]/g, ' ')
    .replace(/\s+/g, ' ')
    .trim();
}
export function tokenScore(a, b) {
  const ta = normalizeTeam(a).split(' ').filter(Boolean);
  const tb = normalizeTeam(b).split(' ').filter(Boolean);
  if (!ta.length || !tb.length) return 0;
  const la = ta[ta.length - 1], lb = tb[tb.length - 1];
  if (la === lb) {
    if (la === 'sox') return ta[ta.length - 2] === tb[tb.length - 2] ? 1 : 0;
    return 1;
  }
  let hits = 0;
  for (const t of ta) if (tb.includes(t)) hits++;
  return hits / Math.max(ta.length, tb.length);
}
