# Plan for a general ARC-AGI-3 agent

Written 2026-10-31 7:10 PM CT, from `monad2/MODULE_SCAN.md`. No run is part of this plan. Implementation comes later, one milestone at a time.

The agent that clears a level is mostly code that already exists. The missing piece is a target. Today a hypothesis names a goal type and nothing walks toward an object of that type, so the completion that would bind the goal never happens.

## Rules that stay in force

- No `game_id` branch, no fingerprint key, no hardcoded palette, no hardcoded coordinate, no stored action sequence. `general_guard.static_violations` and `schema.assert_structure` stay on the modules that propose a move.
- The 27 solvers stay in the tree as reference. The agent calls the primitives, not the methods. `arm_solver_guard` stays armed.
- Do not delete PLL, Gohst, the observer, tonic, the INOS joints, or `ControllerState` because one flag changed nothing. A deletion needs the factorial contrast and the holdout confirmation.
- Do not turn `MONAD2_GOAL_DISCOVERY`, `MONAD2_GOAL_MEMORY`, `MONAD2_REHEARSAL`, or any other factorial column on as a substitute for the glue below. Call the function the flag would have called, from the coordinate path, with an explicit input.
- Stop a run that is not passing levels. One game: stop by 100 actions, or earlier when the plan repeats and the evidence is not new. Several games: stop when the first three finish at 0 levels. A 0-level run is not healthy and is not a score.
- Evaluation traces are for scoring a milestone. They are not an input to the agent.
- `environment_files/` is not imported.
- PR #1 stays untouched. This work stays on PR #2 until a later instruction says otherwise.

## The break to close first

`roles.note_effect` writes `role_evidence["goal"]` only when the outcome is `completed`. That rule stays. A candidate is not a goal.

What has to change is everything that currently waits for that write before it will move toward an object:

- `primitives.precondition("approach")` requires a goal role, so `applicable` never lists approach.
- `step_toward` returns None when `_role_geom(obs, "goal")` is None.
- `planmode.PLAN_SYSTEM` tells the model a hypothesis is not a goal, which is right, and then no other code uses the hypothesis, which is the bug.
- `planmode.ready` treats receptor and reference as goal-like, so the executive writes align / convey / assemble against the HUD hollow rect.
- `MyAgent._ggl_plan_reach` already picks objects and BFS-es toward them, and `decide` throws the action away. Its key also stores a color, so the loop is reused only after the id is a geom.

The efficient policy is a deterministic candidate walk. The models are called when the walk is stuck, not when it is merely unfinished.

## Capabilities, in order

Each one names the functions to call, the glue to write, and the gap that is still empty.

### 1. Perceive objects and roles

Reuse:

- `CanvasDocument` and `canvas_stream.shape_record` / `diff_records` / `scene_brief`
- `roles.infer_roles` and `roles.note_effect`
- `schema.hypothesis_line` as the place that already stores `frame_records`, `schema_obs`, and `affordances`

Glue:

- Read `_m2_grid` from the frame before `_scp_canonicalize_split_panel_palette`. The remap is game-specific and it currently sits in front of perception. Leave the function in the file.
- Keep click points and boxes on the ephemeral state. Do not put them in `upsert`.

Gap:

- None for objects. The controllable binding is already the unique translating geom, or the largest part of one shared delta.

### 2. Explore to learn action effects

Reuse:

- `roles.note_effect` for what actually translated
- `primitives.note_route` and `blocked_dirs` for edges that did not
- `discovery.score_change` and `leader` for the type vote
- `discovery.watch_step` (already forced from `observe`)

Glue:

