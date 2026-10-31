# Monad(2) data flow to the action

This map is what the code reads when it picks an action. A field that is only copied into `self_narrative` or the action's reasoning blob is a sink. Sinks are listed so a zero single-module ablation is not mistaken for "nothing downstream could care."

Kyle's rule for gaps 4, 7, 8, and 9: do not drop a module because turning that module off alone changed 0% of actions. A module stays in the default path only when a measured influence path reaches the action, either directly or through a consumer. The screen for that path is the per-level fractional factorial (`monad2/factorial.py`), not a stack of one-module suites. Nothing in this file is on by default.

## What can change the action

| Source | Consumer | What changes |
| --- | --- | --- |
| Canvas A* (`SecondOrderCognitiveCanvas.audited_first_raw_aid`) | d-pad ordering in `_rank_direction_ids` | first direction, when the audit passes |
| `canonical_to_raw_dpad` | that same A* audit, and macro execution | the raw id of a canonical step, only after a gauge flip |
| Qwen A/B verdict `INVERT_CANONICAL_DPAD_ON_OPEN_CORRIDOR_NOOP` plus `IntentSpec` | gauge flip and `planned_queue.clear` | the next action, only if that exact command fires |
| `IntentSpec` → tension engine | the Qwen verdict above, and the kappa<0 queue flush for one panel macro | same |
| Collapse guard, Skinner rewards, dead-action memory, hazard colors | click order, A* rejection, d-pad scores | search order |
| `GLOBAL_SOLVED_GEOM_PRIORS` / avatar priors | click rank, `_is_proven_sig`, avatar match | cross-game bias. `MONAD2_EARNED` ignores a residue below 2 until this episode adds a count |
| General goal engine plans | `planned_queue` | the committed plan |
| `MONAD2_REHEARSAL` | `_fx_pick_rehearsed` | which of the goal plans is committed |
| `MONAD2_SCP` | goal-type order, and the callosum when that flag is also on | type priority from the compact projection |
| `MONAD2_GOAL_MEMORY` | goal-type order | retrieval reads `monad2/fmf_corpus/records.jsonl` unless `MONAD2_RECORDS` is set, excludes the held-out game, and can relabel a record from a described change |
| `MONAD2_GOAL_DISCOVERY` | `maybe_replace_key`, then goal-type order | up to 6 early probes; the leading outcome vote adds 3 to that goal; a later outcome label is stored by affordance features. Holdout games do not write the store. Default off. Watch mode is the separate flag below and does not do this |
| `MONAD2_CALLOSUM` | `maybe_replace_key` | with a hypothesis, replaces the key only when the world model predicts more progress toward that goal; otherwise only when the alternative changes the frame and A's choice does not |
| `MONAD2_DLADDER` | `maybe_replace_key` | vetoes a predicted no-op, illegal, or hazard and re-picks, including a probe |
| `MONAD2_PLL_SURPRISE` | plan queue, `ggl_active`, `EpisodeLTP`, discovery votes | on a lock loss while a plan is active, clears the plan and demotes that goal hypothesis |
| stall fallback | the decision flags, then one level RESET | after 48 unchanged frames, a reset loop near the 600-step exit, or step 900 of a flagged level, those flags go off, the level-start residue (goal votes, gauge, HUD mask, responsive signatures) is restored, the level world model is rebuilt, and one RESET restarts the level |
| `MONAD2_TONIC` | goal BFS depth and rehearsal breadth | reads `inos_depth_budget` (default 4) |
| `MONAD2_SKIP_DEAD_ORGANS` | master loop | skips PLL, Gohst, observer, Qwen, tonic, joints |

## Wired, but the consumer is a sink today

These edges exist. Their outputs do not currently select the action unless a flag above is on.

- `MONAD2_GOAL_WATCH` reads each natural transition and the action-effect table built from those transitions. It freezes a start-of-level hypothesis and, at level clear, reset, or game end, labels the segment from the start frame versus the last in-level frame. Confirmed REACH/PLACE/MATCH labels are stored by affordance features. Holdout prefixes do not write the store. The flag is not a factorial column and does not change `maybe_replace_key`, the goal-type prior, or `m2_goal_hypothesis`.

