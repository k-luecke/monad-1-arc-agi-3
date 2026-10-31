"""Gap 1 test: next-frame object delta from the SCP projection vs an 8x8 raw grid.

Held-out games are evaluation-only (fold 0). A fixed majority model is trained
on the other games. The projection passes when its accuracy is at least the raw
grid's and it uses fewer tokens. Exit 0 on pass, 1 on fail, 2 if the env cannot run.
"""
from __future__ import annotations

import random
import sys
from collections import Counter, defaultdict
from pathlib import Path

from monad2.scp import delta_label, project, raw_tokens, validate_action

HOLDOUT = {"cd82", "ft09", "m0r0", "tn36", "tr87"}
STEPS = 20


def _fit_predict(train: list[tuple[tuple, str]], test: list[tuple[tuple, str]]) -> float:
    """Laplace naive Bayes over tokens. Exact keys do not have to repeat."""
    import math

    label_c: Counter = Counter()
    token_c: dict[str, Counter] = defaultdict(Counter)
    for key, label in train:
        label_c[label] += 1
        for tok in key:
            token_c[str(tok)][label] += 1
    labels = list(label_c)
    n = sum(label_c.values())
    if not test or not labels:
        return 0.0
    hit = 0
    k = len(labels)
    for key, truth in test:
        best = None
        best_s = -1e300
        for label in labels:
            score = math.log((label_c[label] + 1) / (n + k))
            denom = label_c[label] + 0.5 * k
            for tok in key:
                score += math.log((token_c[str(tok)][label] + 0.5) / denom)
            if score > best_s:
                best, best_s = label, score
        hit += int(best == truth)
    return hit / len(test)


def _self_check() -> None:
    legal = validate_action(1, [1, 2, 3, 4])
    assert legal.ok
    illegal = validate_action(6, [1, 2, 3, 4])
    assert not illegal.ok and illegal.rung == "D0"
    reset = validate_action(0, [0, 1])
    assert not reset.ok and reset.rung == "D4"
    noop = validate_action(1, [1], known_noop=True)
    assert noop.rung == "D1"
    grid = [[0] * 64 for _ in range(64)]
    for r in range(10, 14):
        for c in range(10, 14):
            grid[r][c] = 3
    for r in range(40, 48):
        for c in range(40, 48):
            grid[r][c] = 5
    proj = project(grid, legal=[1, 2, 3, 4])
    assert proj.n_objects == 2
    assert sum(1 for t in proj.tokens() if t.startswith("L")) == 16
    assert len(proj.tokens()) < len(raw_tokens(grid))
    assert any(t.startswith("dir:") for t in proj.tokens())
    shifted = [[0] * 64 for _ in range(64)]
    for r in range(12, 16):
        for c in range(12, 16):
            shifted[r][c] = 9
    for r in range(42, 50):
        for c in range(42, 50):
            shifted[r][c] = 8
    # Color permutation + translation keeps object-count and size buckets.
    a = project(grid).tokens()
    b = project(shifted).tokens()
    assert any(t.startswith("nobj:") for t in a)
    assert [t for t in a if t.startswith("nobj:")] == [t for t in b if t.startswith("nobj:")]


def _collect(env_dir: Path) -> tuple[list, list, dict]:
    from arc_agi import Arcade, OperationMode
    from arcengine import GameAction

    arc = Arcade(operation_mode=OperationMode.OFFLINE, environments_dir=str(env_dir))
    game_ids = sorted({e.game_id for e in arc.get_environments()})
    rng = random.Random(0)
    train_p: list[tuple[tuple, str]] = []
    test_p: list[tuple[tuple, str]] = []
    train_r: list[tuple[tuple, str]] = []
    test_r: list[tuple[tuple, str]] = []
    tok_p = 0
    tok_r = 0
    n = 0
    for gid in game_ids:
        prefix = gid.split("-")[0]
        env = arc.make(gid, scorecard_id="m2-scp", save_recording=False)
        frame = env.reset()
        if frame is None or not frame.frame:
            continue
        prev = frame.frame[-1]
        older = None
        held = prefix in HOLDOUT
        for _ in range(STEPS):
            legal = [int(a) for a in (frame.available_actions or []) if int(a) != 0]
            state_name = str(getattr(getattr(frame, "state", None), "name", frame.state))
            if not legal or state_name in ("WIN", "GAME_OVER"):
                break
            aid = rng.choice(legal)
            # Feedback is the transition that already happened. The label is
            # the next one. The first measured run omitted the prior frame, so
            # this token was stuck on "start".
            proj = project(prev, older, legal=legal)
            p_toks = tuple(proj.tokens() + [f"act:{aid}"])
            r_toks = tuple(raw_tokens(prev) + [f"act:{aid}"])
            tok_p += len(proj.tokens())
            tok_r += len(raw_tokens(prev))
            n += 1
            data = {"x": 32, "y": 32} if aid == 6 else None
            nxt = env.step(GameAction.from_id(aid), data=data)
            if nxt is None or not nxt.frame:
                break
            label = delta_label(prev, nxt.frame[-1])
            bucket_p = (train_p, test_p)[held]
            bucket_r = (train_r, test_r)[held]
            # Key is a short prefix so unseen layouts still share buckets.
            bucket_p.append((p_toks, label))
            bucket_r.append((r_toks, label))
            older = prev
            prev = nxt.frame[-1]
            frame = nxt
            if str(getattr(frame.state, "name", frame.state)) in ("WIN", "GAME_OVER"):
                break
    return (train_p, test_p), (train_r, test_r), {"n": n, "tok_p": tok_p, "tok_r": tok_r}


def main() -> int:
    _self_check()
    env_dir = Path(sys.argv[1] if len(sys.argv) > 1 else "environment_files")
    try:
        (train_p, test_p), (train_r, test_r), meta = _collect(env_dir)
    except Exception as exc:
        print(f"SCP collection failed: {exc}")
        return 2
    if meta["n"] == 0 or not test_p:
        print("SCP test had no held-out transitions")
        return 2
    acc_p = _fit_predict(train_p, test_p)
    acc_r = _fit_predict(train_r, test_r)
    mean_p = meta["tok_p"] / meta["n"]
    mean_r = meta["tok_r"] / meta["n"]
    # Majority baseline on the test labels.
    labels = Counter(label for _k, label in test_p)
    maj = labels.most_common(1)[0][1] / len(test_p)
    passed = acc_p + 1e-9 >= acc_r and mean_p < mean_r
    print(f"transitions={meta['n']} heldout={len(test_p)}")
    print(f"projection_acc={acc_p:.3f} raw_acc={acc_r:.3f} majority={maj:.3f}")
    print(f"projection_tokens={mean_p:.1f} raw_tokens={mean_r:.1f}")
    print("PASS" if passed else "FAIL")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
