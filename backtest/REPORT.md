# Who gains minutes when a teammate is out: backtest report

Ranking only: for each game where a rotation player (15+ minute baseline) is out, rank his healthy teammates by how likely they are to play 2+ minutes more than their baseline (average of their previous 10 games).

## Bottom line

- Both models beat every simple rule in all three tests. Tested on 2025-26 after training on 2024-25, the #1 pick gained 2+ minutes 54.2% of the time (boosted ranker) and 54.1% (simple model), against 44.6% for next man up at the same position, 32.7% for the highest-minutes teammate and 38.4% for a random pick.
- Re-trained month by month through 2025-26, the boosted ranker's #1 pick was right 56.3% of the time; its top 3 averaged 48.4% gainers and its ranking correlated 0.24 with the real changes (next man up: 0.05).
- The simple model is nearly as good as the boosted ranker and is easier to explain, so it is the one to start with.
- The strongest signal is a player whose minutes were already rising in his last 3 games. Next: lower usual minutes (a bench player clears +2 more easily than a 34-minute starter), and how he did the last times a similar teammate was out. Playing the same position as the missing player adds little once those are known.
- Highest-minutes teammate is worse than random: stars are already near their ceiling.

## Limits

- ESPN leaves most inactive players out of its box scores, so a player missing from a game while on the team counts as inactive (out). ESPN does not say why for those; rare non-injury absences (personal, G League) can slip in.
- An absence only counts for its first 10 games; after that his teammates' 10-game baselines already include it.
- 245 players who played for two teams were dropped, as asked; that removes many rotation players from trade-deadline teams.
- ESPN minutes are whole numbers.
- The most common miss is a #1 pick who doesn't play at all (coach's decision), often late in the season.

## Data

- 2,460 regular-season games (2024-25 and 2025-26) from ESPN box scores; 701 players.
- Dropped 245 players who played for more than one team; 456 kept.
- Player-games by status: played 33,377, missing from box score while on the team (out) 20,533, DNP coach's decision (not out) 5,007, DNP injury/illness/rest (out) 1,555, DNP personal/suspension/other (not out) 84.
- Test units (team-games with a rotation player out): 3,043 (2024-25: 1,388, 2025-26: 1,655); 21,810 teammate rankings scored.
- Share of healthy teammates who gained 2+ minutes: 37.9%. That is what a random pick gets.

## Train 2024-25, test 2025-26

| Method | #1 pick is a gainer | Top 3 precision | Rank correlation |
|---|---|---|---|
| Random | 38.4% | 38.4% | 0.000 |
| Highest usual minutes | 32.7% | 38.3% | 0.061 |
| Next man up (same position) | 44.6% | 41.1% | 0.051 |
| Simple model | 54.1% | 46.7% | 0.222 |
| Boosted ranker | 54.2% | 47.6% | 0.227 |

- **Simple model vs Next man up (same position):** #1 pick +6.6 to +12.3 points, top 3 +4.2 to +7.0 points, rank correlation +0.147 to +0.197 (95% range; if it doesn't cross 0, the gap is real)
- **Boosted ranker vs Next man up (same position):** #1 pick +6.9 to +12.4 points, top 3 +5.2 to +7.9 points, rank correlation +0.152 to +0.199 (95% range; if it doesn't cross 0, the gap is real)

## Train 2025-26, test 2024-25

| Method | #1 pick is a gainer | Top 3 precision | Rank correlation |
|---|---|---|---|
| Random | 40.0% | 40.0% | 0.000 |
| Highest usual minutes | 33.4% | 40.0% | 0.033 |
| Next man up (same position) | 47.3% | 42.5% | 0.046 |
| Simple model | 53.7% | 48.0% | 0.225 |
| Boosted ranker | 54.8% | 48.2% | 0.227 |

