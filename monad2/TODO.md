# Remaining work

Written 2026-10-31 7:25 PM CT. Docs only. Drawn from `MODULE_SCAN.md`, `ARC3_AGENT_PLAN.md`, `DIAGNOSIS.md`, and ledger entries 14–16. No code was changed and no game was played to write this list.

Checked items are already in the tree. The commit is the one that put the behavior there. Open items are the path from that tree to a general agent. Do them in order. A failed milestone stops the next one.

## Rules

- No `game_id` branch, no fingerprint key, no hardcoded palette, no hardcoded coordinate, no stored action sequence. `general_guard.static_violations` and `schema.assert_structure` stay on every module that proposes a move.
- The 27 solvers stay in the file as reference. The agent calls primitives. `arm_solver_guard` stays armed. A clear that came from a solver plan is not a pass.
- Group ablations before deleting anything. PLL, Gohst, the observer field, tonic, the INOS joints, and `ControllerState` are not deleted because one flag changed nothing. A deletion needs the factorial contrast and the holdout confirmation.
- Do not turn `MONAD2_GOAL_DISCOVERY`, `MONAD2_GOAL_MEMORY`, `MONAD2_REHEARSAL`, or any other factorial column on as a substitute for an open item. Call the function from the coordinate path.
- Stop a run that is passing no levels. One game: stop by 100 actions, or earlier when the plan repeats and the evidence is not new. Several games: stop when the first three finish at 0 levels.
- Never call a 0-level run healthy. Never call it a score. Entry 1 (19/183, 42,729 actions, `98227b8`) and the optimal 6,444 are not moved by an aborted slice. Entry 14 stays aborted.
- Evaluation traces score a milestone. They are not fed to the agent. `environment_files/` is not imported.
- PR #1 stays untouched. This list lives on PR #2.

## Known blockers

- The goal role is written only in `roles.note_effect` when the outcome is `completed`. Nothing has completed, so the role stays empty. `approach` is never offered. `step_toward` returns no step. Entry 16 is that break: 59 actions, 0 levels, 64 LLM calls, plan `hold_gradient` then `convey`. Not healthy.
- The watch line does reach the executive (`watch REACH unconfirmed; goal role unbound`) and no function turns it into a box or a click.
- `planmode.ready` treats receptor and reference as goal-like, so planning starts against the HUD hollow rect.
- The General Goal Engine already walks candidate objects. `decide` discards the action. Its target key stores a color and a coarse coordinate, so the loop cannot be reused until the id is a geom.
- A hand-fed `approach` on `ls20` walks the open line, the entrance step does not translate, and the repeat is spent off that line. Level 0. The conditional-edge item is the intended general fix. Do not special-case the game.
- A hand-fed `toggle` on `vc33` clears level 1 when the predicate geom is the unique object the click translates and the anchor stays. Pressing each live anchor once does not clear. `vc33` was not played live after the kill.
- `_scp_canonicalize_split_panel_palette` still rewrites the grid, using fixed cells and fixed colors, before monad2 sees the frame.
- A three-call model step is about 30–40 seconds. A 300 second game can afford about eight of those. Execute steps are already 0 seconds of model time, and discover steps are not.
- Cross-game schema transfer has no solvers-off clear to its name. It is not on the M1 path.

## Rule compliance

- [ ] **Stop the split-panel palette remap from touching the frame monad2 reads.** `_scp_canonicalize_split_panel_palette` matches fixed colors at fixed cells and can rewrite every pixel. `choose_action` runs it before `_m2_grid` is saved. Read the raw frame for `_m2_grid`. Leave the function in `my_agent_v7_inos.py`.
  - Files: `MyAgent._choose_action_impl`, `_scp_canonicalize_split_panel_palette`. The node-graph canonicalizer already returns immediately when solvers are disabled.
  - Why: game-specific palette and coordinates are on the live perception path (`MODULE_SCAN.md`).
  - Done when: a unit check shows `_m2_grid` equals the frame from `_grid_from_frame` on a grid that would have been remapped, and `static_violations` stays empty.
  - Depends on: nothing.

