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


def unhash_record(rec: dict) -> dict:
    """Decode an FMF corpus record's structural features and schema text into actionable planning primitives,
    role bindings, and candidate priority without leaking game ids or coordinates."""
    feats = set(_features(rec))
    text = _text(rec).lower()
    goal = _goal(rec) or "REACH"
    primitives: list[str] = []
    role_bindings: list[str] = []
    candidate_priority = goal
    if "aff:switch" in feats or ("switch" in text and ("barrier" in text or "dissolve" in text or "gate" in text)):
        primitives.extend(["toggle", "approach"])
        role_bindings.append("switch->barrier:toggle(switch)->approach(avatar,goal)")
        candidate_priority = "SWITCH_FIRST"
    if "aff:push" in feats or "aff:annihil" in feats or ("push" in text and "block" in text):
        for p in ("convey", "approach"):
            if p not in primitives:
                primitives.append(p)
        role_bindings.append("movable->target:convey(avatar,movable)")
        if candidate_priority == "REACH":
            candidate_priority = "PLACE"
    if "aff:panel" in feats or ("panel" in text and any(w in text for w in ("align", "mismatch", "twin", "same shape"))):
        for p in ("align", "toggle"):
            if p not in primitives:
                primitives.append(p)
        role_bindings.append("panel->clickable:align(clickable,reference)")
        candidate_priority = "MATCH"
    if "aff:portal" in feats or "portal" in text or "coordinate transport" in text:
        if "approach" not in primitives:
            primitives.append("approach")
        role_bindings.append("portal->twin:approach(avatar,portal)")
    if not primitives:
        primitives.append("approach" if "aff:avatar" in feats else ("toggle" if "aff:click" in feats else "explore"))
    return {
        "goal": goal,
        "features": tuple(sorted(feats)),
        "is_schema": _is_schema(rec),
        "primitives": primitives,
        "role_bindings": role_bindings,
        "candidate_priority": candidate_priority,
        "schema_text": _text(rec).strip(),
    }


def retrieve_unhashed(query_features: tuple[str, ...], records: list[dict], k: int = 5) -> dict:
    """Unhash the top-k matching FMF records into ranked goals, motor primitives, role bindings,
    candidate priority, and structural schema rules for planning."""
    q = set(query_features)
    goal_scores: Counter[str] = Counter()
    prim_scores: Counter[str] = Counter()
    prio_scores: Counter[str] = Counter()
    bindings: list[str] = []
    schemas: list[str] = []
    matched_records: list[dict] = []
    if not q:
        return {
            "goals": [],
            "primitives": [],
            "role_bindings": [],
            "candidate_priority": "REACH",
            "schemas": [],
            "records": [],
        }
    scored_rows: list[tuple[int, dict]] = []
    for rec in records:
        rec_feats = set(_features(rec))
        overlap = len(q & rec_feats)
        if overlap <= 0:
            continue
        weight = 2 if _is_schema(rec) else 1
        score = overlap * weight
        decoded = unhash_record(rec)
        scored_rows.append((score, decoded))
        if decoded["goal"] in GOAL_TYPES:
            goal_scores[decoded["goal"]] += score
        for idx, prim in enumerate(decoded["primitives"]):
            prim_scores[prim] += max(1, score - idx)
        prio_scores[decoded["candidate_priority"]] += score
    scored_rows.sort(key=lambda item: (-item[0], 0 if item[1]["is_schema"] else 1, item[1]["goal"]))
    for _score, dec in scored_rows[:k]:
        matched_records.append(dec)
        for rb in dec["role_bindings"]:
            if rb not in bindings:
                bindings.append(rb)
        if dec["schema_text"] and len(schemas) < 2:
            schemas.append(dec["schema_text"])
    best_prio = prio_scores.most_common(1)[0][0] if prio_scores else "REACH"
    return {
        "goals": [g for g, _n in goal_scores.most_common(k)],
        "primitives": [p for p, _n in prim_scores.most_common(4)],
        "role_bindings": bindings[:4],
        "candidate_priority": best_prio,
        "schemas": schemas,
        "records": matched_records,
    }


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


