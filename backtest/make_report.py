#!/usr/bin/env python3
"""Write backtest/REPORT.md from data/results.json and data/dataset_stats.json."""
import json, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, "data")      # optional: another data folder
OUT = os.path.join(HERE, "REPORT.md") if len(sys.argv) <= 1 else os.path.join(DATA, "REPORT.md")
R = json.load(open(os.path.join(DATA, "results.json")))
S = json.load(open(os.path.join(DATA, "dataset_stats.json")))
ORDER = ["Random", "Highest usual minutes", "Next man up (same position)", "Simple model", "Boosted ranker"]
STATUS = {"played": "played", "cd": "DNP coach's decision (not out)", "out": "DNP injury/illness/rest (out)",
          "inactive": "missing from box score while on the team (out)", "other": "DNP personal/suspension/other (not out)"}
pct = lambda x: f"{100 * x:.1f}%"


def table(block):
    rows = ["| Method | #1 pick is a gainer | Top 3 precision | Rank correlation |", "|---|---|---|---|"]
    for k in ORDER:
        v = block[k]
        rows.append(f"| {k} | {pct(v['top1'])} | {pct(v['p3'])} | {v['rho']:.3f} |")
    return "\n".join(rows)


def ci(block):
    lines = []
    for m, d in block["_vs_best_baseline"].items():
        lines.append(f"- **{m} vs {d['baseline']}:** #1 pick {100*d['top1'][0]:+.1f} to {100*d['top1'][1]:+.1f} points, "
                     f"top 3 {100*d['p3'][0]:+.1f} to {100*d['p3'][1]:+.1f} points, rank correlation {d['rho'][0]:+.3f} to {d['rho'][1]:+.3f} "
                     f"(95% range; if it doesn't cross 0, the gap is real)")
    return "\n".join(lines)


sp = R["splits"]["Train 2024-25, test 2025-26"]; wfb = R["walk_forward"]
best = R["best_model"]
bottom = [
    "## Bottom line", "",
    f"- Both models beat every simple rule in all three tests. Tested on 2025-26 after training on 2024-25, the #1 pick "
    f"gained 2+ minutes {pct(sp['Boosted ranker']['top1'])} of the time (boosted ranker) and {pct(sp['Simple model']['top1'])} (simple model), "
    f"against {pct(sp['Next man up (same position)']['top1'])} for next man up at the same position, "
    f"{pct(sp['Highest usual minutes']['top1'])} for the highest-minutes teammate and {pct(sp['Random']['top1'])} for a random pick.",
    f"- Re-trained month by month through 2025-26, the boosted ranker's #1 pick was right {pct(wfb['Boosted ranker']['top1'])} of the time; "
    f"its top 3 averaged {pct(wfb['Boosted ranker']['p3'])} gainers and its ranking correlated {wfb['Boosted ranker']['rho']:.2f} with the real changes "
    f"(next man up: {wfb['Next man up (same position)']['rho']:.2f}).",
    "- The simple model is nearly as good as the boosted ranker and is easier to explain, so it is the one to start with.",
    "- The strongest signal is a player whose minutes were already rising in his last 3 games. Next: lower usual minutes "
    "(a bench player clears +2 more easily than a 34-minute starter), and how he did the last times a similar teammate was out. "
    "Playing the same position as the missing player adds little once those are known.",
    "- Highest-minutes teammate is worse than random: stars are already near their ceiling.",
    "",
    "## Limits", "",
    "- ESPN leaves most inactive players out of its box scores, so a player missing from a game while on the team counts as "
    "inactive (out). ESPN does not say why for those; rare non-injury absences (personal, G League) can slip in.",
    "- An absence only counts for its first 10 games; after that his teammates' 10-game baselines already include it.",
    f"- {S['players_dropped_multi_team']} players who played for two teams were dropped, as asked; that removes many rotation players from trade-deadline teams.",
    "- ESPN minutes are whole numbers.",
    "- The most common miss is a #1 pick who doesn't play at all (coach's decision), often late in the season.", ""]
out = [f"# Who gains minutes when a teammate is out: backtest report", "",
       "Ranking only: for each game where a rotation player (15+ minute baseline) is out, rank his healthy teammates by how "
       "likely they are to play 2+ minutes more than their baseline (average of their previous 10 games).", "",
       *bottom, "## Data", "",
       f"- {S['games']:,} regular-season games (2024-25 and 2025-26) from ESPN box scores; {S['players_all']:,} players.",
       f"- Dropped {S['players_dropped_multi_team']:,} players who played for more than one team; {S['players_kept']:,} kept.",
       f"- Player-games by status: " + ", ".join(f"{STATUS.get(k, k)} {v:,}" for k, v in S["status_counts"].items()) + ".",
       f"- Test units (team-games with a rotation player out): {S['units']:,} "
       f"({', '.join(f'{k}: {v:,}' for k, v in sorted(S['units_by_season'].items()))}); {S['candidates']:,} teammate rankings scored.",
       f"- Share of healthy teammates who gained 2+ minutes: {pct(S['gainer_rate'])}. That is what a random pick gets.", ""]
for label, block in R["splits"].items():
    out += [f"## {label}", "", table(block), "", ci(block), ""]
out += ["## Walk-forward through 2025-26 (re-trained each month on everything before it)", "", table(R["walk_forward"]), ""]
months = sorted({k.split("|")[0] for k in R["walk_forward_by_month"]})
out += ["| Month | " + " | ".join(ORDER[1:]) + " |", "|---|" + "---|" * (len(ORDER) - 1)]
for mth in months:
    out.append(f"| {mth} | " + " | ".join(pct(R["walk_forward_by_month"][f"{mth}|{k}"]["top1"]) for k in ORDER[1:]) + " |")
out += ["", "_(#1 pick is a gainer, by month)_", "",
        "## What the models look at", "", "**Simple model** (weights on a common scale; + means more likely to gain):", ""]
out += [f"- {n}: {w:+.2f}" for n, w in R["simple_weights"]]
out += ["", "**Boosted ranker** (share of what it learned from each input):", ""]
out += [f"- {n}: {w:.1f}%" for n, w in R["gbm_importance"]]
out += ["", f"## Where the model fails ({R['best_model']}, test 2025-26; next man up shown for comparison)", ""]
for k, d in R["fail_by"].items():
    if k == "Units":
        out += [f"- {kk}: {pct(vv)}" for kk, vv in d.items()]
        continue
    out += [f"**{k}**", "", "| | Model #1 pick right | Next man up #1 pick right |", "|---|---|---|"]
    out += [f"| {kk} | {pct(vv['top1'])} | {pct(vv['nextman_top1'])} |" for kk, vv in d.items()]
    out.append("")
for title, key in (("Examples: hits", "examples_hit"), ("Examples: misses", "examples_miss")):
    out += ["", f"## {title}", "", "| Date | Team | Opp | Out (baseline) | Model's top 3 (actual change) | Biggest real gainer |", "|---|---|---|---|---|---|"]
    out += [f"| {e['date']} | {e['team']} | {e['opponent']} | {e['out_players']} | {e['model_top3']} | {e['real_biggest']} |" for e in R[key]]
open(OUT, "w").write("\n".join(out) + "\n")
print("wrote REPORT.md")
