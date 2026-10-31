# Monad(2) scorecard

Fresh ledger. Earlier Monad(1) totals are not entries here. The machine-readable log is `scorecard.jsonl` (one JSON object per line).

Primary metric: blind levels (`--offline --blind-id --no-game-solvers`) at no more actions than the previous best. Solvers-on is a regression check that the per-game solvers still solve every game.

Every entry records America/Chicago time, commit, flags, seeds, per-game time limit, wins/25, levels/183, actions, levels per 1,000 actions, the gap item under test, and whether that item's test passed.

`PYTHONHASHSEED` is fixed per seed. Game order is the harness default (sorted prefixes) unless the entry names a permutation. The per-game limit is `--max-game-seconds` (300 unless an entry says otherwise).

Gaps 1–9 are independent flags and default off. `MONAD2_FACTORIAL=1` assigns a row of the 32-run design in `monad2/factorial.py` to each level. Discovery analysis ignores the pre-registered holdout prefixes `cd82`, `ft09`, `m0r0`, `tn36`, `tr87`. A factor is turned on only after a fixed-flag replay of that combo on the holdout beats this baseline. `monad2/DATAFLOW.md` is the influence-path rule: a one-module zero is not grounds to delete a module.

| # | When (CT) | Commit | What | Seeds | Wins | Levels | Actions | Levels/1k | Passed |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | 2026-10-30 8:33 PM | 98227b8 | fresh blind baseline, flags off, 300s | 0, 1, 2 | 0/25 | 19/183 | 42729 | 0.4447 | yes |
| 2 | 2026-10-30 8:48 PM | a39c069 | per-level 32-run factorial, gaps 1–9, 300s | 0 | 0/25 | 8/183 | 27460 | 0.2913 | no |

Entry 2 assigned a different design row to each level (`MONAD2_FACTORIAL=1`, `MONAD2_FACTORIAL_SEED=0`). Discovery games produced 0 clears of a level the baseline missed, so nothing was confirmed and every flag stays off. On the 12 discovery level-rows the baseline can already clear, factor-on vs factor-off clear counts were: SCP 4/8 vs 2/4, goal memory 1/4 vs 5/8, rehearsal 2/7 vs 4/5, callosum 0/5 vs 6/7, D-ladder 3/7 vs 3/5, earned 3/5 vs 3/7, tonic 4/8 vs 2/4, PLL surprise 3/8 vs 3/4, skip-organs 3/6 vs 3/6. Callosum overrode 5,505 of 11,004 actions it saw. The aggregate 8 levels is below the baseline, at fewer actions because games stalled early.


Seeds 0, 1, and 2 matched on every game (levels, actions, and terminal state). The goal engine is on because game-specific solvers are disabled. Monad(2) flags were unset. Code is the ledger commit `98227b8` (configurable time limit only).
