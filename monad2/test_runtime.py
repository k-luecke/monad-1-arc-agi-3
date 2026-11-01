"""Unit checks for earned cross-game counts, the D-ladder, and PLL surprise.

These do not play a game. Suite-level pass/fail stays on the scorecard.
"""
from __future__ import annotations

import os

from monad2 import runtime as rt


class A:
    def __init__(self):
        self.m2_cross_game = "carry"
        self.m2 = {k: 0 for k in rt.COUNTERS}
        self.m2_geom_snapshot = None
        self.m2_avatar_snapshot = None
        self.dead_actions = {}
        self._m2_state_hash = 7
        self._m2_avail = [1, 2, 3, 4]
        self.planned_queue = []
        self.ggl_active = None


def main() -> int:
    agent = A()
    agent.m2_cross_game = "carry"
    assert rt.earned_count(agent, 1, ("g",), "geom") == 1

    agent.m2_cross_game = "earned"
    agent.m2_geom_snapshot = {("g",): 1}
    # One prior game, no new evidence this episode: do not steer.
    assert rt.earned_count(agent, 1, ("g",), "geom") == 0
    # Two prior games: confirmed reuse.
    agent.m2_geom_snapshot = {("g",): 2}
    assert rt.earned_count(agent, 2, ("g",), "geom") == 2
    # This episode incremented the count: within-game evidence counts.
    agent.m2_geom_snapshot = {("g",): 1}
    assert rt.earned_count(agent, 2, ("g",), "geom") == 2

    os.environ["MONAD2_DLADDER"] = "1"
    os.environ.pop("MONAD2_CALLOSUM", None)
    agent.m2_cross_game = "carry"
    agent.dead_actions = {7: {("SIMPLE", 1)}}
    out = rt.maybe_replace_key(agent, ("SIMPLE", 1))
    assert out == ("SIMPLE", 2), out
    assert agent.m2["ladder_vetoes"] == 1
    os.environ.pop("MONAD2_DLADDER", None)
    assert rt.maybe_replace_key(agent, ("SIMPLE", 1)) == ("SIMPLE", 1)

    os.environ["MONAD2_PLL_SURPRISE"] = "1"
    agent.m2 = {k: 0 for k in rt.COUNTERS}
    agent._m2_lock_hist = None
    agent.dead_actions = {}
    agent.planned_queue = [1]
    rt.arm_expectation(agent, ("SIMPLE", 1))
    assert agent._m2_expect_change is True
    # Unexpected no-op while a plan is active. No prior lock loss, so it does not count as preceded.
    first = rt.pll_observation(agent, 0)
    assert first["locked"] is False
    assert agent.m2["plan_fails"] == 1
    assert agent.m2["loss_and_fail"] == 0
    assert agent.planned_queue == []
    # Second failure now has a lock loss in the previous step.
    agent.planned_queue = [1]
    rt.arm_expectation(agent, ("SIMPLE", 2))
    rt.pll_observation(agent, 0)
    assert agent.m2["loss_and_fail"] == 1
    assert agent.m2["pll_losses"] == 2
    os.environ.pop("MONAD2_PLL_SURPRISE", None)
    assert rt.pll_observation(agent, 0) is None

    # Lock loss demotes a confirmed goal and clears the plan.
    from monad2.memory import EpisodeLTP

    os.environ["MONAD2_PLL_SURPRISE"] = "1"
    agent.m2 = {k: 0 for k in rt.COUNTERS}
    agent._m2_lock_hist = None
    agent.planned_queue = [1]
    agent.ggl_active = {"type": "REACH"}
    agent.ggl_confirmed_type = "REACH"
    agent.m2_ltp = EpisodeLTP()
    agent.m2_ltp.confirms["REACH"] = 2
    rt.arm_expectation(agent, ("SIMPLE", 1))
    rt.pll_observation(agent, 0)
    assert agent.planned_queue == []
    assert agent.ggl_active is None
    assert agent.ggl_confirmed_type is None
    assert agent.m2_ltp.confirms["REACH"] == 1
    assert agent.m2["goal_demotions"] == 1
    os.environ.pop("MONAD2_PLL_SURPRISE", None)

    # Callosum stays quiet until the world model disagrees.
    grid = [[0] * 64 for _ in range(64)]
    for r in range(10, 12):
        for c in range(10, 12):
            grid[r][c] = 3
    for r in range(10, 18):
        for c in range(40, 48):
            grid[r][c] = 5
    agent._m2_grid = grid
    agent._m2_avail = [1, 2, 3, 4]
    agent.m2 = {k: 0 for k in rt.COUNTERS}
    agent.fx_dpad = {}
    os.environ["MONAD2_CALLOSUM"] = "1"
    quiet = rt.maybe_replace_key(agent, ("SIMPLE", 1))
    assert quiet == ("SIMPLE", 1), quiet
    assert agent.m2["callosum_overrides"] == 0
    assert agent.m2["callosum_blocked"] >= 1
    from collections import Counter

    agent.fx_dpad = {4: Counter({(1, 0): 3}), 1: Counter({(0, 0): 3})}
    agent.m2 = {k: 0 for k in rt.COUNTERS}
    moved = rt.maybe_replace_key(agent, ("SIMPLE", 1))
    assert moved == ("SIMPLE", 4), moved
    assert agent.m2["callosum_overrides"] == 1
    os.environ.pop("MONAD2_CALLOSUM", None)
    assert rt.maybe_replace_key(agent, ("SIMPLE", 1)) == ("SIMPLE", 1)

    # Stall fallback fires only while a decision flag is on.
    os.environ["MONAD2_CALLOSUM"] = "1"
    agent.m2 = {k: 0 for k in rt.COUNTERS}
    agent.rehearse_enabled = True
    agent.fx_enabled = True
    agent.m2_cross_game = "earned"
    agent._m2_stall_fallback = False
    agent._m2_unchanged_streak = 0
    agent.steps_since_novel_atom = 0
    agent.level_resets_in_level = 0
    agent.steps_in_level = 0
    agent.m2_level_log = [{"level": 0}]
    for _ in range(47):
        rt.note_step(agent, False, False)
    assert os.environ["MONAD2_CALLOSUM"] == "1"
    rt.note_step(agent, False, False)
    assert os.environ["MONAD2_CALLOSUM"] == "0"
    assert agent.rehearse_enabled is False
    assert agent.fx_enabled is False
    assert agent.m2_cross_game == "carry"
    assert agent.m2["stall_fallbacks"] == 1
    assert agent.m2_level_log[-1]["stall_fallback"] == 0
    assert agent._m2_pending_level_restore is True
    rt.note_step(agent, False, False)
    assert agent.m2["stall_fallbacks"] == 1
    # Residue captured at level start is what the replay puts back.
    agent.ggl_pushable_votes = {"box": 3}
    agent.ggl_confirmed_type = "REACH"
    agent.control_inversions_detected = 0
    agent.canonical_to_raw_dpad = {1: 1, 2: 2, 3: 3, 4: 4}
    agent.raw_to_canonical_dpad = {1: 1, 2: 2, 3: 3, 4: 4}
    agent.ggl_dir_votes = {}
    agent.ggl_mover_votes = {}
    agent.ggl_dynamic_colors = {}
    agent.ggl_hazard_colors = {}
    agent.skinner_model = None
    agent.hud_rows = {1}
    agent.hud_cols = set()
    agent.hud_coords = {(1, 2)}
    agent.mutable_object_sigs = set()
    agent.responsive_sigs = {}
    agent.responsive_geom_sigs = {}
    agent.avatar_sig = None
    rt.capture_policy_residue(agent)
    agent.ggl_pushable_votes = {"box": 9}
    agent.ggl_confirmed_type = "MATCH"
    agent.control_inversions_detected = 2
    agent.hud_rows.add(9)
    agent.hud_coords.add((4, 4))
    rt.apply_policy_residue(agent)
    assert agent.ggl_pushable_votes["box"] == 3
    assert agent.ggl_confirmed_type == "REACH"
    assert agent.control_inversions_detected == 0
    assert agent.hud_rows == {1}
    assert agent.hud_coords == {(1, 2)}

    os.environ.pop("MONAD2_CALLOSUM", None)
    agent.rehearse_enabled = True
    agent._m2_stall_fallback = False
    for _ in range(80):
        rt.note_step(agent, False, False)
    assert agent.rehearse_enabled is True
    print("RUNTIME UNIT PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
