"""Blowout chance by pre-game spread (user, Nov 4 2026).

For every regular-season game of the last 5 seasons (2021-22 to 2025-26): ESPN's last pre-game spread (the
"consensus" line in the game summary's pickcenter, i.e. the closing line, which is the closest thing to "30 minutes
before tip" that is kept for past games; for 2023-24 and 2024-25, which have none, the middle of the pre-game lines in
ESPN's odds list) and the final score. A blowout = the FAVORITE wins by 15 or more.

    python backtest/blowout.py fetch     -> backtest/data/spreads.csv (cached; re-running only fetches what's missing)
    python backtest/blowout.py table     -> pipeline/blowout_table.json + printout by spread
"""
import csv, datetime as dt, json, math, os, sys, time
from concurrent.futures import ThreadPoolExecutor

import requests

HERE = os.path.dirname(os.path.abspath(__file__))
CSV = os.path.join(HERE, "data", "spreads.csv")
OUT = os.path.join(HERE, "..", "pipeline", "blowout_table.json")
SB = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard?dates={d:%Y%m%d}&seasontype=2"
SUM = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/summary?event={gid}"
CORE = "https://sports.core.api.espn.com/v2/sports/basketball/leagues/nba/events/{gid}/competitions/{gid}/odds?limit=50"
# regular seasons (ESPN season year = the year it ends)
SEASONS = {2022: ("2021-10-19", "2022-04-10"), 2023: ("2022-10-18", "2023-04-09"), 2024: ("2023-10-24", "2024-04-14"),
           2025: ("2024-10-22", "2025-04-13"), 2026: ("2025-10-21", "2026-04-12")}
MARGIN = 15
FIELDS = ["season", "date", "gid", "away", "home", "away_score", "home_score", "fav", "spread", "provider"]
S = requests.Session()
S.headers["User-Agent"] = "nba-board blowout study"


def get(url, tries=4):
    for i in range(tries):
        try:
            r = S.get(url, timeout=30)
            if r.status_code == 200:
                return r.json()
        except (requests.RequestException, ValueError):
            pass
        time.sleep(2 * (i + 1))
    return None


def finals(season, start, end):
    d, e = dt.date.fromisoformat(start), dt.date.fromisoformat(end)
    out = []
    while d <= e:
        sb = get(SB.format(d=d)) or {}
        for ev in sb.get("events", []):
            c = ev["competitions"][0]
            if not c["status"]["type"].get("completed"):
                continue
            t = {x["homeAway"]: x for x in c["competitors"]}
            out.append({"season": season, "date": d.isoformat(), "gid": ev["id"],
                        "away": t["away"]["team"]["abbreviation"], "home": t["home"]["team"]["abbreviation"],
                        "away_score": int(t["away"]["score"]), "home_score": int(t["home"]["score"])})
        d += dt.timedelta(days=1)
    return out


