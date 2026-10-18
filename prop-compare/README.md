# Prop Price Compare (DraftKings / FanDuel / Ours)

Shows **odds only**: the American odds each book shows customers. No chance-of-over lines.

A Chrome extension, separate from the injury board. Pick an NBA game and press **Start**. Every 15 seconds it
pulls player points and alternate points ("20+ points") from DraftKings and FanDuel, lines the prices up, and
shows a table and a live graph. Everything it pulls is saved, and you can export it to CSV or a Google Sheet.


## How the prices are lined up

- DraftKings, FanDuel and our test Dolly screen are all asked at the same moment, once every 15 seconds. Each of
  those is one **pull**.
- A pull is **aligned** when every source answered within 2 seconds of the first one (you can change this in
  Settings).
- If a source answers late or fails, it is left **blank for that pull**. Odds are never compared with odds from a
  different pull.
- The table and graph show **American odds** as customers see them. The graph plots the over odds over time.
- "Biggest difference" sorts by how far our over odds are from DraftKings' or FanDuel's.

## Install (about 2 minutes)

1. Download and unzip `prop-compare-extension.zip`.
2. In Chrome, go to `chrome://extensions`.
3. Turn on **Developer mode** (top right).
4. Click **Load unpacked** and pick the unzipped `extension` folder.
5. Pin the extension (puzzle-piece icon → pin), then click its icon. The dashboard opens in a new tab.

## Use

1. Pick the **Day**. It opens on today. Then pick a **Game**. All times are Mountain Time.
2. Press **Start**. Leave the tab open; it keeps pulling in the background. Closing the tab stops it.
3. The table is sorted by player, then line from lowest up. **Sort → Biggest difference** puts the lines where our
   odds differ most from DraftKings/FanDuel first.
4. The **team buttons** (All / away / home) show one team's players. Teams come from ESPN's public rosters.
5. Click any row to graph its over odds. Hover over the graph for the exact odds at each pull.
6. When a line comes down (e.g. a player hits it and Dolly or a book pulls it), the row stays with its last odds,
   greyed, marked "(off 3:49 PM)". Its graph and every saved pull are kept.

## DraftKings: let the extension learn its IDs (once)

DraftKings blocks cloud servers, so its ID numbers could not be checked while this was built. The extension
learns them from your browser instead. It only watches which addresses DraftKings' own page asks for; it doesn't
change or block anything.

1. Keep the dashboard open.
2. In another tab, open sportsbook.draftkings.com → NBA → a game → **Player Points** tab.
   - Click the **Points** and **Points Milestones** sub-tabs if you see them.
3. Go back to the dashboard. Within a few seconds the game list reloads, and DraftKings games show "(DK + FD)" or
   "(DK only)".
4. Pick the game and press **Start**.

If the DraftKings light stays red, open **Diagnostics** and send me a screenshot. It lists what was learned and the
last DraftKings requests it saw.

Settings still has the DraftKings IDs as a backup. The ones learned from your browser are used first.

## Our prices: from the Dolly screen (App column)

Our prices are the **App** odds (what the app shows customers), read off the Dolly Market Manager screen.

**Which Dolly:** Settings → **Dolly environment**.
- **Test (UAT)** is the default (`dolly.uat.oddsfactorytrading.bet`). While Test is selected, the extension has
  **no permission for prod Dolly** and loads **nothing** into prod pages.
- **Prod**: pick it and click **Save settings**. Chrome asks you to allow `dolly.1.oddsfactorytrading.com`; say
  Allow, then reload the prod Dolly tab once. The header turns red and says PROD so it can't be mistaken for test.
- Going back to Test removes the prod permission again.

- It only reads text. It never clicks, types, changes or sends anything, and it doesn't measure the page
  (measuring is what froze Dolly in earlier versions).
- It reads only when the dashboard asks, once per pull.

To use it:
1. Open the game's **Market Manager** in test Dolly. If it was already open when you installed or updated the
   extension, reload it once.
