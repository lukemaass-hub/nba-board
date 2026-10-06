#!/usr/bin/env python3
"""Refresh data.json for the NBA availability board.

Sources (each one is optional; a failure keeps that source's last good data, marked stale):
  schedule   fixturedownload.com JSON feed (all 1,230 games, converted to ET)
  cbs        cbssports.com/nba/injuries
  covers     covers.com NBA injuries
  espn       ESPN public JSON injuries endpoint
  espn_depth ESPN depth charts, all 30 teams (rotation and minutes-up order)
  rotowire   RotoWire expected / confirmed starting lineups for today, plus its "may not play" list
  minutes    your Google Sheet, published to the web as CSV (MINUTES_CSV_URL)
  x          team beat writers on X (X_BEARER_TOKEN + ANTHROPIC_API_KEY + beat_writers.json)

Usage:  python pipeline/update_data.py --out data.json
"""
import argparse, csv, datetime as dt, io, json, os, re, sys, time
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup

ET = ZoneInfo("America/New_York")
UA = {"User-Agent": "Mozilla/5.0 (compatible; availability-board/1.0)"}

TEAMS = {
    "ATL": ["Atlanta Hawks", "Atlanta", "Hawks"], "BOS": ["Boston Celtics", "Boston", "Celtics"],
    "BKN": ["Brooklyn Nets", "Brooklyn", "Nets"], "CHA": ["Charlotte Hornets", "Charlotte", "Hornets"],
    "CHI": ["Chicago Bulls", "Chicago", "Bulls"], "CLE": ["Cleveland Cavaliers", "Cleveland", "Cavaliers", "Cavs"],
    "DAL": ["Dallas Mavericks", "Dallas", "Mavericks", "Mavs"], "DEN": ["Denver Nuggets", "Denver", "Nuggets"],
    "DET": ["Detroit Pistons", "Detroit", "Pistons"], "GSW": ["Golden State Warriors", "Golden State", "Golden St", "Warriors"],
    "HOU": ["Houston Rockets", "Houston", "Rockets"], "IND": ["Indiana Pacers", "Indiana", "Pacers"],
    "LAC": ["LA Clippers", "Los Angeles Clippers", "LA Clippers", "Clippers"], "LAL": ["Los Angeles Lakers", "LA Lakers", "Lakers"],
    "MEM": ["Memphis Grizzlies", "Memphis", "Grizzlies"], "MIA": ["Miami Heat", "Miami", "Heat"],
    "MIL": ["Milwaukee Bucks", "Milwaukee", "Bucks"], "MIN": ["Minnesota Timberwolves", "Minnesota", "Timberwolves", "Wolves"],
    "NOP": ["New Orleans Pelicans", "New Orleans", "Pelicans"], "NYK": ["New York Knicks", "New York", "Knicks"],
    "OKC": ["Oklahoma City Thunder", "Oklahoma City", "Thunder"], "ORL": ["Orlando Magic", "Orlando", "Magic"],
    "PHI": ["Philadelphia 76ers", "Philadelphia Sixers", "Philadelphia", "76ers", "Sixers"], "PHX": ["Phoenix Suns", "Phoenix", "Suns"],
    "POR": ["Portland Trail Blazers", "Portland", "Trail Blazers", "Blazers"], "SAC": ["Sacramento Kings", "Sacramento", "Kings"],
    "SAS": ["San Antonio Spurs", "San Antonio", "Spurs"], "TOR": ["Toronto Raptors", "Toronto", "Raptors"],
    "UTA": ["Utah Jazz", "Utah", "Jazz"], "WAS": ["Washington Wizards", "Washington", "Wizards"],
}
ALIAS = {}
for code, names in TEAMS.items():
    ALIAS[code.lower()] = code
    for n in names:
        ALIAS[re.sub(r"[.']", "", n.lower())] = code
ALIAS.update({"la lakers": "LAL", "la clippers": "LAC", "los angeles lakers": "LAL", "los angeles clippers": "LAC",
              "gs": "GSW", "ny": "NYK", "sa": "SAS", "no": "NOP", "pho": "PHX", "utah": "UTA", "wsh": "WAS"})


