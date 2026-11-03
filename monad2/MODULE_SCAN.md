# Module scan

Written 2026-10-31 7:10 PM CT. Static reading of the tree at `359c13e` (agent code `9610309`), plus the unit tests those modules already have. No game was played for this scan.

The question for each module is what the code does when `MONAD2_COORDINATE=1` and the 27 solvers are stubbed. A name or a docstring is not evidence. `WatchEpisode` says nothing on it is read by action selection; `coordinate._hypothesis_line` does read it, and `applicable` / `step_toward` do not.

## Top findings

1. The live action is chosen in `monad2/coordinate.py:decide`, called from `MyAgent._materialize_action` via `runtime.maybe_replace_key`. Everything V7 computed before that call, including a General Goal Engine path, is only the heuristic string in the thought stream.
2. The goal role is written in one place: `roles.note_effect` when `outcome == "completed"`. A level that has not completed has no goal. `approach` requires that role, so it is never offered. The menu that remains is align, route, hold_gradient, convey, assemble. That is the cycle in ledger entry 16.
3. A goal-type hypothesis does reach the executive. `observe` calls `watch_step(..., force=True)`. After two productive translations the line is `watch REACH unconfirmed; goal role unbound`. `planmode.prompt` appends it. No function turns that sentence into a box to walk toward or a click to repeat.
4. The code that already walks toward candidate objects is `MyAgent._ggl_plan_reach` / `_ggl_plan_match` / `_ggl_plan_push`. It runs on the solvers-off path (`ggl_enabled` is true when solvers are disabled). `decide` then discards the action. Its target key is `(type, color, x//4, y//4, w, h)`, which is palette and position, so it cannot be reused as stored memory.
5. `planmode.ready` treats receptor or reference as goal-like. A hollow shape (geom type 2) is always labeled receptor and reference. Planning therefore starts aimed at the HUD while the real goal is unbound.
6. Execute steps already skip the models (`_finish_fast` with 0 ms). Discover and replan do not. Entry 16 spent 64 LLM calls on 59 actions and cleared nothing. A three-call step is about 30–40 s, so a 300 s game can afford on the order of 8 such steps.
7. `choose_action` still rewrites the grid in `_scp_canonicalize_split_panel_palette` before monad2 sees it. That function matches hardcoded colors at fixed cells and remaps the palette. The node-graph canonicalizer returns the grid unchanged when solvers are disabled. The split-panel one does not.
8. The effect model `fx_dpad` is recorded only when `MONAD1_EFFECT_MODEL`, `MONAD2_REHEARSAL`, or `MONAD2_CALLOSUM` is on. The coordinate-only run does not learn it. `dead_actions` and the hash graph still update, and they only affect the heuristic key.

## Feed map, today

```
frame
  -> _scp_canonicalize_split_panel_palette   (may remap colors)
  -> CanvasDocument / VectorShape
  -> hash graph, dead_actions, tried, HUD masks, Skinner, collapse
  -> General Goal Engine plan  -> planned_queue -> heuristic key
  -> canvas A* audited_first_raw_aid (d-pad tie-break inside V7)
  -> _materialize_action
       -> runtime.maybe_replace_key
            -> coordinate.decide          REPLACES the key
                 -> _stream
                      canvas_stream.scene_brief
                      schema.hypothesis_line -> infer_roles(role_evidence)
                      scp.project            (tokens only)
                      discovery.leader(m2_watch.scores) -> hypothesis TEXT
                      primitives.proposals_for -> menu from bound roles
                 -> planmode script, or Qwen A' / B' / Mistral
                 -> primitives.step_toward / menu click
  -> env.step
  -> runtime.note_step
       -> coordinate.observe
            -> discovery.watch_step(force=True) -> scores, not a target
            -> predicates.evaluate
            -> roles.note_effect          goal only if completed
            -> planmode.note_result       walk / press budget
```

Off on this path, present in the tree: the 27 solver bodies (instance stubs), `MONAD2_GOAL_DISCOVERY` probes, FMF `retrieve`, callosum, D-ladder as a policy (the ladder still vetoes inside `decide`), rehearsal, PLL surprise, tonic depth, factorial row assignment. PLL, Gohst, the observer field, and the five INOS joints still run inside V7 and write narrative, Merkle weights, or IntScript. They do not choose the key once `decide` returns.

## Feed map that should exist

```
frame (raw, no palette remap)
  -> CanvasDocument records
  -> infer_roles + note_effect          controllable from motion
  -> watch leader + unique geoms        candidate list, ephemeral boxes
  -> step_toward / toggle on that box   no model call
  -> predicates.evaluate
       hit and level completes -> note_effect writes goal -> schema.upsert
       contact or budget fails -> refute that geom, next candidate
       adjacent no-op, not a wall -> conditional block, try another object, retry
       new relation the enumerator cannot see -> one Mistral replan
  -> next level: schema.match biases candidate order
```

