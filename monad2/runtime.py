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
    "callosum_blocked",
    "stall_fallbacks",
    "goal_demotions",
    "discovery_probes",
    "discovery_scored",
    "discovery_hits",
    "watch_episodes",
    "watch_labeled",
    "watch_scored",
    "watch_hits",
    "level_restores",
    "coord_steps",
    "coord_plan_steps",
    "coord_inhibit",
    "coord_inhibit_changed",
    "coord_accept",
    "coord_combine",
    "coord_explore",
    "coord_errors",
    "qwen_proposals",
    "qwen_differ",
    "qwen_influenced",
    "fmf_in_stream",
    "expect_scored",
    "expect_hits",
    "expect_doc_scored",
    "expect_doc_hits",
    "surprise_revisions",
    "coord_ladder_vetoes",
    "carried_theories",
    "infl_scp",
    "infl_canvas",
    "infl_pll",
    "infl_tonic",
    "infl_fmf",
    "infl_effect",
    "infl_dead",
    "infl_collapse",
    "infl_skinner",
    "infl_heuristic",
    "infl_qwen_a",
    "infl_qwen_b",
    "infl_model_a",
    "infl_model_b",
    "infl_solver",
    "infl_schema",
    "schema_revisions",
    "schema_in_stream",
    "predicate_checks",
    "predicate_hits",
    "predicate_surprises",
    "qwen_repaired",
)


def cross_game_mode() -> str:
    mode = os.getenv("MONAD2_CROSS_GAME", "carry").strip().lower()
    return mode if mode in ("carry", "reset", "earned") else "carry"


def on(name: str) -> bool:
    return os.getenv(name, "0") == "1"


def _action_token(action) -> str:
    raw = getattr(action, "value", None)
    if isinstance(raw, tuple):
        raw = raw[0]
    try:
        aid = int(raw)
    except (TypeError, ValueError):
        aid = str(getattr(action, "name", action))
    data = getattr(action, "data", None)
    if isinstance(data, dict) and ("x" in data or "y" in data):
        return f"{aid}:{int(data.get('x', -1))},{int(data.get('y', -1))}"
    return str(aid)


def _install_action_log(agent) -> None:
    """Record the action stream after it is chosen. Off unless MONAD2_LOG_ACTIONS=1."""
    if os.getenv("MONAD2_LOG_ACTIONS", "0") != "1":
        return
    if getattr(agent, "_m2_log_installed", False):
        return
    agent._m2_log_installed = True
    agent.m2_action_log = []
    orig = agent.choose_action

    def wrapped(frames, latest, _orig=orig):
        action = _orig(frames, latest)
        try:
            agent.m2_action_log.append(_action_token(action))
        except Exception:
            pass
        return action

    agent.choose_action = wrapped


def _copy_counter_map(value):
    if value is None:
        return None
    try:
        return {key: dict(votes) for key, votes in value.items()}
    except Exception:
        return None


def capture_policy_residue(agent) -> None:
    """Level-start copy of the state a later stall restore puts back.

    The copy is not read by action selection. Restoring it is what makes the
    post-stall replay the baseline policy instead of the diverged one.
    """
    import copy

    def _set_copy(name: str):
        value = getattr(agent, name, None)
        if isinstance(value, set):
            return set(value)
        return None

    residue: dict = {
        "inversions": int(getattr(agent, "control_inversions_detected", 0) or 0),
        "canon": dict(getattr(agent, "canonical_to_raw_dpad", {}) or {}),
        "raw": dict(getattr(agent, "raw_to_canonical_dpad", {}) or {}),
        "confirmed": getattr(agent, "ggl_confirmed_type", None),
        "confirm_level": getattr(agent, "ggl_confirm_level", None),
        "dir_votes": _copy_counter_map(getattr(agent, "ggl_dir_votes", None)),
        "mover_votes": dict(getattr(agent, "ggl_mover_votes", {}) or {}),
        "dynamic_colors": dict(getattr(agent, "ggl_dynamic_colors", {}) or {}),
        "pushable": dict(getattr(agent, "ggl_pushable_votes", {}) or {}),
        "hazards": dict(getattr(agent, "ggl_hazard_colors", {}) or {}),
        "hud_rows": _set_copy("hud_rows"),
        "hud_cols": _set_copy("hud_cols"),
        "hud_coords": _set_copy("hud_coords"),
        "mutable_sigs": _set_copy("mutable_object_sigs"),
        "responsive": dict(getattr(agent, "responsive_sigs", {}) or {}),
        "responsive_geom": dict(getattr(agent, "responsive_geom_sigs", {}) or {}),
        "avatar_sig": getattr(agent, "avatar_sig", None),
    }
    skinner = getattr(agent, "skinner_model", None)
    try:
        residue["skinner"] = copy.deepcopy(skinner) if skinner is not None else None
    except Exception:
        residue["skinner"] = None
    agent._m2_policy_residue = residue