def team_code(s):
    return ALIAS.get(re.sub(r"[.']", "", (s or "").strip().lower()))


def norm_name(s):
    s = re.sub(r"[.'’]", "", (s or "").lower())
    toks = [t for t in re.sub(r"[^a-z0-9]+", " ", s).split() if t not in ("jr", "sr", "ii", "iii", "iv")]
    return " ".join(toks)


def get(url, **kw):
    r = requests.get(url, headers=UA, timeout=45, **kw)
    r.raise_for_status()
    return r


def today_et():
    return dt.datetime.now(ET).date()


MONTHS = {m: i for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}


def _nearest(mon, day, future):
    """Resolve a month/day with no year. Past dates (updated stamps) resolve to the latest date on or before
    tomorrow; future dates (return dates) resolve to the earliest date after one month ago."""
    m, d, t = MONTHS[mon[:3].lower()], int(day), today_et()
    cands = []
    for y in (t.year - 1, t.year, t.year + 1):
        try:
            cands.append(dt.date(y, m, d))
        except ValueError:
            pass
    if future:
        return min(c for c in cands if c >= t - dt.timedelta(days=30)).isoformat()
    return max(c for c in cands if c <= t + dt.timedelta(days=1)).isoformat()


def past_date(mon, day):
    return _nearest(mon, day, future=False)


def future_date(mon, day):
    return _nearest(mon, day, future=True)


def parse_until(text):
    """'Expected to be out until at least Jan 2' -> '2027-01-02'."""
    m = re.search(r"until at least ([A-Za-z]{3})[a-z]*\.? (\d{1,2})", text or "")
    return future_date(m.group(1), m.group(2)) if m else ""


WORDNUM = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6}


def parse_duration_until(note, updated_iso):
    """'out at least 4 weeks', 're-evaluated in two weeks', 'about six months' -> an ISO date, else ''."""
    if not updated_iso or re.search(r"season", note or "", re.I):
        return ""
    m = re.search(r"(\d+|one|two|three|four|five|six)(?:\s*-\s*\d+)?\s+(week|month)s?", note or "", re.I)
    if not m:
        return ""
    n = int(m.group(1)) if m.group(1).isdigit() else WORDNUM[m.group(1).lower()]
    days = n * (7 if m.group(2).lower() == "week" else 30)
    return (dt.date.fromisoformat(updated_iso) + dt.timedelta(days=days)).isoformat()


def rec(team, player, src, kind, injury="", upd="", until="", note="", through="", st=None, url=""):
    r = {"team": team, "player": player, "src": src, "kind": kind, "injury": injury, "upd": upd,
         "until": until, "note": note, "through": through}
    if st:
        r["st"] = st
    if url:
        r["url"] = url
    return r


CBS_URL = "https://www.cbssports.com/nba/injuries/"
COVERS_URL = "https://www.covers.com/sport/basketball/nba/injuries"
ESPN_URL = "https://www.espn.com/nba/injuries"


def find_link(page, text):
    """Link to the source page that jumps to (and highlights) the player's name, in browsers that support it."""
    return page + "#:~:text=" + requests.utils.quote(text, safe="")


def snapshot_through(days=2):
    """Game-time decisions are only trusted for a short window; the job refreshes them daily."""
    return (today_et() + dt.timedelta(days=days)).isoformat()


# ---------------------------------------------------------------- schedule
def parse_schedule(rows):
    out, skipped = [], 0
    for r in rows:
        h, a = team_code(r.get("HomeTeam")), team_code(r.get("AwayTeam"))
        try:
            when = dt.datetime.fromisoformat(r["DateUtc"].replace(" ", "T").replace("Z", "+00:00")).astimezone(ET)
        except Exception:
            skipped += 1
            continue
        if not h or not a:
            skipped += 1
            continue
        out.append({"date": when.date().isoformat(), "time": when.strftime("%H:%M"), "away": a, "home": h,
                    "venue": r.get("Location", "")})
    return sorted(out, key=lambda g: (g["date"], g["time"])), skipped


