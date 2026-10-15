#!/usr/bin/env python3
"""Download every regular-season box score for 2024-25 and 2025-26 from ESPN's public JSON.

For each date: scoreboard?dates=YYYYMMDD -> game ids; for each game: summary?event=ID -> box score.
Writes backtest/data/box_<season>.csv (one row per player listed in a box score) and
backtest/data/games_<season>.csv. Re-running skips games already saved (resume after a cut-off).

ESPN lists players who dressed (played or DNP). Injured players who did not dress are usually missing; the
backtest treats "missing but on the team" as inactive (see build_dataset.py).
"""
import csv, datetime as dt, json, os, sys, time, urllib.request
from concurrent.futures import ThreadPoolExecutor

UA = {"User-Agent": "Mozilla/5.0 (compatible; availability-board/1.0)"}
HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "data")
SEASONS = {"2024-25": ("2024-10-22", "2025-04-13", 2025), "2025-26": ("2025-10-21", "2026-04-12", 2026)}
BOX_COLS = ["season", "game_id", "date", "team", "opponent", "home", "player_id", "player", "position", "starter",
            "minutes", "played", "dnp", "dnp_reason", "ejected"]


def get(url, tries=4):
    for i in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=45) as r:
                return json.load(r)
        except Exception as e:
            if i == tries - 1:
                raise
            time.sleep(2 * (i + 1))


def game_ids(start, end, year):
    out, d = [], dt.date.fromisoformat(start)
    while d <= dt.date.fromisoformat(end):
        sb = get(f"https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard?dates={d:%Y%m%d}")
        for e in sb.get("events", []):
            s = e.get("season") or {}
            if s.get("year") == year and s.get("type") == 2:
                out.append((e["id"], d.isoformat()))
        d += dt.timedelta(days=1)
        time.sleep(0.15)
    return out


def box_rows(season, gid, date, summary):
    rows = []
    teams = summary["boxscore"]["players"]
    if len(teams) != 2:
        return rows, None
    comp = summary["header"]["competitions"][0]
    home_id = next(c["team"]["id"] for c in comp["competitors"] if c["homeAway"] == "home")
    abbr = [t["team"]["abbreviation"] for t in teams]
    for i, t in enumerate(teams):
        st = t["statistics"][0] if t.get("statistics") else {"athletes": [], "keys": []}
        mi = st["keys"].index("minutes") if "minutes" in st.get("keys", []) else 0
        for a in st["athletes"]:
            ath, stats = a["athlete"], a.get("stats") or []
            mins = stats[mi] if len(stats) > mi else ""
            try:
                mins = float(mins)
            except (TypeError, ValueError):
                mins = 0.0
            dnp = bool(a.get("didNotPlay"))
            rows.append({"season": season, "game_id": gid, "date": date, "team": abbr[i], "opponent": abbr[1 - i],
                         "home": int(t["team"]["id"] == home_id),
                         # a few ESPN entries have no id or full name; key them by short name and team
                         "player_id": ath.get("id") or f"x-{abbr[i]}-{ath.get('shortName', '?')}",
                         "player": ath.get("displayName") or ath.get("shortName", "?"),
                         "position": (ath.get("position") or {}).get("abbreviation", ""), "starter": int(bool(a.get("starter"))),
                         "minutes": mins, "played": int(not dnp and mins > 0), "dnp": int(dnp),
                         "dnp_reason": (a.get("reason") or "") if dnp else "", "ejected": int(bool(a.get("ejected")))})
    game = {"season": season, "game_id": gid, "date": date, "home": next(a for a, t in zip(abbr, teams) if t["team"]["id"] == home_id),
            "away": next(a for a, t in zip(abbr, teams) if t["team"]["id"] != home_id)}
    return rows, game


def main():
    os.makedirs(OUT, exist_ok=True)
    for season, (start, end, year) in SEASONS.items():
        box_path, games_path = os.path.join(OUT, f"box_{season}.csv"), os.path.join(OUT, f"games_{season}.csv")
        done = set()
        if os.path.exists(games_path):
            done = {r["game_id"] for r in csv.DictReader(open(games_path))}
        ids_path = os.path.join(OUT, f"ids_{season}.json")
        if os.path.exists(ids_path):
            ids = json.load(open(ids_path))
        else:
            ids = game_ids(start, end, year)
            json.dump(ids, open(ids_path, "w"))
        print(f"{season}: {len(ids)} games listed, {len(done)} already saved", flush=True)
        new_box = not os.path.exists(box_path)
        with open(box_path, "a", newline="") as fb, open(games_path, "a", newline="") as fg:
            wb, wg = csv.DictWriter(fb, BOX_COLS), csv.DictWriter(fg, ["season", "game_id", "date", "home", "away"])
            if new_box:
                wb.writeheader(); wg.writeheader()
            todo = [(gid, date) for gid, date in ids if gid not in done]

            def one(item):
                gid, date = item
                try:
                    return box_rows(season, gid, date, get(f"https://site.api.espn.com/apis/site/v2/sports/basketball/nba/summary?event={gid}"))
                except Exception as e:
                    print(f"  {gid} failed: {e}", file=sys.stderr, flush=True)
                    return [], None
            with ThreadPoolExecutor(max_workers=4) as pool:          # 4 at a time: gentle on ESPN
                for n, (rows, game) in enumerate(pool.map(one, todo), 1):
                    if game:
                        wb.writerows(rows); wg.writerow(game); fb.flush(); fg.flush()
                    if n % 200 == 0:
                        print(f"  {season}: {n}/{len(todo)}", flush=True)


if __name__ == "__main__":
    main()
