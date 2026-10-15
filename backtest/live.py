#!/usr/bin/env python3
"""Live test of the teammate-minutes model on the 2026-27 season.

  python backtest/live.py update     # download new 2026-27 box scores from ESPN (box_2026-27.csv)
  python backtest/live.py predict    # rank healthy teammates for games starting soon, where a rotation player is out
  python backtest/live.py score      # score finished games against the real box score; rewrite live/SCORECARD.md

Picks for a game are rewritten until it starts (so the latest injury news is used) and then locked.
"Out" = listed Out or Doubtful on the board's injury report (data.json, which already applies beat-writer news).
The model is the tuned simple model trained on 2024-25 + 2025-26, with the two weights in live/settings.json.
"""
import csv, datetime as dt, json, os, sys
import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE); sys.path.insert(0, os.path.join(HERE, "..", "pipeline"))
import backtest as bt, build_dataset as bd, fetch_espn as fe, tune  # noqa: E402
from update_data import ET, norm_name  # noqa: E402

LIVE = os.path.join(HERE, "live"); PRED = os.path.join(LIVE, "predictions")
DATA = bt.DATA
SEASON, SEASON_YEAR, SEASON_START = "2026-27", 2027, "2026-10-20"
SET = json.load(open(os.path.join(LIVE, "settings.json")))
if os.environ.get("LIVE_DRY"):              # test run: allow preseason games and any tip time
    SET.update(regular_season_only=False, predict_within_minutes=24 * 60)
ABBR = bd.ESPN_ABBR
SB = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard?dates={}"
TEAM_IDS = {}


# ---------------------------------------------------------------- data
def box_history():
    files = [os.path.join(DATA, f"box_{s}.csv") for s in ("2024-25", "2025-26", SEASON)]
    b = pd.concat([pd.read_csv(f, dtype={"game_id": str, "player_id": str}) for f in files if os.path.exists(f)])
    b["team"] = b["team"].replace(ABBR)
    return b.sort_values(["date", "game_id"])


def games_on(day, season_type):
    out = []
    for e in fe.get(SB.format(day.strftime("%Y%m%d"))).get("events", []):
        s = e.get("season") or {}
        if s.get("year") != SEASON_YEAR or (SET["regular_season_only"] and s.get("type") != 2) or s.get("type") not in season_type:
            continue
        comp = e["competitions"][0]
        teams = {c["homeAway"]: c["team"] for c in comp["competitors"]}
        for c in comp["competitors"]:
            TEAM_IDS[ABBR.get(c["team"]["abbreviation"], c["team"]["abbreviation"])] = c["team"]["id"]
        out.append({"game_id": e["id"], "tip": dt.datetime.fromisoformat(e["date"].replace("Z", "+00:00")),
                    "state": e["status"]["type"]["state"],
                    "home": ABBR.get(teams["home"]["abbreviation"], teams["home"]["abbreviation"]),
                    "away": ABBR.get(teams["away"]["abbreviation"], teams["away"]["abbreviation"])})
    return out


def cmd_update():
    """Append finished 2026-27 regular-season games to box_2026-27.csv (resumes)."""
    box_path, games_path = os.path.join(DATA, f"box_{SEASON}.csv"), os.path.join(DATA, f"games_{SEASON}.csv")
    done = {r["game_id"] for r in csv.DictReader(open(games_path))} if os.path.exists(games_path) else set()
    new = not os.path.exists(box_path)
    day, today = dt.date.fromisoformat(SEASON_START), dt.datetime.now(ET).date()
    with open(box_path, "a", newline="") as fb, open(games_path, "a", newline="") as fg:
        wb, wg = csv.DictWriter(fb, fe.BOX_COLS), csv.DictWriter(fg, ["season", "game_id", "date", "home", "away"])
        if new:
            wb.writeheader(); wg.writeheader()
        n = 0
        while day < today:
            for g in games_on(day, (2,)):
                if g["game_id"] in done or g["state"] != "post":
                    continue
                rows, game = fe.box_rows(SEASON, g["game_id"], day.isoformat(), fe.get(
                    f"https://site.api.espn.com/apis/site/v2/sports/basketball/nba/summary?event={g['game_id']}"))
                if game and any(r["played"] for r in rows):
                    wb.writerows(rows); wg.writerow(game); n += 1
            day += dt.timedelta(days=1)
    print(f"update: {n} new games")


