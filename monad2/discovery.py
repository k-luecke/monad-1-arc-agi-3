"""Outcome-grounded goal discovery.

A short probe budget watches what a move actually changes: object shift,
panel agreement, contact, and containment. Those changes vote for REACH,
PLACE, or MATCH. The goal-type words themselves are not features. Labels are
stored by affordance features, never by game id. Holdout games do not write
the cross-game store.
"""
from __future__ import annotations

import os
from collections import Counter

from monad2.factorial import HOLDOUT_PREFIXES
from monad2.memory import GOAL_TYPES, grid_features
from monad2.scp import project

# Confirmed outcome labels from this process. Features only.
EPISODE_FMF: list[tuple[tuple[str, ...], str]] = []


def reset_store() -> None:
    EPISODE_FMF.clear()


def _copy(grid) -> list[list[int]] | None:
    if grid is None:
        return None
    if hasattr(grid, "tolist"):
        grid = grid.tolist()
    if not grid or not isinstance(grid, list):
        return None
    return [[int(v) for v in row] for row in grid]


def _changed_cells(before: list[list[int]], after: list[list[int]]) -> int:
    if len(before) != len(after):
        return 10**6
    n = 0
    for a, b in zip(before, after):
        if len(a) != len(b):
            return 10**6
        n += sum(x != y for x, y in zip(a, b))
        if n > 400:
            return n
    return n


def _center(obj) -> tuple[float, float]:
    return obj.r0 + obj.h / 2.0, obj.c0 + obj.w / 2.0


def _shift_of(before_objs, after_objs) -> tuple[int, int, bool]:
    """How many objects moved, the controllable shift in cells, and whether two shared a shift."""
    def index(objs):
        out = {}
        for obj in objs:
            out.setdefault(obj.role, obj)
        return out

    a = index(before_objs)
    b = index(after_objs)
    movers = 0
    shifts: list[tuple[int, int]] = []
    ctrl = 0
    for role, obj in a.items():
        other = b.get(role)
        if other is None:
            continue
        dr = int(round(_center(other)[0] - _center(obj)[0]))
        dc = int(round(_center(other)[1] - _center(obj)[1]))
        if dr or dc:
            movers += 1
            shifts.append((dr, dc))
            if obj.size <= 36:
                ctrl = max(ctrl, abs(dr) + abs(dc))
    same = len(shifts) >= 2 and len(set(shifts)) == 1
    return movers, ctrl, same


def _contain_gain(before_objs, after_objs) -> bool:
    def inside(objs) -> int:
        n = 0
        for i, small in enumerate(objs):
            if small.size > 36:
                continue
            sr, sc = _center(small)
            for big in objs:
                if big is small or big.size <= small.size:
                    continue
                if big.r0 <= sr <= big.r0 + big.h and big.c0 <= sc <= big.c0 + big.w:
                    n += 1
                    break
        return n

    return inside(after_objs) > inside(before_objs)


def _contact_gain(before_objs, after_objs) -> bool:
    def pairs(objs) -> int:
        n = 0
        for i, a in enumerate(objs):
            for b in objs[i + 1 :]:
                if a.r0 <= b.r0 + b.h and b.r0 <= a.r0 + a.h and a.c0 <= b.c0 + b.w and b.c0 <= a.c0 + a.w:
                    n += 1
        return n

    return pairs(after_objs) > pairs(before_objs)


def score_change(before, after) -> Counter[str]:
    """Votes from one observed transition. A no-op or a jump votes for nothing."""
    scores: Counter[str] = Counter()
    b = _copy(before)
    a = _copy(after)
    if b is None or a is None:
        return scores
    changed = _changed_cells(b, a)
    if changed <= 0 or changed > 400:
        return scores
    pb = project(b)
    pa = project(a)
    movers, ctrl, same = _shift_of(pb.objects, pa.objects)
    mismatch_drop = int(pb.panel_mismatch) - int(pa.panel_mismatch)
    if mismatch_drop >= 2:
        scores["MATCH"] += 2
    if _contain_gain(pb.objects, pa.objects) or same or (_contact_gain(pb.objects, pa.objects) and movers >= 2):
        scores["PLACE"] += 2
    if pa.n_objects < pb.n_objects and movers >= 1:
        scores["PLACE"] += 1
    if ctrl >= 1 and movers <= 1 and mismatch_drop <= 0:
        scores["REACH"] += 2
    return scores


