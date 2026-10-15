#!/usr/bin/env python3
"""Hand-adjust two weights of the tuned simple model and see what happens.

  last-game weight x A  ("his last game vs his usual")
  bench weight x B      ("coach's-decision benchings in the last 5 games")

Each version is scored on the test season (train one season, test the other, both ways) and also on a check
inside the training season (last 25% of its dates), so a change that only fits the test seasons shows up.
Gainer = +1 minute. Writes data/weights_experiment.json.
"""
import json, os
import numpy as np
import pandas as pd
import backtest as bt
import tune

GAIN = 1.0
GRID = [(1, 1), (1.5, 1), (2, 1), (3, 1), (1, 0.5), (1, 0), (1.5, 0.5), (2, 0.5), (2, 0.25), (3, 0.5), (3, 0)]
LAST, BENCH = "last1_vs_base", "cd_last5"


def adjusted(model, a, b):
    kind, F, sc, lr = model
    w = lr.coef_[0].copy()
    w[F.index(LAST)] *= a
    w[F.index(BENCH)] *= b
    return lambda df: sc.transform(df[F]) @ w + lr.intercept_[0]


def scores(df, f):
    d = df.copy(); d["s"] = f(d)
    s = bt.summarize(bt.unit_metrics(d, "s"))
    top = d.sort_values("s", ascending=False).groupby("unit").head(1)
    q = pd.qcut(top["s"].rank(method="first"), 4, labels=False)
    s["most_confident_quarter"] = top["gainer"][q == 3].mean()
    return s


def main():
    C = pd.read_csv(os.path.join(bt.DATA, "candidates.csv"), dtype={"game_id": str, "player_id": str})
    C[tune.PLUS] = C[tune.PLUS].fillna(0); C["gainer"] = (C["truth"] >= GAIN).astype(int)
    s1, s2 = C[C["season"] == "2024-25"], C[C["season"] == "2025-26"]
    chosen = json.load(open(os.path.join(bt.DATA, "results_tuned_gain1.json")))["chosen"]
    out = {}
    for label, tr, te in (("Train 2024-25, test 2025-26", s1, s2), ("Train 2025-26, test 2024-25", s2, s1)):
        cfg = chosen[label]["simple"]
        dates = sorted(tr["date"].unique()); cut = dates[int(len(dates) * 0.75)]
        early, late = tr[tr["date"] < cut], tr[tr["date"] >= cut]
        m_check, m_full = tune.fit(cfg, early), tune.fit(cfg, tr)
        out[label] = []
        for a, b in GRID:
            out[label].append({"last_game_x": a, "bench_x": b, "check": scores(late, adjusted(m_check, a, b)),
                               "test": scores(te, adjusted(m_full, a, b))})
    json.dump(out, open(os.path.join(bt.DATA, "weights_experiment.json"), "w"), indent=1, default=float)
    for label, rows in out.items():
        print(label)
        print("  last x  bench x | check #1   test #1   test top3  test corr  test most-confident 25%")
        for r in rows:
            c, t = r["check"], r["test"]
            print(f"   {r['last_game_x']:>4}    {r['bench_x']:>4}  |  {c['top1']:.3f}    {t['top1']:.3f}    {t['p3']:.3f}     {t['rho']:.3f}      {t['most_confident_quarter']:.3f}")


if __name__ == "__main__":
    main()
