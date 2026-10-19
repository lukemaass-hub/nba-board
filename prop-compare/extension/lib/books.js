// DraftKings + FanDuel player-points prices, from the books' own public JSON APIs.
//
// Request handling (cache-busting, per-book backoff, header rules) is ported from the
// MLB In-Play Suite's background/book-api.js, which runs these endpoints in production.
// The NBA market mapping is new:
//   FD  slate:  content-managed-page?page=CUSTOM&customPageId=nba        (verified 2026-10-16)
//       props:  event-page?eventId=..&tab=player-points                   (verified 2026-10-16)
//               "<Player> - Points"  PLAYER_x_TOTAL_POINTS  runners "<Player> Over/Under", handicap = line
//               "To Score N+ Points" TO_SCORE_N+_POINTS     runners = players, line = N - 0.5
//   DK  league 42648 (NBA); player-points subcategory ids are NOT verified from here (DK blocks
//       non-browser traffic). They are a settings list: each is tried, the ones that return
//       selections are kept, and the dashboard shows which worked.
//
// Every price is returned as a "quote":
//   { book, player, kind: 'ou' | 'alt', line, side: 'over' | 'under', american, decimal }
// kind 'ou' = over/under market (both sides); 'alt' = "N+" milestone (over only).

export const FD_AK = 'FhMFpcPWXMeyZxOx';   // FD's public web key; if FD rotates it every FD call 401s (see README)
export const DK_HOST = 'sportsbook-nash.draftkings.com';
let dkHost = DK_HOST;
/** Use the API host DraftKings' own page was seen using (see background.js). */
export function setDkHost(h) { dkHost = h || DK_HOST; }
const REQUEST_TIMEOUT_MS = 12_000;
const DK_HEADERS = { accept: '*/*', 'x-client-name': 'web', 'x-client-page': 'event' };

// ---------------------------------------------------------------- HTTP with backoff
const backoff = { DK: { until: 0, fails: 0 }, FD: { until: 0, fails: 0 } };
export function isBackingOff(book) { return Date.now() < backoff[book].until; }
function noteFailure(book, retryAfterSec) {
  const b = backoff[book];
  b.fails += 1;
  const base = retryAfterSec != null ? retryAfterSec * 1000 : Math.min(5 * 60_000, 5_000 * 2 ** (b.fails - 1));
  b.until = Date.now() + base + Math.random() * 1000;
  return Math.round((b.until - Date.now()) / 1000);
}
let cb = 0;
const bust = () => `_cb=${Date.now()}${++cb}`;   // the books' CDNs serve stale prices otherwise

export async function getJson(url, book, headers = {}) {
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), REQUEST_TIMEOUT_MS);
  let res;
  try {
    res = await fetch(url, { signal: ctrl.signal, credentials: 'omit', headers: { accept: 'application/json, text/plain, */*', ...headers } });
  } finally { clearTimeout(timer); }
  if (res.status === 429 || res.status === 403 || res.status >= 500) {
    const ra = parseFloat(res.headers.get('Retry-After'));
    const secs = noteFailure(book, Number.isFinite(ra) ? ra : null);
    const hint = res.status === 403 && book === 'DK' ? ' (DK blocks requests without the site Origin header: is rules/book-api-headers.json loaded?)'
      : res.status === 500 && book === 'FD' ? ' (FD rejects an extension Origin: is rules/book-api-headers.json loaded?)' : '';
    throw new Error(`${book} HTTP ${res.status}, retrying in ${secs}s${hint}`);
  }
  if (!res.ok) throw new Error(`${book} HTTP ${res.status}`);
  backoff[book].fails = 0; backoff[book].until = 0;
  return res.json();
}

// ---------------------------------------------------------------- odds helpers
export function decimalFromAmerican(a) {
  const n = Number(String(a).replace('−', '-').replace('+', ''));
  if (!Number.isFinite(n) || n === 0) return null;
  return n > 0 ? 1 + n / 100 : 1 + 100 / -n;
}
const americanStr = (n) => (n == null || !Number.isFinite(Number(n)) || Number(n) === 0) ? null : (Number(n) > 0 ? `+${Number(n)}` : String(Number(n)));
const cleanTeam = (s) => String(s || '').replace(/\s*\([^)]*\)\s*/g, ' ').replace(/\s{2,}/g, ' ').trim();

// ---------------------------------------------------------------- FanDuel
const fdBase = (state) => `https://sbapi.${state}.sportsbook.fanduel.com/api`;