- A candidate enumerator, new, called from `coordinate.decide` when the goal role is empty. Suggested place: `monad2/candidates.py`, kept inside `general_guard.ACTIVE_MODULES`.
- Inputs: `frame_records`, `role_evidence`, the watch leader, the legal set.
- Output: an ordered list of `{kind, geom}` plus an ephemeral box. REACH: unique geoms that are not the avatar, not the wall, not a hollow type-2 HUD, and not the co-moving part already labeled movable. PLACE: the movable, paired with a static unique geom of the same shape. MATCH: two regions of equal box size that differ, which is the idea in `_ggl_find_panel_pair` without storing a color. Click legal set: the existing `affordances["clickable"]` list, one anchor at a time.
- Order by the leader. REACH first when REACH leads. Do not sort by color rarity (`_ggl_reach_candidates` does, and that is a palette prior).
- The first steps of a level, before any translation, try each legal direction once. That is `discovery.next_probe` without the flag: call it, or do the same one-liner in the enumerator. Stop probing a direction `dead_actions` or `note_route` has already recorded.

Gap:

- `fx_dpad` is empty on the coordinate-only path because `_fx_learn` is flag-gated. Do not turn the flag on. The geom delta from `note_effect` is the effect table. A color shift table is the wrong identity.

### 3. Infer goal hypotheses and test them

Reuse:

- `discovery.leader` and `_hypothesis_line` for the type
- `predicates.bind_predicate` / `evaluate` as the test
- `roles.note_effect` on `completed` as the only writer of the goal role

Glue:

- Pass the candidate geom into the walk as `state["hypothesis_target"]`. `step_toward` gains one branch: if the goal geom is missing and that ephemeral target has a unique box, aim at the box. Do not write the geom into `role_evidence["goal"]`.
- `precondition("approach")` stays strict for a confirmed goal. The candidate walk is a separate labeled step, `explore` aimed at a geom, so the log can tell a hypothesis from a confirmation. `expand_action` already has a labeled explore; it currently calls `suggest_action("explore")`, which picks any non-progress direction. Point it at `hypothesis_target`.
- Refute a candidate, in memory that dies with the level, when: the mover touches it and the level did not complete; the press budget is spent; or the walk budget is spent. Then take the next candidate.
- The entrance case, stated generally. The hand-fed approach walks an open corridor and the last step does not translate, and the cell is not a wall role. `note_route` today records that edge as a hard wall, so the walker leaves and spends the repeat elsewhere. Record it as conditional instead. Switch to another unique object whose interaction changes something other than the avatar. When a non-avatar relation changes, clear the conditional edge and retry the first candidate. That is the whole rule. No game id, no coordinate.
- `planmode.ready` stops treating receptor and reference as enough to open an align plan. A plan may start when a controllable is bound and at least one candidate exists. The script's target is the candidate.

Gap:

- Nothing in the tree ranks two REACH candidates by "this one changed a latent match." The conditional-edge rule above is the stand-in. A richer latent state (rotation, selector index) is not a stored object anywhere except inside the solver bodies, which stay unread.

### 4. World model and prediction

Reuse:

- `primitives._around` for the walk once `route_quantum` and `route_blocks` exist
- `MyAgent.dead_actions` and `tried` as "this action did nothing at this hash"
- `_ggl_measure` as the idea of a distance that should fall, reimplemented on boxes and geoms
- `_fx_predict` only after it is keyed by geom

Glue:

- Before spending a long walk, simulate it with the known quantum and the blocked edges. `_around` already returns the first step. Extending it to return the prefix, and running that prefix inside `mode == "execute"`, is the world model the step needs. It is not a neural net.
- Skip `_ggl_bfs_path` until its blocked mask is "geoms already marked wall or route_blocks," not "colors in `ggl_hazard_colors`."

Gap:

- No model predicts a click that changes a distant object before the click has been seen. The press budget is the experiment. Do not build a second simulator for that.
- The CNN is not on the action path. Leave it.

### 5. Plan with Mistral over primitives

Reuse:

- `llm.get_backend`, `planmode.prompt`, `plan_grammar`, `parse_plan`, `reject_same`
- The replan context that already includes the failed predicate, the moved geom, and the failing action

Glue:

