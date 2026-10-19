// Which team each player is on, for the team buttons. ESPN's public NBA team rosters (the same
// source the injury board uses). Fetched once per game and cached for the session.
import { teamNick, playerMatch } from './match.js';

const ESPN = 'https://site.api.espn.com/apis/site/v2/sports/basketball/nba';
let teamsP = null;
const rosterCache = new Map();   // espn team id -> [player names]

async function getJson(url) {
  const r = await fetch(url, { credentials: 'omit' });
  if (!r.ok) throw new Error(`ESPN HTTP ${r.status}`);
  return r.json();
}

async function espnTeams() {
  teamsP ||= getJson(`${ESPN}/teams`).then(d => d.sports[0].leagues[0].teams.map(x => x.team))
    .catch(e => { teamsP = null; throw e; });
  return teamsP;
}

/** -> [{ name: 'Boston Celtics', abbr: 'BOS', players: [...] }] for the two teams of a game */
export async function gameRosters(awayName, homeName) {
  const teams = await espnTeams();
  const out = [];
  for (const nm of [awayName, homeName]) {
    const t = teams.find(x => teamNick(x.displayName) === teamNick(nm));
    if (!t) { out.push({ name: nm, abbr: nm, players: [] }); continue; }
    if (!rosterCache.has(t.id)) rosterCache.set(t.id, (await getJson(`${ESPN}/teams/${t.id}/roster`)).athletes.map(a => a.displayName).filter(Boolean));
    out.push({ name: t.displayName, abbr: t.abbreviation, players: rosterCache.get(t.id) });
  }
  return out;
}

/** abbr of the team a player is on, or null */
export function teamOf(player, rosters) {
  for (const t of rosters || []) if (t.players.some(p => playerMatch(p, player))) return t.abbr;
  return null;
}