def fetch_schedule():
    rows = get("https://fixturedownload.com/feed/json/nba-2026").json()
    games, skipped = parse_schedule(rows)
    if len(games) < 1000:
        raise RuntimeError(f"schedule looks incomplete: {len(games)} games")
    return games, {"count": len(games), "skipped_placeholders": skipped}


# ---------------------------------------------------------------- injuries
def classify_status(text):
    t = (text or "").lower()
    if re.search(r"\bout\b|\bofs\b|suspend", t):
        return "O"
    return "G"


def status_code(text):
    """Explicit Doubtful / Questionable / Probable -> the page's status key. Game-time decision and
    day-to-day return None, so the page shows them as 'Game-time decision'."""
    t = (text or "").lower()
    for word, st in (("doubtful", "doubt"), ("questionable", "q"), ("probable", "prob")):
        if word in t:
            return st
    return None


def clean(s):
    return re.sub(r"\s+", " ", s or "").strip()


def parse_cbs(html):
    soup = BeautifulSoup(html, "html.parser")
    out = []
    for wrap in soup.select("div.TableBaseWrapper"):
        name = wrap.select_one(".TeamName")
        team = team_code(name.get_text(" ", strip=True)) if name else None
        if not team:
            continue
        for tr in wrap.select("tbody tr"):
            tds = tr.find_all("td")
            if len(tds) < 5:
                continue
            a = tds[0].select_one(".CellPlayerName--long a") or (tds[0].find_all("a") or [None])[-1]
            player = a.get_text(" ", strip=True) if a else tds[0].get_text(" ", strip=True)
            upd_txt = tds[2].get_text(" ", strip=True)           # 'Mon, Oct 5'
            mu = re.search(r"([A-Za-z]{3}) (\d{1,2})", upd_txt)
            upd = past_date(mu.group(1), mu.group(2)) if mu else ""
            injury = tds[3].get_text(" ", strip=True)
            status = tds[4].get_text(" ", strip=True)
            kind = classify_status(status)
            until = parse_until(status)
            note = status if kind == "O" else ""
            out.append(rec(team, player, "CBS", kind, injury, upd, until, note,
                           through=snapshot_through() if kind == "G" else "", st=status_code(status),
                           url=find_link(CBS_URL, player)))
    return out


def covers_player(a):
    """Covers shows 'H. Veesaar'; the link ends in '/henri-veesaar', which gives the full name."""
    text = clean(a.get_text(" ", strip=True))
    m = re.search(r"/players/\d+/([a-z0-9-]+)", a.get("href", ""))
    if re.match(r"^[A-Z]\.\s", text) and m:
        return " ".join(w.capitalize() for w in m.group(1).split("-"))
    return text


def parse_covers(html):
    soup = BeautifulSoup(html, "html.parser")
    out = []
    for table in soup.find_all("table"):
        team_a = table.find_previous("a", href=re.compile(r"/teams/main/"))
        team = team_code(team_a.get_text(" ", strip=True)) if team_a else None
        if not team:
            continue
        for tr in table.find_all("tr"):
            pa = tr.find("a", href=re.compile(r"/nba/players/"))
            if not pa:
                continue
            player = covers_player(pa)
            strong = tr.find(["b", "strong"])
            status = clean(strong.get_text(" ", strip=True)) if strong else ""
            injury = status.split("-", 1)[1].strip() if "-" in status else ""
            md = re.search(r"\(\s*([A-Za-z]{3}),?\s+([A-Za-z]{3}) (\d{1,2})\s*\)", tr.get_text(" ", strip=True))
            upd = past_date(md.group(2), md.group(3)) if md else ""
            nxt = tr.find_next_sibling("tr")
            note = clean(nxt.get_text(" ", strip=True)) if nxt and not nxt.find("a", href=re.compile(r"/nba/players/")) else ""
            kind = classify_status(status)
            until = parse_duration_until(note, upd) if kind == "O" else ""
            out.append(rec(team, player, "Covers", kind, injury, upd, until, note,
                           through=snapshot_through() if kind == "G" else "", st=status_code(status),
                           url=find_link(COVERS_URL, clean(pa.get_text(" ", strip=True)))))
    return out


