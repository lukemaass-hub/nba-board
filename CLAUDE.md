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
- CBS, Covers, RealGM parsers: written from page structure seen as markdown; never run against live HTML.
- ESPN: public JSON endpoint (site.api.espn.com/apis/site/v2/sports/basketball/nba/injuries); shape assumed.
- X beat writers: needs X API access, ANTHROPIC_API_KEY, and handles in pipeline/beat_writers.json (left empty on
  purpose; do not guess handles).
- Depth charts: embedded set covers only 22 of 30 teams (RealGM page was truncated in the chat). The pipeline run
  should fill all 30. HoopsHype blocks automated access.
- Minutes shifts are a heuristic: vacated minutes = last-season MPG (or 30/18/6 by tier) split 40/20 to the next two
  at the same position and 20/20 to bench players at adjacent positions; doubtful counts 80%, questionable 50%.

## Next steps, in order
1. Run pytest, then the pipeline against the live sites. Fix each parser against the real response and update tests.
2. Serve index.html locally (python -m http.server) and check all 30 teams render with injuries and depth charts.
3. Help set up the GitHub repo, Pages, and Actions secrets (X_BEARER_TOKEN, ANTHROPIC_API_KEY, MINUTES_CSV_URL).
   Never ask the user to paste secrets into chat.
4. Then add the daily Slack post (webhook) using the same text as slackText() in index.html.

## Style preferences
Plain language, no jargon, short answers. The user is not a developer: say exactly where to click.
