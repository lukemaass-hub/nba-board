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
- X beat writers: X has no free read access (pay per post read, ~$0.005 each, as of 2026); user chose not to pay
  and not to scrape. pipeline/beat_writers.json holds 44 verified handles in case that changes.
- Beat-writer news (Oct 9 2026, user's choice): RotoWire NBA RSS (rotowire.com/rss/news.php?sport=NBA). It only
  returns the latest 5 items, so update_data.py checks it on every 10-minute run (even when no game is close) and
  keeps items for 3 days in data.json "news", tagged with the team from the depth chart. Shown per team (last 36 h)
  on the board, email and Slack as "Beat-writer news" with the writer and outlet. Oct 20 2026 (user): only items about
  injuries, suspensions, minutes/restrictions are shown (news_relevant / newsRelevant); contracts and lineup notes are hidden.
  Oct 26 2026 (user): one item per player, his newest only. Name keys (norm_name / normName) have no spaces, so
  "Nae Qwan" (Covers) and "NaeQwan" (CBS) are the same player.
- News -> status (Oct 9 2026, user's rule): apply_news() reads status words (out / doubtful / questionable /
  will play = probable) and turns them into injury records with "override": a beat writer's status beats CBS/ESPN/
  Covers/RotoWire on the page, email and Slack ("per <writer>"); the newest writer report wins. The day comes from
  the text ("Sunday's game" -> that date only; none named -> posted day + next day; "said Friday" is skipped).
  "Minutes restriction" phrases -> data["restrictions"] -> big red warning at the top of that game everywhere.
- Season minutes (Oct 9 2026): ESPN byathlete stats (regular season) -> data["season_minutes"]: current season
  refreshed every 12 h (morning run picks up last night), last + prior season fetched once. Email/Slack show
  "Name (35)" = this season's MPG (since Oct 26 2026 as soon as he has played), else last season (Oct 19 2026: only this + last season are used, never
  older; ESPN answers an unstarted season with the last one, so that counts as no data). Big change = 5+ min vs the last
  season he played (5+ games now, 10+ then): yellow highlight + "+N min vs 2025-26" badge in the pre-game email,
  and a weekly email (Mondays 9 AM ET, or Run workflow > weekly_email) listing all of them. Nothing until 2026-27
  games are played.
- Board layout: starters & bench are inside a closed "Starters & bench" dropdown; injuries, alerts, news visible.
- Depth charts: embedded set covers only 22 of 30 teams (RealGM page was truncated in the chat). The pipeline run
  should fill all 30. HoopsHype blocks automated access.
- Minutes shifts are a heuristic (changed Oct 6 2026 at the user's request): all vacated minutes (last-season MPG, or
  30/18/6 by tier) go to ONE player, the next healthy player below at the same position (else top bench player at an
  adjacent position). Shown as "Minutes up: Name +N" under each injured player; "Next up" lines were removed.
- Page shows today only (ET); if no games today, the next game day. Calendar removed. Injured player names link to
  the source page with a #:~:text= fragment that jumps to the name.
- Workflow also runs every 10 min, 11 AM-1 AM ET, with --pregame 90 (was 45; widened Oct 21 2026 to catch confirmed
  lineups for the Props DMs): refreshes only if a game tips within 90 min,
  then pipeline/email_report.py --window 25 emails each game once (email_log.json), about 20 min before tip.
  Oct 26 2026: pre-game emails OFF (PREGAME_EMAIL=False; the Slack group DMs replace them). Weekly email still on.

- Matchup minutes alerts (Oct 9 2026): pipeline/build_matchup_alerts.py reads the user's NBA_Mins_VS_Teams.xlsx
  (Team_Chart method: each player's avg minutes vs every opponent from Player_vs_Team_Grid; "Avg Mins" = mean of
  those 30). Alert when vs-opponent avg is 5+ min above/below Avg Mins AND 5+ games vs that team (game count from the
  Top100_vs_Opponent sheet, whose averages match the grid exactly) -> pipeline/matchup_alerts.json (top 100 players). Shown on page and in email as "usually plays more/fewer minutes vs X" (no numbers, user's
  choice).
  The xlsx itself is not in the repo; re-run the builder when the user sends a new copy.
  Oct 26 2026: REMOVED for now at the user's request (MATCHUP_ALERTS=False in email_report.py and index.html); kept for later.

