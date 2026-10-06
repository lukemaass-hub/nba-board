#!/usr/bin/env python3
"""Refresh data.json for the NBA availability board.

Sources (each one is optional; a failure keeps that source's last good data, marked stale):
  schedule   fixturedownload.com JSON feed (all 1,230 games, converted to ET)
  cbs        cbssports.com/nba/injuries
  covers     covers.com NBA injuries
  espn       ESPN public JSON injuries endpoint
  realgm     RealGM depth charts (projected starters / rotation)
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
ALIAS.update({"la lakers": "LAL", "la clippers": "LAC", "los angeles lakers": "LAL", "los angeles clippers": "LAC"})


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
    m = re.search(r"(\d+|one|two|three|four|five|six)\s+(week|month)s?", note or "", re.I)
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
    if "out" in t:
        return "O"
    return "G"


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
                           through=snapshot_through() if kind == "G" else ""))
    return out


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
            player = pa.get_text(" ", strip=True)
            strong = tr.find("strong")
            status = strong.get_text(" ", strip=True) if strong else ""
            injury = status.split("-", 1)[1].strip() if "-" in status else ""
            md = re.search(r"\(\s*([A-Za-z]{3}),?\s+([A-Za-z]{3}) (\d{1,2})\s*\)", tr.get_text(" ", strip=True))
            upd = past_date(md.group(2), md.group(3)) if md else ""
            nxt = tr.find_next_sibling("tr")
            note = nxt.get_text(" ", strip=True) if nxt and not nxt.find("a", href=re.compile(r"/nba/players/")) else ""
            kind = classify_status(status)
            until = parse_duration_until(note, upd) if kind == "O" else ""
            out.append(rec(team, player, "Covers", kind, injury, upd, until, note,
                           through=snapshot_through() if kind == "G" else ""))
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
            injury = " ".join(x for x in [d.get("side"), d.get("type") or (i.get("type") or {}).get("description"), d.get("detail")] if x)
            kind = classify_status(i.get("status", ""))
            ret = (d.get("returnDate") or "")[:10]
            out.append(rec(team, player, "ESPN", kind, injury, (i.get("date") or "")[:10], ret if kind == "O" else "",
                           i.get("shortComment", ""), through=snapshot_through() if kind == "G" else ""))
    return out


def fetch_cbs():
    return parse_cbs(get("https://www.cbssports.com/nba/injuries/").text)


def fetch_covers():
    return parse_covers(get("https://www.covers.com/sport/basketball/nba/injuries").text)


def fetch_espn():
    return parse_espn(get("https://site.api.espn.com/apis/site/v2/sports/basketball/nba/injuries").json())


# ---------------------------------------------------------------- depth charts
TIER = {"starters": "S", "rotation": "R", "lim pt": "L"}


def player_display(a):
    text = a.get_text(" ", strip=True)
    if re.match(r"^[A-Z]\.(\s?[A-Z]\.)?\s", text):                      # 'N. Alexander-Walker'
        m = re.search(r"/player/([^/]+)/", a.get("href", ""))
        if m:
            return m.group(1).replace("-", " ")
    return text


def parse_realgm_depth(html):
    soup = BeautifulSoup(html, "html.parser")
    out = {}
    for h in soup.find_all(["h2", "h3"]):
        m = re.match(r"\d{4}-\d{4}\s+(.*?)\s+Depth Chart", h.get_text(" ", strip=True))
        if not m:
            continue
        team = team_code(m.group(1))
        table = h.find_next("table")
        if not team or not table:
            continue
        rows = table.find_all("tr")
        header = [c.get_text(strip=True).upper() for c in rows[0].find_all(["th", "td"])][1:]
        cols = {p: {"S": [], "R": [], "L": []} for p in header}
        for tr in rows[1:]:
            cells = tr.find_all(["th", "td"])
            tier = TIER.get(cells[0].get_text(" ", strip=True).lower())
            if not tier:
                continue
            for p, td in zip(header, cells[1:]):
                a = td.find("a")
                if a:
                    cols[p][tier].append(player_display(a))
        out[team] = {p: "{}/{}/{}".format(",".join(v["S"][:1]), ",".join(v["R"]), ",".join(v["L"])) for p, v in cols.items()}
    return out


def fetch_realgm():
    d = parse_realgm_depth(get("https://basketball.realgm.com/nba/depth-charts").text)
    if len(d) < 25:
        raise RuntimeError(f"only {len(d)} depth charts parsed")
    return d


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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="data.json")
    ap.add_argument("--beat-config", default=os.path.join(os.path.dirname(__file__), "beat_writers.json"))
    args = ap.parse_args()

    prev = {}
    if os.path.exists(args.out):
        try:
            prev = json.load(open(args.out))
        except Exception:
            pass
    status, injuries = {}, []
    data = {"schedule": prev.get("schedule", []), "depth": prev.get("depth", {}), "minutes": prev.get("minutes", {})}

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
    dep = run("realgm_depth", fetch_realgm)
    if dep:
        data["depth"] = dep
        status["realgm_depth"]["teams"] = len(dep)
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

    data.update({"generated_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
                 "sources": status, "injuries": injuries})
    with open(args.out, "w") as f:
        json.dump(data, f, indent=1)
    print(json.dumps(status, indent=1))
    hard_fail = [k for k, v in status.items() if v.get("ok") is False and k in ("schedule", "cbs", "covers", "espn")]
    sys.exit(1 if len(hard_fail) == 4 else 0)   # only fail the run if every core source broke


if __name__ == "__main__":
    main()
