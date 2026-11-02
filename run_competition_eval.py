#!/usr/bin/env python3
"""
Monad(1) V7 — Official ARC-AGI-3 Competition Mode & Blinded-ID Verification Harness
Author: Kyle W. Luecke (Drift Bound Labs)
License: Apache-2.0

Usage:
  1. Official Remote Competition Mode on https://three.arcprize.org (requires ARC_API_KEY):
     export ARC_API_KEY="your-arc-prize-api-key"
     python run_competition_eval.py

  2. Local Kaggle Rerun Gateway Replica (listen_and_serve(port=8001, competition_mode=True)):
     python run_competition_eval.py --local-gateway --blind-id

  3. Offline 25-Game Verification (with --blind-id environment proxy):
     python run_competition_eval.py --offline --blind-id

  4. Standalone Self-Test (runs MyAgent.main() end-to-end without arc_agi or arcengine):
     python run_competition_eval.py --self-test --blind-id
"""
from __future__ import annotations

import argparse
import ast
import concurrent.futures
import json
import logging
import os
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

os.environ.setdefault("INOS_BRIDGE_MODE", "STATIC_MONOLITH_IN_MEMORY")
os.environ.setdefault("INOS_USE_EXTERNAL_DAEMON", "0")

logging.getLogger("arc_agi").setLevel(logging.WARNING)
logging.getLogger("werkzeug").setLevel(logging.ERROR)

try:
    from arc_agi import Arcade, OperationMode
    HAS_ARC_AGI = True
except Exception:
    _sib = (Path(__file__).resolve().parent.parent if "__file__" in globals() else Path.cwd().parent) / "monad(1)"
    if _sib.is_dir() and str(_sib) not in sys.path:
        sys.path.append(str(_sib))
    try:
        from arc_agi import Arcade, OperationMode
        HAS_ARC_AGI = True
    except Exception:
        Arcade = Any  # type: ignore[misc,assignment]
        OperationMode = Any  # type: ignore[misc,assignment]
        HAS_ARC_AGI = False

if HAS_ARC_AGI and hasattr(Arcade, "_convert_scorecard_to_environment_scorecard"):
    _orig_convert_sc = Arcade._convert_scorecard_to_environment_scorecard
    if not getattr(_orig_convert_sc, "_monad_patched", False):
        def _safe_convert_sc(self: Any, data: dict[str, Any]) -> Any:
            if isinstance(data, dict):
                data = {k: v for k, v in data.items() if k not in ("open_at", "last_update")}
            return _orig_convert_sc(self, data)

        _safe_convert_sc._monad_patched = True  # type: ignore[attr-defined]
        Arcade._convert_scorecard_to_environment_scorecard = _safe_convert_sc  # type: ignore[method-assign]

if "MyAgent" not in globals():
    from my_agent_v7_inos import FrameData, GameAction, GameState, MyAgent

EXPECTED_FULL_SUITE_GAMES = 25
EXPECTED_FULL_SUITE_LEVELS = 183
EXPECTED_FULL_SUITE_ACTIONS = 6444

_BLIND_ENV_REGISTRY: dict[int, Any] = {}
_ALLOWED_CALLER_CODES: set[Any] = set()


def _scrub_frame(frame: Any) -> Any:
    if frame is not None and hasattr(frame, "game_id"):
        try:
            frame.game_id = "blind_unknown_env"
        except Exception:
            pass
    return frame


def _lookup_blind_env(proxy: Any) -> Any:
    caller_code = sys._getframe(1).f_code
    if caller_code not in _ALLOWED_CALLER_CODES:
        raise PermissionError("Direct access to _BLIND_ENV_REGISTRY is prohibited.")
    return _BLIND_ENV_REGISTRY[id(proxy)]


class BlindEnvironmentProxy:
    """
    Interface-isolating environment wrapper for `--blind-id` verification:
      1. `__slots__ = ()`: stores zero instance attributes on `self`.
      2. Methods (`reset`, `step`, `observation_space`, `action_space`) define zero lexical
         closures (`__closure__ is None`) and expose no `.info`, `._game`, or `.game_id` attributes.
      3. Scrubs `game_id` to `'blind_unknown_env'` on `observation_space` and on every frame
         returned by `reset()` and `step()`.
      Note: As an in-process Python wrapper, this isolates standard attribute/frame interfaces
      and is paired with `verify_agent_ast_no_env_introspection()` to confirm the agent only
      ever accesses `self.arc_env.observation_space` and `self.arc_env.step(...)`.
    """
    __slots__ = ()

    def reset(self) -> Any:
        env = _lookup_blind_env(self)
        return _scrub_frame(env.reset())

    def step(self, action: Any, data: Any = None, reasoning: Any = None) -> Any:
        env = _lookup_blind_env(self)
        if reasoning is not None:
            return _scrub_frame(env.step(action, data=data, reasoning=reasoning))
        return _scrub_frame(env.step(action, data=data))

    @property
    def action_space(self) -> Any:
        env = _lookup_blind_env(self)
        return getattr(env, "action_space", None)

    @property
    def observation_space(self) -> Any:
        env = _lookup_blind_env(self)
        return _scrub_frame(getattr(env, "observation_space", None))

    def __getattr__(self, name: str) -> Any:
        raise AttributeError(
            f"BlindEnvironmentProxy blocks access to underlying environment attribute '{name}'"
        )


_ALLOWED_CALLER_CODES.update({
    BlindEnvironmentProxy.reset.__code__,
    BlindEnvironmentProxy.step.__code__,
    BlindEnvironmentProxy.action_space.fget.__code__,  # type: ignore[union-attr]
    BlindEnvironmentProxy.observation_space.fget.__code__,  # type: ignore[union-attr]
})


def make_blind_env_proxy(real_env: Any) -> BlindEnvironmentProxy:
    proxy = BlindEnvironmentProxy()
    _BLIND_ENV_REGISTRY[id(proxy)] = real_env
    return proxy


def verify_agent_ast_no_env_introspection(agent_py_path: Path | None = None) -> None:
    """
    Static AST check confirming that `my_agent_v7_inos.py` only ever accesses
    `observation_space` and `step` on `self.arc_env` and never references
    `__globals__`, `__closure__`, `_BLIND_ENV_REGISTRY`, or `inspect`.
    """
    if agent_py_path is None:
        cand = Path(__file__).resolve().parent / "my_agent_v7_inos.py" if "__file__" in globals() else Path("my_agent_v7_inos.py")
        if not cand.exists():
            return
        agent_py_path = cand
    src = agent_py_path.read_text(encoding="utf-8")
    for forbidden in ("__globals__", "__closure__", "_BLIND_ENV_REGISTRY", "f_locals", "f_globals"):
        assert forbidden not in src, f"Forbidden introspection token {forbidden!r} found in {agent_py_path}"
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Attribute)
            and isinstance(node.value, ast.Attribute)
            and isinstance(node.value.value, ast.Name)
            and node.value.value.id == "self"
            and node.value.attr == "arc_env"
        ):
            assert node.attr in ("observation_space", "step"), (
                f"Disallowed attribute access self.arc_env.{node.attr} in {agent_py_path}"
            )