# ---------------------------------------------------------------- model
def load_model():
    C = pd.read_csv(os.path.join(DATA, "candidates.csv"), dtype={"game_id": str, "player_id": str})
    C[tune.PLUS] = C[tune.PLUS].fillna(0); C["gainer"] = (C["truth"] >= SET["gain"]).astype(int)
    cfg = json.load(open(os.path.join(DATA, "results_tuned_gain1.json")))["chosen"]["Train 2024-25, test 2025-26"]["simple"]
    kind, F, sc, lr = tune.fit(cfg, C)
    w = lr.coef_[0].copy()
    w[F.index("last1_vs_base")] *= SET["last_game_x"]; w[F.index("cd_last5")] *= SET["bench_x"]
    f = lambda df: sc.transform(df[F].fillna(0)) @ w + lr.intercept_[0]
    # confidence bands: where the #1 pick's score fell in training games
    C["s"] = f(C)
    tops = C.sort_values("s", ascending=False).groupby("unit").head(1)["s"]
    return f, np.quantile(tops, [0.25, 0.5, 0.75]), C


def confidence(s, q):
    return ["low", "medium-low", "medium-high", "high"][int(np.searchsorted(q, s))]


# ---------------------------------------------------------------- features (same definitions as build_dataset.py)
def player_state(hist, pid, team_games_since):
    """Baseline etc. from his played games (any team), most recent first."""
    h = hist[hist["player_id"] == pid]
    played = h[h["played"] == 1]
    last = played["minutes"].tail(bd.BASE_GAMES).to_numpy()
    if len(last) < bd.BASE_MIN_GAMES:
        return None
    rows5 = h.tail(5)
    return {"baseline": last.mean(), "base_start_rate": played["starter"].tail(bd.BASE_GAMES).mean(),
            "last3": played["minutes"].tail(3).mean(), "last1": played["minutes"].iat[-1], "std10": last.std(),
            "cd_last5": int(((rows5["dnp"] == 1) & rows5["dnp_reason"].fillna("").str.contains("COACH")).sum()
                            + ((rows5["dnp"] == 0) & (rows5["played"] == 0)).sum()),
            "last_played": played["date"].iat[-1], "out_streak": team_games_since(played["date"].iat[-1])}


def build_unit(game, team, opp, hist, statuses, past):
    roster = fe.get(f"https://site.api.espn.com/apis/site/v2/sports/basketball/nba/teams/{TEAM_IDS[team]}/roster")["athletes"]
    tg = hist[hist["team"] == team].drop_duplicates("game_id")["date"]
    since = lambda d: int((tg > d).sum()) + 1          # team games missed so far, counting this one
    rows, outs = [], []
    for a in roster:
        stt = statuses.get(norm_name(a["displayName"]))
        ps = player_state(hist, a["id"], since)
        if ps is None:
            continue
        grp = bd.GROUP.get((a.get("position") or {}).get("abbreviation", ""), "")
        r = {"player_id": a["id"], "player": a["displayName"], "group": grp, "status": stt or "healthy", **ps}
        if stt in ("out", "doubt"):
            if ps["baseline"] >= bd.ROTATION_MIN and ps["out_streak"] <= bd.MAX_OUT_STREAK:
                outs.append(r)
        else:
            rows.append(r)
    if not outs or len(rows) < 3:
        return None, outs
    hc = pd.DataFrame(rows); top = max(outs, key=lambda o: o["baseline"])
    hc["base_rank"] = hc["baseline"].rank(ascending=False, method="first")
    hc["is_starter"] = (hc["base_start_rate"] >= 0.5).astype(int)
    hc["bench_rank"] = hc[hc["is_starter"] == 0]["baseline"].rank(ascending=False, method="first").reindex(hc.index).fillna(0)
    hc["overlap_top"] = [bd.overlap(g, top["group"]) for g in hc["group"]]
    hc["vacated_same_pos"] = [sum(bd.overlap(g, o["group"]) * o["baseline"] for o in outs) for g in hc["group"]]
    hc["vacated_total"] = sum(o["baseline"] for o in outs); hc["n_out"] = len(outs)
    hc["starter_out_same_pos"] = [int(any(bd.overlap(g, o["group"]) >= 1 and o["base_start_rate"] >= 0.5 for o in outs)) for g in hc["group"]]
    hc["trend"] = hc["last3"] - hc["baseline"]; hc["n_healthy"] = len(hc); hc["out_streak"] = top["out_streak"]
    hc["last1_vs_base"] = hc["last1"] - hc["baseline"]
    prev = tg[tg < game["tip"].astimezone(ET).date().isoformat()]
    hc["b2b"] = int(len(prev) > 0 and (game["tip"].astimezone(ET).date() - dt.date.fromisoformat(prev.iat[-1])).days == 1)
    hc["home"] = int(game["home"] == team)
    hs, ha = [], []
    for pid in hc["player_id"]:
        p = past[past["player_id"] == pid]
        sim = p[p["top_group"] == top["group"]]["truth"]
        hs.append(sim.sum() / (len(sim) + bd.SHRINK_K)); ha.append(p["truth"].sum() / (len(p) + bd.SHRINK_K))
    hc["hist_similar"], hc["hist_any"] = hs, ha
    return hc, outs


