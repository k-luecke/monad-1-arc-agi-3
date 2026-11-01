"""Compact CanvasDocument scene graph for the thought stream.

Reads the classes that already live on the agent. It does not choose an action.
Shape signatures and click anchors are the Layer-1 scene. The second-order
canvas contributes meta-label counts plus the Model A proposal and Model B audit.
A prev-document to curr-document diff is how an expectation is checked.
"""
from __future__ import annotations

from collections import Counter, defaultdict

SHAPE_NAMES = {
    0: "NONE",
    1: "RECT",
    2: "HOLLOW_RECT",
    3: "LINE",
    4: "ELLIPSE",
    5: "SPRITE",
    6: "ENCLOSED_CELL",
}

# Repo constants, not the 1..8 numbering in Kyle's guide.
META_NAMES = {
    1: "solid_wall",
    2: "floor",
    3: "avatar",
    4: "subgoal",
    5: "secondary",
    6: "terminal_goal",
    7: "hazard",
    8: "portal",
    9: "locked_gate",
    10: "illusory_wall",
    11: "responsive_switch",
    12: "inert_decor",
    14: "planned_path",
    15: "planned_target",
}


def _sets(agent, name: str) -> set:
    value = getattr(agent, name, None)
    return value if isinstance(value, set) else set()


def current_document(agent):
    grid = getattr(agent, "_m2_grid", None)
    if grid is None:
        return None
    from my_agent_v7_inos import CanvasDocument

    return CanvasDocument(
        grid,
        _sets(agent, "hud_rows"),
        _sets(agent, "hud_coords"),
        _sets(agent, "hud_cols"),
    )


def shape_record(shape) -> dict:
    return {
        "type": int(shape.shape_type),
        "sig": tuple(int(v) for v in shape.sig),
        "geom": tuple(int(v) for v in shape.shape_geom_sig),
        "click": (int(shape.click_x), int(shape.click_y)),
        "xy": (int(shape.x), int(shape.y)),
        "wh": (int(shape.w), int(shape.h)),
        "area": int(shape.area),
    }


def _fmt_sig(sig) -> str:
    return ",".join(str(int(v)) for v in sig)


def shape_line(rec: dict) -> str:
    name = SHAPE_NAMES.get(int(rec["type"]), str(rec["type"]))
    click = rec["click"]
    wh = rec["wh"]
    return (
        f"{name} sig={_fmt_sig(rec['sig'])} geom={_fmt_sig(rec['geom'])} "
        f"{wh[0]}x{wh[1]} click={click[0]},{click[1]}"
    )


def diff_records(before: list[dict], after: list[dict]) -> dict:
    """Match shapes by signature. Report translation, vanish, and appear."""
    pools: dict[tuple, list[int]] = defaultdict(list)
    for index, rec in enumerate(after):
        pools[tuple(rec["sig"])].append(index)
    taken: set[int] = set()
    moved = []
    vanished = []
    for rec in before:
        pool = pools.get(tuple(rec["sig"]), [])
        choice = None
        best = None
        for index in pool:
            if index in taken:
                continue
            other = after[index]
            dist = abs(other["click"][0] - rec["click"][0]) + abs(other["click"][1] - rec["click"][1])
            if best is None or dist < best:
                best = dist
                choice = index
        if choice is None:
            vanished.append(rec)
            continue
        taken.add(choice)
        other = after[choice]
        dx = int(other["xy"][0]) - int(rec["xy"][0])
        dy = int(other["xy"][1]) - int(rec["xy"][1])
        if dx or dy:
            moved.append({"sig": rec["sig"], "dx": dx, "dy": dy})
    appeared = [after[index] for index in range(len(after)) if index not in taken]
    return {"moved": moved, "vanished": vanished, "appeared": appeared}


def diff_text(diff: dict | None) -> str:
    if not diff:
        return "no prior document"
    parts = []
    for move in diff["moved"][:3]:
        parts.append(f"sig {_fmt_sig(move['sig'])} moves {move['dx']:+d}x {move['dy']:+d}y")
    for rec in diff["vanished"][:2]:
        parts.append(f"sig {_fmt_sig(rec['sig'])} vanishes")
    for rec in diff["appeared"][:2]:
        parts.append(f"sig {_fmt_sig(rec['sig'])} appears")
    if not parts:
        return "no shape change"
    return "; ".join(parts)


def expectation_matches(expectation: str, diff: dict | None) -> bool | None:
    """True when the stated canvas change is what the document diff shows."""
    if not diff or not expectation:
        return None
    text = expectation.lower()
    moved = bool(diff["moved"])
    vanished = bool(diff["vanished"])
    appeared = bool(diff["appeared"])
    any_change = moved or vanished or appeared
    if any(word in text for word in ("vanish", "disappear")):
        return vanished
    if "appear" in text:
        return appeared
    if any(word in text for word in ("no shape", "unchanged", "stays")):
        return not any_change
    if any(word in text for word in ("move", "shift", "+", "translat")):
        return moved
    if "frame change" in text or "changes under" in text:
        return any_change
    return None


def solver_name(reason: str, agent) -> str:
    """A general concept. The raw reason is not copied: it can name a puzzle plan."""
    text = (reason or "").lower()
    family = str(getattr(agent, "active_macro_family", "") or "")
    if any(word in text for word in ("panel", "receptor", "align", "match")):
        return "match the shape to the receptor"
    if "hit-test" in text or "operant" in text or "click" in text:
        return "click the unique switch shape"
    if "kinematic" in text or family == "online_learned_kinematic" or "trail" in text or "paint" in text:
        return "paint the remaining floor"
    return "move the avatar onto the unique shape"