def apply_policy_residue(agent) -> None:
    residue = getattr(agent, "_m2_policy_residue", None)
    if not isinstance(residue, dict):
        return
    agent.control_inversions_detected = int(residue.get("inversions", 0) or 0)
    if residue.get("canon"):
        agent.canonical_to_raw_dpad = dict(residue["canon"])
    if residue.get("raw"):
        agent.raw_to_canonical_dpad = dict(residue["raw"])
    agent.ggl_confirmed_type = residue.get("confirmed")
    agent.ggl_confirm_level = residue.get("confirm_level")
    dir_votes = residue.get("dir_votes")
    current_dirs = getattr(agent, "ggl_dir_votes", None)
    if isinstance(dir_votes, dict) and current_dirs is not None and hasattr(current_dirs, "clear"):
        current_dirs.clear()
        for item_key, votes in dir_votes.items():
            bucket = current_dirs[item_key]
            if hasattr(bucket, "update") and isinstance(votes, dict):
                bucket.update(votes)
    for name, key in (
        ("ggl_mover_votes", "mover_votes"),
        ("ggl_dynamic_colors", "dynamic_colors"),
        ("ggl_pushable_votes", "pushable"),
        ("ggl_hazard_colors", "hazards"),
    ):
        raw = residue.get(key)
        current = getattr(agent, name, None)
        if isinstance(raw, dict) and current is not None and hasattr(current, "clear"):
            current.clear()
            current.update(raw)
    if residue.get("skinner") is not None:
        import copy

        try:
            agent.skinner_model = copy.deepcopy(residue["skinner"])
        except Exception:
            pass
    for name, key in (
        ("hud_rows", "hud_rows"),
        ("hud_cols", "hud_cols"),
        ("hud_coords", "hud_coords"),
        ("mutable_object_sigs", "mutable_sigs"),
    ):
        saved = residue.get(key)
        current = getattr(agent, name, None)
        if isinstance(saved, set) and isinstance(current, set):
            current.clear()
            current.update(saved)
    for name, key in (
        ("responsive_sigs", "responsive"),
        ("responsive_geom_sigs", "responsive_geom"),
    ):
        saved = residue.get(key)
        current = getattr(agent, name, None)
        if isinstance(saved, dict) and current is not None and hasattr(current, "clear"):
            current.clear()
            current.update(saved)
    if "avatar_sig" in residue:
        agent.avatar_sig = residue.get("avatar_sig")


def init_agent(agent) -> None:
    agent.m2_cross_game = cross_game_mode()
    agent.m2 = {key: 0 for key in COUNTERS}
    agent.m2_rehearsal_log = []
    agent.m2_watch_log = []
    agent.m2_thought_log = []
    agent._m2_pending_level_restore = False
    _install_action_log(agent)
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


def stall_n() -> int:
    """Consecutive unchanged frames before falling back to baseline. 0 disables."""
    raw = os.getenv("MONAD2_STALL_N", "").strip()
    if not raw:
        return 48
    try:
        return max(0, int(raw))
    except ValueError:
        return 48


def _decision_flags_on() -> bool:
    from monad2.factorial import FACTORS

    return any(on(name) for name in FACTORS)


