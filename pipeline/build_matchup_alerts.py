#!/usr/bin/env python3
"""Turn the minutes-vs-opponent workbook into matchup alerts (pipeline/matchup_alerts.json).

Uses the same numbers as the workbook's Team_Chart sheet ("Select Team"): that sheet filters
Player_vs_Team_Grid by team and shows each player's average minutes against every opponent, plus
"Avg Mins" = the average of those 30 opponent averages. This script does that for all 100 players at once.

A matchup becomes an alert when the player's average against that opponent is at least MIN_DIFF minutes
above or below his Avg Mins. The sheet has no game counts, so one odd game can cause an alert; the report
says so.

Usage:  python pipeline/build_matchup_alerts.py NBA_Mins_VS_Teams.xlsx
Needs:  pip install openpyxl   (only for this script)
"""
import datetime as dt, json, os, statistics as st, sys

sys.path.insert(0, os.path.dirname(__file__))
from update_data import TEAMS, team_code  # noqa: E402

MIN_DIFF = 5.0


def alerts_from_grid(rows):
    """rows[0] = header (blank, 30 opponent codes, ...); then one row per player: name, 30 averages, team."""
    opps = [team_code(c) for c in rows[0][1:31]]
    out = []
    for r in rows[1:]:
        if not r or not r[0]:
            continue
        vals = [(o, float(v)) for o, v in zip(opps, r[1:31]) if o in TEAMS and isinstance(v, (int, float))]
        if not vals:
            continue
        avg = st.mean(v for _, v in vals)
        for o, v in vals:
            if abs(v - avg) >= MIN_DIFF:
                out.append({"player": str(r[0]).strip(), "opp": o, "dir": "up" if v > avg else "down",
                            "vs": round(v, 1), "avg": round(avg, 1)})
    return out


def main():
    import openpyxl
    wb = openpyxl.load_workbook(sys.argv[1], read_only=True, data_only=True)
    rows = list(wb["Player_vs_Team_Grid"].iter_rows(values_only=True))
    alerts = alerts_from_grid(rows)
    path = os.path.join(os.path.dirname(__file__), "matchup_alerts.json")
    json.dump({"_about": f"Built {dt.date.today()} from NBA_Mins_VS_Teams.xlsx (Team_Chart / Player_vs_Team_Grid). "
                         f"Alert = average vs that opponent at least {MIN_DIFF:g} min above/below the player's Avg Mins. "
                         "Rebuild with pipeline/build_matchup_alerts.py.",
               "alerts": alerts}, open(path, "w"), indent=1)
    print(f"{len(alerts)} alerts -> {path}")


if __name__ == "__main__":
    main()
