# LEDGER -- one row per idea attempt (the 12M campaign)

Append immediately after each gate, kills included. The main thread keeps only the one-line
result in context; this file is the campaign memory.

Format: | id | pool | mechanism (one line) | deg deltas | sweep median | verdict | commit |

## Baseline entering the campaign

sweep median **18,982,338** -- branch m4-nine-levels, tip acaed54.
Best binary of that build: the deg.fjm produced by census_ts5_cand (see _deg_ts5.log).
Rebuild it with: python scratchpad/popcount_census.py capture-doom --out <c.json.gz> --stl stock

## Prior work (closed -- context only, details in handoff sections 16-19)

| round | ideas | median | notes |
|---|---|---|---|
| campaign 1-11 | 11 shipped | 24,306,866 -> 20,775,735 | one-shadow, DDA, lockstep, T4, ... |
| campaign 12-20 | 9 shipped, 6 killed | -> 19,716,925 | chains (-464k biggest), placement rounds |
| ts round 1-5 | 5 shipped, 0 killed | -> 18,982,338 | width 8->5 (-386k biggest) |

## The 12M campaign

| id | pool | mechanism | deg | sweep median | verdict | commit |
|---|---|---|---|---|---|---|
| (first row goes here) | | | | | | |
