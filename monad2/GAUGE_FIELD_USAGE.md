# Gauge-field usage

Written 2026-11-01 8:00 AM CT. Read-only. No counters, no game run, no module disabled. Tree is `cursor/monad2-a533` at `7599191` plus this file. The organ implementations live in `my_agent_v7_inos.py`, which this branch inherits. PR #1 was not edited. Line numbers are that file unless a `monad2/` path is named.

Question: with `MONAD2_COORDINATE=1` and game solvers off (`--no-game-solvers` / `MONAD1_DISABLE_GAME_SOLVERS=1`), do the top-down gauge and observer fields change the action, the candidate order, a role, a predicate, or the executive's choice?

## Live path

`choose_action` calls `_choose_action_impl`. On a visible frame the order is:

1. Palette gauges, then the frame monad2 reads is saved (`24704`–`24709`).
2. Unless the frame is a blackout, `_observe_and_recover_adversarial_controls` (`25016`) then `_run_bottom_up_qwen_ab_and_observer_top_down` (`25019`) then `render_experience_of_experience` (`25028`).
3. The game-solver tier raises `_GameSolversOff` and is skipped (`25494`–`25752`). The General Goal Engine can still queue a key (`25807`–`25817`).
4. A queued or heuristic key is passed to `_materialize_action` (`25846` and the later heuristic returns). That calls `runtime.maybe_replace_key` (`22200`), which calls `coordinate.decide` when the coordinate flag is on (`monad2/runtime.py` `564`–`567`). `decide` returns its own key. The original key is discarded.
5. After `decide` returns, a d-pad id in `{1,2,3,4}` is passed through `canonical_to_raw_dpad` and that raw id is what `GameAction.from_id` emits (`22273`–`22290`).

The organ loop returns early only when `MONAD2_SKIP_DEAD_ORGANS=1` (`23546`). That flag defaults off (`monad2/factorial.py` `32`) and is not on for a coordinate run. A blackout skips the loop (`25003`–`25014`). Execute mode does not.

`coordinate._maybe_script` (`801`–`823`) skips the three local models when `mode=="execute"` and the current plan step expands. That short-circuit is inside `decide`, which runs after the organ loop. Execute steps still compute every field below. The unchecked TODO item "short-circuit execute" would be the first place the loop could be skipped; it is not built.

`roles.py`, `primitives.py`, `predicates.py`, and `planmode.py` contain no read of the gauge map, tonic depth, standing wave, Ricci scalar, or Gohst coupling. Role binding, `step_toward`, predicate checks, and plan expansion do not see these values.

## What the executive actually receives

`coordinate._stream` puts tonic depth, canvas audit, and the control-gauge sentence into the logged stream (`525`–`527`, and `canvas_stream._control_line` at `222`–`234`). `_for_model` (`646`–`676`) keeps `[roles]`, `[hypothesis]`, `[legal]`, `[menu]`, `[primitives]`, `[pll]`, `[schema]`, `[avatar]`, `[diff]`, and `[solver]` at the front and then clips to 700 characters. `[tonic]`, `[canvas]`, and `[control]` are not in that front list, so the field sentences are the first text dropped. The `[pll]` line that is kept is the plan-mismatch sentence (`_pll_line`, `411`), not the resonant-oscillator report.

`_influence` (`581`–`643`) increments `infl_tonic` or `infl_canvas` when the model's own `used` list or reason text contains those words. That is a counter of what the model claimed. It does not read the field and it does not change the key.

## Table

