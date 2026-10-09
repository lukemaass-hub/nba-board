#!/usr/bin/env python3
"""Turn the minutes-vs-opponent workbook into matchup alerts (pipeline/matchup_alerts.json).

Uses the same numbers as the workbook's Team_Chart sheet ("Select Team"): that sheet filters
Player_vs_Team_Grid by team and shows each player's average minutes against every opponent, plus
"Avg Mins" = the average of those 30 opponent averages. This script does that for all 100 players at once.

A matchup becomes an alert when the player's average against that opponent is at least MIN_DIFF minutes
above or below his Avg Mins, and he played at least MIN_GAMES games against that team. The game count comes
from the Top100_vs_Opponent sheet (one row per game; its averages match the grid exactly).

Usage:  python pipeline/build_matchup_alerts.py NBA_Mins_VS_Teams.xlsx
Needs:  pip install openpyxl   (only for this script)
"""
import datetime as dt, json, os, statistics as st, sys

sys.path.insert(0, os.path.dirname(__file__))
from update_data import TEAMS, team_code  # noqa: E402

MIN_DIFF = 5.0
MIN_GAMES = 5


def games_played(log_rows):
    """Top100_vs_Opponent rows (DID_NOT_PLAY, GAME_ID, MINUTES, OPPONENT_ABBR, PLAYER, ...) -> {(player, opp): games}."""
    out = {}
    for dnp, _gid, mins, opp, player, *_ in log_rows:
        code = team_code(opp)
        if not dnp and mins is not None and code:
            out[(str(player).strip(), code)] = out.get((str(player).strip(), code), 0) + 1
    return out


def alerts_from_grid(rows, games=None):
    """rows[0] = header (blank, 30 opponent codes, ...); then one row per player: name, 30 averages, team.
    games = {(player, opp): games played}; matchups with fewer than MIN_GAMES are skipped."""
    opps = [team_code(c) for c in rows[0][1:31]]
    out = []
    for r in rows[1:]:
        if not r or not r[0]:
            continue
        vals = [(o, float(v)) for o, v in zip(opps, r[1:31]) if o in TEAMS and isinstance(v, (int, float))]
        if not vals:
            continue
        avg = st.mean(v for _, v in vals)
        player = str(r[0]).strip()
        for o, v in vals:
            n = (games or {}).get((player, o), 0)
            if abs(v - avg) >= MIN_DIFF and n >= MIN_GAMES:
                out.append({"player": player, "opp": o, "dir": "up" if v > avg else "down",
                            "vs": round(v, 1), "avg": round(avg, 1), "games": n})
    return out


def main():
    import openpyxl
    wb = openpyxl.load_workbook(sys.argv[1], read_only=True, data_only=True)
    rows = list(wb["Player_vs_Team_Grid"].iter_rows(values_only=True))
    games = games_played(list(wb["Top100_vs_Opponent"].iter_rows(values_only=True))[1:])
    alerts = alerts_from_grid(rows, games)
    path = os.path.join(os.path.dirname(__file__), "matchup_alerts.json")
    json.dump({"_about": f"Built {dt.date.today()} from NBA_Mins_VS_Teams.xlsx (Team_Chart / Player_vs_Team_Grid). "
                         f"Alert = average vs that opponent at least {MIN_DIFF:g} min above/below the player's Avg Mins, "
                         f"over {MIN_GAMES}+ games vs that team (2023-24 to 2025-26). "
                         "Rebuild with pipeline/build_matchup_alerts.py.",
               "alerts": alerts}, open(path, "w"), indent=1)
    print(f"{len(alerts)} alerts -> {path}")


if __name__ == "__main__":
    main()