- PLL report → observer standing wave, Merkle prune, Qwen packet. With surprise mode off, the probe is the live signature, so the lock is not a comparison to a prediction.
- Gohst coupling → PLL sharpness, Qwen's decoupled-exploration verdict, tonic's `coupling_coherence_r`. The decoupled verdict string is not the invert command the gauge branch checks.
- Observer field → Gohst dark-matter weights and the standing wave. Standing-wave energy is an input to tonic.
- Tonic `optimal_depth_budget` → IntScript spool and `self_narrative`. The search reads it only when `MONAD2_TONIC=1`.
- Joint 3 guard report → IntScript and the narrative. `is_tombstoned` has no caller. `ControllerState` is written and never read by a branch.
- Qwen packet fields other than the one invert command → narrative.

## Oscillator, observer, INOS

- Goal group: discovery probes write a hypothesis; goal memory and the episode store write the same prior; SCP adjusts it from the projection; rehearsal scores plans by predicted progress toward the goal object; callosum reads that hypothesis; PLL demotes it. The tenth factorial column is this group. Watch mode records the same kind of hypothesis and does not write the prior.
- Guard group: D-ladder and PLL. The ladder vetoes before callosum. PLL demotes after the step.
- Oscillator group: PLL, Gohst, tonic. Gohst writes PLL sharpness and tonic's coupling term. Tonic does not read PLL directly; the standing wave does.
- Observer-field group: field update, standing wave, dark-matter callback into Gohst.
- INOS group: the master loop as a whole (Merkle, PLL, Gohst, observer, Qwen, tonic, joints 3–5). `MONAD2_SKIP_DEAD_ORGANS` is that group, as one factorial bit.

Pairwise connections that can interact before an action are the rows in the first table plus Gohst→PLL, observer→Gohst, PLL→standing wave, and standing wave→tonic. The 32-run design estimates main effects clear of two-factor aliases. It does not separate those pairs from each other. A bit is a candidate only when levels it was on cleared games the baseline missed. Confirmation is a fixed-flag replay on `cd82`, `ft09`, `m0r0`, `tn36`, `tr87`, which the screen is not allowed to use for selection.

## Influence-path rule

Keep a factor off by default unless confirmation beats the baseline at no more actions. Do not delete PLL, Gohst, the observer, tonic, the joints, or `ControllerState` from the source on the strength of a one-module zero. Deletion would require the factorial contrast (factor on vs off) and the holdout confirmation both to show no path to a clear.

## Coordination path

`MONAD2_COORDINATE=1` is the only path that asks Qwen A', Qwen B', and Mistral for a move. It is off during score runs. The executive picks or inhibits one motor primitive from `monad2/primitives.py` and states its effect. Those primitives are the motion rules mined from the old solvers. The old methods stay in the agent for reference and are not called when solvers are disabled. The mapping of each method onto a primitive, and what was dropped, is `monad2/PRIMITIVES.md`. A two-action smoke on `ls20`, `lp85`, and `vc33` (entry 11) proposed those rules, inhibited one, and checked the effect. It is not a score run. Entry 12 binds roles from the frame and from action effects, including clickable and reference on click games, and scores the executive with a structured predicate (`translate`, `no_reverse`, `contact`, `match`, `changed`, `unchanged`). Confidence follows that predicate. A miss is a surprise on the PLL line. Qwen actions outside the legal set are repaired before the executive sees them. The executive then picks from a per-frame menu by index or by a role reference such as `click(clickable#2)`; the grammar admits only those choices, and code resolves a click to coordinates that stay off the schema. A stored binding is dropped when the live legal set contradicts it, including an avatar on a frame with no directional actions. Once the same roles have held for two steps and a goal-like role is bound, the executive writes one primitive plan. Code expands each step and checks its predicate with no model call until a predicate fails, a new role appears, the level resets, or four steps make no progress. That is plan-once mode. Discovery stays on until then.

