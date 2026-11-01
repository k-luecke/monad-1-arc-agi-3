"""Select factorial combinations from discovery games only.

A candidate is a flag row that cleared a level the baseline did not clear
on the same game. Holdout prefixes are ignored here. Prints JSON.
"""
from __future__ import annotations

import json
import sys
from collections import defaultdict

from monad2.factorial import FACTORS, HOLDOUT_PREFIXES


def _prefix(game_id: str) -> str:
    return str(game_id).split("-")[0]


def _plays(fact: dict):
    for game in fact.get("per_game_results") or []:
        report = game.get("monad2") or {}
        for entry in report.get("level_log") or []:
            yield _prefix(game["game_id"]), entry


def main() -> int:
    if len(sys.argv) < 3:
        print(
            "usage: analyze_factorial.py <factorial.json> <baseline.json> [more factorial.json ...]",
            file=sys.stderr,
        )
        return 2
    fact_paths = [sys.argv[1], *sys.argv[3:]]
    facts = [json.loads(open(path, encoding="utf-8").read()) for path in fact_paths]
    base = json.loads(open(sys.argv[2], encoding="utf-8").read())
    fact = facts[0]
    base_levels = {_prefix(g["game_id"]): int(g["levels_completed"]) for g in base["per_game_results"]}
    # row -> games where this row cleared a level the baseline never reached.
    # A clear after the stall breaker handed the level back to baseline is not
    # credited to the row.
    extra = defaultdict(list)
    rows_seen = defaultdict(int)
    # Factor contrast on discovery levels the baseline already clears.
    on_hit = defaultdict(int)
    on_n = defaultdict(int)
    off_hit = defaultdict(int)
    off_n = defaultdict(int)
    solvable_plays = 0
    for one in facts:
        for game in one["per_game_results"]:
            prefix = _prefix(game["game_id"])
            if prefix in HOLDOUT_PREFIXES:
                continue
            report = game.get("monad2") or {}
            ceiling = base_levels.get(prefix, 0)
            for entry in report.get("level_log") or []:
                row = int(entry["row"])
                rows_seen[row] += 1
                level = int(entry["level"])
                cleared = bool(entry.get("cleared"))
                fallback = entry.get("stall_fallback") is not None
                if cleared and level >= ceiling and not fallback:
                    extra[row].append(
                        {
                            "game": prefix,
                            "level": level,
                            "flags": entry.get("flags") or {},
                            "seed": entry.get("seed"),
                        }
                    )
                if level < ceiling and not fallback:
                    solvable_plays += 1
                    flags = entry.get("flags") or {}
                    for name in FACTORS:
                        if int(flags.get(name, 0)):
                            on_n[name] += 1
                            on_hit[name] += int(cleared)
                        else:
                            off_n[name] += 1
                            off_hit[name] += int(cleared)
    contrast = {
        name: {
            "on": f"{on_hit[name]}/{on_n[name]}",
            "off": f"{off_hit[name]}/{off_n[name]}",
        }
        for name in FACTORS
    }
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
        "runs": len(facts),
        "discovery_rows_seen": len(rows_seen),
        "solvable_plays": solvable_plays,
        "factor_contrast": contrast,
        "candidates": candidates,
    }
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
