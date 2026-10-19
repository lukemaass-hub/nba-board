# NBA Board: Dolly Expected Minutes (Chrome extension)

Part of the daily NBA email. It is separate from the DraftKings/FanDuel props extension (`prop-compare/`).

**What it does.** While a game's **Rosters** screen is open in **test Dolly** (`dolly.uat.oddsfactorytrading.bet`),
it reads the **Expected Mins.** column about once a minute. It saves the numbers to `expected_minutes.json` in this
repo, at most every 10 minutes. The pipeline copies that file into `data.json`. The pre-game email, Slack and the
board then add a **Dolly expected minutes** line for any player Dolly expects to play **3+ minutes more or less**
than his average. The average is last season's until he has 15 games this season.

**Why it's an extension.** The email is built on GitHub's computers, which can't log in to Dolly. Your Chrome is
already logged in, so this small extension passes the numbers on.

**What it never does.**
- It never clicks, types or changes anything in Dolly; it only reads text on the screen.
- It never runs on prod Dolly (test only for now).
- It sends nothing anywhere except `expected_minutes.json` to this repo.

## Install
1. In Chrome go to `chrome://extensions`, turn on **Developer mode**, click **Load unpacked**, and pick the
   `dolly-minutes/extension` folder.
2. Make a GitHub key that can only edit this repo:
   1. On github.com, click your picture (top right), then **Settings → Developer settings → Personal access tokens →
      Fine-grained tokens → Generate new token**.
   2. Under **Repository access**, choose **Only select repositories → nba-board**.
   3. Under **Permissions → Contents**, choose **Read and write**.
   4. Click **Generate** and copy the key.
3. Click the extension's icon, paste the key, and click **Save**. Don't paste the key anywhere else, and never into
   a chat.
4. Open a game's **Rosters** screen in test Dolly. Within a minute or so, the icon's window shows "players kept" and
   "Last saved to GitHub".

## Daily use
Before games, open each game's **Rosters** screen in test Dolly and leave the tabs open. Each open Rosters screen is
read about once a minute and saved every 10 minutes. The extension never uses your Dolly sign-in to fetch anything
itself (the user's choice); a fully hands-off version would need a data feed from the Dolly team.
