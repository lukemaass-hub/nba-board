"""Should this scheduled run do anything? (Oct 27 2026, user: run a couple of times before each slate, not every 5 min.)
The slate starts (PREGAME_CRONS) only proceed when a game today has not tipped and has no group DM yet; the run then
stays on until the whole slate is sent. The morning refresh, the Monday email, pushes and manual runs always proceed.
Writes go=true/false to $GITHUB_OUTPUT. Standard library only, so it runs before anything is installed."""
import datetime as dt, json, os, sys
from zoneinfo import ZoneInfo

PREGAME_CRONS = {"30 15 * * *", "30 18 * * *", "30 21 * * *", "30 22 * * *"}   # UTC; the last one is a backup


def games(data):
    out = [(g["date"], g["time"]) for g in data.get("schedule", [])]
    for team, l in (data.get("lineups") or {}).items():     # games only RotoWire lists (preseason)
        if l.get("home") and l.get("time") and l.get("date"):
            out.append((l["date"], l["time"]))
    return out


def go(data, now, sent=None):
    """A game today (ET) that hasn't tipped and has no group DM yet."""
    et = ZoneInfo("America/New_York")
    today = now.astimezone(et).date().isoformat()
    for g in data.get("schedule", []) + [{"date": l["date"], "time": l["time"], "away": l.get("vs"), "home": t}
                                          for t, l in (data.get("lineups") or {}).items() if l.get("home") and l.get("time")]:
        tip = dt.datetime.fromisoformat(f"{g['date']}T{g['time']}").replace(tzinfo=et)
        if g["date"] == today and now < tip and f"dm {g['date']} {g['away']}@{g['home']}" not in (sent or {}):
            return True
    return False


if __name__ == "__main__":
    ev, sched = os.environ.get("EVENT", ""), os.environ.get("SCHEDULE", "")
    ok = True
    if ev == "schedule" and sched in PREGAME_CRONS:
        try:
            log = sys.argv[2] if len(sys.argv) > 2 else "email_log.json"
            sent = json.load(open(log)) if os.path.exists(log) else {}
            ok = go(json.load(open(sys.argv[1] if len(sys.argv) > 1 else "data.json")), dt.datetime.now(dt.timezone.utc), sent)
        except Exception as e:          # can't tell: run, to be safe
            print(f"gate: {e}")
    print(f"gate: {'go' if ok else 'every game today is sent or has tipped: nothing to do'}")
    with open(os.environ.get("GITHUB_OUTPUT", os.devnull), "a") as f:
        f.write(f"go={'true' if ok else 'false'}\n")