def _fallback_to_baseline(agent) -> None:
    """Drop Monad(2) decision flags and ask for a level restart.

    Zeroing the flags mid-trajectory left the world model and the game state
    on the diverged path, so sc25, tu93, bp35, and ka59 never got the baseline
    policy that clears them. The pending restore emits one RESET and rebuilds
    the level world model from the residue captured at level start.
    """
    if getattr(agent, "_m2_stall_fallback", False):
        return
    from monad2.factorial import FACTORS

    agent._m2_stall_fallback = True
    agent._m2_pending_level_restore = True
    stats = getattr(agent, "m2", None)
    if isinstance(stats, dict):
        stats["stall_fallbacks"] = stats.get("stall_fallbacks", 0) + 1
    for name in FACTORS:
        os.environ[name] = "0"
    agent.m2_cross_game = "carry"
    os.environ["MONAD2_CROSS_GAME"] = "carry"
    if os.getenv("MONAD1_CANVAS_REHEARSAL", "0") != "1":
        agent.rehearse_enabled = False
    if os.getenv("MONAD1_EFFECT_MODEL", "0") != "1":
        agent.fx_enabled = False
    log = getattr(agent, "m2_level_log", None)
    if isinstance(log, list) and log:
        log[-1]["stall_fallback"] = int(getattr(agent, "action_counter", 0) or 0)
    try:
        from monad2.discovery import watch_close

        watch_close(agent, reason="stall")
    except Exception:
        pass


def note_step(agent, changed: bool, plan_active: bool) -> None:
    stats = getattr(agent, "m2", None)
    if stats is None:
        return
    stats["steps"] += 1
    if not changed:
        stats["wasted_noop"] += 1
    if plan_active:
        stats["plan_steps"] += 1
    # Watch mode records hypotheses and endpoint labels. It is not a decision
    # flag, and it does not write anything the policy reads.
    if on("MONAD2_GOAL_WATCH"):
        try:
            from monad2.discovery import watch_step

            watch_step(agent, changed)
        except Exception:
            pass
    if on("MONAD2_COORDINATE"):
        try:
            from monad2.coordinate import observe

            observe(agent, changed)
        except Exception:
            pass
    # Flags-off is a no-op. A bad combo that freezes the frame, or that is
    # about to hit the 600-step reset loop / the 1500-step level cap, hands
    # the rest of the level back to baseline.
    n = stall_n()
    if n <= 0 or not _decision_flags_on() or getattr(agent, "_m2_stall_fallback", False):
        return
    streak = 0 if changed else int(getattr(agent, "_m2_unchanged_streak", 0)) + 1
    agent._m2_unchanged_streak = streak
    novel = int(getattr(agent, "steps_since_novel_atom", 0) or 0)
    resets = int(getattr(agent, "level_resets_in_level", 0) or 0)
    steps = int(getattr(agent, "steps_in_level", 0) or 0)
    frozen = streak >= n
    # tu93 died at ~600 steps (novel drought plus resets, 33s, not the clock).
    # Hand back before that exit, including when the resets arrive late.
    loop = (novel >= 240 and resets >= 3 and steps >= 480) or (steps >= 560 and novel >= 280)
    # sc25 died at the 1500-step cap with the frame still changing.
    cap = steps >= 900
    if frozen or loop or cap:
        _fallback_to_baseline(agent)
    if on("MONAD2_GOAL_DISCOVERY"):
        try:
            from monad2.discovery import observe_step

            observe_step(agent, changed)
        except Exception:
            pass


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


