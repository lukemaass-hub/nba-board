# NBA availability board

`index.html` is the board. `data.json` is what it reads. `pipeline/update_data.py` rewrites `data.json` on a schedule
(GitHub Actions workflow in `.github/workflows/update-data.yml`), so nobody pastes anything day to day.

## One-time setup
1. Put this folder in a GitHub repo and turn on GitHub Pages for the main branch (or host `index.html` + `data.json`
   on any static host; the page must be served from a URL, not opened as a local file, so it can read `data.json`).
2. Actions > "Update availability data" > Run workflow. Open the run log: it prints one status line per source.
3. Optional secrets (Settings > Secrets and variables > Actions):
   - `MINUTES_CSV_URL`: in Google Sheets use File > Share > Publish to web > CSV for the minutes tab, paste that URL.
   - `X_BEARER_TOKEN` and `ANTHROPIC_API_KEY`: turns on beat writers. Also fill in `pipeline/beat_writers.json`.

## What each source needs
| Source | Needs | Status |
|---|---|---|
| Schedule (fixturedownload.com) | nothing | checked live Oct 6 2026: 1,200 games (7 "To be announced" Cup slots skipped) |
| CBS | nothing | checked live Oct 6 2026: 81 players, 27 teams |
| Covers | nothing | checked live Oct 6 2026: 21 players; parser fixed for the real page |
| ESPN | nothing | checked live Oct 6 2026: 89 players, 27 teams |
| RealGM depth charts | nothing | RealGM refused the request (403) from our test machine; may or may not work from GitHub. Until it works, the board keeps the 22 teams already in data.json |
| Minutes sheet | published CSV link | untested until you add the link |
| Beat writers on X | X API access, Anthropic key, handle list | untested until you add keys and handles |

If a source breaks, the run keeps that source's last good data, marks it stale on the page, and shows "failed" in the
freshness line at the top. Run `pytest tests` to check the parsers after changing them.
