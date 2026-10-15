#!/usr/bin/env python3
"""One-tab CSV of the backtest results for Google Sheets (Drive converts it on upload). Sections are stacked;
the 'vs best simple rule' cells are formulas over the rows above them."""
import csv, datetime as dt, io, json, os

HERE = os.path.dirname(os.path.abspath(__file__))
R = json.load(open(os.path.join(HERE, "data", "results.json")))
S = json.load(open(os.path.join(HERE, "data", "dataset_stats.json")))
ORDER = ["Random", "Highest usual minutes", "Next man up (same position)", "Simple model", "Boosted ranker"]
p = lambda x: f"{100 * x:.1f}%"
LABELS = {("Players out", "1"): "1 player out", ("Players out", "2"): "2 players out", ("Players out", "3+"): "3 or more out",
          ("Position of main player out", "C"): "Center", ("Position of main player out", "F"): "Forward",
          ("Position of main player out", "G"): "Guard", ("Gainers available", "0"): "No teammate gained",
          ("Gainers available", "1-2"): "1 or 2 teammates gained", ("Gainers available", "3+"): "3 or more gained",
          ("Game of the absence", "2nd-3rd"): "2nd or 3rd game out", ("Game of the absence", "4th-10th"): "4th to 10th game out"}
rows = []
add = rows.append
sp = R["splits"]["Train 2024-25, test 2025-26"]
add([f"Both models beat every simple rule: the #1 pick gained minutes {100*sp['Simple model']['top1']:.0f}% of the time, "
     f"vs {100*sp['Next man up (same position)']['top1']:.0f}% for next man up"])
add(["Ranks healthy teammates by chance of playing 2+ minutes above their 10-game baseline, in team-games where a rotation player (15+ min) is out."])
add([f"Source: backtest/backtest.py (github.com/lukemaass-hub/nba-board), ESPN box scores, 2024-25 and 2025-26 regular seasons, "
     f"{S['games']:,} games, {S['units']:,} team-games with a rotation player out. Run by Claude {dt.date.today()}. Full write-up: backtest/REPORT.md"])
add([])
for label, block in list(R["splits"].items()) + [("Walk-forward through 2025-26 (re-trained each month)", R["walk_forward"])]:
    add([label])
    add(["Method", "Units", "#1 pick is a gainer", "Top 3 precision", "Rank correlation", "#1 pick vs best simple rule", "Top 3 vs best simple rule"])
    first = len(rows) + 1                                  # sheet row of "Random"
    for k in ORDER:
        v = block[k]; r = len(rows) + 1
        row = [k, v["units"], p(v["top1"]), p(v["p3"]), f"{v['rho']:.3f}"]
        if k in ("Simple model", "Boosted ranker"):
            row += [f"=C{r}-MAX(C{first + 1}:C{first + 2})", f"=D{r}-MAX(D{first + 1}:D{first + 2})"]
        add(row)
    if "_vs_best_baseline" in block:
        for m, d in block["_vs_best_baseline"].items():
            add([f"{m} vs {d['baseline']}: 95% range of the #1-pick gap {100*d['top1'][0]:+.1f} to {100*d['top1'][1]:+.1f} points"])
    add([])
add(["Walk-forward by month: #1 pick is a gainer"])
add(["Month", "Units"] + ORDER)
months = sorted({k.split("|")[0] for k in R["walk_forward_by_month"]})
m0 = len(rows) + 1
for mth in months:
    add([dt.date(int(mth[:4]), int(mth[5:]), 1).strftime("%b (%Y)"), R["walk_forward_by_month"][f"{mth}|Simple model"]["units"]] + [p(R["walk_forward_by_month"][f"{mth}|{k}"]["top1"]) for k in ORDER])
m1 = len(rows)
add(["Weighted by units", f"=SUM(B{m0}:B{m1})"] + [f"=SUMPRODUCT($B${m0}:$B${m1},{c}{m0}:{c}{m1})/$B${m1 + 1}" for c in "CDEFG"])
add([])
add(["What the simple model looks at", "Weight (+ = more likely to gain)"])
for n, w in R["simple_weights"]:
    add([n, f"{w:+.2f}"])
add([])
add(["What the boosted ranker looks at", "Share of what it learned"])
for n, w in R["gbm_importance"]:
    add([n, f"{w:.1f}%"])
add([])
add([f"Where the #1 pick goes wrong ({R['best_model']}, tested on 2025-26)", "Model #1 pick right", "Next man up #1 pick right", "Model minus next man up"])
for k, d in R["fail_by"].items():
    if k == "Units":
        for kk, vv in d.items():
            add([f"Share of games with {kk}", p(vv)])
        continue
    add([k])
    for kk, vv in d.items():
        r = len(rows) + 1
        add([f"  {LABELS.get((k, kk), kk)}", p(vv["top1"]), p(vv["nextman_top1"]), f"=B{r}-C{r}"])
add([])
for title, key in (("Hits (2025-26, 30+ minutes missing): the #1 pick gained minutes", "examples_hit"),
                   ("Misses: the #1 pick did not, though someone else did", "examples_miss")):
    add([title])
    add(["Date", "Team", "Opponent", "Out (baseline minutes)", "Model's top 3 (actual change)", "Biggest real gainer"])
    for e in R[key]:
        add([e["date"], e["team"], e["opponent"], e["out_players"], e["model_top3"], e["real_biggest"]])
    add([])
add(["Data source"])
add(["Source", "Object", "Obtained via", "Request", "Run at", "Requested by", "Rows", "Changes after retrieval"])
add(["ESPN public JSON (scoreboard + game summary box scores)", "site.api.espn.com/apis/site/v2/sports/basketball/nba/summary?event=ID",
     "Downloaded and scored by Claude", "Backtest which healthy teammates gain 2+ minutes when a rotation teammate is out",
     str(dt.date.today()), "Luke", f"{S['candidates']:,} teammate rows",
     "Postponed, All-Star and NBA Cup final games removed; players on two teams dropped; aggregated by backtest/backtest.py"])
buf = io.StringIO(); csv.writer(buf).writerows(rows)
open(os.path.join(HERE, "results_for_sheets.csv"), "w").write(buf.getvalue())
print(len(rows), "rows,", len(buf.getvalue()), "chars")
