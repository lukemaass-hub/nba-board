#!/usr/bin/env python3
"""Tune both models, then re-run every test. Gainer = +GAIN minutes vs the 10-game baseline (default +1).

Tuning never looks at the test season: inside the training season, the first 75% of dates train and the last 25%
check; the settings with the best check score (#1 pick + top-3 precision) are refit on the whole training season
and then scored once on the test season. Writes data/results_tuned.json.
"""
import itertools, json, os, sys
import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler
import lightgbm as lgb
import backtest as bt

GAIN = 1.0                                   # set from the command line in main()
BASE = bt.FEATURES
NEW = ["last1_vs_base", "std10", "cd_last5", "b2b", "home"]
PLUS = BASE + NEW
bt.PLAIN.update({"last1_vs_base": "his last game vs his usual", "std10": "how much his minutes swing game to game",
                 "cd_last5": "coach's-decision benchings in the last 5 games", "b2b": "second night of a back-to-back",
                 "home": "home game"})
LR_GRID = [{"kind": "lr", "C": c, "feats": f} for c, f in itertools.product([0.02, 0.1, 0.5, 2.0], ["base", "plus"])]
GBM_GRID = [{"kind": "gbm", "obj": o, "leaves": l, "trees": t, "minchild": m, "feats": "plus"}
            for o, l, t, m in itertools.product(["lambdarank", "binary"], [7, 15, 31], [200, 500], [30, 100])]


def feats(cfg):
    return BASE if cfg["feats"] == "base" else PLUS


def fit(cfg, tr):
    F = feats(cfg)
    if cfg["kind"] == "lr":
        sc = StandardScaler().fit(tr[F])
        return ("lr", F, sc, LogisticRegression(C=cfg["C"], max_iter=3000).fit(sc.transform(tr[F]), tr["gainer"]))
    tr = tr.sort_values("unit")
    common = dict(n_estimators=cfg["trees"], learning_rate=0.03, num_leaves=cfg["leaves"], min_child_samples=cfg["minchild"],
                  subsample=0.8, subsample_freq=1, colsample_bytree=0.8, reg_lambda=1.0, verbose=-1, random_state=7)
    if cfg["obj"] == "lambdarank":
        m = lgb.LGBMRanker(objective="lambdarank", **common)
        m.fit(tr[F], np.select([tr["truth"] >= GAIN + 4, tr["truth"] >= GAIN], [2, 1], 0),
              group=tr.groupby("unit", sort=False).size().to_numpy())
    else:
        m = lgb.LGBMClassifier(objective="binary", **common).fit(tr[F], tr["gainer"])
    return ("gbm", F, None, m)


def score(model, df):
    kind, F, sc, m = model
    if kind == "lr":
        return m.predict_proba(sc.transform(df[F]))[:, 1]
    return m.predict_proba(df[F])[:, 1] if isinstance(m, lgb.LGBMClassifier) else m.predict(df[F])


def evaluate(df, col):
    s = bt.summarize(bt.unit_metrics(df, col))
    return s, s["top1"] + s["p3"]


def pick(grid, tr):
    """Best settings on the late part of the training season."""
    dates = sorted(tr["date"].unique()); cut = dates[int(len(dates) * 0.75)]
    a, b = tr[tr["date"] < cut], tr[tr["date"] >= cut].copy()
    best = None
    for cfg in grid:
        b["s"] = score(fit(cfg, a), b)
        _, v = evaluate(b, "s")
        if best is None or v > best[1]:
            best = (cfg, v)
    return best[0]


def rank01(df, col):
    return df.groupby("unit")[col].rank(pct=True)


def run(tr, te, lr_cfg, gbm_cfg):
    te = bt.add_baselines(te)
    te["s_old_simple"] = bt.score_simple(bt.fit_simple(tr), te)            # the original models, same +GAIN target
    te["s_old_gbm"] = bt.fit_gbm(tr).predict(te[bt.FEATURES])
    te["s_lr"] = score(fit(lr_cfg, tr), te)
    te["s_gbm"] = score(fit(gbm_cfg, tr), te)
    te["s_ens"] = rank01(te, "s_lr") + rank01(te, "s_gbm")                # average of the two rankings
    cols = {"Random": None, "Highest usual minutes": "s_highest", "Next man up (same position)": "s_nextman",
            "Original simple model": "s_old_simple", "Original boosted ranker": "s_old_gbm",
            "Tuned simple model": "s_lr", "Tuned boosted ranker": "s_gbm", "Tuned blend (both)": "s_ens"}
    res = {k: (bt.random_metrics(te) if c is None else bt.unit_metrics(te, c)) for k, c in cols.items()}
    return te, res