A schema in `monad2/schema.py` is an abstract role and relation structure learned from play: avatar, goal, receptor, movable, switch, wall, hazard, trail floor, counter/HUD; contact, containment, shape match, paint, toggle, and a translate effect. Slots store `shape_geom_sig` only. `assert_structure` rejects `game_id`, a color, an absolute coordinate, a 4-tuple signature (that tuple carries the fill color), and an action list. `upsert` returns without writing when `MONAD2_HOLDOUT_GAME` is one of `cd82`, `ft09`, `m0r0`, `tn36`, `tr87`. The next episode matches stored schemas from other episodes and writes the binding into the `[schema]` line, including a rebound when the same role has a different geom. A document miss either rebinds the avatar geom or rejects that schema id for the episode.

| Component | Class | Proposes? | Evidence |
| --- | --- | --- | --- |
| `monad2/schema.py` role/relation matcher | GENERAL | yes, as a hypothesis the executive can use | no game-id key; geom is `(type, min, max)`; holdout `upsert` is a no-op |
| `monad2/canvas_stream.py` scene and `solver_name` | GENERAL | yes, as a phrase | phrases are "move the avatar onto the unique shape", "paint the remaining floor", "match the shape to the receptor", "click the unique switch shape"; the raw reason is not copied |
| `CanvasDocument` / `VectorShape.shape_geom_sig` | GENERAL | yes, as the scene | connected components; geom drops color and orientation |
| `SecondOrderCognitiveCanvas` meta labels, Model A proposal, Model B audit | GENERAL | yes, as `[meta]`, `[model_a]`, `[model_b]` | counts of repo meta ids; no game dispatch in `canvas_stream.py` |
| `monad2/scp.py` `project` and `validate_action` | GENERAL | yes, SCP line; D-ladder can reject | role tokens and legal/noop/hazard rungs |
| `monad2/memory.py` affordance retrieval | GENERAL | yes, as a goal hypothesis | overlap on `aff:*` features; a named game is dropped, not solved |
| `monad2/discovery.py` `remember` / `recall` | GENERAL | yes, episode FMF | holdout prefixes do not write |
| learned `fx_dpad` effect table | GENERAL | yes, as `[effect]` | shifts counted on this episode |
| `dead_actions` | GENERAL | yes, as a veto | per-state no-ops learned here |
| collapse `get_phi` | GENERAL | read into the stream | one phi for the live state |
| tonic depth | GENERAL | read into the stream | `inos_depth_budget` or the last tonic report |
| PLL mismatch line | GENERAL | yes, as `[pll]` | compares the stated expectation with the frame |
| general goal engine, visited BFS, operant click, kinematic trail | GENERAL | yes, only through the general phrase above | goal engine comment: pixels only, no game ids; `solver_name` will not pass a puzzle plan through |
| Qwen A' 0.5B, Qwen B' 1.5B, Mistral executive | GENERAL | yes | local GGUF, temperature 0, seed 0; no game table in `llm.py` |
| 27 old solver methods | reference only | no; their motion rules are the primitives | disabled tier raises `_GameSolversOff` before the methods run; `arm_solver_guard` records a call if one still happens; `monad2/PRIMITIVES.md` is the mapping |

`monad2/general_guard.py` scans `coordinate.py`, `schema.py`, `canvas_stream.py`, `scp.py`, `memory.py`, `runtime.py`, `llm.py`, and `discovery.py`. A known game prefix as a whole string literal, a compare operand, or a dict key is a violation. A sentence that names a past stall is not a branch. The guard's own denylist is not on that list. The coordination probe asserts the hit list is empty after blinded play.

The episode id is an attribute on the agent (`_m2_schema_ep`). It is not `id(agent)`, which Python reuses after a game object is freed; that reuse made every later game look like the same episode and refuse its own schema. A stored plan of up to two further actions is run without another model call when the previous step matched and the D-ladder accepts the action. A mismatch clears the plan. Model prompts are clipped for prefill; the logged stream is the full one. Generation caps are 48 tokens for A' and B' and 64 for the executive. Thread count is the machine CPU count.
