#!/usr/bin/env python3
"""Email (and post to Slack) the availability report for games that tip off soon.

Run right after update_data.py. Picks every game starting within --window minutes that has not been sent yet
(email_log.json remembers, separately for email and Slack), builds the same report the page shows, and sends it.

Email needs (GitHub secrets): SMTP_USER, SMTP_PASSWORD, EMAIL_TO. Optional: SMTP_HOST (smtp.gmail.com), SMTP_PORT (465).
Slack needs: SLACK_WEBHOOK_URL (an incoming webhook; it posts wherever the webhook was pointed, e.g. your own DMs).
Without them, that channel is skipped. --out writes the email to files instead of sending.
--test-slack posts the next game's report to Slack right away, marked TEST, without touching the log.

Usage:  python pipeline/email_report.py --data data.json --window 25
"""
import argparse, datetime as dt, html, json, os, re, smtplib, sys
import urllib.request
from email.message import EmailMessage

sys.path.insert(0, os.path.dirname(__file__))
from update_data import ET, TEAMS, all_games, norm_name  # noqa: E402

SITE = "https://lukemaass-hub.github.io/nba-board/"
POS = ["PG", "SG", "SF", "PF", "C"]
# "avail" = Available on the NBA's official injury report (via Presser Wire, Oct 26 2026)
RANK = {"out": 0, "doubt": 1, "q": 2, "prob": 3, "avail": 4}
LABEL = {"out": "Out", "doubt": "Doubtful", "q": "Questionable", "prob": "Probable", "avail": "Available"}
DOT = {"out": "🔴", "doubt": "🟠", "q": "🟡", "prob": "🟢", "avail": "✅"}
SRC_URL = {"CBS": "https://www.cbssports.com/nba/injuries/", "Covers": "https://www.covers.com/sport/basketball/nba/injuries",
           "ESPN": "https://www.espn.com/nba/injuries", "RotoWire": "https://www.rotowire.com/basketball/nba-lineups.php",
           "NBA report": "https://presserwire.com/nba/injury-report.html"}


def name(code):
    return TEAMS.get(code, [code])[0]


def fmt_time(t):
    h, m = map(int, t.split(":"))
    return f"{(h + 11) % 12 + 1}:{m:02d} {'PM' if h >= 12 else 'AM'}"


def injuries_for(data, team, date):
    """Same merge as the page: one entry per player, every source listed. The worst status wins, except that a
    beat writer's status (from the news feed) overrides the injury sites; the newest beat-writer report counts."""
    groups = {}
    for r in data.get("injuries", []):
        if r["team"] != team or (r.get("through") and date > r["through"]) or (r.get("from") and date < r["from"]):
            continue
        if r.get("st"):
            st, label = r["st"], LABEL[r["st"]]
        elif r.get("kind") == "O":
            st, label = ("q", "Out earlier, return date passed") if r.get("until") and date >= r["until"] else ("out", "Out")
        else:
            st, label = "q", "Game-time decision"
        g = groups.setdefault(norm_name(r["player"]), {"player": r["player"], "sts": set(), "lines": [], "beat": None})
        g["sts"].add(st)
        g["lines"].append({"src": r["src"], "st": st, "label": label, "injury": r.get("injury", ""),
                           "url": r.get("url") or SRC_URL.get(r["src"], ""), "beat": bool(r.get("override"))})
        if r.get("override") and (not g["beat"] or r.get("at", "") > g["beat"]["at"]):
            g["beat"] = {"st": st, "at": r.get("at", ""), "src": r["src"]}
    out = []
    for g in groups.values():
        best = g["beat"]["st"] if g["beat"] else min(g["sts"], key=RANK.get)
        srcs, seen = [], set()
        for l in g["lines"]:
            if l["src"] not in seen:
                seen.add(l["src"])
                srcs.append(l)
        link = next((l["url"] for l in g["lines"] if l["st"] == best and l["url"]), "") or next((l["url"] for l in srcs if l["url"]), "")
        out.append({"player": g["player"], "st": best, "injury": next((l["injury"] for l in g["lines"] if l["injury"]), ""),
                    "srcs": srcs, "link": link, "differ": len(g["sts"]) > 1,
                    # "per <source>" only when the override actually decided it (sources disagree)
                    "beat": g["beat"]["src"] if g["beat"] and len(g["sts"]) > 1 else ""})
    return sorted(out, key=lambda i: (RANK[i["st"]], i["player"]))


def starters_for(data, team, date, inj):
    """RotoWire lineup for the day if there is one, else depth-chart starters with injured ones replaced."""
    l = (data.get("lineups") or {}).get(team)
    if l and l.get("date") == date and l.get("starters"):
        return ("Confirmed starters (RotoWire)" if l.get("confirmed") else "Expected starters (RotoWire, not confirmed)",
                [(s["pos"], s["name"], "") for s in l["starters"]])
    chart = (data.get("depth") or {}).get(team)
    if not chart:
        return "Projected starters", []
    status = {norm_name(i["player"]): i["st"] for i in inj}
    rows = []
    for p in POS:
        parts = (chart.get(p) or "").split("/")
        col = [n.strip() for part in parts for n in part.split(",") if n.strip()]
        if not col:
            continue
        st = col[0]
        if status.get(norm_name(st)) in ("out", "doubt"):
            sub = next((n for n in col[1:] if status.get(norm_name(n)) not in ("out", "doubt")), None)
            if sub:
                rows.append((p, sub, f"in for {st}"))
                continue
        rows.append((p, st, ""))
    return "Projected starters (depth chart)", rows


ESPN_LOGO = {"GSW": "gs", "NOP": "no", "NYK": "ny", "SAS": "sa", "UTA": "utah", "WAS": "wsh"}
TAG = {"out": ("OUT", "#c0392b"), "doubt": ("DOUBT", "#d35400"), "q": ("GTD", "#b7950b"), "prob": ("PROB", "#1e8449")}


def logo(code, size):
    src = f"https://a.espncdn.com/i/teamlogos/nba/500/{ESPN_LOGO.get(code, code.lower())}.png"
    return (f'<img src="{src}" width="{size}" height="{size}" alt="{code}" '
            f'style="vertical-align:middle;border:0;width:{size}px;height:{size}px">')