def main():
    global GAIN
    GAIN = float(sys.argv[1]) if len(sys.argv) > 1 else 1.0
    C = pd.read_csv(os.path.join(bt.DATA, "candidates.csv"), dtype={"game_id": str, "player_id": str})
    C[PLUS] = C[PLUS].fillna(0)
    C["gainer"] = (C["truth"] >= GAIN).astype(int)
    bt.grade = lambda t: np.select([t >= GAIN + 4, t >= GAIN], [2, 1], 0)   # original ranker uses the same target
    s1, s2 = C[C["season"] == "2024-25"], C[C["season"] == "2025-26"]
    out = {"gain": GAIN, "gainer_rate": round(C["gainer"].mean(), 3), "splits": {}, "chosen": {}}
    for label, tr, te in (("Train 2024-25, test 2025-26", s1, s2), ("Train 2025-26, test 2024-25", s2, s1)):
        lr_cfg, gbm_cfg = pick(LR_GRID, tr), pick(GBM_GRID, tr)
        out["chosen"][label] = {"simple": lr_cfg, "boosted": gbm_cfg}
        _, res = run(tr, te, lr_cfg, gbm_cfg)
        out["splits"][label] = {k: bt.summarize(v) for k, v in res.items()}
        out["splits"][label]["_ci"] = {m: {c: bt.boot_diff(res[m], res["Next man up (same position)"], c) for c in ("top1", "p3")}
                                       for m in ("Tuned simple model", "Tuned boosted ranker", "Tuned blend (both)")}
        print(label, "chosen:", lr_cfg, gbm_cfg, flush=True)
    # walk-forward through 2025-26 with the settings picked on 2024-25
    lr_cfg, gbm_cfg = out["chosen"]["Train 2024-25, test 2025-26"].values()
    s2m = s2.assign(month=s2["date"].str[:7]); wf = []
    for month in sorted(s2m["month"].unique()):
        tr = pd.concat([s1, s2m[s2m["month"] < month].drop(columns="month")]); te = s2m[s2m["month"] == month].drop(columns="month")
        _, res = run(tr, te, lr_cfg, gbm_cfg)
        for k, v in res.items():
            wf.append(v.assign(model=k, month=month))
    wf = pd.concat(wf)
    out["walk_forward"] = {k: bt.summarize(g) for k, g in wf.groupby("model")}
    out["walk_forward_by_month"] = {f"{m}|{k}": bt.summarize(g) for (m, k), g in wf.groupby(["month", "model"])}
    # weights of the tuned simple model on both seasons, in plain words
    m = fit(lr_cfg, C); _, F, sc, lr = m
    out["tuned_simple_weights"] = sorted(((bt.PLAIN[f], round(w, 3)) for f, w in zip(F, lr.coef_[0])), key=lambda x: -abs(x[1]))
    g = fit(gbm_cfg, C)[3]; imp = g.booster_.feature_importance("gain")
    out["tuned_gbm_importance"] = sorted(((bt.PLAIN[f], round(100 * v / imp.sum(), 1)) for f, v in zip(PLUS, imp)), key=lambda x: -x[1])
    # how sure: #1 pick hit rate by how far ahead the model's #1 is (blend, test 2025-26)
    te, _ = run(s1, s2, *out["chosen"]["Train 2024-25, test 2025-26"].values())
    top = te.sort_values("s_lr", ascending=False).groupby("unit").head(1)
    top["conf"] = pd.qcut(top["s_lr"], 4, labels=["lowest 25%", "25-50%", "50-75%", "most confident 25%"])
    out["by_confidence"] = top.groupby("conf", observed=True)["gainer"].mean().round(3).to_dict()
    json.dump(out, open(os.path.join(bt.DATA, f"results_tuned_gain{GAIN:g}.json"), "w"), indent=1, default=float)
    for split, b in list(out["splits"].items()) + [("Walk-forward", out["walk_forward"])]:
        print(split)
        for k, v in b.items():
            if not k.startswith("_"):
                print(f"  {k:30s} top1 {v['top1']:.3f}  p3 {v['p3']:.3f}  rho {v['rho']:.3f}")
    print("by confidence:", out["by_confidence"])


if __name__ == "__main__":
    main()