/** NBA games on FanDuel: [{ eventId, name, away, home, startTime }] */
export async function fdGames(state) {
  const json = await getJson(`${fdBase(state)}/content-managed-page?page=CUSTOM&customPageId=nba&_ak=${FD_AK}&timezone=America%2FNew_York`, 'FD');
  return parseFdGames(json);
}
export function parseFdGames(json) {
  const out = [];
  const comps = json?.attachments?.competitions || {};
  for (const ev of Object.values(json?.attachments?.events || {})) {
    // FD's NBA page also carries eBasketball ("Toronto Raptors (FRENZY) @ ...") under its own competition
    const comp = String(comps[ev.competitionId]?.name || '');
    if (/^e|esport|2k|sim/i.test(comp) || /\(/.test(ev.name || '')) continue;
    const parts = String(ev.name || '').split('@').map(cleanTeam).filter(Boolean);
    if (parts.length !== 2) continue;   // futures / awards
    out.push({ eventId: String(ev.eventId), name: `${parts[0]} @ ${parts[1]}`, away: parts[0], home: parts[1],
               competition: comp, startTime: Date.parse(ev.openDate) || null });
  }
  return out.sort((a, b) => (a.startTime || 0) - (b.startTime || 0));
}

/** The event page's tabs that carry player points (titles like "Player Points" / "Live Player Points"). */
export async function fdPointsTabs(state, eventId) {
  const json = await getJson(`${fdBase(state)}/event-page?eventId=${eventId}&_ak=${FD_AK}&timezone=America%2FNew_York&${bust()}`, 'FD');
  const tabs = Object.values(json?.layout?.tabs || {});
  const slugs = tabs.map(t => String(t.title || '')).filter(t => /points/i.test(t) && !/combo/i.test(t))
    .map(t => t.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, ''));
  return slugs;   // [] = FD has no player points for this game (yet); preseason games usually have none
}

export async function fdQuotes(state, eventId, tabs) {
  const markets = [];
  for (const tab of tabs) {
    const json = await getJson(`${fdBase(state)}/event-page?eventId=${eventId}&_ak=${FD_AK}&timezone=America%2FNew_York&tab=${tab}&${bust()}`, 'FD');
    markets.push(...Object.values(json?.attachments?.markets || {}));
  }
  return parseFdQuotes(markets);
}

export function parseFdQuotes(markets) {
  const out = [], seen = new Set();
  const push = (q) => { const k = `${q.player}|${q.kind}|${q.line}|${q.side}`; if (!seen.has(k)) { seen.add(k); out.push(q); } };
  for (const m of markets) {
    if (String(m?.marketStatus || '').toUpperCase() !== 'OPEN') continue;
    const type = String(m.marketType || ''), name = String(m.marketName || '');
    const runners = (m.runners || []).filter(r => String(r?.runnerStatus || '').toUpperCase() === 'ACTIVE');
    const oddsOf = (r) => {
      const am = r?.winRunnerOdds?.americanDisplayOdds?.americanOdds;
      const dec = r?.winRunnerOdds?.trueOdds?.decimalOdds?.decimalOdds;   // fallback only: we compare the price bettors see
      return { american: americanStr(am), decimal: decimalFromAmerican(am) ?? (Number.isFinite(dec) ? dec : null) };
    };
    const alt = type.match(/^TO_SCORE_(\d+)\+_POINTS$/);
    if (alt) {                                            // "To Score 20+ Points": every runner is a player
      const line = parseInt(alt[1], 10) - 0.5;
      for (const r of runners) {
        const o = oddsOf(r);
        if (o.american && r.runnerName) push({ book: 'FD', player: String(r.runnerName).trim(), kind: 'alt', line, side: 'over', ...o });
      }
      continue;
    }
    // "<Player> - Points" (main line) and any "<Player> - Alt Points" style O/U market
    if (/POINTS/.test(type) && / - .*points/i.test(name) && !/rebound|assist|three|combo|\+/i.test(name)) {
      const player = name.split(' - ')[0].trim();
      for (const r of runners) {
        const side = /\bover\b/i.test(r.runnerName) ? 'over' : /\bunder\b/i.test(r.runnerName) ? 'under' : null;
        const o = oddsOf(r);
        if (side && o.american && r.handicap != null) push({ book: 'FD', player, kind: 'ou', line: Number(r.handicap), side, ...o });
      }
    }
  }
  return out;
}

// ---------------------------------------------------------------- DraftKings
function dkLeagueUrl(site, league, subId) {
  const eventsQuery = `$filter=leagueId eq '${league}' AND clientMetadata/Subcategories/any(s: s/Id eq '${subId}')`;
  const marketsQuery = `$filter=clientMetadata/subCategoryId eq '${subId}' AND tags/all(t: t ne 'SportcastBetBuilder')`;
  return `https://${dkHost}/sites/${site}/api/sportscontent/controldata/league/leagueSubcategory/v1/markets`
    + `?isBatchable=false&templateVars=${league}&eventsQuery=${encodeURIComponent(eventsQuery)}`
    + `&marketsQuery=${encodeURIComponent(marketsQuery)}&include=Events&entity=events&${bust()}`;
}
function dkEventUrl(site, eventId, subId) {
  const marketsQuery = `$filter=eventId eq '${eventId}' AND clientMetadata/subCategoryId eq '${subId}' AND tags/all(t: t ne 'SportcastBetBuilder')`;
  return `https://${dkHost}/sites/${site}/api/sportscontent/controldata/event/eventSubcategory/v1/markets`
    + `?isBatchable=false&templateVars=${eventId}%2C${subId}&marketsQuery=${encodeURIComponent(marketsQuery)}&entity=markets&${bust()}`;
}