def bench_for(data, team, inj, starters):
    """Depth-chart players not starting, minus anyone out or doubtful: (bench, deep bench)."""
    chart = (data.get("depth") or {}).get(team) or {}
    status = {norm_name(i["player"]): i["st"] for i in inj}
    skip = {norm_name(n) for _, n, _ in starters}
    bench, deep, seen = [], [], set()
    for tier in (0, 1, 2):                     # starter / rotation / limited, best players first
        for p in POS:
            parts = (chart.get(p) or "").split("/")
            names = [n.strip() for n in (parts[tier] if tier < len(parts) else "").split(",") if n.strip()]
            for n in names:
                k = norm_name(n)
                if k in skip or k in seen or status.get(k) in ("out", "doubt"):
                    continue
                seen.add(k)
                (deep if tier == 2 else bench).append((p, n, status.get(k)))
    return bench, deep


def matchup_alerts_for(data, team, opp, inj, starters):
    """Players on this team today (depth chart or lineup, not out/doubtful) whose minutes vs this opponent are
    well above or below their usual, from the minutes-vs-teams workbook."""
    names = {norm_name(n): n for _, n, _ in starters}
    for col in ((data.get("depth") or {}).get(team) or {}).values():
        for n in col.replace("/", ",").split(","):
            if n.strip():
                names.setdefault(norm_name(n), n.strip())
    status = {norm_name(i["player"]): i["st"] for i in inj}
    out = []
    for a in data.get("matchup_alerts", []):
        k = norm_name(a["player"])
        if a["opp"] == opp and k in names and status.get(k) not in ("out", "doubt"):
            out.append((names[k], a["dir"]))
    return sorted(out, key=lambda x: (x[1] != "up", x[0]))


NEWS_HOURS = 36
CUR_MIN_GAMES = 1          # this season's average as soon as he has played (Oct 26 2026, user: most up-to-date; was 15)
CHANGE_MIN = 5.0           # minutes up/down vs last season that counts as a big change
CHANGE_CUR_GAMES = 5       # games this season needed before we call a change
CHANGE_BASE_GAMES = 10     # games in the comparison season needed


def _season_index(data):
    sm = data.get("season_minutes") or {}
    if "_idx" not in sm:
        sm["_idx"] = {k: {norm_name(n): v for n, v in (sm.get(k) or {}).items()} for k in ("current", "last")}
    return sm, sm["_idx"]


def avg_minutes(data, player):
    """(minutes per game, season label) from this season once he has CUR_MIN_GAMES games, else last season.
    None if we have nothing (seasons before last are never used)."""
    sm, idx = _season_index(data)
    k = norm_name(player)
    for key, need, label in (("current", CUR_MIN_GAMES, sm.get("season")), ("last", 1, sm.get("last_season"))):
        v = idx[key].get(k)
        if v and v[0] >= need:
            return v[1], label
    return None


def minutes_change(data, player):
    """Big change this season vs last season only: (difference, this season mpg, last season mpg, label) or None."""
    sm, idx = _season_index(data)
    k = norm_name(player)
    cur = idx["current"].get(k)
    if not cur or cur[0] < CHANGE_CUR_GAMES:
        return None
    for key in ("last",):
        base = idx[key].get(k)
        if base and base[0] >= CHANGE_BASE_GAMES:
            diff = cur[1] - base[1]
            return (round(diff, 1), cur[1], base[1], sm.get(f"{key}_season")) if abs(diff) >= CHANGE_MIN else None
    return None


def mins_tag(data, player, unit=False):
    """" (34.1)", or " (34.1 MPG)" with unit=True (Slack: makes clear it is minutes per game). Last season's number
    (he hasn't played this season yet) says so: " (7.9 MPG, 2025-26)"."""
    m = avg_minutes(data, player)
    if not m:
        return ""
    old = m[1] and m[1] != (data.get("season_minutes") or {}).get("season")
    return f" ({m[0]:.1f}{' MPG' if unit else ''}{f', {m[1]}' if old else ''})"


def change_html(data, player):
    c = minutes_change(data, player)
    if not c:
        return ""
    up = c[0] > 0
    return (f' <span style="font-size:11px;font-weight:bold;color:#fff;background:{"#1e8449" if up else "#c0392b"};'
            f'border-radius:3px;padding:1px 5px">{"📈 +" if up else "📉 "}{round(c[0])} min vs {c[3]}</span>')


def change_text(data, player):
    c = minutes_change(data, player)
    return f" [{'+' if c[0] > 0 else ''}{round(c[0])} min vs {c[3]}]" if c else ""


# Oct 26 2026: Dolly disconnected (user's choice), so expected minutes are left out of every report for now.
# Set to True to bring them back once a Dolly source is reconnected.
EXPECTED_ENABLED = False
EXPECTED_DIFF = 5.0         # Dolly expected minutes this far above/below the average gets a tag (the user's rule)
EXPECTED_MAX_AGE_H = 36     # ignore Dolly numbers older than this
EXPECTED_ROLE_MIN = 15.0    # only rotation players: Dolly expects 15+ minutes, or he averaged 15+ (cuts deep-bench noise)
EXPECTED_FLOOR = 5.0        # and never players Dolly expects for under 5 minutes


def expected_minutes_for(data, team, date, now=None, skip=()):
    """Dolly's prematch expected minutes (expected_minutes.json, saved by the prop-compare extension from the Dolly
    Rosters screen) that are EXPECTED_DIFF+ above or below the player's average (avg_minutes: last season until 15
    games this season), for rotation players only (EXPECTED_ROLE_MIN, EXPECTED_FLOOR).
    -> [(player, expected, average, diff, season label)], biggest first."""
    out = []
    for name, exp, avg in expected_raw(data, team, date, now, skip):
        if avg and abs(exp - avg[0]) >= EXPECTED_DIFF and exp >= EXPECTED_FLOOR and max(exp, avg[0]) >= EXPECTED_ROLE_MIN:
            out.append((name, exp, avg[0], round(exp - avg[0], 1), avg[1]))
    return sorted(out, key=lambda x: -abs(x[3]))


def expected_raw(data, team, date, now=None, skip=()):
    """Every fresh Dolly number for this team and date: [(player, expected, avg_minutes result or None)]."""
    if not EXPECTED_ENABLED:
        return []
    em = data.get("expected_minutes") or {}
    now = now or dt.datetime.now(dt.timezone.utc)
    out = []
    for p in em.get("players", []):
        if p.get("team") != team or (p.get("game_date") and p["game_date"] != date) or norm_name(p["name"]) in skip:
            continue
        try:
            if now - dt.datetime.fromisoformat(p["at"]) > dt.timedelta(hours=EXPECTED_MAX_AGE_H):
                continue
            out.append((p["name"], float(p["expected"]), avg_minutes(data, p["name"])))
        except (KeyError, ValueError, TypeError):
            continue
    return out


DEEP_NEW_MIN = 5.0          # a deep-bench player with no average yet shows if Dolly expects at least this


