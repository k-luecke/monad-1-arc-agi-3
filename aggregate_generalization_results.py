#!/usr/bin/env python3
"""
Aggregate blind-generalization evaluation results (game-specific solvers disabled).

Usage:
  python aggregate_generalization_results.py \
      --engine-runs runA.json runB.json \
      --baseline-runs baseA.json baseB.json

Each input JSON is the --output file of:
  python run_competition_eval.py --offline --blind-id --no-game-solvers [--output f.json]
(baseline runs additionally set MONAD1_DISABLE_GOAL_ENGINE=1).

Produces a per-game markdown table (levels per run, goal type identified) plus
totals and the "goal type correctly identified on an unseen game" metric.

NOTE: The ground-truth goal types and the 5-fold split below are EVALUATION-ONLY
metadata (from the external trainer study). They are never read by the agent and
exist solely to score goal-type identification and held-out generalization.
"""
from __future__ import annotations

import argparse
import json
import statistics
from pathlib import Path

# Ground-truth goal type per game (study judgment from solver docstrings).
GT_GOAL_TYPE = {
    "ar25": "PLACE", "bp35": "REACH", "cd82": "MATCH", "cn04": "PLACE",
    "dc22": "REACH", "ft09": "MATCH", "g50t": "REACH", "ka59": "PLACE",
    "lf52": "PLACE", "lp85": "PLACE", "ls20": "REACH", "m0r0": "REACH",
    "r11l": "PLACE", "re86": "PLACE", "s5i5": "PLACE", "sb26": "MATCH",
    "sc25": "REACH", "sk48": "MATCH", "sp80": "PLACE", "su15": "MATCH",
    "tn36": "REACH", "tr87": "MATCH", "tu93": "REACH", "vc33": "PLACE",
    "wa30": "PLACE",
}

# Study fold 0 test games: held out during goal-engine development/tuning.
HELD_OUT_FOLD0 = {"cd82", "ft09", "m0r0", "tn36", "tr87"}


def load_runs(paths: list[str]) -> list[dict[str, dict]]:
    runs = []
    for p in paths:
        data = json.loads(Path(p).read_text(encoding="utf-8"))
        per_game = {}
        for r in data.get("per_game_results", []):
            per_game[r["game_id"].split("-")[0]] = r
        runs.append(per_game)
    return runs


def fmt_levels(vals: list[int]) -> str:
    if not vals:
        return "-"
    if len(set(vals)) == 1:
        return str(vals[0])
    return "/".join(str(v) for v in vals) + f" (mean {statistics.mean(vals):.1f})"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--engine-runs", nargs="+", required=True)
    ap.add_argument("--baseline-runs", nargs="+", default=[])
    args = ap.parse_args()

    eng = load_runs(args.engine_runs)
    base = load_runs(args.baseline_runs)
    games = sorted(GT_GOAL_TYPE)

    print("| game | held-out | GT type | baseline levels | engine levels | engine actions | identified type | correct |")
    print("|---|---|---|---|---|---|---|---|")
    id_correct_all, id_made_all = [], []
    id_correct_held, id_made_held = [], []
    for g in games:
        b_lv = [run[g]["levels_completed"] for run in base if g in run]
        e_lv = [run[g]["levels_completed"] for run in eng if g in run]
        e_ac = [run[g]["actions"] for run in eng if g in run]
        conf_types = [
            (run[g].get("goal_report") or {}).get("confirmed_type")
            for run in eng
            if g in run
        ]
        conf = next((c for c in conf_types if c), None)
        correct = "" if conf is None else ("yes" if conf == GT_GOAL_TYPE[g] else "no")
        held = "yes" if g in HELD_OUT_FOLD0 else ""
        if conf is not None:
            id_made_all.append(g)
            if conf == GT_GOAL_TYPE[g]:
                id_correct_all.append(g)
            if g in HELD_OUT_FOLD0:
                id_made_held.append(g)
                if conf == GT_GOAL_TYPE[g]:
                    id_correct_held.append(g)
        print(
            f"| {g} | {held} | {GT_GOAL_TYPE[g]} | {fmt_levels(b_lv)} | {fmt_levels(e_lv)} | "
            f"{'/'.join(str(a) for a in e_ac) or '-'} | {conf or '-'} | {correct} |"
        )

    def tot(runs: list[dict]) -> list[tuple[int, int, int]]:
        out = []
        for run in runs:
            out.append(
                (
                    sum(1 for r in run.values() if r["state"] == "WIN"),
                    sum(r["levels_completed"] for r in run.values()),
                    sum(r["actions"] for r in run.values()),
                )
            )
        return out

    print()
    for name, runs in (("baseline (goal engine off)", base), ("goal engine on", eng)):
        for i, (w, l, a) in enumerate(tot(runs)):
            print(f"{name} run {i}: wins={w}/25 levels={l} actions={a}")
    print()
    print(
        f"goal type identified (evidence-based, all games): {len(id_made_all)}/25 made, "
        f"{len(id_correct_all)} correct ({sorted(id_made_all)})"
    )
    print(
        f"goal type identified on held-out fold-0 games: {len(id_made_held)}/5 made, "
        f"{len(id_correct_held)} correct ({sorted(id_made_held)})"
    )
    held_gain = []
    train_gain = []
    if base and eng:
        for g in games:
            b = statistics.mean([run[g]["levels_completed"] for run in base if g in run] or [0])
            e = statistics.mean([run[g]["levels_completed"] for run in eng if g in run] or [0])
            (held_gain if g in HELD_OUT_FOLD0 else train_gain).append(e - b)
        print(f"mean level delta, tuning games (n={len(train_gain)}): {sum(train_gain):+.1f} total")
        print(f"mean level delta, held-out fold-0 games (n={len(held_gain)}): {sum(held_gain):+.1f} total")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