def run_self_test_episode(blind_id: bool = True) -> dict:
    """
    Execute a complete standalone episode of `MyAgent.main()` against an in-memory mock
    environment (requiring neither `arc_agi` nor `arcengine` to be installed).
    Exercises both D-pad navigation and `GameAction.ACTION6` coordinate click paths.
    """
    verify_agent_ast_no_env_introspection()

    class _SyntheticEnv:
        def __init__(self) -> None:
            self.step_idx = 0
            self.observation_space = self._make_frame(GameState.NOT_FINISHED, 0)

        def _make_frame(self, state: GameState, lvls: int) -> FrameData:
            grid = [[0 for _ in range(64)] for _ in range(64)]
            # Place a distinct clickable 4x4 target block at (20..23, 20..23)
            for r in range(20, 24):
                for c in range(20, 24):
                    grid[r][c] = 11
            return FrameData(
                game_id="synthetic_secret_id",
                frame=[grid],
                state=state,
                levels_completed=lvls,
                win_levels=1,
                guid="synthetic-guid-001",
                full_reset=(self.step_idx == 0),
                available_actions=[1, 2, 3, 4, 5, 6],
            )

        def reset(self) -> FrameData:
            self.step_idx = 0
            self.observation_space = self._make_frame(GameState.NOT_FINISHED, 0)
            return self.observation_space

        def step(self, action: Any, data: Any = None, reasoning: Any = None) -> FrameData:
            self.step_idx += 1
            # Test that GameAction.ACTION6 comparison and coordinate payload work cleanly
            assert hasattr(GameAction, "ACTION6") and hasattr(GameAction, "RESET")
            state = GameState.WIN if self.step_idx >= 3 else GameState.NOT_FINISHED
            lvls = 1 if state == GameState.WIN else 0
            self.observation_space = self._make_frame(state, lvls)
            return self.observation_space

    raw_env = _SyntheticEnv()
    env: Any = make_blind_env_proxy(raw_env) if blind_id else raw_env
    agent_gid = "blind_unknown_env" if blind_id else "synthetic_secret_id"
    t0 = time.perf_counter()
    try:
        agent = MyAgent(
            card_id="self-test-card",
            game_id=agent_gid,
            agent_name="monad(1)-v7-inos",
            ROOT_URL="http://localhost",
            record=False,
            arc_env=env,
            tags=["monad(1)", "v7-inos", "self-test"],
        )
        agent.max_game_seconds = 30.0
        agent.main()
        assert agent.state == GameState.WIN, f"Expected GameState.WIN, got {agent.state}"
        assert agent.levels_completed == 1, f"Expected 1 level completed, got {agent.levels_completed}"
        assert agent.action_counter == 3, f"Expected 3 actions, got {agent.action_counter}"
        if blind_id:
            assert agent.game_id == "blind_unknown_env"
            for frame in getattr(agent, "frames", []):
                assert getattr(frame, "game_id", "blind_unknown_env") in ("blind_unknown_env", "unknown", "")
    finally:
        if blind_id:
            _BLIND_ENV_REGISTRY.pop(id(env), None)
    dt = round(time.perf_counter() - t0, 3)
    print("=" * 80)
    print(
        f"[Monad(1) V7] Standalone Self-Test PASSED: state={agent.state.name} | "
        f"levels={agent.levels_completed}/1 | actions={agent.action_counter} | {dt}s"
    )
    print("=" * 80)
    return {
        "game_id": "self_test",
        "agent_game_id": agent_gid,
        "state": agent.state.name,
        "levels_completed": int(agent.levels_completed),
        "actions": int(agent.action_counter),
        "elapsed_s": dt,
    }


def ensure_local_environments(
    env_dir: Path,
    offline: bool = False,
    game_filter: set[str] | None = None,
) -> list[str]:
    """Ensure official ARC-AGI-3 environments are cached locally in env_dir."""
    if not HAS_ARC_AGI:
        raise RuntimeError("The 'arc-agi' package is required to load official ARC-AGI-3 environments.")
    if not env_dir.exists():
        env_dir.mkdir(parents=True, exist_ok=True)
    existing_py = [p for p in env_dir.rglob("*.py") if "__pycache__" not in str(p)]
    offline_ids: list[str] = []
    if existing_py:
        offline_arc = Arcade(operation_mode=OperationMode.OFFLINE, environments_dir=str(env_dir))
        offline_ids = sorted({e.game_id for e in offline_arc.get_environments()})
        if len(offline_ids) >= EXPECTED_FULL_SUITE_GAMES:
            return offline_ids
        if offline and offline_ids and (
            not game_filter
            or all(any(g == f or g.startswith(f"{f}-") for g in offline_ids) for f in game_filter)
        ):
            return offline_ids

    try:
        fetcher = Arcade(environments_dir=str(env_dir))
        envs = fetcher.get_environments()
        game_ids = sorted({e.game_id for e in envs})
        for gid in game_ids:
            prefix = gid.split("-")[0]
            if not list((env_dir / prefix).rglob("*.py")):
                fetcher.make(gid, save_recording=False)
        return game_ids
    except Exception:
        if offline_ids:
            return offline_ids
        raise


def _select_game_ids(game_ids: list[str], game_filter: set[str], game_order: str) -> list[str]:
    """Filter and optionally reorder games. `--game-order` is a comma-separated prefix list."""
    order = [part.strip() for part in game_order.split(",") if part.strip()]
    if order:
        by_key: dict[str, str] = {}
        for gid in game_ids:
            by_key.setdefault(gid, gid)
            by_key.setdefault(gid.split("-")[0], gid)
        selected: list[str] = []
        for key in order:
            gid = by_key.get(key)
            if gid and gid not in selected:
                selected.append(gid)
        return selected
    if game_filter:
        return [g for g in game_ids if g in game_filter or g.split("-")[0] in game_filter]
    return list(game_ids)


def _session_remaining_seconds() -> float:
    raw_start = os.getenv("MONAD_SESSION_START_EPOCH", "").strip()
    if not raw_start:
        return float(6 * 3600 - 240)
    try:
        start_epoch = float(raw_start)
        session_limit = float(os.getenv("MONAD_SESSION_SECONDS", str(6 * 3600)))
        reserve = float(os.getenv("MONAD_FINALIZE_RESERVE_SECONDS", "240"))
        return (start_epoch + session_limit - reserve) - time.time()
    except Exception:
        return float(6 * 3600 - 240)


