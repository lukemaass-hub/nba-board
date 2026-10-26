"""Should this scheduled run do anything? (Oct 26 2026, user: only check before games, not all day.)
The every-5-minute schedule only proceeds when a game tips within the next WINDOW_MIN minutes (ET); the three daily
refreshes, the Monday email, pushes and manual runs always proceed. Writes go=true/false to $GITHUB_OUTPUT.
Standard library only, so it runs before anything is installed."""
import datetime as dt, json, os, sys
from zoneinfo import ZoneInfo

WINDOW_MIN = 90
AFTER_MIN = 15      # a few minutes after tip too, only so a game that tipped unsent triggers the owner's alert email
PREGAME_CRON = "*/5 14-23,0-3 * * *"


def games(data):
    out = [(g["date"], g["time"]) for g in data.get("schedule", [])]
    for team, l in (data.get("lineups") or {}).items():     # games only RotoWire lists (preseason)
        if l.get("home") and l.get("time") and l.get("date"):
            out.append((l["date"], l["time"]))
    return out


def go(data, now):
    et = ZoneInfo("America/New_York")
    for d, t in games(data):
        tip = dt.datetime.fromisoformat(f"{d}T{t}").replace(tzinfo=et)
        if now - dt.timedelta(minutes=AFTER_MIN) <= tip <= now + dt.timedelta(minutes=WINDOW_MIN):
            return True
    return False


if __name__ == "__main__":
    ev, sched = os.environ.get("EVENT", ""), os.environ.get("SCHEDULE", "")
    ok = True
    if ev == "schedule" and sched == PREGAME_CRON:
        try:
            ok = go(json.load(open(sys.argv[1] if len(sys.argv) > 1 else "data.json")), dt.datetime.now(dt.timezone.utc))
        except Exception as e:          # can't tell: run, to be safe
            print(f"gate: {e}")
    print(f"gate: {'go' if ok else 'no game within %d min, nothing to do' % WINDOW_MIN}")
    with open(os.environ.get("GITHUB_OUTPUT", os.devnull), "a") as f:
        f.write(f"go={'true' if ok else 'false'}\n")