- **Simple model vs Next man up (same position):** #1 pick +3.5 to +9.4 points, top 3 +4.1 to +6.8 points, rank correlation +0.148 to +0.208 (95% range; if it doesn't cross 0, the gap is real)
- **Boosted ranker vs Next man up (same position):** #1 pick +4.6 to +10.5 points, top 3 +4.4 to +6.9 points, rank correlation +0.150 to +0.208 (95% range; if it doesn't cross 0, the gap is real)

## Walk-forward through 2025-26 (re-trained each month on everything before it)

| Method | #1 pick is a gainer | Top 3 precision | Rank correlation |
|---|---|---|---|
| Random | 38.4% | 38.4% | 0.000 |
| Highest usual minutes | 32.7% | 38.3% | 0.061 |
| Next man up (same position) | 44.6% | 41.1% | 0.051 |
| Simple model | 53.9% | 46.9% | 0.224 |
| Boosted ranker | 56.3% | 48.4% | 0.239 |

| Month | Highest usual minutes | Next man up (same position) | Simple model | Boosted ranker |
|---|---|---|---|---|
| 2025-10 | 33.7% | 31.6% | 52.0% | 45.9% |
| 2025-11 | 37.7% | 45.6% | 56.1% | 56.7% |
| 2025-12 | 29.9% | 41.3% | 53.8% | 53.8% |
| 2026-01 | 30.6% | 46.1% | 55.2% | 60.6% |
| 2026-02 | 25.7% | 46.8% | 56.8% | 58.6% |
| 2026-03 | 35.0% | 43.8% | 48.3% | 52.9% |
| 2026-04 | 37.8% | 53.5% | 56.7% | 63.0% |

