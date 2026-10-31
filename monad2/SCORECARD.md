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
| 3 | 2026-10-30 9:04 PM | 236b81c | gap 2: FMF goal-type top-1, holdout exclusion | — | — | — | — | — | bars only |
| 4 | 2026-10-30 9:05 PM | 236b81c | gap 1: SCP next-frame test, 4×4 role map | — | — | — | — | — | yes |
| 5 | 2026-10-30 9:53 PM | 236b81c | 3-seed balanced factorial, stall breaker on, 300s | 0, 1, 2 | 0/25 | 21, 15, 19 | 42044, 39629, 41582 | 0.499, 0.379, 0.457 | no |
| 6 | 2026-10-30 10:02 PM | 236b81c | holdout replay of row 13, stall breaker off, 300s | 0 | 0/5 | 2 | 8313 | 0.241 | no |

Entry 2 assigned a different design row to each level (`MONAD2_FACTORIAL=1`, `MONAD2_FACTORIAL_SEED=0`). Discovery games produced 0 clears of a level the baseline missed, so nothing was confirmed and every flag stays off. On the 12 discovery level-rows the baseline can already clear, factor-on vs factor-off clear counts were: SCP 4/8 vs 2/4, goal memory 1/4 vs 5/8, rehearsal 2/7 vs 4/5, callosum 0/5 vs 6/7, D-ladder 3/7 vs 3/5, earned 3/5 vs 3/7, tonic 4/8 vs 2/4, PLL surprise 3/8 vs 3/4, skip-organs 3/6 vs 3/6. Callosum overrode 5,505 of 11,004 actions it saw. The aggregate 8 levels is below the baseline, at fewer actions because games stalled early.


Entry 1: seeds 0, 1, and 2 matched on every game (levels, actions, and terminal state). The goal engine is on because game-specific solvers are disabled. Monad(2) flags were unset. Code is the ledger commit `98227b8`. The per-game limit is the `max_game_seconds` argument of `play_single_game` (default 300, or `MONAD2_MAX_GAME_SECONDS`).

### Entry 3 — goal memory

Corpus is `monad2/fmf_corpus/records.jsonl` (469 records, plus the README, stats, and representatives). Retrieval drops any record whose `game_id`, `task_id`, `game_ids`, or text names the game being scored. Query features come from the level-0 projection (avatar, panel, click, push, switch, corridor, portal), not from goal-label words.

Held-out top-1 is 6/25 = 0.240. The fixed bar is 0.217. The corpus's own chance (mean fraction of eligible records that carry the query game's goal type) is 0.266. Majority label in the corpus is MATCH, and that constant guess is also 6/25 = 0.240. Every game received a hypothesis, so UNKNOWN levels are 0 of 183 (level sum 183), under the 102 bar. The two stated bars are met, and the predictor is the constant MATCH guess, so `MONAD2_GOAL_MEMORY` stays off.

### Entry 4 — SCP percept

The old projection (0.170 vs raw 0.310) kept a size bucket and a 32px quadrant and dropped singletons, adjacency, and where mass sat inside the quadrant. The 8×8 raw grid still had that layout. Tokens now include a 4×4 majority-role map, the controllable cell's four neighbors, direction toward the largest other object, and 4×4 positions of the four largest objects. The test also passes the previous frame into feedback; the first run had left that token on `start`. Same Laplace model, same 500 transitions, 100 of them on fold 0.

Projection accuracy 0.580, raw 0.310, majority 0.560. Mean tokens 30.0 vs 64. The prediction test passes. The flag stays off until a blind level gain is confirmed.

### Entry 5 — callosum, PLL, stalls, and the 3-seed screen

Code is `236b81c`. Each of seeds 0, 1, and 2 plays a balanced triple, so each flag is on in 1 or 2 of the 3 plays of each level. All 32 design rows appear. The per-game limit is the existing `--max-game-seconds` argument (default 300, also `MONAD2_MAX_GAME_SECONDS`).

Entry 2's sc25 (3→0, 1528 actions, 27.6s) and tu93 (4→0, 610 actions, 33.0s) stopped on the in-agent loop, not the clock. sc25 hit `steps_in_level >= 1500`. tu93 hit the 600-step rule (no novel cell for 300 steps and at least 4 resets). The stall breaker, on during this screen, returns a flagged level to baseline after 48 unchanged frames, or when that 600-step exit is close, or at step 900. It fired 74 times across the three seeds (25, 26, 23).

| Seed | Levels | Actions | Levels/1k | sc25 | tu93 |
| --- | --- | --- | --- | --- | --- |
| 0 | 21 | 42044 | 0.4995 | 2 | 7 |
| 1 | 15 | 39629 | 0.3785 | 0 | 4 |
| 2 | 19 | 41582 | 0.4569 | 3 | 4 |
| baseline | 19 | 42729 | 0.4447 | 3 | 4 |

Mean of the three seeds is 18.3 levels and 41085 actions, below the baseline. The only discovery clear of a level the baseline never reached, with no stall fallback on that level, is tu93 level 4 under row 13 (SCP, rehearsal, callosum, tonic, skip-organs) on seed 0. Seeds 1 and 2 reached tu93 level 4 and did not clear it (seed 2's row there was every flag off). On discovery levels the baseline already clears, plays that did not fall back cleared 43/43, so the on/off contrast is tied. The losses (sc25 on seeds 0 and 1, ka59 on seed 1) are outside that set.

Callosum overrides are conditional: the world model must predict progress for the alternative and none for A's choice. Effects are recorded while the flag is on, without turning on rehearsal probes. Overrides were 293 of 30,478 seen actions (about 1.0%). The gate blocked 13,714 proposals. That is the re-measure of the old 5,505/11,004 unconditional overrides.

PLL lock loss still precedes a failed plan: 51/140 = 0.364 versus a 3-step chance of about 0.257 (1,642 losses in 17,447 PLL steps). The new path clears the plan and demotes the goal hypothesis (93 demotions). The suite did not gain levels, so the flag stays off.

### Entry 6 — holdout confirmation

Row 13 replayed on `cd82, ft09, m0r0, tn36, tr87` with `PYTHONHASHSEED=0`, those five flags on, the others off, and `MONAD2_STALL_N=0` so the breaker could not hand the game back to baseline. Result: 0/5 wins, 2 levels, 8313 actions. The same five games in the baseline are 2 levels and 8309 actions (cd82 1/2201, ft09 0/1509, m0r0 1/1565, tn36 0/1523, tr87 0/1511). This replay was cd82 1/2201, ft09 0/1512, m0r0 1/1565, tn36 0/1524, tr87 0/1511. It does not beat the baseline. Nothing is turned on by default.
