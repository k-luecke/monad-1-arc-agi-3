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


def _color_centroids(grid: list[list[int]]) -> dict[int, tuple[float, float, int]]:
    counts: Counter[int] = Counter(v for row in grid for v in row)
    if not counts:
        return {}
    bg = counts.most_common(1)[0][0]
    acc: dict[int, list[int]] = {}
    for r, row in enumerate(grid):
        for c, value in enumerate(row):
            if value == bg:
                continue
            bucket = acc.setdefault(int(value), [0, 0, 0])
            bucket[0] += r
            bucket[1] += c
            bucket[2] += 1
    return {color: (sr / n, sc / n, n) for color, (sr, sc, n) in acc.items() if n}


def _color_votes(before: list[list[int]], after: list[list[int]], scores: Counter[str]) -> None:
    """Shift votes keyed by color, so a role-rank change does not hide the motion."""
    left = _color_centroids(before)
    right = _color_centroids(after)
    shifts: list[tuple[int, int]] = []
    small = 0
    for color, (r, c, n) in left.items():
        other = right.get(color)
        if other is None:
            continue
        if abs(other[2] - n) / max(n, other[2]) > 0.5:
            continue
        dr = int(round(other[0] - r))
        dc = int(round(other[1] - c))
        if dr or dc:
            shifts.append((dr, dc))
            if n <= 36:
                small = max(small, abs(dr) + abs(dc))
    if len(shifts) >= 2 and len(set(shifts)) == 1:
        scores["PLACE"] += 2
    if small >= 1 and len(shifts) <= 1:
        scores["REACH"] += 2


def score_change(before, after, *, allow_large: bool = False) -> Counter[str]:
    """Votes from one observed transition. A no-op votes for nothing.

    A jump above 400 cells votes for nothing unless ``allow_large`` is set.
    The start-versus-end label sets it, because a whole level can move more
    than one step does. Goal-type words are not read.
    """
    scores: Counter[str] = Counter()
    b = _copy(before)
    a = _copy(after)
    if b is None or a is None:
        return scores
    changed = _changed_cells(b, a)
    if changed <= 0 or (changed > 400 and not allow_large):
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
    _color_votes(b, a, scores)
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


def watch_on() -> bool:
    return os.getenv("MONAD2_GOAL_WATCH", "0") == "1"


class WatchEpisode:
    """Start hypothesis and endpoint label for one level segment.

    Nothing on this object is read by action selection. The hypothesis freezes
    from the natural action stream and from effects already observed for other
    legal actions. The outcome is the start frame against the last in-level frame.
    """

    def __init__(self, level: int) -> None:
        self.level = int(level)
        self.start = None
        self.last = None
        self.scores: Counter[str] = Counter()
        self.frozen: str | None = None
        self.frozen_step: int | None = None
        self.changes = 0
        self.steps = 0
        self.closed = False
        self.hypotheticals: set[int] = set()
        self.seen: set[int] = set()

    def note_last(self, grid) -> None:
        copied = _copy(grid)
        if copied is not None:
            self.last = copied


def _effect_table(agent) -> dict[int, Counter[str]]:
    table = getattr(agent, "m2_watch_effects", None)
    if not isinstance(table, dict):
        table = {}
        agent.m2_watch_effects = table
    return table


def _apply_hypotheticals(agent, ep: WatchEpisode, legal: list[int]) -> None:
    """Add votes for actions the effect model has already seen and this segment has not taken."""
    if ep.frozen_step is not None:
        return
    used = ep.hypotheticals if isinstance(ep.hypotheticals, set) else set()
    ep.hypotheticals = used
    table = _effect_table(agent)
    for aid in legal:
        if aid in ep.seen or aid in used or aid not in table:
            continue
        ep.scores.update(table[aid])
        used.add(aid)
    predict = getattr(agent, "_fx_predict", None)
    grid = ep.last if ep.last is not None else ep.start
    if not callable(predict) or grid is None:
        return
    for aid in legal:
        if aid in ep.seen or aid in used:
            continue
        key = ("CLICK", 32, 32) if aid == 6 else ("SIMPLE", aid)
        try:
            nxt = predict(grid, key)
        except Exception:
            nxt = None
        if nxt is None:
            used.add(aid)
            continue
        ep.scores.update(score_change(grid, nxt))
        used.add(aid)


def _maybe_freeze(agent, ep: WatchEpisode) -> None:
    if ep.frozen is not None or ep.frozen_step is not None:
        return
    steps = int(getattr(agent, "steps_in_level", 0) or 0)
    best, margin = leader(ep.scores)
    ready = (ep.changes >= 2 and best is not None and margin >= 1) or steps >= 12
    if not ready:
        return
    ep.frozen = best
    ep.frozen_step = steps


