# Monad(2) scorecard

Fresh ledger. Earlier Monad(1) totals are not entries here. The machine-readable log is `scorecard.jsonl` (one JSON object per line).

Primary metric: blind levels (`--offline --blind-id --no-game-solvers`) at no more actions than the previous best. Solvers-on is a regression check that the per-game solvers still solve every game.

Every entry records America/Chicago time, commit, flags, seeds, per-game time limit, wins/25, levels/183, actions, levels per 1,000 actions, the gap item under test, and whether that item's test passed.

`PYTHONHASHSEED` is fixed per seed. Game order is the harness default (sorted prefixes) unless the entry names a permutation. The per-game limit is `--max-game-seconds` (300 unless an entry says otherwise).

Gaps 1–9 are independent flags and default off. Entry 7 adds `MONAD2_GOAL_DISCOVERY` as a tenth column of the same 32-run design (the AB interaction in `monad2/factorial.py`). `MONAD2_FACTORIAL=1` assigns one row to each level. Discovery analysis ignores the pre-registered holdout prefixes `cd82`, `ft09`, `m0r0`, `tn36`, `tr87`. A factor is turned on only after a fixed-flag replay of that combo on the holdout beats this baseline. `monad2/DATAFLOW.md` is the influence-path rule: a one-module zero is not grounds to delete a module.

| # | When (CT) | Commit | What | Seeds | Wins | Levels | Actions | Levels/1k | Passed |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | 2026-10-30 8:33 PM | 98227b8 | fresh blind baseline, flags off, 300s | 0, 1, 2 | 0/25 | 19/183 | 42729 | 0.4447 | yes |
| 2 | 2026-10-30 8:48 PM | a39c069 | per-level 32-run factorial, gaps 1–9, 300s | 0 | 0/25 | 8/183 | 27460 | 0.2913 | no |
| 3 | 2026-10-30 9:04 PM | 236b81c | gap 2: FMF goal-type top-1, holdout exclusion | — | — | — | — | — | bars only |
| 4 | 2026-10-30 9:05 PM | 236b81c | gap 1: SCP next-frame test, 4×4 role map | — | — | — | — | — | yes |
| 5 | 2026-10-30 9:53 PM | 236b81c | 3-seed balanced factorial, stall breaker on, 300s | 0, 1, 2 | 0/25 | 21, 15, 19 | 42044, 39629, 41582 | 0.499, 0.379, 0.457 | no |
| 6 | 2026-10-30 10:02 PM | 236b81c | holdout replay of row 13, stall breaker off, 300s | 0 | 0/5 | 2 | 8313 | 0.241 | no |
| 7 | 2026-10-31 8:59 AM | 4576a1e | goal discovery in the 10-factor screen, 300s | 0, 1, 2 | 0/25 | 11, 12, 18 | 37703, 38171, 41675 | 0.292, 0.314, 0.432 | no |
| 8 | 2026-10-31 11:24 AM | c80088b | watch-only goal discovery, 300s | 0, 1, 2 | 0/25 | 19, 19, 19 | 42729, 42729, 42729 | 0.445, 0.445, 0.445 | yes |
| 9 | 2026-10-31 12:09 PM | af41cb0 | stall restore on the factorial, seed 0, 300s | 0 | 0/25 | 17/183 | 58524 | 0.290 | no |
| 10 | 2026-10-31 1:49 PM | cdd1719 | coordination test, not a score run | 0 | 0/3 | 1 | 18 | — | yes |
| 11 | 2026-10-31 2:21 PM | e880261 | motor-primitive smoke, not a score run | 0 | 0/3 | 0 | 6 | — | yes |
| 12 | 2026-10-31 3:02 PM | 4cc3ef7 | role binding and predicate smoke, not a score run | 0 | 0/3 | 0 | 9 | — | yes |

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

### Entry 7 — goal discovery