def line(g):
    """(favorite abbreviation, spread as a positive number, provider) from the game summary, or None."""
    sm = get(SUM.format(gid=g["gid"])) or {}
    pcs = sm.get("pickcenter") or []
    pcs = sorted(pcs, key=lambda p: (p.get("provider", {}).get("name") != "consensus", p.get("provider", {}).get("priority", 9)))
    for p in pcs:
        sp = p.get("spread")
        if sp is None:
            continue
        sp = float(sp)               # home team's spread: negative = home favored
        if sp == 0:
            return ("PK", 0.0, p["provider"].get("name"))
        return (g["home"] if sp < 0 else g["away"], abs(sp), p["provider"].get("name"))
    # 2023-24 and 2024-25 games have no pickcenter: use ESPN's odds list, the middle of the pre-game (not "Live") lines
    co = get(CORE.format(gid=g["gid"])) or {}
    sps = sorted(float(it["spread"]) for it in co.get("items", [])
                 if it.get("spread") is not None and "live" not in (it.get("provider") or {}).get("name", "").lower())
    if sps:
        sp = sps[len(sps) // 2]
        return ("PK", 0.0, "median") if sp == 0 else (g["home"] if sp < 0 else g["away"], abs(sp), f"median of {len(sps)}")
    return None


def fetch():
    have = {}
    if os.path.exists(CSV):
        have = {r["gid"]: r for r in csv.DictReader(open(CSV))}
    os.makedirs(os.path.dirname(CSV), exist_ok=True)
    for season, (a, b) in SEASONS.items():
        games = [g for g in finals(season, a, b) if g["gid"] not in have or have[g["gid"]]["spread"] == ""]
        print(f"{season}: {len(games)} games to look up", flush=True)

        def one(g):
            ln = line(g)
            return {**g, "fav": ln[0], "spread": ln[1], "provider": ln[2]} if ln else {**g, "fav": "", "spread": "", "provider": ""}
        with ThreadPoolExecutor(6) as ex:
            for r in ex.map(one, games):
                have[r["gid"]] = r
        with open(CSV, "w", newline="") as f:
            w = csv.DictWriter(f, FIELDS)
            w.writeheader()
            w.writerows(sorted(have.values(), key=lambda r: (r["date"], r["gid"])))
    print(f"saved {len(have)} games -> {CSV}")


def rows():
    for r in csv.DictReader(open(CSV)):
        if r["spread"] == "" or r["fav"] in ("", "PK"):
            continue
        fav_home = r["fav"] == r["home"]
        margin = (int(r["home_score"]) - int(r["away_score"])) * (1 if fav_home else -1)
        yield float(r["spread"]), margin


def logistic(xs, ys, iters=4000, lr=0.05):
    """P(blowout) = 1 / (1 + exp(-(a + b * spread))), fitted by plain gradient descent (no extra packages)."""
    a = b = 0.0
    n = len(xs)
    m = sum(xs) / n
    for _ in range(iters):
        ga = gb = 0.0
        for x, y in zip(xs, ys):
            p = 1 / (1 + math.exp(-(a + b * (x - m))))
            ga += p - y
            gb += (p - y) * (x - m)
        a -= lr * ga / n
        b -= lr * gb / n
    return a - b * m, b


def table():
    data = list(rows())
    xs = [s for s, _ in data]
    ys = [1 if mg >= MARGIN else 0 for _, mg in data]
    a, b = logistic(xs, ys)
    print(f"{len(data)} games with a spread; favorite won by {MARGIN}+ in {sum(ys)} ({sum(ys) / len(ys):.1%})")
    print(f"{'spread':>12} {'games':>6} {'blowouts':>9} {'actual':>7} {'model':>6}")
    buckets = [(0, 2.5), (3, 4.5), (5, 6.5), (7, 8.5), (9, 10.5), (11, 12.5), (13, 14.5), (15, 30)]
    by = []
    for lo, hi in buckets:
        g = [(s, y) for s, y in zip(xs, ys) if lo <= s <= hi]
        if not g:
            continue
        mid = sum(s for s, _ in g) / len(g)
        act = sum(y for _, y in g) / len(g)
        model = 1 / (1 + math.exp(-(a + b * mid)))
        by.append({"from": lo, "to": hi, "games": len(g), "blowouts": sum(y for _, y in g), "actual": round(act, 3)})
        print(f"{lo:>5}-{hi:<6} {len(g):>6} {sum(y for _, y in g):>9} {act:>7.1%} {model:>6.1%}")
    pct = {f"{s / 2:g}": round(1 / (1 + math.exp(-(a + b * s / 2))), 3) for s in range(0, 41)}   # 0 to 20 by 0.5
    json.dump({"made": dt.date.today().isoformat(), "seasons": "2021-22 to 2025-26 regular season",
               "line": "ESPN closing (consensus) spread", "blowout": f"favorite wins by {MARGIN}+",
               "games": len(data), "a": a, "b": b, "by_spread": pct, "buckets": by},
              open(OUT, "w"), indent=1)
    print(f"-> {OUT}")


if __name__ == "__main__":
    {"fetch": fetch, "table": table}[sys.argv[1] if len(sys.argv) > 1 else "table"]()
