"""Motor primitives: guard, gradient, confidence, and rotation invariance."""
from __future__ import annotations

import os
from pathlib import Path

from monad2.primitives import (
    applicable,
    contradicts_gradient,
    credit,
    proposals_for,
    source_violations,
    suggest_action,
)
from monad2.schema import _permute, _records_from_grid, _rot90, induce


def _grid():
    grid = [[0] * 16 for _ in range(16)]
    for col in range(2, 12):
        grid[2][col] = 3
    grid[8][4] = 7
    grid[8][5] = 7
    grid[9][4] = 7
    grid[9][5] = 7
    for col in range(11, 14):
        for row in range(11, 14):
            if row in (11, 13) or col in (11, 13):
                grid[row][col] = 5
    return grid


def _ids(obs, state=None):
    items = applicable(obs, state or {}, [1, 2, 3, 4, 5])
    return {item["id"] for item in items if item["id"] != "explore"}


def main() -> int:
    violations = source_violations()
    assert violations == [], violations
    text = Path("monad2/primitives.py").read_text(encoding="utf-8")
    assert "_try_solve" not in text

    obs = {
        "roles": [{"role": "avatar"}, {"role": "goal"}, {"role": "hazard"}, {"role": "movable"}],
        "relations": [],
    }
    ids = _ids(obs)
    assert "approach" in ids and "avoid" in ids and "convey" in ids
    state = {"progress_axis": 4}
    assert contradicts_gradient("approach", ("SIMPLE", 3), state)
    assert not contradicts_gradient("explore", ("SIMPLE", 3), state)
    assert suggest_action("hold_gradient", [1, 2, 3, 4], state) == ("SIMPLE", 4)
    conf, note = credit(state, "approach", False, ("SIMPLE", 4))
    assert note == "demoted" and conf == 0.5
    assert state.get("progress_axis") is None
    conf, note = credit(state, "approach", True, ("SIMPLE", 1))
    assert note == "confirmed" and state.get("progress_axis") == 1

    grid = _grid()
    play = "bg=stripped shapes=0 hud_rows=0 hud_cols=0"
    base = induce(_records_from_grid(grid), None, "", play)
    turned = induce(_records_from_grid(_permute(_rot90(grid))), None, "", play)
    assert _ids(base) == _ids(turned)
    line, _items = proposals_for(base, {}, [1, 2, 3, 4, 5])
    assert "approach" in line or "route" in line or "align" in line

    os.environ["MONAD2_COORDINATE"] = "1"
    from monad2.coordinate import decide, observe
    from monad2.test_coordinate import Backend, _agent

    agent = _agent()
    agent._m2_coord = {
        "theory": {"goal": None, "text": ""},
        "pending": None,
        "mismatch": None,
        "progress_axis": 4,
        "schema_obs": obs,
    }
    executive = (
        '{"decision":"accept","action":"SIMPLE 3","primitive":"approach","binding":"avatar,goal",'
        '"plan":[],"expect_change":true,"expectation":"avatar translates toward the goal",'
        '"reason":"step toward the goal","theory":"approach","goal":"REACH","used":["schema"]}'
    )
    backend = Backend(executive)
    chosen = decide(agent, ("SIMPLE", 1), "heuristic", backend=backend)
    assert chosen == ("SIMPLE", 4)
    row = agent.m2_thought_log[-1]
    assert row["decision"] == "inhibit"
    assert row["primitive"] == "hold_gradient"
    assert "[primitives]" in row["stream"]
    observe(agent, False)
    assert row.get("primitive_check") == "demoted"
    assert agent._m2_coord["primitive_confidence"]["hold_gradient"] < 1.0

    explore = (
        '{"decision":"explore","action":"SIMPLE 3","primitive":"explore","binding":"",'
        '"plan":[],"expect_change":true,"expectation":"frame changes under labeled exploration",'
        '"reason":"labeled exploration","theory":"look","goal":"REACH","used":["schema"]}'
    )
    agent._m2_coord["progress_axis"] = 4
    agent._m2_coord["mismatch"] = None
    chosen = decide(agent, ("SIMPLE", 1), "heuristic", backend=Backend(explore))
    assert chosen == ("SIMPLE", 3)
    assert agent.m2_thought_log[-1]["primitive"] == "explore"
    assert "explor" in agent.m2_thought_log[-1]["expectation"]
    print("PRIMITIVES PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