V7 search, GGL color keys, and the three model calls stay off the per-step path. GGL's BFS idea and its progress measure are worth copying only after the target id is a geom, not a color.

## Live path in one pass

`run_competition_eval.play_single_game` builds `MyAgent` and calls `main`. `choose_action` catches errors and falls back to a reset, a center click, or SIMPLE 1. `_choose_action_impl` resets on `NOT_PLAYED` / `GAME_OVER`, canonicalizes the palette, stores `_m2_grid` and `_m2_avail`, updates the hash graph, and may push a GGL plan. Any queued action goes through `_materialize_action`, which calls `maybe_replace_key`. With `MONAD2_COORDINATE=1` that is `decide`. `decide` runs the primitive script with no model when `mode == "execute"` and the step expands; otherwise it calls A', B', and the executive. After the env steps, `note_step` calls `observe`.

`planmode.ready` becomes true after two discovery steps when a controllable role and a goal-like role exist. Goal-like includes receptor and reference, so a HUD hollow rect is enough. The resulting plan cannot name `approach` until `role_evidence["goal"]` exists, and that write happens only on completion.

---

## `my_agent_v7_inos.py`

26,283 lines. One process. The coordination path uses it as the body that owns the frame, the action, and a lot of unused machinery.

### `GameAction` shim and the embedded harness

The top of the file defines `GameAction.from_id` and a small `Agent.main` loop: `choose_action`, then `take_action`. `GameAction(3)` is not valid; callers must use `from_id`. This is the loop the eval harness drives.

Live: yes. Works: the harness completes games. Contribute: action execution. Must not use: nothing game-specific here.

### `Brg1BridgeClient`

In-memory BRG1 frame codec. Optional external daemon if `INOS_USE_EXTERNAL_DAEMON=1` and a binary exists. `solve_arc_task` and `_try_in_memory_ring_cropped_solve` run a D4 crop search on a byte payload.

Live: the client is constructed; `decide` does not read its solve result. Works: not on the level path. Contribute: nothing until a caller uses a crop hypothesis as a MATCH candidate. Must not use: any payload that is a stored board solution.

### `CanvasDocument` and `VectorShape`

`_vectorize` extracts connected components from the grid, skipping HUD rows and columns the agent has accumulated. Each shape carries a box, a click point, area, and `shape_geom_sig`. The geom used downstream is type and the two side lengths, with color and orientation dropped. `canvas_stream.shape_record` is the projection monad2 actually reads.

Live: yes. `hypothesis_line` stores these records on `state["frame_records"]`. Works: roles and predicates operate on them; entry 16 bound the translating pair from these records. Contribute: perception. Must not use: `sig` tuples that still contain fill color if they are written into a schema. `assert_structure` rejects a 4-int signature for that reason. Click points are ephemeral and must stay that way.

### `IntentSpec`, `OutcomeDeltaReport`, `IntentOutcomeTensionEngine`

`_materialize_action` builds an `IntentSpec` (expected avatar delta, open-corridor bit) and stores it. The tension engine compares a later canvas to that intent.

Live: the spec is written. `decide` does not read the tension value. Works: no level evidence. Contribute: feedback, if a missed delta became the predicate failure the replanner already receives from `note_result`. Must not use: the free-text `model_a_hypothesis`, which embeds the action key.

### Merkle forest

`MonadAssociativeMerkleTree` pre-builds a forest of procedure names, packs uint64 nodes, and answers Hamming queries. `record_autobiographical_causal_episode` and `replay_autobiographical_causal_chain` store lived `(state, procedure, action, next state)` episodes. `inos_merkle_log_solved_pattern` reinforces a winning procedure.

Live: the forest exists and some V7 gauges query it. The coordinate action does not. Works: not measured on a clear under solvers-off. Contribute: memory, only if the key is a role relation and a geom, not a board fingerprint or a procedure name tied to one puzzle. Must not use: `compute_fuzzy_fingerprint` as a game id, and any log of a solved action list.

### `InlineResonantPLLModulator`

Keeps a phase history and a fuzzy similarity against a probe signature. With `MONAD2_PLL_SURPRISE` off, the probe is the live signature, so the lock is not a comparison to a prediction (`runtime.pll_observation` returns None unless that flag is on).

Live: the object steps inside V7. Coordinate's `[pll]` line is `coordinate._pll_line`, which prints `state["mismatch"]` from the predicate, not this modulator. Works: the predicate mismatch line is real; the oscillator lock is not the thing that replans. Contribute: feedback, already covered by `predicates.evaluate`. Do not delete the modulator on a one-module zero. Must not use: a fingerprint as an identity.

