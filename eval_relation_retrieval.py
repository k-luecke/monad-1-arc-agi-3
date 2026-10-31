#!/usr/bin/env python3
"""Retrieval quality for the 64-bit minutiae LSH.

Evaluation-only. Ground-truth goal types and fold 0 are never read by the agent.
The memory file the agent loads has no game ids; this script joins the harness
game id back on so it can ask whether a held-out game retrieves training
memories of the same goal type more often than chance.

  python eval_relation_retrieval.py --self-check
  python eval_relation_retrieval.py --scorecard solvers_on_wins.json
"""
from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

import numpy as np

from aggregate_generalization_results import GT_GOAL_TYPE, HELD_OUT_FOLD0


def _blank_agent():
    from my_agent_v7_inos import MyAgent

    agent = MyAgent.__new__(MyAgent)
    agent.hud_rows = set()
    agent.hud_cols = set()
    agent.hud_coords = set()
    agent.fx_color_shift = {}
    agent.fx_push = {}
    agent.fx_click = {}
    agent.fx_appear = Counter()
    agent.fx_vanish = Counter()
    agent.fx_toggle_pairs = {}
    return agent


def _paint(grid: np.ndarray, color: int, x: int, y: int, w: int, h: int) -> None:
    grid[y : y + h, x : x + w] = color


def _pair_grids() -> dict[str, np.ndarray]:
    """Three structures, each with a translated and a recolored twin."""
    def base(kind: str, dx: int = 0, dy: int = 0, perm: dict[int, int] | None = None) -> np.ndarray:
        g = np.zeros((64, 64), dtype=np.int16)
        perm = perm or {}

        def c(v: int) -> int:
            return int(perm.get(v, v))

        if kind == "REACH":
            _paint(g, c(3), 8 + dx, 10 + dy, 3, 3)
            _paint(g, c(4), 40 + dx, 36 + dy, 4, 4)
        elif kind == "PLACE":
            _paint(g, c(3), 8 + dx, 28 + dy, 3, 3)
            _paint(g, c(5), 30 + dx, 24 + dy, 10, 10)
            _paint(g, c(1), 32 + dx, 26 + dy, 6, 6)  # hole punched below
            g[26 + dy : 32 + dy, 32 + dx : 38 + dx] = 0
        elif kind == "MATCH":
            _paint(g, c(2), 8 + dx, 12 + dy, 8, 8)
            _paint(g, c(2), 40 + dx, 12 + dy, 8, 8)
            g[14 + dy, 10 + dx] = c(6)
            g[14 + dy, 42 + dx] = c(7)
        return g

    out = {}
    for kind in ("REACH", "PLACE", "MATCH"):
        out[kind] = base(kind)
        out[kind + ":shift"] = base(kind, dx=7, dy=5)
        out[kind + ":recolor"] = base(kind, perm={3: 9, 4: 8, 5: 11, 2: 12, 6: 13, 7: 14, 1: 10})
    return out


def _hamming(a: int, b: int, bits: int = 64) -> int:
    return ((int(a) ^ int(b)) & ((1 << bits) - 1)).bit_count()