def deep_bench_up(data, team, date, deep, skip=(), now=None):
    """Deep bench is left out of the email, except (the user's rule) any deep-bench player Dolly expects to play MORE
    than his average, by any amount (or DEEP_NEW_MIN+ minutes when he has no average yet).
    -> [(player, expected, diff or None)] in depth-chart order."""
    raw = {norm_name(n): (x, a) for n, x, a in expected_raw(data, team, date, now, skip)}
    out = []
    for _, n, _ in deep:
        r = raw.get(norm_name(n))
        if not r:
            continue
        x, a = r
        if (a and x > a[0]) or (not a and x >= DEEP_NEW_MIN):
            out.append((n, x, round(x - a[0], 1) if a else None))
    return out


def expected_tags(data, team, date, skip=()):
    """{normalized name: (expected, diff)} for the players expected_minutes_for flags, to tag next to their names."""
    return {norm_name(n): (x, d) for n, x, a, d, _ in expected_minutes_for(data, team, date, skip=skip)}


def exp_html(tags, player):
    """Green "Exp 32.8 (+5.1)" when Dolly expects more than his average, red "Exp 15.2 (−5.0)" when less."""
    t = tags.get(norm_name(player))
    if not t:
        return ""
    x, d = t
    return (f' <span style="font-size:12px;font-weight:bold;color:{"#1e8449" if d > 0 else "#c0392b"}" '
            f'title="Expected minutes (Dolly) vs average">Exp {x:.1f} ({"+" if d > 0 else "−"}{abs(d):.1f})</span>')


def exp_text(tags, player):
    t = tags.get(norm_name(player))
    return f" {'📈' if t[1] > 0 else '📉'} Expected {t[0]:.1f} ({'+' if t[1] > 0 else '-'}{abs(t[1]):.1f})" if t else ""


def back_to_back(data, team, date):
    """The user's rule (Oct 26 2026): warn when a team plays the 1st or 2nd game of a back-to-back (games on
    consecutive days, ET). -> [(team, "1st" | "2nd", the other game)]."""
    d = dt.date.fromisoformat(date)
    out = []
    for which, other in (("2nd", d - dt.timedelta(days=1)), ("1st", d + dt.timedelta(days=1))):
        g = next((g for g in all_games(data) if g["date"] == other.isoformat() and team in (g["away"], g["home"])), None)
        if g:
            out.append((team, which, g))
    return out


def b2b_text(team, which, g):
    """'2nd game of a back-to-back: played @ NYK last night' / '1st game of a back-to-back: vs MIA tomorrow 7:30 PM'"""
    where = "@" if g["away"] == team else "vs"
    opp = g["home"] if g["away"] == team else g["away"]
    when = "last night" if which == "2nd" else f"tomorrow {fmt_time(g['time'])} ET"
    return f"{which} game of a back-to-back: {'played ' if which == '2nd' else ''}{where} {opp} {when}"


def b2b_for(data, g):
    return [x for t in (g["away"], g["home"]) for x in back_to_back(data, t, g["date"])]


def restrictions_for(data, teams, date):
    """Minutes-restriction warnings from beat-writer news for these teams on this date."""
    return [w for w in data.get("restrictions", []) if w["team"] in teams and w["from"] <= date <= w["through"]]


# Beat-writer news is shown only for injuries, suspensions and minutes restrictions (user's rule, Oct 20 2026):
# no contracts, team options or starting-lineup notes. RotoWire marks injury items with "(ankle)" after the name.
# Same rule in index.html (NEWS_KEEP / NEWS_SKIP).
NEWS_KEEP = re.compile(r"\((?!\d)[a-z][a-z /-]{1,25}\)|\b(injur\w*|ruled out|out (for|indefinitely|at least|another)|won'?t (play|debut|travel)"
                       r"|will not (play|debut|be ready)|not (play|travel|ready)\w*|(expected|planning|plans|hopeful|fine|cleared) to play|questionable"
                       r"|doubtful|probable|day-to-day|game-time|miss(es|ed|ing)?|sidelined|illness|surgery|torn|tear|sprain\w*|strain\w*"
                       r"|fractur\w*|concussion|sore\w*|rehab\w*|recover\w*|return\w*|injury report|availab\w*|cleared|suspen\w+"
                       r"|restriction\w*|minutes|will play|limited|workload|ramp\w*|load management)\b", re.I)
NEWS_SKIP = re.compile(r"\b(extension|contract|team option|signs|inks|agrees)\b", re.I)


def news_relevant(i):
    t = f"{i.get('headline', '')} {i.get('text', '')}"
    return bool(NEWS_KEEP.search(t)) and not (NEWS_SKIP.search(t) and not re.search(r"suspen", t, re.I))


def pressers_for(data, team, now=None, hours=NEWS_HOURS):
    """Presser Wire press-conference notes about this team from the last 36 hours, injury / minutes related only
    (news_relevant, the same rule as beat-writer news), newest first."""
    now = now or dt.datetime.now(dt.timezone.utc)
    out = []
    for n in (data.get("presserwire") or {}).get("notes", []):
        try:
            fresh = dt.datetime.fromisoformat(n["at"]) >= now - dt.timedelta(hours=hours)
        except (KeyError, ValueError):
            continue
        if n.get("team") == team and fresh and news_relevant({"text": n.get("text", "")}):
            out.append(n)
    return sorted(out, key=lambda n: n["at"], reverse=True)


def news_for(data, team, now=None):
    """Beat-writer news (RotoWire feed) about this team's players from the last 36 hours, newest first:
    injuries, suspensions and minutes restrictions only (news_relevant)."""
    now = now or dt.datetime.now(dt.timezone.utc)
    return [i for i in data.get("news", []) if i.get("team") == team and news_relevant(i)
            and dt.datetime.fromisoformat(i["at"]) >= now - dt.timedelta(hours=NEWS_HOURS)]


