# When a rotation player is out, who gets more minutes?

**Backtest findings: 2024-25 and 2025-26 NBA regular seasons**

## Summary

- The model's #1 pick plays more than his usual minutes in **about 63–64%** of games where a rotation teammate is out.
  "Next man up at the same position" is right about **50–53%** of the time, and a random teammate about **45%**.
- **When the model is most confident, it is right 73% of the time** (the top quarter of games). When it is least confident, it is right 49%, no better than a coin flip.
  The confidence score is the most useful thing to act on.
- Tuning the weights and adding new inputs added **2 to 3 points** over the first version. Most of the lead over the simple rules comes from what the model looks at, not from fine-tuning.
- The strongest signals are what the player did in his **last game and last 3 games**, whether the coach has **benched him recently**, and his **usual minutes** (bench players gain more often than stars).
  Playing the same position as the missing player matters very little once those are known.

## What was tested

- **Situation:** a team-game where a rotation player (15+ minutes a game) is out with an injury, illness or rest, in the first 10 games of his absence. Coach's-decision benchings don't count as out.
- **Question:** rank the healthy teammates. Who is most likely to play **at least 1 minute more** than his average of the previous 10 games?
- **Size:** 2,460 games, 3,043 team-games with a rotation player out, and 21,810 teammates ranked. Players who played for two teams across the two seasons were left out.
- **Fair testing:** the model learned on one season and was tested on the other, in both directions. A third test re-trained it month by month through 2025-26, using only earlier games each time. The tuning only ever looked at the training season.
- **How often teammates gain:** 44% of healthy teammates played 1+ minute more than their usual, so that is what a random pick scores.

## Results: how often the #1 pick played 1+ minute more

| Method | Train 2024-25, test 2025-26 | Train 2025-26, test 2024-25 | Month by month, 2025-26 |
|---|---|---|---|
| Random teammate | 44.5% | 46.6% | 44.5% |
| Highest-minutes teammate | 41.3% | 43.2% | 41.3% |
| Next man up (same position) | 50.0% | 52.8% | 50.0% |
| Original model (simple) | 59.0% | 61.0% | 58.9% |
| Original model (boosted) | 61.0% | 60.6% | 61.8% |
| **Tuned model (simple)** | **62.7%** | **62.9%** | **62.5%** |
| **Tuned model (boosted)** | **62.8%** | **64.1%** | **63.6%** |

- **Top 3:** about 56% of the tuned model's top 3 picks gained minutes, against 47–48% for next man up.
- **Is the lead real?** The tuned model's lead over next man up is 10 to 16 points (testing on 2025-26) and 7 to 14 points (testing on 2024-25), at 95% confidence. The gap is not luck.
- **Every month:** the tuned model beat next man up in every month of 2025-26. Its best month was April (68%) and its worst was October (54%), when there is little history to learn from.

### With the stricter rule (2+ minutes more)

| Method | Test 2025-26 | Test 2024-25 | Month by month |
|---|---|---|---|
| Random teammate | 38.4% | 40.0% | 38.4% |
| Next man up (same position) | 44.6% | 47.3% | 44.6% |
| Tuned model (best) | 57.6% | 56.7% | 58.6% |

### By how confident the model is (tuned simple model, tested on 2025-26)

| Model's confidence in its #1 pick | #1 pick played 1+ more minute |
|---|---|
| Lowest 25% of games | 49.3% |
| 25–50% | 59.4% |
| 50–75% | 69.2% |
| **Most confident 25%** | **72.7%** |

## What the model looks at, in order of weight

1. **His last game compared with his usual (more likely to gain).** If he already played more last game, often because the teammate's absence started then, he usually keeps getting those minutes.
2. **Coach's-decision benchings in his last 5 games (less likely to gain).** A player the coach has been sitting rarely gets the extra minutes, even when someone is out.
3. **His usual minutes (less likely to gain the higher they are).** A 12-minute bench player can easily play 13. A 36-minute starter has little room left.
4. **His minutes rank on the team (less likely the higher he ranks).**
5. **His last 3 games compared with his usual (more likely to gain).**
6. **Total minutes missing (more likely to gain).** The more minutes that are out, the more there are to hand out.
7. **How long the main player has been out (less likely to gain).** The first few games of an absence move minutes the most.
8. **How he did the last times a similar player was out (more likely to gain).** This is shrunk toward zero so a few games don't decide it.

These have **little or no effect**: playing the same position as the missing player, home or away, back-to-backs, and whether he is a starter.

## Where the model fails

- **The #1 pick doesn't play at all.** This is the most common miss: the coach sits him. Several of the clearest misses came from rebuilding teams late in the season (Utah, Washington, Memphis and Portland in March and April).
- **Only one player out.** With one rotation player out, it is right less often than with three or more out, because fewer minutes are up for grabs.
- **Early in the season.** In October there is little history for "how he did when a similar player was out", so it was right 54% of the time.
- **Low-confidence games.** In the bottom quarter, the model is no better than a coin flip.

### Examples

**Hits:**
- **Nov 12, 2025, Pistons vs Bulls.** Cunningham, Duren, Thompson, Harris and Stewart were out. #1 pick: Daniss Jenkins, who played **30 minutes more than his usual**.
- **Feb 3, 2026, Pacers vs Jazz.** Siakam, Nembhard, Nesmith and McConnell were out. #1 pick: Kam Jones, **+28 minutes**.
- **Jan 16, 2026, Clippers vs Raptors.** Leonard and Jones Jr. were out. #1 pick: Jordan Miller, **+28 minutes**.

**Misses:**
- **Apr 10, 2026, Grizzlies vs Jazz.** Four rotation players were out. #1 pick Javon Small didn't play (coach's decision). Jahmai Mashack got +20.
- **Dec 5, 2025, 76ers vs Bucks.** Embiid and Oubre were out. #1 pick Justin Edwards was benched. Adem Bona got +8.

## Limits to keep in mind

- **Missing players count as out.** ESPN's box scores leave out most inactive players, so a player missing from a game while on the team is counted as out. Usually that's an injury, but ESPN doesn't say why.
- **Absences only count for 10 games.** After the first 10 games, his teammates' 10-game averages already include his absence, so there is nothing left to gain.
- **Traded players are left out.** Players who changed teams were excluded, which removes many rotation players on teams that made deadline trades.
- **It ranks players, it doesn't predict minutes.** It says who is most likely to play more, not by how much.

## What I'd suggest next

- **Only act on confident picks.** The top half of confidence is right about 70% of the time.
- **Add starting lineups.** A confirmed lineup (RotoWire), known before tip-off, should cut the "#1 pick didn't play" misses. That is the biggest single failure.

*Scripts and data: `backtest/` in the nba-board repository (`tune.py` for these results; `REPORT.md` has the full tables).*