### `DynamicPackedMerkleGraph`, `BitPackedMerkleNodeCodec`

Contiguous uint64 graph, Hamming top-k, collapse, prune. Support for the forest above.

Live: no action edge. Contribute: an index, if memory is ever stored as relations. Must not use: weights that were reinforced from a per-game solver win.

### `MultiSolverGohstTSPOscillator`

Three TSP tours (MST preorder, greedy, spiral 2-opt) on a warped distance, then a coupling score. Dark-matter weights come from the observer field.

Live: runs in the V7 master loop when `MONAD2_SKIP_DEAD_ORGANS` is off. The coupling score is not an input to `decide`. Works: factorial screens did not turn it on by default. Contribute: a tour over candidate objects, which `_around` and `_ggl_bfs_path` already do more directly. Must not use: a tour whose nodes are per-game coordinates baked into the forest.

### `ObserverFieldTensorState`, `ObserverGeneralFieldTheoryEngine`

A field updated from environmental change, a dark-matter redistribution, and a standing wave. The wave is an input to tonic. Tonic's depth budget is read by search only when `MONAD2_TONIC=1`.

Live: the field updates; `decide` does not read it. `[tonic]` in the stream is a depth number. Contribute: nothing required for level 1. Do not delete on a one-module zero.

### `BicameralSmallQwenAB`

An in-process A-then-B handoff with a SHA-256 token. It is not llama.cpp and it is not `monad2/llm.py`.

Live: no. The models that ran in entry 16 are `LocalLlama`. Must not use: this class as the executive.

### `INOSMetaReasoningEngine`

Five joints: tonic gate, arbitration plus an SCP guard report, IntScript compile, differential verifier, tombstone query. `is_tombstoned` has no caller. `ControllerState` is assigned (`USE` when a queue is non-empty) and no branch reads it. Joint output is copied into the action reasoning blob.

Live: the engine is stepped; the blob is a sink. Contribute: a place to record a contract. The contract that actually checks a step is `predicates.evaluate`. Do not delete the joints on a one-module zero.

### `SecondOrderCognitiveCanvas`

Paints a second grid of meta labels, runs an audited A* (`_critically_plan_and_audit`), and stores `audited_first_raw_aid`. `_rank_direction_ids` and a GGL preference read that id when the audit passes. `canvas_stream._model_lines` copies it into `[model_a]` / `[model_b]`.

Live: it can change the heuristic key. `decide` replaces that key. Works: the audit can veto a direction inside V7; entry 16's actions were the primitive script, not this A*. Contribute: perception of open corridor, already partly duplicated by `route_blocks`. Must not use: meta ids as a game dispatch. `solver_name` already refuses to pass a raw puzzle-plan reason through.

### Grid helpers

`_grid_from_frame`, `_diff_coords`, `_hash_interior`, `_hash_playfield`, `_solve_linear_mod`. Hashes key `dead_actions`, `tried`, and `state_actions`.

Live: yes, for the heuristic. Coordinate's own no-op memory is `route_blocks` / `blocked_here`, not these hashes. Contribute: world model. A hash that includes palette is not a transferable state id.

### `SmartDreamCollapseGuard`, `SkinnerOperantContingencyModel`

Collapse stores a resistance and a phi per hash. Skinner reinforces actions that changed the frame. Both affect click order and d-pad scores inside V7.

Live: heuristic only. `[collapse]` and `[skinner]` are stream lines. Contribute: a prior over actions that changed something. The predicate already distinguishes a real hit from a mere frame change. Must not use: a reward table keyed by a game.

### `Monad1ActionModelCNN`

A small conv net over 16 channels, trained from `_record_cnn_experience` when torch is present and `INOS_DISABLE_CNN` is not set. No coordinate caller reads its output.

Live: it may train in the background. It does not pick the action. Contribute: a learned transition, only after the analytic effect model is actually consulted. Must not use: weights fit on one game's palette.

### `MyAgent` world model and `choose_action`

Per-level state: `prev_grid`, `dead_actions`, `tried`, `visited` via hashes, `planned_queue`, `bfs_route_queue`, HUD sets, avatar bbox, `solved_plans_by_level_idx`, `learned_level_opt_plans`. On `full_reset` the executed action list is stored and can be replayed, including a blind replay from `last_solved_plan` during a blackout.

`_materialize_action` is the seam. `note_step` is called from the transition block around line 24842, before the next key is chosen, so `observe` runs on the previous action even when the next action is replaced.

