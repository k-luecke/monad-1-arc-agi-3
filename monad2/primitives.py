"""Motor primitives mined from the old solvers.

Each primitive is a rule of motion: a precondition read from the current role
binding, an action pattern, and an expected effect. Bindings are role names.
There is no game id, no frame fingerprint, no palette entry, and no coordinate.

The old solver methods stay in the agent for reference. This module does not
call them. A move that is not one of these rules is the explore primitive,
and it has to be labeled as exploration.
"""
from __future__ import annotations

import ast
from pathlib import Path

# Action ids. 1 up, 2 down, 3 left, 4 right, 5 interact. Not coordinates.
_REVERSE = {1: 2, 2: 1, 3: 4, 4: 3}

NAMES = (
    "approach",
    "hold_gradient",
    "convey",
    "align",
    "toggle",
    "avoid",
    "cycle_select",
    "route",
    "assemble",
    "explore",
)

_EFFECT = {
    "approach": "avatar translates toward the goal",
    "hold_gradient": "avatar does not reverse",
    "convey": "movable translates toward the goal",
    "align": "the object matches the reference",
    "toggle": "the switch changes another role",
    "avoid": "avatar stays off the hazard",
    "cycle_select": "the selector matches the reference",
    "route": "avatar translates along the open axis",
    "assemble": "two roles make contact",
    "explore": "frame changes under labeled exploration",
}

_BINDING = {
    "approach": ("avatar", "goal"),
    "hold_gradient": ("avatar", "goal"),
    "convey": ("avatar", "movable", "goal"),
    "align": ("avatar", "receptor"),
    "toggle": ("switch",),
    "avoid": ("avatar", "hazard"),
    "cycle_select": ("switch", "goal"),
    "route": ("avatar", "wall"),
    "assemble": ("movable", "receptor"),
    "explore": (),
}


def _roles(obs: dict) -> set[str]:
    return {str(slot.get("role")) for slot in (obs or {}).get("roles") or [] if slot.get("role")}


def _relations(obs: dict) -> set[str]:
    return {str(rel.get("kind")) for rel in (obs or {}).get("relations") or [] if rel.get("kind")}


def _has(roles: set[str], *need: str) -> bool:
    return all(name in roles for name in need)


def _role_geom(obs: dict, role: str):
    for slot in (obs or {}).get("roles") or []:
        if slot.get("role") == role and slot.get("geom") and len(slot["geom"]) == 3:
            return (int(slot["geom"][0]), int(slot["geom"][1]), int(slot["geom"][2]))
    return None


def _rec_geom(rec: dict):
    raw = rec.get("geom")
    if not raw or len(raw) != 3:
        return None
    return (int(raw[0]), int(raw[1]), int(raw[2]))


def _rec_box(rec: dict):
    xy = rec.get("xy")
    wh = rec.get("wh")
    if not xy or not wh or len(xy) != 2 or len(wh) != 2:
        return None
    return (int(xy[0]), int(xy[1]), int(wh[0]), int(wh[1]))


def _boxes_for(records, geom) -> list:
    if geom is None:
        return []
    found = []
    for rec in records or []:
        if _rec_geom(rec) != geom:
            continue
        box = _rec_box(rec)
        if box is not None:
            found.append(box)
    return found


def _overlap(a, b) -> bool:
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    return ax < bx + bw and ax + aw > bx and ay < by + bh and ay + ah > by


def _neg() -> int:
    return 0 - 1


def _ahead(box, aid: int):
    x, y, w, h = box
    step = _neg()
    if aid == 1:
        return (x, y + step, w, 1)
    if aid == 2:
        return (x, y + h, w, 1)
    if aid == 3:
        return (x + step, y, 1, h)
    if aid == 4:
        return (x + w, y, 1, h)
    return None


def _dir_order(dx: int, dy: int) -> list[int]:
    step = _neg()
    deltas = ((1, 0, step), (2, 0, 1), (3, step, 0), (4, 1, 0))
    scored = []
    for aid, sx, sy in deltas:
        scored.append((sx * dx + sy * dy, aid))
    scored.sort(key=lambda item: (-item[0], item[1]))
    return [aid for _score, aid in scored]


def _quantum_of(state) -> int:
    try:
        value = int((state or {}).get("route_quantum") or 0)
    except (TypeError, ValueError):
        return 0
    if value < 1:
        return 0
    return value


