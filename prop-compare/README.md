# Prop Price Compare (DraftKings / FanDuel / Ours)

A Chrome extension, separate from the injury board. Pick an NBA game and press **Start**. Every 15 seconds it
pulls player points and alternate points ("20+ points") from DraftKings and FanDuel, lines the prices up, and
shows a table and a live graph. Everything it pulls is saved, and you can export it to CSV or a Google Sheet.


## How the prices are lined up

- Both books are asked at the same moment, once every 15 seconds. Each of those is one **pull**.
- A pull is **aligned** when both books answered within 2 seconds of each other (you can change this in Settings).
- If a book answers late or fails, it is left **blank for that pull**. A price is never compared with a price
  from a different pull.
- Each line is turned into the **chance of the over**:
  - When the book offers both over and under, the vig is removed.
  - For one-sided "N+" lines, it is the plain implied chance.
  - **Gap** = DraftKings % minus FanDuel %, in percentage points.
  - A gap is only shown when both books price the line the same way.

## Install (about 2 minutes)

1. Download and unzip `prop-compare-extension.zip`.
2. In Chrome, go to `chrome://extensions`.
3. Turn on **Developer mode** (top right).
4. Click **Load unpacked** and pick the unzipped `extension` folder.
5. Pin the extension (puzzle-piece icon → pin), then click its icon. The dashboard opens in a new tab.

## Use

1. Pick a game.
   - "(DK + FD)" means both books have it.
   - "(FD only)" means DraftKings wasn't found yet. See the next section.
2. Press **Start**.
   - Leave the tab open. It keeps pulling in the background.
   - Closing the tab stops it.
3. Click any row to graph it. Hover over the graph to see the exact prices at each pull.
4. Use **Export CSV** for a spreadsheet file, or **Send to Google Sheet** (setup below).

Notes:
- Preseason: FanDuel has no player props (checked Oct 16 in 5 states), but DraftKings does. The table then shows
  DraftKings' lines alone.
- Lines for games several days out are thin (only a few stars). The full board appears closer to tip.

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

## Our prices: from the Dolly screen

Our prices are read off the **Dolly Market Manager** screen, the same way the In-Play Trading Guard reads Dolly.
It finds the **Selection**, **Trading** and **OF** column headers by their text and reads the numbers under them.
It makes no data requests, uses no logins, and never clicks or types anything.

- **Trading** shows as "Ours" (green line). **OF** (Odds Factory) shows as "OF" (yellow line).
- The gaps are ours (Trading) minus DraftKings and minus FanDuel.

To use it:
1. Open the game's **Market Manager** in Dolly. If Dolly was already open when you installed or updated the
   extension, reload it once.
2. **Expand the player-points markets.** As with the Trading Guard, Dolly doesn't show the rows of a collapsed
   market, so they can't be read.
3. Keep Dolly in **its own window**, not a hidden tab, so its prices keep updating.
4. On the dashboard, pick the game and press **Start**.

If our prices stay blank, open **Diagnostics**. Under "Our prices (Dolly screen)" it lists each market it saw
and its first rows. Send me a screenshot.

## Google Sheet (optional)

1. Make a new Google Sheet → **Extensions → Apps Script**.
2. Replace the code with `extension/apps-script/prop-compare-handler.gs` and save.
3. Click **Deploy → New deployment → Web app**:
   - **Execute as:** Me
   - **Who has access:** Anyone within betfanatics.com
4. Copy the URL that ends in `/exec`.
5. Open that URL once in Chrome and click **Allow** if asked. It should show `{"ok":true,...}`.
6. On the dashboard, go to **Settings** and paste the URL into "Google Sheet web app URL", then save.

Each game gets its own tab in the sheet. **Send to Google Sheet** only sends pulls that weren't sent before. Tick
"Send every pull automatically" to have it add rows live.

## Columns (CSV and Sheet), one row per line per pull

| Column | Meaning |
|---|---|
| tick_time_et / tick_time_utc / tick_id | When the pull started, and its number |
| aligned | yes = both books answered within the limit |
| spread_ms | How far apart the two books answered |
| game, player, market, line | e.g. "Points O/U 24.5" (line 24.5) or "25+ points" (line 24.5) |
| dk_over, dk_under, fd_over, fd_under | American odds. Blank = not offered, or that book was late or failed on this pull |
| dk_over_prob, fd_over_prob | Chance of the over, % |
| dk_fetched_utc, fd_fetched_utc | When each book's answer arrived |
| prob_kind | "no-vig" (both sides) or "implied (one-sided)" |
| gap_pts_dk_minus_fd | DK % minus FD %, in percentage points |

## How much traffic this sends

Each pull is 1 request to FanDuel and 1 request per DraftKings ID. That is about 8–12 requests a minute for one
game, far below what the MLB suite sends. After an error, the book is paused for 5 seconds, doubling up to
5 minutes.

## For developers

- Tests (parsers on real FanDuel responses, alignment, export): `node --test prop-compare/tests/*.test.mjs`
- Code:
  - `extension/lib/books.js`: DK/FD requests and parsing. Request handling is ported from the MLB suite's
    `background/book-api.js`.
  - `lib/compare.js`: alignment, no-vig, rows, CSV.
  - `lib/match.js`: player and team name matching.
  - `lib/chart.js`: the graph.
  - `lib/store.js`: saved pulls (IndexedDB).
  - `lib/ticker.js`: the 15-second timer. It runs in a worker so a background tab doesn't slow it down.
  - `dashboard.*`: the page.
- `rules/book-api-headers.json` makes requests look like they come from the books' own sites. It is the same file
  as in the MLB suite. Without it, DraftKings returns 403 and FanDuel returns 500.
- `tests/fixtures/dk_points_synthetic.json` is made up, in DraftKings' format. Replace it with a real response
  once DraftKings is checked in a browser.