- [x] **Keep the solver guard armed.** With solvers disabled and `MONAD2_COORDINATE=1`, each of the 27 methods is stubbed and `arm_solver_guard` records a call.
  - Files: `MyAgent._disable_game_specific_solvers`, `general_guard.arm_solver_guard`, `solver_catalog_ok`.
  - Why: solvers are a source of motion rules, not a plan the agent may run.
  - Done when: `HITS` is empty after a solvers-off run, and the stub list still matches the methods.
  - Depends on: nothing.
  - Commit: `cdd1719`. Still the live switch at `9610309`. Entry 16 recorded no solver hits.

- [x] **Keep the palette-permutation and D4 tests.** `_same_roles` checks that a recoloring and a quarter turn do not change the role assignment.
  - Files: `monad2/test_roles.py`.
  - Why: a role rule that sees a color or an absolute orientation is a hidden palette.
  - Done when: `test_roles.py` still passes those two checks after every later edit. The candidate-enumerator tests have to do the same.
  - Depends on: nothing.
  - Commit: `9993145`. Still present at `9610309`.

## M1 — level 1 on `ls20`, then `vc33`

Live, no clock, solvers off, `MONAD2_COORDINATE=1`, `PYTHONHASHSEED=0`. The agent source must not mention either id. Stop `ls20` at 100 actions, or earlier if the plan repeats with no new evidence. If it clears nothing, do not start `vc33`.

### Perception

- [x] **Leave the goal role empty until a level completes.** Do not copy the hollow reference into goal. Do not let a previous episode's schema fill that slot. A completion may write it, and only when the geom is unique.
  - Files: `roles.note_effect`, `schema.induce`, `schema.drop_contradictions`.
  - Why: diagnosis fix 1. Entry 15's goal was the HUD icon.
  - Done when: a frame with a hollow rect has receptor and reference, and no goal, until `outcome == "completed"`.
  - Depends on: nothing.
  - Commit: `271fca7`.

- [x] **Bind the controllable from the effect.** One unique translating geom is the avatar. Several unique geoms that share one delta bind the largest part. Different deltas bind nothing. A click binds switch only when the frame changed and the geom's count is 1.
  - Files: `roles.note_effect`, `roles._largest_part`, `roles._unique_geom`.
  - Why: diagnosis fix 2. The old rule picked the smallest mark. Two co-moving parts used to bind nothing.
  - Done when: `test_roles.py` covers a shared geom, a shared delta, and a different-delta pair. Entry 16 bound avatar `[1, 3, 5]` and movable `[1, 2, 5]` on the first effect.
  - Depends on: nothing.
  - Commit: `271fca7`, shared-delta case `9610309`.

- [x] **Keep click points and boxes off the schema.** Affordances live on the ephemeral state. `assert_structure` rejects a coordinate and a 4-int signature.
  - Files: `roles.infer_roles`, `menu.resolve_choice`, `schema.assert_structure`, `schema.upsert`.
  - Why: a stored xy or fill color is a solution fragment.
  - Done when: a schema round-trip still has no coordinate list, and the menu resolves a click at execution time.
  - Depends on: nothing.
  - Commit: `cdd1719` for the schema guard, `f910fbb` for the menu. Unchanged by the six fixes.

### Explore

- [ ] **Add a candidate enumerator and call it when the goal role is empty.** Suggested module `monad2/candidates.py`, added to `general_guard.ACTIVE_MODULES`. Inputs are `frame_records`, `role_evidence`, the watch leader, and the legal set. Output is an ordered list of `{kind, geom}` plus an ephemeral box that is not stored.
  - Files: new `monad2/candidates.py`, `coordinate.decide`, `general_guard.ACTIVE_MODULES`.
  - Why: the hypothesis names a type and names no object, which is the entry 16 break.
  - Done when: REACH candidates are unique geoms that are not the avatar, not the wall, not a hollow type-2 HUD, and not the co-moving movable. A shared geom is skipped. PLACE pairs the movable with a static unique geom of the same shape. MATCH is two equal-size regions that differ, with no stored color. A click legal set yields `affordances["clickable"]`, one anchor at a time. The list is unchanged by a palette permutation and a D4 turn.
  - Depends on: the checked perception items, and the remap item above so the records are from the raw frame.