2. **Expand ALTERNATE PLAYER POINTS** (and PLAYER TOTAL POINTS for over/unders). Dolly doesn't show the rows of a
   collapsed market.
3. Keep Dolly in **its own window**, not a hidden tab, so its prices keep updating.
4. On the dashboard, pick the game and press **Start**.

If our odds stay blank, open **Diagnostics**. Under "Our prices" it shows how many rows it saw, how many App prices
it read, and examples. Send me a screenshot.

## Anomalies tab

Lists every time our odds were far from the market. Each side (over / under) is checked on every pull, using only
odds pulled at the same moment. It compares the chance each price implies. A side is flagged when:

- our odds are **10%+ off the average of DraftKings and FanDuel**, or
- our odds are **20%+ off DraftKings or FanDuel on its own**. This also catches lines only one book offers.

Both numbers can be changed in Settings. **15%+ off** is marked large in red.

**Every pull adds a new row** for each line that is off, newest first. Each row shows:
- the time of that pull (MT, to the second);
- the player and team;
- the line (over/under lines say Over or Under);
- which rule fired;
- that pull's odds for ours, DK and FD, and the DK/FD average;
- % off the average, off DK and off FD.

A line that stays off for 10 pulls gets 10 rows. The screen shows the newest 500; the CSV has all of them.

**Red** = 15%+ off; **white** = flagged but under 15%.

Click a row to graph that line. **Export anomalies CSV** downloads the list. Anomalies are saved with the game,
so they're still there after lines come down or the dashboard is closed.

## Export

- **Export CSV** downloads every pull of the selected game as a file.
- **New Google Sheet** copies every pull of the game, then opens a brand-new blank Google Sheet in your account.
  Click cell A1 and press **Ctrl+V**. There's nothing to set up.
  (Making the sheet with no paste at all would need a Google sign-in app registered for the extension.)

## Columns (CSV and Sheet), one row per line per pull

| Column | Meaning |
|---|---|
| tick_time_mt / tick_time_utc / tick_id | When the pull started (Mountain Time / UTC), and its number |
| aligned | yes = every source answered within the limit |
| spread_ms | How far apart the sources answered |
| game, team, player, market, line | e.g. "Points O/U 24.5" (line 24.5) or "25+ points" (line 24.5) |
| dk_over, dk_under, fd_over, fd_under, ours_over, ours_under | American odds. Blank = not offered, or that source was late or failed on this pull |
| dk_fetched_utc, fd_fetched_utc, ours_fetched_utc | When each source's answer arrived |

## How much traffic this sends

Each pull is 1 request to FanDuel and 1 request per DraftKings ID. That is about 8–12 requests a minute for one
game, far below what the MLB suite sends. After an error, the book is paused for 5 seconds, doubling up to
5 minutes.

## For developers

- Tests (parsers on real FanDuel responses, alignment, export): `node --test prop-compare/tests/*.test.mjs`
- Code:
  - `extension/lib/books.js`: DK/FD requests and parsing. Request handling is ported from the MLB suite's
    `background/book-api.js`.
  - `lib/compare.js`: alignment, rows, CSV.
  - `content/dolly-props.js`: reads the App odds off the test Dolly Market Manager (text only).
  - `lib/match.js`: player and team name matching.
  - `lib/chart.js`: the graph.
  - `lib/store.js`: saved pulls (IndexedDB).
  - `lib/ticker.js`: the 15-second timer. It runs in a worker so a background tab doesn't slow it down.
  - `dashboard.*`: the page.
- `rules/book-api-headers.json` makes requests look like they come from the books' own sites. It is the same file
  as in the MLB suite. Without it, DraftKings returns 403 and FanDuel returns 500.
- `tests/fixtures/dk_points_synthetic.json` is made up, in DraftKings' format. Replace it with a real response
  once DraftKings is checked in a browser.