Live: yes. Works: entry 16 showed the seam. The stored plan replay is a solution cache and must not be a source for the general agent. Blackout dead-reckoning (`_dead_reckon_step_on_mental_grid`) is a world model; it is not consulted by `step_toward`.

### General Goal Engine (`_ggl_*`)

On when solvers are disabled, unless `MONAD1_DISABLE_GOAL_ENGINE=1`. Three types, REACH, PLACE, MATCH, ordered by `_ggl_type_order` from the legal set, push votes, and optional SCP / memory / discovery flags (all off in the coordinate run).

`_ggl_reach_candidates` keeps components of size 1..150 whose color is not background, wall, hazard, or the avatar color, drops refuted keys, and sorts by color rarity then Manhattan distance. `_ggl_plan_reach` BFS-es on a color blocked-mask and returns a prefix of 6 actions (2 if a dynamic color looks like a sentry). It will not start while `steps_in_level < 8`, while untried d-pad actions remain and the novel-atom counter is under 4, or after the level has spent half its steps on GGL. `_ggl_plan_match` looks for two equal-size panels that differ. `_ggl_plan_push` looks for an object that has translated and a same-size static target. `_ggl_measure` is distance or mismatch count. A target reached without a level change becomes a decoy; 20 decoys with no credit stand the type down.

Live: the plan is queued, then `decide` replaces every action. Works: the machinery is real and unused by the executive. Entry 16's plans were align / hold_gradient / convey, not REACH prefixes. Contribute: goal inference and planning. Must not use: the color-and-coordinate target key, the rarity sort (a palette prior), or the hardcoded wait of 8 steps as if it were a rule of a game.

### Palette canonicalizers

`_scp_canonicalize_node_graph_palette` returns immediately when solvers are disabled.

`_scp_canonicalize_split_panel_palette` does not. It returns early on a 64×64 grid whose cells `(0,0)`, `(2,2)`, and `(16,40)` are colors 3, 4, and 5, and otherwise can lock a color map from samples in rows 16..48 and columns 40..62 and rewrite every pixel. `choose_action` applies this before `_m2_grid` is saved.

Live: yes, in front of perception. This is game-specific content on the live path. The general agent must read the frame before this rewrite. Do not delete the function until a group ablation says the baseline does not need it.

### The 27 solvers

Instance stubs when `MONAD1_DISABLE_GAME_SOLVERS=1`: the 26 methods in `_GAME_SPECIFIC_SOLVERS_RETURN_NONE` return None, and `_try_solve_kick_thruster_sliding_blocks` returns `[]`. `arm_solver_guard` wraps them again under coordinate so a call increments `general_guard.HITS`.

The bodies remain in the file. `monad2/PRIMITIVES.md` is the mapping onto motion rules. What each body still contains, and must not be copied, is a game id or family test, a palette, a coordinate, a fingerprint, or an action list. The motion rule that is allowed is the primitive: step toward a bound object, repeat an interaction, do not reverse, route around a block, match a reference, convey a pushed object.

| Method | Motion that was kept | What stays in the body |
| --- | --- | --- |
| `_try_solve_grammar_container_tree` | align, assemble | shelf and legend layout |
| `_try_solve_stencil_linear_constraints` | align | tile size, modular color constraints |
| `_try_plan_hybrid_switch_navigation` | toggle, approach | panel split, click coordinates |
| `_try_solve_loop_tile_cycles` | cycle_select | stored cycle |
| `_try_solve_symbol_grammar_translation` | cycle_select, align | glyph tables |
| `_try_solve_fluid_spill_routing` | route | channel coordinates |
| `_try_solve_midpoint_handle_orbs` | convey, avoid | tether coordinates |
| `_try_solve_hydraulic_columns` | toggle, route | column and pump colors |
| `_try_solve_kinematic_arms` | route, align | joint coordinates |
| `_try_solve_layered_stamp_peeling` | cycle_select, align | swatch palette |
| `_try_solve_cooperative_box_warehouse` | convey, avoid | player and box palette |
| `_try_solve_binary_program_panel` | toggle, approach | bit columns, bracket coordinates |
| `_try_solve_mirrored_avatar_merge` | assemble, avoid | stored trajectory |
| `_try_solve_node_graph_sentries` | approach, avoid | stride, sentry palette |
| `_try_solve_skewer_bead_threading` | route, align | lattice palette, search sequence |
| `_try_solve_shape_target_alignment` | align | deformer palette |
| `_try_solve_connector_piece_assembly` | assemble | piece coordinates |
| `_try_solve_mirror_reflection_targets` | align | mirror-axis coordinates |
| `_try_solve_attraction_merge_ecology` | assemble, convey | zone palette |
| `_try_solve_shape_color_rot_labyrinth` | align, cycle_select, avoid | icon index, rotation index |
| `_try_solve_rune_spell_labyrinth` | toggle, route | rune kinds, coordinates |
| `_try_solve_time_clone_circuits` | toggle, avoid | epoch search, stored sequence |
| `_step_gravity_shaft_mechanics` | route | camera track |
| `_step_peg_track_mechanics` | route, convey | track graph, search sequence |
| `_try_solve_kick_thruster_sliding_blocks` | convey | stored kicks |
| `_try_monad1_scp_cegis_panel_solver` | align | bit masks |
| `_try_solve_scaled_tile_navigation` | approach | scale factor, pointer coordinates |