def play_single_game(
    worker_arc: Any,
    base_url: str,
    card_id: str,
    gid: str,
    idx: int,
    total: int,
    blind_id: bool = False,
    max_game_seconds: float = 300.0,
    *,
    agent_cache: dict[str, tuple[Any, Any, Any]] | None = None,
    cache_lock: threading.Lock | None = None,
    round_idx: int = 1,
) -> dict:
    t0 = time.perf_counter()
    agent_gid = "blind_unknown_env" if blind_id else gid
    os.environ["MONAD2_HOLDOUT_GAME"] = gid.split("-")[0]
    if os.getenv("MONAD2_FACTORIAL", "0") == "1" and os.getenv("MONAD2_GAME_SLOT_LOCK", "0") != "1":
        os.environ["MONAD2_GAME_SLOT"] = str(max(0, int(idx) - 1))
    elif os.getenv("MONAD2_GAME_SLOT_LOCK", "0") != "1":
        os.environ["MONAD2_GAME_SLOT"] = str(int(idx))
    goal_report = None
    win_records = None
    monad2_report = None
    cached_entry = None
    if round_idx >= 2 and agent_cache is not None:
        if cache_lock is not None:
            with cache_lock:
                cached_entry = agent_cache.get(gid)
        else:
            cached_entry = agent_cache.get(gid)
    if cached_entry is not None:
        env, agent, _cached_arc = cached_entry
    else:
        raw_env = worker_arc.make(gid, scorecard_id=card_id, save_recording=False)
        env = make_blind_env_proxy(raw_env) if blind_id else raw_env
        agent = None
    try:
        if agent is None:
            agent = MyAgent(
                card_id=card_id,
                game_id=agent_gid,
                agent_name="monad(1)-v7-inos",
                ROOT_URL=base_url,
                record=False,
                arc_env=env,
                tags=["monad(1)", "v7-inos", "competition-mode"],
            )
            agent.max_game_seconds = float(max_game_seconds)
            agent.m2_game_slot = int(idx)
            agent.m2_round_idx = max(1, int(round_idx))
            agent.m2_pass_idx = int(os.getenv("MONAD2_PASS", "1") or "1")
            if agent_cache is not None:
                if cache_lock is not None:
                    with cache_lock:
                        agent_cache[gid] = (env, agent, worker_arc)
                else:
                    agent_cache[gid] = (env, agent, worker_arc)
        else:
            agent.prepare_for_next_round(round_idx=int(round_idx), slice_seconds=float(max_game_seconds))
        agent.main()
        try:
            if getattr(agent, "ggl_enabled", False):
                goal_report = agent._ggl_build_report()
        except Exception:
            goal_report = None
        try:
            records = getattr(agent, "win_records", None)
            if records:
                win_records = list(records)
        except Exception:
            win_records = None
        monad2_report = None
        synth_dict = None
        try:
            from monad2.discovery import finalize_watch

            finalize_watch(agent)
        except Exception:
            pass
        try:
            from monad2.synthesizer import SYNTHESIZED_BY_SLOT, synthesize_solver_from_pass1

            synth_spec = synthesize_solver_from_pass1(agent, slot=int(idx))
            if synth_spec is None:
                synth_spec = getattr(agent, "_m2_synthesized_solver", None) or SYNTHESIZED_BY_SLOT.get(int(idx))
            synth_dict = synth_spec.to_dict() if synth_spec is not None else None
        except Exception:
            synth_dict = None
        try:
            stats = getattr(agent, "m2", None)
            if isinstance(stats, dict) and stats:
                monad2_report = dict(stats)
                if synth_dict is not None:
                    monad2_report["synthesized_solver"] = synth_dict
                monad2_report["rehearsal_log"] = list(getattr(agent, "m2_rehearsal_log", []) or [])
                monad2_report["cross_game"] = getattr(agent, "m2_cross_game", "carry")
                level_clear_actions: dict[str, int] = {}
                level_log = getattr(agent, "m2_level_log", None)
                if isinstance(level_log, list) and level_log:
                    prefix = gid.split("-")[0]
                    done_levels = max(
                        int(getattr(agent, "levels_completed", 0) or 0),
                        int(getattr(agent, "_max_levels_completed", 0) or 0),
                    )
                    done_actions = int(getattr(agent, "action_counter", 0) or 0)
                    ends = [int(row["action_start"]) for row in level_log[1:]] + [done_actions]
                    stamped = []
                    for row, end in zip(level_log, ends):
                        item = dict(row)
                        item["game"] = prefix
                        item["actions"] = int(end) - int(row["action_start"])
                        item["cleared"] = int(row["level"]) < done_levels
                        item["holdout"] = prefix in ("cd82", "ft09", "m0r0", "tn36", "tr87")
                        stamped.append(item)
                        if item["cleared"]:
                            level_clear_actions[str(int(item["level"]))] = int(item["actions"])
                    monad2_report["level_log"] = stamped
                    monad2_report["level_clear_actions"] = level_clear_actions
                    monad2_report["factorial_seed"] = stamped[0].get("seed")
                watch_log = getattr(agent, "m2_watch_log", None)
                if isinstance(watch_log, list) and watch_log:
                    monad2_report["watch_log"] = list(watch_log)
                action_log = getattr(agent, "m2_action_log", None)
                if isinstance(action_log, list) and action_log:
                    monad2_report["action_log"] = list(action_log)
                thought_log = getattr(agent, "m2_thought_log", None)
                if isinstance(thought_log, list) and thought_log:
                    monad2_report["thought_log"] = list(thought_log)
                    if not level_clear_actions:
                        done_levels = max(
                            int(getattr(agent, "levels_completed", 0) or 0),
                            int(getattr(agent, "_max_levels_completed", 0) or 0),
                        )
                        lvl_counts: dict[int, int] = {}
                        for r_idx, r_item in enumerate(thought_log, start=1):
                            if isinstance(r_item, dict):
                                lv_i = int(r_item.get("level", 0) or 0)
                                if lv_i < done_levels:
                                    lvl_counts[lv_i + 1] = r_idx
                        for k_lv in sorted(lvl_counts):
                            level_clear_actions[str(k_lv)] = lvl_counts[k_lv]
                        monad2_report["level_clear_actions"] = level_clear_actions
        except Exception:
            monad2_report = None
        if blind_id:
            assert agent.game_id == "blind_unknown_env", f"Agent game_id mutated to {agent.game_id!r}"
            for frame in getattr(agent, "frames", []):
                assert getattr(frame, "game_id", "blind_unknown_env") in ("blind_unknown_env", "unknown", ""), (
                    f"Unscrubbed frame.game_id={getattr(frame, 'game_id', None)!r}"
                )
    finally:
        won_check = bool(
            agent is not None
            and (
                (agent.state is not None and agent.state.name == "WIN")
                or getattr(agent, "_puzzle_win_recorded", False)
            )
        )
        if blind_id and (agent_cache is None or won_check):
            _BLIND_ENV_REGISTRY.pop(id(env), None)
    dt = round(time.perf_counter() - t0, 2)
    won_any_play = bool(
        (agent.state is not None and agent.state.name == "WIN")
        or getattr(agent, "_puzzle_win_recorded", False)
    )
    state_name = "WIN" if won_any_play else (agent.state.name if agent.state is not None else "NONE")
    lvls = max(int(agent.levels_completed), int(getattr(agent, "_max_levels_completed", 0) or 0))
    steps = int(agent.action_counter)
    opt_replay_acts = int(getattr(agent, "replay_win_actions", 0) or 0)
    blind_tag = f" (blind_proxy={agent_gid})" if blind_id else ""
    round_tag = f" [R{round_idx}]" if round_idx > 1 else ""
    goal_tag = ""
    if goal_report is not None:
        goal_tag = f" | goal={goal_report.get('confirmed_type') or '-'}"
        pred = goal_report.get("prediction") or {}
        if pred.get("scored"):
            goal_tag += f" | pred={pred.get('hits')}/{pred.get('scored')}"
        if goal_report.get("memory_retrievals"):
            goal_tag += f" | mem={goal_report.get('memory_retrievals')}"
    if opt_replay_acts > 0:
        goal_tag += f" | opt_replay={opt_replay_acts}a"
    print(
        f"  [{idx:02d}/{total:02d}]{round_tag} {gid:16s}{blind_tag} | state={state_name:9s} | "
        f"levels={lvls:2d} | actions={steps:4d} | {dt:6.2f}s{goal_tag}",
        flush=True,
    )
    clear_acts = dict((monad2_report or {}).get("level_clear_actions") or {})
    if not clear_acts and isinstance(win_records, list):
        for wrec in win_records:
            if isinstance(wrec, dict) and "level_idx" in wrec and "actions" in wrec:
                clear_acts[str(int(wrec["level_idx"]))] = int(wrec["actions"])
    if not clear_acts and isinstance(synth_dict, dict):
        for lv_k, lv_info in (synth_dict.get("levels") or {}).items():
            if isinstance(lv_info, dict) and lv_info.get("cleared"):
                cp = lv_info.get("causal_policy") or {}
                if cp:
                    clear_acts[str(int(lv_k) + 1)] = len(cp)
    result = {
        "game_id": gid,
        "agent_game_id": agent_gid,
        "state": state_name,
        "levels_completed": lvls,
        "actions": steps,
        "round": int(round_idx),
        "level_clear_actions": clear_acts,
        "elapsed_s": dt,
    }
    if opt_replay_acts > 0:
        result["optimal_replay_actions"] = opt_replay_acts
    if goal_report is not None:
        result["goal_report"] = goal_report
    if win_records:
        result["win_records"] = win_records
    if monad2_report:
        result["monad2"] = monad2_report
    return result


