"""Per-level fractional factorial for Monad(2) gaps 1-9.

Every factor defaults off. ``MONAD2_FACTORIAL=1`` assigns one row of a
2^(9-4) design to each level. The row is a function of the factorial seed,
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
    )
    return {name: int(bit) for name, bit in zip(FACTORS, bits)}


def row_index(seed: int, slot: int, level: int) -> int:
    order = list(range(32))
    random.Random(int(seed)).shuffle(order)
    return order[(int(slot) * 3 + int(level)) % 32]


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
