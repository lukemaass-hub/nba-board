#!/usr/bin/env python3
"""Backtest: rank healthy teammates by how likely they are to GAIN minutes (+2 or more vs baseline) when a
rotation teammate is out. Ranking only.

Scores per unit (team-game with a rotation player out), averaged over units:
  top1  = is the #1 pick a real gainer
  p3    = share of the top 3 picks who are real gainers
  rho   = Spearman rank correlation between the ranking and the real minute changes
Tests: train 2024-25 -> test 2025-26; train 2025-26 -> test 2024-25; walk-forward by month through 2025-26.
Baselines: random, highest-baseline-minutes teammate, next man up at the same position.
"""
import json, os
import numpy as np
import pandas as pd
from scipy.stats import spearmanr
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler
import lightgbm as lgb

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
FEATURES = ["baseline", "is_starter", "bench_rank", "base_rank", "overlap_top", "vacated_same_pos", "starter_out_same_pos",
            "vacated_total", "n_out", "n_healthy", "trend", "out_streak", "hist_similar", "hist_any"]
PLAIN = {"baseline": "his usual minutes (last 10 games)", "is_starter": "he is a starter", "bench_rank": "his spot in the bench order",
         "base_rank": "his minutes rank on the team", "overlap_top": "plays the same position as the main player out",
         "vacated_same_pos": "minutes missing at his position", "starter_out_same_pos": "a starter at his position is out",
         "vacated_total": "total minutes missing", "n_out": "number of rotation players out", "n_healthy": "number of healthy teammates",
         "trend": "his last 3 games vs his usual", "out_streak": "how many games the main player has been out", "hist_similar": "how he did before when a similar player was out (shrunk)",
         "hist_any": "how he did before in any game with a teammate out (shrunk)"}
RNG = np.random.default_rng(7)


# ---------------------------------------------------------------- scoring
def unit_metrics(df, score_col):
    out = []
    for u, g in df.groupby("unit", sort=False):
        g = g.sort_values([score_col, "baseline"], ascending=[False, False])
        top = g["gainer"].to_numpy()
        rho = spearmanr(g[score_col], g["truth"]).statistic if g[score_col].nunique() > 1 and g["truth"].nunique() > 1 else np.nan
        out.append({"unit": u, "top1": top[0], "p3": top[:3].mean(), "rho": rho, "pick": g["player"].iat[0], "pick_truth": g["truth"].iat[0]})
    return pd.DataFrame(out)


def random_metrics(df):
    """Expected scores of a random ordering: top1 and p3 = share of gainers among candidates; rho = 0."""
    r = df.groupby("unit", sort=False)["gainer"].mean().rename("top1").reset_index()
    r["p3"], r["rho"] = r["top1"], 0.0
    return r


def summarize(m):
    return {"units": len(m), "top1": m["top1"].mean(), "p3": m["p3"].mean(), "rho": m["rho"].mean(skipna=True)}


def boot_diff(a, b, col, n=2000):
    """95% interval for mean(a - b) over units (paired bootstrap)."""
    d = (a.set_index("unit")[col] - b.set_index("unit")[col]).dropna().to_numpy()
    if not len(d):
        return (np.nan, np.nan)
    means = [RNG.choice(d, len(d)).mean() for _ in range(n)]
    return (np.percentile(means, 2.5), np.percentile(means, 97.5))


# ---------------------------------------------------------------- baselines
def add_baselines(df):
    df = df.copy()
    df["s_highest"] = df["baseline"]
    # next man up: same position as the main player out first, bench players before starters, then usual minutes
    df["s_nextman"] = df["overlap_top"] * 1000 + (1 - df["is_starter"]) * 100 + df["baseline"]
    return df


# ---------------------------------------------------------------- models
def fit_simple(train):
    sc = StandardScaler().fit(train[FEATURES])
    lr = LogisticRegression(C=0.5, max_iter=2000).fit(sc.transform(train[FEATURES]), train["gainer"])
    return sc, lr


def score_simple(model, df):
    sc, lr = model
    return lr.predict_proba(sc.transform(df[FEATURES]))[:, 1]


def grade(t):
    return np.select([t >= 6, t >= 2], [2, 1], 0)


def fit_gbm(train):
    train = train.sort_values("unit")
    m = lgb.LGBMRanker(objective="lambdarank", n_estimators=300, learning_rate=0.03, num_leaves=15, min_child_samples=60,
                       subsample=0.8, subsample_freq=1, colsample_bytree=0.8, reg_lambda=1.0, verbose=-1, random_state=7)
    m.fit(train[FEATURES], grade(train["truth"]), group=train.groupby("unit", sort=False).size().to_numpy())
    return m


def run_split(train, test):
    test = add_baselines(test)
    test["s_simple"] = score_simple(fit_simple(train), test)
    gbm = fit_gbm(train)
    test["s_gbm"] = gbm.predict(test[FEATURES])
    res = {"Random": random_metrics(test), "Highest usual minutes": unit_metrics(test, "s_highest"),
           "Next man up (same position)": unit_metrics(test, "s_nextman"), "Simple model": unit_metrics(test, "s_simple"),
           "Boosted ranker": unit_metrics(test, "s_gbm")}
    return test, res, gbm