def self_check() -> int:
    agent = _blank_agent()
    grids = _pair_grids()
    hashes = {}
    for name, grid in grids.items():
        sig, bands = agent._lsh_situation(grid, [1, 2, 3, 4])
        hashes[name] = (sig, bands)
        print(f"{name:16s} sig={sig:016x} bands={[f'{b:04x}' for b in bands]}")

    failures = []

    def expect_close(a: str, b: str, limit: int) -> None:
        dist = _hamming(hashes[a][0], hashes[b][0])
        print(f"  dist {a} vs {b}: {dist}")
        if dist > limit:
            failures.append(f"{a} vs {b} hamming {dist} > {limit}")

    def expect_far(a: str, b: str, limit: int) -> None:
        dist = _hamming(hashes[a][0], hashes[b][0])
        print(f"  dist {a} vs {b}: {dist}")
        if dist < limit:
            failures.append(f"{a} vs {b} hamming {dist} < {limit}")

    for kind in ("REACH", "PLACE", "MATCH"):
        expect_close(kind, kind + ":shift", 0)
        expect_close(kind, kind + ":recolor", 0)
    expect_far("REACH", "MATCH", 1)
    expect_far("REACH", "PLACE", 1)
    expect_far("PLACE", "MATCH", 1)

    # Rotation: a quarter-turn of a symmetric-enough board should stay close.
    rot = np.rot90(grids["MATCH"], 1)
    sig_r, _ = agent._lsh_situation(rot, [1, 2, 3, 4])
    dist_rot = _hamming(hashes["MATCH"][0], sig_r)
    print(f"  dist MATCH vs rot90: {dist_rot}")
    if dist_rot > 6:
        failures.append(f"MATCH vs rot90 hamming {dist_rot} > 6")

    # Banded retrieval: memories are the three originals; a shifted MATCH must vote MATCH.
    agent.wt_memory = []
    agent.wt_band_index = [dict() for _ in range(8)]
    agent.wt_retrievals = 0
    agent.wt_agree_sum = 0
    agent.wt_dist_sum = 0
    agent.GGL_GOAL_TYPES = ("REACH", "PLACE", "MATCH")
    for kind in ("REACH", "PLACE", "MATCH"):
        sig, bands = hashes[kind]
        idx = len(agent.wt_memory)
        agent.wt_memory.append(
            {"sig64": sig, "bands": bands, "sig16": bands[0] or 1, "goal_type": kind, "abstract": ""}
        )
        for s in range(8):
            piece = (sig >> (8 * s)) & 0xFF
            agent.wt_band_index[s].setdefault(piece, []).append(idx)
    qsig, qbands = hashes["MATCH:shift"]
    bonus = agent._wt_memory_bonus(qsig, qbands)
    print(f"  shifted MATCH retrieval bonus: {bonus} retrievals={agent.wt_retrievals}")
    if bonus.get("MATCH", 0) <= 0:
        failures.append(f"shifted MATCH did not retrieve MATCH, bonus={bonus}")
    if bonus.get("REACH", 0) > 0 or bonus.get("PLACE", 0) > 0:
        failures.append(f"shifted MATCH also retrieved another type, bonus={bonus}")

    if failures:
        print("SELF-CHECK FAILED")
        for line in failures:
            print(" -", line)
        return 1
    print("SELF-CHECK PASSED")
    return 0


def _sig_of(rec: dict) -> int:
    try:
        sig = int(rec.get("sig64") or 0)
    except (TypeError, ValueError):
        sig = 0
    if sig == 0 and rec.get("sig64_hex"):
        try:
            sig = int(str(rec["sig64_hex"]), 16)
        except (TypeError, ValueError):
            sig = 0
    return sig & 0xFFFFFFFFFFFFFFFF


def _bands_of(rec: dict, sig: int) -> list[int]:
    bands = rec.get("bands")
    if isinstance(bands, list) and len(bands) == 4:
        return [int(b) & 0xFFFF for b in bands]
    return [(sig >> (16 * i)) & 0xFFFF for i in range(4)]


def _index(records: list[dict]) -> list[dict[int, list[int]]]:
    index: list[dict[int, list[int]]] = [dict() for _ in range(8)]
    for i, rec in enumerate(records):
        sig = int(rec["sig64"])
        for s in range(8):
            piece = (sig >> (8 * s)) & 0xFF
            index[s].setdefault(piece, []).append(i)
    return index


def _retrieve(query: dict, records: list[dict], index: list[dict[int, list[int]]]) -> list[int]:
    """Same accept rule as MyAgent._wt_memory_bonus, returning memory indices."""
    sig = int(query["sig64"])
    bands = query["bands"]
    effect_unknown = int(bands[3]) == 0
    cand: Counter = Counter()
    n_bands = 6 if effect_unknown else 8
    for s in range(n_bands):
        piece = (sig >> (8 * s)) & 0xFF
        probes = [piece] + [piece ^ (1 << bit) for bit in range(8)]
        seen: set[int] = set()
        for probe in probes:
            for idx in index[s].get(probe, ()):
                if idx in seen:
                    continue
                seen.add(idx)
                cand[idx] += 1
    kept = []
    mask = (1 << 48) - 1 if effect_unknown else (1 << 64) - 1
    limit = 16 if effect_unknown else 22
    for idx, hits in cand.items():
        if hits < 2:
            continue
        rec = records[idx]
        fam_dist = [
            (int(bands[fam]) ^ int(rec["bands"][fam])).bit_count() for fam in range(4)
        ]
        struct_agree = int(fam_dist[0] <= 4) + int(fam_dist[1] <= 4)
        ctrl_ok = fam_dist[2] <= 4
        fx_ok = True if effect_unknown else fam_dist[3] <= 4
        dist = ((sig ^ int(rec["sig64"])) & mask).bit_count()
        if struct_agree >= 1 and ctrl_ok and fx_ok and dist <= limit:
            kept.append(idx)
    return kept