- The executive is asked when the candidate list is exhausted, or when a step produced a new relation the enumerator does not represent. It is not asked to pick the next cell.
- The prompt gains one concrete line: the candidate geoms still alive, and the type the watch leader holds. The model chooses a type or a primitive. Code binds the geom. `PLAN_SYSTEM` keeps "a hypothesis is not a goal."
- Drop the two-action `state["plan"]` from `_remember_plan`, or run it only when no candidate script exists. It currently preempts `_maybe_script` and it has no predicate.

Gap:

- The grammar does not mention a candidate id. Add a token the parser already understands (a role name or `explore`), not a coordinate.

### 6. Deterministic execution with predicate checks

Reuse:

- `planmode.expand_action`, `note_result`, `_finish_fast`
- `menu.resolve_choice` for clicks
- `predicates.evaluate`
- `coordinate._ladder_ok`

This path already takes 0 ms of model time. The candidate walk should be this path from the second action onward.

Glue:

- Repeat for a walk is the step budget of that candidate, not a failure limit. The failure budget stays separate. Both already exist.
- Toggle and cycle_select stay on `anchor_i` until the predicate changes or the budget is spent, then the next affordance. The hand-fed click plan clears level 1 when the predicate geom is the unique object the click translates and the anchor does not move. The live click search that presses each anchor once does not clear. The executor already implements the first of those; the enumerator has to bind the geom the click actually moves, which `note_effect` does when the count is 1, and has to skip a shared geom.

Gap:

- `evaluate` returns None when the geom is missing from one side. `_note_press` spends the budget on None. That is correct for a miss and wrong for "the records were not passed." `observe` must keep passing `before` and `after` shape records, which it already tries to do. A unit check should lock that None means "geom absent," not "diff missing."

### 7. Surprise-driven replanning

Reuse:

- `planmode.note_result` surprise when the budget is spent or no direction is open
- `reject_same` and `alternate_plan`
- `observe` setting `mismatch` on a false predicate

Glue:

- A false predicate on a candidate does not by itself call the model. It refutes the candidate and the script continues at the next one, still in `execute`.
- The model is called when the next candidate would repeat a signature already in `rejected_sigs`, or when `note_effect` added a role the enumerator did not have (a new switch, a new hazard).
- One replan, then back to execute. Entry 16 replanned inside a family of HUD plans because every replan was still "roles without a goal." With candidates in the script, that loop should not start.

Gap:

- None beyond the glue. The tools are there.

### 8. Memory and schema transfer

Reuse:

- `schema.upsert`, `match`, `drop_contradictions`, `account`
- `memory.EpisodeLTP` and `discovery.remember` / `recall`
- Holdout no-write in `upsert` and `remember`

Glue:

- On completion, the goal geom is already in `role_evidence`. `upsert` may store it. The next level's enumerator tries a live object with that geom before the others.
- A transferred item is a geom and a type, never a box and never an action list.
- `drop_contradictions` already refuses a stored goal when the live frame has no goal role. Keep that. The bias is an order over candidates, not a filled-in goal role.
- `scp.project`'s smallest-object controllable must not become the transferred avatar. `note_effect` is the avatar.

Gap:

- Cross-game transfer has no positive evidence under solvers-off. Milestone 2 is where it is allowed to matter. It is not on the critical path for milestone 1.

## What stays unused on purpose

- Solver methods, solution replay, blackout replay of `last_solved_plan`.
- `BicameralSmallQwenAB`. The models are `monad2/llm.py`.
- Gohst tours, the observer field, Merkle fingerprints, IntScript, the CNN. They remain in the tree. They are not called by the candidate walk.
- `MONAD2_FACTORIAL` during milestone runs. A milestone is one configuration: coordinate on, solvers off, clock off, `PYTHONHASHSEED=0`.

## Time budget

Measured cost, entry 13 and entry 16: a discover step that calls A', B', and the executive is about 30–40 s. An execute step is 0 s of model time. The harness default is 300 s per game, so a game can afford about eight three-call steps.

Most actions have to be execute.

Glue, in `runtime.maybe_replace_key` or at the top of the search in `_choose_action_impl`, after `observe` has consumed the previous step:

