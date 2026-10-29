#!/usr/bin/env python3
"""
Monad(1) V7 (INOS v0.7) — Official ARC-AGI-3 Competition Mode Reproduction Harness
Author: Kyle W. Luecke (Drift Bound Labs)
License: Apache-2.0

Usage:
  1. Official Remote Competition Mode (generates a verified scorecard on https://arcprize.org):
     export ARC_API_KEY="your-arc-prize-api-key"
     python run_competition_eval.py

  2. Local Kaggle Rerun Gateway Replica (runs listen_and_serve(port=8001, competition_mode=True)):
     python run_competition_eval.py --local-gateway --environments-dir /path/to/environment_files
"""
import argparse
import concurrent.futures
import json
import os
import sys
import threading
import time
from pathlib import Path

from arc_agi import Arcade, OperationMode
from arcengine import GameAction, GameState

from my_agent_v7_inos import MyAgent

OFFICIAL_25_GAMES = [
    "ls20", "ft09", "vc33", "sp80", "lp85",
    "sb26", "tr87", "cn04", "OR53", "r11l",
    "m0r0", "dc22", "tl00", "c69f", "p17d",
    "f78r", "t5c2", "g50t", "s5i5", "b76x",
    "sk48", "bp35", "ka59", "wa30", "cd82",
]


def play_single_game(
    base_url: str,
    api_key: str,
    card_id: str,
    gid: str,
    idx: int,
    total: int,
    max_steps: int = 800,
) -> dict:
    t0 = time.perf_counter()
    worker_arc = Arcade(
        arc_api_key=api_key,
        arc_base_url=base_url,
        operation_mode=OperationMode.COMPETITION,
        environments_dir="",
    )
    env = worker_arc.make(gid, scorecard_id=card_id)
    agent = MyAgent(game_id=gid)
    obs = env.reset()
    steps = 0
    while steps < max_steps and obs is not None and obs.state not in (GameState.WIN, GameState.GAME_OVER):
        action, data = agent.act(obs)
        if action == GameAction.RESET:
            obs = env.reset()
        else:
            obs = env.step(action, data=data or {})
        steps += 1
    dt = round(time.perf_counter() - t0, 2)
    state_name = obs.state.name if obs is not None else "NONE"
    lvls = int(obs.levels_completed) if obs is not None else 0
    print(
        f"  [{idx:02d}/{total:02d}] {gid}: state={state_name} | levels={lvls} | actions={steps} | {dt:.2f}s",
        flush=True,
    )
    return {
        "game_id": gid,
        "state": state_name,
        "levels_completed": lvls,
        "actions": steps,
        "elapsed_s": dt,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Monad(1) V7 ARC-AGI-3 Competition Mode Runner")
    parser.add_argument(
        "--local-gateway",
        action="store_true",
        help="Start a local listen_and_serve(port=8001, competition_mode=True) server instead of connecting to three.arcprize.org",
    )
    parser.add_argument(
        "--environments-dir",
        type=str,
        default="environment_files",
        help="Path to local environment_files directory when using --local-gateway",
    )
    parser.add_argument("--port", type=int, default=8001, help="Local gateway port (default: 8001)")
    parser.add_argument("--workers", type=int, default=4, help="Parallel game workers (default: 4)")
    parser.add_argument(
        "--output",
        type=str,
        default="scorecards/latest_competition_scorecard.json",
        help="Output JSON path for the closed Competition Mode scorecard",
    )
    args = parser.parse_args()

    api_key = os.environ.get("ARC_API_KEY", "").strip()
    if args.local_gateway:
        if not api_key:
            api_key = "local-competition-mode-key"
            os.environ["ARC_API_KEY"] = api_key
        base_url = f"http://127.0.0.1:{args.port}"
        server_arc = Arcade(
            environments_dir=args.environments_dir,
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
            print("ERROR: Please set the ARC_API_KEY environment variable before running in remote Competition Mode.", file=sys.stderr)
            return 1
        base_url = os.environ.get("ARC_BASE_URL", "https://three.arcprize.org")
        print(f"[Monad(1) V7] Connecting to {base_url} in OperationMode.COMPETITION...")

    client_arc = Arcade(
        arc_api_key=api_key,
        arc_base_url=base_url,
        operation_mode=OperationMode.COMPETITION,
        environments_dir="",
    )
    card_id = client_arc.open_scorecard(
        tags=["monad-1-v7-inos", "competition-mode"],
        opaque={"agent": "Monad(1) V7 INOS", "author": "Kyle W. Luecke (Drift Bound Labs)"},
    )
    print(f"[Monad(1) V7] Opened OperationMode.COMPETITION Scorecard: {card_id}")
    if not args.local_gateway:
        print(f"[Monad(1) V7] Official Scorecard URL: https://arcprize.org/scorecards/{card_id}")

    t0 = time.perf_counter()
    results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as pool:
        futs = {
            pool.submit(
                play_single_game,
                base_url,
                api_key,
                card_id,
                gid,
                i + 1,
                len(OFFICIAL_25_GAMES),
            ): gid
            for i, gid in enumerate(OFFICIAL_25_GAMES)
        }
        for fut in concurrent.futures.as_completed(futs):
            results.append(fut.result())

    scorecard = client_arc.close_scorecard(card_id)
    total_s = round(time.perf_counter() - t0, 2)
    sc_dict = scorecard.model_dump() if hasattr(scorecard, "model_dump") else dict(scorecard)

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "mode": "local_listen_and_serve_competition_mode" if args.local_gateway else "remote_competition_mode",
        "operation_mode": "COMPETITION",
        "card_id": card_id,
        "scorecard_url": f"https://arcprize.org/scorecards/{card_id}",
        "three_arcprize_url": f"https://three.arcprize.org/scorecards/{card_id}",
        "elapsed_s": total_s,
        "scorecard": sc_dict,
        "per_game_results": sorted(results, key=lambda x: OFFICIAL_25_GAMES.index(x["game_id"])),
    }
    out_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    print("=" * 80)
    print(f"[Monad(1) V7] Competition Mode Scorecard Closed: {card_id}")
    print(f"  Score:            {sc_dict.get('score')}")
    print(f"  Environments Won: {sc_dict.get('won')} / {sc_dict.get('played')}")
    print(f"  Levels Completed: {sc_dict.get('total_levels_completed')} / {sc_dict.get('total_levels')}")
    print(f"  Total Actions:    {sc_dict.get('total_actions')}")
    print(f"  Saved to:         {out_path}")
    print("=" * 80)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