- [ ] **Order candidates by the watch leader, not by color rarity.** REACH first when REACH leads. Do not sort by how rare a color is.
  - Files: `candidates.py`, `discovery.leader`, `discovery.watch_step`. Contrast with `MyAgent._ggl_reach_candidates`, which sorts by color rarity and must not be copied.
  - Why: rarity is a palette prior. The leader is already computed and unused.
  - Done when: a unit case with REACH ahead of PLACE returns a REACH geom first, and a recoloring does not change that order.
  - Depends on: the enumerator.

- [ ] **Probe each legal direction once before any translation, without turning a factorial flag on.** Skip a direction `dead_actions` or `note_route` has already recorded. This is `discovery.next_probe`'s job, called directly.
  - Files: `discovery.next_probe` or the same loop inside the enumerator. Do not set `MONAD2_GOAL_DISCOVERY`.
  - Why: the effect table is empty until something moves, and the flag-gated `fx_dpad` path stays off.
  - Done when: a fresh d-pad level tries each legal direction at most once, records the geom that moved, and does not call `_fx_learn`.
  - Depends on: `roles.note_effect`.

- [ ] **Use the geom delta from `note_effect` as the effect table.** Do not turn on `MONAD1_EFFECT_MODEL`, `MONAD2_REHEARSAL`, or `MONAD2_CALLOSUM` to fill `fx_dpad`.
  - Files: `roles.note_effect`, `coordinate.observe`. `MyAgent._fx_learn` stays flag-gated.
  - Why: `fx_dpad` keys a color. The controllable is a geom.
  - Done when: after two translations the enumerator knows the moving geom, and `fx_dpad` is still empty.
  - Depends on: the probe item.

### Goal hypotheses

- [ ] **Carry the candidate as `state["hypothesis_target"]`.** Do not write it into `role_evidence["goal"]`. `precondition("approach")` stays strict: approach requires a confirmed goal.
  - Files: `coordinate._state`, `primitives.precondition`.
  - Why: a candidate is not a completion. Diagnosis fix 1 stays in force.
  - Done when: during a walk, `role_evidence` has no goal key, and the target geom is only on the ephemeral state. It is cleared when the level changes.
  - Depends on: the enumerator.

- [ ] **Aim `step_toward` at that ephemeral box when the goal geom is missing.** If both boxes are unique, step around wall geoms and `route_blocks`. If the goal role is bound, the existing branch is unchanged.
  - Files: `primitives.step_toward`, `primitives._around`.
  - Why: `step_toward` returns None while the goal is unbound, so the walker cannot start.
  - Done when: goal role empty, target box set, a wall between them, the returned step is not into the wall. Palette and D4 do not change the step.
  - Depends on: `hypothesis_target`, and the checked route memory (`3c00ed3`).

- [ ] **Point labeled `explore` at the candidate.** `expand_action` currently calls `suggest_action("explore")`, which picks any non-progress direction.
  - Files: `planmode.expand_action`, `primitives.suggest_action`.
  - Why: the log has to show a hypothesis rather than a confirmed approach, and the step still has to move toward the object.
  - Done when: with a REACH candidate and no goal role, the expanded action is the step toward that box, and the step is marked labeled.
  - Depends on: the `step_toward` branch.

- [ ] **Refute a candidate inside the level, then take the next one.** Refute when the mover touches it and the level did not complete, when the press budget is spent, or when the walk budget is spent. The refutation dies with the level.
  - Files: `planmode.note_result`, the enumerator, `coordinate._touch_level`.
  - Why: touching the wrong object must not be stored as the goal, and it must not end the level's search.
  - Done when: a unit walk that contacts a decoy clears that geom from the live list and the next expansion aims at the following candidate, with the goal role still empty.
  - Depends on: labeled explore, `note_result`.

- [ ] **Record an adjacent no-op that is not a wall as a conditional edge.** Do not put it in hard `route_blocks`. Switch to another unique object whose interaction changes something other than the avatar. When a non-avatar relation changes, clear the conditional edge and retry the first candidate.
  - Files: `primitives.note_route`, `planmode._note_walk`.
  - Why: the hand-fed `ls20` approach walks an open corridor, the entrance step does not translate, and today's code treats that edge as a wall and spends the repeat elsewhere. This is the general form of that refusal.
  - Done when: a unit case stores the edge as conditional, a later non-avatar change clears it, and the next step can enter again. No game id and no coordinate in the test's assertion message.
  - Depends on: the refute item. Does not depend on a live run.