Code is `4576a1e`. Early in a level, while `MONAD2_GOAL_DISCOVERY` is on, the agent spends up to 6 probe actions and ranks REACH, PLACE, and MATCH from what the frame actually changed (a controllable shift, a shared shift or a containment/contact gain, a panel-mismatch drop). The leading vote adds 3 to that goal type when the action set already allows it. A later outcome label, from non-probe transitions, is stored in the episode field by affordance features. Holdout prefixes do not write that store. The world-model canvas plans toward the hypothesis. The callosum may override only when the one-step prediction gains more of that goal than the current move. The D-ladder still checks the probe and the override. A PLL lock loss demotes the vote and clears the plan. The tenth factorial column is this group. `monad2/DATAFLOW.md` records the path.

| Seed | Levels | Actions | Levels/1k | Elapsed | sc25 | tu93 | ka59 | bp35 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 0 | 11 | 37703 | 0.2918 | 794.83s | 0 | 1 | 0 | 0 |
| 1 | 12 | 38171 | 0.3144 | 812.44s | 0 | 1 | 0 | 1 |
| 2 | 18 | 41675 | 0.4319 | 898.25s | 3 | 3 | 1 | 1 |
| baseline | 19 | 42729 | 0.4447 | — | 3 | 4 | 1 | 1 |

Mean of the three seeds is 13.7 levels and 39183 actions, below the 19-level baseline. Wins stay 0/25. The drops against the baseline are bp35 and ka59 on seed 0, ka59 on seed 1, sc25 on seeds 0 and 1 (3→0), and tu93 on every seed (4→1, 4→1, 4→3). Every one of those missed baseline clears except sc25 on seed 1 had goal discovery on, then the stall breaker fired, and the level still did not clear. sc25 on seed 1 missed with discovery off (row 15) and a stall fallback, so the drop is not discovery alone. On discovery levels the baseline already clears, plays that did not fall back cleared 33/33. Goal discovery was 13/13 on and 20/20 off. The other nine factors are tied the same way. There is no extra clear of a level the baseline never reached, so there is no candidate and no holdout replay. No flag turns on. No module is removed.

Goal-hypothesis accuracy against the later outcome label is 3/3. Those three level-episodes are the only ones that closed with both a frozen probe hypothesis and a separate later-outcome label: cd82 level 0, ls20 level 0, and sp80 level 0, all on seed 2. cd82 is a holdout prefix, so that label was not written into the episode store. Seeds 0 and 1 closed zero such levels. Probes across the screen: 72, 38, 54. Corpus relabel, from described changes rather than goal-type words, added 1 REACH label. 87 records already carried an explicit REACH, PLACE, or MATCH label. 381 records stay unlabeled. Callosum overrides on this screen were 260 of 29,405 seen actions, with 13,066 proposals blocked. Stall fallbacks fired 72 times. PLL demotions were 235.

### Entry 8 — watch-only goal discovery

Code is `c80088b`. `MONAD2_GOAL_WATCH=1` and `MONAD2_LOG_ACTIONS=1`. No probe actions, no goal-prior bonus, and `m2_goal_hypothesis` is left unset, so the callosum cannot read the watch hypothesis. A start hypothesis freezes from the natural transitions plus effects already observed for other legal actions. The outcome label is the start frame against the last in-level frame, taken at level change, stall, or game end. Confirmed labels are stored by affordance features in `monad2/fmf_corpus/watch_labels.jsonl`. Holdout prefixes do not write that store.

The flags-off control (`MONAD2_LOG_ACTIONS=1`, watch off, seed 0) matched the entry-1 baseline on every game: 19 levels, 42729 actions. Watch seeds 0, 1, and 2 each also finished at 19 levels and 42729 actions, and each game's action sequence matched that control. Elapsed times were 807.19s (control), 827.77s, 814.63s, and 829.09s.

| | Episodes | Confirmed label | Both hyp and label | Hits | Accuracy |
| --- | --- | --- | --- | --- | --- |
| 3 seeds | 132 | 87 (0.659) | 75 | 54 | 0.720 |

Hypothesis rows against outcome columns, including segments whose frames changed without a REACH/PLACE/MATCH vote (`OTHER`) and segments with no frozen hypothesis (`NONE`):

