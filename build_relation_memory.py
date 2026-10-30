#!/usr/bin/env python3
"""Build relation-keyed memory from a solvers-on wins-teach scorecard.

The harness JSON carries the real game id. Fold-0 games are dropped here, and
the written records contain only a relational signature, goal type, abstract
plan, and object relations. The agent never sees a game id in this file.

Held-out fold 0 is evaluation-only metadata from the trainer study. It is not
read by the agent.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

HELD_OUT_FOLD0 = {"cd82", "ft09", "m0r0", "tn36", "tr87"}
GOAL_TYPES = {"REACH", "PLACE", "MATCH"}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--scorecard", required=True, help="Eval JSON with per_game_results")
    ap.add_argument("--output", required=True, help="Memory JSON consumed by MONAD1_RELATION_MEMORY")
    args = ap.parse_args()
    data = json.loads(Path(args.scorecard).read_text(encoding="utf-8"))
    seen: set[tuple[int, str]] = set()
    records: list[dict] = []
    kept_games = 0
    dropped_games = 0
    for game in data.get("per_game_results", []):
        gid = str(game.get("game_id", "")).split("-")[0]
        if gid in HELD_OUT_FOLD0:
            dropped_games += 1
            continue
        raw = game.get("win_records") or []
        if not raw:
            continue
        kept_games += 1
        for rec in raw:
            gtype = str(rec.get("goal_type", ""))
            if gtype not in GOAL_TYPES:
                continue
            sig16 = int(rec.get("sig16", 0)) & 0xFFFF
            if sig16 == 0:
                continue
            key = (sig16, gtype)
            if key in seen:
                continue
            seen.add(key)
            relations = rec.get("relations") or {}
            records.append(
                {
                    "sig16": sig16,
                    "goal_type": gtype,
                    "abstract": str(rec.get("abstract", ""))[:80],
                    "relations": {
                        "n_colors": relations.get("n_colors"),
                        "has_panel": relations.get("has_panel"),
                        "n_actions": relations.get("n_actions"),
                    },
                }
            )
    Path(args.output).write_text(
        json.dumps({"records": records}, indent=2),
        encoding="utf-8",
    )
    print(
        f"wrote {len(records)} records from {kept_games} games "
        f"(dropped {dropped_games} fold-0 games) -> {args.output}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
