#!/usr/bin/env python3
"""Email the availability report for games that tip off soon.

Run right after update_data.py. Picks every game starting within --window minutes that has not been emailed yet
(email_log.json remembers), builds the same report the page shows, and sends it by SMTP.

Needs (GitHub secrets): SMTP_USER, SMTP_PASSWORD, EMAIL_TO. Optional: SMTP_HOST (default smtp.gmail.com), SMTP_PORT (465).
Without them, --out writes the email to files instead of sending.

Usage:  python pipeline/email_report.py --data data.json --window 40
"""
import argparse, datetime as dt, html, json, os, smtplib, sys
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
    """Same merge as the page: one entry per player, worst status wins, every source listed."""
    groups = {}
    for r in data.get("injuries", []):
        if r["team"] != team or (r.get("through") and date > r["through"]):
            continue
        if r.get("st"):
            st, label = r["st"], LABEL[r["st"]]
        elif r.get("kind") == "O":
            st, label = ("q", "Out earlier, return date passed") if r.get("until") and date >= r["until"] else ("out", "Out")
        else:
            st, label = "q", "Game-time decision"
        g = groups.setdefault(norm_name(r["player"]), {"player": r["player"], "sts": set(), "lines": []})
        g["sts"].add(st)
        g["lines"].append({"src": r["src"], "st": st, "label": label, "injury": r.get("injury", ""),
                           "url": r.get("url") or SRC_URL.get(r["src"], "")})
    out = []
    for g in groups.values():
        best = min(g["sts"], key=RANK.get)
        srcs, seen = [], set()
        for l in g["lines"]:
            if l["src"] not in seen:
                seen.add(l["src"])
                srcs.append(l)
        link = next((l["url"] for l in g["lines"] if l["st"] == best and l["url"]), "") or next((l["url"] for l in srcs if l["url"]), "")
        out.append({"player": g["player"], "st": best, "injury": next((l["injury"] for l in g["lines"] if l["injury"]), ""),
                    "srcs": srcs, "link": link, "differ": len(g["sts"]) > 1})
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
        for team in (g["away"], g["home"]):
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
            # 3. injuries, smaller
            h.append(f'<div style="font-size:11px;text-transform:uppercase;letter-spacing:.5px;{grey};margin:8px 0 2px">Injuries</div>'
                     '<div style="font-size:12px;line-height:1.5">')
            if not inj:
                h.append("✅ None listed")
                t.append("    Injuries: none listed")
            for i in inj:
                who = f'<a href="{e(i["link"])}" style="color:#1d1c1d">{e(i["player"])}</a>' if i["link"] else e(i["player"])
                srcs = ", ".join(f'<a href="{e(x["url"])}" style="color:#8a8a8a">{e(x["src"])}</a>' if x["url"] else e(x["src"])
                                 for x in i["srcs"])
                h.append(f'<div>{DOT[i["st"]]} <b>{who}</b> {LABEL[i["st"]]}{" · " + e(i["injury"]) if i["injury"] else ""} '
                         f'<span style="color:#8a8a8a">· {srcs}{" · sources differ" if i["differ"] else ""}</span></div>')
                t.append(f"    {DOT[i['st']]} {i['player']}: {LABEL[i['st']]}{' | ' + i['injury'] if i['injury'] else ''}"
                         f" ({', '.join(x['src'] for x in i['srcs'])})")
            h.append("</div></div>")
        t.append("")
    h.append(f'<div style="font-size:11px;{grey};margin-top:16px;border-top:1px solid #ddd;padding-top:8px">'
             '🔴 Out · 🟠 Doubtful · 🟡 Questionable · 🟢 Probable. Click a player for the source. '
             'Bench comes from the ESPN depth chart.</div></div>')
    return title, "".join(h), "\n".join(t)


def due_games(data, now, window, sent):
    out = []
    for g in all_games(data):
        tip = dt.datetime.fromisoformat(f"{g['date']}T{g['time']}").replace(tzinfo=ET)
        key = f"{g['date']} {g['away']}@{g['home']}"
        if now <= tip <= now + dt.timedelta(minutes=window) and key not in sent:
            out.append((key, g))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data.json")
    ap.add_argument("--log", default="email_log.json")
    ap.add_argument("--window", type=int, default=40, help="email games tipping off within this many minutes")
    ap.add_argument("--out", help="write subject/html/text to files with this prefix instead of sending")
    args = ap.parse_args()

    data = json.load(open(args.data))
    sent = json.load(open(args.log)) if os.path.exists(args.log) else {}
    due = due_games(data, dt.datetime.now(ET), args.window, sent)
    if not due:
        print("No games due for an email.")
        return
    games = [g for _, g in due]
    subject, body_html, body_text = build(data, games, games[0]["date"])

    if args.out:
        open(args.out + ".subject.txt", "w").write(subject)
        open(args.out + ".html", "w").write(body_html)
        open(args.out + ".txt", "w").write(body_text)
        print(f"Wrote {args.out}.*  ({len(games)} games)")
        return
    user, pw, to = os.environ.get("SMTP_USER"), os.environ.get("SMTP_PASSWORD"), os.environ.get("EMAIL_TO")
    if not (user and pw and to):
        print("SMTP_USER / SMTP_PASSWORD / EMAIL_TO not set; not sending.")
        return
    msg = EmailMessage()
    msg["Subject"], msg["From"], msg["To"] = subject, user, to
    msg.set_content(body_text)
    msg.add_alternative(body_html, subtype="html")
    with smtplib.SMTP_SSL(os.environ.get("SMTP_HOST", "smtp.gmail.com"), int(os.environ.get("SMTP_PORT", "465"))) as s:
        s.login(user, pw)
        s.send_message(msg)
    now = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    sent.update({k: now for k, _ in due})
    cutoff = (dt.date.today() - dt.timedelta(days=7)).isoformat()
    sent = {k: v for k, v in sent.items() if k[:10] >= cutoff}
    json.dump(sent, open(args.log, "w"), indent=1)
    print(f"Sent: {subject}")


if __name__ == "__main__":
    main()
