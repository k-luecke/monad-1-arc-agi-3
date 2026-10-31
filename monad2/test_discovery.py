"""Outcome labels and the probe budget. Does not play a game."""
from __future__ import annotations

import os

from monad2.discovery import LevelDiscovery, outcome_label, remember, reset_store, score_change
from monad2.memory import _goal


def _grid() -> list[list[int]]:
    grid = [[0] * 32 for _ in range(32)]
    for r in range(4, 8):
        for c in range(4, 8):
            grid[r][c] = 3
    for r in range(4, 12):
        for c in range(20, 28):
            grid[r][c] = 5
    return grid


def main() -> int:
    before = _grid()
    after = _grid()
    for r in range(4, 8):
        for c in range(4, 8):
            after[r][c] = 0
        for c in range(6, 10):
            after[r][c] = 3
    scores = score_change(before, after)
    assert scores["REACH"] >= 2, scores
    assert outcome_label(
        {
            "record_kind": "dream_schema",
            "hypothesis": "SCHEMA_ANNIHILATION_BRIDGE: a block into a chasm annihilates both into floor",
            "outcome": "solved_counterfactual",
        }
    ) == "PLACE"
    assert _goal({"observation": "the instruction says to reach it", "outcome": "positive_mention"}) is None
    labeled = _goal(
        {
            "record_kind": "dream_schema",
            "hypothesis": "SCHEMA_NONLOCAL_PORTAL_PAIR: twin sprites induce coordinate transport",
            "outcome": "solved_counterfactual",
        }
    )
    assert labeled == "REACH", labeled

    disc = LevelDiscovery(0)
    assert disc.want_probe(0, None)
    disc.note_probe(("SIMPLE", 1))
    disc.absorb(before, after, probe=True)
    disc.note_probe(("SIMPLE", 2))
    disc.absorb(before, after, probe=True)
    assert disc.hypothesis() == "REACH"
    # Later transitions are the outcome label, separate from the probe vote.
    disc.absorb(before, after, probe=False)
    disc.absorb(before, after, probe=False)
    assert disc.outcome() == "REACH"

    reset_store()
    remember(("aff:avatar",), "PLACE", holdout="cd82")
    from monad2.discovery import EPISODE_FMF

    assert EPISODE_FMF == []
    remember(("aff:avatar",), "PLACE", holdout="ar25")
    assert EPISODE_FMF == [(("aff:avatar",), "PLACE")]
    reset_store()

    os.environ["MONAD2_GOAL_DISCOVERY"] = "1"
    from monad2 import runtime as rt

    class A:
        def __init__(self):
            self.m2 = {k: 0 for k in rt.COUNTERS}
            self._m2_avail = [1, 2, 3, 4]
            self._m2_grid = before
            self.current_level = 0
            self.steps_in_level = 0
            self.planned_queue = []
            self.dead_actions = {}
            self._m2_state_hash = 1

    agent = A()
    first = rt.maybe_replace_key(agent, ("SIMPLE", 4))
    assert first == ("SIMPLE", 1), first
    assert agent.m2_discovery.used == 1
    os.environ.pop("MONAD2_GOAL_DISCOVERY", None)
    os.environ.pop("MONAD2_DLADDER", None)
    os.environ.pop("MONAD2_CALLOSUM", None)
    assert rt.maybe_replace_key(agent, ("SIMPLE", 4)) == ("SIMPLE", 4)
    print("DISCOVERY PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
