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
import argparse, datetime as dt, html, json, os, smtplib, sys
import urllib.request
from email.message import EmailMessage

sys.path.insert(0, os.path.dirname(__file__))
from update_data import ET, TEAMS, all_games, norm_name  # noqa: E402

SITE = "https://lukemaass-hub.github.io/nba-board/"
POS = ["PG", "SG", "SF", "PF", "C"]
RANK = {"out": 0, "doubt": 1, "q": 2, "prob": 3}
LABEL = {"out": "Out", "doubt": "Doubtful", "q": "Questionable", "prob": "Probable"}
DOT = {"out": "🔴", "doubt": "🟠", "q": "🟡", "prob": "🟢"}
SRC_URL = {"CBS": "https://www.cbssports.com/nba/injuries/", "Covers": "https://www.covers.com/sport/basketball/nba/injuries",
           "ESPN": "https://www.espn.com/nba/injuries", "RotoWire": "https://www.rotowire.com/basketball/nba-lineups.php"}


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
                    "beat": g["beat"]["src"] if g["beat"] else ""})
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


def restrictions_for(data, teams, date):
    """Minutes-restriction warnings from beat-writer news for these teams on this date."""
    return [w for w in data.get("restrictions", []) if w["team"] in teams and w["from"] <= date <= w["through"]]


def news_for(data, team, now=None):
    """Beat-writer news (RotoWire feed) about this team's players from the last 36 hours, newest first."""
    now = now or dt.datetime.now(dt.timezone.utc)
    return [i for i in data.get("news", []) if i.get("team") == team
            and dt.datetime.fromisoformat(i["at"]) >= now - dt.timedelta(hours=NEWS_HOURS)]