- [ ] **Stop treating receptor and reference as enough to open a plan.** `ready` may become true when a controllable is bound and at least one candidate exists. The script's target is that candidate, not the HUD.
  - Files: `planmode.ready`, `planmode.parse_plan`, `coordinate._maybe_script`.
  - Why: entry 16 planned align, hold_gradient, and convey at the hollow rect and the co-moving part.
  - Done when: receptor and reference alone do not produce an align plan while a REACH candidate exists. The script primitive is the labeled explore toward that geom.
  - Depends on: the enumerator and labeled explore.

### World model

- [x] **Remember a blocked edge for the rest of the walk.** A successful step does not clear `route_blocks`. `_around` treats those edges as walls. A sealed dead end blocks the entrance.
  - Files: `primitives.note_route`, `primitives._around`, `primitives._seal`.
  - Why: the greedy step was turning back into the wall it had just left.
  - Done when: `test_plan.py` still shows a failed up staying blocked after a successful left, and the next step from the new cell is up.
  - Depends on: nothing.
  - Commit: `3c00ed3`.

- [ ] **Simulate the walk from the known quantum and the blocked edges, and run that prefix in execute mode.** `_around` already returns the first step. Extend it to a prefix. This is not a neural net, and it is not `_ggl_bfs_path`.
  - Files: `primitives._around`, `planmode.expand_action`, `coordinate._finish_fast`.
  - Why: most actions have to be chosen with no model call. GGL's BFS is keyed by color (`ggl_hazard_colors`) and `decide` throws it away.
  - Done when: given a quantum and a blocked edge, the prefix's first step matches `_around`, later steps do not cross that edge, and no call to `_ggl_bfs_path` or `_fx_predict` is required.
  - Depends on: the ephemeral `step_toward` branch.

### Planning

- [x] **Tell the model a hypothesis is not a goal, and reject a repeated plan.** The replan prompt includes the failed predicate, the geom that moved, and the failing action. `reject_same` bans that signature.
  - Files: `planmode.PLAN_SYSTEM`, `planmode.prompt`, `planmode.reject_same`, `coordinate._maybe_script`.
  - Why: diagnosis fix 6. Four replans on the old `ls20` trace were the same JSON.
  - Done when: `test_plan.py` rejects an identical replan and the prompt builder still adds those three fields.
  - Depends on: nothing.
  - Commit: `271fca7`.

- [ ] **Ask Mistral only when the candidate list is stuck.** The prompt lists the geoms still alive and the watch type. The model picks a type or a primitive. Code binds the geom. `PLAN_SYSTEM` keeps the sentence that a hypothesis is not a goal. The grammar token is a role name or `explore`, not a coordinate.
  - Files: `planmode.prompt`, `planmode.plan_grammar`, `planmode.parse_plan`, `llm.get_backend`.
  - Why: entry 16 spent model calls choosing among HUD primitives. The model is not supposed to pick the next cell.
  - Done when: a prompt built from two live geoms and leader REACH contains those geoms and the type, and `parse_plan` accepts `explore` without a coordinate literal. `source_violations` stays empty.
  - Depends on: the enumerator and the ready-rule change.

- [ ] **Do not let the two-action `state["plan"]` run ahead of the candidate script.** `_remember_plan` stores up to two raw actions. `_follow_plan` runs them before `_maybe_script`, and they have no predicate.
  - Files: `coordinate._remember_plan`, `coordinate._follow_plan`, `coordinate.decide`.
  - Why: an unpredicated pair can steal the steps the candidate walk was about to take.
  - Done when: with a candidate script in execute mode, `decide` expands that script and does not pop `state["plan"]`.
  - Depends on: the candidate script.

### Execution