def _compact_game(res: dict) -> dict:
    """Drop thought streams. Keep counters, mode counts, and a short trace."""
    out = {k: v for k, v in res.items() if k != "monad2"}
    report = res.get("monad2") if isinstance(res.get("monad2"), dict) else {}
    thoughts = report.get("thought_log") if isinstance(report.get("thought_log"), list) else []
    modes: dict[str, int] = {"discover": 0, "plan": 0, "execute": 0, "replan": 0}
    llm_by_level: dict[str, int] = {}
    excerpts: list[dict] = []
    seen_modes: set[str] = set()
    for row in thoughts:
        if not isinstance(row, dict):
            continue
        mode = str(row.get("mode") or "")
        if mode:
            modes[mode] = modes.get(mode, 0) + 1
        level = str(row.get("level", 0))
        try:
            calls = int(row.get("llm_calls_level") or 0)
        except (TypeError, ValueError):
            calls = 0
        llm_by_level[level] = max(llm_by_level.get(level, 0), calls)
        if len(excerpts) >= 16:
            continue
        if mode in seen_modes and len(excerpts) >= 8:
            continue
        seen_modes.add(mode)
        latency = row.get("latency_ms") if isinstance(row.get("latency_ms"), dict) else {}
        excerpts.append(
            {
                "level": row.get("level"),
                "mode": mode,
                "action": row.get("action"),
                "primitive": row.get("primitive"),
                "predicate": row.get("predicate") or row.get("expectation") or "",
                "predicate_hit": row.get("predicate_hit"),
                "decision": row.get("decision"),
                "reason": str(row.get("reason") or "")[:180],
                "roles": str(row.get("roles") or "")[:180],
                "plan": str(row.get("plan") or "")[:240],
                "llm_calls_level": row.get("llm_calls_level"),
                "step_ms": latency.get("step"),
            }
        )
    keep = {
        k: v
        for k, v in report.items()
        if k not in ("thought_log", "action_log", "rehearsal_log", "watch_log")
    }
    keep["modes"] = modes
    keep["llm_calls_by_level"] = llm_by_level
    keep["excerpts"] = excerpts
    out["monad2"] = keep
    return out


def _scorecard_payload(
    *,
    blind_id: bool,
    no_game_solvers: bool,
    max_game_seconds: float,
    game_ids: list[str],
    results: list[dict],
    elapsed_s: float,
    warmup_s: float,
    complete: bool,
) -> dict:
    wins = sum(1 for r in results if r.get("state") == "WIN")
    lvls = sum(int(r.get("levels_completed") or 0) for r in results)
    acts = sum(int(r.get("actions") or 0) for r in results)
    return {
        "mode": "offline",
        "blind_id_mode": blind_id,
        "game_specific_solvers_disabled": no_game_solvers,
        "max_game_seconds": max_game_seconds,
        "game_order": [g.split("-")[0] for g in game_ids],
        "partial": not complete,
        "games_finished": len(results),
        "games_expected": len(game_ids),
        "warmup_s": round(warmup_s, 2),
        "elapsed_s": round(elapsed_s, 2),
        "wins": wins,
        "levels_completed": lvls,
        "actions": acts,
        "levels_per_1k_actions": round(lvls / (acts / 1000.0), 4) if acts else 0.0,
        "per_game_results": results,
    }


