# Motor primitives

The old solver methods stay in `my_agent_v7_inos.py` for reference. With game solvers disabled, that tier is not entered. The coordination path does not call them. What they knew about motion is the primitive list below. A primitive has a precondition read from the current role binding, an action pattern, and an expected effect. Bindings are role names. Dropped from every solver: the game id, frame fingerprints, palette entries, absolute coordinates, and any stored action sequence.

| Primitive | Precondition | Action pattern | Expected effect |
| --- | --- | --- | --- |
| approach | avatar and goal or receptor | step on the productive axis, never its reverse | avatar translates toward the goal |
| hold_gradient | a productive axis is already known | repeat that axis; the reverse is inhibited | avatar does not reverse |
| convey | movable and goal or receptor | step so the movable keeps the productive axis | movable translates toward the goal |
| align | receptor, or a shape-match relation | interact or step until the object matches the reference | the object matches the reference |
| toggle | switch, or a toggle relation | one interact, then observe | the switch changes another role |
| avoid | avatar and hazard | step off the axis that entered the hazard | avatar stays off the hazard |
| cycle_select | switch and goal or receptor | repeat interact until the reference matches | the selector matches the reference |
| route | avatar and wall or containment | step along the open axis, not into the wall | avatar translates along the open axis |
| assemble | movable, or avatar and receptor | bring the two roles into contact | two roles make contact |
| explore | labeled only | a legal step that is not the productive axis | frame changes under labeled exploration |

Qwen A' and B' propose one of these with a role binding. Mistral picks or inhibits it and states the effect. The document diff confirms or demotes that primitive. A move that is not one of these rules has to be `explore`.

## Smoke, 2026-10-31 2:21 PM CT

Not a score run. Three games, two actions each, solvers off, `MONAD2_COORDINATE=1`, code `e880261`. Mean step 28.8 s. Solver hits 0. Static scan clean. The saved 6-action sample in `COORD_SAMPLE.md` was not overwritten.

`ls20`, first step. The observation proposed `approach` bound to avatar,goal and `route` bound to avatar,wall. Qwen A' proposed `approach` / avatar,goal / left, effect "avatar translates toward". Qwen B' challenged with `hold_gradient` / avatar,goal / left. Mistral inhibited and took `hold_gradient`, expecting "avatar does not reverse". The frame changed. That matched the expected change, so the check confirmed and confidence moved from 1.0 to 1.25. The canvas sentence "avatar does not reverse" did not parse as a document predicate.

`lp85` and `vc33` had no role precondition, so the only listed rule was labeled `explore`. Both Qwen calls still named a primitive, and neither action was legal, so the executive took the labeled explore click. On `vc33` the frame changed and the document diff matched; confidence 1.25.

The second action of each game was chosen and not scored. The action cap returns before that step's diff.

## What each old solver became

| Old solver | Primitive | Dropped as game-specific |
| --- | --- | --- |
| `_try_solve_grammar_container_tree` | align, assemble | shelf labels, brush palette, legend coordinates |
| `_try_solve_stencil_linear_constraints` | align | stencil size, modular arithmetic, tile coordinates |
| `_try_plan_hybrid_switch_navigation` | toggle, approach | panel split, macro-region paths, click coordinates |
| `_try_solve_loop_tile_cycles` | cycle_select | tile sizes, permutation search, stored cycle |
| `_try_solve_symbol_grammar_translation` | cycle_select, align | glyph palette, box size, rewrite tables |
| `_try_solve_fluid_spill_routing` | route | display rotation, spill palette, channel coordinates |
| `_try_solve_midpoint_handle_orbs` | convey, avoid | handle size, hazard palette, tether coordinates |
| `_try_solve_hydraulic_columns` | toggle, route | column palette, pump palette, scale factor |
| `_try_solve_kinematic_arms` | route, align | button sizes, bar palette, joint coordinates |
| `_try_solve_layered_stamp_peeling` | cycle_select, align | canvas boxes, swatch palette, cursor index |
| `_try_solve_cooperative_box_warehouse` | convey, avoid | player palette, box palette, NPC palette |
| `_try_solve_binary_program_panel` | toggle, approach | bit columns, instruction encoding, bracket coordinates |
| `_try_solve_mirrored_avatar_merge` | assemble, avoid | grid size, hazard pattern, stored trajectory |
| `_try_solve_node_graph_sentries` | approach, avoid | stride, sentry palette, node coordinates |
| `_try_solve_skewer_bead_threading` | route, align | lattice palette, skewer palette, search sequence |
| `_try_solve_shape_target_alignment` | align | deformer palette, lattice stride, ring coordinates |
| `_try_solve_connector_piece_assembly` | assemble | upscale, letterbox, piece coordinates |
| `_try_solve_mirror_reflection_targets` | align | grid size, mirror-axis coordinates |
| `_try_solve_attraction_merge_ecology` | assemble, convey | tier counts, zone size, value palette |
| `_try_solve_shape_color_rot_labyrinth` | align, cycle_select, avoid | icon index, palette, rotation index |
| `_try_solve_rune_spell_labyrinth` | toggle, route | rune kinds, search state, coordinates |
| `_try_solve_time_clone_circuits` | toggle, avoid | epoch search, door kinds, stored sequence |
| `_step_gravity_shaft_mechanics` | route | camera track, search coordinates |
| `_step_peg_track_mechanics` | route, convey | camera offset, track graph, search sequence |
| `_try_solve_kick_thruster_sliding_blocks` | convey | coarse grid, border palette, stored kicks |
| `_try_monad1_scp_cegis_panel_solver` | align | bit masks, wiring search |
| `_try_solve_scaled_tile_navigation` | approach | scale factor, pointer coordinates |