def ago(iso, now=None):
    mins = int(((now or dt.datetime.now(dt.timezone.utc)) - dt.datetime.fromisoformat(iso)).total_seconds() // 60)
    return f"{max(mins, 1)}m ago" if mins < 60 else f"{mins // 60}h ago" if mins < 48 * 60 else f"{mins // 1440}d ago"


def news_credit(i):
    return f"{i['reporter']}, {i['outlet']}" if i.get("reporter") else "RotoWire"


def build(data, games, date):
    e = html.escape
    title = "NBA injury report: " + ", ".join(f"{g['away']} @ {g['home']} {fmt_time(g['time'])}" for g in games)
    grey = "color:#6b6b6b"

    def tag(st):
        if not st:
            return ""
        t, c = TAG[st]
        return (f' <span style="font-size:10px;font-weight:bold;color:#fff;background:{c};border-radius:3px;'
                f'padding:1px 4px;vertical-align:middle">{t}</span>')

    h = [f'<div style="font-family:Arial,Helvetica,sans-serif;color:#1d1c1d;max-width:640px">'
         f'<div style="font-size:18px;font-weight:bold">Injury report, {e(dt.date.fromisoformat(date).strftime("%A, %B %-d"))}</div>'
         f'<div style="font-size:12px;{grey};margin:2px 0 8px">Data refreshed {e(data.get("generated_at", "?"))} UTC · '
         f'<a href="{SITE}" style="color:#1264a3">Open the full board</a></div>']
    t = [title, ""]
    for g in games:
        h.append(f'<div style="margin:18px 0 6px;padding:10px 0 6px;border-top:2px solid #1d1c1d;font-size:16px;font-weight:bold">'
                 f'{fmt_time(g["time"])} ET &nbsp;{logo(g["away"], 26)} {e(name(g["away"]))} '
                 f'<span style="{grey};font-weight:normal">@</span> {logo(g["home"], 26)} {e(name(g["home"]))}</div>')
        t.append(f"{fmt_time(g['time'])} ET: {name(g['away'])} @ {name(g['home'])}")
        for w in restrictions_for(data, (g["away"], g["home"]), date):
            h.append(f'<div style="margin:8px 0;padding:10px 12px;background:#fdecea;border:2px solid #c0392b;border-radius:6px">'
                     f'<div style="font-size:15px;font-weight:bold;color:#c0392b">⚠️ MINUTES RESTRICTION: '
                     f'<a href="{e(w["url"])}" style="color:#c0392b">{e(w["player"])}</a> ({e(w["team"])})</div>'
                     f'<div style="font-size:12px;margin-top:3px">{e(w["text"])} '
                     f'<span style="color:#8a8a8a">({e(news_credit(w))} · {ago(w["at"])})</span></div></div>')
            t.append(f"  ⚠️ MINUTES RESTRICTION: {w['player']} ({w['team']}): {w['text']} ({news_credit(w)})")
        for team, opp in ((g["away"], g["home"]), (g["home"], g["away"])):
            inj = injuries_for(data, team, date)
            status = {norm_name(i["player"]): i["st"] for i in inj}
            label, starters = starters_for(data, team, date, inj)
            bench, deep = bench_for(data, team, inj, starters)
            h.append(f'<div style="margin:12px 0 0;padding:10px 12px;background:#f6f7f9;border-radius:6px">'
                     f'<div style="font-size:15px;font-weight:bold;margin-bottom:6px">{logo(team, 28)} {e(name(team))}</div>')
            t.append(f"  {name(team)}")
            # 1. starters
            if starters:
                h.append(f'<div style="font-size:11px;text-transform:uppercase;letter-spacing:.5px;{grey};margin:4px 0 2px">{e(label)}</div>'
                         '<table cellpadding="0" cellspacing="0" style="border-collapse:collapse;font-size:15px">')
                for p, n, why in starters:
                    h.append(f'<tr><td style="width:34px;padding:2px 0;{grey};font-size:12px;font-weight:bold">{e(p)}</td>'
                             f'<td style="padding:2px 0"><b>{e(n)}</b>{tag(status.get(norm_name(n)))}'
                             f'{f" <span style=color:#1e8449;font-size:12px>in for {e(why[7:])}</span>" if why else ""}</td></tr>')
                h.append("</table>")
                t.append(f"    {label}: " + ", ".join(f"{p} {n}{f' ({why})' if why else ''}" for p, n, why in starters))
            # 2. bench
            if bench or deep:
                h.append(f'<div style="font-size:11px;text-transform:uppercase;letter-spacing:.5px;{grey};margin:8px 0 2px">Projected bench</div>'
                         f'<div style="font-size:13px;line-height:1.6">'
                         + " · ".join(f'<span style="{grey};font-size:11px">{e(p)}</span> {e(n)}{tag(st)}' for p, n, st in bench)
                         + (f'<div style="font-size:12px;{grey}">Deep bench: ' + ", ".join(e(n) for _, n, _ in deep) + "</div>" if deep else "")
                         + "</div>")
                t.append("    Bench: " + ", ".join(n for _, n, _ in bench) + (f" | Deep bench: {', '.join(n for _, n, _ in deep)}" if deep else ""))
            # 3. matchup minutes alerts (minutes-vs-teams workbook)
            alerts = matchup_alerts_for(data, team, opp, inj, starters)
            if alerts:
                h.append(f'<div style="font-size:11px;text-transform:uppercase;letter-spacing:.5px;{grey};margin:8px 0 2px">'
                         f'Matchup minutes alert</div><div style="font-size:13px;line-height:1.5">'
                         + "".join(f'<div>{"📈" if d == "up" else "📉"} <b>{e(n)}</b> usually plays '
                                   f'<b style="color:{"#1e8449" if d == "up" else "#c0392b"}">{"more" if d == "up" else "fewer"}</b>'
                                   f' minutes vs {e(name(opp).split()[-1])}</div>' for n, d in alerts) + "</div>")
                t.append("    Matchup minutes: " + ", ".join(f"{n} {'more' if d == 'up' else 'fewer'} vs {opp}" for n, d in alerts))
            # 4. beat-writer news (RotoWire feed)
            news = news_for(data, team)
            if news:
                h.append(f'<div style="font-size:11px;text-transform:uppercase;letter-spacing:.5px;{grey};margin:8px 0 2px">'
                         f'Beat-writer news</div>')
                for i in news[:4]:
                    h.append(f'<div style="font-size:12px;line-height:1.45;margin:3px 0">📰 <b>{e(i["player"])}:</b> '
                             f'<a href="{e(i["url"])}" style="color:#1d1c1d">{e(i["headline"])}</a> '
                             f'<span style="{grey}">{e(i["text"])}</span> '
                             f'<span style="color:#8a8a8a">({e(news_credit(i))} · {ago(i["at"])})</span></div>')
                t.append("    News: " + " | ".join(f"{i['player']}: {i['headline']} ({news_credit(i)})" for i in news[:4]))
            # 5. injuries, smaller
            h.append(f'<div style="font-size:11px;text-transform:uppercase;letter-spacing:.5px;{grey};margin:8px 0 2px">Injuries</div>'
                     '<div style="font-size:12px;line-height:1.5">')
            if not inj:
                h.append("✅ None listed")
                t.append("    Injuries: none listed")
            for i in inj:
                who = f'<a href="{e(i["link"])}" style="color:#1d1c1d">{e(i["player"])}</a>' if i["link"] else e(i["player"])
                srcs = ", ".join(f'<a href="{e(x["url"])}" style="color:#8a8a8a">{e(x["src"])}</a>' if x["url"] else e(x["src"])
                                 for x in i["srcs"])
                per = f" <i>(per {e(i['beat'])})</i>" if i["beat"] else ""
                h.append(f'<div>{DOT[i["st"]]} <b>{who}</b> {LABEL[i["st"]]}{per}'
                         f'{" · " + e(i["injury"]) if i["injury"] else ""} '
                         f'<span style="color:#8a8a8a">· {srcs}{" · sources differ" if i["differ"] else ""}</span></div>')
                t.append(f"    {DOT[i['st']]} {i['player']}: {LABEL[i['st']]}{' | ' + i['injury'] if i['injury'] else ''}"
                         f" ({', '.join(x['src'] for x in i['srcs'])})")
            h.append("</div></div>")
        t.append("")
    h.append(f'<div style="font-size:11px;{grey};margin-top:16px;border-top:1px solid #ddd;padding-top:8px">'
             '🔴 Out · 🟠 Doubtful · 🟡 Questionable · 🟢 Probable. Click a player for the source. '
             'Bench comes from the ESPN depth chart. Matchup alerts: average minutes vs this opponent is 5+ above or below '
             'the player\'s usual over 5+ games vs that team (your minutes-vs-teams sheet, top 100 players, 2023-26).</div></div>')
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
        logo_url = f"https://a.espncdn.com/i/teamlogos/nba/500/{ESPN_LOGO.get(team, team.lower())}.png"
        blocks.append({"type": "context", "elements": [
            {"type": "image", "image_url": logo_url, "alt_text": team},
            {"type": "mrkdwn", "text": f"*{e(name(team))}*"}]})
        if starters:
            rows = [f"`{p:<2}` *{e(n)}*{tag.get(status.get(norm_name(n)), '')}{f'  _in for {e(why[7:])}_' if why else ''}"
                    for p, n, why in starters]
            blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": f"_{e(label)}_\n" + "\n".join(rows)}})
        if bench or deep:
            txt = "*Bench:* " + " · ".join(f"{e(n)}{tag.get(st, '')}" for _, n, st in bench)
            if deep:
                txt += "\n*Deep bench:* " + ", ".join(e(n) for _, n, _ in deep)
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
        lines = []
        for i in inj:
            who = f"<{i['link']}|{e(i['player'])}>" if i["link"] else e(i["player"])
            per = f" _(per {e(i['beat'])})_" if i["beat"] else ""
            lines.append(f"{DOT[i['st']]} *{who}* {LABEL[i['st']]}{per}"
                         f"{' · ' + e(i['injury']) if i['injury'] else ''}"
                         f" · {', '.join(e(x['src']) for x in i['srcs'])}{' · sources differ' if i['differ'] else ''}")
        blocks.append({"type": "context", "elements": [{"type": "mrkdwn",
                       "text": ("*Injuries*\n" + "\n".join(lines))[:2900] if lines else "✅ No injuries listed"}]})
        blocks.append({"type": "divider"})
    blocks.append({"type": "context", "elements": [{"type": "mrkdwn", "text":
                   f"🔴 Out · 🟠 Doubtful · 🟡 Questionable · 🟢 Probable · <{SITE}|Open the full board>"}]})
    return title, blocks


def post_slack(url, text, blocks):
    req = urllib.request.Request(url, data=json.dumps({"text": text, "blocks": blocks}).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        body = r.read().decode()
    if body.strip() != "ok":
        raise RuntimeError(f"Slack said: {body[:200]}")


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
    args = ap.parse_args()

    data = json.load(open(args.data))
    now = dt.datetime.now(ET)
    slack_url = os.environ.get("SLACK_WEBHOOK_URL")

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
        if send_email(subject, body_html, body_text):
            sent.update({k: stamp for k, _ in due})
    elif not args.out:
        print("Email: no games due.")

    if slack_url and not args.out:
        for key, g in due_games(data, now, args.window, sent, prefix="slack "):
            title, blocks = build_slack(data, g, g["date"])
            post_slack(slack_url, title, blocks)
            sent["slack " + key] = stamp
            print(f"Slack sent: {title}")

    cutoff = (dt.date.today() - dt.timedelta(days=7)).isoformat()
    sent = {k: v for k, v in sent.items() if k.removeprefix("slack ")[:10] >= cutoff}
    if sent or os.path.exists(args.log):
        json.dump(sent, open(args.log, "w"), indent=1)


if __name__ == "__main__":
    main()
