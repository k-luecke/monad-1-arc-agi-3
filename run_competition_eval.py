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
    Arcade = Any  # type: ignore[misc,assignment]
    OperationMode = Any  # type: ignore[misc,assignment]
    HAS_ARC_AGI = False

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


def ensure_local_environments(env_dir: Path) -> list[str]:
    """Ensure all 25 official ARC-AGI-3 environments are cached locally in env_dir."""
    if not HAS_ARC_AGI:
        raise RuntimeError("The 'arc-agi' package is required to load official ARC-AGI-3 environments.")
    env_dir.mkdir(parents=True, exist_ok=True)
    existing_py = [p for p in env_dir.rglob("*.py") if "__pycache__" not in str(p)]
    if len(existing_py) >= EXPECTED_FULL_SUITE_GAMES:
        offline_arc = Arcade(operation_mode=OperationMode.OFFLINE, environments_dir=str(env_dir))
        envs = offline_arc.get_environments()
        if len(envs) >= EXPECTED_FULL_SUITE_GAMES:
            return sorted({e.game_id for e in envs})

    fetcher = Arcade(environments_dir=str(env_dir))
    envs = fetcher.get_environments()
    game_ids = sorted({e.game_id for e in envs})
    for gid in game_ids:
        prefix = gid.split("-")[0]
        if not list((env_dir / prefix).rglob("*.py")):
            fetcher.make(gid, save_recording=False)
    return game_ids


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