def parse_espn(j):
    out = []
    for t in j.get("injuries", []):
        team = team_code(t.get("displayName", ""))
        if not team:
            continue
        for i in t.get("injuries", []):
            ath = i.get("athlete") or {}
            player = ath.get("displayName")
            if not player:
                continue
            d = i.get("details") or {}
            injury = " ".join(x for x in [d.get("side"), d.get("type") or (i.get("type") or {}).get("description"), d.get("detail")]
                              if x and x.lower() != "not specified")
            fantasy = (d.get("fantasyStatus") or {}).get("abbreviation", "")
            kind = classify_status(i.get("status", "") + " " + fantasy)
            ret = (d.get("returnDate") or "")[:10]
            out.append(rec(team, player, "ESPN", kind, injury, (i.get("date") or "")[:10], ret if kind == "O" else "",
                           i.get("shortComment", ""), through=snapshot_through() if kind == "G" else "",
                           st=status_code(i.get("status", "")), url=find_link(ESPN_URL, player)))
    return out


def fetch_cbs():
    return parse_cbs(get("https://www.cbssports.com/nba/injuries/").text)


def fetch_covers():
    return parse_covers(get("https://www.covers.com/sport/basketball/nba/injuries").text)


def fetch_espn():
    return parse_espn(get("https://site.api.espn.com/apis/site/v2/sports/basketball/nba/injuries").json())


# ---------------------------------------------------------------- depth charts (ESPN)
ESPN_POS = ["pg", "sg", "sf", "pf", "c"]
ROTATION_SIZE = 5          # bench players marked "rotation"; the rest are "limited minutes"


def parse_espn_depth(j):
    """One ESPN team depth chart -> (team, {"PG": "starter/rotation,rotation/limited,limited", ...}).
    ESPN lists the same player under several positions. Each bench player is kept at the position where he
    ranks highest; the 5 highest-ranked bench players overall count as the rotation."""
    team = team_code((j.get("team") or {}).get("displayName"))
    charts = j.get("depthchart") or []
    if not team or not charts:
        return None, None
    pos = charts[0].get("positions") or {}
    cols = {p.upper(): [clean(a.get("displayName")) for a in (pos.get(p) or {}).get("athletes", []) if a.get("displayName")]
            for p in ESPN_POS}
    starters, used = {}, set()
    for p, names in cols.items():
        st = next((n for n in names if norm_name(n) not in used), "")
        starters[p] = st
        used.add(norm_name(st))
    best = {}
    for pi, (p, names) in enumerate(cols.items()):
        for i, n in enumerate(names):
            k = norm_name(n)
            if k not in used and (k not in best or (i, pi) < best[k][:2]):
                best[k] = (i, pi, p, n)
    bench = sorted(best.values())
    rotation = {x[3] for x in bench[:ROTATION_SIZE]}
    out = {}
    for p in cols:
        mine = [x[3] for x in bench if x[2] == p]
        out[p] = "{}/{}/{}".format(starters[p], ",".join(n for n in mine if n in rotation),
                                   ",".join(n for n in mine if n not in rotation))
    return team, out


def fetch_espn_depth():
    out = {}
    for tid in range(1, 31):
        try:
            team, chart = parse_espn_depth(get(f"https://site.api.espn.com/apis/site/v2/sports/basketball/nba/teams/{tid}/depthcharts").json())
        except Exception as e:
            print(f"[espn_depth] team {tid}: {e}", file=sys.stderr)
            continue
        if team:
            out[team] = chart
        time.sleep(0.3)
    if len(out) < 25:
        raise RuntimeError(f"only {len(out)} depth charts parsed")
    return out


# ---------------------------------------------------------------- lineups (RotoWire)
ROTO_URL = "https://www.rotowire.com/basketball/nba-lineups.php"


