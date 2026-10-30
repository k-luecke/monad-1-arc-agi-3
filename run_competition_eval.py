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
     python run_competition_eval.py --local-gateway

  3. Offline 25-Game Verification (with optional --blind-id to strip game_id):
     python run_competition_eval.py --offline --blind-id
"""
from __future__ import annotations

import argparse
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

os.environ.setdefault("INOS_BRIDGE_MODE", "STATIC_MONOLITH_IN_MEMORY")
os.environ.setdefault("INOS_USE_EXTERNAL_DAEMON", "0")

logging.getLogger("arc_agi").setLevel(logging.WARNING)
logging.getLogger("werkzeug").setLevel(logging.ERROR)

from arc_agi import Arcade, OperationMode
from arcengine import GameState
from my_agent_v7_inos import MyAgent


def ensure_local_environments(env_dir: Path) -> list[str]:
    """Ensure all 25 official ARC-AGI-3 environments are cached locally in env_dir."""
    env_dir.mkdir(parents=True, exist_ok=True)
    fetcher = Arcade(environments_dir=str(env_dir))
    envs = fetcher.get_environments()
    game_ids = sorted({e.game_id for e in envs})
    # Ensure each environment's files are downloaded into env_dir
    for gid in game_ids:
        prefix = gid.split("-")[0]
        if not list((env_dir / prefix).rglob("*.py")):
            fetcher.make(gid, save_recording=False)
    return game_ids


def play_single_game(
    worker_arc: Arcade,
    base_url: str,
    card_id: str,
    gid: str,
    idx: int,
    total: int,
    blind_id: bool = False,
) -> dict:
    t0 = time.perf_counter()
    env = worker_arc.make(gid, scorecard_id=card_id, save_recording=False)
    agent_gid = "blind_unknown_env" if blind_id else gid
    agent = MyAgent(
        card_id=card_id,
        game_id=agent_gid,
        agent_name="monad(1)-v7-inos",
        ROOT_URL=base_url,
        record=False,
        arc_env=env,
        tags=["monad(1)", "v7-inos", "competition-mode"],
    )
    agent.max_game_seconds = 300.0
    agent.main()
    dt = round(time.perf_counter() - t0, 2)
    state_name = agent.state.name if agent.state is not None else "NONE"
    lvls = int(agent.levels_completed)
    steps = int(agent.action_counter)
    blind_tag = f" (agent_game_id={agent_gid})" if blind_id else ""
    print(
        f"  [{idx:02d}/{total:02d}] {gid:16s}{blind_tag} | state={state_name:9s} | "
        f"levels={lvls:2d} | actions={steps:4d} | {dt:6.2f}s",
        flush=True,
    )
    return {
        "game_id": gid,
        "agent_game_id": agent_gid,
        "state": state_name,
        "levels_completed": lvls,
        "actions": steps,
        "elapsed_s": dt,
    }


def main() -> int:
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
        "--blind-id",
        action="store_true",
        help="Pass game_id='blind_unknown_env' to MyAgent on every game to verify zero game-ID dependence",
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
    args = parser.parse_args()

    env_dir = Path(args.environments_dir).resolve()
    game_filter = {g.strip() for g in args.games.split(",") if g.strip()}

    if args.offline:
        print(f"[Monad(1) V7] Ensuring official ARC-AGI-3 environments in {env_dir}...")
        game_ids = ensure_local_environments(env_dir)
        if game_filter:
            game_ids = [g for g in game_ids if g in game_filter or g.split("-")[0] in game_filter]
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
            )
            results.append(res)
        total_s = round(time.perf_counter() - t0, 2)
        wins = sum(1 for r in results if r["state"] == "WIN")
        lvls = sum(r["levels_completed"] for r in results)
        acts = sum(r["actions"] for r in results)
        print("=" * 80)
        print(f"[Monad(1) V7] Offline Verification Complete ({'BLIND-ID' if args.blind_id else 'STANDARD'}):")
        print(f"  Environments Won: {wins} / {len(game_ids)} ({100.0 * wins / max(1, len(game_ids)):.1f}%)")
        print(f"  Levels Completed: {lvls}")
        print(f"  Total Actions:    {acts}")
        print(f"  Elapsed Time:     {total_s}s")
        print("=" * 80)
        return 0 if wins == len(game_ids) else 1

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
                "ERROR: Please set ARC_API_KEY for remote Competition Mode, or pass --local-gateway / --offline.",
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
            return play_single_game(w_arc, base_url, card_id, g, i, len(game_ids), blind_id=args.blind_id)

        with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as pool:
            for res in pool.map(_worker, enumerate(game_ids, 1)):
                results.append(res)

    scorecard = client_arc.close_scorecard(card_id)
    total_s = round(time.perf_counter() - t0, 2)
    sc_dict = scorecard.model_dump(mode="json") if hasattr(scorecard, "model_dump") else dict(scorecard)

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
    print(f"[Monad(1) V7] Competition Mode Scorecard Closed: {card_id}")
    print(f"  Score:            {sc_dict.get('score')}")
    print(f"  Environments Won: {wins} / {len(game_ids)}")
    print(f"  Levels Completed: {sc_dict.get('total_levels_completed')}")
    print(f"  Total Actions:    {sc_dict.get('total_actions')}")
    print(f"  Saved to:         {out_path}")
    print("=" * 80)
    return 0 if wins == len(game_ids) else 1


if __name__ == "__main__":
    raise SystemExit(main())
