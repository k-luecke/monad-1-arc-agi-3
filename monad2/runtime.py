"""Monad(2) decision hooks. Every flag defaults off, so the blind baseline is unchanged."""
from __future__ import annotations

import os

from monad2.scp import project, validate_action

COUNTERS = (
    "steps",
    "wasted_noop",
    "ladder_vetoes",
    "illegal_blocked",
    "callosum_overrides",
    "callosum_seen",
    "pll_steps",
    "pll_losses",
    "plan_steps",
    "plan_fails",
    "loss_and_fail",
    "rehearsal_taken",
    "dead_skipped",
)


def cross_game_mode() -> str:
    mode = os.getenv("MONAD2_CROSS_GAME", "carry").strip().lower()
    return mode if mode in ("carry", "reset", "earned") else "carry"


def on(name: str) -> bool:
    return os.getenv(name, "0") == "1"


def init_agent(agent) -> None:
    agent.m2_cross_game = cross_game_mode()
    agent.m2 = {key: 0 for key in COUNTERS}
    agent.m2_rehearsal_log = []
    if agent.m2_cross_game == "reset":
        agent.reset_cross_puzzle_archive()
    # Snapshot is the cross-game residue. Increments after this belong to the episode.
    if agent.m2_cross_game == "earned":
        agent.m2_geom_snapshot = dict(agent.GLOBAL_SOLVED_GEOM_PRIORS)
        agent.m2_avatar_snapshot = dict(agent.GLOBAL_SOLVED_AVATAR_GEOM_PRIORS)
    else:
        agent.m2_geom_snapshot = None
        agent.m2_avatar_snapshot = None


def earned_count(agent, n: int, key=None, kind: str = "geom") -> int:
    """Counts that may steer a decision.

    Carry and reset return ``n`` unchanged (reset has already cleared the archive).
    Earned memory ignores a cross-game residue below 2. A count that grew during
    this episode is within-game evidence and is kept.
    """
    n = int(n)
    if getattr(agent, "m2_cross_game", "carry") != "earned":
        return n
    snap_name = "m2_avatar_snapshot" if kind == "avatar" else "m2_geom_snapshot"
    snap = getattr(agent, snap_name, None)
    if not isinstance(snap, dict) or key is None:
        return n if n >= 2 else 0
    carried = int(snap.get(key, 0))
    if n > carried:
        return n
    return n if carried >= 2 else 0


def geom_count(agent, geom) -> int:
    n = int(agent.GLOBAL_SOLVED_GEOM_PRIORS[geom])
    return earned_count(agent, n, geom, "geom")


def note_step(agent, changed: bool, plan_active: bool) -> None:
    stats = getattr(agent, "m2", None)
    if stats is None:
        return
    stats["steps"] += 1
    if not changed:
        stats["wasted_noop"] += 1
    if plan_active:
        stats["plan_steps"] += 1


def _action_id(key) -> int:
    if not key or key[0] == "CLICK":
        return 6 if key and key[0] == "CLICK" else -1
    try:
        return int(key[1])
    except (TypeError, ValueError, IndexError):
        return -1


def _known_noop(agent, key) -> bool:
    state = getattr(agent, "_m2_state_hash", None)
    if state is None:
        state = getattr(agent, "prev_hash", None)
    dead = getattr(agent, "dead_actions", {}) or {}
    return bool(state is not None and key in dead.get(state, ()))


def _known_hazard(agent, key) -> bool:
    if not key or key[0] != "SIMPLE":
        return False
    try:
        aid = int(key[1])
    except (TypeError, ValueError, IndexError):
        return False
    if aid not in (1, 2, 3, 4):
        return False
    hazards = getattr(agent, "ggl_hazard_colors", None)
    if not hazards:
        return False
    hot = {c for c, n in hazards.items() if n >= 2}
    if not hot:
        return False
    grid = getattr(agent, "_m2_grid", None)
    avatar = getattr(agent, "avatar_bbox", None)
    if grid is None or avatar is None:
        return False
    r, c = int(avatar[1]), int(avatar[0])
    delta = {1: (-1, 0), 2: (1, 0), 3: (0, -1), 4: (0, 1)}.get(aid)
    if delta is None:
        return False
    nr, nc = r + delta[0], c + delta[1]
    if not (0 <= nr < len(grid) and 0 <= nc < len(grid[0])):
        return True
    return int(grid[nr][nc]) in hot


def _alternative(agent, key, legal: list[int]):
    """Next legal simple action that passes the ladder. None if the original stands."""
    current = _action_id(key)
    for aid in (1, 2, 3, 4, 5, 6, 7):
        if aid == current or aid not in legal:
            continue
        alt = ("CLICK", 32, 32) if aid == 6 else ("SIMPLE", aid)
        verdict = validate_action(
            aid,
            legal,
            known_noop=_known_noop(agent, alt),
            known_hazard=_known_hazard(agent, alt),
            click=(32, 32) if aid == 6 else None,
        )
        if verdict.ok:
            return alt
    return None


