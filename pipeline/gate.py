"""Should this scheduled run do anything? (Oct 27 2026, user: start ~30 minutes before the games, not all day.)
The half-hourly checks (PREGAME_CRONS) only proceed when a game tips within SOON_MIN minutes without its group DM;
the run then stays on until every game today is sent. The morning refresh, the Monday email, pushes and manual runs always proceed.
Writes go=true/false to $GITHUB_OUTPUT. Standard library only, so it runs before anything is installed."""
import datetime as dt, json, os, sys
from zoneinfo import ZoneInfo

PREGAME_CRONS = {"0,30 15-23,0-3 * * *"}   # UTC, every 30 min in game hours
SOON_MIN = 45       # proceed only if a game tips within this many minutes (user: start ~30 min before the games)


def games(data):
    out = [(g["date"], g["time"]) for g in data.get("schedule", [])]
    for team, l in (data.get("lineups") or {}).items():     # games only RotoWire lists (preseason)
        if l.get("home") and l.get("time") and l.get("date"):
            out.append((l["date"], l["time"]))
    return out


def go(data, now, sent=None):
    """A game tipping within SOON_MIN minutes (ET) that has no group DM yet."""
    et = ZoneInfo("America/New_York")
    today = now.astimezone(et).date().isoformat()
    for g in data.get("schedule", []) + [{"date": l["date"], "time": l["time"], "away": l.get("vs"), "home": t}
                                          for t, l in (data.get("lineups") or {}).items() if l.get("home") and l.get("time")]:
        tip = dt.datetime.fromisoformat(f"{g['date']}T{g['time']}").replace(tzinfo=et)
        if now < tip <= now + dt.timedelta(minutes=SOON_MIN) and f"dm {g['date']} {g['away']}@{g['home']}" not in (sent or {}):
            return True
    return False


LEAD_MIN = 30       # the timer starts the real run this long before each tip (user, Oct 27 2026)


def next_start(data, now, sent=None, after=None):
    """Seconds until the timer should start the real run: LEAD_MIN before the next game (ET, today) that has no group
    DM yet and tips after `after` (a datetime, to move past a game already handled); 0 if that moment has passed but
    the game hasn't tipped; -1 if there is nothing left today. Returns (seconds, tip)."""
    et = ZoneInfo("America/New_York")
    today = now.astimezone(et).date().isoformat()
    tips = []
    for g in data.get("schedule", []) + [{"date": l["date"], "time": l["time"], "away": l.get("vs"), "home": t}
                                          for t, l in (data.get("lineups") or {}).items() if l.get("home") and l.get("time")]:
        tip = dt.datetime.fromisoformat(f"{g['date']}T{g['time']}").replace(tzinfo=et)
        if g["date"] == today and now < tip and (after is None or tip > after) \
                and f"dm {g['date']} {g['away']}@{g['home']}" not in (sent or {}):
            tips.append(tip)
    if not tips:
        return -1, None
    tip = min(tips)
    return max(0, int((tip - dt.timedelta(minutes=LEAD_MIN) - now).total_seconds())), tip


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--next-start":     # gate.py --next-start data.json email_log.json [after]
        d = json.load(open(sys.argv[2]))
        sent = json.load(open(sys.argv[3])) if os.path.exists(sys.argv[3]) else {}
        after = dt.datetime.fromisoformat(sys.argv[4]) if len(sys.argv) > 4 and sys.argv[4] else None
        secs, tip = next_start(d, dt.datetime.now(dt.timezone.utc), sent, after)
        print(secs, tip.isoformat() if tip else "")
        sys.exit(0)
    ev, sched = os.environ.get("EVENT", ""), os.environ.get("SCHEDULE", "")
    ok = True
    if ev == "schedule" and sched in PREGAME_CRONS:
        try:
            log = sys.argv[2] if len(sys.argv) > 2 else "email_log.json"
            sent = json.load(open(log)) if os.path.exists(log) else {}
            ok = go(json.load(open(sys.argv[1] if len(sys.argv) > 1 else "data.json")), dt.datetime.now(dt.timezone.utc), sent)
        except Exception as e:          # can't tell: run, to be safe
            print(f"gate: {e}")
    print(f"gate: {'go' if ok else 'no game in the next %d minutes needs its group DM: nothing to do' % SOON_MIN}")
    with open(os.environ.get("GITHUB_OUTPUT", os.devnull), "a") as f:
        f.write(f"go={'true' if ok else 'false'}\n")