| Component | Computed live? | Consumed by decisions? | Where | Verdict |
| --- | --- | --- | --- | --- |
| Intent-vs-outcome tension | Yes, every non-blackout step | The boolean flags feed the Qwen stub. The numeric score does not select an action, a role, or a predicate | `evaluate_delta` `858`–`939`, called at `23566`. Stored on `last_outcome_delta` and `self_narrative` `23803`–`23805` | used only as the invert predicate's input; the number is logged |
| Open-corridor no-op flag | Yes, inside that same call | Yes, but only as the gate on the d-pad remap below. One no-op is enough: the stub increments the streak before it tests `streak >= 1` (`2829`, `2895`) | Flag set at `892` when the prior intent expected a board change, expected an open corridor, and the frame changed 0 pixels | used, rarely |
| Direction-reversed flag | Yes | The stub emits `INVERT_CANONICAL_DPAD_IMMEDIATELY` (`2892`–`2894`). The only map writer checks a different string (`23766`). Nothing else reads the command | `886`–`890`, `2892` | computed-but-ignored |
| Observer field (Ricci, metric gamma, Lorentz, magnetic vorticity, dark-matter potential, top-down omega) | Yes | No decision reads the numbers. Gamma scales a Merkle node weight (`23633`). The numbers are copied into the Qwen stub's hashed payload (`2883`–`2885`) and into `self_narrative` (`23866`–`23869`). The stub's if-ladder does not branch on them | `apply_environmental_field_effects` `1458`–`1545`, called at `23625` | computed-but-ignored |
| Bidirectional standing wave | Yes | Feeds tonic depth and the same hashed payload (`2884`–`2885`, `23821`). No action, role, or predicate reads `standing_wave_energy` or the regime | `compute_bidirectional_standing_wave` `1582`–`1616`, called at `23689` | computed-but-ignored |
| Gohst TSP oscillator and dark-matter redistribution | Yes | Tour cost and ghost weights stay inside the oscillator. `coupling_mode == DECOUPLED_ORTHOGONAL_EXPLORATION` can change the stub's command string to a Merkle operator name (`2904`–`2906`). That string is not the invert command, so the branch that writes the map ignores it | `step_bouncing_solvers_and_evaluate_coupling` `1769`, called at `23653`; redistribution at `1784` | computed-but-ignored |
| Resonant PLL | Yes. Legacy mode locks onto the live signature on purpose (`23672`–`23674`) | `pll_observation` returns `None` unless `MONAD2_PLL_SURPRISE=1` (`monad2/runtime.py` `632`), which is off. The lock bit is logged (`23813`) and hashed into the stub payload. It does not pick the key | `record_compressed_historical_point` `23647`; `evaluate_stream_and_middle_of_time` `23681` | logged-only |
| Associative Merkle sift, autobiographical episode, replay | Yes | `causal_efficacy_kappa < 0` clears `planned_queue` only when `active_macro_family == "monad1_scp_cegis_panel"` (`23784`–`23791`). Solvers-off never enters that family (`25494`). `decide` would discard the queued key anyway. Weights and hashes are narrative | `23578`, `23593`, `23606` | computed-but-ignored on this path |
| In-process Qwen A/B stub | Yes. HTTP is off unless `MONAD1_ENABLE_QWEN_AB_HTTP` or `INOS_ENABLE_QWEN_HTTP` is `1` (`2809`). The live cycle hashes a payload and applies the if-ladder at `2890`–`2906`. It does not call the GGUF models | The verdict string is read at `23754`. Only one command is honored. The other four commands are stored in `self_narrative["observer_top_down_cmd"]` (`23807`) | `run_bottom_up_ab_cycle` `2813`, called at `23736` | used only for the one command below; otherwise logged-only |
| D4 gauge map `canonical_to_raw_dpad` | The map starts as identity (`4687`). It is rewritten when the stub command is exactly `INVERT_CANONICAL_DPAD_ON_OPEN_CORRIDOR_NOOP`, the map is still identity, the last intent was a d-pad direction, the sticky-tile guard passes, that direction is in the open-corridor set, and the opposite is not (`23764`–`23776`). A second writer, observed-displacement recovery, can also rewrite it (`6058`–`6078`) while `active_macro_family` is `None` or one of the listed families (`6023`–`6034`). `online_general_goal` is not in that list, so recovery stops once the goal engine binds a family | Yes. `_materialize_action` applies the map after `decide` (`22274`). A non-identity map changes the button that leaves the process. Identity is a no-op, which is the usual case. The map is also copied into the `[control]` sentence (`canvas_stream.py` `222`–`234`), which the 700-character clip drops. `runtime.py` `150` and `181` save and restore the map across a baseline replay; that is not the coordinate decision | Writers: `23776`, `6058`–`6094`. Reader that emits the action: `22274` | used, conditionally. The numeric fields are not what this if reads |
| Click mirrors `click_mirror_x` / `click_mirror_y` | Initialized `False` (`4693`–`4694`). No assignment sets them `True` | The click path would flip coordinates (`22250`–`22251`) if either flag were true. Both stay false | `22250` | dead on this path |
| Tonic gate and depth budget | Yes. `evaluate_tonic_gate_and_lora_hub` (`3032`) reads standing-wave energy, Ricci, coupling, tension, and gamma, and writes `optimal_depth_budget` | `_m2_tonic_limits` returns the fixed search unless `MONAD2_TONIC=1` (`4518`). That flag is off. Depth is copied into the action reasoning blob (`22244`) and the `[tonic]` line. The GGL breadth that would use it (`18480`, `19016`) does not, and `decide` replaces the GGL key | Called at `23821`. Narrative at `23870`–`23871` | logged-only while the flag is off |
| INOS guard ladder, IntScript, NNC diff | Yes (`23836`, `23844`, `23854`) | Status strings land in `self_narrative` and in `act.reasoning` (`22240`–`22246`). No branch reads `arbitration_status` to accept or reject the key `decide` returns. `is_tombstoned` (`3278`) has no caller | Joints 3–5, `3096`–`3276` | logged-only. `is_tombstoned` is dead |
| `ControllerState` | Assigned in the organ loop (`23781`–`23801`) and overwritten later in the same step (`25825`, `26050`–`26060`) | The only read is `.name` into the narrative (`23879`). No branch selects an action from the enum | assignments listed above | logged-only |
| Second-order canvas audit | Yes, after the organ loop, still before the key is finalized (`25028`). `audited_first_raw_aid` is the gauge-mapped first step of a visual path (`3696`, `3716`) | Two heuristic sorts prefer that id (`19130`, `19263`). `decide` then replaces the heuristic key. `_canvas_line` (`coordinate.py` `362`) puts the audit in the stream and returns a proposal only if the audit passed; `decide` does not take that proposal as the action. `summary_metrics()` is stored on the reasoning blob (`22254`, `22281`) | `render_experience_of_experience` `3393` | computed-but-ignored on the coordinate path |
| Split-panel palette gauge | Yes, before `_m2_grid` is saved (`24704`), including with solvers off. It matches fixed cells (`23209`: `grid[0][0]==3`, `grid[2][2]==4`, `grid[16][40]==5`) and can rewrite colors | The rewritten grid is what monad2 perceives, so a lock changes roles and geometry. It also sets `_scp_split_gate_color_map`, which makes `s16_shifted` true (`23576`) and adds a gauge term inside the observer field (`1472`). That term does not itself select an action. This is the game-specific remap the TODO says to stop from touching the frame monad2 reads. It was not removed here | `23202`–`23345`, call `24704` | used, as a palette rewrite of the frame. The field term it feeds is ignored |
| Node-graph palette gauge | The function is called (`24705`) and returns the grid unchanged when solvers are disabled (`23355`) | No | `23348`–`23356` | dead on this path (early return) |
| Scaled-tile corridor walker | The body would write `canonical_to_raw_dpad[want_dir]` (`24519`). With solvers off the method is replaced by a stub that returns `None` (`16832`, `16848`–`16850`), and the solver tier is not entered (`25494`) | No | `_try_solve_scaled_tile_navigation` `24031` | dead on this path |
| Reducing valve | Only while `steps_in_level <= 2` (`23556`) | Writes `self_narrative["inos_valve_regime"]`. Nothing reads it to pick an action | `23558` | logged-only |