def cmd_predict():
    f, q, C = load_model()
    U = pd.read_csv(os.path.join(DATA, "units.csv"), dtype={"game_id": str})
    past = C.merge(U[["unit", "top_out_group"]], on="unit").rename(columns={"top_out_group": "top_group"})[["player_id", "truth", "top_group"]]
    scored = os.path.join(LIVE, "scored_candidates.csv")
    if os.path.exists(scored):
        past = pd.concat([past, pd.read_csv(scored, dtype={"player_id": str})[["player_id", "truth", "top_group"]]])
    sys.path.insert(0, os.path.join(HERE, "..", "pipeline"))
    import email_report as er
    board = json.load(open(os.environ.get("LIVE_BOARD") or os.path.join(HERE, "..", "data.json")))   # LIVE_BOARD: test copy
    hist = box_history()
    now = dt.datetime.now(dt.timezone.utc)
    today = now.astimezone(ET).date()
    types = (2,) if SET["regular_season_only"] else (1, 2)
    n = 0
    for g in games_on(today, types):
        if g["state"] != "pre" or (g["tip"] - now).total_seconds() > SET["predict_within_minutes"] * 60:
            continue
        path = os.path.join(PRED, f"{today}_{g['game_id']}.csv")
        frames = []
        for team, opp in ((g["away"], g["home"]), (g["home"], g["away"])):
            statuses = {norm_name(i["player"]): i["st"] for i in er.injuries_for(board, team, today.isoformat())}
            hc, outs = build_unit(g, team, opp, hist, statuses, past)
            if hc is None:
                continue
            hc["score"] = f(hc)
            hc["nextman"] = hc["overlap_top"] * 1000 + (1 - hc["is_starter"]) * 100 + hc["baseline"]
            hc = hc.sort_values(["score", "baseline"], ascending=False)
            hc["rank"] = range(1, len(hc) + 1)
            hc["confidence"] = confidence(hc["score"].iat[0], q)
            hc["top_group"] = max(outs, key=lambda o: o["baseline"])["group"]
            hc["out_players"] = "; ".join(f"{o['player']} ({o['baseline']:.0f})" for o in outs)
            hc = hc.assign(date=today.isoformat(), game_id=g["game_id"], tip=g["tip"].isoformat(), team=team, opponent=opp,
                           predicted_at=now.isoformat(timespec="seconds"))
            frames.append(hc)
        if frames:
            cols = ["date", "game_id", "tip", "team", "opponent", "out_players", "rank", "player_id", "player", "status",
                    "baseline", "score", "confidence", "nextman", "top_group", "predicted_at"]
            pd.concat(frames)[cols].round(3).to_csv(path, index=False); n += 1
    print(f"predict: {n} games ranked")
    write_picks_all()


PICK_COLS = ["date", "tip", "team", "opponent", "out_players", "rank", "player", "status", "baseline", "confidence", "predicted_at"]
SCORE_COLS = ["date", "game_id", "team", "opponent", "out_players", "confidence", "pick", "pick_change", "hit", "top3_hits",
              "rank_corr", "nextman_hit", "random_hit"]


def write_picks_all():
    """All picks in one file, newest first (the Google Sheet reads this)."""
    files = [os.path.join(PRED, f) for f in sorted(os.listdir(PRED)) if f.endswith(".csv")]
    P = pd.concat([pd.read_csv(f, dtype={"game_id": str}) for f in files]) if files else pd.DataFrame(columns=PICK_COLS)
    if len(P):
        P = P.sort_values(["date", "tip", "team", "rank"], ascending=[False, False, True, True])
    P[PICK_COLS].round(1).to_csv(os.path.join(LIVE, "picks_all.csv"), index=False)