`_disable_game_specific_solvers` is the live switch. The methods are not called. Entry 16 recorded 0 solver hits.

### Effect model (`_fx_*`)

`_fx_learn` counts color shifts into `fx_dpad`, `fx_push`, and `fx_mover`. `_fx_predict` replays the dominant shift. `_fx_probe_action` picks an untried action. Recording happens only when `fx_enabled` or `MONAD2_CALLOSUM=1`. Prediction arming happens only when `fx_enabled` or `rehearse_enabled`.

Live under coordinate alone: the tables stay empty. `discovery._apply_hypotheticals` would add those votes and does nothing without them. Contribute: world model. The identity has to become the translating geom, which `roles.note_effect` already computes, not the color.

---

## `monad2/`

### `roles.py`

`infer_roles` labels the frame. A hollow geom (type 2) becomes receptor and reference. A long thin shape, or a blocked-step geom, becomes wall. Avatar, movable, hazard, switch, clickable, and goal are copied from `role_evidence` only when that geom is unique on the frame. Clickable affordance points are still listed for every non-wall shape on a click frame, without a role. Relations: containment, contact, shape_match against the reference, an effect arrow once an avatar exists.

`note_effect` is the writer. A d-pad action collects unique translating geoms. One unique mover becomes the avatar. Several unique geoms that share one delta bind the largest by area (`_largest_part`); different deltas bind nothing. A known avatar that is no longer unique is dropped. A unique geom that touches the avatar and is not the avatar becomes movable. A click binds switch and clickable only when the frame changed and the geom under the click has count 1. A reset binds hazard. A completion walks movable, avatar, switch, clickable and writes goal when the count is at most 1.

Live: yes, from `schema.hypothesis_line` and `observe`. Works: unit tests in `test_roles.py` (shared geom does not bind, shared motion binds the larger part, shared-geom click does not bind switch, palette permutation and D4). Entry 16 bound avatar `[1, 3, 5]` and movable `[1, 2, 5]` on the first effect and never wrote goal. Contribute: perception and the controllable half of goal inference. Must not use: a smallest-shape fallback. It is gone from this file and still present in `scp.project`.

### `predicates.py`

`bind_predicate` picks a template from the primitive: translate, no_reverse, contact, match, changed, unchanged. `evaluate` compares two shape-record lists. Translate uses the geom's delta and the action's direction. `changed` is a translation, a vanish, or an appearance of that geom, not an in-place recolor. Contact is a bbox gap of at most 1. `render` is the string the log stores.

Live: yes. Works: `test_plan.py` and `test_roles.py`. The hand-fed click plan completes when the predicate geom is the object the click translates. A predicate that cannot be evaluated returns None, and `planmode._note_press` treats None as a miss. Contribute: feedback. Must not use: a predicate that names a coordinate.

### `primitives.py`

Ten names. `precondition` is the gate `applicable` uses. `approach` needs avatar and goal. `hold_gradient` needs a known progress axis and an avatar, not a goal. `convey` needs a movable and a goal or a receptor. `align` needs a receptor, a reference, or a shape_match. `toggle` needs a switch, a clickable, or a toggle relation. `route` needs an avatar and a wall or containment. `assemble` is broad (movable, or avatar and receptor, or clickable and a reference). `explore` is always appended and is excluded from the text line until nothing else applies.

`step_toward` returns one d-pad id toward a unique mover box and a unique target box. With a learned `route_quantum`, `_around` BFS-es (node cap `6*6*6`) treating `route_blocks` as walls. Without it, the step is greedy and skips a one-cell overlap with a wall role. `note_route` records a failed edge and seals a dead end. Success does not clear `route_blocks`. `suggest_action` for a walk calls `step_toward`. For toggle and cycle_select it clicks `affordances` at `anchor_i`. `contradicts_gradient` is true when the action is the reverse of the last productive step. `source_violations` rejects integer literals outside 0..6 and a set of banned names; the file currently returns none.

Live: yes. Works: `test_primitives.py`, `test_plan.py` (a wall stays blocked after a successful step away from it; one true translate does not retire the step). The hand-fed approach on the d-pad level walks the open line and is refused at the entrance, then spends its repeat off that line. Contribute: planning and action execution. Gap: `step_toward` returns None when the goal geom is missing, so a hypothesis cannot aim it.

