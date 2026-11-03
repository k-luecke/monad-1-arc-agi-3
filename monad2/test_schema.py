"""Schema structure, holdout exclusion, equivariance, and the solver guard."""
from __future__ import annotations

import os

from monad2.general_guard import (
    HITS,
    arm_solver_guard,
    assert_solvers_unreached,
    reset_hits,
    solver_catalog_ok,
    static_violations,
)
from monad2.schema import (
    STORE,
    assert_structure,
    audit_store,
    induce,
    match,
    render,
    reset_store,
    transformed_case,
    upsert,
)


def _bad(obj) -> None:
    try:
        assert_structure(obj)
    except ValueError:
        return
    raise AssertionError(f"accepted {obj}")


def main() -> int:
    reset_store()
    reset_hits()
    _bad({"game_id": "hidden", "roles": []})
    _bad({"roles": [{"role": "avatar", "color": 4}]})
    _bad({"roles": [{"role": "avatar", "geom": [4, 8]}]})
    _bad({"roles": [], "click": [3, 4]})
    _bad({"actions": [1, 2, 3, 4]})

    base = {
        "roles": [
            {"role": "avatar", "geom": [4, 2, 2], "shape": "ellipse"},
            {"role": "goal", "geom": [2, 4, 6], "shape": "hollow_rect"},
            {"role": "wall", "geom": [1, 2, 12], "shape": "rect"},
        ],
        "relations": [{"kind": "effect", "role": "avatar", "change": "translate"}],
    }
    os.environ["MONAD2_HOLDOUT_GAME"] = "cd82"
    assert upsert(base, "ep-hold") is None
    assert STORE == []
    os.environ["MONAD2_HOLDOUT_GAME"] = "ft09"
    assert upsert(base, "ep-hold") is None
    os.environ.pop("MONAD2_HOLDOUT_GAME", None)
    assert upsert(base, "ep-1") == "S0"
    assert audit_store() == []
    obs = induce(
        [
            {"sig": (4, 9, 3, 3), "geom": (4, 3, 3), "xy": (4, 4), "wh": (3, 3), "area": 9, "type": 4},
            {"sig": (2, 1, 4, 6), "geom": (2, 4, 6), "xy": (20, 20), "wh": (4, 6), "area": 20, "type": 2},
            {"sig": (1, 1, 12, 2), "geom": (1, 2, 12), "xy": (0, 0), "wh": (12, 2), "area": 24, "type": 1},
        ],
        {"moved": [{"sig": (4, 9, 3, 3), "dx": 4, "dy": 0}], "vanished": [], "appeared": []},
        "terminal_goal:2 solid_wall:8",
        "bg=0 shapes=3 hud_rows=1 hud_cols=0",
    )
    hit = match(obs, "ep-2")
    assert hit is not None and hit["id"] == "S0"
    text = render(hit)
    assert "this is schema S0" in text
    assert "rebound" in text
    assert "goal" in text
    assert "cd82" not in text and "game_id" not in text
    assert audit_store() == []

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
    case = transformed_case(grid, set(), set())
    assert case["identity_geoms"], (case["base_geoms"], case["turned_geoms"])
    assert case["pure"]
    assert case["rebound"], case["line"]
    assert "game_id" not in case["line"]

    violations = static_violations()
    assert violations == [], violations
    from my_agent_v7_inos import MyAgent

    assert solver_catalog_ok(MyAgent)

    class Dummy:
        _GAME_SPECIFIC_SOLVERS_RETURN_NONE = ("_try_solve_grammar_container_tree",)
        _GAME_SPECIFIC_SOLVERS_RETURN_EMPTY = ("_try_solve_kick_thruster_sliding_blocks",)

    dummy = Dummy()
    assert arm_solver_guard(dummy) == 2
    assert dummy._try_solve_grammar_container_tree() is None
    assert dummy._try_solve_kick_thruster_sliding_blocks() == []
    assert HITS == [
        "_try_solve_grammar_container_tree",
        "_try_solve_kick_thruster_sliding_blocks",
    ]
    try:
        assert_solvers_unreached()
    except AssertionError:
        pass
    else:
        raise AssertionError("guard did not see the per-game call")
    reset_hits()
    assert_solvers_unreached()
    from monad2.schema import episode_of

    class _Box:
        pass

    first, second = _Box(), _Box()
    assert episode_of(first) != episode_of(second)
    assert episode_of(first) == episode_of(first)
    from llama_cpp import LlamaGrammar
    from monad2.llm import _GRAMMAR

    for role, text in _GRAMMAR.items():
        LlamaGrammar.from_string(text)
    reset_store()
    print("SCHEMA GUARD PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