def _predicted_progress(agent, key) -> bool | None:
    """World-model opinion. None means it has not seen this action yet.

    True only when the recorded effect is a real change. A known no-op or a
    known hazard is a confident False.
    """
    if _known_noop(agent, key) or _known_hazard(agent, key):
        return False
    aid = _action_id(key)
    if aid in (1, 2, 3, 4):
        fx = getattr(agent, "fx_dpad", None)
        votes = fx.get(aid) if fx is not None else None
        if not votes:
            return None
        try:
            shift, n = votes.most_common(1)[0]
        except (AttributeError, ValueError, IndexError):
            return None
        if n < 1:
            return None
        return tuple(shift) != (0, 0)
    if aid == 6:
        clicks = getattr(agent, "fx_click", None)
        if not clicks:
            return None
        change = inert = 0
        try:
            items = clicks.values()
        except AttributeError:
            return None
        for counter in items:
            change += int(counter.get("CHANGE", 0))
            inert += int(counter.get("INERT", 0))
        if change + inert <= 0:
            return None
        return change > inert
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
    # Toward a discovered goal, override only when the world model predicts
    # the alternative gains more on that goal. Otherwise keep the older gate:
    # the alternative must be predicted to change the frame and A's choice must not.
    goal = getattr(agent, "m2_goal_hypothesis", None)
    if goal:
        alt_delta = _goal_delta(agent, proposal, goal)
        cur_delta = _goal_delta(agent, key, goal)
        if alt_delta is None or cur_delta is None or not (alt_delta > cur_delta and alt_delta > 0):
            agent._m2_callosum_gated = True
            return None
        return proposal
    alt_prog = _predicted_progress(agent, proposal)
    cur_prog = _predicted_progress(agent, key)
    if alt_prog is not True or cur_prog is not False:
        agent._m2_callosum_gated = True
        return None
    return proposal


def _goal_delta(agent, key, goal: str) -> float | None:
    predict = getattr(agent, "_fx_predict", None)
    grid = getattr(agent, "_m2_grid", None)
    if not callable(predict) or grid is None:
        return None
    try:
        nxt = predict(grid, key)
    except Exception:
        return None
    if nxt is None:
        return None
    from monad2.discovery import score_change

    return float(score_change(grid, nxt).get(goal, 0))


def maybe_replace_key(agent, key, reason: str = ""):
    """Probes, D-ladder, and A'/B' callosum. The original key when every flag is off.

    ``MONAD2_COORDINATE=1`` hands the key to the executive instead. That path
    is not a factorial column and stays off during score runs.
    """
    if on("MONAD2_COORDINATE"):
        from monad2.coordinate import decide

        return decide(agent, key, reason)
    ladder = on("MONAD2_DLADDER")
    callosum = on("MONAD2_CALLOSUM")
    discovery = on("MONAD2_GOAL_DISCOVERY")
    if not ladder and not callosum and not discovery:
        return key
    legal = [int(a) for a in (getattr(agent, "_m2_avail", None) or []) if int(a) != 0]
    if not legal:
        return key
    probing = False
    if discovery:
        try:
            from monad2.discovery import ensure, next_probe

            probe = next_probe(agent, legal)
            if probe is not None and _action_id(probe) in legal:
                key = probe
                probing = True
                ensure(agent).note_probe(key)
        except Exception:
            probing = False
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
    if callosum and not probing:
        stats["callosum_seen"] += 1
        agent._m2_callosum_gated = False
        alt = _callosum_key(agent, key, legal)
        if getattr(agent, "_m2_callosum_gated", False):
            stats["callosum_blocked"] += 1
        if alt is not None:
            stats["callosum_overrides"] += 1
            key = alt
    if probing:
        try:
            from monad2.discovery import ensure

            ensure(agent).pending = key
        except Exception:
            pass
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
        active = getattr(agent, "ggl_active", None)
        gtype = active.get("type") if isinstance(active, dict) else None
        if getattr(agent, "planned_queue", None):
            agent.planned_queue.clear()
        agent.ggl_active = None
        if gtype:
            from monad2.memory import EpisodeLTP

            ltp = getattr(agent, "m2_ltp", None)
            if ltp is None:
                ltp = EpisodeLTP()
                if getattr(agent, "ggl_confirmed_type", None) == gtype:
                    ltp.confirms[gtype] = 2
                agent.m2_ltp = ltp
            left = ltp.demote(gtype)
            stats["goal_demotions"] += 1
            if getattr(agent, "ggl_confirmed_type", None) == gtype and left < 2:
                agent.ggl_confirmed_type = None
            try:
                from monad2.discovery import demote

                demote(agent, gtype)
            except Exception:
                pass
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
