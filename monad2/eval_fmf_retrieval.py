"""Gap 2: held-out goal-type top-1 from the FMF corpus.

Ground-truth types are imported only here, for scoring. The retriever never
sees them. A game's own records are excluded by id and by text. Exit 0 when
top-1 beats 0.217 and UNKNOWN levels are below 102/183.
"""
from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

from aggregate_generalization_results import GT_GOAL_TYPE
from monad2.memory import _goal, corpus_path, eligible, grid_features, load_records, retrieve
from monad2.scp import project

CHANCE_BAR = 0.217
UNKNOWN_BAR = 102


def _win_levels(frame) -> int:
    for name in ("win_levels", "levels"):
        val = getattr(frame, name, None)
        if isinstance(val, int) and val > 0:
            return val
    return 0


def main() -> int:
    env_dir = Path(sys.argv[1] if len(sys.argv) > 1 else "environment_files")
    path = corpus_path()
    records = load_records(path)
    from arc_agi import Arcade, OperationMode

    arc = Arcade(operation_mode=OperationMode.OFFLINE, environments_dir=str(env_dir))
    game_ids = sorted({e.game_id for e in arc.get_environments()})
    rows = []
    unknown_levels = 0
    level_sum = 0
    chance_mass = 0.0
    for gid in game_ids:
        prefix = gid.split("-")[0]
        if prefix not in GT_GOAL_TYPE:
            continue
        env = arc.make(gid, scorecard_id="m2-fmf", save_recording=False)
        frame = env.reset()
        grid = frame.frame[-1] if frame is not None and frame.frame else None
        legal = [int(a) for a in (getattr(frame, "available_actions", None) or [])]
        levels = _win_levels(frame) if frame is not None else 0
        level_sum += levels
        proj = project(grid, legal=legal) if grid is not None else None
        feats = grid_features(proj, legal) if proj is not None else ()
        train = eligible(records, prefix)
        n_train = 0
        n_match_gt = 0
        gt = GT_GOAL_TYPE[prefix]
        for rec in train:
            g = _goal(rec)
            if g is None:
                continue
            n_train += 1
            if g == gt:
                n_match_gt += 1
        hyp = retrieve(feats, train, k=1)
        pred = hyp[0] if hyp else None
        if pred is None:
            unknown_levels += levels
        chance_mass += (n_match_gt / n_train) if n_train else 0.0
        rows.append(
            {
                "game": prefix,
                "gt": gt,
                "pred": pred,
                "features": list(feats),
                "n_train": n_train,
                "win_levels": levels,
                "hit": pred == gt,
            }
        )
    n = len(rows)
    hits = sum(1 for r in rows if r["hit"])
    top1 = hits / n if n else 0.0
    chance = chance_mass / n if n else 0.0
    # Majority among mapped corpus goals, scored against these games' labels.
    corpus_goals = [_goal(r) for r in records]
    corpus_goals = [g for g in corpus_goals if g]
    majority = Counter(corpus_goals).most_common(1)[0][0] if corpus_goals else None
    maj_hits = sum(1 for r in rows if r["gt"] == majority)
    maj_acc = maj_hits / n if n else 0.0
    passed = top1 > CHANCE_BAR and unknown_levels < UNKNOWN_BAR
    print(f"games={n} records={len(records)} corpus={path.name}")
    print(f"top1={top1:.3f} hits={hits}/{n} chance_bar={CHANCE_BAR:.3f} corpus_chance={chance:.3f}")
    print(f"majority={majority} majority_acc={maj_acc:.3f} ({maj_hits}/{n})")
    print(f"unknown_levels={unknown_levels} level_sum={level_sum} unknown_bar={UNKNOWN_BAR}/183")
    for r in rows:
        mark = "hit" if r["hit"] else ("unk" if r["pred"] is None else "miss")
        print(f"  {r['game']} gt={r['gt']} pred={r['pred'] or '-'} {mark} feats={','.join(r['features']) or '-'} train={r['n_train']} lvls={r['win_levels']}")
    print("PASS" if passed else "FAIL")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
