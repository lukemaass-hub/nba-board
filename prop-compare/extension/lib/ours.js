// OUR prices, from the Fanatics content feed: the same source and method as the MLB
// In-Play Suite's background/ml-injector.js (fetchOurFeed / resolveEventId):
//   event prices:  https://content.1.betfanatics.com/page/event/{eventId}   (credentials: include)
//   slate lookup:  https://content.1.betfanatics.com/cardpack/INS/<base64 JSON {paths,...}>?channel=..&segment=..&stateCode=..
// MLB's slate paths are known ('8:1255:1257'); NBA's are not, so background.js learns the
// paths, query and event ids from our own sportsbook site while the user browses it.
//
// Market codes: MLB alt props are e.g. BASEBALL:FT:PROPALTH with selections "Player N+".
// NBA points codes aren't confirmed, so any BASKETBALL market whose code or name says
// points (and not rebounds/assists/threes/combos) is read; every code seen is reported.

const FEED = 'https://content.1.betfanatics.com';
const TIMEOUT_MS = 12_000;
export const DEFAULT_SLATE_PARAMS = { eventStateOptions: 'All', eventsFromDay: 3, eventLimit: 30, enableStreamingEvents: false, orderEventsChronologically: true };
export const DEFAULT_CARDPACK_QUERY = 'channel=AMELCO_TN_MASTER&segment=AMELCO_TN&stateCode=TN';   // the MLB suite's (TN)

/** What the last feed request did (for the Test button / Diagnostics). */
export let lastFeed = null;

async function directFetch(url) {
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), TIMEOUT_MS);
  try {
    const res = await fetch(url, { credentials: 'include', signal: ctrl.signal, cache: 'no-store' });
    return { status: res.status, text: await res.text(), type: res.headers.get('content-type') || '' };
  } finally { clearTimeout(timer); }
}
// The MLB suite fetches the feed from its background service worker; do the same as a fallback.
const viaBackground = (url) => new Promise((resolve, reject) =>
  chrome.runtime.sendMessage({ type: 'OURS_FETCH', url }, (r) => chrome.runtime.lastError ? reject(new Error(chrome.runtime.lastError.message)) : r?.error ? reject(new Error(r.error)) : resolve(r)));

async function getFeed(url) {
  const tries = [];
  for (const [via, fn] of [['dashboard', directFetch], ['background', viaBackground]]) {
    try {
      const r = await fn(url);
      let json = null; try { json = JSON.parse(r.text); } catch { /* not JSON */ }
      tries.push(`${via}: HTTP ${r.status}, ${r.text.length} bytes${json ? '' : `, not JSON (${r.type}) starts "${r.text.slice(0, 80).replace(/\s+/g, ' ')}"`}`);
      lastFeed = { url, at: Date.now(), tries, text: r.text };
      if (r.status >= 200 && r.status < 300 && json) return json;
    } catch (e) { tries.push(`${via}: ${String(e.message || e)}`); lastFeed = { url, at: Date.now(), tries, text: '' }; }
  }
  throw new Error(`our feed failed: ${tries.join(' | ')}`);
}

/** Look at one event in our feed: what came back, which markets, what we could read. */
export async function testOurEvent(eventId) {
  const url = `${FEED}/page/event/${encodeURIComponent(eventId)}`;
  const out = { eventId, url };
  try {
    const json = await getFeed(url);
    const ev = parseOurSlate(json).find(x => x.eventId === String(eventId)) || parseOurSlate(json)[0];
    const parsed = parseOurQuotes(json);
    Object.assign(out, { ok: true, event: ev ? `${ev.name} (${ev.participants.map(p => p[0]).join(' / ')})` : 'no event object found in the answer',
      marketCount: Object.keys(parsed.types).length, types: parsed.types, pointsPrices: parsed.quotes.length,
      sample: parsed.quotes.slice(0, 4), unread: parsed.unread, topKeys: Object.keys(json || {}).slice(0, 20) });
  } catch (e) { Object.assign(out, { ok: false, error: String(e.message || e) }); }
  out.tries = lastFeed?.tries;
  return out;
}

export const americanFromDecimal = (d) => {
  if (!(d > 1)) return null;
  const a = d >= 2 ? Math.round((d - 1) * 100) : Math.round(-100 / (d - 1));
  return a > 0 ? `+${a}` : String(a);
};

// ---------------------------------------------------------------- slate (event lookup)
export function cardpackUrl(paths, params = DEFAULT_SLATE_PARAMS, query = DEFAULT_CARDPACK_QUERY) {
  return `${FEED}/cardpack/INS/${btoa(JSON.stringify({ paths, ...params }))}?${query}`;
}