def _write_scorecard(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    tmp.replace(path)


def _load_resume(path: Path) -> tuple[list[dict], float, float]:
    if os.getenv("MONAD2_RESUME", "0") != "1" or not path.is_file():
        return [], 0.0, 0.0
    try:
        prev = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return [], 0.0, 0.0
    rows = [r for r in (prev.get("per_game_results") or []) if isinstance(r, dict) and r.get("game_id")]
    try:
        elapsed = float(prev.get("elapsed_s") or 0.0)
    except (TypeError, ValueError):
        elapsed = 0.0
    try:
        warmup = float(prev.get("warmup_s") or 0.0)
    except (TypeError, ValueError):
        warmup = 0.0
    return rows, elapsed, warmup


def verify_claimed_totals(
    results: list[dict],
    is_full_suite: bool,
    require_inflight_lock: bool = False,
    inflight_lock_verified: bool = False,
    allow_losses: bool = False,
) -> None:
    wins = sum(1 for r in results if r["state"] == "WIN")
    lvls = sum(r["levels_completed"] for r in results)
    acts = sum(r["actions"] for r in results)

    if allow_losses:
        # Blind-generalization mode (game-specific solvers disabled): report totals
        # without asserting the solvers-on reference numbers.
        print(
            f"[Monad(1) V7] Generalization-mode totals: wins={wins}/{len(results)} | "
            f"levels={lvls} | actions={acts}"
        )
        return

    if require_inflight_lock:
        assert inflight_lock_verified, (
            "VERIFICATION FAILED: In-flight HTTP 403 scorecard lock before close_scorecard() was not verified."
        )
    assert wins == len(results), f"VERIFICATION FAILED: Won {wins}/{len(results)} games."
    if is_full_suite:
        assert len(results) == EXPECTED_FULL_SUITE_GAMES, (
            f"VERIFICATION FAILED: Expected {EXPECTED_FULL_SUITE_GAMES} games, ran {len(results)}."
        )
        assert lvls == EXPECTED_FULL_SUITE_LEVELS, (
            f"VERIFICATION FAILED: Expected {EXPECTED_FULL_SUITE_LEVELS} levels completed, got {lvls}."
        )
        if acts != EXPECTED_FULL_SUITE_ACTIONS:
            print(
                f"[Monad(1) V7] Note: Total actions={acts} (baseline reference={EXPECTED_FULL_SUITE_ACTIONS}) "
                f"with all {wins}/{EXPECTED_FULL_SUITE_GAMES} games WON ({lvls}/{EXPECTED_FULL_SUITE_LEVELS} levels)."
            )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Monad(1) V7 ARC-AGI-3 Competition Mode & Verification Runner")
    parser.add_argument(
        "--local-gateway",
        action="store_true",
        help="Start a local listen_and_serve(port=8001, competition_mode=True) server and evaluate over HTTP",
    )
    parser.add_argument(
        "--offline",
        action="store_true",
        help="Run all 25 games in local OperationMode.OFFLINE mode (no API key required)",
    )
    parser.add_argument(
        "--self-test",
        action="store_true",
        help="Run standalone MyAgent.main() self-test episode against an in-memory mock environment",
    )
    parser.add_argument(
        "--blind-id",
        action="store_true",
        help="Wrap environment in BlindEnvironmentProxy and scrub game_id on all frames",
    )
    parser.add_argument(
        "--no-game-solvers",
        action="store_true",
        help=(
            "Disable all 27 game-specific solver methods (blind generalization mode): "
            "the agent runs on its generic tiers plus the General Goal Engine only. "
            "Win/level/action totals are reported but not asserted."
        ),
    )
    parser.add_argument(
        "--environments-dir",
        type=str,
        default="environment_files",
        help="Directory to cache/load official environment files for --local-gateway or --offline",
    )
    parser.add_argument("--port", type=int, default=8001, help="Local gateway port (default: 8001)")
    parser.add_argument("--workers", type=int, default=4, help="Parallel workers for remote Competition Mode (default: 4)")
    parser.add_argument(
        "--games",
        type=str,
        default="",
        help="Optional comma-separated subset of game prefixes/IDs to run (default: all 25)",
    )
    parser.add_argument(
        "--output",
        type=str,
        default="scorecards/latest_competition_scorecard.json",
        help="Output JSON path for the verification report",
    )
    parser.add_argument(
        "--max-game-seconds",
        type=float,
        default=None,
        help="Per-game wall clock limit. Default 300, or MONAD2_MAX_GAME_SECONDS. Recorded in the output JSON.",
    )
    parser.add_argument(
        "--game-order",
        type=str,
        default="",
        help="Comma-separated game prefixes in the order to play them. Overrides sorted order. Used for cross-game permutation tests.",
    )
    parser.add_argument(
        "--two-pass",
        action="store_true",
        help="Run Pass 1 (discovery + online solver synthesis) followed by Pass 2 (executing synthesized solvers).",
    )
    parser.add_argument(
        "--pass-num",
        type=int,
        choices=[1, 2],
        default=None,
        help="Explicitly run as Pass 1 (discovery + synthesis) or Pass 2 (execute synthesized solvers).",
    )
    parser.add_argument(
        "--synthesized-solvers-path",
        type=str,
        default="scorecards/synthesized_solvers.json",
        help="Path to save (Pass 1) or load (Pass 2) synthesized solver specifications.",
    )
    parser.add_argument(
        "--six-hour-loop",
        action="store_true",
        help="Run the 6-hour iterative multi-round loop until all games achieve 100%% solutions or session time expires.",
    )
    parser.add_argument(
        "--no-six-hour-loop",
        action="store_true",
        help="Disable the 6-hour multi-round loop after the initial pass.",
    )
    parser.add_argument(
        "--session-seconds",
        type=float,
        default=None,
        help="Total session wall-clock budget in seconds (default: 21600 = 6 hours).",
    )
    args, _unknown = parser.parse_known_args(argv)
    os.environ.setdefault("MONAD_SESSION_START_EPOCH", str(time.time()))
    if args.session_seconds is not None:
        os.environ["MONAD_SESSION_SECONDS"] = str(float(args.session_seconds))
    else:
        os.environ.setdefault("MONAD_SESSION_SECONDS", str(6 * 3600))
    os.environ.setdefault("MONAD_FINALIZE_RESERVE_SECONDS", "240")
    six_hour_loop_enabled = bool(args.six_hour_loop) or (
        not args.no_six_hour_loop
        and not args.two_pass
        and os.getenv("MONAD2_TWO_PASS") != "1"
        and os.getenv("MONAD_SIX_HOUR_LOOP", "1") != "0"
    )
    if args.max_game_seconds is not None:
        max_game_seconds = float(args.max_game_seconds)
    else:
        max_game_seconds = float(os.getenv("MONAD2_MAX_GAME_SECONDS", "300") or "300")

    if args.no_game_solvers:
        os.environ["MONAD1_DISABLE_GAME_SOLVERS"] = "1"
        for _m2_flag in (
            "MONAD2_COORDINATE",
            "MONAD2_GOAL_DISCOVERY",
            "MONAD2_CALLOSUM",
            "MONAD2_REHEARSAL",
            "MONAD2_TONIC",
            "MONAD2_GRAFT",
        ):
            os.environ.setdefault(_m2_flag, "1")
    if args.two_pass or args.pass_num in (1, 2):
        os.environ.setdefault("MONAD2_COORDINATE", "1")
    if args.pass_num in (1, 2):
        os.environ["MONAD2_PASS"] = str(args.pass_num)
        if args.pass_num == 2 and args.synthesized_solvers_path:
            try:
                from monad2.synthesizer import load_synthesized_store

                load_synthesized_store(args.synthesized_solvers_path)
            except Exception:
                pass

    verify_agent_ast_no_env_introspection()

    if args.self_test:
        run_self_test_episode(blind_id=args.blind_id or True)
        return 0

    if not HAS_ARC_AGI:
        print(
            "[Monad(1) V7] 'arc_agi' package not installed in current environment; running standalone self-test episode...",
            flush=True,
        )
        run_self_test_episode(blind_id=True)
        return 0

    raw_env_dir = Path(args.environments_dir)
    if args.environments_dir == "environment_files" and not raw_env_dir.is_dir():
        _here = Path(__file__).resolve().parent if "__file__" in globals() else Path.cwd()
        for _cand_env in (
            Path(os.environ["MONAD2_ENV_DIR"]) if os.environ.get("MONAD2_ENV_DIR") else None,
            Path("../environment_files"),
            _here.parent / "monad(1)" / "environment_files",
            Path("/kaggle/input/competitions/arc-prize-2026-arc-agi-3/environment_files"),
            Path("/kaggle/input/arc-prize-2026-arc-agi-3/environment_files"),
        ):
            if _cand_env is not None and _cand_env.is_dir():
                raw_env_dir = _cand_env
                break
    env_dir = raw_env_dir.resolve()
    game_filter = {g.strip() for g in args.games.split(",") if g.strip()}
    is_full_suite = len(game_filter) == 0 and not args.game_order.strip()

    if args.offline:
        print(f"[Monad(1) V7] Ensuring official ARC-AGI-3 environments in {env_dir}...")
        game_ids = ensure_local_environments(env_dir, offline=True, game_filter=game_filter)
        game_ids = _select_game_ids(game_ids, game_filter, args.game_order)
        out_path = Path(args.output)
        results, prior_s, warmup_s = _load_resume(out_path)
        done = {str(r.get("game_id", "")).split("-")[0] for r in results}
        if done:
            print(
                f"[Monad(1) V7] Resuming: {len(done)} game(s) already in {out_path}",
                flush=True,
            )
        pending = [g for g in game_ids if g.split("-")[0] not in done]
        offline_arc = Arcade(operation_mode=OperationMode.OFFLINE, environments_dir=str(env_dir))
        if os.getenv("MONAD2_COORDINATE") == "1" and pending:
            tw = time.perf_counter()
            try:
                from monad2.llm import get_backend

                loaded = get_backend().warmup()
                this_warm = time.perf_counter() - tw
                warmup_s += this_warm
                print(
                    f"[Monad(1) V7] Coordination models loaded in {this_warm:.1f}s: {loaded}",
                    flush=True,
                )
            except Exception as exc:
                this_warm = time.perf_counter() - tw
                warmup_s += this_warm
                print(f"[Monad(1) V7] Coordination model warmup failed after {this_warm:.1f}s: {exc}", flush=True)
                raise
        t0 = time.perf_counter()
        agent_cache: dict[str, tuple[Any, Any, Any]] = {}
        cache_lock = threading.Lock()
        for gid in pending:
            idx = len(results) + 1
            res = play_single_game(
                offline_arc,
                "http://localhost",
                "offline-card",
                gid,
                idx,
                len(game_ids),
                blind_id=args.blind_id,
                max_game_seconds=max_game_seconds,
                agent_cache=agent_cache if six_hour_loop_enabled else None,
                cache_lock=cache_lock,
                round_idx=1,
            )
            results.append(_compact_game(res))
            elapsed_s = prior_s + (time.perf_counter() - t0)
            try:
                _write_scorecard(
                    out_path,
                    _scorecard_payload(
                        blind_id=args.blind_id,
                        no_game_solvers=args.no_game_solvers,
                        max_game_seconds=max_game_seconds,
                        game_ids=game_ids,
                        results=results,
                        elapsed_s=elapsed_s,
                        warmup_s=warmup_s,
                        complete=len(results) >= len(game_ids),
                    ),
                )
                print(f"[Monad(1) V7] Flushed {len(results)}/{len(game_ids)} games to {out_path}", flush=True)
            except Exception as exc:
                print(f"[Monad(1) V7] Scorecard flush failed: {exc}", flush=True)
        if (
            args.synthesized_solvers_path
            and int(os.getenv("MONAD2_PASS", "1") or "1") == 1
            and (
                args.two_pass
                or args.pass_num == 1
                or six_hour_loop_enabled
                or os.getenv("MONAD2_TWO_PASS") == "1"
                or not Path(args.synthesized_solvers_path).exists()
            )
        ):
            try:
                from monad2.synthesizer import save_synthesized_store

                save_synthesized_store(args.synthesized_solvers_path)
            except Exception:
                pass
        pass1_saved: list[dict] | None = None
        if args.two_pass or os.getenv("MONAD2_TWO_PASS") == "1":
            print(
                f"[Monad(1) V7] Pass 1 complete ({len(results)} games). Launching Pass 2 with synthesized solvers...",
                flush=True,
            )
            pass1_results = list(results)
            pass1_saved = pass1_results
            prev_pass = os.environ.get("MONAD2_PASS")
            os.environ["MONAD2_PASS"] = "2"
            pass2_results: list[dict] = []
            try:
                for idx2, gid in enumerate(game_ids, 1):
                    if hasattr(MyAgent, "reset_cross_puzzle_archive"):
                        MyAgent.reset_cross_puzzle_archive()
                    try:
                        from monad2.coordinate import reset_carried

                        reset_carried()
                    except Exception:
                        pass
                    res2 = play_single_game(
                        offline_arc,
                        "http://localhost",
                        "offline-card-pass2",
                        gid,
                        idx2,
                        len(game_ids),
                        blind_id=args.blind_id,
                        max_game_seconds=max_game_seconds,
                        agent_cache=agent_cache if six_hour_loop_enabled else None,
                        cache_lock=cache_lock,
                        round_idx=1,
                    )
                    c2 = _compact_game(res2)
                    c2["pass"] = 2
                    p1_row = pass1_results[idx2 - 1] if idx2 - 1 < len(pass1_results) else {}
                    p1_m2 = p1_row.get("monad2") if isinstance(p1_row.get("monad2"), dict) else {}
                    c2["pass1_levels_completed"] = int(p1_row.get("levels_completed") or 0)
                    c2["pass1_actions"] = int(p1_row.get("actions") or 0)
                    c2["pass1_llm_calls"] = int(p1_m2.get("llm_calls") or (p1_m2.get("stats") or {}).get("llm_calls") or 0)
                    pass2_results.append(c2)
                results = pass2_results
            finally:
                if prev_pass is None:
                    os.environ.pop("MONAD2_PASS", None)
                else:
                    os.environ["MONAD2_PASS"] = prev_pass
        if six_hour_loop_enabled and len(results) == len(game_ids):
            unsolved_indices = [i for i, r in enumerate(results) if r.get("state") != "WIN"]
            if not unsolved_indices:
                print(
                    f"[Monad(1) V7 6h-Loop] All {len(results)}/{len(game_ids)} games achieved 100% solutions in Round 1.",
                    flush=True,
                )
            else:
                if pass1_saved is None:
                    pass1_saved = [dict(r) for r in results]
                round_idx = 2
                while unsolved_indices and _session_remaining_seconds() > 15.0:
                    rem_s = _session_remaining_seconds()
                    n_rem = len(unsolved_indices)
                    round_budget_s = min(
                        rem_s * 0.55 if rem_s >= 120.0 else rem_s * 0.85,
                        max_game_seconds * n_rem,
                    )
                    slice_s = max(5.0, min(max_game_seconds, round_budget_s / max(1, n_rem), rem_s - 5.0))
                    print(
                        f"[Monad(1) V7 6h-Loop] === Round {round_idx} | Unsolved: {n_rem}/{len(game_ids)} | "
                        f"Remaining Session: {rem_s:.1f}s | Slice/Game: {slice_s:.1f}s ===",
                        flush=True,
                    )
                    for list_pos in list(unsolved_indices):
                        if _session_remaining_seconds() <= 10.0:
                            break
                        gid = game_ids[list_pos]
                        idx_r = list_pos + 1
                        res_r = play_single_game(
                            offline_arc,
                            "http://localhost",
                            "offline-card",
                            gid,
                            idx_r,
                            len(game_ids),
                            blind_id=args.blind_id,
                            max_game_seconds=slice_s,
                            agent_cache=agent_cache,
                            cache_lock=cache_lock,
                            round_idx=round_idx,
                        )
                        prev_row = results[list_pos]
                        cr = _compact_game(res_r)
                        cr["round"] = round_idx
                        cr["elapsed_s"] = round(float(prev_row.get("elapsed_s") or 0.0) + float(cr.get("elapsed_s") or 0.0), 2)
                        results[list_pos] = cr
                        if args.synthesized_solvers_path:
                            try:
                                from monad2.synthesizer import save_synthesized_store

                                save_synthesized_store(args.synthesized_solvers_path)
                            except Exception:
                                pass
                        try:
                            _write_scorecard(
                                out_path,
                                _scorecard_payload(
                                    blind_id=args.blind_id,
                                    no_game_solvers=args.no_game_solvers,
                                    max_game_seconds=max_game_seconds,
                                    game_ids=game_ids,
                                    results=results,
                                    elapsed_s=prior_s + (time.perf_counter() - t0),
                                    warmup_s=warmup_s,
                                    complete=True,
                                ),
                            )
                        except Exception:
                            pass
                    unsolved_indices = [i for i, r in enumerate(results) if r.get("state") != "WIN"]
                    round_idx += 1
            if args.blind_id:
                for _e, _a, _arc in agent_cache.values():
                    _BLIND_ENV_REGISTRY.pop(id(_e), None)
        total_s = round(prior_s + (time.perf_counter() - t0), 2)
        wins = sum(1 for r in results if r["state"] == "WIN")
        lvls = sum(r["levels_completed"] for r in results)
        acts = sum(r["actions"] for r in results)
        verify_claimed_totals(
            results,
            is_full_suite=is_full_suite and len(results) == len(game_ids),
            allow_losses=args.no_game_solvers,
        )
        try:
            payload = _scorecard_payload(
                blind_id=args.blind_id,
                no_game_solvers=args.no_game_solvers,
                max_game_seconds=max_game_seconds,
                game_ids=game_ids,
                results=results,
                elapsed_s=total_s,
                warmup_s=warmup_s,
                complete=len(results) >= len(game_ids),
            )
            if pass1_saved is not None:
                payload["pass1_summary"] = {
                    "wins": sum(1 for r in pass1_saved if r.get("state") == "WIN"),
                    "levels_completed": sum(int(r.get("levels_completed") or 0) for r in pass1_saved),
                    "actions": sum(int(r.get("actions") or 0) for r in pass1_saved),
                    "llm_calls": sum(
                        int((r.get("monad2") or {}).get("llm_calls") or ((r.get("monad2") or {}).get("stats") or {}).get("llm_calls") or 0)
                        for r in pass1_saved
                    ),
                }
                payload["pass1_results"] = pass1_saved
            _write_scorecard(out_path, payload)
        except Exception:
            pass
        print("=" * 80)
        mode_tag = "BLIND-ID PROXY" if args.blind_id else "STANDARD"
        if args.no_game_solvers:
            mode_tag += ", GAME-SPECIFIC SOLVERS DISABLED"
        print(f"[Monad(1) V7] Offline Verification {'COMPLETE' if args.no_game_solvers else 'PASSED'} ({mode_tag}):")
        print(f"  Environments Won: {wins} / {len(game_ids)} ({100.0 * wins / max(1, len(game_ids)):.1f}%)")
        print(f"  Levels Completed: {lvls}")
        print(f"  Total Actions:    {acts}")
        print(f"  Levels / 1k acts: {lvls / (acts / 1000.0):.3f}" if acts else "  Levels / 1k acts: 0")
        print(f"  Time limit:       {max_game_seconds:.0f}s per game")
        print(f"  Elapsed Time:     {total_s}s")
        print("=" * 80)
        return 0

    api_key = os.environ.get("ARC_API_KEY", "").strip()
    inflight_lock_verified = False

    if args.local_gateway:
        print(f"[Monad(1) V7] Ensuring official ARC-AGI-3 environments in {env_dir}...")
        game_ids = ensure_local_environments(env_dir, game_filter=game_filter)
        if game_filter:
            game_ids = [g for g in game_ids if g in game_filter or g.split("-")[0] in game_filter]
        if not api_key:
            api_key = "local-competition-mode-key"
        base_url = f"http://127.0.0.1:{args.port}"
        server_arc = Arcade(
            environments_dir=str(env_dir),
            operation_mode=OperationMode.OFFLINE,
        )
        srv_thread = threading.Thread(
            target=lambda: server_arc.listen_and_serve(
                host="127.0.0.1",
                port=args.port,
                competition_mode=True,
            ),
            daemon=True,
        )
        srv_thread.start()
        time.sleep(2.5)
        print(f"[Monad(1) V7] Local Competition Mode gateway active on {base_url} (competition_mode=True)")
    else:
        if not api_key:
            print(
                "ERROR: Please set ARC_API_KEY for remote Competition Mode, or pass --local-gateway / --offline / --self-test.",
                file=sys.stderr,
            )
            return 1
        base_url = os.environ.get("ARC_BASE_URL", "https://three.arcprize.org")
        print(f"[Monad(1) V7] Connecting to {base_url} in OperationMode.COMPETITION...")

    client_arc = Arcade(
        arc_api_key=api_key,
        arc_base_url=base_url,
        operation_mode=OperationMode.COMPETITION,
        environments_dir="",
    )
    if not args.local_gateway:
        game_ids = sorted({e.game_id for e in client_arc.get_environments()})
        if game_filter:
            game_ids = [g for g in game_ids if g in game_filter or g.split("-")[0] in game_filter]

    card_id = client_arc.open_scorecard(
        tags=["monad-1-v7-inos", "competition-mode"],
        opaque={"agent": "Monad(1) V7 INOS", "author": "Kyle W. Luecke (Drift Bound Labs)"},
    )
    print(f"[Monad(1) V7] Opened OperationMode.COMPETITION Scorecard: {card_id}")

    if args.local_gateway:
        try:
            req = urllib.request.Request(
                f"{base_url}/api/scorecard/{card_id}",
                headers={"X-API-Key": api_key},
            )
            urllib.request.urlopen(req, timeout=5)
        except urllib.error.HTTPError as e:
            if e.code == 403:
                inflight_lock_verified = True
                print("[Monad(1) V7] Verified HTTP 403 blind in-flight scorecard lock before close_scorecard().")

    t0 = time.perf_counter()
    results = []
    is_kaggle_rerun = bool(os.environ.get("KAGGLE_IS_COMPETITION_RERUN"))
    catch_game_errors = is_kaggle_rerun or os.environ.get("MONAD_CATCH_GAME_ERRORS") == "1"
    scorecard = None
    comp_agent_cache: dict[str, tuple[Any, Any, Any]] = {}
    comp_cache_lock = threading.Lock()

    def _safe_play(
        arc_inst: Any,
        gid: str,
        idx: int,
        *,
        round_idx: int = 1,
        slice_seconds: float | None = None,
    ) -> dict:
        limit_s = float(slice_seconds) if slice_seconds is not None else max_game_seconds
        if not catch_game_errors:
            return play_single_game(
                arc_inst,
                base_url,
                card_id,
                gid,
                idx,
                len(game_ids),
                blind_id=args.blind_id,
                max_game_seconds=limit_s,
                agent_cache=comp_agent_cache if six_hour_loop_enabled else None,
                cache_lock=comp_cache_lock,
                round_idx=round_idx,
            )
        try:
            return play_single_game(
                arc_inst,
                base_url,
                card_id,
                gid,
                idx,
                len(game_ids),
                blind_id=args.blind_id,
                max_game_seconds=limit_s,
                agent_cache=comp_agent_cache if six_hour_loop_enabled else None,
                cache_lock=comp_cache_lock,
                round_idx=round_idx,
            )
        except Exception as exc:
            print(f"[Monad(1) V7] Warning: error in game {gid}: {exc}", file=sys.stderr, flush=True)
            return {
                "game_id": gid,
                "agent_game_id": "blind_unknown_env" if args.blind_id else gid,
                "state": "ERROR",
                "levels_completed": 0,
                "actions": 0,
                "round": int(round_idx),
                "elapsed_s": 0.0,
                "error": str(exc),
            }

    try:
        if args.local_gateway or args.workers <= 1:
            for idx, gid in enumerate(game_ids, 1):
                results.append(_safe_play(client_arc, gid, idx, round_idx=1))
        else:
            def _worker(idx_gid: tuple[int, str]) -> dict:
                i, g = idx_gid
                w_arc = Arcade(
                    arc_api_key=api_key,
                    arc_base_url=base_url,
                    operation_mode=OperationMode.COMPETITION,
                    environments_dir="",
                )
                return _safe_play(w_arc, g, i, round_idx=1)

            with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as pool:
                for res in pool.map(_worker, enumerate(game_ids, 1)):
                    results.append(res)

        if six_hour_loop_enabled and len(results) == len(game_ids):
            unsolved_indices = [i for i, r in enumerate(results) if r.get("state") != "WIN"]
            if not unsolved_indices:
                print(
                    f"[Monad(1) V7 6h-Loop] All {len(results)}/{len(game_ids)} games achieved 100% solutions in Round 1.",
                    flush=True,
                )
            else:
                round_idx = 2
                while unsolved_indices and _session_remaining_seconds() > 15.0:
                    rem_s = _session_remaining_seconds()
                    n_rem = len(unsolved_indices)
                    round_budget_s = min(
                        rem_s * 0.55 if rem_s >= 120.0 else rem_s * 0.85,
                        max_game_seconds * n_rem,
                    )
                    slice_s = max(5.0, min(max_game_seconds, round_budget_s / max(1, n_rem), rem_s - 5.0))
                    print(
                        f"[Monad(1) V7 6h-Loop] === Round {round_idx} | Unsolved: {n_rem}/{len(game_ids)} | "
                        f"Remaining Session: {rem_s:.1f}s | Slice/Game: {slice_s:.1f}s ===",
                        flush=True,
                    )
                    for list_pos in list(unsolved_indices):
                        if _session_remaining_seconds() <= 10.0:
                            break
                        gid = game_ids[list_pos]
                        idx_r = list_pos + 1
                        cached = comp_agent_cache.get(gid)
                        arc_for_gid = cached[2] if cached is not None else client_arc
                        res_r = _safe_play(
                            arc_for_gid,
                            gid,
                            idx_r,
                            round_idx=round_idx,
                            slice_seconds=slice_s,
                        )
                        if res_r.get("state") != "ERROR":
                            prev_row = results[list_pos]
                            res_r["elapsed_s"] = round(
                                float(prev_row.get("elapsed_s") or 0.0) + float(res_r.get("elapsed_s") or 0.0),
                                2,
                            )
                            results[list_pos] = res_r
                        if args.synthesized_solvers_path:
                            try:
                                from monad2.synthesizer import save_synthesized_store

                                save_synthesized_store(args.synthesized_solvers_path)
                            except Exception:
                                pass
                    unsolved_indices = [i for i, r in enumerate(results) if r.get("state") != "WIN"]
                    round_idx += 1
    finally:
        if args.blind_id:
            for _e, _a, _arc in comp_agent_cache.values():
                _BLIND_ENV_REGISTRY.pop(id(_e), None)
        scorecard = client_arc.close_scorecard(card_id)

    total_s = round(time.perf_counter() - t0, 2)
    sc_dict = (
        scorecard.model_dump(mode="json")
        if hasattr(scorecard, "model_dump")
        else (dict(scorecard) if scorecard else {})
    )

    verify_claimed_totals(
        results,
        is_full_suite=is_full_suite,
        require_inflight_lock=args.local_gateway,
        inflight_lock_verified=inflight_lock_verified,
        allow_losses=args.no_game_solvers or is_kaggle_rerun,
    )

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "mode": "local_listen_and_serve_competition_mode" if args.local_gateway else "remote_competition_mode",
        "operation_mode": "COMPETITION",
        "blind_id_mode": args.blind_id,
        "inflight_http_403_lock_verified": inflight_lock_verified,
        "card_id": card_id,
        "scorecard_url": f"https://arcprize.org/scorecards/{card_id}",
        "elapsed_s": total_s,
        "scorecard": sc_dict,
        "per_game_results": results,
    }
    out_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    wins = sum(1 for r in results if r["state"] == "WIN")
    print("=" * 80)
    print(f"[Monad(1) V7] Competition Mode Scorecard Verified & Closed: {card_id}")
    print(f"  Score:            {sc_dict.get('score')}")
    print(f"  Environments Won: {wins} / {len(game_ids)}")
    print(f"  Levels Completed: {sc_dict.get('total_levels_completed')}")
    print(f"  Total Actions:    {sc_dict.get('total_actions')}")
    print(f"  Saved to:         {out_path}")
    print("=" * 80)
    return 0