def scorecard_report(path: str) -> int:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    train: list[dict] = []
    queries: list[dict] = []
    for game in data.get("per_game_results", []):
        gid = str(game.get("game_id", "")).split("-")[0]
        gt = GT_GOAL_TYPE.get(gid)
        if gt is None:
            continue
        for rec in game.get("win_records") or []:
            sig = _sig_of(rec)
            if sig == 0:
                continue
            item = {
                "sig64": sig,
                "bands": _bands_of(rec, sig),
                "goal_type": str(rec.get("goal_type", "")),
                "game": gid,
                "gt": gt,
            }
            if gid in HELD_OUT_FOLD0:
                queries.append(item)
            else:
                train.append(item)
    print(f"training records: {len(train)} from {len({r['game'] for r in train})} games")
    print(f"held-out queries: {len(queries)} from {len({r['game'] for r in queries})} games")
    if not train or not queries:
        print("not enough labelled records to score retrieval")
        return 1
    index = _index(train)
    train_gt_counts = Counter(r["gt"] for r in train)
    n_train = len(train)
    majority_gt, majority_n = train_gt_counts.most_common(1)[0]
    majority_acc = majority_n / n_train

    top1_correct = 0
    covered = 0
    same_type_hits = 0
    retrieved_n = 0
    chance_mass = 0.0
    by_game: dict[str, list[str | None]] = {}
    for q in queries:
        hits = _retrieve(q, train, index)
        by_game.setdefault(q["game"], [])
        chance_mass += train_gt_counts[q["gt"]] / n_train
        if not hits:
            by_game[q["game"]].append(None)
            continue
        covered += 1
        retrieved_n += len(hits)
        votes = Counter(train[i]["gt"] for i in hits)
        pred, _n = votes.most_common(1)[0]
        by_game[q["game"]].append(pred)
        if pred == q["gt"]:
            top1_correct += 1
        same_type_hits += sum(1 for i in hits if train[i]["gt"] == q["gt"])

    n_q = len(queries)
    chance = chance_mass / n_q
    print()
    print(f"queries with at least one neighbor: {covered}/{n_q}")
    if covered:
        print(
            f"majority-neighbor goal type correct: {top1_correct}/{covered} "
            f"= {top1_correct / covered:.3f} among retrieved, "
            f"{top1_correct}/{n_q} = {top1_correct / n_q:.3f} counting misses as wrong"
        )
        print(
            f"neighbor records of the same goal type: {same_type_hits}/{retrieved_n} "
            f"= {same_type_hits / retrieved_n:.3f}"
        )
    print(f"chance (mean fraction of training records with the query's goal type): {chance:.3f}")
    print(f"majority-class baseline (always {majority_gt}): {majority_acc:.3f}")
    print()
    print("| held-out game | GT | queries | retrieved | predicted types |")
    print("|---|---|---|---|---|")
    for gid in sorted(HELD_OUT_FOLD0):
        preds = by_game.get(gid, [])
        got = [p for p in preds if p is not None]
        print(
            f"| {gid} | {GT_GOAL_TYPE[gid]} | {len(preds)} | {len(got)} | "
            f"{dict(Counter(got)) if got else '-'} |"
        )
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--self-check", action="store_true")
    ap.add_argument("--scorecard", default="")
    args = ap.parse_args()
    rc = 0
    if args.self_check or not args.scorecard:
        rc = self_check()
    if args.scorecard:
        rc = scorecard_report(args.scorecard) or rc
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