def _callosum_key(agent, key, legal: list[int]):
    grid = getattr(agent, "_m2_grid", None)
    if grid is None:
        return None
    proj = project(grid, getattr(agent, "prev_grid", None), legal=legal)
    proposal = None
    ctrl = None
    target = None
    for obj in proj.objects:
        if proj.controllable_role is not None and obj.role == proj.controllable_role and ctrl is None:
            ctrl = obj
        elif target is None or obj.size > target.size:
            target = obj
    if ctrl is not None and target is not None and target is not ctrl:
        if abs(target.c0 - ctrl.c0) >= abs(target.r0 - ctrl.r0):
            proposal = ("SIMPLE", 4 if target.c0 > ctrl.c0 else 3)
        else:
            proposal = ("SIMPLE", 2 if target.r0 > ctrl.r0 else 1)
    elif proj.panel_mismatch >= 4 and 6 in legal:
        proposal = ("CLICK", 32, 32)
    if proposal is None or proposal == key:
        return None
    aid = _action_id(proposal)
    verdict = validate_action(
        aid,
        legal,
        known_noop=_known_noop(agent, proposal),
        known_hazard=_known_hazard(agent, proposal),
        click=(32, 32) if aid == 6 else None,
    )
    # B' rejects a proposal the ladder will not defend.
    if not verdict.ok:
        return None
    return proposal


def maybe_replace_key(agent, key):
    """D-ladder and A'/B' callosum. Returns the original key when both flags are off."""
    ladder = on("MONAD2_DLADDER")
    callosum = on("MONAD2_CALLOSUM")
    if not ladder and not callosum:
        return key
    legal = [int(a) for a in (getattr(agent, "_m2_avail", None) or []) if int(a) != 0]
    if not legal:
        return key
    stats = agent.m2
    aid = _action_id(key)
    if ladder:
        verdict = validate_action(
            aid,
            legal,
            known_noop=_known_noop(agent, key),
            known_hazard=_known_hazard(agent, key),
            click=(int(key[1]), int(key[2])) if key and key[0] == "CLICK" and len(key) >= 3 else None,
        )
        if not verdict.ok:
            alt = _alternative(agent, key, legal)
            if alt is not None:
                stats["ladder_vetoes"] += 1
                if verdict.rung == "D0":
                    stats["illegal_blocked"] += 1
                key = alt
    if callosum:
        stats["callosum_seen"] += 1
        alt = _callosum_key(agent, key, legal)
        if alt is not None:
            stats["callosum_overrides"] += 1
            key = alt
    return key


def pll_observation(agent, changed_pixels: int) -> dict | None:
    """Predicted-versus-observed change. None keeps the legacy self-comparing PLL.

    Lock loss is whether this step matched the prediction made before it was spent.
    A failed plan is a no-op while a plan was active. The scorecard asks whether a
    lock loss in the previous three steps precedes a failed plan more often than
    the base lock-loss rate, so the same step is not used as both events.
    """
    if not on("MONAD2_PLL_SURPRISE"):
        return None
    from collections import deque

    expected = getattr(agent, "_m2_expect_change", None)
    observed = int(changed_pixels) > 0
    locked = expected is not None and bool(expected) == bool(observed)
    plan_active = bool(getattr(agent, "_m2_plan_active", False))
    stats = agent.m2
    stats["pll_steps"] += 1
    hist = getattr(agent, "_m2_lock_hist", None)
    if hist is None:
        hist = deque(maxlen=3)
        agent._m2_lock_hist = hist
    failed = bool(plan_active and expected and not observed)
    if not locked:
        stats["pll_losses"] += 1
    if failed:
        stats["plan_fails"] += 1
        if any(hist):
            stats["loss_and_fail"] += 1
    if not locked and plan_active:
        if getattr(agent, "planned_queue", None):
            agent.planned_queue.clear()
        if getattr(agent, "ggl_active", None) is not None:
            agent.ggl_active = None
    hist.append(not locked)
    return {"locked": locked, "expected": expected, "observed": observed}


def arm_expectation(agent, key) -> None:
    if not on("MONAD2_PLL_SURPRISE"):
        return
    agent._m2_expect_change = not _known_noop(agent, key)
    agent._m2_plan_active = bool(getattr(agent, "planned_queue", None)) or getattr(agent, "ggl_active", None) is not None


def note_rehearsal(agent, index: int, goal_type: str) -> None:
    stats = getattr(agent, "m2", None)
    if stats is None:
        return
    stats["rehearsal_taken"] += 1
    log = getattr(agent, "m2_rehearsal_log", None)
    if isinstance(log, list) and len(log) < 16:
        log.append({"index": int(index), "goal": goal_type})