- Slack (Oct 9 2026, TESTING ONLY, user's DMs): pipeline/email_report.py also posts one Block Kit message per game to
  SLACK_WEBHOOK_URL (secret), same layout as the email; tracked in email_log.json as "slack <date> A@H". Workflow
  "Run workflow" has a test_slack checkbox that posts the next game now, marked [TEST]. Don't point it at a shared
  channel until the user says testing is over.
- Trader DMs (Oct 20 2026, built, NOT sending yet): pipeline/slack_assign.py reads the daily "<m/d> IP Trader
  Schedule" message (posted ~8:30 AM MT by the team's existing IP Trader Bot app in #in-play-trading, C06U8AW81K2),
  takes the NBA section ("7:00 PM - A @ B - <@U..|Name> Cores / <@U..|Name> Props") and email_report.dm_traders() DMs
  (Oct 26 2026: one GROUP DM per game with the bot + that game's Props AND Cores traders, like the football reports;
  one-on-one bot DMs are invisible because the bot's Messages tab is off; Oct 27 2026: a game with only ONE listed trader
  gets the owner added so it is a visible group DM) the game's Slack report as soon as both teams' RotoWire lineups are confirmed, else 10 min before tip (user's rule, Oct 26 2026) (Oct 21 2026, user's rule; Cores etc. get nothing; just the report, no extra line) (logged as "dm <date> A@H"). Needs the user's own new
  app (also named IP Trader Bot, App ID A0CALRVPDBM, install awaiting admin approval) with bot scopes chat:write,
  im:write, channels:history, added to #in-play-trading, token in secret SLACK_BOT_TOKEN. Repository variable
  SLACK_DM_MODE: on by default since Oct 26 2026 (user switched it on; variable can set off / test).
  slack_assign.ALSO_INCLUDE adds people to every group DM on a date (the user on Oct 26 2026). The user
  said: don't send anything until approved; turn on test first. The schedule channel lives in workspace T04DVTM1BB6
  (FBG Enterprises Opco); the new app was created in "Fanatics Betting and Gaming" (T030UFQJYEL): it must be
  installed where #in-play-trading is.

- Teammate-minutes backtest (Oct 15 2026, separate from the site; nothing on the site uses it): backtest/.
  fetch_espn.py (ESPN scoreboard + summary box scores, 2024-25 and 2025-26 regular season; NBA cdn/stats block us,
  bref terms forbid bulk download) -> build_dataset.py -> backtest.py -> make_report.py (REPORT.md),
  make_sheet.py (results.xlsx), make_csv.py (one-tab CSV uploaded to the user's Drive as a Google Sheet).
  ESPN omits most inactive players, so "missing while on the team" = inactive (out); an absence counts for its
  first 10 games. Result: simple model ~54% #1-pick hit vs 45% next man up, 38% random; boosted ranker ~56% in
  walk-forward. Main signal: last-3-games trend, then low baseline, then past response when a similar player was out.

## Next steps, in order
1. Run pytest, then the pipeline against the live sites. Fix each parser against the real response and update tests.
2. Serve index.html locally (python -m http.server) and check all 30 teams render with injuries and depth charts.
3. Help set up the GitHub repo, Pages, and Actions secrets (X_BEARER_TOKEN, ANTHROPIC_API_KEY, MINUTES_CSV_URL).
   Never ask the user to paste secrets into chat.
4. Then add the daily Slack post (webhook) using the same text as slackText() in index.html.

## Style preferences
Plain language, no jargon, short answers. The user is not a developer: say exactly where to click.

- Unattended safety (Oct 26-27 2026, user: run without them; only before games; always send before tip, never after;
  Oct 27: "a couple of runs before each slate", not every 5 min): crons = 7 AM ET refresh, a quick check every 30 min
  ("0,30 15-23,0-3 * * *" UTC), Monday email. The "gate" job (pipeline/gate.py) lets a check proceed only if a game
  tips within 45 min without its group DM (reads email_log.json; user: start ~30 min before the games). That run then STAYS ON (watch
  step, up to 5 h, job timeout 330): email_report.py --next-wait says how long to sleep (until 30 min before the next
  tip, 30 min at a time; every 3 min inside that), then refresh (update_data --pregame 90) + send + save (commit
  email_log.json after every check, so a stopped run never causes a repeat), until every game today is sent.
  Oct 27 2026, user: "make sure it goes 30 mins before" -> .github/workflows/pregame-timer.yml: starts 8 AM ET, reads
  today's tips (gate.py --next-start), SLEEPS until 30 min before each game and starts update-data.yml (workflow_dispatch,
  GITHUB_TOKEN with actions: write), then waits for the next game; hands over to a fresh copy of itself before the
  6-hour job limit. Doesn't depend on GitHub's cron punctuality. The half-hourly checks remain as a backup.
  Group DMs: lineups confirmed, else 10 min before tip, never after tip. Steps are continue-on-error; the owner gets an
  email if a step fails (once an hour) or a game tips without its group DM. The RotoWire news RSS is now read only
  around games and in the morning, so some news items can be missed.
- Presser Wire (Oct 26 2026, user's choice; the user's company OK'd the use): update_data.fetch_presserwire reads two
  pages, at most every 15 min (their terms: no wholesale copying or bulk scraping): presserwire.com/nba/injury-report.html
  = the NBA's OFFICIAL injury report -> injury records src "NBA report" with override (newest override wins vs beat
  writers) and a new status "avail" = Available (✅); and /nba/availability.html + the report's attached quotes ->
  data["presserwire"]["notes"], shown per team (36 h, injury/minutes only via news_relevant) as "Press conferences".
- Minutes per game (Oct 26 2026, user: most up to date): this season's MPG as soon as a player has played (CUR_MIN_GAMES
  = 1, board too); last season's only when he hasn't, labelled "(7.9 MPG, 2025-26)". Season minutes refresh every 2 h.