### `planmode.py`

`ready` after `_DISCOVER` (2) stable steps with a controllable and a goal-like role. `parse_plan` accepts the ten primitives, including a labeled explore, and stores `repeat`, `walked`, `fails`, `anchor_i`, `fail_budget`. The grammar's repeat is 1..6 even though the executor will walk longer if a step says so. `expand_action` arms `step_target` / `step_role` / `anchor_i` and calls `suggest_action`. `note_result` counts a successful walk toward `repeat` and does not advance the step index until the count is met, the mover touches the target, or the failure budget (4) is spent. A press stays on one anchor until the budget is spent, then increments `anchor_i`. `prompt` adds the hypothesis line and, on a replan, the failed predicate, the moved geom, and the failing action. `reject_same` bans the previous signature and substitutes `alternate_plan`.

`PLAN_SYSTEM` tells the model to name goal only when the prompt lists goal, and that a hypothesis is not a goal.

Live: yes. Works: `test_plan.py` (toggle stays on one anchor, identical replan is rejected, click-only grammar). Entry 16's last plan was `hold_gradient(avatar,wall)` then `convey(avatar,movable)`. Contribute: planning, execution, feedback. Gap: the hypothesis sentence is not an input to `parse_plan` or `expand_action`.

### `coordinate.py`

`decide` builds the stream, follows a leftover two-action `state["plan"]` if there is no mismatch, otherwise `_maybe_script`. Execute that expands and passes the D-ladder returns with no model. A replan or a first plan calls only the executive (`max_tokens` 160). Otherwise A', B', and the executive are called. Grammars drop SIMPLE, avatar, and hold_gradient on a click-only legal set. An illegal or gradient-reversing choice is replaced. `observe` scores the predicate, calls `note_effect` and `note_result`, and sets `mismatch` when the predicate is false.

`_hypothesis_line` uses `m2_watch.frozen` or `leader(scores)` and always appends `goal role unbound` or `goal role confirmed by completion`. `leader` returns a type once its count is at least 2, even if the margin is 0.

Live: yes, the action. Works: entry 16, 59 actions, 0 levels, 64 LLM calls, goal empty on every decision. The two-action `state["plan"]` from `_remember_plan` can run ahead of the script and is cleared on mismatch. Contribute: the glue point. Gap: it never reads the hypothesis as a target.

### `discovery.py`

`score_change` votes REACH, PLACE, or MATCH from one transition. A change of more than 400 cells votes for nothing unless `allow_large`. A single-controller shift votes REACH. A containment or a second co-moving object votes PLACE. A panel-mismatch drop votes MATCH. `leader` needs a count of at least 2. `watch_step` with `force=True` skips the `MONAD2_GOAL_WATCH` flag, updates scores, and freezes when the margin is at least 1 after two changes, or after 12 steps. `next_probe` / `observe_step` run only when `MONAD2_GOAL_DISCOVERY=1`, which the coordinate run does not set. `remember` / `recall` are an episode store of feature tuples to a goal type; holdout prefixes do not write.

Live: `watch_step` yes, probes no. Works: `test_discovery.py`. A measured productive step of about 52 cells votes both PLACE and REACH when two parts move together; a second step that only translates the controller leaves REACH ahead. The leader is text, not a target. Contribute: goal inference. The missing use is the gap in entry 16.

### `schema.py`

`induce` builds a draft: hollow geom to receptor, a long bar to wall, one unique mover to avatar, an unbound goal slot only if the meta string contains `terminal_goal`. It does not copy the receptor into goal. `upsert` stores the draft unless `MONAD2_HOLDOUT_GAME` is one of the five holdout prefixes. Slots are geoms. `assert_structure` rejects a game id, a bare color, an absolute coordinate, a 4-int signature, and an action list. `match` retrieves another episode's schema. `drop_contradictions` drops a stored goal when the live roles have no goal, and drops an avatar on a click-only legal set. `hypothesis_line` writes `schema_obs`, `affordances`, `role_line`, and `frame_records` from `infer_roles`, then renders the match as text. `account` rebinds or rejects after a document miss.

Live: yes, as the role store for the step. The cross-episode match is text in `[schema]`. Works: `test_schema.py`. Entry 16 did not confirm a goal, so nothing transferable was written. Contribute: memory and transfer. Must not use: a schema row keyed by a game, or a rebound that fills goal from the previous episode's receptor. `drop_contradictions` already refuses the goal half of that.

### `scp.py`