def parse_rotowire(html):
    """-> (lineups {team: {date, vs, confirmed, starters: [{pos, name}]}}, injury records)."""
    soup = BeautifulSoup(html, "html.parser")
    m = re.search(r"lineups for ([A-Za-z]+) (\d{1,2}), (\d{4})", soup.get_text(" ", strip=True))
    date = dt.date(int(m.group(3)), MONTHS[m.group(1)[:3].lower()], int(m.group(2))).isoformat() if m else today_et().isoformat()
    lineups, injuries = {}, []
    for g in soup.select(".lineup.is-nba"):
        teams = [team_code(x.get_text(strip=True)) for x in g.select(".lineup__abbr")]
        if len(teams) != 2 or not all(teams):
            continue
        tm = g.select_one(".lineup__time")
        mt = re.match(r"(\d{1,2}):(\d{2})\s*([AP]M)", clean(tm.get_text()) if tm else "")
        tip = f"{int(mt.group(1)) % 12 + (12 if mt.group(3) == 'PM' else 0):02d}:{mt.group(2)}" if mt else ""
        for side, team, opp in (("is-visit", teams[0], teams[1]), ("is-home", teams[1], teams[0])):
            home = side == "is-home"
            ul = g.select_one(f"ul.lineup__list.{side}")
            if not ul:
                continue
            head = ul.select_one(".lineup__status")
            confirmed = bool(head and "is-confirmed" in head.get("class", []))
            starters, bench = [], False
            for li in ul.find_all("li", recursive=False):
                cls = li.get("class", [])
                if "lineup__title" in cls:
                    bench = True
                    continue
                a = li.find("a")
                if "lineup__player" not in cls or not a:
                    continue
                name = clean(a.get("title") or a.get_text())
                p = li.select_one(".lineup__pos")
                if not bench:
                    starters.append({"pos": clean(p.get_text()) if p else "", "name": name})
                tag = li.select_one(".lineup__inj")
                tag = clean(tag.get_text()) if tag else ""
                if bench or tag:
                    # RotoWire tag "Out" (or OFS / suspended) = out. Anything else on its "may not play" list = questionable.
                    st = "out" if tag.lower() in ("out", "ofs", "susp") else "q"
                    injuries.append(rec(team, name, "RotoWire", "O" if st == "out" else "G", upd=date, through=date, st=st,
                                        note=f"RotoWire tag: {tag}" if tag else "RotoWire: may not play",
                                        url=find_link(ROTO_URL, clean(a.get_text()))))
            if starters:
                lineups[team] = {"date": date, "time": tip, "vs": opp, "home": home, "confirmed": confirmed,
                                 "starters": starters}
    return lineups, injuries


def fetch_rotowire():
    return parse_rotowire(get(ROTO_URL).text)


# ---------------------------------------------------------------- minutes sheet
def parse_minutes_csv(text):
    rows = list(csv.reader(io.StringIO(text)))
    rows = [r for r in rows if any(c.strip() for c in r)]
    if not rows:
        return {}
    hdr = [c.strip().lower() for c in rows[0]]
    pi = next((i for i, c in enumerate(hdr) if re.search(r"player|name", c)), 0)
    mi = next((i for i, c in enumerate(hdr) if re.search(r"^(mpg|min|mins|mp|minutes)\b|min.*game|avg.*min", c)), None)
    if mi is None:
        mi = next((i for i, c in enumerate(hdr) if "min" in c), 2)
    out = {}
    for r in rows[1:]:
        try:
            out[r[pi].strip()] = round(float(r[mi]), 1)
        except (ValueError, IndexError):
            pass
    return out


def fetch_minutes():
    url = os.environ.get("MINUTES_CSV_URL")
    if not url:
        raise SkipSource("MINUTES_CSV_URL not set")
    return parse_minutes_csv(get(url).text)


# ---------------------------------------------------------------- beat writers on X
INJURY_WORDS = re.compile(r"\b(out|questionable|doubtful|probable|available|miss|sidelined|return|rest|injur|status|ruled|won't play|will not play|expected to play|gtd|minutes restriction|load management|upgraded|downgraded)\b", re.I)
STATUS_MAP = {"out": "out", "doubtful": "doubt", "questionable": "q", "probable": "prob", "available": "prob"}