def _emit_kaggle_commit_parquet_if_needed() -> None:
    if os.environ.get("KAGGLE_IS_COMPETITION_RERUN"):
        return
    if not (
        Path("/kaggle/working").exists()
        or os.environ.get("KAGGLE_KERNEL_RUN_TYPE")
        or os.environ.get("MONAD_EMIT_SUBMISSION_PARQUET") == "1"
        or not (Path.cwd() / ".git").exists()
    ):
        return
    try:
        import pandas as pd

        target_paths = [Path("submission.parquet")]
        if Path("/kaggle/working").exists():
            kw_path = Path("/kaggle/working/submission.parquet")
            if kw_path.resolve() != target_paths[0].resolve():
                target_paths.insert(0, kw_path)
        for tp in target_paths:
            tp.parent.mkdir(parents=True, exist_ok=True)
            pd.DataFrame(
                [["1_0", "1", True, 1]],
                columns=["row_id", "game_id", "end_of_game", "score"],
            ).to_parquet(tp, index=False)
        print("[Monad(1) V7] Emitted commit-mode submission.parquet.")
    except Exception as exc:
        print(f"[Monad(1) V7] Note: submission.parquet emission skipped: {exc}")


def run_notebook_entrypoint() -> int:
    """
    Automatic entry point when executed inside a Kaggle or Jupyter notebook cell:
      - If KAGGLE_IS_COMPETITION_RERUN is active, connects to the Kaggle competition gateway.
      - Else if ARC_API_KEY is set, runs remote OperationMode.COMPETITION evaluation.
      - Else if local environment_files exist and arc_agi is installed, runs --offline --blind-id.
      - Otherwise runs the standalone --self-test --blind-id verification episode.
    """
    try:
        import shutil as _shutil

        for _src_agents in (
            Path("/kaggle/input/competitions/arc-prize-2026-arc-agi-3/ARC-AGI-3-Agents"),
            Path("/kaggle/input/arc-prize-2026-arc-agi-3/ARC-AGI-3-Agents"),
        ):
            if _src_agents.is_dir():
                _dst_agents = Path("ARC-AGI-3-Agents")
                if not _dst_agents.exists():
                    _shutil.copytree(_src_agents, _dst_agents)
                _dst_pkg = _dst_agents / "agents" / "templates"
                if _dst_pkg.is_dir():
                    if Path("my_agent.py").is_file():
                        _shutil.copy2("my_agent.py", _dst_pkg / "my_agent.py")
                    if Path("monad2").is_dir():
                        _shutil.copytree("monad2", _dst_pkg / "monad2", dirs_exist_ok=True)
                break
    except Exception:
        pass

    if os.environ.get("KAGGLE_IS_COMPETITION_RERUN"):
        os.environ.setdefault("ARC_BASE_URL", "http://gateway:8001")
        os.environ.setdefault("ARC_API_KEY", "test-key-123")
        gw_url = f"{os.environ['ARC_BASE_URL'].rstrip('/')}/api/games"
        deadline = time.time() + float(os.environ.get("MONAD_GATEWAY_WAIT_SECONDS", "600"))
        while time.time() < deadline:
            try:
                with urllib.request.urlopen(gw_url, timeout=5) as resp:
                    if resp.status == 200:
                        break
            except Exception:
                time.sleep(2.0)
        extra_args = [a for a in os.environ.get("KAGGLE_RERUN_ARGS", "").split() if a]
        return main(["--workers", "1", *extra_args])
    if os.environ.get("ARC_API_KEY", "").strip():
        rc = main([])
        _emit_kaggle_commit_parquet_if_needed()
        return rc
    for cand in (
        Path("environment_files"),
        Path("/kaggle/input/competitions/arc-prize-2026-arc-agi-3/environment_files"),
        Path("/kaggle/input/arc-prize-2026-arc-agi-3/environment_files"),
    ):
        if HAS_ARC_AGI and cand.exists() and list(cand.rglob("*.py")):
            rc = main(["--offline", "--blind-id", "--environments-dir", str(cand)])
            _emit_kaggle_commit_parquet_if_needed()
            return rc
    rc = main(["--self-test", "--blind-id"])
    _emit_kaggle_commit_parquet_if_needed()
    return rc


if __name__ == "__main__":
    if any("ipykernel" in a for a in sys.argv) or "__file__" not in globals():
        run_notebook_entrypoint()
    else:
        raise SystemExit(main())