_CANONICAL_MERKLE_PARENTS: dict[int, tuple[str, str, list[str], str]] = {
    1: ("PRIM_01_CONTROL_GAUGE_INVERSION", "INVERT_CANONICAL_DPAD_AND_CLEAR_FALSE_WALLS", ["explore", "approach"], "invert_dpad"),
    2: ("PRIM_02_S16_PALETTE_GAUGE_EQUIVARIANCE", "CANONICALIZE_S16_TOPOLOGICAL_PALETTE_GAUGE", ["approach", "explore"], "shape_invariant"),
    3: ("PRIM_03_ILLUSORY_VS_SOLID_BARRIER", "PROBE_STICKY_THEN_MARK_SOLID_WALL_AND_DETOUR", ["route", "approach"], "detour_wall"),
    4: ("PRIM_04_COUPLED_REMOTE_SWITCH_GATE", "ROUTE_TO_COUPLED_SWITCH_AFFORDANCE", ["toggle", "approach"], "switch_first"),
    5: ("PRIM_05_DYNAMIC_SENTRY_PATROL_PHASE", "MARK_HAZARD_LOCUS_AND_SIMULATE_SENTRY_PHASE", ["avoid", "approach"], "avoid_hazard"),
    6: ("PRIM_06_DECOY_GOAL_INHIBITION", "INHIBIT_DECOY_GOAL_AND_RETARGET", ["explore", "approach"], "refute_decoy"),
    7: ("PRIM_07_MULTI_OPERATOR_COUPLED_SYMMETRY", "CYCLE_COUPLED_OPERATOR_SYMMETRY_MODE", ["convey", "approach"], "coupled_avatar"),
    8: ("PRIM_08_DEMONSTRATION_PANEL_CEGIS_SYNTHESIS", "SYNTHESIZE_CEGIS_PANEL_TRANSFORMATION", ["align", "toggle"], "match_panel"),
    11: ("PRIM_11_AUTOBIOGRAPHICAL_CAUSAL_WIN_CHAIN", "BACKPROPAGATE_AUTOBIOGRAPHICAL_WIN_CHAIN_LTP", ["approach", "convey", "toggle"], "win_chain"),
    12: ("PRIM_12_PROCEDURAL_CAUSAL_REFUTATION_REDIRECT", "DEPRESS_PROCEDURAL_WEIGHT_LTD_AND_REDIRECT_SOLVER", ["explore", "toggle"], "refute_decoy"),
}


def unhash_packed_node(packed_u64: int, tree=None, relational_sig16: int | None = None) -> dict:
    """Decode a 64-bit packed Fuzzy Merkle node [32b_sig : 16b_parent_id : 16b_weight] into
    actionable planning primitives, endorsed/refuted goals, board relation flags, and candidate bias."""
    if tree is not None and hasattr(tree, "unhash_packed_node"):
        return tree.unhash_packed_node(int(packed_u64), relational_sig16=relational_sig16)
    u = int(packed_u64) & 0xFFFFFFFFFFFFFFFF
    sig32 = (u >> 32) & 0xFFFFFFFF
    pid16 = (u >> 16) & 0xFFFF
    w16 = u & 0xFFFF
    prim_id, operator, rec_prims, cand_bias = _CANONICAL_MERKLE_PARENTS.get(
        pid16,
        (f"SEED_{pid16:04d}", "OBSERVE", ["approach", "explore"], "canonical"),
    )
    upper16 = (sig32 >> 16) & 0xFFFF
    rel_b16 = int(relational_sig16) & 0xFFFF if relational_sig16 is not None else upper16
    decoded_board_relations = {
        "has_dpad": bool((rel_b16 >> 15) & 1),
        "has_pointer": bool((rel_b16 >> 14) & 1),
        "has_avatar": bool((rel_b16 >> 13) & 1),
        "has_panel_pair": bool((rel_b16 >> 12) & 1),
        "has_pushable": bool((rel_b16 >> 11) & 1),
        "shape_bucket": int((rel_b16 >> 8) & 0x7),
        "color_bucket": int((rel_b16 >> 4) & 0xF),
        "unique_small_objs": int(rel_b16 & 0xF),
    }
    endorsed_goals: list[str] = []
    refuted_goals: list[str] = []
    if pid16 == 8:
        endorsed_goals.append("MATCH")
    elif pid16 == 4:
        endorsed_goals.append("REACH")
    return {
        "sig32": sig32,
        "parent_id16": pid16,
        "weight16": w16,
        "parent_primitive_id": prim_id,
        "top_down_operator": operator,
        "core_knowledge_axiom": "",
        "decoded_pattern": (),
        "decoded_minutiae": [],
        "decoded_procedure": "",
        "decoded_board_relations": decoded_board_relations,
        "endorsed_goals": endorsed_goals,
        "refuted_goals": refuted_goals,
        "recommended_primitives": list(rec_prims),
        "candidate_bias": cand_bias,
        "cold_payload": {},
    }