CLASSIFY_PROMPT = """You read tweets from an NBA team beat writer. Extract only explicit player availability facts
(injury, rest, return, minutes restriction, upgrade or downgrade). Ignore opinions, trade talk, quotes about performance.
Return ONLY a JSON array. Each item: {"player": "Full Name", "status": "out|doubtful|questionable|probable|available",
"injury": "short body part or reason or empty", "note": "one short sentence", "tweet_index": 0}.
If nothing qualifies return []. Team: %s
Tweets:
%s"""


def classify_tweets(team, tweets, client_call):
    cand = [t for t in tweets if INJURY_WORDS.search(t["text"])]
    if not cand:
        return []
    listing = "\n".join(f"[{i}] {t['text']}" for i, t in enumerate(cand))
    raw = client_call(CLASSIFY_PROMPT % (team, listing))
    raw = re.sub(r"^```(?:json)?|```$", "", raw.strip(), flags=re.M).strip()
    try:
        items = json.loads(raw)
    except json.JSONDecodeError:
        return []
    out = []
    for it in items if isinstance(items, list) else []:
        st = STATUS_MAP.get(str(it.get("status", "")).lower())
        idx = it.get("tweet_index")
        if not st or not it.get("player") or not isinstance(idx, int) or idx >= len(cand):
            continue
        t = cand[idx]
        posted = t["created_at"][:10]
        through = (dt.date.fromisoformat(posted) + dt.timedelta(days=2)).isoformat()
        out.append(rec(team, it["player"], "@" + t["handle"], "O" if st == "out" else "G", it.get("injury", ""),
                       posted, "", it.get("note", ""), through=through, st=st, url=t["url"]))
    return out


def claude_call_factory():
    import anthropic
    client = anthropic.Anthropic()

    def call(prompt):
        msg = client.messages.create(model="claude-haiku-4-5-20251001", max_tokens=1200,
                                     messages=[{"role": "user", "content": prompt}])
        return "".join(b.text for b in msg.content if b.type == "text")
    return call


def fetch_x(cfg_path):
    token = os.environ.get("X_BEARER_TOKEN")
    if not token or not os.environ.get("ANTHROPIC_API_KEY"):
        raise SkipSource("X_BEARER_TOKEN / ANTHROPIC_API_KEY not set")
    cfg = json.load(open(cfg_path))
    handles = {t: [h.lstrip("@") for h in hs] for t, hs in cfg.items() if not t.startswith("_") and hs}
    if not handles:
        raise SkipSource("beat_writers.json has no handles yet")
    call = claude_call_factory()
    hdr = {"Authorization": f"Bearer {token}"}
    since = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=36)).strftime("%Y-%m-%dT%H:%M:%SZ")
    out = []
    for team, hs in handles.items():
        tweets = []
        for h in hs:
            u = requests.get(f"https://api.x.com/2/users/by/username/{h}", headers=hdr, timeout=30)
            u.raise_for_status()
            uid = u.json()["data"]["id"]
            r = requests.get(f"https://api.x.com/2/users/{uid}/tweets", headers=hdr, timeout=30,
                             params={"max_results": 20, "start_time": since, "exclude": "retweets,replies",
                                     "tweet.fields": "created_at"})
            r.raise_for_status()
            for t in r.json().get("data", []):
                tweets.append({"text": t["text"], "created_at": t["created_at"], "handle": h,
                               "url": f"https://x.com/{h}/status/{t['id']}"})
            time.sleep(0.5)
        out += classify_tweets(team, tweets, call)
    return out


# ---------------------------------------------------------------- orchestration
class SkipSource(Exception):
    pass


def all_games(data):
    """Schedule games plus any RotoWire game not in it (preseason games are only on RotoWire)."""
    games = list(data.get("schedule", []))
    have = {(g["date"], g["home"]) for g in games}
    for team, l in (data.get("lineups") or {}).items():
        if l.get("home") and l.get("time") and (l["date"], team) not in have:
            games.append({"date": l["date"], "time": l["time"], "away": l["vs"], "home": team, "venue": ""})
    return sorted(games, key=lambda g: (g["date"], g["time"]))


