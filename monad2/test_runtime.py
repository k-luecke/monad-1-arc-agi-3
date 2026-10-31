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
    print("RUNTIME UNIT PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