def ago(iso, now=None):
    mins = int(((now or dt.datetime.now(dt.timezone.utc)) - dt.datetime.fromisoformat(iso)).total_seconds() // 60)
    return f"{max(mins, 1)}m ago" if mins < 60 else f"{mins // 60}h ago" if mins < 48 * 60 else f"{mins // 1440}d ago"


def news_credit(i):
    return f"{i['reporter']}, {i['outlet']}" if i.get("reporter") else "RotoWire"


def short(text, n=170):
    text = text or ""
    return text if len(text) <= n else text[:n].rsplit(" ", 1)[0] + "…"


def build(data, games, date):
    e = html.escape
    title = "NBA injury report: " + ", ".join(f"{g['away']} @ {g['home']} {fmt_time(g['time'])}" for g in games)
    grey, light = "color:#6b7280", "color:#9aa3ad"
    label_css = f"font-size:10.5px;text-transform:uppercase;letter-spacing:.6px;{grey};font-weight:bold;margin:12px 0 4px"

    def tag(st):
        if not st:
            return ""
        t, c = TAG[st]
        return (f' <span style="font-size:10px;font-weight:bold;color:#fff;background:{c};border-radius:3px;'
                f'padding:1px 4px;vertical-align:middle">{t}</span>')

    def mins(n):
        m = mins_tag(data, n)
        return f'<span style="{grey};font-size:12.5px;font-weight:normal">{m}</span>' if m else ""

    h = [f'<div style="font-family:Arial,Helvetica,sans-serif;color:#1d1c1d;background:#f2f4f7;padding:14px">'
         f'<div style="max-width:640px;margin:0 auto">'
         f'<div style="background:#1d1c1d;color:#fff;border-radius:10px;padding:14px 18px">'
         f'<div style="font-size:18px;font-weight:bold">NBA injury report</div>'
         f'<div style="font-size:13px;color:#c9ced6;margin-top:2px">{e(dt.date.fromisoformat(date).strftime("%A, %B %-d"))} · '
         f'<a href="{SITE}" style="color:#9ec5ff">Open the board</a></div></div>']
    t = [title, ""]
    for g in games:
        h.append(f'<div style="background:#fff;border:1px solid #e3e6ea;border-radius:10px;padding:14px 16px;margin-top:12px">'
                 f'<div style="font-size:16px;font-weight:bold;padding-bottom:10px;border-bottom:1px solid #eceff2">'
                 f'<span style="font-size:12px;color:#fff;background:#1d1c1d;border-radius:4px;padding:2px 7px;vertical-align:middle">'
                 f'{fmt_time(g["time"])} ET</span>&nbsp; {logo(g["away"], 26)} {e(name(g["away"]))} '
                 f'<span style="{light};font-weight:normal">@</span> {logo(g["home"], 26)} {e(name(g["home"]))}</div>')
        t.append(f"{fmt_time(g['time'])} ET: {name(g['away'])} @ {name(g['home'])}")
        for team, which, og in b2b_for(data, g):
            h.append(f'<div style="margin:12px 0 0;padding:8px 12px;background:#fff4c2;border:2px solid #b7950b;border-radius:8px;'
                     f'font-size:14px"><b style="color:#7d6608">🔁 BACK-TO-BACK: {e(name(team))}</b> · {e(b2b_text(team, which, og))}</div>')
            t.append(f"  🔁 BACK-TO-BACK: {name(team)} · {b2b_text(team, which, og)}")
        for w in restrictions_for(data, (g["away"], g["home"]), date):
            h.append(f'<div style="margin:12px 0 0;padding:10px 12px;background:#fdecea;border:2px solid #c0392b;border-radius:8px">'
                     f'<div style="font-size:15px;font-weight:bold;color:#c0392b">⚠️ MINUTES RESTRICTION: '
                     f'<a href="{e(w["url"])}" style="color:#c0392b">{e(w["player"])}</a> ({e(w["team"])})</div>'
                     f'<div style="font-size:12.5px;margin-top:3px">{e(short(w["text"], 260))} '
                     f'<span style="{light}">{e(news_credit(w))} · {ago(w["at"])}</span></div></div>')
            t.append(f"  ⚠️ MINUTES RESTRICTION: {w['player']} ({w['team']}): {w['text']} ({news_credit(w)})")
        for n_team, (team, opp) in enumerate(((g["away"], g["home"]), (g["home"], g["away"]))):
            inj = injuries_for(data, team, date)
            status = {norm_name(i["player"]): i["st"] for i in inj}
            label, starters = starters_for(data, team, date, inj)
            bench, deep = bench_for(data, team, inj, starters)
            xt = expected_tags(data, team, date, skip={k for k, st in status.items() if st in ("out", "doubt")})
            sep = "border-top:1px solid #eceff2;margin-top:14px;padding-top:12px" if n_team else "margin-top:12px"
            h.append(f'<div style="{sep}"><div style="font-size:15px;font-weight:bold">{logo(team, 24)} {e(name(team))}</div>')
            t.append(f"  {name(team)}")
            # 1. starters
            if starters:
                h.append(f'<div style="{label_css}">{e(label)}</div><table cellpadding="0" cellspacing="0" style="border-collapse:collapse;font-size:14px">')
                for p, n, why in starters:
                    hl = "background:#fff4c2;" if minutes_change(data, n) else ""
                    h.append(f'<tr><td style="width:30px;padding:2px 0;{light};font-size:11px;font-weight:bold">{e(p)}</td>'
                             f'<td style="padding:2px 4px;{hl}"><b>{e(n)}</b> {mins(n)}{exp_html(xt, n)}{tag(status.get(norm_name(n)))}{change_html(data, n)}'
                             f'{f" <span style=color:#1e8449;font-size:12px>in for {e(why[7:])}</span>" if why else ""}</td></tr>')
                h.append("</table>")
                t.append(f"    {label}: " + ", ".join(f"{p} {n}{mins_tag(data, n)}{exp_text(xt, n)}{change_text(data, n)}{f' ({why})' if why else ''}"
                                                       for p, n, why in starters))
            # 2. bench (deep bench only when expected up)
            up = []
            if bench or deep:
                h.append(f'<div style="{label_css}">Bench</div><div style="font-size:13px;line-height:1.7">'
                         + " &nbsp;·&nbsp; ".join(f'<span style="{"background:#fff4c2;" if minutes_change(data, n) else ""}">{e(n)} {mins(n)}</span>'
                                                  f'{exp_html(xt, n)}{tag(st)}{change_html(data, n)}' for p, n, st in bench) + "</div>")
                up = deep_bench_up(data, team, date, deep, skip={k for k, st in status.items() if st in ("out", "doubt")})
                if up:   # deep bench only when Dolly expects him to play more than usual
                    h.append(f'<div style="font-size:12px;{light};line-height:1.6;margin-top:2px">Deep bench, expected up: '
                             + ", ".join(f'{e(n)}{mins_tag(data, n)}'
                                         f' <span style="font-size:12px;font-weight:bold;color:#1e8449">Exp {x:.1f}{f" (+{d:.1f})" if d is not None else ""}</span>'
                                         for n, x, d in up) + "</div>")
                t.append("    Bench: " + ", ".join(f"{n}{mins_tag(data, n)}{exp_text(xt, n)}{change_text(data, n)}" for _, n, _ in bench)
                         + (f" | Deep bench, expected up: {', '.join(f'{n}{mins_tag(data, n)} 📈 Expected {x:.1f}' + (f' (+{d:.1f})' if d is not None else '') for n, x, d in up)}" if up else ""))
            # 3. matchup minutes alerts (minutes-vs-teams workbook)
            alerts = matchup_alerts_for(data, team, opp, inj, starters)
            if alerts:
                h.append(f'<div style="{label_css}">Matchup minutes</div><div style="font-size:13px;line-height:1.6">'
                         + "".join(f'<div>{"📈" if d == "up" else "📉"} <b>{e(n)}</b> usually plays '
                                   f'<b style="color:{"#1e8449" if d == "up" else "#c0392b"}">{"more" if d == "up" else "fewer"}</b>'
                                   f' minutes vs {e(name(opp).split()[-1])}</div>' for n, d in alerts) + "</div>")
                t.append("    Matchup minutes: " + ", ".join(f"{n} {'more' if d == 'up' else 'fewer'} vs {opp}" for n, d in alerts))
            # 4. beat-writer news (RotoWire feed)
            news = news_for(data, team)
            if news:
                h.append(f'<div style="{label_css}">Beat-writer news</div>')
                for i in news[:4]:
                    h.append(f'<div style="font-size:13px;line-height:1.45;margin:0 0 7px"><b>{e(i["player"])}</b> · '
                             f'<a href="{e(i["url"])}" style="color:#1d1c1d;font-weight:bold">{e(i["headline"])}</a> '
                             f'<span style="{light};font-size:11.5px">{e(i.get("reporter") or "RotoWire")} · {ago(i["at"])}</span>'
                             f'<div style="{grey};font-size:12.5px">{e(short(i["text"]))}</div></div>')
                t.append("    News: " + " | ".join(f"{i['player']}: {i['headline']} ({news_credit(i)})" for i in news[:4]))
            pr = pressers_for(data, team)
            if pr:
                h.append(f'<div style="{label_css}">Press conferences</div>')
                for n in pr[:3]:
                    h.append(f'<div style="font-size:13px;line-height:1.45;margin:0 0 7px">🎙️ <b>{e(", ".join(n["players"][:4]))}</b> · '
                             f'{e(short(n["text"], 280))} <span style="{light};font-size:11.5px">'
                             f'<a href="{e(n["url"])}" style="color:#5a6470">Presser Wire</a> · {ago(n["at"])}</span></div>')
                t.append("    Pressers: " + " | ".join(f"{', '.join(n['players'][:4])}: {n['text']} (Presser Wire)" for n in pr[:3]))
            # 5. injuries
            h.append(f'<div style="{label_css}">Injuries</div>')
            if not inj:
                h.append(f'<div style="font-size:13px;{grey}">None listed</div>')
                t.append("    Injuries: none listed")
            for i in inj:
                who = f'<a href="{e(i["link"])}" style="color:#1d1c1d;text-decoration:none">{e(i["player"])}</a>' if i["link"] else e(i["player"])
                per = (f' <span style="font-size:11px;font-weight:bold;color:#5b4b00;background:#fff4c2;border-radius:3px;padding:0 4px">'
                       f'per {e(i["beat"])}</span>') if i["beat"] else ""
                srcs = ", ".join(e(x["src"]) for x in i["srcs"]) + (" · sources differ" if i["differ"] else "")
                what = f' <span style="{grey}">{e(i["injury"])}</span>' if i["injury"] else ""
                h.append(f'<div style="font-size:13px;line-height:1.4;margin:0 0 6px">{DOT[i["st"]]} <b>{who}</b> {mins(i["player"])} '
                         f'<b style="color:{TAG[i["st"]][1]}">{LABEL[i["st"]]}</b>{per}{what}'
                         f'<div style="font-size:11px;{light};margin-left:20px">{srcs}</div></div>')
                t.append(f"    {DOT[i['st']]} {i['player']}{mins_tag(data, i['player'])}: {LABEL[i['st']]}{' | ' + i['injury'] if i['injury'] else ''}"
                         f" ({', '.join(x['src'] for x in i['srcs'])})")
            h.append("</div>")
        h.append("</div>")
        t.append("")
    h.append(f'<div style="font-size:11px;{light};margin:12px 4px 0;line-height:1.5">'
             '🔴 Out · 🟠 Doubtful · 🟡 Questionable · 🟢 Probable · ✅ Available (NBA official report) · (Number) = average minutes per game, this season, '
             'otherwise last season (marked with the season) · Green / red "Exp N (+/−)" = expected minutes 5+ more / fewer than that average · Highlighted = 5+ minutes more or fewer than last season · Click a player for the source.</div></div></div>')
    return title, "".join(h), "\n".join(t)


def slack_escape(t):
    return str(t).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def build_slack(data, game, date, test=False):
    """One Slack message (Block Kit) per game, same layout as the email: starters, bench, alerts, then injuries."""
    e = slack_escape
    tag = {"out": " `OUT`", "doubt": " `DOUBT`", "q": " `GTD`", "prob": " `PROB`"}
    g = game
    title = f"{'[TEST] ' if test else ''}{fmt_time(g['time'])} ET · {name(g['away'])} @ {name(g['home'])}"
    blocks = [{"type": "header", "text": {"type": "plain_text", "text": title[:150]}}]
    for team, which, og in b2b_for(data, g):
        blocks.append({"type": "section", "text": {"type": "mrkdwn", "text":
                       f":repeat: *BACK-TO-BACK: {e(name(team))}* · {e(b2b_text(team, which, og))}"}})
    for w in restrictions_for(data, (g["away"], g["home"]), date):
        blocks.append({"type": "section", "text": {"type": "mrkdwn", "text":
                       f":warning: *MINUTES RESTRICTION: <{w['url']}|{e(w['player'])}> ({w['team']})*\n{e(w['text'])} "
                       f"_({e(news_credit(w))} · {ago(w['at'])})_"[:2900]}})
    for team, opp in ((g["away"], g["home"]), (g["home"], g["away"])):
        inj = injuries_for(data, team, date)
        status = {norm_name(i["player"]): i["st"] for i in inj}
        label, starters = starters_for(data, team, date, inj)
        bench, deep = bench_for(data, team, inj, starters)
        alerts = matchup_alerts_for(data, team, opp, inj, starters)
        xt = expected_tags(data, team, date, skip={k for k, st in status.items() if st in ("out", "doubt")})
        logo_url = f"https://a.espncdn.com/i/teamlogos/nba/500/{ESPN_LOGO.get(team, team.lower())}.png"
        blocks.append({"type": "context", "elements": [
            {"type": "image", "image_url": logo_url, "alt_text": team},
            {"type": "mrkdwn", "text": f"*{e(name(team))}*"}]})
        if starters:
            rows = [f"`{p:<2}` *{e(n)}*{mins_tag(data, n, True)}{exp_text(xt, n)}{tag.get(status.get(norm_name(n)), '')}{change_text(data, n)}{f'  _in for {e(why[7:])}_' if why else ''}"
                    for p, n, why in starters]
            blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": f"_{e(label)}_\n" + "\n".join(rows)}})
        if bench or deep:
            txt = "*Bench:* " + " · ".join(f"{e(n)}{mins_tag(data, n, True)}{exp_text(xt, n)}{tag.get(st, '')}{change_text(data, n)}" for _, n, st in bench)
            up = deep_bench_up(data, team, date, deep, skip={k for k, st in status.items() if st in ("out", "doubt")})
            if up:
                txt += "\n*Deep bench, expected up:* " + ", ".join(
                    f"{e(n)}{mins_tag(data, n, True)} 📈 Expected {x:.1f}" + (f" (+{d:.1f})" if d is not None else "") for n, x, d in up)
            blocks.append({"type": "context", "elements": [{"type": "mrkdwn", "text": txt[:2900]}]})
        if alerts:
            blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": "\n".join(
                f"{'📈' if d == 'up' else '📉'} *{e(n)}* usually plays *{'more' if d == 'up' else 'fewer'}* minutes vs "
                f"{e(name(opp).split()[-1])}" for n, d in alerts)}})
        news = news_for(data, team)
        if news:
            blocks.append({"type": "context", "elements": [{"type": "mrkdwn", "text": ("*Beat-writer news*\n" + "\n".join(
                f"📰 *{e(i['player'])}:* <{i['url']}|{e(i['headline'])}> {e(i['text'])} _({e(news_credit(i))} · {ago(i['at'])})_"
                for i in news[:4]))[:2900]}]})
        pr = pressers_for(data, team)
        if pr:
            blocks.append({"type": "context", "elements": [{"type": "mrkdwn", "text": ("*Press conferences*\n" + "\n".join(
                f"🎙️ *{e(', '.join(n['players'][:4]))}:* {e(short(n['text'], 280))} _(<{n['url']}|Presser Wire> · {ago(n['at'])})_"
                for n in pr[:3]))[:2900]}]})
        lines = []
        for i in inj:
            who = f"<{i['link']}|{e(i['player'])}>" if i["link"] else e(i["player"])
            per = f" _(per {e(i['beat'])})_" if i["beat"] else ""
            lines.append(f"{DOT[i['st']]} *{who}*{mins_tag(data, i['player'], True)} {LABEL[i['st']]}{per}"
                         f"{' · ' + e(i['injury']) if i['injury'] else ''}"
                         f" · {', '.join(e(x['src']) for x in i['srcs'])}{' · sources differ' if i['differ'] else ''}")
        blocks.append({"type": "context", "elements": [{"type": "mrkdwn",
                       "text": ("*Injuries*\n" + "\n".join(lines))[:2900] if lines else "✅ No injuries listed"}]})
        blocks.append({"type": "divider"})
    blocks.append({"type": "context", "elements": [{"type": "mrkdwn", "text":
                   f"🔴 Out · 🟠 Doubtful · 🟡 Questionable · 🟢 Probable · ✅ Available (NBA report) · <{SITE}|Open the full board>"}]})
    return title, blocks