def game_starting_soon(schedule, now, minutes):
    """True if any game tips off between now and `minutes` from now (times are ET)."""
    for g in schedule:
        try:
            tip = dt.datetime.fromisoformat(f"{g['date']}T{g['time']}").replace(tzinfo=ET)
        except (KeyError, ValueError):
            continue
        if now <= tip <= now + dt.timedelta(minutes=minutes):
            return True
    return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="data.json")
    ap.add_argument("--pregame", type=int, metavar="MINUTES",
                    help="only refresh if a game tips off within this many minutes; otherwise exit without changes")
    ap.add_argument("--beat-config", default=os.path.join(os.path.dirname(__file__), "beat_writers.json"))
    args = ap.parse_args()

    prev = {}
    if os.path.exists(args.out):
        try:
            prev = json.load(open(args.out))
        except Exception:
            pass
    if args.pregame and not game_starting_soon(all_games(prev), dt.datetime.now(ET), args.pregame):
        print(f"No game starts in the next {args.pregame} minutes; nothing to do.")
        return
    status, injuries = {}, []
    data = {"schedule": prev.get("schedule", []), "depth": prev.get("depth", {}), "minutes": prev.get("minutes", {}),
            "lineups": prev.get("lineups", {})}

    def run(name, fn):
        try:
            res = fn()
            status[name] = {"ok": True, "at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")}
            return res
        except SkipSource as e:
            status[name] = {"ok": None, "note": str(e)}
        except Exception as e:  # keep last good data for this source
            status[name] = {"ok": False, "error": f"{type(e).__name__}: {e}"[:300]}
            print(f"[{name}] FAILED: {e}", file=sys.stderr)
        return None

    sch = run("schedule", fetch_schedule)
    if sch:
        data["schedule"] = sch[0]
        status["schedule"]["count"] = sch[1]["count"]
    dep = run("espn_depth", fetch_espn_depth)
    if dep:
        data["depth"].update(dep)
        status["espn_depth"]["teams"] = len(dep)
    roto = run("rotowire", fetch_rotowire)
    roto_inj = None
    if roto:
        data["lineups"], roto_inj = roto
        status["rotowire"]["teams"] = len(roto[0])
    mins = run("minutes", fetch_minutes)
    if mins:
        data["minutes"] = mins
        status["minutes"]["players"] = len(mins)

    for name, label, fn in [("cbs", "CBS", fetch_cbs), ("covers", "Covers", fetch_covers), ("espn", "ESPN", fetch_espn),
                            ("x", None, lambda: fetch_x(args.beat_config))]:
        res = run(name, fn)
        if res is not None:
            injuries += res
            status[name]["count"] = len(res)
        elif status[name].get("ok") is False:
            old = [r for r in prev.get("injuries", []) if (r["src"].startswith("@") if name == "x" else r["src"] == label)]
            for r in old:
                r["stale"] = True
            injuries += old
            status[name]["kept_stale"] = len(old)

    if roto:                      # RotoWire's "may not play" list only covers today, so it is never kept stale
        injuries += roto_inj
        status["rotowire"]["injuries"] = len(roto_inj)

    canon = {}
    for r in injuries:
        if r["src"] in ("CBS", "ESPN"):
            canon.setdefault((r["team"], norm_name(r["player"])), r["player"])
    for r in injuries:
        r["player"] = canon.get((r["team"], norm_name(r["player"])), r["player"])

    data.update({"generated_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
                 "sources": status, "injuries": injuries})
    with open(args.out, "w") as f:
        json.dump(data, f, indent=1)
    print(json.dumps(status, indent=1))
    hard_fail = [k for k, v in status.items() if v.get("ok") is False and k in ("schedule", "cbs", "covers", "espn")]
    sys.exit(1 if len(hard_fail) == 4 else 0)   # only fail the run if every core source broke


if __name__ == "__main__":
    main()