_(#1 pick is a gainer, by month)_

## What the models look at

**Simple model** (weights on a common scale; + means more likely to gain):

- his last 3 games vs his usual: +0.38
- his spot in the bench order: -0.23
- his usual minutes (last 10 games): -0.20
- his minutes rank on the team: -0.16
- how many games the main player has been out: -0.15
- he is a starter: -0.14
- how he did before when a similar player was out (shrunk): +0.14
- total minutes missing: +0.12
- minutes missing at his position: +0.11
- number of healthy teammates: -0.03
- how he did before in any game with a teammate out (shrunk): +0.03
- a starter at his position is out: +0.03
- number of rotation players out: +0.03
- plays the same position as the main player out: +0.01

**Boosted ranker** (share of what it learned from each input):

- his last 3 games vs his usual: 28.4%
- his usual minutes (last 10 games): 20.2%
- how he did before when a similar player was out (shrunk): 11.9%
- how he did before in any game with a teammate out (shrunk): 9.9%
- minutes missing at his position: 7.6%
- total minutes missing: 7.6%
- his minutes rank on the team: 4.6%
- how many games the main player has been out: 2.3%
- plays the same position as the main player out: 1.8%
- his spot in the bench order: 1.7%
- number of healthy teammates: 1.7%
- a starter at his position is out: 0.9%
- he is a starter: 0.7%
- number of rotation players out: 0.6%

## Where the model fails (Boosted ranker, test 2025-26; next man up shown for comparison)

**Players out**

| | Model #1 pick right | Next man up #1 pick right |
|---|---|---|
| 1 | 49.2% | 39.6% |
| 2 | 55.6% | 43.7% |
| 3+ | 65.6% | 59.5% |

**Position of main player out**

| | Model #1 pick right | Next man up #1 pick right |
|---|---|---|
| C | 56.3% | 49.4% |
| F | 54.3% | 39.4% |
| G | 53.4% | 47.4% |

**Game of the absence**

| | Model #1 pick right | Next man up #1 pick right |
|---|---|---|
| 1st game out | 56.0% | 48.7% |
| 2nd-3rd | 56.2% | 46.8% |
| 4th-10th | 51.2% | 39.5% |

**Time of season**

| | Model #1 pick right | Next man up #1 pick right |
|---|---|---|
| April (end of season) | 62.2% | 53.5% |
| Oct-Mar | 53.5% | 43.8% |

**Gainers available**

| | Model #1 pick right | Next man up #1 pick right |
|---|---|---|
| 0 | 0.0% | 0.0% |
| 1-2 | 39.5% | 31.8% |
| 3+ | 68.3% | 56.7% |

- no gainer at all (nobody could be right): 4.8%

## Examples: hits

| Date | Team | Opp | Out (baseline) | Model's top 3 (actual change) | Biggest real gainer |
|---|---|---|---|---|---|
| 2025-11-12 | DET | CHI | Cade Cunningham (37); Isaiah Stewart (23); Jalen Duren (30); Ausar Thompson (29); Tobias Harris (28) | Daniss Jenkins (+30), Chaz Lanier (+8), Bobi Klintman (+7) | Daniss Jenkins (+30) |
| 2026-04-10 | OKC | DEN | Alex Caruso (16); Isaiah Hartenstein (20); Shai Gilgeous-Alexander (32); Isaiah Joe (17); Jaylin Williams (16); Chet Holmgren (26); Jalen Williams (24); Cason Wallace (22); Ajay Mitchell (23) | Nikola Topic (+29), Kenrich Williams (+23), Brooks Barnhizer (+26) | Branden Carlson (+29) |
| 2026-02-03 | IND | UTA | T.J. McConnell (16); Pascal Siakam (34); Andrew Nembhard (33); Aaron Nesmith (32) | Kam Jones (+28), Quenton Jackson (+3), Taelon Peter (+26) | Kam Jones (+28) |
| 2026-04-12 | ATL | MIA | Onyeka Okongwu (30); Jalen Johnson (35); Dyson Daniels (33) | Asa Newell (+28), Mouhamed Gueye (-14), Zaccharie Risacher (+8) | Asa Newell (+28) |
| 2026-01-16 | LAC | TOR | Derrick Jones Jr. (24); Kawhi Leonard (34) | Jordan Miller (+28), Nicolas Batum (-16), Cam Christie (+14) | Jordan Miller (+28) |
| 2026-04-07 | NOP | UTA | Dejounte Murray (29); Trey Murphy III (35); Karlo Matkovic (19); Yves Missi (23) | Micah Peavy (+26), Derik Queen (+16), Jeremiah Fears (+12) | Micah Peavy (+26) |

## Examples: misses

| Date | Team | Opp | Out (baseline) | Model's top 3 (actual change) | Biggest real gainer |
|---|---|---|---|---|---|
| 2026-04-10 | MEM | UTA | Cam Spencer (23); Cedric Coward (24); GG Jackson (25); Jaylen Wells (25) | Javon Small (-25), Lucas Williamson (+20), Jahmai Mashack (+20) | Jahmai Mashack (+20) |
| 2026-01-10 | UTA | CHA | Lauri Markkanen (38); Oscar Tshiebwe (20); Ace Bailey (26) | Svi Mykhailiuk (-22), Cody Williams (+16), Isaiah Collier (+10) | Cody Williams (+16) |
| 2025-12-05 | PHI | MIL | Joel Embiid (25); Kelly Oubre Jr. (35) | Justin Edwards (-22), Paul George (+3), Adem Bona (+8) | Adem Bona (+8) |
| 2026-03-21 | UTA | PHI | Keyonte George (27); Isaiah Collier (27); Brice Sensabaugh (26) | Blake Hinson (-20), Elijah Harkless (+12), Kyle Filipowski (-9) | Elijah Harkless (+12) |
| 2026-03-19 | WAS | DET | Leaky Black (32); Julian Reese (30); Bilal Coulibaly (28); Kyshawn George (20) | Justin Champagnie (-20), Anthony Gill (+1), Tre Johnson (+2) | Sharife Cooper (+14) |
| 2026-03-01 | POR | ATL | Robert Williams III (17); Caleb Love (24); Deni Avdija (27); Shaedon Sharpe (30) | Kris Murray (-20), Scoot Henderson (+1), Donovan Clingan (+2) | Toumani Camara (+3) |