- [x] **Count a walk by successful steps, and keep a press on one anchor.** One true translate does not retire approach, convey, or route. Toggle and cycle_select stay on `anchor_i` until the predicate changes or the failure budget is spent, then the next affordance. The failure budget stays separate from `repeat`.
  - Files: `planmode.note_result`, `planmode._note_walk`, `planmode._note_press`.
  - Why: diagnosis fixes 3 and 4. The old `repeat` was a failure cap, and the first frame change left the pump.
  - Done when: `test_plan.py` still holds those two cases. The hand-fed `vc33` plan, three presses, predicate geom equal to the unique object that click translates, still reaches level 1.
  - Depends on: nothing.
  - Commit: `271fca7`. Hand-fed click clear rechecked at `9610309` (ledger entry 16).

- [x] **On a click-only legal set, drop SIMPLE, avatar, and hold_gradient from the grammars.**
  - Files: `llm.grammar_for`, `llm.drop_directional_roles`, `menu.executive_grammar`, `planmode.plan_grammar`.
  - Why: diagnosis fix 5. The click-game executive was emitting a direction.
  - Done when: `test_plan.py` still shows a click-only grammar with no SIMPLE alternative and no avatar role.
  - Depends on: nothing.
  - Commit: `271fca7`.

- [ ] **Bind a click candidate to the unique geom the click translated.** Skip a geom whose count is not 1. Stay on that anchor for the press budget. `note_effect` already refuses a shared geom. The enumerator has to use that result instead of walking the affordance list one press each.
  - Files: `roles.note_effect`, `planmode._note_press`, `menu.resolve_choice`, the enumerator.
  - Why: the hand-fed pump plan clears level 1. The live-anchor search, one press each, does not. Entry 15's first anchor was not the object that finishes the level.
  - Done when: a fixture with two objects of one geom does not bind switch, and a unique translated geom keeps `anchor_i` at 0 across two frame-changing clicks.
  - Depends on: the enumerator and the checked press accounting.

- [ ] **Lock the meaning of a None predicate.** `evaluate` returns None when the geom is missing from one side. `_note_press` spends the budget on None. That is right for a missing geom and wrong for a dropped diff.
  - Files: `predicates.evaluate`, `planmode._note_press`, `coordinate.observe`.
  - Why: `observe` must pass both shape-record lists. A missing `after` list would burn the anchor budget on a bookkeeping gap.
  - Done when: a unit check with both record lists and a missing geom returns None and spends one failure, and a unit check where `observe` is given both lists does not call `evaluate` with an empty `after` unless the document really had no shapes.
  - Depends on: the checked `observe` path (`271fca7`).

### Replanning

- [ ] **A false predicate on a candidate does not call the model.** Refute that candidate and stay in `execute` on the next one. Call the executive when the next candidate would repeat a signature in `rejected_sigs`, or when `note_effect` added a role the enumerator did not have, such as a new switch or a new hazard. Then one replan, then execute again.
  - Files: `planmode.note_result`, `coordinate.observe`, `coordinate._maybe_script`, `planmode.reject_same`.
  - Why: entry 16 replanned inside a family of HUD plans because every replan still had no goal object.
  - Done when: a unit sequence of two failed candidates produces no backend call, and a third step that introduces a switch calls the executive once.
  - Depends on: refute, the ready-rule change, and the "ask Mistral only when stuck" item.

### Time, so the live run is affordable

- [ ] **Short-circuit execute.** After `observe` has consumed the previous step, if `mode == "execute"` and `expand_action` returns a legal action, return it from `maybe_replace_key` and do not run GGL, the solver tier, or the canvas BFS on that step.
  - Files: `runtime.maybe_replace_key`, `MyAgent._choose_action_impl`, `planmode.expand_action`. Perception (document, diff, `note_step`) still runs.
  - Why: those searches still run today, and `decide` discards their key. A model call is 30–40 seconds. An execute step must stay at 0 model seconds.
  - Done when: a unit agent in execute mode with a legal expansion returns the action with no backend and without calling `_ggl_propose_plan`.
  - Depends on: labeled explore and the candidate script. This is step 5 of the M1 build order. The live run depends on it.

### Verification

- [ ] **Re-run the hand-fed click plan before any live game.** Solvers off. The winning trace is used only to name the binding.
  - Files: the existing executor (`planmode`, `predicates`, `roles`). The driver stays outside the agent modules.
  - Why: M1's click game uses this path. A regression here means the live run is not worth starting. The hand-fed d-pad approach is not required to pass: it aims at the exit and is refused, and the candidate walk is what leaves that line.
  - Done when: three clicks, predicate geom the unique translated object, level 1. If this fails, fix the executor and do not start the live run.
  - Depends on: the checked press accounting, and the click-candidate item if that item changed `note_effect` or `note_result`.

