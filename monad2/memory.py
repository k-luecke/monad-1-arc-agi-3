"""Structural FMF memory. Keys are affordance features, never a game id.

When evaluating game G, drop any record whose game_id, task_id, game_ids, or
text names G. SCHEMA abstracts outrank game-specific traces. A hypothesis is
promoted only after two confirmations inside the episode, and one lock-loss
demotion can take it back under that line.

Goal-label words are not features. "match" and "reach" in prose would leak the
label into the key.
"""
from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path

GOAL_TYPES = ("REACH", "PLACE", "MATCH")

# Structural needles only. Do not add the goal-type names.
_NEEDLES = (
    ("portal", "aff:portal"),
    ("switch", "aff:switch"),
    ("annihil", "aff:annihil"),
    ("chasm", "aff:annihil"),
    ("panel", "aff:panel"),
    ("push", "aff:push"),
    ("block", "aff:push"),
    ("avatar", "aff:avatar"),
    ("sprite", "aff:avatar"),
    ("remote", "aff:remote"),
    ("action6", "aff:click"),
    ("click", "aff:click"),
    ("corridor", "aff:corridor"),
)

_CACHE: dict[tuple[str, int], list[dict]] = {}


def corpus_path() -> Path:
    return Path(__file__).resolve().parent / "fmf_corpus" / "records.jsonl"


def _is_schema(rec: dict) -> bool:
    kind = str(rec.get("record_kind") or rec.get("kind") or rec.get("type") or "")
    return kind.lower() == "dream_schema" or kind.upper().startswith("SCHEMA")


def _text(rec: dict) -> str:
    parts = []
    for key in (
        "observation",
        "hypothesis",
        "outcome",
        "inferred_goal",
        "text",
        "thought",
        "abstract",
        "schema",
        "content",
        "reasoning",
    ):
        val = rec.get(key)
        if isinstance(val, str):
            parts.append(val)
    plan = rec.get("action_plan")
    if isinstance(plan, list):
        parts.append(" ".join(str(x) for x in plan))
    elif isinstance(plan, str):
        parts.append(plan)
    return "\n".join(parts)


def _names_game(rec: dict, game: str) -> bool:
    game = game.lower().strip()
    if not game:
        return False
    for key in ("game_id", "task_id", "game"):
        val = rec.get(key)
        if isinstance(val, str) and val.lower().startswith(game):
            return True
    listed = rec.get("game_ids")
    if isinstance(listed, list):
        for val in listed:
            if str(val).lower().startswith(game):
                return True
    return re.search(rf"\b{re.escape(game)}\b", _text(rec).lower()) is not None


def _goal(rec: dict) -> str | None:
    """Map a record onto REACH, PLACE, or MATCH. Other tags stay unmapped."""
    for key in ("inferred_goal", "goal_type", "goal"):
        raw = str(rec.get(key) or "").upper()
        if raw in GOAL_TYPES:
            return raw
    listed = rec.get("goal_types")
    if isinstance(listed, list):
        for val in listed:
            name = str(val).upper()
            if name in GOAL_TYPES:
                return name
    # No explicit label. A described change can still ground one.
    from monad2.discovery import outcome_label

    return outcome_label(rec)


def _features(rec: dict) -> tuple[str, ...]:
    if rec.get("features"):
        feats = rec["features"]
        if isinstance(feats, dict):
            return tuple(sorted(f"{k}:{v}" for k, v in feats.items()))
        if isinstance(feats, list):
            return tuple(str(x) for x in feats)
    text = _text(rec).lower()
    feats = [name for needle, name in _NEEDLES if needle in text]
    if not feats:
        feats.append("aff:unknown")
    return tuple(sorted(set(feats)))


def grid_features(proj, legal: list[int] | tuple[int, ...]) -> tuple[str, ...]:
    """Affordances read off the live projection. No game id and no goal word."""
    feats: list[str] = []
    actions = [int(a) for a in (legal or [])]
    if getattr(proj, "controllable_role", None) is not None:
        feats.append("aff:avatar")
    if int(getattr(proj, "panel_mismatch", 0) or 0) >= 4:
        feats.append("aff:panel")
    if 6 in actions:
        feats.append("aff:click")
    objs = list(getattr(proj, "objects", None) or [])
    has_dpad = any(a in (1, 2, 3, 4) for a in actions)
    if has_dpad and len(objs) >= 3:
        feats.append("aff:push")
    if 6 in actions and any(int(getattr(o, "size", 0)) <= 2 for o in objs):
        feats.append("aff:switch")
    for obj in objs:
        h = int(getattr(obj, "h", 0))
        w = int(getattr(obj, "w", 0))
        long = max(h, w)
        if long >= 12 and min(h, w) / long <= 0.35:
            feats.append("aff:corridor")
            break
    for i, a in enumerate(objs):
        for b in objs[i + 1 :]:
            if int(getattr(a, "role", -1)) != int(getattr(b, "role", -2)):
                continue
            if abs(int(a.size) - int(b.size)) > max(2, int(a.size) // 4):
                continue
            gap = abs((a.r0 + a.h / 2) - (b.r0 + b.h / 2)) + abs((a.c0 + a.w / 2) - (b.c0 + b.w / 2))
            if gap >= 16:
                feats.append("aff:portal")
                break
        if "aff:portal" in feats:
            break
    return tuple(sorted(set(feats)))


def load_records(path: str | Path) -> list[dict]:
    p = Path(path)
    key = (str(p.resolve()), p.stat().st_mtime_ns)
    cached = _CACHE.get(key)
    if cached is not None:
        return cached
    rows = []
    with p.open(encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            rows.append(json.loads(line))
    _CACHE[key] = rows
    return rows


def eligible(records: list[dict], heldout_game: str) -> list[dict]:
    kept = []
    for rec in records:
        if heldout_game and _names_game(rec, heldout_game):
            continue
        if _goal(rec) is None and not _is_schema(rec):
            continue
        kept.append(rec)
    schema = [r for r in kept if _is_schema(r)]
    rest = [r for r in kept if not _is_schema(r)]
    return schema + rest


def retrieve(query_features: tuple[str, ...], records: list[dict], k: int = 5) -> list[str]:
    """Top-k goal hypotheses by feature overlap. SCHEMA records count double."""
    scores: Counter[str] = Counter()
    q = set(query_features)
    if not q:
        return []
    for rec in records:
        goal = _goal(rec)
        if goal is None:
            continue
        overlap = len(q & set(_features(rec)))
        if overlap <= 0:
            continue
        weight = 2 if _is_schema(rec) else 1
        scores[goal] += overlap * weight
    return [g for g, _n in scores.most_common(k)]


class EpisodeLTP:
    """Promote a goal only after two confirmations in the episode."""

    def __init__(self) -> None:
        self.confirms: Counter[str] = Counter()
        self.surprises: list[str] = []

    def confirm(self, goal: str) -> bool:
        self.confirms[goal] += 1
        return self.confirms[goal] >= 2

    def demote(self, goal: str) -> int:
        if self.confirms[goal] > 0:
            self.confirms[goal] -= 1
        return int(self.confirms[goal])

    def promoted(self) -> list[str]:
        return [g for g, n in self.confirms.items() if n >= 2]