def _block_set(state) -> set:
    found = set()
    for item in (state or {}).get("route_blocks") or []:
        if not isinstance(item, (list, tuple)) or len(item) < 3:
            continue
        try:
            found.add((int(item[0]), int(item[1]), int(item[2])))
        except (TypeError, ValueError):
            continue
    return found


def _blocked_at(blocks: set, box) -> set:
    ox, oy = int(box[0]), int(box[1])
    return {aid for x, y, aid in blocks if x == ox and y == oy}


def _shift(aid: int, quantum: int):
    back = _neg()
    if aid == 1:
        return (0, back * quantum)
    if aid == 2:
        return (0, quantum)
    if aid == 3:
        return (back * quantum, 0)
    if aid == 4:
        return (quantum, 0)
    return None


def _snap(value: int, origin: int, quantum: int) -> int:
    if quantum < 1:
        return value
    delta = int(value) - int(origin)
    steps = int(round(delta / quantum))
    return int(origin) + steps * quantum


def _around(mover, target, quantum: int, blocks: set, legal: list[int], walls: list):
    """First step of a path that treats known blocked edges as walls."""
    sx, sy = int(mover[0]), int(mover[1])
    gx = _snap(int(target[0]), sx, quantum)
    gy = _snap(int(target[1]), sy, quantum)
    if (sx, sy) == (gx, gy):
        return None
    options = set(_dpad(legal))
    order = _dir_order(gx - sx, gy - sy)
    start = (sx, sy)
    came = {start: None}
    queue = [start]
    found = None
    limit = 6 * 6 * 6
    head = 0
    while head < len(queue) and len(came) < limit:
        x, y = queue[head]
        head = head + 1
        if (x, y) == (gx, gy):
            found = (x, y)
            break
        ranked = []
        for aid in order:
            if aid not in options:
                continue
            if (x, y, aid) in blocks:
                continue
            shift = _shift(aid, quantum)
            if shift is None:
                continue
            nxt = (x + shift[0], y + shift[1])
            probe = _ahead((x, y, int(mover[2]), int(mover[3])), aid)
            if probe is not None and any(_overlap(probe, wall) for wall in walls):
                continue
            ranked.append((abs(nxt[0] - gx) + abs(nxt[1] - gy), aid, nxt))
        ranked.sort()
        for _dist, aid, nxt in ranked:
            if nxt in came:
                continue
            came[nxt] = (x, y, aid)
            queue.append(nxt)
    if found is None:
        return None
    node = found
    first = None
    while node != start:
        parent = came.get(node)
        if parent is None:
            return None
        _px, _py, aid = parent
        first = aid
        node = (_px, _py)
    return first


def _mover_box(state, records):
    obs = (state or {}).get("schema_obs") or {}
    role = str((state or {}).get("step_role") or "")
    if not role or role == "none":
        role = "avatar"
    boxes = _boxes_for(records, _role_geom(obs, role))
    if len(boxes) != 1:
        return None
    return boxes[0]


def blocked_dirs(state) -> set:
    """Directions already blocked at the current mover. Ephemeral; not a schema."""
    box = _mover_box(state, (state or {}).get("frame_records") or [])
    found = set()
    if box is not None:
        found.update(_blocked_at(_block_set(state), box))
    for item in (state or {}).get("blocked_here") or []:
        try:
            found.add(int(item))
        except (TypeError, ValueError):
            continue
    return found


def _seal(state, box) -> None:
    quantum = _quantum_of(state)
    if quantum < 1:
        return
    here = _blocked_at(_block_set(state), box)
    if len(here) < 3:
        return
    prev = (state or {}).get("route_prev")
    if not isinstance(prev, (list, tuple)) or len(prev) < 3:
        return
    try:
        px, py, aid = int(prev[0]), int(prev[1]), int(prev[2])
    except (TypeError, ValueError):
        return
    shift = _shift(aid, quantum)
    if shift is None:
        return
    if (px + shift[0], py + shift[1]) != (int(box[0]), int(box[1])):
        return
    entry = [px, py, aid]
    store = state.setdefault("route_blocks", [])
    if entry not in store:
        store.append(entry)