- [ ] **Play M1 live.** `ls20` first, then `vc33`. No session clock. Harness `--max-game-seconds` high enough that the clock is not the stop. The stop is the standing rule.
  - Files: `run_competition_eval.py` as the driver only.
  - Why: this is the milestone.
  - Done when: `ls20` level 1 completes, then `vc33` level 1 completes. For each game the note records levels, actions, LLM calls, the step where the controllable bound, the candidate geom pursued at the clear, and the plan text. `general_guard.HITS` is empty.
  - Depends on: every open M1 item above, including the hand-fed click check. Do not start until those unit checks pass.

- [ ] **If M1 clears nothing, record the new first break and stop.** Do not add another perception heuristic. Do not start `vc33`. Do not start M2.
  - Files: `monad2/SCORECARD.md`, `monad2/scorecard.jsonl`.
  - Why: entry 16. A 0-level run is not healthy and is not a reason to keep spending compute.
  - Done when: the ledger entry says killed, 0 levels, the plan at the kill, and the first break. The next milestone is not started.
  - Depends on: the live M1 item.

## M2 — level 1 on five games

Only after M1 passes. The five games are chosen before looking at the new results. They span a d-pad legal set, a click-only legal set, and a hybrid legal set. The M1 pair counts as two of them. The other three are named in the eval command, not in agent code.

### Coverage

- [ ] **Name the other three games in the harness invocation only.**
  - Files: the eval command. No edit under `monad2/` that contains a game prefix as a selector. `general_guard.ACTIVE_MODULES` stays clean.
  - Why: five legal-set shapes, without a per-game branch.
  - Done when: the command line lists five games, `static_violations` is empty, and the agent source still has no game prefix.
  - Depends on: M1 passed.

### Memory and transfer

- [x] **Holdout prefixes do not write a schema or an episode goal.** `upsert` and `discovery.remember` return without writing when `MONAD2_HOLDOUT_GAME` is one of `cd82`, `ft09`, `m0r0`, `tn36`, `tr87`.
  - Files: `schema.upsert`, `schema.holding_out`, `discovery.remember`.
  - Why: the holdout was fixed before the factorial screen. Writing it would leak the confirmation set into memory.
  - Done when: `test_schema.py` still shows a holdout `upsert` as a no-op.
  - Depends on: nothing.
  - Commit: `cdd1719`.

- [x] **A stored goal is dropped when this frame has no goal role.** The bias, when it exists, is an order over candidates. It is not a filled-in goal.
  - Files: `schema.drop_contradictions`, `schema.hypothesis_line`.
  - Why: entry 15 rebound goal from schema S0 onto the HUD hollow rect.
  - Done when: a match against a stored goal renders text and does not set `role_evidence["goal"]`.
  - Depends on: the checked "goal stays empty until completion" item.
  - Commit: `271fca7`.

- [ ] **On a completion, store the confirmed goal geom and try that geom first on the next level.** The stored item is a geom and a type. It is not a box and not an action list. `scp.project`'s smallest-object controllable must not become the transferred avatar. `note_effect` is the avatar.
  - Files: `schema.upsert`, `schema.match`, the enumerator, `roles.note_effect`. `scp.project` stays a token source, not the binder.
  - Why: M2 is the first milestone where transfer is allowed to matter. M1 does not need it.
  - Done when: after a synthetic completion, the next episode's candidate list puts a live object of that geom first, the goal role is still empty until the new level completes, and a palette permutation does not change the stored geom.
  - Depends on: M1's completion path actually writing the goal, and the enumerator.

### Verification

- [ ] **Play the five games.** Same flags as M1. Stop when the first three finish at 0 levels.
  - Files: `run_competition_eval.py` as the driver.
  - Why: this is the milestone.
  - Done when: each of the five completes at least level 1. The note has the same trace fields as M1. `HITS` is empty. A game that finished by replaying `solved_plans_by_level_idx` or `last_solved_plan` is not a pass.
  - Depends on: M1 passed, the three extra games named only on the command line, and the transfer item.

