"""Who is trading each NBA game, from the daily "IP Trader Schedule" message in #in-play-trading.

Each morning (about 8:30 AM MT) the team's IP Trader Bot posts, e.g.

    *10/20 IP Trader Schedule (Times EST)*
    _*NBA*_ :nba:
    7:00 PM - Philadelphia 76ers @ New York Knicks - <@U09BNHCQD5Z|Evan Finger> Cores / <@U0ACFA2QDFF|Amol Singh> Props
    _*NHL*_ :nhl:
    ...

parse_schedule() turns the NBA part into {(away, home): [{"user", "name", "role"}]}, and email_report.py DMs each
listed trader that game's report (the same one posted to Slack) about 20 minutes before tip.

Needs our own Slack app's bot token (SLACK_BOT_TOKEN secret) with chat:write, im:write and channels:history, and the
app added to #in-play-trading so it can read the schedule. SLACK_DM_MODE (a repository variable) decides what happens:
    off  (default) nothing is sent; the run log only says who WOULD get each game
    test           everything goes to SLACK_TEST_USER only (the owner), marked [TEST] with who it would have gone to
    on             each listed trader gets their game(s)

Try it without Slack:  python pipeline/slack_assign.py --text-file schedule.txt --data data.json
"""
import argparse, datetime as dt, json, os, re, sys, urllib.parse, urllib.request

sys.path.insert(0, os.path.dirname(__file__))
from update_data import ET, TEAMS, all_games  # noqa: E402

SCHEDULE_CHANNEL = "C06U8AW81K2"   # #in-play-trading
OWNER = "U0B5EP4PV3M"              # Luke Maass: test mode sends everything here
GAME = re.compile(r"^\s*(\d{1,2}:\d{2}\s*[AP]M)\s*-\s*(.+?)\s+@\s+(.+?)\s+-\s+(.+?)\s*$", re.I)
HEADER = re.compile(r"^\s*[_*]+\s*([A-Za-z0-9 ]+?)\s*[_*]+")   # _*NBA*_ :nba:   /   *IP Call Lead:*
MENTION = re.compile(r"<@([UW][A-Z0-9]+)(?:\|([^>]*))?>\s*([^<]*)")


def team_code(name):
    n = re.sub(r"[^a-z0-9 ]", "", name.lower()).strip()
    for code, aliases in TEAMS.items():
        if any(n == re.sub(r"[^a-z0-9 ]", "", a.lower()) for a in aliases):
            return code
    for code, aliases in TEAMS.items():     # "LA Clippers", "Portland Trail Blazers": nickname at the end
        if any(n.endswith(" " + a.lower()) for a in aliases[1:] if len(a) > 3):
            return code
    return None


def is_schedule(text, date):
    """The schedule message for this date ("10/20 IP Trader Schedule")."""
    return bool(re.search(rf"\b0?{date.month}/0?{date.day}\b[^\n]*IP Trader Schedule", text or "", re.I))


def parse_schedule(text):
    """NBA games in the schedule text -> {(away_code, home_code): [{"user": id, "name": str, "role": str}]}."""
    out, sport = {}, None
    for line in (text or "").splitlines():
        h = HEADER.match(line)
        if h and not GAME.match(line):
            sport = h.group(1).strip().upper()
            continue
        m = GAME.match(line)
        if sport != "NBA" or not m:
            continue
        away, home = team_code(m.group(2)), team_code(m.group(3))
        if not (away and home):
            print(f"Schedule: could not match teams in: {line.strip()}")
            continue
        people = [{"user": u, "name": (nm or "").strip(), "role": role.strip(" /-")}
                  for u, nm, role in MENTION.findall(m.group(4))]
        out[(away, home)] = people
    return out


def _api(token, method, params=None, body=None):
    url = f"https://slack.com/api/{method}" + (f"?{urllib.parse.urlencode(params)}" if params else "")
    req = urllib.request.Request(url, data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json; charset=utf-8"})
    with urllib.request.urlopen(req, timeout=30) as r:
        res = json.loads(r.read().decode())
    if not res.get("ok"):
        raise RuntimeError(f"Slack {method}: {res.get('error')}")
    return res


def fetch_schedule(token, date, channel=SCHEDULE_CHANNEL):
    """Today's schedule message text from the channel, or None if it isn't posted (yet)."""
    start = dt.datetime.combine(date, dt.time(0), tzinfo=ET)   # midnight Eastern (daylight or winter time)
    res = _api(token, "conversations.history", {"channel": channel, "oldest": f"{start.timestamp() - 6 * 3600:.0f}", "limit": 100})
    for msg in res.get("messages", []):
        if is_schedule(msg.get("text"), date):
            return msg["text"]
    return None


_names = {}


def user_name(token, user):
    """Display name for a Slack user ID (the schedule read through the API has only <@U...>). Needs users:read."""
    if user not in _names:
        try:
            u = _api(token, "users.info", {"user": user})["user"]
            _names[user] = (u.get("profile") or {}).get("real_name") or u.get("real_name") or u.get("name") or user
        except Exception:
            _names[user] = user
    return _names[user]


def dm(token, user, text, blocks):
    """One-on-one message. Note: these land in the bot's Messages tab, which is switched off on IP Trader Bot, so
    people can't see them; group_dm (2+ people) shows up in everyone's normal DMs."""
    _api(token, "chat.postMessage", body={"channel": user, "text": text, "blocks": blocks, "unfurl_links": False})


def group_dm(token, users, text, blocks):
    """Group DM of the bot + these people (like the football reports: "IP Trader Bot, Max Pasley"). Same group every
    time for the same people. Needs mpim:write + chat:write. Falls back to dm() for a single person."""
    users = list(dict.fromkeys(users))
    if len(users) < 2:
        return dm(token, users[0], text, blocks)
    ch = _api(token, "conversations.open", body={"users": ",".join(users)})["channel"]["id"]
    _api(token, "chat.postMessage", body={"channel": ch, "text": text, "blocks": blocks, "unfurl_links": False})


def post_channel(token, channel, text, blocks):
    _api(token, "chat.postMessage", body={"channel": channel, "text": text, "blocks": blocks, "unfurl_links": False})


# People added to every NBA game's group DM on these dates, on top of that game's Props and Cores traders
# (user's request: "for all of the games tonight include me", Oct 26 2026).
ALSO_INCLUDE = {"2026-10-26": [OWNER]}


def mode():
    m = (os.environ.get("SLACK_DM_MODE") or "off").strip().lower()
    return m if m in ("off", "test", "on") else "off"


def plan(people):
    return ", ".join((p["name"] or p["user"]) + (f" ({p['role']})" if p["role"] else "") for p in people) or "no one"


def main():
    ap = argparse.ArgumentParser(description="Show which NBA game goes to whom (no Slack needed).")
    ap.add_argument("--text-file", required=True, help="the schedule message text, copied from Slack")
    ap.add_argument("--data", default="data.json")
    a = ap.parse_args()
    sched = parse_schedule(open(a.text_file).read())
    games = {(g["away"], g["home"]) for g in all_games(json.load(open(a.data)))}
    for (away, home), people in sched.items():
        print(f"{away} @ {home}: {plan(people)}{'' if (away, home) in games else '  (not in data.json schedule)'}")


if __name__ == "__main__":
    main()