/** NBA games on DraftKings, found through whichever league + subcategory answers first.
 *  Returns { games: [{eventId, name, away, home, startTime}], tried: [{league, subId, status, events}] } */
export async function dkGames(site, leagues, subIds) {
  const tried = [];
  for (const league of leagues) for (const subId of subIds) {
    try {
      const json = await getJson(dkLeagueUrl(site, league, subId), 'DK', { ...DK_HEADERS, 'x-client-page': 'league' });
      const games = parseDkGames(json);
      tried.push({ league, subId, status: 'ok', events: games.length });
      if (games.length) return { games, tried };
    } catch (e) {
      tried.push({ league, subId, status: String(e.message || e), events: 0 });
      if (isBackingOff('DK')) return { games: [], tried };
    }
  }
  return { games: [], tried };
}
export function parseDkGames(json) {
  const out = [];
  for (const ev of (json?.events || [])) {
    const ps = ev.participants || [];
    const away = ps.find(p => p.venueRole === 'Away')?.name, home = ps.find(p => p.venueRole === 'Home')?.name;
    if (!away || !home) continue;
    out.push({ eventId: String(ev.id), name: `${cleanTeam(away)} @ ${cleanTeam(home)}`, away: cleanTeam(away), home: cleanTeam(home),
               startTime: Date.parse(ev.startEventDate || ev.startDate || '') || null });
  }
  return out;
}

/** Raw sample of the last DK answer we couldn't read (for Diagnostics). */
export let lastDkSample = null;

/** Player-points quotes for one DK event. Returns { quotes, perSub: {subId: count | error} } */
export async function dkQuotes(site, eventId, subIds) {
  const quotes = [], perSub = {};
  const lists = await Promise.all(subIds.map(subId =>
    getJson(dkEventUrl(site, eventId, subId), 'DK', DK_HEADERS).then(j => ({ j, q: parseDkQuotes(j) })).catch(e => e)));
  lists.forEach((r, i) => {
    if (r instanceof Error) { perSub[subIds[i]] = String(r.message || r); return; }
    const sels = r.j?.selections?.length || 0;
    if (!r.q.length && sels) {   // DK answered with prices we couldn't read: say what it sent
      lastDkSample = { subId: subIds[i], markets: (r.j.markets || []).slice(0, 3), selections: r.j.selections.slice(0, 3) };
      perSub[subIds[i]] = `0 prices read from ${sels} selections (markets: ${(r.j.markets || []).slice(0, 4).map(m => m.name || m.marketType?.name).join(' | ')})`;
    } else perSub[subIds[i]] = r.q.length;
    quotes.push(...r.q);
  });
  const seen = new Set();
  return { quotes: quotes.filter(q => { const k = `${q.player}|${q.kind}|${q.line}|${q.side}`; if (seen.has(k)) return false; seen.add(k); return true; }), perSub };
}

export function parseDkQuotes(json) {
  const out = [];
  const marketName = new Map((json?.markets || []).map(m => [String(m.id), String(m.name || m.marketType?.name || '')]));
  for (const s of (json?.selections || [])) {
    if (/suspend/i.test(String(s?.status || ''))) continue;
    const mname = marketName.get(String(s.marketId)) || '';
    if (/rebound|assist|three|\bpra\b|\+ ?reb|\+ ?ast|combo/i.test(mname)) continue;   // points only
    const p = (s.participants && s.participants[0]) || null;
    const player = String(p ? (p.name || '') : '').trim();
    const american = String(s?.displayOdds?.american || '').replace(/−/g, '-').trim();
    if (!player || !/^[+-]\d{2,}$/.test(american)) continue;
    const decimal = Number(s?.displayOdds?.decimal) || decimalFromAmerican(american);
    const label = String(s.label || '').replace(/\s/g, '');
    const otype = String(s.outcomeType || '').toLowerCase();
    if (typeof s.milestoneValue === 'number') out.push({ book: 'DK', player, kind: 'alt', line: s.milestoneValue - 0.5, side: 'over', american, decimal });
    else if (/^\d+\+$/.test(label)) out.push({ book: 'DK', player, kind: 'alt', line: parseInt(label, 10) - 0.5, side: 'over', american, decimal });
    else if ((otype === 'over' || otype === 'under') && typeof s.points === 'number')
      out.push({ book: 'DK', player, kind: 'ou', line: s.points, side: otype, american, decimal });
  }
  return out;
}