- [ ] **If the first three games finish at 0 levels, record the abort and stop.** Do not start M3. Do not describe the run as healthy.
  - Files: `SCORECARD.md`, `scorecard.jsonl`.
  - Why: the standing stop rule. Entry 14 is the pattern: partial, 0 levels, not a score.
  - Done when: the ledger says aborted, lists the games that finished, and M3 is not started.
  - Depends on: the five-game run.

## M3 — the time budget

Only after M2 passes. Same five games. Harness cap 300 seconds. Solvers off. Coordinate on.

### Time

- [ ] **Confirm the M1 short-circuit is what the five-game run actually uses.** Execute steps must not enter `_ggl_propose_plan`, the solver tier, or the canvas BFS.
  - Files: `runtime.maybe_replace_key`, the M1 short-circuit.
  - Why: M1 added the bypass. M3 checks that the measured run took it.
  - Done when: the per-step log shows execute steps at 0 model milliseconds, and a counter of skipped GGL proposals is greater than zero on a game that walked.
  - Depends on: the M1 short-circuit item and an M2 pass.

- [ ] **Run the five games inside 300 seconds and apply the numeric gates.**
  - Files: `run_competition_eval.play_single_game` (`max_game_seconds=300`).
  - Why: a clear that spends a model call on every step does not fit the harness the benchmark will use.
  - Done when: every game that cleared level 1 in M1 or M2 still clears level 1; on each of those clears at least four of every five actions make zero LLM calls; model calls per cleared level are at most eight.
  - Depends on: M2 passed, and the short-circuit confirmation.

- [ ] **If a clear needs a model call on every step, fail M3 and do not start the benchmark.** Record the counts. Do not call the run healthy if it also cleared nothing. A clear that misses the ratio is a failed milestone even though the level completed.
  - Files: `SCORECARD.md`, `scorecard.jsonl`.
  - Why: the plan's gate in front of the 25-game run.
  - Done when: the ledger states the three numbers and says the benchmark was not started.
  - Depends on: the 300 second run.

## Full benchmark

Only after M1, M2, and M3 pass.

- [ ] **Seed 0, all 25 games, blind and offline.** `--offline --blind-id --no-game-solvers`, 300 seconds, `MONAD2_COORDINATE=1`, other Monad(2) flags off, `PYTHONHASHSEED=0`. Same action accounting as entry 1.
  - Files: `run_competition_eval.py`.
  - Why: this is the score the ledger is for. It is not a place to discover the agent.
  - Done when: the run finishes, or the stop rule fires. `HITS` is empty either way.
  - Depends on: M3 passed.

- [ ] **Stop when the first three games finish at 0 levels.** Record it the way entry 14 was recorded. Do not resume it. Do not rewrite entry 14.
  - Files: `SCORECARD.md`, `scorecard.jsonl`.
  - Why: the standing rule. Entry 14 is 10 of 25 games, 0 levels, 98 actions, and it is not a score.
  - Done when: the new entry says aborted, names the three games, and the process is dead.
  - Depends on: the seed-0 run having started.

- [ ] **Three seeds only after seed 0 clears levels on more games than the M2 set.** Until then, do not spend seeds 1 and 2.
  - Files: the harness seed argument.
  - Why: entry 5 and entry 7 already showed a three-seed screen that did not beat entry 1. Another one waits on a seed-0 gain.
  - Done when: either seeds 1 and 2 are not started, or seed 0's per-game levels are in the ledger and cover more than the five M2 games.
  - Depends on: seed 0 finishing without the three-game abort.

- [ ] **Write the ledger entry against entry 1.** Comparison point: 19/183 levels, 42,729 actions, commit `98227b8`. Optimal count 6,444. No flag turns on by default because a benchmark happened. Traces are not copied into the agent. `environment_files/` stays unimported.
  - Files: `SCORECARD.md`, `scorecard.jsonl`.
  - Why: a finished run is the only thing that can sit next to entry 1. An abort cannot.
  - Done when: the entry has levels, actions, seeds, and a pass/fail against "no more actions than entry 1 for at least as many levels." PR #2 is updated. PR #1 is not.
  - Depends on: the seed-0 run reaching a real finish or a recorded abort.