def note_route(state, before, after, aid: int, moved: bool) -> None:
    """A failed step stays blocked at that cell. A move teaches the step size."""
    if not isinstance(state, dict):
        return
    origin = _mover_box(state, before)
    if origin is None:
        return
    if not moved:
        entry = [int(origin[0]), int(origin[1]), int(aid)]
        store = state.setdefault("route_blocks", [])
        if entry not in store:
            store.append(entry)
        _seal(state, origin)
        return
    landed = _mover_box(state, after)
    if landed is None:
        return
    dx = int(landed[0]) - int(origin[0])
    dy = int(landed[1]) - int(origin[1])
    dist = abs(dx) if abs(dx) >= abs(dy) else abs(dy)
    if dist > 0 and not _quantum_of(state):
        state["route_quantum"] = dist
    state["route_prev"] = [int(origin[0]), int(origin[1]), int(aid)]


def step_toward(name: str, legal: list[int], state: dict):
    """One d-pad step toward the bound target. None when that target has no unique box."""
    if name not in ("approach", "convey", "route"):
        return None
    obs = (state or {}).get("schema_obs") or {}
    records = (state or {}).get("frame_records") or []
    mover_role = str((state or {}).get("step_role") or "")
    target_role = str((state or {}).get("step_target") or "")
    if name == "convey" and not mover_role:
        mover_role = "movable"
    if not mover_role:
        mover_role = "avatar"
    if not target_role or target_role == "none":
        target_role = "goal" if name != "route" else "wall"
    if target_role == "goal" and _role_geom(obs, "goal") is None:
        return None
    mover_boxes = _boxes_for(records, _role_geom(obs, mover_role))
    target_boxes = _boxes_for(records, _role_geom(obs, target_role))
    if len(mover_boxes) != 1 or len(target_boxes) != 1:
        return None
    mover = mover_boxes[0]
    target = target_boxes[0]
    walls = _boxes_for(records, _role_geom(obs, "wall"))
    blocked = blocked_dirs(state)
    options = _dpad(legal)
    quantum = _quantum_of(state)
    if quantum:
        aimed = _around(mover, target, quantum, _block_set(state), options, walls)
        if aimed is not None and aimed not in blocked and aimed in options:
            return aimed
    cx = mover[0] + mover[2] // 2
    cy = mover[1] + mover[3] // 2
    gx = target[0] + target[2] // 2
    gy = target[1] + target[3] // 2
    for aid in _dir_order(gx - cx, gy - cy):
        if aid not in options or aid in blocked:
            continue
        probe = _ahead(mover, aid)
        if probe is not None and any(_overlap(probe, wall) for wall in walls):
            continue
        return aid
    return None


def precondition(name: str, obs: dict, state: dict) -> bool:
    roles = _roles(obs)
    rels = _relations(obs)
    progress = state.get("progress_axis")
    if name == "approach":
        return "avatar" in roles and "goal" in roles
    if name == "hold_gradient":
        return progress in _REVERSE and "avatar" in roles
    if name == "convey":
        return "movable" in roles and ("goal" in roles or "receptor" in roles)
    if name == "align":
        return "receptor" in roles or "reference" in roles or "shape_match" in rels
    if name == "toggle":
        return "switch" in roles or "clickable" in roles or "toggle" in rels
    if name == "avoid":
        return "hazard" in roles and ("avatar" in roles or "clickable" in roles)
    if name == "cycle_select":
        return ("switch" in roles or "clickable" in roles) and (
            "goal" in roles or "receptor" in roles or "reference" in roles
        )
    if name == "route":
        return "avatar" in roles and ("wall" in roles or "containment" in rels)
    if name == "assemble":
        return (
            "movable" in roles
            or ("receptor" in roles and "avatar" in roles)
            or ("clickable" in roles and ("reference" in roles or "receptor" in roles))
        )
    if name == "explore":
        return True
    return False


def _dpad(legal: list[int]) -> list[int]:
    return [aid for aid in legal if aid in _REVERSE]


def _click_at(state: dict, *roles: str):
    """A click anchor from the live affordance map. Not stored on the primitive."""
    aff = (state or {}).get("affordances") or {}
    for role in roles:
        points = aff.get(role) or []
        if isinstance(points, (list, tuple)) and points:
            point = points[0]
            if isinstance(point, (list, tuple)) and len(point) == 2:
                return ("CLICK", int(point[0]), int(point[1]))
    return None


def action_legal(key, legal: list[int]) -> bool:
    if not key:
        return False
    if key[0] == "CLICK":
        return 6 in legal
    if key[0] == "SIMPLE":
        try:
            return int(key[1]) in legal
        except (TypeError, ValueError, IndexError):
            return False
    return False


