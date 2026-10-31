"""Select factorial combinations from discovery games only.

A candidate is a flag row that cleared a level the baseline did not clear
on the same game. Holdout prefixes are ignored here. Prints JSON.
"""
from __future__ import annotations

import json
import sys
from collections import defaultdict

from monad2.factorial import HOLDOUT_PREFIXES


def _prefix(game_id: str) -> str:
    return str(game_id).split("-")[0]


def main() -> int:
    if len(sys.argv) < 3:
        print("usage: analyze_factorial.py <factorial.json> <baseline.json>", file=sys.stderr)
        return 2
    fact = json.loads(open(sys.argv[1], encoding="utf-8").read())
    base = json.loads(open(sys.argv[2], encoding="utf-8").read())
    base_levels = {_prefix(g["game_id"]): int(g["levels_completed"]) for g in base["per_game_results"]}
    # row -> games where this row cleared a level the baseline never reached
    extra = defaultdict(list)
    rows_seen = defaultdict(int)
    for game in fact["per_game_results"]:
        prefix = _prefix(game["game_id"])
        if prefix in HOLDOUT_PREFIXES:
            continue
        report = game.get("monad2") or {}
        ceiling = base_levels.get(prefix, 0)
        for entry in report.get("level_log") or []:
            row = int(entry["row"])
            rows_seen[row] += 1
            if entry.get("cleared") and int(entry["level"]) >= ceiling:
                extra[row].append(
                    {
                        "game": prefix,
                        "level": int(entry["level"]),
                        "flags": entry.get("flags") or {},
                    }
                )
    candidates = []
    for row, hits in sorted(extra.items(), key=lambda kv: -len(kv[1])):
        flags = hits[0]["flags"]
        candidates.append(
            {
                "row": row,
                "extra_clears": len(hits),
                "games": sorted({h["game"] for h in hits}),
                "hits": hits,
                "flags": flags,
            }
        )
    summary = {
        "factorial_levels": fact.get("levels_completed"),
        "factorial_actions": fact.get("actions"),
        "factorial_wins": fact.get("wins"),
        "baseline_levels": base.get("levels_completed"),
        "baseline_actions": base.get("actions"),
        "discovery_rows_seen": len(rows_seen),
        "candidates": candidates,
    }
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
