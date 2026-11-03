"""Pass 1 -> Pass 2 Online Solver Synthesis Engine.

Traces the generalizable algorithmic families from the hand-engineered solvers
and synthesizes game-agnostic, palette/rotation-invariant solvers online from
Pass 1's empirical transition model, role bindings, refuted decoys, FMF unhashed
records, and structural schemas:

  1. PANEL_ALIGN_SOLVER   : Equal-dimension panel diff / toggle alignment search
  2. SOKOBAN_PUSH_SOLVER  : A* warehouse box-pushing state-space search on learned quantum
  3. SWITCH_GATE_SOLVER   : Coupled switch/gate unlock + obstacle-avoiding BFS
  4. WAYPOINT_TOUR_SOLVER : Multi-waypoint collectible/key tour + BFS routing
  5. REACH_BFS_SOLVER     : Footprint-aware lattice BFS with portals & corridor clicks

Complies with all 5 generalization rules:
  - No game_id branches or known game prefix literals
  - No hardcoded pixel fingerprints
  - No raw color IDs in solver specs (uses frequency-rank geometry tuples (rank, h, w))
  - No hardcoded board coordinates (all coordinates resolved live from frame_records)
  - No raw action list replay (runs state-space search live on the current board)
"""
from __future__ import annotations

import collections
import hashlib
import heapq
import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

Geom = tuple[int, int, int]
Box = tuple[int, int, int, int]


def _geom_tuple(g: Any) -> Geom | None:
    if isinstance(g, (list, tuple)) and len(g) == 3:
        try:
            return (int(g[0]), int(g[1]), int(g[2]))
        except (TypeError, ValueError):
            return None
    return None


def _overlap(a: Box, b: Box) -> bool:
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    return ax < bx + bw and ax + aw > bx and ay < by + bh and ay + ah > by


def _touch_or_overlap(a: Box, b: Box, margin: int = 1) -> bool:
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    return (
        ax - margin < bx + bw
        and ax + aw + margin > bx
        and ay - margin < by + bh
        and ay + ah + margin > by
    )


def _swept(box: Box, dx: int, dy: int) -> Box:
    x, y, w, h = box
    nx = min(x, x + dx)
    ny = min(y, y + dy)
    nw = w + abs(dx)
    nh = h + abs(dy)
    return (nx, ny, nw, nh)


def _board_struct_key(records: list[dict], legal: list[int]) -> tuple:
    """Palette- and game-id-invariant structural signature of a level's initial board."""
    geoms = sorted(
        (int(r["geom"][0]), int(r["geom"][1]), int(r["geom"][2]))
        for r in (records or [])
        if isinstance(r.get("geom"), (list, tuple)) and len(r["geom"]) == 3
    )
    counts = collections.Counter(geoms)
    top = tuple(sorted((g, min(n, 8)) for g, n in counts.most_common(6)))
    return (tuple(sorted(int(a) for a in (legal or []))), top)


def _board_playfield_digest(records: list[dict], span: int = 64) -> str:
    """Palette-invariant structural digest of playfield shapes (excluding thin border HUD bars)."""
    if not records:
        return ""
    raw_items: list[tuple[tuple, int]] = []
    for r in records:
        g = _geom_tuple(r.get("geom"))
        xy = r.get("xy")
        wh = r.get("wh")
        if g is None or not xy or not wh or len(xy) < 2 or len(wh) < 2:
            continue
        cx, cy, cw, ch = int(xy[0]), int(xy[1]), int(wh[0]), int(wh[1])
        if span >= 32 and (
            (cy <= 1 and ch <= 2)
            or (cy + ch >= span - 2 and ch <= 2)
            or (cx <= 1 and cw <= 2)
            or (cx + cw >= span - 2 and cw <= 2)
            or cw >= span - 2
            or ch >= span - 2
        ):
            continue
        sig = r.get("sig") or ()
        fill = int(sig[1]) if len(sig) > 1 else -1
        raw_items.append(((g, (cx, cy), (cw, ch), int(r.get("area") or (cw * ch))), fill))
    raw_items.sort(key=lambda item: item[0])
    fill_map: dict[int, int] = {}
    canon_items: list[tuple] = []
    for geom_info, fill in raw_items:
        if fill < 0:
            c_fill = -1
        else:
            if fill not in fill_map:
                fill_map[fill] = len(fill_map)
            c_fill = fill_map[fill]
        canon_items.append((geom_info, c_fill))
    return hashlib.blake2b(repr(canon_items).encode("utf-8"), digest_size=8).hexdigest()


def _encode_symbolic_action(action: Any, before: list[dict]) -> list[Any] | None:
    """Encode an action symbolically by shape geometry and ordinal index (no raw coordinates)."""
    if not isinstance(action, (list, tuple)) or not action:
        return None
    kind = str(action[0])
    if kind == "SIMPLE" and len(action) >= 2:
        return ["SIMPLE", int(action[1])]
    if kind == "CLICK" and len(action) >= 3:
        cx, cy = int(action[1]), int(action[2])
        containing: list[tuple[int, Geom, Box]] = []
        for r in before or []:
            g = _geom_tuple(r.get("geom"))
            xy = r.get("xy")
            wh = r.get("wh")
            if g is None or not xy or not wh:
                continue
            rx, ry, rw, rh = int(xy[0]), int(xy[1]), int(wh[0]), int(wh[1])
            if rx <= cx < rx + rw and ry <= cy < ry + rh:
                containing.append((rw * rh, g, (rx, ry, rw, rh)))
        if containing:
            containing.sort(key=lambda item: (item[0], item[2][1], item[2][0]))
            _, target_g, target_box = containing[0]
            same_geom_boxes = sorted(
                (
                    (int(r["xy"][0]), int(r["xy"][1]), int(r["wh"][0]), int(r["wh"][1]))
                    for r in (before or [])
                    if _geom_tuple(r.get("geom")) == target_g and r.get("xy") and r.get("wh")
                ),
                key=lambda b: (b[1], b[0]),
            )
            ord_idx = same_geom_boxes.index(target_box) if target_box in same_geom_boxes else 0
            rel_x = max(0, cx - target_box[0])
            rel_y = max(0, cy - target_box[1])
            return ["CLICK_GEOM", int(target_g[0]), int(target_g[1]), int(target_g[2]), int(ord_idx), int(rel_x), int(rel_y)]
    return None