# ---------------------------------------------------------------- scoring
def cmd_score():
    sc_path, cand_path = os.path.join(LIVE, "scorecard.csv"), os.path.join(LIVE, "scored_candidates.csv")
    done = set(pd.read_csv(sc_path, dtype={"game_id": str})["game_id"]) if os.path.exists(sc_path) else set()
    units, cands = [], []
    for name in sorted(os.listdir(PRED)):
        if not name.endswith(".csv"):
            continue
        P = pd.read_csv(os.path.join(PRED, name), dtype={"game_id": str, "player_id": str})
        gid = P["game_id"].iat[0]
        if gid in done:
            continue
        s = fe.get(f"https://site.api.espn.com/apis/site/v2/sports/basketball/nba/summary?event={gid}")
        if s["header"]["competitions"][0]["status"]["type"]["state"] != "post":
            continue
        rows, _ = fe.box_rows(SEASON, gid, P["date"].iat[0], s)
        mins = {r["player_id"]: (r["minutes"], r["played"], r["dnp"]) for r in rows}
        for team, u in P.groupby("team"):
            u = u[u["player_id"].isin(mins)].copy()               # not in the box score = scratched late; not scored
            if len(u) < 3:
                continue
            u["minutes"] = u["player_id"].map(lambda p: mins[p][0])
            u["truth"] = u["minutes"] - u["baseline"]; u["gainer"] = (u["truth"] >= SET["gain"]).astype(int)
            u["unit"] = f"{gid}-{team}"
            m = bt.unit_metrics(u.assign(s=-u["rank"]), "s").iloc[0]
            nm = bt.unit_metrics(u, "nextman").iloc[0]
            units.append({"date": u["date"].iat[0], "game_id": gid, "team": team, "opponent": u["opponent"].iat[0],
                          "out_players": u["out_players"].iat[0], "confidence": u["confidence"].iat[0],
                          "pick": m["pick"], "pick_change": round(m["pick_truth"], 1), "hit": int(m["top1"]),
                          "top3_hits": round(m["p3"], 3), "rank_corr": m["rho"], "nextman_hit": int(nm["top1"]),
                          "random_hit": round(u["gainer"].mean(), 3)})
            cands.append(u[["date", "game_id", "team", "player_id", "player", "rank", "baseline", "minutes", "truth", "gainer", "top_group"]])
    if units:
        pd.DataFrame(units)[SCORE_COLS].to_csv(sc_path, mode="a", header=not os.path.exists(sc_path), index=False)
        pd.concat(cands).to_csv(cand_path, mode="a", header=not os.path.exists(cand_path), index=False)
    print(f"score: {len(units)} team-games scored")
    write_scorecard()


def write_scorecard():
    sc_path = os.path.join(LIVE, "scorecard.csv")
    if not os.path.exists(sc_path):
        pd.DataFrame(columns=SCORE_COLS).to_csv(sc_path, index=False)      # header only, so the Google Sheet has a file to read
    lines = ["# Live test, 2026-27: who gains minutes when a teammate is out", "",
             f"Gain = {SET['gain']:g}+ minutes above the player's last-10-game average. Weights: last game x{SET['last_game_x']:g}, "
             f"coach's-decision benchings x{SET['bench_x']:g}. Picks lock at tip-off.", ""]
    S = pd.read_csv(sc_path)
    if not len(S):
        lines.append("No games scored yet.")
    else:
        lines += [f"**{len(S)} team-games scored** ({S['date'].min()} to {S['date'].max()})", "",
                  "| | #1 pick gained minutes |", "|---|---|",
                  f"| Model | {100 * S['hit'].mean():.1f}% |", f"| Next man up (same position) | {100 * S['nextman_hit'].mean():.1f}% |",
                  f"| Random teammate | {100 * S['random_hit'].mean():.1f}% |", "",
                  f"Model top 3: {100 * S['top3_hits'].mean():.1f}% gained. Rank correlation: {S['rank_corr'].mean():.2f}.", "",
                  "| Model's confidence | Games | #1 pick gained |", "|---|---|---|"]
        for c in ["high", "medium-high", "medium-low", "low"]:
            g = S[S["confidence"] == c]
            if len(g):
                lines.append(f"| {c} | {len(g)} | {100 * g['hit'].mean():.1f}% |")
        lines += ["", "## Latest", "", "| Date | Team | Out | #1 pick (change) | Hit | Confidence |", "|---|---|---|---|---|---|"]
        for r in S.sort_values("date", ascending=False).head(25).itertuples():
            lines.append(f"| {r.date} | {r.team} | {r.out_players} | {r.pick} ({r.pick_change:+.0f}) | {'yes' if r.hit else 'no'} | {r.confidence} |")
    open(os.path.join(LIVE, "SCORECARD.md"), "w").write("\n".join(lines) + "\n")


if __name__ == "__main__":
    {"update": cmd_update, "predict": cmd_predict, "score": cmd_score}[sys.argv[1]]()
