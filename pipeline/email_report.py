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


def build(data, games, date):
    e = html.escape
    title = f"NBA injury report: " + ", ".join(f"{g['away']} @ {g['home']} {fmt_time(g['time'])}" for g in games)
    h = [f'<div style="font-family:Arial,sans-serif;font-size:14px;color:#1d1c1d;max-width:680px">'
         f'<h2 style="margin:0 0 4px">Injury report, {e(dt.date.fromisoformat(date).strftime("%A, %B %-d"))}</h2>'
         f'<div style="color:#666;font-size:12px;margin-bottom:12px">Data refreshed {e(data.get("generated_at", "?"))} UTC. '
         f'<a href="{SITE}">Open the full board</a></div>']
    t = [title, ""]
    for g in games:
        h.append(f'<h3 style="margin:16px 0 4px;border-top:1px solid #ddd;padding-top:10px">{fmt_time(g["time"])} ET: '
                 f'{e(name(g["away"]))} @ {e(name(g["home"]))}</h3>')
        t.append(f"{fmt_time(g['time'])} ET: {name(g['away'])} @ {name(g['home'])}")
        for team in (g["away"], g["home"]):
            inj = injuries_for(data, team, date)
            h.append(f'<div style="font-weight:bold;margin:10px 0 4px">{e(name(team))}</div>')
            t.append(f"  {name(team)}")
            if not inj:
                h.append('<div>✅ No injuries listed</div>')
                t.append("    No injuries listed")
            for i in inj:
                who = f'<a href="{e(i["link"])}" style="color:#1d1c1d">{e(i["player"])}</a>' if i["link"] else e(i["player"])
                srcs = ", ".join(f'<a href="{e(s["url"])}" style="color:#888">{e(s["src"])}</a>' if s["url"] else e(s["src"])
                                 for s in i["srcs"])
                h.append(f'<div style="margin:2px 0">{DOT[i["st"]]} <b>{who}</b>: {LABEL[i["st"]]}'
                         f'{" · " + e(i["injury"]) if i["injury"] else ""} <span style="color:#888;font-size:12px">{srcs}'
                         f'{" · sources differ" if i["differ"] else ""}</span></div>')
                t.append(f"    {DOT[i['st']]} {i['player']}: {LABEL[i['st']]}{' | ' + i['injury'] if i['injury'] else ''}"
                         f" ({', '.join(s['src'] for s in i['srcs'])})")
            label, rows = starters_for(data, team, date, inj)
            if rows:
                h.append(f'<div style="color:#666;font-size:12px;margin-top:6px">{e(label)}</div><div>'
                         + " · ".join(f'<span style="color:#888">{e(p)}</span> {e(n)}{f" <i style=color:#2a7>({e(why)})</i>" if why else ""}'
                                      for p, n, why in rows) + "</div>")
                t.append(f"    {label}: " + ", ".join(f"{p} {n}{f' ({why})' if why else ''}" for p, n, why in rows))
        t.append("")
    h.append('<div style="color:#888;font-size:12px;margin-top:16px;border-top:1px solid #ddd;padding-top:8px">'
             '🔴 Out · 🟠 Doubtful · 🟡 Questionable · 🟢 Probable. Click a player for the source.</div></div>')
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
