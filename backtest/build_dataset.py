#!/usr/bin/env python3
"""Turn the ESPN box scores into the backtest dataset.

Rules (from the task):
- Regular season 2024-25 and 2025-26 only.
- Players who played for more than one team across the two seasons are dropped, as candidates and as "out" players.
- "Out" = inactive, or DNP for injury / illness / rest. Coach's-decision DNPs are not out.
  ESPN leaves most inactive players out of the box score, so a player who is missing from a game while clearly on
  the team (he appears for them before and after it, or in the other season / on the 2026-27 depth chart) counts
  as inactive. ESPN does not say why for those.
- Baseline = average minutes over the player's previous 10 games played, before that game only (it can reach back
  into the previous season; same team, since multi-team players are dropped). At least 5 earlier games needed.
- Unit = a team-game where at least one rotation player (baseline 15+) is out.
- Candidates = healthy teammates (played, or DNP coach's decision) with a baseline. Truth = minutes - baseline;
  gainer = +2 or more.

Writes backtest/data/units.csv (one row per unit) and backtest/data/candidates.csv (one row per candidate, with
features). Features use only information from before the game.
"""
import json, os, re
import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
SEASONS = ["2024-25", "2025-26"]
ROTATION_MIN = 15.0
BASE_GAMES, BASE_MIN_GAMES = 10, 5
GAIN = 2.0
SHRINK_K = 5.0                       # history shrinkage: k phantom games at 0 change

NOT_OUT_REASONS = re.compile(r"COACH'?S DECISION|PERSONAL|SUSPEN|G LEAGUE|G-LEAGUE|TWO-WAY|NOT WITH TEAM|"
                             r"TRADE|LEAGUE SUSPENSION|BEREAVEMENT|FAMILY|BIRTH", re.I)
GROUP = {"PG": "G", "SG": "G", "G": "G", "SF": "F", "F": "F", "GF": "F", "G-F": "F", "PF": "F", "FC": "C", "F-C": "C", "C": "C"}
ORDER = {"G": 0, "F": 1, "C": 2}


def overlap(a, b):
    """1 = same position group, 0.5 = next to it (guard-forward, forward-center), 0 = guard vs center."""
    if not a or not b:
        return 0.25
    d = abs(ORDER[a] - ORDER[b])
    return 1.0 if d == 0 else 0.5 if d == 1 else 0.0


def classify_dnp(reason):
    if not reason or NOT_OUT_REASONS.search(reason):
        return "cd" if re.search(r"COACH", reason or "", re.I) or not reason else "other"
    return "out"                                     # injury, illness, rest, surgery, reconditioning...


def load():
    box = pd.concat([pd.read_csv(os.path.join(DATA, f"box_{s}.csv"), dtype={"game_id": str, "player_id": str}) for s in SEASONS])
    games = pd.concat([pd.read_csv(os.path.join(DATA, f"games_{s}.csv"), dtype={"game_id": str}) for s in SEASONS])
    return box.drop_duplicates(["game_id", "player_id"]), games.drop_duplicates("game_id")


def depth_2027():
    """Players on each team's 2026-27 ESPN depth chart (from the board's data.json), to tell a late-season shutdown
    in 2025-26 from leaving the team."""
    try:
        d = json.load(open(os.path.join(HERE, "..", "data.json")))
    except Exception:
        return {}
    out = {}
    for team, chart in (d.get("depth") or {}).items():
        for col in chart.values():
            for n in col.replace("/", ",").split(","):
                if n.strip():
                    out[n.strip().lower()] = team
    return out


ESPN_ABBR = {"GS": "GSW", "NO": "NOP", "NY": "NYK", "SA": "SAS", "UTAH": "UTA", "WSH": "WAS"}