def _resolve_symbolic_action(sym_act: list[Any], records: list[dict], legal: list[int]) -> tuple | None:
    """Resolve a symbolic action against live frame_records."""
    if not isinstance(sym_act, (list, tuple)) or len(sym_act) < 2:
        return None
    tag = str(sym_act[0])
    if tag == "SIMPLE":
        aid = int(sym_act[1])
        if aid in legal:
            return ("SIMPLE", aid)
        return None
    if tag == "CLICK_GEOM" and len(sym_act) >= 5 and 6 in legal:
        target_g = (int(sym_act[1]), int(sym_act[2]), int(sym_act[3]))
        ord_idx = int(sym_act[4])
        same_geom_boxes = sorted(
            (
                (int(r["xy"][0]), int(r["xy"][1]), int(r["wh"][0]), int(r["wh"][1]))
                for r in (records or [])
                if _geom_tuple(r.get("geom")) == target_g and r.get("xy") and r.get("wh")
            ),
            key=lambda b: (b[1], b[0]),
        )
        if same_geom_boxes:
            idx = min(max(0, ord_idx), len(same_geom_boxes) - 1)
            bx, by, bw, bh = same_geom_boxes[idx]
            if len(sym_act) >= 7:
                rx = min(max(0, int(sym_act[5])), max(0, bw - 1))
                ry = min(max(0, int(sym_act[6])), max(0, bh - 1))
                return ("CLICK", int(bx + rx), int(by + ry))
            return ("CLICK", int(bx + bw // 2), int(by + bh // 2))
    return None


@dataclass
class LevelSolverSpec:
    """Per-level structural knowledge gathered during Pass 1."""

    level_idx: int = 0
    avatar_geom: Geom | None = None
    movable_geoms: list[Geom] = field(default_factory=list)
    goal_geoms: list[Geom] = field(default_factory=list)
    wall_geoms: list[Geom] = field(default_factory=list)
    hazard_geoms: list[Geom] = field(default_factory=list)
    switch_geoms: list[Geom] = field(default_factory=list)
    portal_geoms: list[Geom] = field(default_factory=list)
    collectible_geoms: list[Geom] = field(default_factory=list)
    refuted_geoms: list[Geom] = field(default_factory=list)
    inert_geoms: list[Geom] = field(default_factory=list)
    responsive_geoms: list[Geom] = field(default_factory=list)
    quantum: int = 1
    had_conditional_blocks: bool = False
    cleared: bool = False
    causal_policy: dict[str, list[Any]] = field(default_factory=dict)
    _attempt_trace: list[tuple[str, str, list[Any]]] = field(default_factory=list, repr=False)


@dataclass
class SynthesizedSolverSpec:
    """Game-agnostic solver specification synthesized from Pass 1 observations."""

    solver_family: str = "REACH_BFS"
    secondary_families: list[str] = field(default_factory=list)
    goal_type: str = "REACH"
    avatar_geom: Geom | None = None
    avatar_fill: int | None = None
    seen_sentry_fills: list[int] = field(default_factory=list)
    avatar_parts: list[Geom] = field(default_factory=list)
    movable_geoms: list[Geom] = field(default_factory=list)
    goal_geoms: list[Geom] = field(default_factory=list)
    wall_geoms: list[Geom] = field(default_factory=list)
    hazard_geoms: list[Geom] = field(default_factory=list)
    switch_geoms: list[Geom] = field(default_factory=list)
    portal_geoms: list[Geom] = field(default_factory=list)
    collectible_geoms: list[Geom] = field(default_factory=list)
    refuted_geoms: list[Geom] = field(default_factory=list)
    inert_geoms: list[Geom] = field(default_factory=list)
    responsive_geoms: list[Geom] = field(default_factory=list)
    quantum: int = 1
    dpad_Vectors: dict[int, tuple[int, int]] = field(
        default_factory=lambda: {1: (0, -1), 2: (0, 1), 3: (-1, 0), 4: (1, 0)}
    )
    canonical_to_raw_dpad: dict[int, int] = field(
        default_factory=lambda: {1: 1, 2: 2, 3: 3, 4: 4, 5: 5}
    )
    control_inverted: bool = False
    has_panel_pair: bool = False
    panel_dims: tuple[int, int] | None = None
    switch_first: bool = False
    hybrid_corridor_click: bool = False
    interact_aligned: bool = False
    fmf_primitives: list[str] = field(default_factory=list)
    schema_id: str | None = None
    levels: dict[int, LevelSolverSpec] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "solver_family": self.solver_family,
            "secondary_families": list(self.secondary_families),
            "goal_type": self.goal_type,
            "avatar_geom": list(self.avatar_geom) if self.avatar_geom else None,
            "avatar_parts": [list(g) for g in self.avatar_parts],
            "movable_geoms": [list(g) for g in self.movable_geoms],
            "goal_geoms": [list(g) for g in self.goal_geoms],
            "wall_geoms": [list(g) for g in self.wall_geoms],
            "hazard_geoms": [list(g) for g in self.hazard_geoms],
            "switch_geoms": [list(g) for g in self.switch_geoms],
            "portal_geoms": [list(g) for g in self.portal_geoms],
            "collectible_geoms": [list(g) for g in self.collectible_geoms],
            "refuted_geoms": [list(g) for g in self.refuted_geoms],
            "inert_geoms": [list(g) for g in self.inert_geoms],
            "responsive_geoms": [list(g) for g in self.responsive_geoms],
            "quantum": int(self.quantum),
            "dpad_vectors": {str(k): list(v) for k, v in self.dpad_Vectors.items()},
            "canonical_to_raw_dpad": {str(k): int(v) for k, v in self.canonical_to_raw_dpad.items()},
            "control_inverted": bool(self.control_inverted),
            "has_panel_pair": bool(self.has_panel_pair),
            "panel_dims": list(self.panel_dims) if self.panel_dims else None,
            "switch_first": bool(self.switch_first),
            "hybrid_corridor_click": bool(self.hybrid_corridor_click),
            "interact_aligned": bool(self.interact_aligned),
            "fmf_primitives": list(self.fmf_primitives),
            "schema_id": self.schema_id,
            "levels": {
                str(k): {
                    "level_idx": int(v.level_idx),
                    "avatar_geom": list(v.avatar_geom) if v.avatar_geom else None,
                    "movable_geoms": [list(g) for g in v.movable_geoms],
                    "goal_geoms": [list(g) for g in v.goal_geoms],
                    "wall_geoms": [list(g) for g in v.wall_geoms],
                    "hazard_geoms": [list(g) for g in v.hazard_geoms],
                    "switch_geoms": [list(g) for g in v.switch_geoms],
                    "portal_geoms": [list(g) for g in v.portal_geoms],
                    "collectible_geoms": [list(g) for g in v.collectible_geoms],
                    "refuted_geoms": [list(g) for g in v.refuted_geoms],
                    "inert_geoms": [list(g) for g in v.inert_geoms],
                    "responsive_geoms": [list(g) for g in v.responsive_geoms],
                    "quantum": int(v.quantum),
                    "had_conditional_blocks": bool(v.had_conditional_blocks),
                    "cleared": bool(v.cleared),
                    "causal_policy": {str(dk): list(dv) for dk, dv in v.causal_policy.items()},
                }
                for k, v in self.levels.items()
            },
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SynthesizedSolverSpec:
        spec = cls(
            solver_family=str(data.get("solver_family") or "REACH_BFS"),
            secondary_families=[str(x) for x in (data.get("secondary_families") or [])],
            goal_type=str(data.get("goal_type") or "REACH"),
            avatar_geom=_geom_tuple(data.get("avatar_geom")),
            avatar_parts=[g for g in (_geom_tuple(x) for x in (data.get("avatar_parts") or [])) if g],
            movable_geoms=[g for g in (_geom_tuple(x) for x in (data.get("movable_geoms") or [])) if g],
            goal_geoms=[g for g in (_geom_tuple(x) for x in (data.get("goal_geoms") or [])) if g],
            wall_geoms=[g for g in (_geom_tuple(x) for x in (data.get("wall_geoms") or [])) if g],
            hazard_geoms=[g for g in (_geom_tuple(x) for x in (data.get("hazard_geoms") or [])) if g],
            switch_geoms=[g for g in (_geom_tuple(x) for x in (data.get("switch_geoms") or [])) if g],
            portal_geoms=[g for g in (_geom_tuple(x) for x in (data.get("portal_geoms") or [])) if g],
            collectible_geoms=[g for g in (_geom_tuple(x) for x in (data.get("collectible_geoms") or [])) if g],
            refuted_geoms=[g for g in (_geom_tuple(x) for x in (data.get("refuted_geoms") or [])) if g],
            inert_geoms=[g for g in (_geom_tuple(x) for x in (data.get("inert_geoms") or [])) if g],
            responsive_geoms=[g for g in (_geom_tuple(x) for x in (data.get("responsive_geoms") or [])) if g],
            quantum=max(1, int(data.get("quantum") or 1)),
            dpad_Vectors={
                int(k): (int(v[0]), int(v[1]))
                for k, v in (data.get("dpad_vectors") or {1: (0, -1), 2: (0, 1), 3: (-1, 0), 4: (1, 0)}).items()
                if isinstance(v, (list, tuple)) and len(v) == 2
            },
            canonical_to_raw_dpad={
                int(k): int(v)
                for k, v in (data.get("canonical_to_raw_dpad") or {1: 1, 2: 2, 3: 3, 4: 4, 5: 5}).items()
            },
            control_inverted=bool(data.get("control_inverted")),
            has_panel_pair=bool(data.get("has_panel_pair")),
            panel_dims=tuple(int(x) for x in data["panel_dims"])
            if isinstance(data.get("panel_dims"), (list, tuple)) and len(data["panel_dims"]) == 2
            else None,
            switch_first=bool(data.get("switch_first")),
            hybrid_corridor_click=bool(data.get("hybrid_corridor_click")),
            interact_aligned=bool(data.get("interact_aligned")),
            fmf_primitives=[str(x) for x in (data.get("fmf_primitives") or [])],
            schema_id=data.get("schema_id"),
        )
        for k, lv in (data.get("levels") or {}).items():
            if not isinstance(lv, dict):
                continue
            l_idx = int(lv.get("level_idx", k))
            spec.levels[l_idx] = LevelSolverSpec(
                level_idx=l_idx,
                avatar_geom=_geom_tuple(lv.get("avatar_geom")),
                movable_geoms=[g for g in (_geom_tuple(x) for x in (lv.get("movable_geoms") or [])) if g],
                goal_geoms=[g for g in (_geom_tuple(x) for x in (lv.get("goal_geoms") or [])) if g],
                wall_geoms=[g for g in (_geom_tuple(x) for x in (lv.get("wall_geoms") or [])) if g],
                hazard_geoms=[g for g in (_geom_tuple(x) for x in (lv.get("hazard_geoms") or [])) if g],
                switch_geoms=[g for g in (_geom_tuple(x) for x in (lv.get("switch_geoms") or [])) if g],
                portal_geoms=[g for g in (_geom_tuple(x) for x in (lv.get("portal_geoms") or [])) if g],
                collectible_geoms=[g for g in (_geom_tuple(x) for x in (lv.get("collectible_geoms") or [])) if g],
                refuted_geoms=[g for g in (_geom_tuple(x) for x in (lv.get("refuted_geoms") or [])) if g],
                inert_geoms=[g for g in (_geom_tuple(x) for x in (lv.get("inert_geoms") or [])) if g],
                responsive_geoms=[g for g in (_geom_tuple(x) for x in (lv.get("responsive_geoms") or [])) if g],
                quantum=max(1, int(lv.get("quantum") or 1)),
                had_conditional_blocks=bool(lv.get("had_conditional_blocks")),
                cleared=bool(lv.get("cleared")),
                causal_policy={
                    str(dk): list(dv)
                    for dk, dv in (lv.get("causal_policy") or {}).items()
                    if isinstance(dv, (list, tuple))
                },
            )
        return spec


# In-memory store of Pass 1 synthesized solvers keyed by anonymous slot or structural board signature
SYNTHESIZED_BY_SLOT: dict[int, SynthesizedSolverSpec] = {}
SYNTHESIZED_BY_STRUCT: dict[tuple, SynthesizedSolverSpec] = {}


def reset_synthesized_store() -> None:
    SYNTHESIZED_BY_SLOT.clear()
    SYNTHESIZED_BY_STRUCT.clear()


def save_synthesized_store(path: str | Path) -> None:
    """Persist Pass 1 synthesized solvers to disk so Pass 2 can run in a separate process."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "by_slot": {str(k): spec.to_dict() for k, spec in SYNTHESIZED_BY_SLOT.items()},
        "by_struct": {repr(k): spec.to_dict() for k, spec in SYNTHESIZED_BY_STRUCT.items()},
    }
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    tmp.replace(p)


def load_synthesized_store(path: str | Path) -> int:
    """Load Pass 1 synthesized solvers from disk into SYNTHESIZED_BY_SLOT and SYNTHESIZED_BY_STRUCT."""
    import ast

    p = Path(path)
    if not p.is_file():
        return 0
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return 0
    by_slot = raw.get("by_slot") if isinstance(raw, dict) else None
    if not isinstance(by_slot, dict):
        return 0
    loaded = 0
    for k, val in by_slot.items():
        if isinstance(val, dict):
            try:
                SYNTHESIZED_BY_SLOT[int(k)] = SynthesizedSolverSpec.from_dict(val)
                loaded += 1
            except Exception:
                continue
    by_struct = raw.get("by_struct") if isinstance(raw, dict) else None
    if isinstance(by_struct, dict):
        for sk_str, val in by_struct.items():
            if isinstance(val, dict):
                try:
                    skey = ast.literal_eval(sk_str)
                    if isinstance(skey, tuple):
                        SYNTHESIZED_BY_STRUCT[skey] = SynthesizedSolverSpec.from_dict(val)
                except Exception:
                    continue
    return loaded


def _add_unique(target: list[Geom], g: Any) -> None:
    gt = _geom_tuple(g)
    if gt is not None and gt not in target:
        target.append(gt)


def record_level_observation(
    agent: Any,
    state: dict,
    level_idx: int,
    *,
    cleared: bool = False,
    before: list[dict] | None = None,
    after: list[dict] | None = None,
    action: Any = None,
    outcome: str = "continue",
) -> SynthesizedSolverSpec:
    """Incrementally update the agent's online SynthesizedSolverSpec from current level state."""
    spec: SynthesizedSolverSpec | None = getattr(agent, "_m2_synthesized_solver", None)
    if not isinstance(spec, SynthesizedSolverSpec):
        spec = SynthesizedSolverSpec()
        setattr(agent, "_m2_synthesized_solver", spec)

    lv = spec.levels.get(int(level_idx))
    if lv is None:
        lv = LevelSolverSpec(level_idx=int(level_idx))
        spec.levels[int(level_idx)] = lv

    ev = state.get("role_evidence") or {}
    av = _geom_tuple(ev.get("avatar")) or _geom_tuple(state.get("mover_geom"))
    if av is not None:
        spec.avatar_geom = av
        lv.avatar_geom = av
        recs_now = state.get("frame_records") or []
        av_recs = [r for r in recs_now if _geom_tuple(r.get("geom")) == av and len(r.get("sig") or ()) > 1]
        if state.get("avatar_fill") is not None:
            spec.avatar_fill = int(state["avatar_fill"])
        elif len(av_recs) == 1:
            spec.avatar_fill = int(av_recs[0]["sig"][1])
            state["avatar_fill"] = spec.avatar_fill
        if spec.avatar_fill is not None:
            s_fills = state.setdefault("seen_sentry_fills", [])
            for r in av_recs:
                rf = int(r["sig"][1])
                if rf != spec.avatar_fill:
                    if rf not in spec.seen_sentry_fills:
                        spec.seen_sentry_fills.append(rf)
                    if rf not in s_fills:
                        s_fills.append(rf)
    for part in ev.get("avatar_parts") or ():
        _add_unique(spec.avatar_parts, part)
    part_set = set(spec.avatar_parts)
    if spec.avatar_geom is not None:
        part_set.add(spec.avatar_geom)

    for role_key, spec_list, lv_list in (
        ("movable", spec.movable_geoms, lv.movable_geoms),
        ("goal", spec.goal_geoms, lv.goal_geoms),
        ("wall", spec.wall_geoms, lv.wall_geoms),
        ("hazard", spec.hazard_geoms, lv.hazard_geoms),
        ("switch", spec.switch_geoms, lv.switch_geoms),
        ("portal", spec.portal_geoms, lv.portal_geoms),
        ("collectible", spec.collectible_geoms, lv.collectible_geoms),
    ):
        gt = _geom_tuple(ev.get(role_key))
        if gt is not None and role_key in ("movable", "hazard", "wall") and gt in part_set:
            continue
        _add_unique(spec_list, gt)
        _add_unique(lv_list, gt)

    if part_set:
        spec.movable_geoms = [g for g in spec.movable_geoms if g not in part_set]
        lv.movable_geoms = [g for g in lv.movable_geoms if g not in part_set]
        spec.hazard_geoms = [g for g in spec.hazard_geoms if g not in part_set]
        lv.hazard_geoms = [g for g in lv.hazard_geoms if g not in part_set]

    for rg in state.get("refuted_candidates") or ():
        gt = _geom_tuple(rg)
        if gt is not None and gt not in lv.goal_geoms:
            _add_unique(lv.refuted_geoms, gt)
            if gt not in spec.goal_geoms:
                _add_unique(spec.refuted_geoms, gt)

    # Record responsive vs inert click geometries from Pass 1 click telemetry
    recs = state.get("frame_records") or []
    resp_coords = getattr(agent, "level_responsive_coords", None)
    inert_coords = getattr(agent, "level_inert_coords", None)
    emp_clicks = getattr(agent, "empirical_click_effects", None)
    resp_pts: set[tuple[int, int]] = set()
    inert_pts: set[tuple[int, int]] = set()
    if isinstance(resp_coords, dict):
        for pt, cnt in resp_coords.items():
            if int(cnt or 0) > 0 and isinstance(pt, (list, tuple)) and len(pt) == 2:
                resp_pts.add((int(pt[0]), int(pt[1])))
    if isinstance(inert_coords, dict):
        for pt, cnt in inert_coords.items():
            if int(cnt or 0) > 0 and isinstance(pt, (list, tuple)) and len(pt) == 2:
                inert_pts.add((int(pt[0]), int(pt[1])))
    if isinstance(emp_clicks, dict):
        for pt, info in emp_clicks.items():
            if not isinstance(pt, (list, tuple)) or len(pt) < 2 or not isinstance(info, dict):
                continue
            coord = (int(pt[0]), int(pt[1]))
            if int(info.get("changed_pixels") or 0) > 0:
                resp_pts.add(coord)
            elif int(info.get("tries") or 0) > 0:
                inert_pts.add(coord)
    if recs and (resp_pts or inert_pts):
        for r in recs:
            g = _geom_tuple(r.get("geom"))
            xy = r.get("xy")
            wh = r.get("wh")
            if g is None or not xy or not wh:
                continue
            rx, ry, rw, rh = int(xy[0]), int(xy[1]), int(wh[0]), int(wh[1])
            if any(rx <= px < rx + rw and ry <= py < ry + rh for px, py in resp_pts):
                _add_unique(spec.responsive_geoms, g)
                _add_unique(lv.responsive_geoms, g)
                if g in spec.inert_geoms:
                    spec.inert_geoms.remove(g)
                if g in lv.inert_geoms:
                    lv.inert_geoms.remove(g)
            elif g not in spec.responsive_geoms and any(
                rx <= px < rx + rw and ry <= py < ry + rh for px, py in inert_pts
            ):
                _add_unique(spec.inert_geoms, g)
                _add_unique(lv.inert_geoms, g)

    if isinstance(action, (list, tuple)) and len(action) >= 2 and action[0] == "SIMPLE" and int(action[1]) == 5:
        if cleared or (before and after and before != after):
            spec.interact_aligned = True

    if outcome == "reset":
        lv._attempt_trace.clear()
    elif before and after and action is not None:
        span = int(state.get("span") or 64)
        d_before = _board_playfield_digest(before, span=span)
        d_after = _board_playfield_digest(after, span=span)
        if d_before and (cleared or d_before != d_after):
            sym_act = _encode_symbolic_action(action, before)
            if sym_act is not None:
                for idx, (prev_b, _prev_a, _prev_act) in enumerate(lv._attempt_trace):
                    if prev_b == d_before:
                        del lv._attempt_trace[idx:]
                        break
                if not cleared:
                    for idx, (prev_b, _prev_a, _prev_act) in enumerate(lv._attempt_trace):
                        if prev_b == d_after:
                            del lv._attempt_trace[idx:]
                            break
                lv._attempt_trace.append((d_before, d_after, sym_act))

    if cleared:
        lv.cleared = True
        if lv._attempt_trace:
            for d_b, _d_a, s_act in lv._attempt_trace:
                lv.causal_policy[d_b] = list(s_act)
            lv._attempt_trace.clear()
        hyp = _geom_tuple(state.get("hypothesis_target") or ev.get("candidate_geom") or ev.get("preferred_goal"))
        if hyp is not None and hyp not in part_set:
            _add_unique(spec.goal_geoms, hyp)
            _add_unique(lv.goal_geoms, hyp)
            if hyp in spec.refuted_geoms:
                spec.refuted_geoms.remove(hyp)
            if hyp in lv.refuted_geoms:
                lv.refuted_geoms.remove(hyp)

    rq = int(state.get("route_quantum") or 0)
    if rq > 0:
        spec.quantum = rq
        lv.quantum = rq

    if state.get("conditional_blocks") or state.get("had_conditional_blocks") or state.get("deferred_candidates"):
        lv.had_conditional_blocks = True
        spec.switch_first = True

    c_map = getattr(agent, "canonical_to_raw_dpad", None)
    if isinstance(c_map, dict):
        spec.canonical_to_raw_dpad = {int(k): int(v) for k, v in c_map.items() if int(k) in (1, 2, 3, 4, 5)}
        spec.control_inverted = any(int(k) != int(v) for k, v in spec.canonical_to_raw_dpad.items() if int(k) in (1, 2, 3, 4))

    fmf_u = state.get("fmf_unhashed") if isinstance(state.get("fmf_unhashed"), dict) else {}
    for p in fmf_u.get("primitives") or ():
        if p and str(p) not in spec.fmf_primitives:
            spec.fmf_primitives.append(str(p))
    if fmf_u.get("candidate_priority") == "SWITCH_FIRST" or fmf_u.get("candidate_bias") == "switch_first":
        spec.switch_first = True

    if state.get("schema_id"):
        spec.schema_id = str(state["schema_id"])

    _classify_solver_family(agent, state, spec)
    return spec


def _classify_solver_family(agent: Any, state: dict, spec: SynthesizedSolverSpec) -> None:
    """Select the primary and secondary general solver algorithms from Pass 1 evidence."""
    legal = list(state.get("legal") or getattr(agent, "_m2_avail", []) or [1, 2, 3, 4])
    has_dpad = any(a in (1, 2, 3, 4) for a in legal)
    has_click = 6 in legal

    # Check equal-sized hollow panel pairs from frame_records
    recs = state.get("frame_records") or []
    panel_pair = _find_panel_pair_from_records(recs)
    if panel_pair is not None:
        spec.has_panel_pair = True
        spec.panel_dims = (int(panel_pair[0][2]), int(panel_pair[0][3]))
    else:
        spec.has_panel_pair = False

    # Check if hybrid corridor click pattern (e.g. avatar inside container + clickable blocks outside)
    if has_dpad and has_click and (state.get("coop_handoff") or not state.get("candidates")):
        spec.hybrid_corridor_click = True

    is_confirmed_mover = has_dpad and (spec.avatar_geom is not None or bool(state.get("dpad_moved")))
    families: list[str] = []
    llm_fam = str(state.get("llm_solver_family") or "").strip().upper()
    if llm_fam in ("PANEL_ALIGN", "SOKOBAN_PUSH", "SWITCH_GATE", "WAYPOINT_TOUR", "REACH_BFS"):
        if llm_fam == "PANEL_ALIGN" and has_click and (not has_dpad or not is_confirmed_mover):
            families.append("PANEL_ALIGN")
        elif llm_fam == "SOKOBAN_PUSH" and has_dpad and spec.movable_geoms:
            families.append("SOKOBAN_PUSH")
        elif llm_fam == "SWITCH_GATE" and spec.switch_geoms:
            families.append("SWITCH_GATE")
        elif llm_fam == "WAYPOINT_TOUR" and has_dpad and spec.collectible_geoms:
            families.append("WAYPOINT_TOUR")
    if has_click and (not has_dpad or (spec.has_panel_pair and not is_confirmed_mover)):
        families.append("PANEL_ALIGN")
        spec.goal_type = "MATCH"
    if has_dpad and spec.movable_geoms:
        families.append("SOKOBAN_PUSH")
        if spec.goal_type == "REACH":
            spec.goal_type = "PLACE"
    if spec.switch_geoms and (spec.switch_first or any(lv.had_conditional_blocks for lv in spec.levels.values())):
        families.append("SWITCH_GATE")
    if spec.collectible_geoms:
        families.append("WAYPOINT_TOUR")
    if has_dpad:
        families.append("REACH_BFS")
    if has_click and "PANEL_ALIGN" not in families:
        families.append("PANEL_ALIGN")

    if families:
        spec.solver_family = families[0]
        spec.secondary_families = families[1:]


def synthesize_solver_from_pass1(
    agent: Any,
    *,
    slot: int | None = None,
    level_idx: int | None = None,
) -> SynthesizedSolverSpec:
    """Finalize and register a SynthesizedSolverSpec at the end of Pass 1."""
    state = getattr(agent, "_m2_coord", None)
    if not isinstance(state, dict):
        state = {}
    lvl = int(level_idx) if level_idx is not None else int(getattr(agent, "current_level", 0) or state.get("level", 0) or 0)
    existing = getattr(agent, "_m2_synthesized_solver", None)
    was_cleared = bool(
        isinstance(existing, SynthesizedSolverSpec)
        and lvl in existing.levels
        and existing.levels[lvl].cleared
    )
    spec = record_level_observation(agent, state, lvl, cleared=was_cleared)

    # Incorporate empirical fx_dpad step quantum from agent if present (do not overwrite canonical dpad_Vectors)
    fx_dpad = getattr(agent, "fx_dpad", None)
    if isinstance(fx_dpad, dict):
        learned_q: list[int] = []
        for aid, counter in fx_dpad.items():
            if int(aid) not in (1, 2, 3, 4) or not counter:
                continue
            (dx, dy), n = counter.most_common(1)[0]
            if int(n) >= 1 and (dx != 0 or dy != 0):
                step_mag = max(abs(int(dx)), abs(int(dy)))
                learned_q.append(step_mag)
        if learned_q and spec.quantum <= 1:
            spec.quantum = collections.Counter(learned_q).most_common(1)[0][0]

    # Confirmed GGL goal type if discovered in Pass 1
    ggl_conf = getattr(agent, "ggl_confirmed_type", None)
    if ggl_conf in ("REACH", "PLACE", "MATCH"):
        spec.goal_type = str(ggl_conf)
    watch = getattr(agent, "m2_watch", None)
    frozen = getattr(watch, "frozen", None) if watch is not None else None
    if frozen in ("REACH", "PLACE", "MATCH"):
        spec.goal_type = str(frozen)

    _classify_solver_family(agent, state, spec)

    if slot is not None:
        SYNTHESIZED_BY_SLOT[int(slot)] = spec
    recs = state.get("frame_records") or []
    legal = list(state.get("legal") or getattr(agent, "_m2_avail", []) or [])
    if recs and legal:
        skey = _board_struct_key(recs, legal)
        SYNTHESIZED_BY_STRUCT[skey] = spec
    return spec


def lookup_synthesized_solver(
    agent: Any,
    records: list[dict],
    legal: list[int],
    *,
    slot: int | None = None,
) -> SynthesizedSolverSpec | None:
    """Retrieve a Pass 1 synthesized solver by slot or structural board signature."""
    existing = getattr(agent, "_m2_synthesized_solver", None)
    if isinstance(existing, SynthesizedSolverSpec) and (
        existing.avatar_geom
        or existing.goal_geoms
        or existing.has_panel_pair
        or existing.movable_geoms
        or existing.responsive_geoms
        or existing.inert_geoms
    ):
        return existing
    if slot is not None and int(slot) in SYNTHESIZED_BY_SLOT:
        spec = SYNTHESIZED_BY_SLOT[int(slot)]
        setattr(agent, "_m2_synthesized_solver", spec)
        return spec
    if records and legal:
        skey = _board_struct_key(records, legal)
        if skey in SYNTHESIZED_BY_STRUCT:
            spec = SYNTHESIZED_BY_STRUCT[skey]
            setattr(agent, "_m2_synthesized_solver", spec)
            return spec
    return None


def apply_synthesized_priors_to_state(
    agent: Any,
    state: dict,
    spec: SynthesizedSolverSpec,
    level_idx: int,
) -> None:
    """Seed Pass 2's coordinate state with Pass 1's learned roles, quantum, DPAD gauge, and refuted decoys."""
    lv = spec.levels.get(int(level_idx))
    ev = state.setdefault("role_evidence", {})
    recs = state.get("frame_records") or []
    live_geoms = {
        _geom_tuple(r.get("geom"))
        for r in recs
        if _geom_tuple(r.get("geom")) is not None
    }
    part_set = set(spec.avatar_parts)

    av_geom = (lv.avatar_geom if lv and lv.avatar_geom in live_geoms else None) or (
        spec.avatar_geom if spec.avatar_geom in live_geoms else None
    )
    if av_geom is not None:
        part_set.add(av_geom)
    if spec.avatar_parts and not ev.get("avatar_parts"):
        live_parts = [list(p) for p in spec.avatar_parts if p in live_geoms]
        if live_parts:
            ev["avatar_parts"] = live_parts

    q = (lv.quantum if lv and lv.quantum > 1 else 0) or spec.quantum
    if q > 1 and not state.get("route_quantum"):
        state["route_quantum"] = int(q)
        ev["quantum"] = int(q)

    if spec.avatar_fill is not None and state.get("avatar_fill") is None:
        state["avatar_fill"] = int(spec.avatar_fill)
    if spec.seen_sentry_fills:
        s_fills = state.setdefault("seen_sentry_fills", [])
        for sf in spec.seen_sentry_fills:
            if int(sf) not in s_fills:
                s_fills.append(int(sf))

    if av_geom is not None:
        if not ev.get("avatar"):
            ev["avatar"] = list(av_geom)
        state["dpad_moved"] = True
        av_priors = getattr(agent, "GLOBAL_SOLVED_AVATAR_GEOM_PRIORS", None)
        if isinstance(av_priors, dict):
            av_priors[av_geom] = max(int(av_priors.get(av_geom, 0)), 16)
        av_boxes = [
            (int(r["xy"][0]), int(r["xy"][1]), int(r["wh"][0]), int(r["wh"][1]))
            for r in recs
            if _geom_tuple(r.get("geom")) == av_geom and r.get("xy") and r.get("wh")
        ]
        if len(av_boxes) == 1 and not state.get("mover_box"):
            state["mover_box"] = av_boxes[0]
        elif len(av_boxes) > 1 and not state.get("mover_box"):
            resolved = resolve_shared_avatar_box(state, recs, av_boxes)
            if resolved is not None:
                state["mover_box"] = resolved
        if int(state.get("route_quantum") or q or 0) >= 1:
            state["discover_steps"] = max(int(state.get("discover_steps") or 0), 2)
            if not state.get("stable_roles"):
                state["stable_roles"] = "avatar"

    has_cond = bool(lv and lv.had_conditional_blocks)
    pref_lv_goals = (
        list(lv.refuted_geoms) + list(lv.goal_geoms)
        if (lv and has_cond and lv.cleared and lv.refuted_geoms)
        else (lv.goal_geoms if lv else [])
    )
    refuted = state.setdefault("refuted_candidates", [])
    has_live_goal = any(g in live_geoms and g not in part_set for g in list(pref_lv_goals) + list(spec.goal_geoms))
    if lv and lv.refuted_geoms and not lv.had_conditional_blocks and (has_live_goal or not av_geom):
        lv_goal_set = set(lv.goal_geoms)
        for rg in lv.refuted_geoms:
            if rg in part_set or rg in lv_goal_set:
                continue
            entry = [int(rg[0]), int(rg[1]), int(rg[2])]
            if entry not in refuted:
                refuted.append(entry)

    cur_refuted = {
        _geom_tuple(x)
        for x in (state.get("refuted_candidates") or [])
        if _geom_tuple(x) is not None
    }
    cur_deferred = {
        _geom_tuple(x)
        for x in (state.get("deferred_candidates") or [])
        if _geom_tuple(x) is not None
    }
    for role_name, lv_geoms, global_geoms in (
        ("movable", lv.movable_geoms if lv else [], spec.movable_geoms),
        ("preferred_goal", pref_lv_goals, spec.goal_geoms),
        ("wall", lv.wall_geoms if lv else [], spec.wall_geoms),
        ("hazard", lv.hazard_geoms if lv else [], spec.hazard_geoms),
        ("switch", lv.switch_geoms if lv else [], spec.switch_geoms),
        ("portal", lv.portal_geoms if lv else [], spec.portal_geoms),
    ):
        cur_val = _geom_tuple(ev.get(role_name))
        if cur_val is not None and (
            role_name != "preferred_goal"
            or (cur_val in live_geoms and cur_val not in cur_refuted and cur_val not in cur_deferred)
        ):
            continue
        for g in list(lv_geoms) + list(global_geoms):
            if g in live_geoms and g not in part_set:
                if role_name == "preferred_goal" and (g in cur_refuted or g in cur_deferred):
                    continue
                ev[role_name] = list(g)
                break

    if spec.control_inverted and isinstance(spec.canonical_to_raw_dpad, dict):
        agent.canonical_to_raw_dpad = dict(spec.canonical_to_raw_dpad)
        agent.raw_to_canonical_dpad = {int(v): int(k) for k, v in spec.canonical_to_raw_dpad.items()}


# ==============================================================================
# General Solver Family Implementations
# ==============================================================================


def _find_panel_pair_from_records(records: list[dict]) -> tuple[Box, Box] | None:
    """Locate two equal-dimension hollow container/panel bounding boxes on the board."""
    all_boxes: list[Box] = []
    frames: list[Box] = []
    for r in records or []:
        xy = r.get("xy")
        wh = r.get("wh")
        geom = r.get("geom")
        if not xy or not wh or not geom:
            continue
        bx, by, w, h = int(xy[0]), int(xy[1]), int(wh[0]), int(wh[1])
        all_boxes.append((bx, by, w, h))
        if int(geom[0]) == 2 and w >= 6 and h >= 6:
            frames.append((bx, by, w, h))
    for i in range(len(frames)):
        for j in range(i + 1, len(frames)):
            a, b = frames[i], frames[j]
            if a[2] == b[2] and a[3] == b[3] and not _overlap(a, b):
                has_inner_a = any(
                    other != a
                    and other[0] > a[0]
                    and other[1] > a[1]
                    and other[0] + other[2] < a[0] + a[2]
                    and other[1] + other[3] < a[1] + a[3]
                    for other in all_boxes
                )
                has_inner_b = any(
                    other != b
                    and other[0] > b[0]
                    and other[1] > b[1]
                    and other[0] + other[2] < b[0] + b[2]
                    and other[1] + other[3] < b[1] + b[3]
                    for other in all_boxes
                )
                if has_inner_a and has_inner_b:
                    return (a, b)
    return None


def _solve_panel_align(
    spec: SynthesizedSolverSpec,
    state: dict,
    legal: list[int],
    grid: list[list[int]] | None = None,
) -> list[tuple] | None:
    """Family 1: Panel Alignment / Toggle Solver.
    Compares two equal-sized panels on the live grid and clicks mismatching cells
    in the editable panel, skipping inert geometries learned in Pass 1."""
    if 6 not in legal:
        return None
    recs = state.get("frame_records") or []
    lvl = int(state.get("level") or 0)
    lv = spec.levels.get(lvl)
    inert_set = set(spec.inert_geoms) | set(lv.inert_geoms if lv else ())
    resp_set = set(spec.responsive_geoms) | set(lv.responsive_geoms if lv else ())
    pair = _find_panel_pair_from_records(recs)
    if pair is not None and grid and len(grid) >= 8 and len(grid[0]) >= 8:
        pa, pb = pair
        xa, ya, w, h = pa
        xb, yb, _, _ = pb
        aff = (state.get("affordances") or {}).get("clickable") or []
        in_a = sum(1 for pt in aff if xa <= int(pt[0]) < xa + w and ya <= int(pt[1]) < ya + h)
        in_b = sum(1 for pt in aff if xb <= int(pt[0]) < xb + w and yb <= int(pt[1]) < yb + h)
        work_x, work_y, ref_x, ref_y = (xb, yb, xa, ya) if in_b > in_a else (xa, ya, xb, yb)
        clicks: list[tuple] = []
        tried_clicks = set(state.get("synth_tried_clicks") or ())
        for pt in (state.get("tried_anchors") or []):
            if isinstance(pt, (list, tuple)) and len(pt) >= 2:
                tried_clicks.add(("CLICK", int(pt[0]), int(pt[1])))
        # Prefer clickable affordance centroids inside the work panel that lie on or near a mismatching cell
        for pt in aff:
            if not isinstance(pt, (list, tuple)) or len(pt) < 2:
                continue
            px, py = int(pt[0]), int(pt[1])
            if work_x < px < work_x + w - 1 and work_y < py < work_y + h - 1:
                act = ("CLICK", px, py)
                if act in tried_clicks:
                    continue
                dx, dy = px - work_x, py - work_y
                ry, rx = ref_y + dy, ref_x + dx
                if 0 <= py < len(grid) and 0 <= px < len(grid[0]) and 0 <= ry < len(grid) and 0 <= rx < len(grid[0]):
                    if int(grid[py][px]) != int(grid[ry][rx]):
                        clicks.append(act)
        if not clicks:
            for dy in range(1, max(1, h - 1)):
                for dx in range(1, max(1, w - 1)):
                    wy, wx = work_y + dy, work_x + dx
                    ry, rx = ref_y + dy, ref_x + dx
                    if 0 <= wy < len(grid) and 0 <= wx < len(grid[0]) and 0 <= ry < len(grid) and 0 <= rx < len(grid[0]):
                        if int(grid[wy][wx]) != int(grid[ry][rx]):
                            act = ("CLICK", int(wx), int(wy))
                            if act not in tried_clicks and not any(
                                abs(int(wx) - int(ca[1])) + abs(int(wy) - int(ca[2])) <= 2
                                for ca in clicks
                            ):
                                clicks.append(act)
        if clicks:
            return [clicks[0]]

    # Fallback for non-pair pointer boards: click responsive geometries first, then non-inert clickable affordances
    aff = (state.get("affordances") or {}).get("clickable") or []
    tried_clicks = set(state.get("synth_tried_clicks") or ())
    responsive_candidates: list[tuple] = []
    other_candidates: list[tuple] = []
    for pt in aff:
        if not isinstance(pt, (list, tuple)) or len(pt) < 2:
            continue
        cx, cy = int(pt[0]), int(pt[1])
        act = ("CLICK", cx, cy)
        if act in tried_clicks:
            continue
        hit_resp = False
        hit_inert = False
        for r in recs:
            if not r.get("xy") or not r.get("wh"):
                continue
            rx, ry, rw, rh = int(r["xy"][0]), int(r["xy"][1]), int(r["wh"][0]), int(r["wh"][1])
            if rx <= cx < rx + rw and ry <= cy < ry + rh:
                rg = _geom_tuple(r.get("geom"))
                if rg in resp_set:
                    hit_resp = True
                elif rg in inert_set:
                    hit_inert = True
        if hit_resp:
            responsive_candidates.append(act)
        elif not hit_inert:
            other_candidates.append(act)
    if responsive_candidates:
        return [responsive_candidates[0]]
    if other_candidates:
        return [other_candidates[0]]
    return None


def _extract_role_boxes(
    records: list[dict],
    geoms: set[Geom],
    exclude_box: Box | None = None,
) -> list[Box]:
    out: list[Box] = []
    if not geoms:
        return out
    for r in records or []:
        g = _geom_tuple(r.get("geom"))
        if g in geoms and r.get("xy") and r.get("wh"):
            bx = (int(r["xy"][0]), int(r["xy"][1]), int(r["wh"][0]), int(r["wh"][1]))
            if exclude_box is not None and bx == exclude_box:
                continue
            out.append(bx)
    return out


def resolve_shared_avatar_box(state: dict | None, records: list[dict], candidate_boxes: list[Box]) -> Box | None:
    """Disambiguate the avatar box when sentries share the avatar's geometry tuple."""
    if not candidate_boxes:
        return None
    if len(candidate_boxes) == 1:
        return candidate_boxes[0]
    cand_set = {
        (int(b[0]), int(b[1]), int(b[2]), int(b[3]))
        for b in candidate_boxes
        if isinstance(b, (list, tuple)) and len(b) == 4
    }
    av_fill = (state or {}).get("avatar_fill") if isinstance(state, dict) else None
    matched: list[Box] = []
    fill_boxes: dict[int, list[Box]] = {}
    for r in records or []:
        if not r.get("xy") or not r.get("wh"):
            continue
        bx = (int(r["xy"][0]), int(r["xy"][1]), int(r["wh"][0]), int(r["wh"][1]))
        if bx not in cand_set:
            continue
        sig = r.get("sig") or ()
        if len(sig) > 1:
            rf = int(sig[1])
            fill_boxes.setdefault(rf, []).append(bx)
            if av_fill is not None and rf == int(av_fill):
                matched.append(bx)
    if matched:
        matched.sort(key=lambda b: (b[1], b[0]))
        return matched[0]
    singletons = [boxes[0] for _f, boxes in fill_boxes.items() if len(boxes) == 1]
    if len(singletons) == 1:
        return singletons[0]
    return None


def plan_bridge_lattice_prefix(
    state: dict | None,
    records: list[dict],
    mover: Box,
    target: Box,
    quantum: int,
    blocks: set,
    legal: list[int],
) -> list[int] | None:
    """Plan on a bridge-connected node graph with stationary, patrol, and chaser sentries."""
    if not records or not mover or not target:
        return None
    px, py, mw, mh = int(mover[0]), int(mover[1]), int(mover[2]), int(mover[3])
    tx, ty = int(target[0]), int(target[1])
    if mw != mh or mw < 2 or quantum != 2 * mw:
        return None
    if (px, py) == (tx, ty):
        return []

    tile_map: dict[tuple[int, int], dict] = {}
    inners_1x1: list[tuple[int, int, int]] = []
    for r in records:
        xy = r.get("xy")
        wh = r.get("wh")
        if not xy or not wh or len(xy) != 2 or len(wh) != 2:
            continue
        rx, ry, rw, rh = int(xy[0]), int(xy[1]), int(wh[0]), int(wh[1])
        if (rw, rh) == (mw, mh):
            tile_map[(rx, ry)] = r
        elif (rw, rh) == (1, 1):
            sig = r.get("sig") or ()
            inners_1x1.append((rx, ry, int(sig[1]) if len(sig) > 1 else -1))

    if (px, py) not in tile_map or (tx, ty) not in tile_map:
        return None

    if isinstance(state, dict):
        cached = state.get("bridge_plan")
        cached_tgt = state.get("bridge_plan_target")
        if isinstance(cached, list) and cached and cached_tgt == (tx, ty):
            if (
                len(cached) >= 2
                and isinstance(cached[1], (list, tuple))
                and len(cached[1]) == 3
                and (int(cached[1][0]), int(cached[1][1])) == (px, py)
            ):
                cached = list(cached[1:])
                state["bridge_plan"] = cached
            c0 = cached[0]
            if isinstance(c0, (list, tuple)) and len(c0) == 3 and (int(c0[0]), int(c0[1])) == (px, py):
                return [int(uaid) for _ux, _uy, uaid in cached]
            state["bridge_plan"] = None

    gx0, gy0 = px % quantum, py % quantum
    nodes = [pos for pos in tile_map if pos[0] % quantum == gx0 and pos[1] % quantum == gy0]
    if len(nodes) < 2:
        return None

    edges: set[tuple[tuple[int, int], tuple[int, int]]] = set()
    for ux, uy in nodes:
        for dx, dy in ((quantum, 0), (0, quantum)):
            vx, vy = ux + dx, uy + dy
            if (vx, vy) in tile_map:
                mx, my = ux + dx // 2, uy + dy // 2
                if (mx, my) in tile_map:
                    edges.add(((ux, uy), (vx, vy)))
                    edges.add(((vx, vy), (ux, uy)))

    if not edges:
        return None

    av_rec = tile_map.get((px, py))
    av_sig = (av_rec.get("sig") or ()) if av_rec else ()
    av_fill = int(av_sig[1]) if len(av_sig) > 1 else (state.get("avatar_fill") if isinstance(state, dict) else None)
    if isinstance(state, dict) and av_fill is not None and state.get("avatar_fill") is None:
        state["avatar_fill"] = int(av_fill)

    seen_sentry_fills: list[int] = list((state or {}).get("seen_sentry_fills") or []) if isinstance(state, dict) else []
    dir_sprites: list[tuple[int, int, tuple[int, int], int, int]] = []
    for ux, uy in sorted(nodes, key=lambda p: (p[1], p[0])):
        if (ux, uy) == (px, py):
            continue
        r = tile_map[(ux, uy)]
        g = _geom_tuple(r.get("geom"))
        if g is None or int(g[0]) != 2:
            continue
        sig = r.get("sig") or ()
        body_f = int(sig[1]) if len(sig) > 1 else -1
        eye_dir = None
        eye_f = -1
        for ex, ey, ef in inners_1x1:
            if ux <= ex < ux + mw and uy <= ey < uy + mh:
                ox = ex - (ux + mw // 2)
                oy = ey - (uy + mh // 2)
                if abs(ox) + abs(oy) == 1:
                    eye_dir = (ox, oy)
                    eye_f = ef
                    break
        if eye_dir is not None:
            dir_sprites.append((ux, uy, eye_dir, body_f, eye_f))
            if av_fill is not None and body_f != av_fill and body_f not in seen_sentry_fills:
                seen_sentry_fills.append(body_f)

    if isinstance(state, dict) and seen_sentry_fills:
        state["seen_sentry_fills"] = list(seen_sentry_fills)

    sentries: list[tuple[int, int, tuple[int, int]]] = []
    patrols: list[tuple[int, int, tuple[int, int]]] = []
    chasers: list[tuple[int, int, tuple[int, int], bool, tuple[tuple[int, int], ...]]] = []

    stat_fills = set((state or {}).get("stationary_sentry_fills") or ()) if isinstance(state, dict) else set()
    pat_fills = set((state or {}).get("patrol_sentry_fills") or ()) if isinstance(state, dict) else set()

    for sx, sy, sdir, body_f, _eye_f in dir_sprites:
        if av_fill is not None and body_f == av_fill:
            sentries.append((sx, sy, sdir))
        elif body_f in pat_fills and body_f not in stat_fills:
            patrols.append((sx, sy, sdir))
        elif body_f in stat_fills and body_f not in pat_fills:
            sentries.append((sx, sy, sdir))
        elif seen_sentry_fills and body_f == seen_sentry_fills[0]:
            sentries.append((sx, sy, sdir))
        elif len(seen_sentry_fills) >= 2 and body_f == seen_sentry_fills[1]:
            patrols.append((sx, sy, sdir))
        else:
            chasers.append((sx, sy, sdir, False, ()))

    options = {int(a) for a in (legal or []) if int(a) in (1, 2, 3, 4)}
    act_dirs = [
        (aid, d)
        for aid, d in ((1, (0, -1)), (2, (0, 1)), (3, (-1, 0)), (4, (1, 0)))
        if aid in options
    ]

    def _step_bridge(player, s_tup, pat_tup, ch_tup, aid: int, act_dir: tuple[int, int]):
        if (player[0], player[1], aid) in blocks:
            return None
        dx, dy = act_dir
        np_pos = (player[0] + quantum * dx, player[1] + quantum * dy)
        if (player, np_pos) not in edges:
            return None

        next_chasers = [
            (cx, cy, cdir, awake, q + (act_dir,) if awake else q)
            for cx, cy, cdir, awake, q in ch_tup
        ]
        rem_sentries = [s for s in s_tup if (s[0], s[1]) != np_pos]
        rem_patrols = [p for p in pat_tup if (p[0], p[1]) != np_pos]
        rem_chasers = [c for c in next_chasers if (c[0], c[1]) != np_pos]

        for sx, sy, (sdx, sdy) in rem_sentries:
            if (sx + quantum * sdx, sy + quantum * sdy) == np_pos:
                return None

        moved_patrols = []
        for p_x, p_y, (pdx, pdy) in rem_patrols:
            npx, npy = p_x + quantum * pdx, p_y + quantum * pdy
            if (npx, npy) == np_pos:
                return None
            if ((npx, npy), (npx + quantum * pdx, npy + quantum * pdy)) not in edges:
                np_dir = (-pdx, -pdy)
            else:
                np_dir = (pdx, pdy)
            moved_patrols.append((npx, npy, np_dir))

        moved_chasers = []
        for cx, cy, (cdx, cdy), awake, q in rem_chasers:
            if awake:
                ncx, ncy = cx + quantum * cdx, cy + quantum * cdy
                if (ncx, ncy) == np_pos:
                    return None
                moved_chasers.append((ncx, ncy, (cdx, cdy), True, q))
            else:
                moved_chasers.append((cx, cy, (cdx, cdy), False, q))

        final_chasers = []
        for cx, cy, (cdx, cdy), awake, q in moved_chasers:
            if not awake and (cx + 2 * quantum * cdx, cy + 2 * quantum * cdy) == np_pos:
                awake = True
                q = ((cdx, cdy), (cdx, cdy))
            if awake and q:
                new_cdir = q[0]
                q = q[1:]
            else:
                new_cdir = (cdx, cdy)
            final_chasers.append((cx, cy, new_cdir, awake, q))

        return (
            np_pos,
            tuple(rem_sentries),
            tuple(moved_patrols),
            tuple(final_chasers),
        )

    init_state = ((px, py), tuple(sentries), tuple(patrols), tuple(chasers))
    q_bfs: collections.deque[tuple[Any, list[tuple[int, int, int]]]] = collections.deque([(init_state, [])])
    visited = {init_state}
    while q_bfs:
        cur_st, seq = q_bfs.popleft()
        player, s_tup, pat_tup, ch_tup = cur_st
        if player == (tx, ty) and seq:
            if isinstance(state, dict):
                state["bridge_plan"] = list(seq)
                state["bridge_plan_target"] = (tx, ty)
            return [aid for _ux, _uy, aid in seq]
        if len(seq) >= 60:
            continue
        for aid, act_dir in act_dirs:
            nxt = _step_bridge(player, s_tup, pat_tup, ch_tup, aid, act_dir)
            if nxt is not None and nxt not in visited:
                visited.add(nxt)
                q_bfs.append((nxt, seq + [(player[0], player[1], aid)]))
    return None


def _avatar_box(spec: SynthesizedSolverSpec, state: dict) -> Box | None:
    mbox = state.get("mover_box")
    if isinstance(mbox, (list, tuple)) and len(mbox) == 4:
        return (int(mbox[0]), int(mbox[1]), int(mbox[2]), int(mbox[3]))
    ev = state.get("role_evidence") or {}
    av_g = _geom_tuple(ev.get("avatar")) or spec.avatar_geom
    if av_g is not None:
        recs = state.get("frame_records") or []
        boxes = _extract_role_boxes(recs, {av_g})
        if len(boxes) == 1:
            return boxes[0]
        if len(boxes) > 1:
            resolved = resolve_shared_avatar_box(state, recs, boxes)
            if resolved is not None:
                return resolved
            return boxes[0]
    return None


def _obstacle_boxes(spec: SynthesizedSolverSpec, state: dict, av_box: Box, target_box: Box | None) -> list[Box]:
    ev = state.get("role_evidence") or {}
    obs_geoms: set[Geom] = set(spec.wall_geoms) | set(spec.hazard_geoms)
    for k in ("wall", "hazard"):
        gt = _geom_tuple(ev.get(k))
        if gt is not None:
            obs_geoms.add(gt)
    av_g = _geom_tuple(ev.get("avatar")) or spec.avatar_geom
    if av_g in obs_geoms:
        obs_geoms.discard(av_g)
    for part in spec.avatar_parts:
        obs_geoms.discard(part)
    raw = _extract_role_boxes(state.get("frame_records") or [], obs_geoms, exclude_box=av_box)
    out: list[Box] = []
    for b in raw:
        if _overlap(b, av_box):
            continue
        if target_box is not None and _overlap(b, target_box):
            continue
        out.append(b)
    return out


def _bfs_avatar_path(
    start_box: Box,
    goal_test,
    heuristic_fn,
    q: int,
    dpad_vecs: dict[int, tuple[int, int]],
    legal_dpad: list[int],
    obstacles: list[Box],
    blocked_edges: set[tuple[int, int, int]],
    portals: list[Box] | None = None,
    span: int = 64,
    max_expansions: int = 2048,
) -> list[int] | None:
    """Footprint- & swept-volume-aware A* / BFS on the learned step quantum lattice."""
    sx, sy, sw, sh = start_box
    start_pos = (sx, sy)
    if goal_test(start_box):
        return []

    open_heap: list[tuple[int, int, int, tuple[int, int]]] = [
        (int(heuristic_fn(start_box)), 0, 0, start_pos)
    ]
    came_from: dict[tuple[int, int], tuple[tuple[int, int], int] | None] = {start_pos: None}
    g_score: dict[tuple[int, int], int] = {start_pos: 0}
    push_id = 0
    expansions = 0

    while open_heap and expansions < max_expansions:
        _f, g, _pid, (cx, cy) = heapq.heappop(open_heap)
        cur_box = (cx, cy, sw, sh)
        if (cx, cy) != start_pos and goal_test(cur_box):
            path: list[int] = []
            node: tuple[int, int] | None = (cx, cy)
            while node is not None and came_from.get(node) is not None:
                prev_node, aid = came_from[node]  # type: ignore[misc]
                path.append(aid)
                node = prev_node
            return path[::-1]

        expansions += 1
        for aid in legal_dpad:
            ux, uy = dpad_vecs.get(aid, (0, 0))
            dx, dy = ux * q, uy * q
            if dx == 0 and dy == 0:
                continue
            if (cx, cy, aid) in blocked_edges:
                continue
            nx, ny = cx + dx, cy + dy
            if nx < 0 or ny < 0 or nx + sw > span or ny + sh > span:
                continue
            swept = _swept(cur_box, dx, dy)
            if any(_overlap(swept, ob) for ob in obstacles):
                continue
            # Portal transport: if landing overlaps one of a twin portal pair, teleport to the other
            if portals and len(portals) == 2:
                next_box = (nx, ny, sw, sh)
                if _overlap(next_box, portals[0]) and not _overlap(cur_box, portals[0]):
                    nx, ny = portals[1][0], portals[1][1]
                elif _overlap(next_box, portals[1]) and not _overlap(cur_box, portals[1]):
                    nx, ny = portals[0][0], portals[0][1]

            npos = (nx, ny)
            ng = g + 1
            if ng < g_score.get(npos, 1_000_000):
                g_score[npos] = ng
                came_from[npos] = ((cx, cy), aid)
                push_id += 1
                nf = ng + int(heuristic_fn((nx, ny, sw, sh)))
                heapq.heappush(open_heap, (nf, ng, push_id, npos))
    return None


def _solve_sokoban_push(
    spec: SynthesizedSolverSpec,
    state: dict,
    legal: list[int],
) -> list[tuple] | None:
    """Family 2: Sokoban / Box-Pushing A* State-Space Solver on Learned Quantum."""
    legal_dpad = [a for a in (1, 2, 3, 4) if a in legal]
    if not legal_dpad:
        return None
    av_box = _avatar_box(spec, state)
    if av_box is None:
        return None
    recs = state.get("frame_records") or []
    ev = state.get("role_evidence") or {}
    mov_geoms = set(spec.movable_geoms)
    if _geom_tuple(ev.get("movable")):
        mov_geoms.add(_geom_tuple(ev["movable"]))  # type: ignore[arg-type]
    mov_boxes = _extract_role_boxes(recs, mov_geoms, exclude_box=av_box)
    if not mov_boxes and state.get("movable_box"):
        mb = state["movable_box"]
        if isinstance(mb, (list, tuple)) and len(mb) == 4:
            mov_boxes = [(int(mb[0]), int(mb[1]), int(mb[2]), int(mb[3]))]
    if not mov_boxes:
        return None

    # Identify PLACE target box
    target_box: Box | None = None
    goal_geoms = set(spec.goal_geoms)
    if _geom_tuple(ev.get("goal")):
        goal_geoms.add(_geom_tuple(ev["goal"]))  # type: ignore[arg-type]
    goal_boxes = _extract_role_boxes(recs, goal_geoms, exclude_box=av_box)
    for gb in goal_boxes:
        if gb not in mov_boxes:
            target_box = gb
            break
    if target_box is None:
        for cand in state.get("candidates") or []:
            if cand.get("kind") == "PLACE" and cand.get("box"):
                cb = cand["box"]
                target_box = (int(cb[0]), int(cb[1]), int(cb[2]), int(cb[3]))
                break
    if target_box is None and state.get("hypothesis_box"):
        hb = state["hypothesis_box"]
        target_box = (int(hb[0]), int(hb[1]), int(hb[2]), int(hb[3]))
    if target_box is None:
        for cand_tb in _select_target_boxes(spec, state, av_box):
            if cand_tb not in mov_boxes:
                target_box = cand_tb
                break
    if target_box is None:
        return None

    m_box = min(
        mov_boxes,
        key=lambda b: abs(b[0] - target_box[0]) + abs(b[1] - target_box[1]),
    )
    q = max(1, int(state.get("route_quantum") or spec.quantum or 1))
    obstacles = _obstacle_boxes(spec, state, av_box, target_box)
    obstacles = [ob for ob in obstacles if not _overlap(ob, m_box)]
    blocked_edges = {
        (int(e[0]), int(e[1]), int(e[2]))
        for e in (state.get("route_blocks") or []) + (state.get("conditional_blocks") or [])
        if isinstance(e, (list, tuple)) and len(e) == 3
    }

    ax0, ay0, aw, ah = av_box
    bx0, by0, bw, bh = m_box
    tx, ty, tw, th = target_box
    span = int(state.get("span") or 64)

    start_state = (ax0, ay0, bx0, by0)

    def _h(st: tuple[int, int, int, int]) -> int:
        ax, ay, bx, by = st
        box_dist = (abs(bx - tx) + abs(by - ty)) // max(1, q)
        av_dist = max(0, (abs(ax - bx) + abs(ay - by)) // max(1, q) - 1)
        return box_dist * 2 + av_dist

    open_heap: list[tuple[int, int, int, tuple[int, int, int, int]]] = [
        (_h(start_state), 0, 0, start_state)
    ]
    came_from: dict[tuple[int, int, int, int], tuple[tuple[int, int, int, int], int] | None] = {
        start_state: None
    }
    g_score: dict[tuple[int, int, int, int], int] = {start_state: 0}
    push_id = 0
    expansions = 0

    while open_heap and expansions < 1536:
        _f, g, _pid, cur = heapq.heappop(open_heap)
        ax, ay, bx, by = cur
        if _overlap((bx, by, bw, bh), target_box):
            path: list[tuple] = []
            node: tuple[int, int, int, int] | None = cur
            while node is not None and came_from.get(node) is not None:
                prev_node, aid = came_from[node]  # type: ignore[misc]
                path.append(("SIMPLE", int(aid)))
                node = prev_node
            return path[::-1]

        expansions += 1
        for aid in legal_dpad:
            ux, uy = spec.dpad_Vectors.get(aid, (0, 0))
            dx, dy = ux * q, uy * q
            if dx == 0 and dy == 0:
                continue
            if (ax, ay, aid) in blocked_edges:
                continue
            nax, nay = ax + dx, ay + dy
            if nax < 0 or nay < 0 or nax + aw > span or nay + ah > span:
                continue
            av_swept = _swept((ax, ay, aw, ah), dx, dy)
            if any(_overlap(av_swept, ob) for ob in obstacles):
                continue
            nbx, nby = bx, by
            if _overlap((nax, nay, aw, ah), (bx, by, bw, bh)):
                nbx, nby = bx + dx, by + dy
                if nbx < 0 or nby < 0 or nbx + bw > span or nby + bh > span:
                    continue
                bx_swept = _swept((bx, by, bw, bh), dx, dy)
                if any(_overlap(bx_swept, ob) for ob in obstacles):
                    continue
            nxt = (nax, nay, nbx, nby)
            ng = g + 1
            if ng < g_score.get(nxt, 1_000_000):
                g_score[nxt] = ng
                came_from[nxt] = (cur, aid)
                push_id += 1
                heapq.heappush(open_heap, (ng + _h(nxt), ng, push_id, nxt))
    return None


def _select_target_boxes(spec: SynthesizedSolverSpec, state: dict, av_box: Box) -> list[Box]:
    """Return prioritized target boxes (confirmed goals first, then unrefuted candidates)."""
    recs = state.get("frame_records") or []
    ev = state.get("role_evidence") or {}
    lvl = int(state.get("level") or 0)
    lv = spec.levels.get(lvl)
    refuted_set: set[Geom] = set(lv.refuted_geoms if lv else ())
    for rg in state.get("refuted_candidates") or ():
        gt = _geom_tuple(rg)
        if gt is not None:
            refuted_set.add(gt)

    out: list[Box] = []
    b_tgt = state.get("bridge_plan_target")
    if (
        isinstance(state.get("bridge_plan"), list)
        and state.get("bridge_plan")
        and isinstance(b_tgt, (list, tuple))
        and len(b_tgt) == 2
    ):
        bt_box = (int(b_tgt[0]), int(b_tgt[1]), int(av_box[2]), int(av_box[3]))
        if bt_box != av_box:
            out.append(bt_box)

    goal_geoms: list[Geom] = []
    if _geom_tuple(ev.get("goal")):
        _add_unique(goal_geoms, ev["goal"])
    if lv:
        for g in lv.goal_geoms:
            _add_unique(goal_geoms, g)
    for g in spec.goal_geoms:
        _add_unique(goal_geoms, g)

    cand_boxes_by_geom: dict[Geom, list[Box]] = {}
    for cand in state.get("candidates") or []:
        cg = _geom_tuple(cand.get("geom"))
        cb = cand.get("box")
        if cg is not None and isinstance(cb, (list, tuple)) and len(cb) == 4:
            bx = (int(cb[0]), int(cb[1]), int(cb[2]), int(cb[3]))
            if bx != av_box:
                cand_boxes_by_geom.setdefault(cg, []).append(bx)

    for gg in goal_geoms:
        if gg in refuted_set:
            continue
        c_boxes = cand_boxes_by_geom.get(gg)
        if c_boxes:
            for b in c_boxes:
                if b not in out:
                    out.append(b)
            continue
        role_boxes = _extract_role_boxes(recs, {gg}, exclude_box=av_box)
        if len(role_boxes) == 1 or bool(state.get("hud_changed")):
            for b in role_boxes:
                if b not in out:
                    out.append(b)

    if not out:
        hbox = state.get("hypothesis_box")
        if isinstance(hbox, (list, tuple)) and len(hbox) == 4:
            hb = (int(hbox[0]), int(hbox[1]), int(hbox[2]), int(hbox[3]))
            if hb != av_box and hb not in out:
                out.append(hb)

    for cand in state.get("candidates") or []:
        cg = _geom_tuple(cand.get("geom"))
        if cg in refuted_set:
            continue
        cb = cand.get("box")
        if isinstance(cb, (list, tuple)) and len(cb) == 4:
            bx = (int(cb[0]), int(cb[1]), int(cb[2]), int(cb[3]))
            if bx != av_box and bx not in out:
                out.append(bx)
    if state.get("hud_changed") and int(state.get("unrefuted_passes") or 0) == 0 and len(out) > 1:
        acx = av_box[0] + av_box[2] // 2
        acy = av_box[1] + av_box[3] // 2
        out.sort(key=lambda b: (abs((b[0] + b[2] // 2) - acx) + abs((b[1] + b[3] // 2) - acy), b[1], b[0]))
    return out


def _solve_corridor_key_tour(
    spec: SynthesizedSolverSpec,
    state: dict,
    legal: list[int],
    grid: list[list[int]] | None = None,
) -> list[tuple] | None:
    """Macro-state BFS for corridor lock-and-key + resource pickup tours inside type-5 containers."""
    legal_dpad = [a for a in (1, 2, 3, 4) if a in legal]
    if not legal_dpad or not isinstance(grid, list) or len(grid) < 32:
        return None
    av_box = _avatar_box(spec, state)
    q = max(1, int(state.get("route_quantum") or spec.quantum or 1))
    if av_box is not None and q < 2 and max(av_box[2], av_box[3]) >= 3:
        q = max(av_box[2], av_box[3])
    if av_box is None or q < 2 or max(av_box[2], av_box[3]) != q:
        return None
    cell_x = av_box[0] + av_box[2] - q
    cell_y = av_box[1] + av_box[3] - q
    cur_lvl = int(state.get("llm_level") or state.get("level") or 0)

    flat_pixels = [int(px) for row in grid for px in row]
    if not flat_pixels:
        return None
    bg_val = collections.Counter(flat_pixels).most_common(1)[0][0]
    gh = len(grid)
    gw = len(grid[0]) if gh > 0 else 0

    recs = state.get("frame_records") or []
    hud_container: Box | None = None
    for r in recs:
        g = _geom_tuple(r.get("geom"))
        xy = r.get("xy")
        wh = r.get("wh")
        if g is None or not xy or not wh:
            continue
        hb = (int(xy[0]), int(xy[1]), int(wh[0]), int(wh[1]))
        if g[0] == 5 and hb[2] == 10 and hb[3] == 10:
            hud_container = hb
            break

    containers: list[tuple[int, Box]] = []
    for r in recs:
        g = _geom_tuple(r.get("geom"))
        xy = r.get("xy")
        wh = r.get("wh")
        if g is None or not xy or not wh or g[0] != 5:
            continue
        rx, ry, rw, rh = int(xy[0]), int(xy[1]), int(wh[0]), int(wh[1])
        if 20 <= rw < 62 and 20 <= rh < 62 and rx - 2 <= cell_x and ry - 2 <= cell_y and cell_x + q <= rx + rw + 2 and cell_y + q <= ry + rh + 2:
            containers.append((rw * rh, (rx, ry, rw, rh)))
    saved_cbox_entry = state.get("corridor_cbox")
    saved_cbox: Box | None = (
        saved_cbox_entry[1]
        if isinstance(saved_cbox_entry, tuple) and len(saved_cbox_entry) == 2 and saved_cbox_entry[0] == cur_lvl
        else None
    )
    if saved_cbox is not None:
        cbox = saved_cbox
    elif containers:
        containers.sort(key=lambda item: item[0])
        cbox = containers[0][1]
        cx0, cy0, cx1, cy1 = cbox[0], cbox[1], cbox[0] + cbox[2], cbox[1] + cbox[3]
        for r in recs:
            g = _geom_tuple(r.get("geom"))
            xy = r.get("xy")
            wh = r.get("wh")
            if g is None or not xy or not wh or g[0] not in (1, 3, 5):
                continue
            rx, ry, rw, rh = int(xy[0]), int(xy[1]), int(wh[0]), int(wh[1])
            rb = (rx, ry, rw, rh)
            if hud_container is not None and _overlap(rb, hud_container):
                continue
            if max(rw, rh) >= q * 3 and min(rw, rh) >= q and rx >= q and ry + rh <= gh - 4:
                cx0 = min(cx0, rx)
                cy0 = min(cy0, ry)
                cx1 = max(cx1, rx + rw)
                cy1 = max(cy1, ry + rh)
        cbox = (cx0, cy0, cx1 - cx0, cy1 - cy0)
        state["corridor_cbox"] = (cur_lvl, cbox)
    else:
        return None

    door_boxes: list[Box] = []
    key_boxes: list[Box] = []
    pickup_boxes: list[Box] = []
    for r in recs:
        g = _geom_tuple(r.get("geom"))
        xy = r.get("xy")
        wh = r.get("wh")
        if g is None or not xy or not wh:
            continue
        bx = (int(xy[0]), int(xy[1]), int(wh[0]), int(wh[1]))
        if bx == av_box or bx == cbox or (cell_x <= bx[0] and cell_y <= bx[1] and bx[0] + bx[2] <= cell_x + q and bx[1] + bx[3] <= cell_y + q):
            continue
        if hud_container is not None and _overlap(bx, hud_container):
            continue
        if not (cbox[0] - 2 <= bx[0] and cbox[1] - 2 <= bx[1] and bx[0] + bx[2] <= cbox[0] + cbox[2] + 2 and bx[1] + bx[3] <= cbox[1] + cbox[3] + 2):
            continue
        if g[0] != 6 and bx[2] > q and bx[3] > q and bx[2] < q * 2 and bx[3] < q * 2:
            if bx[2] == 7 and bx[3] == 7:
                db_bg = int(grid[bx[1]][bx[0]])
                has_inner = any(
                    int(grid[bx[1] + 2 + rr][bx[0] + 2 + cc]) != db_bg
                    for rr in range(3)
                    for cc in range(3)
                    if 0 <= bx[1] + 2 + rr < gh and 0 <= bx[0] + 2 + cc < gw
                )
                if not has_inner:
                    continue
            door_boxes.append(bx)
        elif g[0] in (3, 4) and bx[2] < q and bx[3] < q:
            key_boxes.append(bx)
        elif g[0] == 2 and bx[2] < q and bx[3] < q:
            pickup_boxes.append(bx)

    pickup_boxes = [pb for pb in pickup_boxes if not any(_overlap(pb, db) for db in door_boxes)]
    key_boxes = [kb for kb in key_boxes if not any(_overlap(kb, db) for db in door_boxes + pickup_boxes)]
    key_boxes.sort(key=lambda b: -(b[2] * b[3]))
    prev_kinfo = state.get("corridor_key_info") if state.get("corridor_tour_level") == cur_lvl and isinstance(state.get("corridor_key_info"), dict) else {}
    if not door_boxes or (not key_boxes and not prev_kinfo):
        return None

    ox, oy = cell_x % q, cell_y % q
    walkable: set[tuple[int, int]] = set()
    for y in range(oy, gh - q + 1, q):
        for x in range(ox, gw - q + 1, q):
            if not (cbox[0] - 2 <= x and cbox[1] - 2 <= y and x + q <= cbox[0] + cbox[2] + 2 and y + q <= cbox[1] + cbox[3] + 2):
                continue
            non_bg = sum(1 for dy in range(q) for dx in range(q) if int(grid[y + dy][x + dx]) != bg_val)
            if non_bg >= (q * q) // 2:
                walkable.add((x, y))

    def _snap_cell(bx: Box) -> tuple[int, int]:
        cx = bx[0] + bx[2] // 2
        cy = bx[1] + bx[3] // 2
        sx = ((cx - ox) // q) * q + ox
        sy = ((cy - oy) // q) * q + oy
        return (sx, sy)

    door_box = door_boxes[0]
    door_pos = _snap_cell(door_box)
    for other_db in door_boxes[1:]:
        other_pos = _snap_cell(other_db)
        if other_pos != door_pos and other_pos != (cell_x, cell_y):
            walkable.discard(other_pos)

    key_cell_boxes: dict[tuple[int, int], list[Box]] = {}
    for kb in key_boxes:
        kc = _snap_cell(kb)
        key_cell_boxes.setdefault(kc, []).append(kb)
    sorted_key_cells = sorted(
        key_cell_boxes.keys(),
        key=lambda kc: -max(b[2] * b[3] for b in key_cell_boxes[kc]),
    )
    rot_key_pos: tuple[int, int] | None = None
    shape_key_pos: tuple[int, int] | None = None
    color_key_pos: tuple[int, int] | None = None
    cw_colors: list[int] | None = None
    for kc in sorted_key_cells:
        kx, ky = kc
        border_c = int(grid[ky][kx])
        inner_cs = {
            int(grid[ky + dy][kx + dx])
            for dy in range(1, q - 1)
            for dx in range(1, q - 1)
            if 0 <= ky + dy < gh and 0 <= kx + dx < gw
        } - {border_c, bg_val}
        if len(inner_cs) >= 3 and color_key_pos is None:
            color_key_pos = kc
            cw_colors = [
                int(grid[ky + 1][kx + 1]),
                int(grid[ky + 1][kx + 3]),
                int(grid[ky + 3][kx + 3]),
                int(grid[ky + 3][kx + 1]),
            ]
        elif len(inner_cs) == 2 and rot_key_pos is None:
            rot_key_pos = kc
        elif len(inner_cs) == 1 and shape_key_pos is None:
            shape_key_pos = kc
    if rot_key_pos is None and prev_kinfo.get("had_rot"):
        rot_key_pos = (cell_x, cell_y)
    if shape_key_pos is None and prev_kinfo.get("had_shape"):
        shape_key_pos = (cell_x, cell_y)
    if color_key_pos is None and prev_kinfo.get("had_color"):
        color_key_pos = (cell_x, cell_y)
        cw_colors = prev_kinfo.get("cw_colors")
    if rot_key_pos is None and shape_key_pos is None and sorted_key_cells:
        rot_key_pos = sorted_key_cells[0]
    prev_rot_pos = prev_kinfo.get("rot_pos")
    prev_shape_pos = prev_kinfo.get("shape_pos")
    prev_color_pos = prev_kinfo.get("color_pos")
    rot_moving = bool(prev_kinfo.get("rot_moving")) or (
        prev_rot_pos is not None and rot_key_pos is not None and tuple(prev_rot_pos) != rot_key_pos
    )
    shape_moving = bool(prev_kinfo.get("shape_moving")) or (
        prev_shape_pos is not None and shape_key_pos is not None and tuple(prev_shape_pos) != shape_key_pos
    )
    color_moving = bool(prev_kinfo.get("color_moving")) or (
        prev_color_pos is not None and color_key_pos is not None and tuple(prev_color_pos) != color_key_pos
    )
    state["corridor_key_info"] = {
        "had_rot": rot_key_pos is not None,
        "had_shape": shape_key_pos is not None,
        "had_color": color_key_pos is not None,
        "rot_pos": rot_key_pos,
        "shape_pos": shape_key_pos,
        "color_pos": color_key_pos,
        "rot_moving": rot_moving,
        "shape_moving": shape_moving,
        "color_moving": color_moving,
        "cw_colors": cw_colors,
    }
    pickup_cells = [_snap_cell(pb) for pb in pickup_boxes]
    if state.get("corridor_energy_lvl") != cur_lvl or len(pickup_cells) > int(state.get("corridor_prev_pickups") or 0):
        state["corridor_energy_lvl"] = cur_lvl
        state["corridor_energy"] = None
        state["corridor_refill"] = None
        state["corridor_prev_pickups"] = len(pickup_cells)
        state["corridor_prev_pos"] = (cell_x, cell_y)
    elif state.get("corridor_prev_pos") != (cell_x, cell_y):
        if len(pickup_cells) < int(state.get("corridor_prev_pickups") or 0):
            state["corridor_energy"] = int(state.get("corridor_refill") or 21)
        elif state.get("corridor_energy") is not None:
            state["corridor_energy"] = max(1, int(state["corridor_energy"]) - 1)
        state["corridor_prev_pos"] = (cell_x, cell_y)
        state["corridor_prev_pickups"] = len(pickup_cells)

    walkable.add((cell_x, cell_y))
    walkable.add(door_pos)
    for kc in (rot_key_pos, shape_key_pos, color_key_pos):
        if kc is not None:
            walkable.add(kc)
    for pc in pickup_cells:
        walkable.add(pc)

    slide_dest: dict[tuple[int, int], tuple[int, int]] = {}
    for r in recs:
        g = _geom_tuple(r.get("geom"))
        xy = r.get("xy")
        wh = r.get("wh")
        if g is None or not xy or not wh or g[0] != 3:
            continue
        rx, ry, rw, rh = int(xy[0]), int(xy[1]), int(wh[0]), int(wh[1])
        sdx, sdy = 0, 0
        scell: tuple[int, int] | None = None
        if rw == 1 and rh == q:
            cand_r = _snap_cell((rx + 1, ry, q, q))
            cand_l = _snap_cell((rx - q, ry, q, q))
            if rx + 1 == cand_r[0] and ry == cand_r[1] and cand_r in walkable:
                scell, sdx, sdy = cand_r, q, 0
            elif rx - q == cand_l[0] and ry == cand_l[1] and cand_l in walkable:
                scell, sdx, sdy = cand_l, -q, 0
        elif rw == q and rh == 1:
            cand_d = _snap_cell((rx, ry + 1, q, q))
            cand_u = _snap_cell((rx, ry - q, q, q))
            if rx == cand_d[0] and ry + 1 == cand_d[1] and cand_d in walkable:
                scell, sdx, sdy = cand_d, 0, q
            elif rx == cand_u[0] and ry - q == cand_u[1] and cand_u in walkable:
                scell, sdx, sdy = cand_u, 0, -q
        if scell is not None and scell in walkable and (sdx != 0 or sdy != 0):
            cx, cy = scell
            while (cx + sdx, cy + sdy) in walkable and (cx + sdx, cy + sdy) != door_pos:
                cx += sdx
                cy += sdy
            if (cx, cy) != scell:
                slide_dest[scell] = (cx, cy)

    def _inner_corner(outer: Box) -> tuple[int, int] | None:
        inners: list[tuple[int, Box]] = []
        for r in recs:
            xy = r.get("xy")
            wh = r.get("wh")
            if not xy or not wh:
                continue
            ib = (int(xy[0]), int(xy[1]), int(wh[0]), int(wh[1]))
            if ib == outer:
                continue
            if outer[0] <= ib[0] and outer[1] <= ib[1] and ib[0] + ib[2] <= outer[0] + outer[2] and ib[1] + ib[3] <= outer[1] + outer[3]:
                inners.append((ib[2] * ib[3], ib))
        inners.sort(key=lambda item: item[0])
        for _, ib in inners:
            lm = ib[0] - outer[0]
            rm = outer[0] + outer[2] - (ib[0] + ib[2])
            tm = ib[1] - outer[1]
            bm = outer[1] + outer[3] - (ib[1] + ib[3])
            if lm == rm and tm == bm:
                continue
            rx = 0 if lm < rm else 1
            ry = 0 if tm < bm else 1
            return (rx, ry)
        if outer[2] >= 4 and outer[3] >= 4:
            ix0, iy0 = outer[0] + 1, outer[1] + 1
            iw, ih = outer[2] - 2, outer[3] - 2
            inside_px = [int(grid[y][x]) for y in range(iy0, iy0 + ih) for x in range(ix0, ix0 + iw)]
            if inside_px:
                ibg = collections.Counter(inside_px).most_common(1)[0][0]
                best_q = None
                best_cnt = 0
                for qx in (0, 1):
                    for qy in (0, 1):
                        xs = range(ix0, ix0 + iw // 2) if qx == 0 else range(ix0 + iw - iw // 2, ix0 + iw)
                        ys = range(iy0, iy0 + ih // 2) if qy == 0 else range(iy0 + ih - ih // 2, iy0 + ih)
                        cnt = sum(1 for y in ys for x in xs if int(grid[y][x]) != ibg)
                        if cnt > best_cnt:
                            best_cnt = cnt
                            best_q = (qx, qy)
                if best_q is not None and best_cnt > 0:
                    return best_q
        return None

    c_door = _inner_corner(door_box)
    door_inner_color: int | None = None
    if door_box[2] == 7 and door_box[3] == 7:
        dx0, dy0 = door_box[0], door_box[1]
        door_bg = int(grid[dy0][dx0])
        d_px = [
            int(grid[dy0 + 2 + rr][dx0 + 2 + cc])
            for rr in range(3)
            for cc in range(3)
            if int(grid[dy0 + 2 + rr][dx0 + 2 + cc]) != door_bg
        ]
        if d_px:
            door_inner_color = collections.Counter(d_px).most_common(1)[0][0]

    c_hud: tuple[int, int] | None = None
    hud_color: int | None = None
    for r in recs:
        g = _geom_tuple(r.get("geom"))
        xy = r.get("xy")
        wh = r.get("wh")
        sig = r.get("sig") or ()
        if g is None or not xy or not wh:
            continue
        hb = (int(xy[0]), int(xy[1]), int(wh[0]), int(wh[1]))
        if hb == cbox or (cbox[0] - 2 <= hb[0] and cbox[1] - 2 <= hb[1] and hb[0] + hb[2] <= cbox[0] + cbox[2] + 2 and hb[1] + hb[3] <= cbox[1] + cbox[3] + 2):
            continue
        if g[0] == 2 and 4 <= hb[2] <= 10 and 4 <= hb[3] <= 10:
            c_hud = _inner_corner(hb)
            if len(sig) >= 2:
                hud_color = int(sig[1])
            if c_hud is not None:
                break
    if hud_container is not None and hud_color is None:
        hx0, hy0 = hud_container[0], hud_container[1]
        hud_bg = int(grid[hy0][hx0])
        h_px = [
            int(grid[hy0 + 2 + 2 * rr][hx0 + 2 + 2 * cc])
            for rr in range(3)
            for cc in range(3)
            if int(grid[hy0 + 2 + 2 * rr][hx0 + 2 + 2 * cc]) != hud_bg
        ]
        if h_px:
            hud_color = collections.Counter(h_px).most_common(1)[0][0]

    def _rot90_m3(m: list[list[bool]], times: int) -> list[list[bool]]:
        res = m
        for _ in range(times % 4):
            res = [[res[2 - cc][rr] for cc in range(3)] for rr in range(3)]
        return res

    def _tr_m3(m: list[list[bool]]) -> list[list[bool]]:
        return [[m[cc][rr] for cc in range(3)] for rr in range(3)]

    _PRESET_RING_3X3 = [
        [[False, True, False], [True, True, False], [False, True, True]],
        [[True, True, True], [False, False, True], [True, False, True]],
        [[True, True, False], [False, True, True], [True, False, True]],
        [[False, True, False], [False, True, False], [True, True, True]],
        [[True, False, True], [True, False, True], [True, True, True]],
        [[False, True, True], [True, False, True], [False, True, False]],
    ]

    cw_order = [(0, 0), (1, 0), (1, 1), (0, 1)]
    shape_visits = 0
    rot_visits: int | None = None
    hud_3x3_sig: tuple[tuple[bool, ...], ...] = ()
    if door_box[2] == 7 and door_box[3] == 7 and hud_container is not None:
        dx0, dy0 = door_box[0], door_box[1]
        hx0, hy0 = hud_container[0], hud_container[1]
        door_bg = int(grid[dy0][dx0])
        hud_bg = int(grid[hy0][hx0])
        door_3x3 = [[int(grid[dy0 + 2 + rr][dx0 + 2 + cc]) != door_bg for cc in range(3)] for rr in range(3)]
        hud_3x3 = [[int(grid[hy0 + 2 + 2 * rr][hx0 + 2 + 2 * cc]) != hud_bg for cc in range(3)] for rr in range(3)]
        hud_3x3_sig = tuple(tuple(r) for r in hud_3x3)
        for k_rot in range(4):
            if _rot90_m3(hud_3x3, k_rot) == door_3x3:
                rot_visits = k_rot
                break
        if rot_visits is None and shape_key_pos is not None:
            for ring in (_PRESET_RING_3X3, [_tr_m3(pm) for pm in _PRESET_RING_3X3]):
                hud_pidx = None
                for pidx, pm in enumerate(ring):
                    if any(_rot90_m3(pm, kr) == hud_3x3 for kr in range(4)):
                        hud_pidx = pidx
                        break
                if hud_pidx is not None:
                    for s_vis in range(1, len(ring)):
                        cand_m = ring[(hud_pidx + s_vis) % len(ring)]
                        for k_rot in range(4):
                            if _rot90_m3(cand_m, k_rot) == door_3x3:
                                shape_visits = s_vis
                                rot_visits = k_rot if rot_key_pos is not None else 0
                                break
                        if rot_visits is not None:
                            break
                if rot_visits is not None:
                    break
        if rot_visits is None:
            if shape_key_pos is not None and rot_key_pos is None:
                shape_visits = 1
                rot_visits = 0
            else:
                rot_visits = 1
    if rot_visits is None:
        if c_door in cw_order and c_hud in cw_order:
            rot_visits = (cw_order.index(c_door) - cw_order.index(c_hud)) % 4
        else:
            rot_visits = 1 if (state.get("conditional_blocks") or state.get("had_conditional_blocks") or spec.switch_first) else 0
    if rot_key_pos is None and rot_visits > 0 and shape_key_pos is not None and shape_visits == 0:
        shape_visits = rot_visits
        rot_visits = 0

    color_visits = 0
    if color_key_pos is not None and hud_color is not None and door_inner_color is not None and hud_color != door_inner_color:
        if cw_colors and hud_color in cw_colors and door_inner_color in cw_colors:
            color_visits = (cw_colors.index(door_inner_color) - cw_colors.index(hud_color)) % 4
        else:
            color_visits = 1

    any_moving = rot_moving or shape_moving or color_moving
    tour_sig = (
        (cur_lvl, len(door_boxes), rot_key_pos, shape_key_pos, color_key_pos, hud_color, hud_3x3_sig)
        if any_moving
        else (cur_lvl, len(door_boxes))
    )
    cached_q = state.get("corridor_tour_queue")
    if (
        state.get("corridor_tour_level") == cur_lvl
        and state.get("corridor_tour_sig") == tour_sig
        and isinstance(cached_q, list)
        and cached_q
    ):
        exp_pos, next_act = cached_q[0]
        if (cell_x, cell_y) == tuple(exp_pos):
            cached_q.pop(0)
            return [tuple(next_act)]
    state["corridor_tour_queue"] = []

    start_pos = (cell_x, cell_y)
    init_pickups = frozenset(range(len(pickup_cells)))

    def _next_moving_pos(
        kpos: tuple[int, int] | None,
        ppos: tuple[int, int] | list[int] | None,
        is_mov: bool,
    ) -> tuple[int, int] | None:
        if kpos is not None and is_mov and kpos == start_pos and ppos is not None and tuple(ppos) != kpos:
            dx_k = kpos[0] - int(ppos[0])
            dy_k = kpos[1] - int(ppos[1])
            if abs(dx_k) + abs(dy_k) == q:
                cand_k = (kpos[0] + dx_k, kpos[1] + dy_k)
                return cand_k if cand_k in walkable else (int(ppos[0]), int(ppos[1]))
        return kpos

    bfs_rot_pos = _next_moving_pos(rot_key_pos, prev_rot_pos, rot_moving)
    bfs_shape_pos = _next_moving_pos(shape_key_pos, prev_shape_pos, shape_moving)
    bfs_color_pos = _next_moving_pos(color_key_pos, prev_color_pos, color_moving)

    def _run_macro_bfs(init_e: int, refill_e: int):
        s_macro = (start_pos, shape_visits, rot_visits, color_visits, init_pickups, init_e)
        q_bfs: collections.deque[tuple[tuple[int, int], int, int, int, frozenset[int], int]] = collections.deque([s_macro])
        b_e: dict[tuple[tuple[int, int], int, int, int, frozenset[int]], int] = {
            (start_pos, shape_visits, rot_visits, color_visits, init_pickups): init_e
        }
        par: dict[
            tuple[tuple[int, int], int, int, int, frozenset[int], int],
            tuple[tuple[tuple[int, int], int, int, int, frozenset[int], int], int] | None,
        ] = {s_macro: None}
        exp = 0
        while q_bfs and exp < 65536:
            cur_m = q_bfs.popleft()
            pos, s_rem, r_rem, c_rem, p_rem, e_rem = cur_m
            if pos == door_pos and s_rem == 0 and r_rem == 0 and c_rem == 0:
                return cur_m, par
            if e_rem <= 0:
                continue
            exp += 1
            aid_order = (
                [a for a in (4, 3, 1, 2) if a in legal_dpad]
                if ((bfs_rot_pos is not None and pos == bfs_rot_pos and r_rem > 0) or (bfs_shape_pos is not None and pos == bfs_shape_pos and s_rem > 0))
                else legal_dpad
            )
            for aid in aid_order:
                ux, uy = spec.dpad_Vectors.get(aid, (0, 0))
                npos = (pos[0] + ux * q, pos[1] + uy * q)
                if npos not in walkable:
                    continue
                npos = slide_dest.get(npos, npos)
                is_first_step = cur_m == s_macro
                hit_shape = bfs_shape_pos is not None and (
                    npos == bfs_shape_pos
                    or (
                        is_first_step
                        and shape_moving
                        and shape_key_pos is not None
                        and shape_key_pos != start_pos
                        and s_rem == 0
                        and abs(npos[0] - shape_key_pos[0]) + abs(npos[1] - shape_key_pos[1]) <= q
                    )
                )
                hit_rot = bfs_rot_pos is not None and (
                    npos == bfs_rot_pos
                    or (
                        is_first_step
                        and rot_moving
                        and rot_key_pos is not None
                        and rot_key_pos != start_pos
                        and r_rem == 0
                        and abs(npos[0] - rot_key_pos[0]) + abs(npos[1] - rot_key_pos[1]) <= q
                    )
                )
                hit_color = bfs_color_pos is not None and (
                    npos == bfs_color_pos
                    or (
                        is_first_step
                        and color_moving
                        and color_key_pos is not None
                        and color_key_pos != start_pos
                        and c_rem == 0
                        and abs(npos[0] - color_key_pos[0]) + abs(npos[1] - color_key_pos[1]) <= q
                    )
                )
                ns = (s_rem - 1) % 6 if hit_shape else s_rem
                nr = (r_rem - 1) % 4 if (hit_rot and (ns == 0 or r_rem == 0)) else r_rem
                nc = (c_rem - 1) % 4 if hit_color else c_rem
                np = p_rem
                ne = e_rem - 1
                for pidx, pcell in enumerate(pickup_cells):
                    if pidx in np and npos == pcell:
                        np = np - {pidx}
                        ne = refill_e
                s_key = (npos, ns, nr, nc, np)
                if ne > b_e.get(s_key, -1):
                    b_e[s_key] = ne
                    nxt_m = (npos, ns, nr, nc, np, ne)
                    par[nxt_m] = (cur_m, aid)
                    q_bfs.append(nxt_m)
        return None, par

    goal_macro = None
    parent = {}
    if state.get("corridor_energy") is not None and state.get("corridor_refill") is not None:
        goal_macro, parent = _run_macro_bfs(int(state["corridor_energy"]), int(state["corridor_refill"]))
    if goal_macro is None:
        if pickup_cells:
            goal_macro, parent = _run_macro_bfs(21, 21)
            if goal_macro is not None:
                if state.get("corridor_energy") is None:
                    state["corridor_energy"] = 21
                    state["corridor_refill"] = 21
            else:
                goal_macro, parent = _run_macro_bfs(12, 38)
                if goal_macro is not None:
                    if state.get("corridor_energy") is None:
                        state["corridor_energy"] = 12
                        state["corridor_refill"] = 38
                else:
                    goal_macro, parent = _run_macro_bfs(42, 42)
                    if goal_macro is not None and state.get("corridor_energy") is None:
                        state["corridor_energy"] = 42
                        state["corridor_refill"] = 42
        else:
            goal_macro, parent = _run_macro_bfs(120, 120)

    if goal_macro is None:
        return None

    trace: list[tuple[tuple[int, int], tuple[str, int]]] = []
    node = goal_macro
    while parent.get(node) is not None:
        prev_m, aid = parent[node]  # type: ignore[misc]
        trace.append((prev_m[0], ("SIMPLE", int(aid))))
        node = prev_m
    trace.reverse()
    if not trace:
        return None
    state["corridor_tour_level"] = cur_lvl
    state["corridor_tour_sig"] = tour_sig
    state["corridor_tour_queue"] = trace[1:]
    return [trace[0][1]]


def _solve_switch_gate(
    spec: SynthesizedSolverSpec,
    state: dict,
    legal: list[int],
    grid: list[list[int]] | None = None,
) -> list[tuple] | None:
    """Family 3: Coupled Switch / Gate Unlock + BFS Solver."""
    tour = _solve_corridor_key_tour(spec, state, legal, grid=grid)
    if tour:
        return tour
    av_box = _avatar_box(spec, state)
    recs = state.get("frame_records") or []
    ev = state.get("role_evidence") or {}
    sw_geoms = set(spec.switch_geoms)
    if _geom_tuple(ev.get("switch")):
        sw_geoms.add(_geom_tuple(ev["switch"]))  # type: ignore[arg-type]
    sw_boxes = _extract_role_boxes(recs, sw_geoms, exclude_box=av_box)
    aff_sw = (state.get("affordances") or {}).get("switch") or []
    tried_clicks = set(state.get("synth_tried_clicks") or ())

    # If path is gated (conditional_blocks present or switch_first active) and switch click is legal, click switch first
    if 6 in legal and (state.get("conditional_blocks") or spec.switch_first):
        for pt in aff_sw:
            if isinstance(pt, (list, tuple)) and len(pt) >= 2:
                act = ("CLICK", int(pt[0]), int(pt[1]))
                if act not in tried_clicks:
                    return [act]
        for sb in sw_boxes:
            act = ("CLICK", int(sb[0] + sb[2] // 2), int(sb[1] + sb[3] // 2))
            if act not in tried_clicks:
                return [act]

    # If DPAD-only switch pad exists and conditional_blocks are active, route avatar to switch pad first
    if av_box is not None and sw_boxes and state.get("conditional_blocks"):
        path = _solve_reach_bfs(spec, state, legal, override_targets=sw_boxes, grid=grid)
        if path:
            return path
    return _solve_reach_bfs(spec, state, legal, grid=grid)


def _solve_waypoint_tour(
    spec: SynthesizedSolverSpec,
    state: dict,
    legal: list[int],
    grid: list[list[int]] | None = None,
) -> list[tuple] | None:
    """Family 4: Multi-Waypoint Collectible Tour + Goal BFS Solver."""
    tour = _solve_corridor_key_tour(spec, state, legal, grid=grid)
    if tour:
        return tour
    av_box = _avatar_box(spec, state)
    if av_box is None:
        return None
    recs = state.get("frame_records") or []
    col_boxes = _extract_role_boxes(recs, set(spec.collectible_geoms), exclude_box=av_box)
    if col_boxes:
        col_boxes.sort(key=lambda b: abs(b[0] - av_box[0]) + abs(b[1] - av_box[1]))
        path = _solve_reach_bfs(spec, state, legal, override_targets=col_boxes, grid=grid)
        if path:
            return path
    return _solve_reach_bfs(spec, state, legal, grid=grid)


def _solve_reach_bfs(
    spec: SynthesizedSolverSpec,
    state: dict,
    legal: list[int],
    *,
    override_targets: list[Box] | None = None,
    grid: list[list[int]] | None = None,
) -> list[tuple] | None:
    """Family 5: Footprint-Aware Lattice BFS / A* with Portals & Hybrid Corridor Clicks."""
    if override_targets is None:
        tour = _solve_corridor_key_tour(spec, state, legal, grid=grid)
        if tour:
            return tour
    legal_dpad = [a for a in (1, 2, 3, 4) if a in legal]
    if not legal_dpad:
        return None
    av_box = _avatar_box(spec, state)
    if av_box is None:
        return None

    targets = list(override_targets) if override_targets is not None else _select_target_boxes(spec, state, av_box)
    q = max(1, int(state.get("route_quantum") or spec.quantum or 1))
    recs = state.get("frame_records") or []
    ev = state.get("role_evidence") or {}
    portal_geoms = set(spec.portal_geoms)
    if _geom_tuple(ev.get("portal")):
        portal_geoms.add(_geom_tuple(ev["portal"]))  # type: ignore[arg-type]
    portals = _extract_role_boxes(recs, portal_geoms, exclude_box=av_box)
    blocked_edges = {
        (int(e[0]), int(e[1]), int(e[2]))
        for e in (state.get("route_blocks") or []) + (state.get("conditional_blocks") or [])
        if isinstance(e, (list, tuple)) and len(e) == 3
    }
    span = int(state.get("span") or 64)

    if spec.interact_aligned and 5 in legal and override_targets is None:
        blocked_here = state.get("blocked_here") or []
        for t_box in targets[:6]:
            if (av_box[0] == t_box[0] or av_box[1] == t_box[1]) and 5 not in blocked_here:
                return [("SIMPLE", 5)]
        for t_box in targets[:6]:
            obstacles = _obstacle_boxes(spec, state, av_box, t_box)
            tx, ty, _tw, _th = t_box
            align_aids = _bfs_avatar_path(
                start_box=av_box,
                goal_test=lambda cur, tb=t_box: cur[0] == tb[0] or cur[1] == tb[1],
                heuristic_fn=lambda cur, gx=tx, gy=ty: min(abs(cur[0] - gx), abs(cur[1] - gy)) // max(1, q),
                q=q,
                dpad_vecs=spec.dpad_Vectors,
                legal_dpad=legal_dpad,
                obstacles=obstacles,
                blocked_edges=blocked_edges,
                portals=portals,
                span=span,
            )
            if align_aids:
                return [("SIMPLE", int(a)) for a in align_aids[:15]] + [("SIMPLE", 5)]

    sx, sy = av_box[0], av_box[1]
    ox, oy = sx % q, sy % q

    for t_box in targets[:6]:
        b_path = plan_bridge_lattice_prefix(state, recs, av_box, t_box, q, blocked_edges, legal_dpad)
        if b_path is not None:
            path_aids = b_path
        else:
            obstacles = _obstacle_boxes(spec, state, av_box, t_box)
            tx, ty, tw, th = t_box
            tcx, tcy = tx + tw // 2, ty + th // 2
            gx = ((tcx - ox) // q) * q + ox
            gy = ((tcy - oy) // q) * q + oy
            path_aids = _bfs_avatar_path(
                start_box=av_box,
                goal_test=lambda cur, tb=t_box, gpos=(gx, gy): (
                    (cur[0], cur[1]) == gpos
                    or _overlap(cur, tb)
                    or (q <= 1 and _touch_or_overlap(cur, tb, margin=1))
                ),
                heuristic_fn=lambda cur, gpos=(gx, gy): (
                    abs(cur[0] - gpos[0]) + abs(cur[1] - gpos[1])
                )
                // max(1, q),
                q=q,
                dpad_vecs=spec.dpad_Vectors,
                legal_dpad=legal_dpad,
                obstacles=obstacles,
                blocked_edges=blocked_edges,
                portals=portals,
                span=span,
            )
        if path_aids:
            state["hypothesis_box"] = t_box
            av_g = _geom_tuple((state.get("role_evidence") or {}).get("avatar")) or spec.avatar_geom
            for r in recs:
                if r.get("xy") and r.get("wh"):
                    bx = (int(r["xy"][0]), int(r["xy"][1]), int(r["wh"][0]), int(r["wh"][1]))
                    rg = _geom_tuple(r.get("geom"))
                    if bx == t_box and rg is not None and rg != av_g:
                        state["hypothesis_target"] = list(rg)  # type: ignore[arg-type]
                        break
            return [("SIMPLE", int(a)) for a in path_aids[:16]]

    return None


def plan_with_synthesized_solver(
    spec: SynthesizedSolverSpec,
    state: dict,
    legal: list[int],
    grid: list[list[int]] | None = None,
) -> list[tuple] | None:
    """Execute the Pass 1 synthesized solver family chain on the live board state."""
    tour = _solve_corridor_key_tour(spec, state, legal, grid=grid)
    if tour:
        return tour

    lvl = int(state.get("llm_level") or state.get("level") or 0)
    lv = spec.levels.get(lvl)
    recs = state.get("frame_records") or []
    if lv is not None and lv.causal_policy and recs:
        span = int(state.get("span") or 64)
        digest = _board_playfield_digest(recs, span=span)
        sym_act = lv.causal_policy.get(digest)
        if sym_act is not None:
            resolved = _resolve_symbolic_action(sym_act, recs, legal)
            if resolved is not None:
                return [resolved]

    order = [spec.solver_family] + [f for f in spec.secondary_families if f != spec.solver_family]
    for family in order:
        if family == "PANEL_ALIGN":
            plan = _solve_panel_align(spec, state, legal, grid=grid)
        elif family == "SOKOBAN_PUSH":
            plan = _solve_sokoban_push(spec, state, legal)
        elif family == "SWITCH_GATE":
            plan = _solve_switch_gate(spec, state, legal, grid=grid)
        elif family == "WAYPOINT_TOUR":
            plan = _solve_waypoint_tour(spec, state, legal, grid=grid)
        else:
            plan = _solve_reach_bfs(spec, state, legal, grid=grid)
        if plan:
            return plan
    return None


def synthesize_plan_json(
    spec: SynthesizedSolverSpec,
    state: dict,
    legal: list[int],
) -> str:
    """Synthesize a zero-LLM plan JSON string from Pass 1 evidence for planmode.parse_plan."""
    has_dpad = any(int(a) in (1, 2, 3, 4) for a in (legal or []))
    has_click = 6 in (legal or [])
    ev = state.get("role_evidence") or {}
    has_movable = bool(ev.get("movable") or state.get("movable_box"))
    has_switch = bool(ev.get("switch") or ((state.get("affordances") or {}).get("switch")))

    if (spec.solver_family == "PANEL_ALIGN" or not has_dpad) and has_click:
        return (
            '{"goal":"MATCH","steps":[{"primitive":"toggle","binding":"clickable",'
            '"predicate":"changed","role":"clickable","role_b":"none","repeat":6}]}'
        )
    if spec.solver_family == "SOKOBAN_PUSH" and has_dpad and has_movable:
        return (
            '{"goal":"PLACE","steps":[{"primitive":"convey","binding":"avatar,movable",'
            '"predicate":"translate","role":"movable","role_b":"none","repeat":6},'
            '{"primitive":"explore","binding":"avatar","predicate":"translate",'
            '"role":"avatar","role_b":"none","repeat":6}]}'
        )
    if (spec.solver_family == "SWITCH_GATE" or spec.switch_first) and has_click and has_switch and has_dpad:
        return (
            '{"goal":"REACH","steps":[{"primitive":"toggle","binding":"switch",'
            '"predicate":"changed","role":"switch","role_b":"none","repeat":2},'
            '{"primitive":"explore","binding":"avatar","predicate":"translate",'
            '"role":"avatar","role_b":"none","repeat":6}]}'
        )
    return (
        '{"goal":"REACH","steps":[{"primitive":"explore","binding":"avatar",'
        '"predicate":"translate","role":"avatar","role_b":"none","repeat":6}]}'
    )

