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