| Hypothesis | REACH | PLACE | MATCH | OTHER | NONE |
| --- | --- | --- | --- | --- | --- |
| REACH | 9 | 18 | 3 | 15 | 0 |
| PLACE | 0 | 45 | 0 | 27 | 0 |
| MATCH | 0 | 0 | 0 | 0 | 0 |
| OTHER | 0 | 0 | 0 | 0 | 0 |
| NONE | 3 | 6 | 3 | 3 | 0 |

The pre-registered chance bar is 0.217 and the corpus majority (MATCH) is 0.240. Accuracy 0.720 is above both. On the 75 scored episodes the outcome majority is PLACE, 63/75 = 0.840. Always guessing PLACE beats the hypothesis. The hypothesis never said MATCH. Of the 381 corpus records that still have no REACH/PLACE/MATCH label, 17 share affordance features with a stored watch label (14 PLACE, 3 MATCH). The stored keys collapse to three bundles, and 60 of the 66 episodes on the largest bundle are PLACE. The text relabel of the corpus is still the 1 REACH record from entry 7. Nothing turns on. The hypothesis is not accurate enough to steer.

### Entry 9 — stall restore

Code is `af41cb0`. Seed 0 of the 10-factor screen, with the stall path restoring the level-start residue (goal votes, gauge, HUD mask, responsive signatures), rebuilding the level world model, and sending one RESET. Result: 0/25 wins, 17 levels, 58524 actions, 0.290 levels per 1k, 1266.22s. The control is 19 levels and 42729 actions. Twenty-seven restores fired.

| Game | This run | Baseline |
| --- | --- | --- |
| bp35 | 1 level, 2852 actions | 1 level, 1795 actions |
| ka59 | 0 levels, 2425 actions, GAME_OVER | 1 level, 2202 actions |
| sc25 | 3 levels, 5862 actions | 3 levels, 4865 actions |
| tu93 | 3 levels, 3317 actions | 4 levels, 1754 actions |

bp35 and sc25 keep the baseline level count. ka59 and tu93 each finish one level short, and the restored games spend the stalled prefix plus the replay, so actions are higher. No holdout replay: the suite is below 19 levels. No flag turns on. No module is removed.

### Entry 10 — coordination, not a score run

Code is `cdd1719`. This is not a 25-game score. `MONAD2_COORDINATE=1`, game solvers off, other Monad(2) flags off, `PYTHONHASHSEED=0`, 6 actions per game, games `ls20`, `lp85`, `vc33`, blinded ids. Qwen2.5-0.5B is A', Qwen2.5-1.5B is B', Mistral-NeMo-Minitron-8B is the executive, all Q4 on CPU llama.cpp, temperature 0, seed 0.

| Game | Levels | Actions | Seconds | State |
| --- | --- | --- | --- | --- |
| ls20 | 0 | 6 | 288.62 | NOT_FINISHED |
| lp85 | 1 | 6 | 255.26 | NOT_FINISHED |
| vc33 | 0 | 6 | 291.05 | NOT_FINISHED |

0/3 wins, 1 level, 18 actions, 835 s. Not comparable to the 19/183 baseline. Mean model step 46.2 s, max 67.4 s. The executive was most of that (about 32–55 s). Expectation matched the frame on 11/14 steps. The document diff matched the stated canvas change on 0/12. The executive inhibited 5 times and changed the action 4 of those. Qwen changed the action 4 times. Per-game solver hits 0. Static game-name scan clean. Stored schema S0 had roles wall, avatar, goal and relations containment, contact, with no game id, color, or coordinate. A recolored, quarter-turned frame matched that structure: receptor and goal bound to hollow_rect geom 2,4,6, wall to line geom 3,1,58, avatar to line geom 3,1,6. Live steps of this 6-action run did not show a cross-game binding because the episode key was the reused object id. That key is now an attribute on the agent. A 2-action follow-up at 2:02 PM CT, same three games, mean step 30.5 s, put the `ls20` schema into the `lp85` stream: wall rebound from geom 1,4,52 to line geom 3,1,64, avatar rebound from ellipse geom 4,1,1 to line geom 3,1,4. Generation caps are 48/48/64 tokens. The plan cache did not skip a model call on that follow-up. No flag turns on.

### Entry 11 — motor primitives, not a score run