def leader(scores: Counter[str]) -> tuple[str | None, int]:
    if not scores:
        return None, 0
    ranked = scores.most_common()
    best, n = ranked[0]
    if best not in GOAL_TYPES or n < 2:
        return None, 0
    second = ranked[1][1] if len(ranked) > 1 else 0
    return best, n - second


def outcome_label(rec: dict) -> str | None:
    """Label a corpus record from a described change, not from a goal-type word.

    Only records that already carry an outcome, or a dream schema, qualify.
    """
    outcome = str(rec.get("outcome") or "")
    kind = str(rec.get("record_kind") or rec.get("kind") or "")
    if outcome not in ("solved_counterfactual", "positive_mention") and kind.lower() != "dream_schema":
        return None
    parts = []
    for key in ("hypothesis", "observation", "outcome"):
        val = rec.get(key)
        if isinstance(val, str):
            parts.append(val.lower())
    text = "\n".join(parts)
    scores: Counter[str] = Counter()
    if "annihil" in text or "into floor" in text or "chasm" in text:
        scores["PLACE"] += 2
    if "portal" in text or "coordinate transport" in text:
        scores["REACH"] += 2
    if "panel" in text and any(word in text for word in ("align", "mismatch", "same shape", "twin")):
        scores["MATCH"] += 2
    if "push" in text and "block" in text:
        scores["PLACE"] += 2
    if "switch" in text and any(word in text for word in ("barrier", "dissolve")):
        scores["REACH"] += 2
    best, _margin = leader(scores)
    return best


def remember(features: tuple[str, ...], goal: str, *, holdout: str = "") -> None:
    if goal not in GOAL_TYPES or not features:
        return
    if holdout in HOLDOUT_PREFIXES:
        return
    EPISODE_FMF.append((features, goal))
    if len(EPISODE_FMF) > 64:
        del EPISODE_FMF[0]


def recall(features: tuple[str, ...], k: int = 3) -> list[str]:
    scores: Counter[str] = Counter()
    query = set(features)
    if not query:
        return []
    for feats, goal in EPISODE_FMF:
        overlap = len(query & set(feats))
        if overlap:
            scores[goal] += overlap * 2
    return [g for g, _n in scores.most_common(k)]


def probe_budget() -> int:
    raw = os.getenv("MONAD2_PROBE_BUDGET", "").strip()
    if not raw:
        return 6
    try:
        return max(0, min(12, int(raw)))
    except ValueError:
        return 6


