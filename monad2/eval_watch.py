"""Score watch-mode goal discovery and check action identity.

Usage:
  python -m monad2.eval_watch <watch.json> [more watch.json ...] [--baseline base.json]
"""
from __future__ import annotations

import json
import sys
from collections import Counter

from monad2.discovery import reset_store, recall
from monad2.factorial import HOLDOUT_PREFIXES
from monad2.memory import _features, _goal, corpus_path, load_records

GOAL_TYPES = ("REACH", "PLACE", "MATCH")
# Pre-registered bars from the corpus retrieval screen. They are not retuned here.
CHANCE_BAR = 0.217
CORPUS_MAJORITY = "MATCH"
CORPUS_MAJORITY_ACC = 0.240


def _prefix(game_id: str) -> str:
    return str(game_id).split("-")[0]


def _rows(paths: list[str]):
    for path in paths:
        doc = json.loads(open(path, encoding="utf-8").read())
        for game in doc.get("per_game_results") or []:
            report = game.get("monad2") or {}
            prefix = _prefix(game.get("game_id", ""))
            for row in report.get("watch_log") or []:
                yield prefix, row


def _cell(value: str | None) -> str:
    if value in GOAL_TYPES:
        return str(value)
    if value == "OTHER":
        return "OTHER"
    return "NONE"


def score(paths: list[str]) -> dict:
    episodes = 0
    labeled = 0
    scored = 0
    hits = 0
    outcomes: Counter[str] = Counter()
    hyps: Counter[str] = Counter()
    confusion: dict[str, Counter[str]] = {name: Counter() for name in (*GOAL_TYPES, "OTHER", "NONE")}
    reset_store()
    stored = 0
    for prefix, row in _rows(paths):
        episodes += 1
        hyp = _cell(row.get("hypothesis"))
        outcome = _cell(row.get("outcome"))
        hyps[hyp] += 1
        outcomes[outcome] += 1
        confusion[hyp][outcome] += 1
        if outcome in GOAL_TYPES:
            labeled += 1
        if hyp in GOAL_TYPES and outcome in GOAL_TYPES:
            scored += 1
            if hyp == outcome:
                hits += 1
        feats = tuple(row.get("features") or [])
        if outcome in GOAL_TYPES and feats and prefix not in HOLDOUT_PREFIXES and row.get("stored"):
            from monad2.discovery import remember

            before = stored
            remember(feats, outcome, holdout=prefix)
            stored = before + 1
    confirmed = [name for name, n in outcomes.items() if name in GOAL_TYPES for _ in range(n)]
    majority = None
    majority_acc = None
    if confirmed:
        majority = Counter(confirmed).most_common(1)[0][0]
        majority_acc = Counter(confirmed)[majority] / len(confirmed)
    records = load_records(corpus_path())
    unlabeled = [rec for rec in records if _goal(rec) is None]
    labelable = 0
    for rec in unlabeled:
        if recall(_features(rec), k=1):
            labelable += 1
    return {
        "episodes": episodes,
        "labeled": labeled,
        "coverage": (labeled / episodes) if episodes else None,
        "scored": scored,
        "hits": hits,
        "accuracy": (hits / scored) if scored else None,
        "outcomes": dict(outcomes),
        "hypotheses": dict(hyps),
        "confusion": {row: dict(cols) for row, cols in confusion.items()},
        "empirical_majority": majority,
        "empirical_majority_acc": majority_acc,
        "chance_bar": CHANCE_BAR,
        "corpus_majority": CORPUS_MAJORITY,
        "corpus_majority_acc": CORPUS_MAJORITY_ACC,
        "corpus_unlabeled": len(unlabeled),
        "corpus_labelable": labelable,
        "stored_episodes": stored,
    }


def _action_logs(path: str) -> dict[str, list[str]]:
    doc = json.loads(open(path, encoding="utf-8").read())
    out = {}
    for game in doc.get("per_game_results") or []:
        report = game.get("monad2") or {}
        log = report.get("action_log")
        if isinstance(log, list):
            out[_prefix(game.get("game_id", ""))] = [str(x) for x in log]
    return out


def identity(watch_paths: list[str], baseline_path: str) -> dict:
    base_doc = json.loads(open(baseline_path, encoding="utf-8").read())
    base_levels = {_prefix(g["game_id"]): int(g["levels_completed"]) for g in base_doc["per_game_results"]}
    base_actions = {_prefix(g["game_id"]): int(g["actions"]) for g in base_doc["per_game_results"]}
    base_logs = _action_logs(baseline_path)
    runs = []
    for path in watch_paths:
        doc = json.loads(open(path, encoding="utf-8").read())
        logs = _action_logs(path)
        mismatches = []
        for game in doc["per_game_results"]:
            prefix = _prefix(game["game_id"])
            same_counts = (
                int(game["levels_completed"]) == base_levels.get(prefix, -1)
                and int(game["actions"]) == base_actions.get(prefix, -1)
            )
            same_seq = None
            if prefix in base_logs and prefix in logs:
                same_seq = base_logs[prefix] == logs[prefix]
            if not same_counts or same_seq is False:
                mismatches.append(
                    {
                        "game": prefix,
                        "levels": int(game["levels_completed"]),
                        "base_levels": base_levels.get(prefix),
                        "actions": int(game["actions"]),
                        "base_actions": base_actions.get(prefix),
                        "sequence": same_seq,
                    }
                )
        runs.append(
            {
                "path": path,
                "levels": doc.get("levels_completed"),
                "actions": doc.get("actions"),
                "wins": doc.get("wins"),
                "mismatches": mismatches,
                "sequences_compared": sum(1 for p in logs if p in base_logs),
            }
        )
    return {
        "baseline_levels": base_doc.get("levels_completed"),
        "baseline_actions": base_doc.get("actions"),
        "runs": runs,
    }


def main() -> int:
    args = [arg for arg in sys.argv[1:] if arg]
    baseline = None
    if "--baseline" in args:
        idx = args.index("--baseline")
        baseline = args[idx + 1]
        paths = args[:idx]
    else:
        paths = args
    if not paths:
        print("usage: python -m monad2.eval_watch <watch.json> [...] [--baseline base.json]", file=sys.stderr)
        return 2
    summary = score(paths)
    if baseline:
        summary["identity"] = identity(paths, baseline)
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