- Bot token (Oct 26 2026): the user was given the team's EXISTING IP Trader Bot token (app A0B2GVBAAF6, bot
  B0B37B4MR5M, workspace T030UFQJYEL, scopes incl. chat:write, mpim:write, channels:history, users:read); it can read
  #in-play-trading. The user pasted it in chat; it belongs only in the SLACK_BOT_TOKEN secret, never in a file.
  SLACK_TEST_CHANNEL (repo variable, optional): where test-mode posts go so they are visible.
- Slack report (Oct 27 2026, user): injury lines show no source names; each player out / doubtful gets his replacement
  (replacements_for: next healthy player below him at his depth-chart position) as "→ ⬆️ Name steps in", and the
  replacement is marked "⬆️ in for X" in starters / bench. Beat-writer news lists MINUTES news only (NEWS_MINUTES:
  restrictions, limits, more / fewer minutes), board too; status news still sets statuses.
- Back-to-back warning (Oct 26 2026, user's rule): when a team plays the 1st or 2nd game of games on consecutive
  days (ET, from the schedule), a yellow "🔁 BACK-TO-BACK: <team> · 2nd game of a back-to-back: played @ NYK last night"
  (or "1st game ...: vs MIA tomorrow 7:30 PM ET") line sits at the top of that game in the email, Slack and board
  (email_report.back_to_back / b2bHTML).
- Oct 26 2026: Dolly expected minutes taken out of the email, Slack and board too (EXPECTED_ENABLED=False in
  email_report.py; update_data.py only loads expected_minutes.json if DOLLY_EXPECTED_MINUTES=on). Kept for later.
- Oct 22 2026: DOLLY DISCONNECTED at the user's request (Dolly was lagging). dolly-minutes 1.2.0 has no Dolly host
  permission or content script; prop-compare 0.23.0 has no Dolly permission and DOLLY_DISABLED=true (no Ours columns).
  The user turned both off in Chrome. Don't reconnect anything to Dolly unless the user asks; if they do, make it lighter
  first (dolly-minutes checked document.body.textContent on every Dolly page every 60 s).
- Dolly expected minutes (Oct 19 2026, UAT for now; prod later): its OWN extension, dolly-minutes/ (kept separate
  from the prop-compare DK/FD props extension, user's choice), reads "Expected Mins." off Dolly's Rosters screen
  (text only) and saves expected_minutes.json to the repo with the user's own fine-grained GitHub key (this repo
  only, typed into the extension's popup). update_data.py copies it into
  data.json; email/Slack/board show "Dolly expected minutes" when 3+ above/below the average (last season until 15
  games this season). Oct 19 2026, user chose option A: the user opens each game's Rosters screen; the extension does
  NOT use the Dolly sign-in token to fetch anything (Dolly's API needs a bearer token; capture removed).
  email_report.py re-reads expected_minutes.json at send time when it is newer than data.json's copy (fresh_expected_minutes). A fully
  unattended version would need a feed from the Dolly team.