def repair_action(key, legal: list[int], primitive: str, state: dict):
    """Keep a proposal only when it is legal. Otherwise substitute a legal pattern."""
    if action_legal(key, legal):
        return key, False
    for name in (primitive, "explore"):
        if name not in NAMES and name != "explore":
            continue
        alt = suggest_action(name if name in NAMES else "explore", legal, state)
        if action_legal(alt, legal):
            return alt, True
    for aid in legal:
        if aid in _REVERSE or aid == 5:
            return ("SIMPLE", int(aid)), True
    click = _click_at(state, "clickable", "switch", "reference", "receptor")
    if click is not None and 6 in legal:
        return click, True
    return None, True


def suggest_action(name: str, legal: list[int], state: dict):
    """An action id pattern. Explore is the only primitive that may leave the gradient."""
    progress = state.get("progress_axis")
    reverse = _REVERSE.get(progress)
    options = _dpad(legal)
    if name in ("approach", "convey", "route") and (state.get("step_target") or state.get("step_role")):
        aimed = step_toward(name, legal, state)
        if aimed is not None:
            return ("SIMPLE", int(aimed))
        return None
    if name in ("approach", "hold_gradient", "convey", "route"):
        if progress in options:
            return ("SIMPLE", int(progress))
        for aid in options:
            if aid != reverse:
                return ("SIMPLE", int(aid))
        if options:
            return ("SIMPLE", int(options[0]))
        return _click_at(state, "clickable", "switch", "reference")
    if name == "avoid":
        blocked = state.get("hazard_axis")
        for aid in options:
            if aid != blocked and aid != reverse:
                return ("SIMPLE", int(aid))
        if options:
            return ("SIMPLE", int(options[0]))
        return _click_at(state, "avatar", "clickable")
    if name in ("toggle", "cycle_select"):
        if 5 in legal and not state.get("step_role"):
            return ("SIMPLE", 5)
        index = 0
        try:
            index = int(state.get("anchor_i") or 0)
        except (TypeError, ValueError):
            index = 0
        if index < 0:
            index = 0
        roles = []
        for role in (state.get("step_role"), state.get("step_target"), "switch", "clickable"):
            if role and role not in roles and role != "none":
                roles.append(role)
        aff = (state or {}).get("affordances") or {}
        for role in roles:
            points = aff.get(role) or []
            if not isinstance(points, (list, tuple)) or index >= len(points):
                continue
            point = points[index]
            if isinstance(point, (list, tuple)) and len(point) == 2:
                return ("CLICK", int(point[0]), int(point[1]))
        return _click_at(state, "switch", "clickable", "reference")
    if name in ("align", "assemble"):
        if progress in options:
            return ("SIMPLE", int(progress))
        if 5 in legal:
            return ("SIMPLE", 5)
        if options:
            return ("SIMPLE", int(options[0]))
        return _click_at(state, "clickable", "switch", "movable", "reference")
    if name == "explore":
        for aid in options:
            if aid != progress:
                return ("SIMPLE", int(aid))
        if 5 in legal:
            return ("SIMPLE", 5)
        return _click_at(state, "clickable", "switch", "reference", "avatar")
    return None


def _confidence(state: dict, name: str) -> float:
    table = state.get("primitive_confidence")
    if not isinstance(table, dict):
        return 1.0
    try:
        return float(table.get(name, 1.0))
    except (TypeError, ValueError):
        return 1.0


def applicable(obs: dict, state: dict, legal: list[int]) -> list[dict]:
    """Primitives whose precondition holds and whose confidence is still usable."""
    found = []
    for name in NAMES:
        if name == "explore":
            continue
        if not precondition(name, obs, state):
            continue
        if _confidence(state, name) < 0.25:
            continue
        action = suggest_action(name, legal, state)
        if action is None:
            continue
        from monad2.predicates import bind_predicate, render

        pred = bind_predicate(name, action, obs, None)
        found.append(
            {
                "id": name,
                "binding": _binding_text(name, obs),
                "effect": _EFFECT[name],
                "predicate": render(pred),
                "action": action,
                "confidence": _confidence(state, name),
            }
        )
    explore = suggest_action("explore", legal, state)
    found.append(
        {
            "id": "explore",
            "binding": "",
            "effect": _EFFECT["explore"],
            "action": explore,
            "confidence": _confidence(state, "explore"),
            "labeled": True,
        }
    )
    return found