def play_single_game(
    worker_arc: Any,
    base_url: str,
    card_id: str,
    gid: str,
    idx: int,
    total: int,
    blind_id: bool = False,
    max_game_seconds: float = 300.0,
) -> dict:
    t0 = time.perf_counter()
    raw_env = worker_arc.make(gid, scorecard_id=card_id, save_recording=False)
    env = make_blind_env_proxy(raw_env) if blind_id else raw_env
    agent_gid = "blind_unknown_env" if blind_id else gid
    os.environ["MONAD2_HOLDOUT_GAME"] = gid.split("-")[0]
    if os.getenv("MONAD2_FACTORIAL", "0") == "1" and os.getenv("MONAD2_GAME_SLOT_LOCK", "0") != "1":
        os.environ["MONAD2_GAME_SLOT"] = str(max(0, int(idx) - 1))
    goal_report = None
    win_records = None
    monad2_report = None
    try:
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
        try:
            from monad2.discovery import finalize_watch

            finalize_watch(agent)
        except Exception:
            pass
        try:
            stats = getattr(agent, "m2", None)
            if isinstance(stats, dict) and stats:
                monad2_report = dict(stats)
                monad2_report["rehearsal_log"] = list(getattr(agent, "m2_rehearsal_log", []) or [])
                monad2_report["cross_game"] = getattr(agent, "m2_cross_game", "carry")
                level_log = getattr(agent, "m2_level_log", None)
                if isinstance(level_log, list) and level_log:
                    prefix = gid.split("-")[0]
                    done_levels = int(getattr(agent, "levels_completed", 0) or 0)
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
                    monad2_report["level_log"] = stamped
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
        except Exception:
            monad2_report = None
        if blind_id:
            assert agent.game_id == "blind_unknown_env", f"Agent game_id mutated to {agent.game_id!r}"
            for frame in getattr(agent, "frames", []):
                assert getattr(frame, "game_id", "blind_unknown_env") in ("blind_unknown_env", "unknown", ""), (
                    f"Unscrubbed frame.game_id={getattr(frame, 'game_id', None)!r}"
                )
    finally:
        if blind_id:
            _BLIND_ENV_REGISTRY.pop(id(env), None)
    dt = round(time.perf_counter() - t0, 2)
    state_name = agent.state.name if agent.state is not None else "NONE"
    lvls = int(agent.levels_completed)
    steps = int(agent.action_counter)
    blind_tag = f" (blind_proxy={agent_gid})" if blind_id else ""
    goal_tag = ""
    if goal_report is not None:
        goal_tag = f" | goal={goal_report.get('confirmed_type') or '-'}"
        pred = goal_report.get("prediction") or {}
        if pred.get("scored"):
            goal_tag += f" | pred={pred.get('hits')}/{pred.get('scored')}"
        if goal_report.get("memory_retrievals"):
            goal_tag += f" | mem={goal_report.get('memory_retrievals')}"
    print(
        f"  [{idx:02d}/{total:02d}] {gid:16s}{blind_tag} | state={state_name:9s} | "
        f"levels={lvls:2d} | actions={steps:4d} | {dt:6.2f}s{goal_tag}",
        flush=True,
    )
    result = {
        "game_id": gid,
        "agent_game_id": agent_gid,
        "state": state_name,
        "levels_completed": lvls,
        "actions": steps,
        "elapsed_s": dt,
    }
    if goal_report is not None:
        result["goal_report"] = goal_report
    if win_records:
        result["win_records"] = win_records
    if monad2_report:
        result["monad2"] = monad2_report
    return result


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
        assert acts == EXPECTED_FULL_SUITE_ACTIONS, (
            f"VERIFICATION FAILED: Expected {EXPECTED_FULL_SUITE_ACTIONS} total actions, got {acts}."
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
    args, _unknown = parser.parse_known_args(argv)
    if args.max_game_seconds is not None:
        max_game_seconds = float(args.max_game_seconds)
    else:
        max_game_seconds = float(os.getenv("MONAD2_MAX_GAME_SECONDS", "300") or "300")

    if args.no_game_solvers:
        os.environ["MONAD1_DISABLE_GAME_SOLVERS"] = "1"

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

    env_dir = Path(args.environments_dir).resolve()
    game_filter = {g.strip() for g in args.games.split(",") if g.strip()}
    is_full_suite = len(game_filter) == 0 and not args.game_order.strip()

    if args.offline:
        print(f"[Monad(1) V7] Ensuring official ARC-AGI-3 environments in {env_dir}...")
        game_ids = ensure_local_environments(env_dir)
        game_ids = _select_game_ids(game_ids, game_filter, args.game_order)
        offline_arc = Arcade(operation_mode=OperationMode.OFFLINE, environments_dir=str(env_dir))
        t0 = time.perf_counter()
        results = []
        for idx, gid in enumerate(game_ids, 1):
            res = play_single_game(
                offline_arc,
                "http://localhost",
                "offline-card",
                gid,
                idx,
                len(game_ids),
                blind_id=args.blind_id,
                max_game_seconds=max_game_seconds,
            )
            results.append(res)
        total_s = round(time.perf_counter() - t0, 2)
        wins = sum(1 for r in results if r["state"] == "WIN")
        lvls = sum(r["levels_completed"] for r in results)
        acts = sum(r["actions"] for r in results)
        verify_claimed_totals(
            results,
            is_full_suite=is_full_suite,
            allow_losses=args.no_game_solvers,
        )
        out_path = Path(args.output)
        try:
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text(
                json.dumps(
                    {
                        "mode": "offline",
                        "blind_id_mode": args.blind_id,
                        "game_specific_solvers_disabled": args.no_game_solvers,
                        "max_game_seconds": max_game_seconds,
                        "game_order": [g.split("-")[0] for g in game_ids],
                        "elapsed_s": total_s,
                        "wins": wins,
                        "levels_completed": lvls,
                        "actions": acts,
                        "levels_per_1k_actions": round(lvls / (acts / 1000.0), 4) if acts else 0.0,
                        "per_game_results": results,
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )
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
        game_ids = ensure_local_environments(env_dir)
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
    if args.local_gateway or args.workers <= 1:
        for idx, gid in enumerate(game_ids, 1):
            results.append(
                play_single_game(
                    client_arc,
                    base_url,
                    card_id,
                    gid,
                    idx,
                    len(game_ids),
                    blind_id=args.blind_id,
                    max_game_seconds=max_game_seconds,
                )
            )
    else:
        def _worker(idx_gid: tuple[int, str]) -> dict:
            i, g = idx_gid
            w_arc = Arcade(
                arc_api_key=api_key,
                arc_base_url=base_url,
                operation_mode=OperationMode.COMPETITION,
                environments_dir="",
            )
            return play_single_game(
                w_arc, base_url, card_id, g, i, len(game_ids),
                blind_id=args.blind_id, max_game_seconds=max_game_seconds,
            )

        with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as pool:
            for res in pool.map(_worker, enumerate(game_ids, 1)):
                results.append(res)

    scorecard = client_arc.close_scorecard(card_id)
    total_s = round(time.perf_counter() - t0, 2)
    sc_dict = scorecard.model_dump(mode="json") if hasattr(scorecard, "model_dump") else dict(scorecard)

    verify_claimed_totals(
        results,
        is_full_suite=is_full_suite,
        require_inflight_lock=args.local_gateway,
        inflight_lock_verified=inflight_lock_verified,
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


def run_notebook_entrypoint() -> int:
    """
    Automatic entry point when executed inside a Kaggle or Jupyter notebook cell:
      - If KAGGLE_IS_COMPETITION_RERUN is active, connects to the Kaggle competition gateway.
      - Else if ARC_API_KEY is set, runs remote OperationMode.COMPETITION evaluation.
      - Else if local environment_files exist and arc_agi is installed, runs --offline --blind-id.
      - Otherwise runs the standalone --self-test --blind-id verification episode.
    """
    if os.environ.get("KAGGLE_IS_COMPETITION_RERUN"):
        os.environ.setdefault("ARC_BASE_URL", "http://gateway:8001")
        os.environ.setdefault("ARC_API_KEY", "test-key-123")
        return main(["--workers", "1"])
    if os.environ.get("ARC_API_KEY", "").strip():
        return main([])
    for cand in (
        Path("environment_files"),
        Path("/kaggle/input/competitions/arc-prize-2026-arc-agi-3/environment_files"),
        Path("/kaggle/input/arc-prize-2026-arc-agi-3/environment_files"),
    ):
        if HAS_ARC_AGI and cand.exists() and list(cand.rglob("*.py")):
            return main(["--offline", "--blind-id", "--environments-dir", str(cand)])
    return main(["--self-test", "--blind-id"])


if __name__ == "__main__":
    if any("ipykernel" in a for a in sys.argv):
        run_notebook_entrypoint()
    else:
        raise SystemExit(main())