`project` builds `ObjectIR` components, layout tokens, a feedback word (noop, shift, local, jump), a panel-mismatch count, and a toward-direction. The controllable role is the smallest object of size at most 36 that is not the largest mass. `validate_action` is the D-ladder: D0 illegal, D1 known no-op, D2 known hazard, D3 click outside 0..63, D4 reset. `raw_tokens` is an 8×8 majority downsample that still contains colors.

Live: tokens go into the stream. The ladder is called from `decide` and from `_follow_plan`. The smallest-object role is not what `infer_roles` binds. `grid_features` in memory is built from the projection, so a future retrieve inherits that controllable guess. Works: `test_projection.py` exists. Contribute: a compact percept and a legality veto. The smallest-object prior is the bug roles.py already removed; it must not come back as the controllable.

### `memory.py`

`grid_features` turns a projection and the legal set into `aff:*` strings. `retrieve` ranks corpus records by feature overlap and returns goal-type names. Schema-tagged records count double. `eligible` drops records that name the held-out game. `EpisodeLTP` promotes a type after two confirmations. `observe` calls `remember` only after a true predicate and two confirmations.

Live: the corpus is not read unless `MONAD2_GOAL_MEMORY=1`. The episode LTP object is written on predicate hits and misses. Entry 16 did not promote a type into the store. Contribute: transfer of a goal type, not of a target object. Must not use: a record that names a game or stores an action list. `load_records` should keep dropping those.

### `llm.py`

`LocalBackend` loads three GGUF files from `INOS_MODEL_DIR` (default `/home/ubuntu/models`). CPU, `n_gpu_layers=0`, `n_ctx=1024`, temperature 0, seed 0. Token caps: A' 72, B' 80, executive 128. `complete` clips the user string so system plus user stay inside a 1100-character budget. `grammar_for` and `drop_directional_roles` implement the click-only grammar.

Live: yes, on discover, plan, and replan. Works: entry 16's 64 calls returned parseable actions often enough to execute 43 scripted steps. Contribute: planning. Must not use: a game id in a prompt. The grammar does not have one.

### `menu.py`

`build_menu` lists legal SIMPLE ids and click affordances as indexed items. `resolve_choice` maps an index or a `click(role#k)` reference to an action key. Coordinates are resolved here and are not put in the plan text. `executive_grammar` admits only those choices; on click-only it strips directional roles and keeps the menu action line.

Live: yes. Works: `test_plan.py`. Contribute: action execution. Must not use: a stored xy in the grammar.

### `canvas_stream.py`

`scene_brief` turns the current document into shape lines, a playfield sentence, an avatar sentence, a control sentence, and diff events. `diff_records` classifies moved, vanished, and appeared shapes. `solver_name` maps the V7 reason string to one of four general phrases and does not copy the raw reason. `document_result` checks a free-text expectation against the diff and often returns None, which is why confidence uses the structured predicate instead.

Live: yes, the percept the stream is built from. Works: roles see its records. Contribute: perception and feedback. Must not use: a reason string that still contains a puzzle plan. `solver_name` is the filter.

### `runtime.py`

`init_agent` attaches `m2` counters. `note_step` always calls `observe` when coordinate is on, and calls `watch_step` a second time only when `MONAD2_GOAL_WATCH=1`. `maybe_replace_key` is the seam. The other flags (D-ladder as a policy, callosum, discovery probes) run only when those env vars are set. `_callosum_key` proposes a step from the SCP controllable toward the largest other object, and overrides only when a world-model delta says so. `_fallback_to_baseline` clears the factorial flags after 48 unchanged frames, a 600-step reset loop, or step 900, and asks for one RESET. It does not clear `MONAD2_COORDINATE`.

`earned_count` / `geom_count` implement `MONAD2_EARNED`: ignore a cross-game residue below 2.

Live: the seam and `observe`, yes. The flag policies, no. Works: `test_runtime.py`. Contribute: the place a candidate walk should short-circuit, before V7 spends the step building a key `decide` will ignore.

### `general_guard.py`

`ACTIVE_MODULES` is the coordination set, including roles, predicates, menu, planmode, primitives. `static_violations` flags a known game prefix used as a whole string literal, a compare, or a dict key. `KNOWN_GAME_PREFIXES` is the 25 three-to-four character ids. `arm_solver_guard` records a solver call. `solver_catalog_ok` checks the stub list matches the methods.

Live: armed when coordinate turns solvers off. Works: entry 16 had an empty hit list after the earlier scans. Contribute: the constraint. The denylist itself is not a selector. Docs are not in `ACTIVE_MODULES`.

### `factorial.py`, `analyze_factorial.py`