def _meta_counts(agent) -> str:
    canvas = getattr(agent, "second_order_canvas", None)
    grid = getattr(canvas, "semantic_canvas", None) if canvas is not None else None
    if not grid:
        return "no second-order canvas"
    counts: Counter[int] = Counter()
    for row in grid:
        for value in row:
            iv = int(value)
            if iv:
                counts[iv] += 1
    if not counts:
        return "meta empty"
    parts = [f"{META_NAMES.get(k, k)}:{n}" for k, n in counts.most_common(6)]
    return " ".join(parts)


def _model_lines(agent) -> tuple[str, str]:
    canvas = getattr(agent, "second_order_canvas", None)
    if canvas is None or not hasattr(canvas, "summary_metrics"):
        return "no model A proposal", "no model B audit"
    try:
        metrics = canvas.summary_metrics()
    except Exception:
        return "model A unread", "model B unread"
    aid = metrics.get("audited_first_raw_aid")
    passed = bool(metrics.get("audit_passed"))
    why = str(metrics.get("audit_reason") or "")
    proposal = f"SIMPLE {aid}" if aid is not None else "none"
    model_a = f"proposes {proposal} path_len={metrics.get('path_len')} target={metrics.get('active_target_rc')}"
    if passed:
        model_b = f"audit passed ({why})"
    else:
        model_b = f"veto {why or 'rejected'} on {proposal}"
    return model_a, model_b


def _avatar_line(agent, doc) -> str:
    if doc is None:
        return "no avatar"
    infer = getattr(agent, "_resolve_or_infer_avatar_shape", None)
    if not callable(infer):
        return "no avatar inference"
    try:
        shape = infer(doc)
    except Exception:
        return "avatar inference failed"
    if shape is None:
        return "avatar unresolved"
    rec = shape_record(shape)
    return shape_line(rec)


def _control_line(agent) -> str:
    flips = int(getattr(agent, "control_inversions_detected", 0) or 0)
    canon = getattr(agent, "canonical_to_raw_dpad", None) or {}
    gauge = ",".join(f"{k}->{v}" for k, v in list(canon.items())[:4]) or "identity"
    regime = ""
    spec = getattr(agent, "last_intent_spec", None)
    delta = getattr(spec, "expected_avatar_delta", None) if spec is not None else None
    if delta is not None:
        regime = f" last_expected_delta={delta}"
    tension = getattr(agent, "self_narrative", None)
    if isinstance(tension, dict) and tension.get("tension_regime"):
        regime += f" tension={tension.get('tension_regime')}"
    return f"inversions={flips} gauge={gauge}{regime}"


def _event_line(agent, diff: dict | None) -> str:
    bits = [diff_text(diff)]
    splits = int(getattr(agent, "object_splits_detected", 0) or 0)
    if splits:
        bits.append(f"object_split_count={splits}")
    lineage = getattr(agent, "schema_lineage", None)
    if isinstance(lineage, dict) and lineage:
        parent = next(iter(lineage.values()))
        bits.append(f"lineage->{_fmt_sig(parent) if isinstance(parent, tuple) else parent}")
    portals = getattr(agent, "learned_portals", None)
    if isinstance(portals, dict) and portals:
        bits.append(f"portals={len(portals)}")
    switches = getattr(agent, "learned_occupancy_switches", None)
    n_sw = len(switches) if hasattr(switches, "__len__") else 0
    if n_sw:
        bits.append(f"occupancy_switches={n_sw}")
    trails = getattr(agent, "trail_color_transitions", None)
    try:
        common = trails.most_common(1) if trails else []
    except Exception:
        common = []
    if common:
        (pair, count) = common[0]
        bits.append(f"trail {pair} x{count}")
    slides = int(getattr(agent, "learned_slide_moves", 0) or 0)
    if slides:
        bits.append(f"slides={slides}")
    return "; ".join(bits)


def scene_brief(agent, diff: dict | None = None) -> dict:
    """One compact scene. Empty fields stay explicit so the stream still names them."""
    doc = None
    records: list[dict] = []
    try:
        doc = current_document(agent)
    except Exception:
        doc = None
    if doc is not None:
        records = [shape_record(s) for s in list(doc.shapes)]
    hud_r = len(_sets(agent, "hud_rows"))
    hud_c = len(_sets(agent, "hud_cols"))
    bg = getattr(doc, "bg_color", None) if doc is not None else None
    nshapes = len(getattr(doc, "shapes", []) or []) if doc is not None else 0
    shape_text = " | ".join(shape_line(rec) for rec in records[:6]) or "no shapes"
    model_a, model_b = _model_lines(agent)
    playfield = f"bg={bg} shapes={nshapes} hud_rows={hud_r} hud_cols={hud_c}"
    return {
        "playfield": playfield,
        "shapes": shape_text,
        "records": records,
        "avatar": _avatar_line(agent, doc),
        "control": _control_line(agent),
        "events": _event_line(agent, diff),
        "meta": _meta_counts(agent),
        "model_a": model_a,
        "model_b": model_b,
        "solver": "",
    }


def document_result(agent, before: list[dict], expectation: str) -> tuple[str, bool | None, dict]:
    doc = None
    try:
        doc = current_document(agent)
    except Exception:
        doc = None
    after = [shape_record(s) for s in list(getattr(doc, "shapes", []) or [])]
    diff = diff_records(list(before or []), after)
    return diff_text(diff), expectation_matches(expectation, diff), diff