def build():
    box, games = load()
    box["team"] = box["team"].replace(ESPN_ABBR); box["opponent"] = box["opponent"].replace(ESPN_ABBR)
    games["home"] = games["home"].replace(ESPN_ABBR); games["away"] = games["away"].replace(ESPN_ABBR)
    stats = {"games": len(games), "box_rows": len(box), "players_all": box["player_id"].nunique()}

    # 1. drop players seen on more than one team
    teams_per = box.groupby("player_id")["team"].nunique()
    multi = set(teams_per[teams_per > 1].index)
    stats["players_dropped_multi_team"] = len(multi)
    box = box[~box["player_id"].isin(multi)].copy()
    stats["players_kept"] = box["player_id"].nunique()

    # player info
    pos = box.groupby("player_id")["position"].agg(lambda s: s.mode().iat[0] if len(s.mode()) else "")
    name = box.groupby("player_id")["player"].last()
    team_of = box.groupby("player_id")["team"].first()
    dc27 = depth_2027()

    # 2. every team-game, in date order
    tg = pd.concat([games.rename(columns={"home": "team", "away": "opponent"}).assign(home=1),
                    games.rename(columns={"away": "team", "home": "opponent"}).assign(home=0)])
    tg = tg.sort_values(["date", "game_id"]).reset_index(drop=True)

    # 3. status of every kept player in every game of his team
    seen = box.groupby(["player_id", "season"])["date"].agg(["min", "max"])
    by_key = box.set_index(["game_id", "player_id"])
    rows = []
    for pid, team in team_of.items():
        g = tg[tg["team"] == team]
        sp = {s: seen.loc[(pid, s)] if (pid, s) in seen.index else None for s in SEASONS}
        on_2027 = dc27.get(str(name[pid]).lower()) == team
        for r in g.itertuples(index=False):
            k = (r.game_id, pid)
            if k in by_key.index:
                b = by_key.loc[k]
                if b["played"]:
                    st = "played"
                elif b["dnp"]:
                    st = classify_dnp(b["dnp_reason"])
                else:
                    st = "cd"                        # listed, 0 minutes, no DNP flag
                rows.append((r.season, r.game_id, r.date, team, r.opponent, pid, st, float(b["minutes"]), int(b["starter"])))
                continue
            span = sp[r.season]
            other = sp["2025-26" if r.season == "2024-25" else "2024-25"]
            inside = span is not None and span["min"] <= r.date <= span["max"]
            after_ok = span is not None and r.date > span["max"] and (r.season == "2024-25" and other is not None or
                                                                      r.season == "2025-26" and on_2027)
            before_ok = span is not None and r.date < span["min"] and r.season == "2025-26" and other is not None
            whole_season = span is None and ((r.season == "2024-25" and other is not None) or (r.season == "2025-26" and other is not None and on_2027))
            if inside or after_ok or before_ok or whole_season:
                rows.append((r.season, r.game_id, r.date, team, r.opponent, pid, "inactive", 0.0, 0))
    st = pd.DataFrame(rows, columns=["season", "game_id", "date", "team", "opponent", "player_id", "status", "minutes", "starter"])
    st = st.sort_values(["player_id", "date"]).reset_index(drop=True)
    stats["status_counts"] = st["status"].value_counts().to_dict()

    # 4. baseline from the previous 10 games played (strictly before)
    played = st["status"].eq("played")
    st["baseline"], st["base_n"], st["base_start_rate"], st["last3"] = np.nan, 0, np.nan, np.nan
    for pid, idx in st.groupby("player_id").groups.items():
        sub = st.loc[idx]
        mins, starts, pl = sub["minutes"].to_numpy(), sub["starter"].to_numpy(), played.loc[idx].to_numpy()
        hist_m, hist_s = [], []
        base, n, sr, l3 = [], [], [], []
        for m, s, p in zip(mins, starts, pl):
            last = hist_m[-BASE_GAMES:]
            base.append(np.mean(last) if len(last) >= BASE_MIN_GAMES else np.nan)
            n.append(len(last)); sr.append(np.mean(hist_s[-BASE_GAMES:]) if last else np.nan)
            l3.append(np.mean(hist_m[-3:]) if len(hist_m) >= 3 else np.nan)
            if p:
                hist_m.append(m); hist_s.append(s)
        st.loc[idx, "baseline"], st.loc[idx, "base_n"], st.loc[idx, "base_start_rate"], st.loc[idx, "last3"] = base, n, sr, l3
    st["position"] = st["player_id"].map(pos).fillna("")
    st["group"] = st["position"].map(GROUP).fillna("")
    st["player"] = st["player_id"].map(name)

    # 5. units and candidates
    st["is_out"] = st["status"].isin(["out", "inactive"])
    st["healthy"] = st["status"].isin(["played", "cd"])
    st = st.sort_values(["date", "game_id"]).reset_index(drop=True)
    units, cands = [], []
    hist = {}                                         # player_id -> list of (out group, change) from earlier units
    for (gid, team), g in st.groupby(["game_id", "team"], sort=False):
        outs = g[g["is_out"] & (g["baseline"] >= ROTATION_MIN)]
        if outs.empty:
            continue
        hc = g[g["healthy"] & g["baseline"].notna()].copy()
        if len(hc) < 3:
            continue
        top = outs.sort_values("baseline", ascending=False).iloc[0]
        vac = outs["baseline"].sum()
        hc["truth"] = hc["minutes"] - hc["baseline"]
        hc["gainer"] = (hc["truth"] >= GAIN).astype(int)
        hc["base_rank"] = hc["baseline"].rank(ascending=False, method="first")
        hc["is_starter"] = (hc["base_start_rate"] >= 0.5).astype(int)
        # bench rank: order among non-starters by baseline (1 = first off the bench); starters get 0
        bench = hc[hc["is_starter"] == 0]["baseline"].rank(ascending=False, method="first")
        hc["bench_rank"] = bench.reindex(hc.index).fillna(0)
        hc["overlap_top"] = [overlap(gr, top["group"]) for gr in hc["group"]]
        hc["vacated_same_pos"] = [sum(overlap(gr, o) * b for o, b in zip(outs["group"], outs["baseline"])) for gr in hc["group"]]
        hc["vacated_total"] = vac
        hc["n_out"] = len(outs)
        hc["starter_out_same_pos"] = [int(any(overlap(gr, o) >= 1 and s >= 0.5 for o, s in zip(outs["group"], outs["base_start_rate"])))
                                      for gr in hc["group"]]
        hc["trend"] = hc["last3"] - hc["baseline"]
        hc["n_healthy"] = len(hc)
        # how he responded before when a similar (same-group) rotation player was out, shrunk toward 0
        hs, hn, ha, han = [], [], [], []
        for pid, gr in zip(hc["player_id"], hc["group"]):
            past = hist.get(pid, [])
            sim = [c for og, c in past if og == top["group"]]
            hs.append(sum(sim) / (len(sim) + SHRINK_K)); hn.append(len(sim))
            ha.append(sum(c for _, c in past) / (len(past) + SHRINK_K)); han.append(len(past))
        hc["hist_similar"], hc["hist_similar_n"], hc["hist_any"], hc["hist_any_n"] = hs, hn, ha, han
        units.append({"season": g["season"].iat[0], "game_id": gid, "date": g["date"].iat[0], "team": team,
                      "opponent": g["opponent"].iat[0], "out_players": "; ".join(f"{p} ({b:.0f})" for p, b in zip(outs["player"], outs["baseline"])),
                      "top_out": top["player"], "top_out_group": top["group"], "n_out": len(outs), "vacated": round(vac, 1),
                      "n_candidates": len(hc), "n_gainers": int(hc["gainer"].sum())})
        cands.append(hc.assign(unit=f"{gid}-{team}"))
        for pid, c in zip(hc["player_id"], hc["truth"]):     # remember for later games (after this game only)
            hist.setdefault(pid, []).append((top["group"], c))
    U = pd.DataFrame(units); C = pd.concat(cands, ignore_index=True)
    U["unit"] = U["game_id"] + "-" + U["team"]
    keep = ["unit", "season", "game_id", "date", "team", "opponent", "player_id", "player", "position", "group", "status", "minutes",
            "baseline", "truth", "gainer", "base_rank", "is_starter", "bench_rank", "overlap_top", "vacated_same_pos",
            "vacated_total", "n_out", "starter_out_same_pos", "trend", "n_healthy", "hist_similar", "hist_similar_n",
            "hist_any", "hist_any_n", "base_start_rate"]
    C = C[keep]
    U.to_csv(os.path.join(DATA, "units.csv"), index=False); C.to_csv(os.path.join(DATA, "candidates.csv"), index=False)
    st.drop(columns=["is_out", "healthy"]).to_csv(os.path.join(DATA, "player_games.csv"), index=False)
    stats.update({"units": len(U), "units_by_season": U["season"].value_counts().to_dict(), "candidates": len(C),
                  "gainer_rate": round(C["gainer"].mean(), 3)})
    json.dump(stats, open(os.path.join(DATA, "dataset_stats.json"), "w"), indent=1, default=str)
    print(json.dumps(stats, indent=1, default=str))


if __name__ == "__main__":
    build()