/** Our NBA games: [{ eventId, name, teams: [nickname-ish names...], startTime }] */
export async function ourGames(paths, params, query) {
  if (!paths?.length) return [];
  return parseOurSlate(await getFeed(cardpackUrl(paths, params, query)));
}
export function parseOurSlate(json) {
  const byId = new Map();
  (function walk(n) {
    if (Array.isArray(n)) return n.forEach(walk);
    if (!n || typeof n !== 'object') return;
    const ev = n.event;
    if (ev?.id && Array.isArray(ev.participants) && ev.participants.length >= 2 && !byId.has(String(ev.id))) {
      byId.set(String(ev.id), {
        eventId: String(ev.id), name: ev.name || ev.participants.map(p => p.name).join(' v '),
        participants: ev.participants.map(p => [p.name, p.shortName, p.veryshortName, p.abbreviation].filter(Boolean)),
        startTime: Date.parse(ev.startTime || ev.startDate || ev.eventTime || ev.start || '') || null,
      });
    }
    for (const k in n) walk(n[k]);
  })(json);
  return [...byId.values()];
}

// ---------------------------------------------------------------- event prices
const POINTS = /point|pts/i, NOT_POINTS = /rebound|assist|three|3pt|3-pt|steal|block|combo|\+ ?(reb|ast)|pra|double|first|quarter|half|1st|2nd|3rd|4th|team/i;

/** Every market object (has a colon "type" code and a selection array), deduped by id. */
function collectMarkets(json) {
  const out = [], seen = new Set();
  (function walk(n) {
    if (Array.isArray(n)) return n.forEach(walk);
    if (!n || typeof n !== 'object') return;
    if (typeof n.type === 'string' && n.type.includes(':') && Array.isArray(n.selection)) {
      const key = n.id || JSON.stringify(n.selection.map(s => s.id));
      if (!seen.has(key)) { seen.add(key); out.push(n); }
    }
    for (const k in n) walk(n[k]);
  })(json);
  return out;
}

export async function ourQuotes(eventId) {
  return parseOurQuotes(await getFeed(`${FEED}/page/event/${encodeURIComponent(eventId)}`));
}

/** -> { quotes: [quote], types: {code: name}, unread: [sample market] } */
export function parseOurQuotes(json) {
  const quotes = [], types = {}, unread = [];
  for (const m of collectMarkets(json)) {
    types[m.type] = m.name || '';
    const desc = `${m.type} ${m.name || ''}`;
    if (!/^BASKETBALL:/i.test(m.type) || !POINTS.test(desc) || NOT_POINTS.test(m.name || '')) continue;
    if (/:(ML|SPRD|OU)$/i.test(m.type) || /^(game\s+)?total points$/i.test(String(m.name || '').trim())) continue;   // game lines
    if (!/PROP|PLAYER|PLY/i.test(m.type) && !/player|points/i.test(m.name || '')) continue;
    let n = 0;
    for (const s of m.selection) {
      const decimal = parseFloat(s.decimalOdds);
      if (!(decimal > 1) || /suspend|closed|settled|void/i.test(String(s.state || ''))) continue;
      const american = americanFromDecimal(decimal);
      // alt: "Player N+" in the selection's name/type (or market name)
      const label = [s.type, s.name, m.name].find(x => /\d+\s*\+\s*$/.test(String(x || '').trim())) || '';
      const alt = String(label).trim().match(/^(.+?)\s+(\d+)\s*\+$/);
      if (alt) { quotes.push({ book: 'OURS', player: alt[1].replace(/\s*-\s*$/, '').trim(), kind: 'alt', line: parseInt(alt[2], 10) - 0.5, side: 'over', american, decimal }); n++; continue; }
      // O/U: "Over"/"Under" (+ line) with the player in the market name
      const side = /\bover\b/i.test(`${s.type} ${s.name}`) ? 'over' : /\bunder\b/i.test(`${s.type} ${s.name}`) ? 'under' : null;
      const ln = m.line != null ? Number(m.line) : parseFloat((String(s.name || '').match(/(\d+(?:\.\d+)?)\s*$/) || [])[1]);
      const player = String(m.name || '').replace(/\s*[-–:]?\s*(total\s+)?points?\b.*$/i, '').replace(/\s*(over\/under|o\/u)\s*$/i, '').trim();
      if (side && Number.isFinite(ln) && player) { quotes.push({ book: 'OURS', player, kind: 'ou', line: ln, side, american, decimal }); n++; }
    }
    if (!n && unread.length < 3) unread.push({ type: m.type, name: m.name, line: m.line, selection: m.selection.slice(0, 3) });
  }
  return { quotes, types, unread };
}
