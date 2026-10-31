"""Per-level fractional factorial for Monad(2).

Every factor defaults off. ``MONAD2_FACTORIAL=1`` assigns one row of the
32-run design to each level. Ten columns: the original nine, plus goal
discovery as the AB interaction, which stays orthogonal to those nine.
The row is a function of the factorial seed,
the harness slot, and the level index. The slot is the position in the
harness order, not a game id, and it is not a retrieval feature.

Holdout prefixes were fixed before this screen (the existing fold 0). They
are not used to choose a combination. A combination is turned on only after
a later fixed-seed run on those prefixes beats the baseline.
"""
from __future__ import annotations

import os
import random

# Pre-registered. Do not edit after looking at factorial clears.
HOLDOUT_PREFIXES = ("cd82", "ft09", "m0r0", "tn36", "tr87")

# Column order is the gap list.
FACTORS = (
    "MONAD2_SCP",            # 1 percept
    "MONAD2_GOAL_MEMORY",    # 2 memory before planning
    "MONAD2_REHEARSAL",      # 3 world-model rehearsal
    "MONAD2_CALLOSUM",       # 4 A'/B' channel
    "MONAD2_DLADDER",        # 5 move guard
    "MONAD2_EARNED",         # 6 cross-game memory after reuse
    "MONAD2_TONIC",          # 7 depth budget controls search
    "MONAD2_PLL_SURPRISE",   # 8 predicted-versus-observed lock
    "MONAD2_SKIP_DEAD_ORGANS",  # 9 master-loop organs as one factor
    "MONAD2_GOAL_DISCOVERY",    # probe budget and outcome-grounded hypothesis
)


def design_row(index: int) -> dict[str, int]:
    """32-run fraction. Generators: E=ABC, F=ABD, G=ACD, H=BCD, J=ABCD.

    Main-effect columns are balanced and mutually orthogonal. Two-factor
    interactions are aliased with each other (resolution IV).
    """
    row = index % 32
    a = (row >> 0) & 1
    b = (row >> 1) & 1
    c = (row >> 2) & 1
    d = (row >> 3) & 1
    bits = (
        a,
        b,
        c,
        d,
        a ^ b ^ c,
        a ^ b ^ d,
        a ^ c ^ d,
        b ^ c ^ d,
        a ^ b ^ c ^ d,
        a ^ b,  # goal discovery; orthogonal to the nine columns above
    )
    return {name: int(bit) for name, bit in zip(FACTORS, bits)}


def _balanced_triples() -> list[tuple[int, int, int]]:
    rows = [design_row(i) for i in range(32)]
    good: list[tuple[int, int, int]] = []
    for i in range(32):
        for j in range(i + 1, 32):
            for k in range(j + 1, 32):
                if all(rows[i][n] + rows[j][n] + rows[k][n] in (1, 2) for n in FACTORS):
                    good.append((i, j, k))
    return good


_SCHEDULE: dict[tuple[int, int], tuple[int, int, int]] | None = None


def schedule() -> dict[tuple[int, int], tuple[int, int, int]]:
    """One balanced triple per (slot, level). Seeds 0, 1, 2 play its three rows.

    Each factor is on in 1 or 2 of those three plays. Across slots 0..24 and
    levels 0..7 the 32 rows all appear.
    """
    global _SCHEDULE
    if _SCHEDULE is not None:
        return _SCHEDULE
    triples = _balanced_triples()
    if not triples:
        raise RuntimeError("no balanced factorial triple")
    usage = [0] * 32
    built: dict[tuple[int, int], tuple[int, int, int]] = {}
    # Low level indices are the ones most games actually play, so cover
    # every design row there before filling deeper levels.
    for level in range(8):
        for slot in range(25):
            best: tuple[int, int, int] | None = None
            best_key: tuple[int, int, int] | None = None
            for triple in triples:
                fresh = sum(1 for row in triple if usage[row] == 0)
                key = (fresh, -max(usage[row] for row in triple), -sum(usage[row] for row in triple))
                if best_key is None or key > best_key:
                    best_key = key
                    best = triple
            assert best is not None
            built[(slot, level)] = best
            for row in best:
                usage[row] += 1
    _SCHEDULE = built
    return built


def row_index(seed: int, slot: int, level: int) -> int:
    """Row for this play. Seeds 0..2 are the balanced triple for that cell."""
    seed_i = int(seed)
    slot_i = int(slot) % 25
    level_i = int(level)
    if level_i < 0:
        level_i = 0
    level_key = level_i if level_i < 8 else level_i % 8
    if seed_i in (0, 1, 2):
        return schedule()[(slot_i, level_key)][seed_i]
    order = list(range(32))
    random.Random(seed_i).shuffle(order)
    return order[(slot_i * 3 + level_i) % 32]


def factorial_on() -> bool:
    return os.getenv("MONAD2_FACTORIAL", "0") == "1"


def assign_level(agent) -> None:
    """Apply this level's row. No-op unless MONAD2_FACTORIAL=1."""
    if not factorial_on():
        return
    level = int(getattr(agent, "current_level", 0) or 0)
    slot = int(os.getenv("MONAD2_GAME_SLOT", "0") or "0")
    if getattr(agent, "_m2_fz_level", None) == level and getattr(agent, "_m2_fz_slot", None) == slot:
        return
    seed = int(os.getenv("MONAD2_FACTORIAL_SEED", "0") or "0")
    index = row_index(seed, slot, level)
    agent._m2_stall_fallback = False
    agent._m2_unchanged_streak = 0
    flags = design_row(index)
    for name, bit in flags.items():
        os.environ[name] = "1" if bit else "0"
    earned = bool(flags["MONAD2_EARNED"])
    agent.m2_cross_game = "earned" if earned else "carry"
    os.environ["MONAD2_CROSS_GAME"] = agent.m2_cross_game
    if earned and not isinstance(getattr(agent, "m2_geom_snapshot", None), dict):
        agent.m2_geom_snapshot = dict(agent.GLOBAL_SOLVED_GEOM_PRIORS)
        agent.m2_avatar_snapshot = dict(agent.GLOBAL_SOLVED_AVATAR_GEOM_PRIORS)
    rehearse = bool(flags["MONAD2_REHEARSAL"]) or os.getenv("MONAD1_CANVAS_REHEARSAL", "0") == "1"
    agent.rehearse_enabled = rehearse
    agent.fx_enabled = bool(flags["MONAD2_REHEARSAL"]) or os.getenv("MONAD1_EFFECT_MODEL", "0") == "1"
    agent._m2_fz_level = level
    agent._m2_fz_slot = slot
    log = getattr(agent, "m2_level_log", None)
    if not isinstance(log, list):
        log = []
        agent.m2_level_log = log
    log.append(
        {
            "seed": seed,
            "slot": slot,
            "level": level,
            "row": index,
            "flags": dict(flags),
            "action_start": int(getattr(agent, "action_counter", 0) or 0),
        }
    )
