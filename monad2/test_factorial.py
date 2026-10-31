"""Balance and orthogonality of the 32-run gap screen. Does not play a game."""
from __future__ import annotations

from monad2.factorial import FACTORS, assign_level, design_row, row_index


def main() -> int:
    rows = [design_row(i) for i in range(32)]
    cols = {name: [1 if row[name] else -1 for row in rows] for name in FACTORS}
    for name, col in cols.items():
        assert sum(col) == 0, name
        assert sum(1 for v in col if v > 0) == 16, name
    names = list(FACTORS)
    for i, a in enumerate(names):
        for b in names[i + 1 :]:
            dot = sum(x * y for x, y in zip(cols[a], cols[b]))
            assert dot == 0, (a, b, dot)
    # Seeds 0..2 put each factor on in 1 or 2 of 3 plays of every cell,
    # and together they cover every design row.
    seen = set()
    for slot in range(25):
        for level in range(4):
            idxs = [row_index(seed, slot, level) for seed in (0, 1, 2)]
            assert len(set(idxs)) == 3, (slot, level, idxs)
            rows = [design_row(i) for i in idxs]
            for name in FACTORS:
                total = sum(row[name] for row in rows)
                assert total in (1, 2), (name, total, slot, level)
            seen.update(idxs)
            assert row_index(0, slot, level) == idxs[0]
    assert len(seen) == 32
    assert row_index(0, 3, 1) != row_index(0, 3, 2)

    class A:
        current_level = 0
        action_counter = 0
        GLOBAL_SOLVED_GEOM_PRIORS = {}
        GLOBAL_SOLVED_AVATAR_GEOM_PRIORS = {}
        rehearse_enabled = False
        fx_enabled = False
        m2_cross_game = "carry"

    import os

    os.environ.pop("MONAD2_FACTORIAL", None)
    agent = A()
    assign_level(agent)
    assert not hasattr(agent, "m2_level_log")
    os.environ["MONAD2_FACTORIAL"] = "1"
    os.environ["MONAD2_FACTORIAL_SEED"] = "0"
    os.environ["MONAD2_GAME_SLOT"] = "4"
    assign_level(agent)
    assert len(agent.m2_level_log) == 1
    assert agent.m2_level_log[0]["row"] == row_index(0, 4, 0)
    assert os.environ["MONAD2_SCP"] in ("0", "1")
    assign_level(agent)
    assert len(agent.m2_level_log) == 1
    for name in FACTORS:
        os.environ.pop(name, None)
    os.environ.pop("MONAD2_FACTORIAL", None)
    os.environ.pop("MONAD2_FACTORIAL_SEED", None)
    os.environ.pop("MONAD2_GAME_SLOT", None)
    os.environ.pop("MONAD2_CROSS_GAME", None)
    print("FACTORIAL DESIGN PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
