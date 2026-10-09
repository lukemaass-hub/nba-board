# Project context (carried over from the claude.ai planning chat, Oct 6 2026)

## Goal
A daily/weekly NBA injury and minutes report for the 2026-27 season. For every game: who is out or questionable,
a likely replacement and minutes increase (from depth charts), projected starters, projected rotation, and last
season's minutes per game. Later: post the report to Slack automatically. Owner works at a sportsbook (Fanatics),
so this feeds betting/trading decisions. Accuracy and honest uncertainty matter more than polish.

## What exists
- index.html: single-file page. Calendar (Oct 2026 to Apr 2027); click a day for a Slack-style report modeled on the
  "IP Trader Bot Starting Pitcher Report" screenshot: time + matchup with team logos, colored status dots, "Next up"
  lines, a "Minutes up" line, projected starters (adjusted for injuries), projected rotation, legend at the bottom.
  "Copy as Slack message" builds the Slack text. Reads data.json; falls back to an embedded Oct 6 snapshot.
- data.json: currently a SEED built from the embedded snapshot. pipeline/update_data.py overwrites it.
- pipeline/update_data.py: pulls schedule (fixturedownload.com JSON, UTC to ET), injuries (CBS, Covers, ESPN JSON,
  X beat writers classified with Claude Haiku), RealGM depth charts, minutes from a published Google Sheet CSV
  (MINUTES_CSV_URL). A failed source keeps its last good data, flagged stale.
- .github/workflows/update-data.yml: runs the pipeline 3x/day, commits data.json. Pages serves the site.
- tests/test_pipeline.py: 8 passing tests, but only against fixtures I wrote, NOT real pages.

## Known status (be honest about this)
- Schedule feed format: verified from a real response.
- CBS, Covers, ESPN parsers: run against live pages on Oct 6 2026 and fixed (Covers used <b> + abbreviated names).
  Tests use the real Covers layout. Questionable/Doubtful/Probable now map to the page's status keys.
- RealGM depth charts: 403 from both here and GitHub Actions; removed. Replaced (Oct 6 2026, user's choice) by
  ESPN depth chart JSON (site.api.espn.com .../teams/{1-30}/depthcharts). ESPN lists players under several
  positions; each bench player is kept at his best-ranked position and the top 5 bench players count as rotation.
- RotoWire (rotowire.com/basketball/nba-lineups.php, robots.txt allows it): expected/confirmed starters for today
  go in data.json "lineups" and replace depth-chart starters on the page; "may not play" entries become RotoWire
  injury records valid for that day only.
- .github/workflows/update-data.yml: added Oct 6 2026 (was missing from the upload).
- X beat writers: needs X API access, ANTHROPIC_API_KEY, and handles in pipeline/beat_writers.json (left empty on
  purpose; do not guess handles).
- Depth charts: embedded set covers only 22 of 30 teams (RealGM page was truncated in the chat). The pipeline run
  should fill all 30. HoopsHype blocks automated access.
- Minutes shifts are a heuristic (changed Oct 6 2026 at the user's request): all vacated minutes (last-season MPG, or
  30/18/6 by tier) go to ONE player, the next healthy player below at the same position (else top bench player at an
  adjacent position). Shown as "Minutes up: Name +N" under each injured player; "Next up" lines were removed.
- Page shows today only (ET); if no games today, the next game day. Calendar removed. Injured player names link to
  the source page with a #:~:text= fragment that jumps to the name.
- Workflow also runs every 10 min, 11 AM-1 AM ET, with --pregame 45: refreshes only if a game tips within 45 min,
  then pipeline/email_report.py --window 25 emails each game once (email_log.json), about 20 min before tip.

- Matchup minutes alerts (Oct 9 2026): pipeline/build_matchup_alerts.py reads the user's NBA_Mins_VS_Teams.xlsx
  (Team_Chart method: each player's avg minutes vs every opponent from Player_vs_Team_Grid; "Avg Mins" = mean of
  those 30). Alert when vs-opponent avg is 5+ min above/below Avg Mins AND 5+ games vs that team (game count from the
  Top100_vs_Opponent sheet, whose averages match the grid exactly) -> pipeline/matchup_alerts.json (top 100 players). Shown on page and in email as "usually plays more/fewer minutes vs X" (no numbers, user's
  choice).
  The xlsx itself is not in the repo; re-run the builder when the user sends a new copy.

## Next steps, in order
1. Run pytest, then the pipeline against the live sites. Fix each parser against the real response and update tests.
2. Serve index.html locally (python -m http.server) and check all 30 teams render with injuries and depth charts.
3. Help set up the GitHub repo, Pages, and Actions secrets (X_BEARER_TOKEN, ANTHROPIC_API_KEY, MINUTES_CSV_URL).
   Never ask the user to paste secrets into chat.
4. Then add the daily Slack post (webhook) using the same text as slackText() in index.html.

## Style preferences
Plain language, no jargon, short answers. The user is not a developer: say exactly where to click.