Code is `e880261` (the primitive list is `1e7d2ff`). This is not a 25-game score. Same three games, two actions each, solvers off, other Monad(2) flags off, `PYTHONHASHSEED=0`. Mean step 28.8 s, max 32.6 s. 0/3 wins, 0 levels, 6 actions, 176 s.

`ls20` proposed `approach` (avatar,goal) and `route` (avatar,wall). Qwen A' named `approach`. Qwen B' challenged with `hold_gradient`. The executive inhibited and kept `hold_gradient`, expecting "avatar does not reverse". The frame changed, the check confirmed, confidence 1.25. `lp85` and `vc33` had no role precondition, so the listed rule was labeled `explore`. Their Qwen actions were not legal, and the executive took that labeled click. `vc33` confirmed it against the document diff. Per-game solver hits 0. Static scan clean. The mapping of the 27 old methods is `monad2/PRIMITIVES.md`. No flag turns on.

### Entry 12 — role binding and checkable predicates, not a score run

Code is `4cc3ef7` (role inference landed in `9993145`). This is not a 25-game score. `MONAD2_COORDINATE=1`, game solvers off, other Monad(2) flags off, `PYTHONHASHSEED=0`, 3 actions per game, games `ls20`, `lp85`, `vc33`, blinded ids. Mean step 32.3 s, max 35.9 s. 0/3 wins, 0 levels, 9 actions, 294 s. The log has no context overflow. Per-game solver hits 0. Static scan clean. Predicate checks 6, predicate hits 1, surprises 5. Qwen repairs 12. No flag turns on.

Roles come from the frame and from what the last action did. A shape that translates under a directional action is the avatar. A second shape that translates while touching it is movable. A shape that changes under a click is a switch. A region tied to a reset is a hazard, a blocked step is a wall, and level completion marks the goal. A shape or fill match with a reference panel is the align relation. Click games get clickable objects and a reference panel, and they do not get a static avatar. Stored slots are geometry only. Click anchors stay on the ephemeral affordance map. A palette permutation plus a quarter turn keeps the same role set and the same geom per role.

| Game | Seconds | Roles on the scored steps | Qwen repaired | Predicate result |
| --- | --- | --- | --- | --- |
| ls20 | 103.83 | receptor, reference, wall, avatar, goal; then movable | 0 | translate left failed, then confirmed |
| lp85 | 95.99 | wall, reference, clickable, goal | 6 | changed(clickable) failed twice |
| vc33 | 94.53 | receptor, reference, wall, clickable, goal; then switch | 6 | changed(clickable) failed twice |

`ls20` step 0. Roles: receptor, reference, wall, avatar, goal. A' `approach` SIMPLE 2 (down), legal. B' `hold_gradient` SIMPLE 3 (left), legal. Executive inhibited to SIMPLE 3 via `approach`. Predicate `translate(role=avatar, dir=left)`. The frame changed and the predicate was false, so confidence went to 0.5 and the predicate was logged as a surprise. Step 1 added movable. The same predicate was true, so the check confirmed and confidence went to 0.75. Step 2 (not scored) inhibited to `hold_gradient` with `no_reverse(role=avatar, axis=x)`.

`lp85`. Roles: wall, reference, clickable, goal. No avatar. Both Qwen actions were illegal and were repaired to CLICK 11 1 before the executive. The executive JSON had no legal action, so the step was labeled `explore` with `changed(role=clickable)`. Both scored steps refuted that predicate. Confidence went 1.0 to 0.5 to 0.0. Each miss is in the surprise list.

`vc33`. Roles began as receptor, reference, wall, clickable, goal, then added switch after the click. Both Qwen actions were repaired to CLICK 38 29. The taken rule was labeled `explore`, predicate `changed(role=clickable)`. Both scored steps refuted it. Confidence went 1.0 to 0.5 to 0.0. The live stream rebound schema S0 onto this frame: receptor and goal to hollow_rect geom 2,4,6, wall to line geom 3,1,64, avatar to rect geom 1,2,4.

The third action of each game was chosen and not scored. The saved 6-action sample in `COORD_SAMPLE.md` was not overwritten.