def watch_close(agent, reason: str = "game") -> None:
    ep = getattr(agent, "m2_watch", None)
    if not isinstance(ep, WatchEpisode) or ep.closed:
        return
    ep.closed = True
    if ep.frozen_step is None:
        best, _margin = leader(ep.scores)
        ep.frozen = best
        ep.frozen_step = int(getattr(agent, "steps_in_level", 0) or 0)
    outcome: str | None = None
    if ep.start is not None and ep.last is not None:
        votes = score_change(ep.start, ep.last, allow_large=True)
        outcome, _margin = leader(votes)
        if outcome is None and _changed_cells(ep.start, ep.last) > 0:
            outcome = "OTHER"
    hyp = ep.frozen if ep.frozen in GOAL_TYPES else None
    confirmed = outcome if outcome in GOAL_TYPES else None
    stats = getattr(agent, "m2", None)
    if isinstance(stats, dict):
        stats["watch_episodes"] = stats.get("watch_episodes", 0) + 1
        if confirmed is not None:
            stats["watch_labeled"] = stats.get("watch_labeled", 0) + 1
        if confirmed is not None and hyp is not None:
            stats["watch_scored"] = stats.get("watch_scored", 0) + 1
            if confirmed == hyp:
                stats["watch_hits"] = stats.get("watch_hits", 0) + 1
    feats: tuple[str, ...] = ()
    stored = False
    if ep.start is not None:
        try:
            feats = grid_features(project(ep.start), [])
        except Exception:
            feats = ()
    holdout = os.getenv("MONAD2_HOLDOUT_GAME", "")
    if confirmed is not None and feats:
        before = len(EPISODE_FMF)
        remember(feats, confirmed, holdout=holdout)
        stored = len(EPISODE_FMF) > before
    log = getattr(agent, "m2_watch_log", None)
    if not isinstance(log, list):
        log = []
        agent.m2_watch_log = log
    log.append(
        {
            "level": ep.level,
            "reason": reason,
            "hypothesis": hyp,
            "outcome": outcome,
            "frozen_step": ep.frozen_step,
            "changes": ep.changes,
            "steps": ep.steps,
            "features": list(feats),
            "stored": stored,
        }
    )


def _open_watch(agent, level: int, *, boundary: bool, before, after) -> WatchEpisode:
    ep = WatchEpisode(level)
    agent.m2_watch = ep
    if boundary:
        ep.start = _copy(after)
        ep.last = ep.start
        return ep
    ep.start = _copy(before) or _copy(after)
    ep.last = _copy(after) or ep.start
    return ep


def watch_step(agent, changed: bool, force: bool = False) -> None:
    """Update the open segment from the transition that just happened.

    The coordination path passes force so a watch hypothesis is available as a
    labeled candidate. That hypothesis is not a bound goal.
    """
    if not force and not watch_on():
        return
    level = int(getattr(agent, "current_level", 0) or 0)
    before = getattr(agent, "prev_grid", None)
    after = getattr(agent, "_m2_grid", None)
    ep = getattr(agent, "m2_watch", None)
    boundary = isinstance(ep, WatchEpisode) and not ep.closed and ep.level != level
    if boundary:
        if before is not None and after is not None:
            b = _copy(before)
            a = _copy(after)
            if b is not None and a is not None and _changed_cells(b, a) <= 400:
                ep.note_last(after)
            elif ep.last is None:
                ep.note_last(before)
        elif before is not None:
            ep.note_last(before)
        watch_close(agent, reason="level")
        ep = None
    if not isinstance(ep, WatchEpisode) or ep.closed:
        ep = _open_watch(agent, level, boundary=boundary, before=before, after=after)
        if boundary:
            return
    ep.steps += 1
    if ep.frozen_step is not None:
        if changed and before is not None and after is not None:
            b = _copy(before)
            a = _copy(after)
            if b is not None and a is not None and 0 < _changed_cells(b, a) <= 400:
                ep.note_last(after)
                ep.changes += 1
        return
    if changed and before is not None and after is not None:
        b = _copy(before)
        a = _copy(after)
        if b is not None and a is not None:
            changed_n = _changed_cells(b, a)
            if 0 < changed_n <= 400:
                ep.note_last(after)
                ep.changes += 1
                votes = score_change(b, a)
                ep.scores.update(votes)
                key = getattr(agent, "prev_action", None)
                aid = -1
                if key and key[0] == "SIMPLE":
                    try:
                        aid = int(key[1])
                    except (TypeError, ValueError, IndexError):
                        aid = -1
                elif key and key[0] == "CLICK":
                    aid = 6
                if aid >= 0 and votes:
                    ep.seen.add(aid)
                    table = _effect_table(agent)
                    bucket = table.get(aid)
                    if bucket is None:
                        bucket = Counter()
                        table[aid] = bucket
                    bucket.update(votes)
    legal = [int(a) for a in (getattr(agent, "_m2_avail", None) or []) if int(a) != 0]
    _apply_hypotheticals(agent, ep, legal)
    _maybe_freeze(agent, ep)


def finalize_watch(agent) -> None:
    watch_close(agent, reason="game")