def blocks_to_text(title, blocks):
    """One plain message from the Block Kit blocks, for Slack Workflow Builder webhooks (they take a single text
    variable, no blocks). Slack still renders *bold*, _italics_ and <url|links> in it."""
    out = []
    for b in blocks:
        if b.get("type") == "divider":
            out.append("────────────")
        elif b.get("type") in ("section", "header"):
            out.append((b.get("text") or {}).get("text", ""))
        elif b.get("type") == "context":
            out.append(" ".join(el.get("text", "") for el in b.get("elements", []) if el.get("type") in ("mrkdwn", "plain_text")))
    return "\n".join(x for x in out if x).strip() or title


def slack_markdown(title, blocks):
    """The Slack report as standard markdown, for the scheduled Claude agent that posts it with the Slack
    connector (which takes **bold** and [text](url), not Slack's own *bold* / <url|text>)."""
    t = blocks_to_text(title, blocks)
    t = re.sub(r"<(https?://[^|>]+)\|([^>]+)>", r"[\2](\1)", t)         # <url|text> -> [text](url)
    t = re.sub(r"(?<![\w*])\*([^*\n]+?)\*(?![\w*])", r"**\1**", t)       # *bold* -> **bold**
    return t


def post_slack(url, text, blocks):
    workflow = "/triggers/" in url    # Workflow Builder webhook ("From a webhook" with a "text" variable)
    payload = {"text": blocks_to_text(text, blocks)[:39000]} if workflow else {"text": text, "blocks": blocks}
    req = urllib.request.Request(url, data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        body = r.read().decode()
    ok = body.strip() == "ok" or (workflow and '"ok":true' in body.replace(" ", ""))
    if not ok:
        raise RuntimeError(f"Slack said: {body[:200]}")


PROPS_FALLBACK_MIN = 15     # no confirmed lineups by this many minutes before tip: send anyway


def lineups_confirmed(data, g):
    """Both teams' RotoWire starting lineups for this game are confirmed."""
    lu = data.get("lineups") or {}
    return all((lu.get(t) or {}).get("date") == g["date"] and (lu.get(t) or {}).get("confirmed") for t in (g["away"], g["home"]))


def dm_traders(data, token, now, window, sent, stamp):
    """DM each game's report to the Props and Cores traders listed for it (one group DM per game) in today's #in-play-trading schedule (slack_assign.py),
    as soon as both teams' lineups are confirmed (RotoWire), or PROPS_FALLBACK_MIN minutes before tip if they never are
    (the user's rule, Oct 21 2026). Sent once per game ("dm <date> A@H").
    SLACK_DM_MODE: off = only print who would get it; test = all to the owner, marked [TEST]; on = to the traders."""
    import slack_assign as sa
    due = []
    for g in all_games(data):
        tip = dt.datetime.fromisoformat(f"{g['date']}T{g['time']}").replace(tzinfo=ET)
        key = f"{g['date']} {g['away']}@{g['home']}"
        if "dm " + key in sent or not (now <= tip <= now + dt.timedelta(hours=3)):
            continue
        confirmed = lineups_confirmed(data, g)
        if confirmed or tip - now <= dt.timedelta(minutes=PROPS_FALLBACK_MIN):
            due.append((key, g, confirmed))
    if not due:
        return
    m = sa.mode()
    try:
        text = sa.fetch_schedule(token, now.date())
    except Exception as ex:   # no access to the channel yet, Slack down: try again on the next run
        print(f"Slack DMs: could not read the schedule ({ex})")
        return
    if not text:
        print("Slack DMs: today's IP Trader Schedule isn't posted yet; trying again next run.")
        return
    sched = sa.parse_schedule(text)
    for key, g, confirmed in due:
        # one group DM per game: the bot + that game's Props AND Cores traders (user's choice, Oct 26 2026), like the
        # football reports; a lone trader gets a one-on-one message instead (hidden while the bot's Messages tab is off)
        people = [p for p in sched.get((g["away"], g["home"]), []) if re.search(r"prop|core", p["role"], re.I)]
        for p in people:
            p["name"] = p["name"] or sa.user_name(token, p["user"])
        who = sa.plan(people)
        why = "lineups confirmed" if confirmed else f"lineups not confirmed {PROPS_FALLBACK_MIN} min before tip"
        title, blocks = build_slack(data, g, g["date"], test=(m == "test"))
        if m == "off" or not people:
            print(f"Slack DMs ({m}, {why}): {g['away']}@{g['home']} would go to {who}")
        else:
            try:
                if m == "test":   # the owner only: SLACK_TEST_CHANNEL if set (visible), else a one-on-one DM
                    head = [{"type": "context", "elements": [{"type": "mrkdwn", "text": slack_escape(f"[TEST] Would go to a group DM with: {who} ({why})")}]}]
                    test_ch = (os.environ.get("SLACK_TEST_CHANNEL") or "").strip()
                    (sa.post_channel if test_ch else sa.dm)(token, test_ch or sa.OWNER, title, head + blocks)
                else:
                    sa.group_dm(token, [p["user"] for p in people] + sa.ALSO_INCLUDE.get(g["date"], []), title, blocks)
                print(f"Slack DMs ({m}, {why}): {g['away']}@{g['home']} sent to {'owner (test)' if m == 'test' else who}")
            except Exception as ex:
                print(f"Slack DMs: {g['away']}@{g['home']} failed: {ex}")
        if m != "off":
            sent["dm " + key] = stamp


def fresh_expected_minutes(data, path):
    """Use expected_minutes.json (saved by the Dolly Minutes extension) when it is newer than data.json's copy, so the
    report always has the latest Dolly read, even between data refreshes."""
    if not EXPECTED_ENABLED:
        return
    try:
        em = json.load(open(path))
    except (OSError, ValueError):
        return
    if (em.get("updated_at") or "") <= ((data.get("expected_minutes") or {}).get("updated_at") or ""):
        return
    from update_data import team_code
    for p in em.get("players", []):
        p["team"] = p.get("team") or team_code(p.get("teamName")) or ""
    data["expected_minutes"] = em


def due_games(data, now, window, sent, prefix=""):
    out = []
    for g in all_games(data):
        tip = dt.datetime.fromisoformat(f"{g['date']}T{g['time']}").replace(tzinfo=ET)
        key = f"{g['date']} {g['away']}@{g['home']}"
        if now <= tip <= now + dt.timedelta(minutes=window) and prefix + key not in sent:
            out.append((key, g))
    return out


def next_games(data, now):
    """The next tip-off time's games (for --test-slack)."""
    upcoming = [g for g in all_games(data)
                if dt.datetime.fromisoformat(f"{g['date']}T{g['time']}").replace(tzinfo=ET) >= now]
    return [g for g in upcoming if (g["date"], g["time"]) == (upcoming[0]["date"], upcoming[0]["time"])] if upcoming else []


def weekly_changes(data):
    """Every player whose minutes this season are CHANGE_MIN+ above or below last season."""
    sm = data.get("season_minutes") or {}
    rows = []
    for player, (gp, mpg, team) in (sm.get("current") or {}).items():
        c = minutes_change(data, player)
        if c:
            rows.append({"player": player, "team": team, "gp": gp, "diff": c[0], "now": c[1], "before": c[2], "vs": c[3]})
    return sorted(rows, key=lambda r: -abs(r["diff"]))


def build_weekly(data, rows):
    e = html.escape
    sm = data.get("season_minutes") or {}
    title = f"NBA weekly minutes changes: {len(rows)} players ({sm.get('season', '')})"
    grey = "color:#6b6b6b"
    h = [f'<div style="font-family:Arial,Helvetica,sans-serif;color:#1d1c1d;max-width:640px">'
         f'<div style="font-size:18px;font-weight:bold">Weekly minutes changes</div>'
         f'<div style="font-size:12px;{grey};margin:2px 0 10px">Players averaging {CHANGE_MIN:g}+ minutes more or fewer than the '
         f'last season, {e(sm.get("last_season", ""))} ({CHANGE_CUR_GAMES}+ games this season, {CHANGE_BASE_GAMES}+ last season). Stats through {e(sm.get("fetched_at", "?")[:10])} (ESPN). '
         f'<a href="{SITE}" style="color:#1264a3">Open the board</a></div>']
    t = [title, ""]
    for label, part in (("📈 Playing more", [r for r in rows if r["diff"] > 0]), ("📉 Playing less", [r for r in rows if r["diff"] < 0])):
        if not part:
            continue
        h.append(f'<div style="font-size:15px;font-weight:bold;margin:14px 0 4px">{label} ({len(part)})</div>'
                 '<table cellpadding="0" cellspacing="0" style="border-collapse:collapse;font-size:14px;width:100%">')
        t.append(label)
        for r in part:
            up = r["diff"] > 0
            h.append(f'<tr style="border-top:1px solid #eee"><td style="padding:5px 6px 5px 0;width:34px">{logo(r["team"], 22) if r["team"] else ""}</td>'
                     f'<td style="padding:5px 0"><b>{e(r["player"])}</b> <span style="{grey};font-size:12px">{e(name(r["team"]) if r["team"] else "")}</span></td>'
                     f'<td style="padding:5px 0;text-align:right;white-space:nowrap"><b>{r["now"]:.1f}</b> '
                     f'<span style="{grey}">vs {r["before"]:.1f} in {e(r["vs"])}</span> '
                     f'<b style="color:{"#1e8449" if up else "#c0392b"}">{"+" if up else ""}{r["diff"]:.1f}</b> '
                     f'<span style="{grey};font-size:12px">({r["gp"]} games)</span></td></tr>')
            t.append(f"  {r['player']} ({r['team']}): {r['now']:.1f} vs {r['before']:.1f} in {r['vs']} ({'+' if up else ''}{r['diff']:.1f}), {r['gp']} games")
        h.append("</table>")
    h.append("</div>")
    return title, "".join(h), "\n".join(t)


PREGAME_EMAIL = False   # pre-game emails off since Oct 26 2026 (Slack replaces them); the weekly email still goes


def send_email(subject, body_html, body_text):
    user, pw, to = os.environ.get("SMTP_USER"), os.environ.get("SMTP_PASSWORD"), os.environ.get("EMAIL_TO")
    if not (user and pw and to):
        print("Email: SMTP_USER / SMTP_PASSWORD / EMAIL_TO not set; skipped.")
        return False
    msg = EmailMessage()
    msg["Subject"], msg["From"], msg["To"] = subject, user, to
    msg.set_content(body_text)
    msg.add_alternative(body_html, subtype="html")
    with smtplib.SMTP_SSL(os.environ.get("SMTP_HOST", "smtp.gmail.com"), int(os.environ.get("SMTP_PORT", "465"))) as s:
        s.login(user, pw)
        s.send_message(msg)
    print(f"Email sent: {subject}")
    return True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data.json")
    ap.add_argument("--log", default="email_log.json")
    ap.add_argument("--window", type=int, default=25, help="send games tipping off within this many minutes")
    ap.add_argument("--out", help="write subject/html/text to files with this prefix instead of sending")
    ap.add_argument("--test-slack", action="store_true", help="post the next game's report to Slack now, marked TEST")
    ap.add_argument("--weekly", action="store_true", help="send the weekly minutes-changes email")
    ap.add_argument("--test-email", action="store_true", help="email the next game's report now, marked TEST (not logged)")
    ap.add_argument("--game", default="", help="with --test-email / --agent: a team in the game, e.g. NYK")
    ap.add_argument("--agent-due", type=int, metavar="MIN", help="print JSON of the Slack markdown for games tipping "
                    "off within MIN minutes (for the scheduled Claude agent that posts to Slack)")
    ap.add_argument("--agent-test", action="store_true", help="like --agent-due but for the next game (or --game), marked TEST")
    args = ap.parse_args()

    data = json.load(open(args.data))
    fresh_expected_minutes(data, os.path.join(os.path.dirname(os.path.abspath(args.data)), "expected_minutes.json"))
    now = dt.datetime.now(ET)
    slack_url = os.environ.get("SLACK_WEBHOOK_URL")

    if args.weekly:
        rows = weekly_changes(data)
        if not rows:
            print("Weekly: no big minutes changes yet (this season needs 5+ games per player); nothing sent.")
            return
        subject, body_html, body_text = build_weekly(data, rows)
        if args.out:
            open(args.out + ".html", "w").write(body_html)
            open(args.out + ".txt", "w").write(body_text)
            print(f"Wrote {args.out}.*  ({len(rows)} players)")
        else:
            send_email(subject, body_html, body_text)
        return

    if args.agent_due is not None or args.agent_test:
        if args.agent_test:
            games = next_games(data, now)
            if args.game.strip():
                games = [g for g in all_games(data) if args.game.strip().upper() in (g["away"], g["home"])
                         and dt.datetime.fromisoformat(f"{g['date']}T{g['time']}").replace(tzinfo=ET) >= now - dt.timedelta(hours=4)][:1]
            due = [(f"{g['date']} {g['away']}@{g['home']}", g) for g in games]
        else:
            due = due_games(data, now, args.agent_due, {})
        out = []
        for key, g in due:
            title, blocks = build_slack(data, g, g["date"], test=args.agent_test)
            out.append({"key": key, "title": title, "markdown": slack_markdown(title, blocks)})
        print(json.dumps(out, ensure_ascii=False, indent=1))
        return

    if args.test_email:
        games = next_games(data, now)
        if args.game.strip():   # a named game instead: the next one (or one under way) with that team
            want = args.game.strip().upper()
            soon = [g for g in all_games(data) if want in (g["away"], g["home"])
                    and dt.datetime.fromisoformat(f"{g['date']}T{g['time']}").replace(tzinfo=ET) >= now - dt.timedelta(hours=4)]
            games = soon[:1]
        if not games:
            sys.exit("No upcoming games in data.json to test with.")
        subject, body_html, body_text = build(data, games, games[0]["date"])
        send_email("[TEST] " + subject, body_html, body_text)   # not logged: the real one still goes out before tip
        return

    if args.test_slack:
        if not slack_url:
            sys.exit("SLACK_WEBHOOK_URL is not set (add it under Settings > Secrets and variables > Actions).")
        games = next_games(data, now)
        if not games:
            sys.exit("No upcoming games in data.json to test with.")
        for g in games:
            title, blocks = build_slack(data, g, g["date"], test=True)
            post_slack(slack_url, title, blocks)
            print(f"Slack test sent: {title}")
        return

    sent = json.load(open(args.log)) if os.path.exists(args.log) else {}
    stamp = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    due = due_games(data, now, args.window, sent)
    if due:
        games = [g for _, g in due]
        subject, body_html, body_text = build(data, games, games[0]["date"])
        if args.out:
            open(args.out + ".subject.txt", "w").write(subject)
            open(args.out + ".html", "w").write(body_html)
            open(args.out + ".txt", "w").write(body_text)
            print(f"Wrote {args.out}.*  ({len(games)} games)")
            return
        # Oct 26 2026: pre-game emails turned off (user: the Slack group DMs replace them). PREGAME_EMAIL = True brings them back.
        if PREGAME_EMAIL and send_email(subject, body_html, body_text):
            sent.update({k: stamp for k, _ in due})
    elif not args.out:
        print("Email: no games due.")

    if slack_url and not args.out:
        for key, g in due_games(data, now, args.window, sent, prefix="slack "):
            title, blocks = build_slack(data, g, g["date"])
            post_slack(slack_url, title, blocks)
            sent["slack " + key] = stamp
            print(f"Slack sent: {title}")

    bot = os.environ.get("SLACK_BOT_TOKEN")
    if bot and not args.out:
        dm_traders(data, bot, now, args.window, sent, stamp)

    cutoff = (dt.date.today() - dt.timedelta(days=7)).isoformat()
    sent = {k: v for k, v in sent.items() if re.sub(r"^(slack|dm) ", "", k)[:10] >= cutoff}
    if sent or os.path.exists(args.log):
        json.dump(sent, open(args.log, "w"), indent=1)


if __name__ == "__main__":
    main()