## Does top-down field processing influence behavior?

The numeric top-down fields do not. Ricci, omega, Lorentz force, dark-matter potential, standing-wave energy, Gohst coupling, PLL lock, tonic depth, IntScript, the NNC report, and `ControllerState` are computed on every visible step and then logged. They do not change the key `decide` returns, the role evidence, the predicate, or the plan expansion. With the default flags they do not change search depth either.

Two gauge mechanisms can change the button, and neither one reads those numbers.

- The d-pad map is applied after `decide`. It changes the emitted id only when it is not the identity. The organ loop writes a swap (`{1:2, 2:1, 3:4, 4:3}`) only for the open-corridor no-op command, and only when the opposite direction does not look open. The "direction reversed" command, which is the stub's response to motion going the wrong way, is computed and dropped.
- While `active_macro_family` is still `None` (or one of the families listed at `6023`), observed displacement can rewrite the same map. Once the goal engine sets `online_general_goal`, that recovery returns without writing.

The split-panel palette remap is separate from the oscillator math and does change the frame monad2 reads. It runs with solvers off.

On the code PR #1 inherits, there is no `decide` replacement when `MONAD2_COORDINATE` is off: `maybe_replace_key` returns the key it was given (`runtime.py` `571`). The canvas-aid preference and a queued plan therefore reach `_materialize_action` as the action, and the same post-hoc d-pad map still applies. The numeric field values still have no reader that selects the action. This report did not modify that branch.

Execute mode does not bypass the computation. The model short-circuit is real; the organ-loop short-circuit is not. Blackout frames and `MONAD2_SKIP_DEAD_ORGANS=1` are the only skips, and the second is off.

No counter run was added. Instrumenting each organ would mean editing the live loop, which this pass was not supposed to do. A short `ls20` run was not started. A 0-level run would not show that the fields are healthy.

## Minimal wiring that would make a field matter

Do not delete the organs, and do not turn Ricci or tonic depth on as a substitute for a goal. The coordinate gap is still that a hypothesis does not pick a target. The smallest wiring that uses a gauge output which already exists:

1. Honor `INVERT_CANONICAL_DPAD_IMMEDIATELY` in the same block that already writes `canonical_to_raw_dpad` (`23764`). Today that command is the one the stub emits when motion opposes the intent, and it is the command the writer ignores. One extra string in that condition is the whole change. Keep the sticky-tile guard.
2. Apply the map where the plan believes it is choosing a direction, or have `decide` return the raw id the process will emit. `step_toward` and `expand_action` speak canonical ids. `_materialize_action` can then swap the button after the predicate was aimed. The plan and the button disagree whenever the map is not identity.
3. Leave tonic depth, standing-wave energy, and the Gohst tour inside the narrative until a group ablation says otherwise. Enabling `MONAD2_TONIC` would change a search cap on the heuristic `decide` discards. Putting the numbers into the executive prompt would not bind a goal.

Stopping the split-panel remap from rewriting `_m2_grid` is a separate TODO item. It is not a field-wiring fix, and this pass did not touch it.