def _binding_text(name: str, obs: dict) -> str:
    have = _roles(obs)
    picked = []
    for role in _BINDING.get(name, ()):
        if role in have:
            picked.append(role)
        elif role == "receptor" and "reference" in have:
            picked.append("reference")
        elif role == "avatar" and "clickable" in have and name in ("align", "toggle", "assemble"):
            picked.append("clickable")
        elif role == "goal" and "goal" in have:
            picked.append("goal")
    if name in ("toggle", "cycle_select", "align") and "clickable" in have and "clickable" not in picked:
        picked.insert(0, "clickable")
    return ",".join(picked or _BINDING.get(name, ()))


def line(items: list[dict]) -> str:
    parts = []
    for item in items:
        if item["id"] == "explore":
            continue
        parts.append(
            f"{item['id']} binds {item['binding'] or 'none'} "
            f"{item.get('predicate') or item['effect']} conf {item['confidence']:.1f}"
        )
    if not parts:
        return "no motion primitive yet; explore is the labeled fallback"
    return "; ".join(parts[:4])


def proposals_for(obs: dict, state: dict, legal: list[int]) -> tuple[str, list[dict]]:
    items = applicable(obs, state or {}, legal)
    return line(items), items


def contradicts_gradient(name: str, action, state: dict) -> bool:
    """True when a non-explore primitive would undo the last productive step."""
    if name == "explore":
        return False
    progress = state.get("progress_axis")
    if progress not in _REVERSE or not action:
        return False
    try:
        aid = int(action[1])
    except (TypeError, ValueError, IndexError):
        return False
    return aid == _REVERSE[progress]


def credit(state: dict, name: str, hit: bool | None, action=None) -> tuple[float, str]:
    """Raise or lower confidence from the expectation diff. Explore does not become a habit."""
    if name not in NAMES:
        return 0.0, "unchecked"
    table = state.get("primitive_confidence")
    if not isinstance(table, dict):
        table = {}
        state["primitive_confidence"] = table
    value = _confidence(state, name)
    if hit is True:
        value = min(3.0, value + 0.25)
        note = "confirmed"
        if name in ("approach", "convey", "route") and action and action[0] == "SIMPLE":
            try:
                aid = int(action[1])
            except (TypeError, ValueError, IndexError):
                aid = 0
            if aid in _REVERSE:
                state["progress_axis"] = aid
        if name == "avoid" and action and action[0] == "SIMPLE":
            state["hazard_axis"] = None
    elif hit is False:
        value = max(0.0, value - 0.5)
        note = "demoted"
        if name == "avoid" and action and action[0] == "SIMPLE":
            try:
                state["hazard_axis"] = int(action[1])
            except (TypeError, ValueError, IndexError):
                pass
        if name in ("approach", "convey", "route"):
            state["progress_axis"] = None
    else:
        note = "unchecked"
    table[name] = value
    return value, note


def known(name: str) -> bool:
    return name in NAMES


def effect_of(name: str) -> str:
    return _EFFECT.get(name, "")


def source_violations(path: Path | None = None) -> list[str]:
    """Fail on game ids, fingerprints, palette entries, or coordinates in this file."""
    from monad2.general_guard import KNOWN_GAME_PREFIXES

    src = path or Path(__file__)
    tree = ast.parse(src.read_text(encoding="utf-8"), filename=str(src))
    found = []
    banned_names = {
        "game_id",
        "fingerprint",
        "sig",
        "color",
        "fill_color",
        "palette",
        "coord",
        "click_x",
        "click_y",
    }
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            tokens = set(node.value.lower().replace(",", " ").split())
            hit = tokens & KNOWN_GAME_PREFIXES
            if node.value.lower() in KNOWN_GAME_PREFIXES:
                hit = set(hit)
                hit.add(node.value.lower())
            if hit:
                found.append(f"{src.name}:{node.lineno}: game id {sorted(hit)}")
        if isinstance(node, ast.Constant) and isinstance(node.value, int) and not isinstance(node.value, bool):
            if int(node.value) not in (0, 1, 2, 3, 4, 5, 6):
                found.append(f"{src.name}:{node.lineno}: literal {node.value}")
        if isinstance(node, ast.Name) and node.id.lower() in banned_names:
            found.append(f"{src.name}:{node.lineno}: name {node.id}")
    return found
