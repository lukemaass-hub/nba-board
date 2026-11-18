"""Points scored per player per game this season, from the same ESPN game summaries as fetch_espn.py (user, Nov 18 2026:
show the actual points next to our points line on the minutes page). Only games not saved yet are fetched.

    python backtest/fetch_points.py        -> backtest/data/points_2026-27.csv (season, game_id, date, player_id, player, points)
"""
import csv, os, time
from concurrent.futures import ThreadPoolExecutor

import fetch_espn as f

HERE = os.path.dirname(os.path.abspath(__file__))
SEASON = "2026-27"
GAMES = os.path.join(HERE, "data", f"games_{SEASON}.csv")
OUT = os.path.join(HERE, "data", f"points_{SEASON}.csv")
COLS = ["season", "game_id", "date", "player_id", "player", "points"]


def points(gid, date):
    sm = f.get(f"https://site.api.espn.com/apis/site/v2/sports/basketball/nba/summary?event={gid}") or {}
    rows = []
    for t in (sm.get("boxscore") or {}).get("players", []):
        for st in t.get("statistics", [])[:1]:
            keys = st.get("keys", [])
            if "points" not in keys:
                continue
            pi = keys.index("points")
            for a in st.get("athletes", []):
                s = a.get("stats") or []
                if len(s) > pi and str(s[pi]).isdigit():
                    ath = a["athlete"]
                    rows.append({"season": SEASON, "game_id": gid, "date": date, "player_id": ath.get("id", ""),
                                 "player": ath.get("displayName", ""), "points": int(s[pi])})
    time.sleep(0.1)
    return rows


def main():
    done = {r["game_id"] for r in csv.DictReader(open(OUT))} if os.path.exists(OUT) else set()
    todo = [(r["game_id"], r["date"]) for r in csv.DictReader(open(GAMES)) if r["game_id"] not in done]
    new = not os.path.exists(OUT)
    with open(OUT, "a", newline="") as fh, ThreadPoolExecutor(6) as ex:
        w = csv.DictWriter(fh, COLS)
        if new:
            w.writeheader()
        n = 0
        for rows in ex.map(lambda x: points(*x), todo):
            w.writerows(rows); n += len(rows)
    print(f"{len(todo)} games fetched, {n} player rows -> {OUT}")


if __name__ == "__main__":
    main()