class LevelDiscovery:
    """Probe votes versus later outcome votes, for one level."""

    def __init__(self, level: int) -> None:
        self.level = int(level)
        self.probe_scores: Counter[str] = Counter()
        self.later_scores: Counter[str] = Counter()
        self.used = 0
        self.tried: set[int] = set()
        self.pending: tuple | None = None
        self.start = None
        self.last = None
        self.closed = False
        self.frozen: str | None = None

    def hypothesis(self) -> str | None:
        if self.frozen is not None:
            return self.frozen
        best, margin = leader(self.probe_scores)
        if best is not None and margin >= 1:
            return best
        return None

    def outcome(self) -> str | None:
        best, _margin = leader(self.later_scores)
        return best

    def want_probe(self, steps: int, queue) -> bool:
        if queue:
            return False
        if self.used >= probe_budget() or steps >= 20:
            self._freeze()
            return False
        best, margin = leader(self.probe_scores)
        if self.used >= 3 and best is not None and margin >= 2:
            self._freeze()
            return False
        return True

    def _freeze(self) -> None:
        if self.frozen is None:
            self.frozen = self.hypothesis()

    def note_probe(self, key) -> None:
        self.pending = key
        self.used += 1
        if key and key[0] == "SIMPLE":
            try:
                self.tried.add(int(key[1]))
            except (TypeError, ValueError, IndexError):
                pass
        elif key and key[0] == "CLICK":
            self.tried.add(6)

    def absorb(self, before, after, *, probe: bool) -> None:
        scores = score_change(before, after)
        if probe:
            self.probe_scores.update(scores)
        else:
            self.later_scores.update(scores)
        copied = _copy(after)
        if copied is not None:
            self.last = copied
        if self.start is None:
            start = _copy(before)
            if start is not None:
                self.start = start

    def close(self, agent) -> None:
        if self.closed:
            return
        self.closed = True
        self._freeze()
        label = self.outcome()
        hyp = self.frozen
        stats = getattr(agent, "m2", None)
        if isinstance(stats, dict) and label and hyp:
            stats["discovery_scored"] = stats.get("discovery_scored", 0) + 1
            if label == hyp:
                stats["discovery_hits"] = stats.get("discovery_hits", 0) + 1
        if label and self.start is not None:
            feats = grid_features(project(self.start), [])
            remember(feats, label, holdout=os.getenv("MONAD2_HOLDOUT_GAME", ""))


def ensure(agent) -> LevelDiscovery:
    level = int(getattr(agent, "current_level", 0) or 0)
    disc = getattr(agent, "m2_discovery", None)
    if isinstance(disc, LevelDiscovery) and disc.level == level and not disc.closed:
        return disc
    if isinstance(disc, LevelDiscovery):
        disc.close(agent)
    disc = LevelDiscovery(level)
    agent.m2_discovery = disc
    return disc


def next_probe(agent, legal: list[int]):
    """The next diagnostic action, or None when the budget is finished."""
    disc = ensure(agent)
    steps = int(getattr(agent, "steps_in_level", 0) or 0)
    queue = getattr(agent, "planned_queue", None)
    if not disc.want_probe(steps, queue):
        return None
    for aid in (1, 2, 3, 4, 5):
        if aid in legal and aid not in disc.tried:
            return ("SIMPLE", aid)
    if 6 in legal and 6 not in disc.tried:
        grid = getattr(agent, "_m2_grid", None)
        if grid is not None:
            proj = project(grid, legal=legal)
            target = None
            for obj in proj.objects:
                if proj.controllable_role is not None and obj.role == proj.controllable_role:
                    continue
                if target is None or obj.size > target.size:
                    target = obj
            if target is not None:
                col = int(target.c0 + target.w // 2)
                row = int(target.r0 + target.h // 2)
                return ("CLICK", col, row)
    disc._freeze()
    return None


def observe_step(agent, changed: bool) -> None:
    """Update votes from the transition that just happened."""
    if not changed and getattr(agent, "m2_discovery", None) is None:
        return
    disc = ensure(agent)
    before = getattr(agent, "prev_grid", None)
    after = getattr(agent, "_m2_grid", None)
    pending = disc.pending
    disc.pending = None
    if pending is not None and before is not None and after is not None:
        disc.absorb(before, after, probe=True)
        stats = getattr(agent, "m2", None)
        if isinstance(stats, dict):
            stats["discovery_probes"] = stats.get("discovery_probes", 0) + 1
    elif disc.start is not None and changed and before is not None and after is not None:
        disc.absorb(before, after, probe=False)
    elif disc.start is None and after is not None:
        disc.start = _copy(after)
    hyp = disc.hypothesis()
    if hyp is not None:
        agent.m2_goal_hypothesis = hyp


def demote(agent, goal: str) -> None:
    disc = getattr(agent, "m2_discovery", None)
    if not isinstance(disc, LevelDiscovery):
        return
    if disc.probe_scores[goal] > 0:
        disc.probe_scores[goal] -= 1
    if disc.frozen == goal:
        best, margin = leader(disc.probe_scores)
        disc.frozen = best if best is not None and margin >= 1 else None
        agent.m2_goal_hypothesis = disc.frozen