A 32-run resolution-IV design over ten flags. `HOLDOUT_PREFIXES` are `cd82`, `ft09`, `m0r0`, `tn36`, `tr87`, fixed before the screen. `assign_level` sets the env for one level from seed, slot, and level index. The slot is a position in the harness order, not a game id. `analyze_factorial.py` aggregates a result file.

Live: off unless `MONAD2_FACTORIAL=1`. `MONAD2_COORDINATE` is not a column. Contribute: the ablation rule. Do not turn a column on as a substitute for the missing target glue.

### `coord_probe.py`, `eval_watch.py`, `eval_fmf_retrieval.py`

Probe and retrieval drivers. `coord_probe._quiet_flags` clears `MONAD2_*` and `MONAD1_*`, then sets coordinate and solvers-off. Its sample writer can overwrite `monad2/COORD_SAMPLE.md` if pointed at the repo.

Not on the live path. Useful as harnesses. Must not use: a probe that writes a game id into the corpus.

### Tests

`test_roles.py`, `test_plan.py`, `test_primitives.py`, `test_schema.py`, `test_coordinate.py`, `test_discovery.py`, `test_memory.py`, `test_runtime.py`, `test_factorial.py`, `test_projection.py`. They construct frames in-process. They are the evidence cited above. They do not play a level.

---

## Harness and offline tools

### `run_competition_eval.py`

`play_single_game` makes an offline env, optionally wraps it in `BlindEnvironmentProxy` (the agent is given `blind_unknown_env`), sets `MONAD2_HOLDOUT_GAME` to the id prefix, and runs `agent.main`. Default cap is 300 s per game. `--no-game-solvers` sets `MONAD1_DISABLE_GAME_SOLVERS`. `--max-game-seconds` is how a no-clock check is requested. The process still stops at the harness cap, at `MAX_ACTIONS` (6000), and at the agent's own level step limits.

Live: this is the driver. It does not choose actions. Must not use: the env's source, or a scorecard that is fed back into the agent.

### `build_relation_memory.py`, `eval_relation_retrieval.py`, `aggregate_generalization_results.py`

Build and score a relation corpus, and aggregate result files. Offline. A corpus row that still carries a game name has to be dropped by `memory.eligible` before retrieve. Not on the step path.

### Docs

`README.md`, `ARCHITECTURE.md`, `MONAD_1_V7_PAPER.md`, `MATHEMATICAL_FOUNDATIONS.md`, `BENCHMARKS.md`, `REPRODUCIBILITY.md`, `AUTHORS.md`, and `monad2/DATAFLOW.md`, `PRIMITIVES.md`, `DIAGNOSIS.md`, `SCORECARD.md`, `COORD_SAMPLE.md`. They describe intent. Where this scan disagrees with them, the code wins. `DATAFLOW.md` is right that coordinate is the only path that calls the three local models, and it is behind the six-fix behavior: goal is no longer copied from the reference.

### `environment_files/`

Untracked game implementations, one directory per id. The harness loads them as ARC environments. The agent must not import them, and this scan does not copy their rules into a plan. They are evaluation-only.

---

## What is game-specific and must not be used

- The 27 solver bodies: ids, palettes, coordinates, fingerprints, stored sequences.
- `_scp_canonicalize_split_panel_palette`: fixed cells and fixed colors, and it still runs.
- GGL target keys that store a color and a coarse coordinate. Ephemeral boxes during one walk are execution state; they are cleared on plan install today (`route_blocks` is). They must not be written by `schema.upsert`.
- `solved_plans_by_level_idx`, `learned_level_opt_plans`, `learned_level_raw_plans`, and the blackout replay of `last_solved_plan`.
- `raw_tokens` and any SimHash of the raw grid, if used as a retrieval key across games.
- `environment_files/`.
- A branch, a prompt, or a schema keyed by a string in `KNOWN_GAME_PREFIXES`.

## Evidence index

| Claim | Where it was checked |
| --- | --- |
| Goal is written only on completion | `roles.note_effect` |
| Hypothesis text reaches the prompt and does not select a target | `_hypothesis_line`, `planmode.prompt`, `applicable`, `step_toward` |
| Avatar binds from a shared translation | `roles._largest_part`, `test_roles.py`, entry 16 |
| Walk repeat is successful steps; toggle stays on one anchor | `planmode.note_result`, `test_plan.py` |
| Hand-fed click plan can clear; hand-fed approach on the open corridor cannot | ledger entry 16 |
| Live run killed at 0 levels | entry 16, commit `359c13e` |
| GGL plan is replaced | `_ggl_propose_plan` then `_materialize_action` then `decide` |
| Solver methods are stubbed | `_disable_game_specific_solvers` |
| `is_tombstoned` has no caller | search of the tree |
| Split-panel palette remap still runs | `choose_action` before `_m2_grid` is saved |