def main():
    C = pd.read_csv(os.path.join(DATA, "candidates.csv"), dtype={"game_id": str, "player_id": str})
    U = pd.read_csv(os.path.join(DATA, "units.csv"), dtype={"game_id": str})
    C[FEATURES] = C[FEATURES].fillna(0)
    s1, s2 = C[C["season"] == "2024-25"], C[C["season"] == "2025-26"]
    out = {"splits": {}}
    scored = {}

    for label, tr, te in (("Train 2024-25, test 2025-26", s1, s2), ("Train 2025-26, test 2024-25", s2, s1)):
        test, res, gbm = run_split(tr, te)
        out["splits"][label] = {k: summarize(v) for k, v in res.items()}
        best_base = max(["Highest usual minutes", "Next man up (same position)"], key=lambda k: res[k]["top1"].mean())
        out["splits"][label]["_vs_best_baseline"] = {
            m: {"baseline": best_base, **{c: boot_diff(res[m], res[best_base], c) for c in ("top1", "p3", "rho")}}
            for m in ("Simple model", "Boosted ranker")}
        scored[label] = (test, res)

    # walk-forward through 2025-26 by month
    s2m = s2.assign(month=s2["date"].str[:7])
    wf = []
    for month in sorted(s2m["month"].unique()):
        tr = pd.concat([s1, s2m[s2m["month"] < month].drop(columns="month")])
        te = s2m[s2m["month"] == month].drop(columns="month")
        if te["unit"].nunique() < 20:
            continue
        _, res, _ = run_split(tr, te)
        for k, v in res.items():
            wf.append(v.assign(model=k, month=month))
    wf = pd.concat(wf)
    out["walk_forward"] = {k: summarize(g) for k, g in wf.groupby("model")}
    out["walk_forward_by_month"] = {f"{m}|{k}": summarize(g) for (m, k), g in wf.groupby(["month", "model"])}

    # explain: simple-model weights and boosted-ranker importance, trained on both seasons
    sc, lr = fit_simple(C)
    out["simple_weights"] = sorted(((PLAIN[f], round(w, 3)) for f, w in zip(FEATURES, lr.coef_[0])), key=lambda x: -abs(x[1]))
    gbm = fit_gbm(C)
    imp = gbm.booster_.feature_importance("gain")
    out["gbm_importance"] = sorted(((PLAIN[f], round(100 * v / imp.sum(), 1)) for f, v in zip(FEATURES, imp)), key=lambda x: -x[1])

    # where it fails (main test split), plus examples
    test, res = scored["Train 2024-25, test 2025-26"]
    best = "Simple model" if res["Simple model"]["top1"].mean() >= res["Boosted ranker"]["top1"].mean() else "Boosted ranker"
    col = "s_simple" if best == "Simple model" else "s_gbm"
    m = res[best].merge(U[["unit", "date", "team", "opponent", "out_players", "top_out_group", "n_out", "vacated", "n_gainers", "n_candidates", "out_streak"]], on="unit")
    nm = res["Next man up (same position)"].set_index("unit")["top1"]
    m["nextman_top1"] = m["unit"].map(nm)
    out["best_model"] = best
    out["fail_by"] = {
        "Players out": m.groupby(np.where(m["n_out"] >= 3, "3+", m["n_out"].astype(str)))[["top1", "nextman_top1"]].mean().round(3).to_dict("index"),
        "Position of main player out": m.groupby("top_out_group")[["top1", "nextman_top1"]].mean().round(3).to_dict("index"),
        "Game of the absence": m.groupby(np.select([m["out_streak"] == 1, m["out_streak"] <= 3], ["1st game out", "2nd-3rd"], "4th-10th"))[["top1", "nextman_top1"]].mean().round(3).to_dict("index"),
        "Time of season": m.groupby(np.where(m["date"].str[5:7] == "04", "April (end of season)", "Oct-Mar"))[["top1", "nextman_top1"]].mean().round(3).to_dict("index"),
        "Gainers available": m.groupby(np.select([m["n_gainers"] == 0, m["n_gainers"] <= 2], ["0", "1-2"], "3+"))[["top1", "nextman_top1"]].mean().round(3).to_dict("index"),
        "Units": {"no gainer at all (nobody could be right)": round((m["n_gainers"] == 0).mean(), 3)},
    }
    top3 = (test.sort_values([col, "baseline"], ascending=[False, False]).groupby("unit").head(3)
            .groupby("unit").apply(lambda g: ", ".join(f"{p} ({t:+.0f})" for p, t in zip(g["player"], g["truth"])), include_groups=False))
    best_real = test.sort_values("truth", ascending=False).groupby("unit").head(1).set_index("unit")
    m["model_top3"] = m["unit"].map(top3)
    m["real_biggest"] = m["unit"].map(lambda u: f"{best_real.at[u, 'player']} ({best_real.at[u, 'truth']:+.0f})")
    ex_cols = ["date", "team", "opponent", "out_players", "model_top3", "real_biggest"]
    hits = m[(m["top1"] == 1) & (m["vacated"] >= 30)].sort_values("pick_truth", ascending=False).head(6)
    misses = m[(m["top1"] == 0) & (m["n_gainers"] > 0) & (m["vacated"] >= 30)].sort_values("pick_truth").head(6)
    out["examples_hit"] = hits[ex_cols].to_dict("records"); out["examples_miss"] = misses[ex_cols].to_dict("records")
    json.dump(out, open(os.path.join(DATA, "results.json"), "w"), indent=1, default=float)
    print(json.dumps({k: out[k] for k in ("splits", "walk_forward", "best_model")}, indent=1, default=float))


if __name__ == "__main__":
    main()
