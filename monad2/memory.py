"""Structural FMF memory. Keys are affordance features, never a game id.

When evaluating game G, drop any record whose game_id/task_id is G or whose text
names G. SCHEMA abstracts outrank game-specific traces. A hypothesis is promoted
only after two confirmations inside the episode.
"""
from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path

GOAL_TYPES = ("REACH", "PLACE", "MATCH")
_GAME_ID = re.compile(r"\b([a-z][a-z0-9]{3})\b", re.I)


def _text(rec: dict) -> str:
    parts = []
    for key in ("text", "thought", "abstract", "schema", "content", "reasoning"):
        val = rec.get(key)
        if isinstance(val, str):
            parts.append(val)
    return "\n".join(parts)


def _names_game(rec: dict, game: str) -> bool:
    game = game.lower()
    for key in ("game_id", "task_id", "game"):
        val = str(rec.get(key) or "").lower()
        if val.startswith(game):
            return True
    return game in _text(rec).lower()


def _goal(rec: dict) -> str | None:
    raw = str(rec.get("goal_type") or rec.get("goal") or "").upper()
    for g in GOAL_TYPES:
        if g in raw:
            return g
    text = _text(rec).upper()
    # Keyword tags are rough. SCHEMA abstracts win over a keyword in a debug trace.
    if str(rec.get("kind") or rec.get("type") or "").upper().startswith("SCHEMA"):
        for g in GOAL_TYPES:
            if g in text:
                return g
    for g in GOAL_TYPES:
        if g in text:
            return g
    return None


def _features(rec: dict) -> tuple[str, ...]:
    if rec.get("features"):
        feats = rec["features"]
        if isinstance(feats, dict):
            return tuple(sorted(f"{k}:{v}" for k, v in feats.items()))
        if isinstance(feats, list):
            return tuple(str(x) for x in feats)
    text = _text(rec).lower()
    feats = []
    for needle, name in (
        ("remote", "aff:remote"),
        ("portal", "aff:portal"),
        ("annihil", "aff:annihil"),
        ("panel", "aff:panel"),
        ("push", "aff:push"),
        ("click", "aff:click"),
        ("avatar", "aff:avatar"),
        ("match", "aff:panel"),
        ("reach", "aff:avatar"),
    ):
        if needle in text:
            feats.append(name)
    if not feats:
        feats.append("aff:unknown")
    return tuple(sorted(set(feats)))


def load_records(path: str | Path) -> list[dict]:
    rows = []
    with Path(path).open(encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            rows.append(json.loads(line))
    return rows


def eligible(records: list[dict], heldout_game: str) -> list[dict]:
    kept = []
    for rec in records:
        if _names_game(rec, heldout_game):
            continue
        if _goal(rec) is None and not str(rec.get("kind") or "").upper().startswith("SCHEMA"):
            continue
        kept.append(rec)
    schema = [r for r in kept if str(r.get("kind") or r.get("type") or "").upper().startswith("SCHEMA")]
    return schema + [r for r in kept if r not in schema]


def retrieve(query_features: tuple[str, ...], records: list[dict], k: int = 5) -> list[str]:
    """Top-k goal hypotheses by feature overlap. SCHEMA records count double."""
    scores: Counter[str] = Counter()
    q = set(query_features)
    for rec in records:
        goal = _goal(rec)
        if goal is None:
            continue
        overlap = len(q & set(_features(rec)))
        if overlap <= 0:
            continue
        weight = 2 if str(rec.get("kind") or rec.get("type") or "").upper().startswith("SCHEMA") else 1
        scores[goal] += overlap * weight
    return [g for g, _n in scores.most_common(k)]


class EpisodeLTP:
    """Promote a goal only after two confirmations in the episode."""

    def __init__(self) -> None:
        self.confirms: Counter[str] = Counter()

    def confirm(self, goal: str) -> bool:
        self.confirms[goal] += 1
        return self.confirms[goal] >= 2

    def promoted(self) -> list[str]:
        return [g for g, n in self.confirms.items() if n >= 2]