- If `state["mode"] == "execute"` and `expand_action` returns a legal action, return it and do not run GGL, the solver tier, or the canvas BFS on that step. Those still run today, and `decide` discards them.
- Cap model calls per level. A clearing level should be one plan write plus a replan only when the candidate list is stuck. The pass number is in milestone 3.

`choose_action`'s perception (document, diff, `note_step`) still runs every step. That cost is small next to a model call.

## Milestones

A milestone that hits the stop rule is a failed milestone. Record it the way entry 16 was recorded. Do not start the next one.

### M1. Level 1 on two games, live, no clock

Games: `ls20` and `vc33`, in that order, because that is the pair already used for the hand-fed check. The agent code must not mention either id.

Configuration: `MONAD2_COORDINATE=1`, solvers off, no session clock, `PYTHONHASHSEED=0`, harness `--max-game-seconds` high enough that the clock is not the stop. The stop is the standing rule.

Pass:

- `ls20` level 1 completes. Then `vc33` level 1 completes.
- For each game, report levels, actions, LLM calls, the step where the controllable bound, the candidate geom that was being pursued when the level completed, and the plan text.
- `ls20` is killed at 100 actions, or earlier if the same plan repeats with no new predicate evidence. If it dies at 0, `vc33` is not started.

The hand-fed executor is the regression check before the live run, because it is cheap. It does not have to pass on `ls20` for M1 to be worth starting: the hand-fed approach aims at the exit and is refused, and the candidate walk is supposed to leave that line. It does have to pass on `vc33`, because that path is the executor the live click game will use. If the hand-fed click plan regresses, fix the executor before any live run.

### M2. Levels on five diverse games

Five games chosen before looking at the new results, spanning a d-pad legal set, a click-only legal set, and a hybrid legal set. The M1 pair counts as two of the five. The other three are named in the eval command, not in agent code.

Pass: each of the five completes at least level 1. Stop when the first three finish at 0 levels. Report the same trace fields as M1. A game that completes on a stored solver plan is not a pass; `general_guard.HITS` must stay empty.

### M3. The time budget

Same five games, harness cap 300 s, solvers off, coordinate on.

Pass, all of:

- Each game that cleared level 1 under M1 or M2 still clears level 1 inside 300 s.
- On each of those clears, at least four of every five actions make zero LLM calls.
- Model calls per cleared level are at most eight.

A clear that needs a model call on every step fails M3 even if the level completes. Do not start the full benchmark on an M3 failure.

### Full benchmark

Only after M1, M2, and M3 pass.

Twenty-five games, the harness blind-id offline setting, solvers off, 300 s, the same action accounting as entry 1. Three seeds only after seed 0 has cleared levels on more than the M2 set. Stop when the first three games finish at 0 levels.

Entry 1 remains the comparison point: 19/183 levels, 42,729 actions, commit `98227b8`. The optimal count is 6,444. An aborted or 0-level slice does not move either number. Entry 14 stays aborted. No flag turns on by default because a benchmark happened.

## Build order inside M1

1. Enumerator and `hypothesis_target`, with unit tests: a REACH candidate is a unique non-HUD geom; a shared geom is skipped; a hollow type-2 is not a REACH target; the list is stable under a palette permutation and a D4 turn.
2. `step_toward` aims at the ephemeral box. Unit test: goal role empty, target box set, a wall between them, the step is not into the wall.
3. Conditional edge. Unit test: a no-op adjacent to the target that is not a wall role is not stored as a hard `route_blocks` entry; a later non-avatar change clears it.
4. `ready` and the script use the candidate. Unit test: receptor and reference alone do not produce an align plan while a REACH candidate exists; the script's primitive is the labeled explore toward that geom.
5. Execute short-circuit. Unit test: with `mode == "execute"` and a legal expansion, `maybe_replace_key` does not need a backend.
6. Hand-fed click plan still clears. Then the live M1 run.

Do not start step 6 until steps 1–5 have tests. Do not add a seventh perception heuristic if step 6 dies at 0. Record the new first break and stop.
