"""Checkable canvas predicates for a motor primitive.

The executive's expected effect is one of these forms, with roles filled from
the live binding. Free text stays a comment. Confirmation uses the predicate
result against the document diff.
"""
from __future__ import annotations

KINDS = ("translate", "no_reverse", "contact", "match", "changed", "unchanged")
DIRS = ("up", "down", "left", "right", "none")
AXES = ("x", "y", "none")

# kind, primary role, second role. A missing live role falls through the aliases.
_TEMPLATES = {
    "approach": ("translate", "avatar", "goal"),
    "hold_gradient": ("no_reverse", "avatar", "none"),
    "convey": ("translate", "movable", "goal"),
    "align": ("match", "clickable", "reference"),
    "toggle": ("changed", "switch", "none"),
    "avoid": ("unchanged", "hazard", "none"),
    "cycle_select": ("match", "clickable", "reference"),
    "route": ("translate", "avatar", "wall"),
    "assemble": ("contact", "movable", "receptor"),
    "explore": ("changed", "clickable", "none"),
}

_ALIASES = {
    "clickable": ("clickable", "switch", "avatar"),
    "reference": ("reference", "receptor", "goal"),
    "switch": ("switch", "clickable"),
    "receptor": ("receptor", "reference", "goal"),
    "goal": ("goal", "receptor", "reference"),
    "avatar": ("avatar",),
    "movable": ("movable", "avatar"),
    "hazard": ("hazard",),
    "wall": ("wall",),
}

_OPP = {"left": "right", "right": "left", "up": "down", "down": "up"}


def _roles(obs: dict) -> set[str]:
    return {str(slot.get("role")) for slot in (obs or {}).get("roles") or [] if slot.get("role")}


def _present(role: str, have: set[str]) -> str:
    if role == "none":
        return "none"
    for name in _ALIASES.get(role, (role,)):
        if name in have:
            return name
    return role


def _geom_of(obs: dict, role: str):
    if role == "none":
        return None
    for slot in (obs or {}).get("roles") or []:
        if slot.get("role") == role and slot.get("geom") and len(slot["geom"]) == 3:
            return [int(v) for v in slot["geom"]]
    return None


def _dir_of(action) -> str:
    if not action or action[0] != "SIMPLE":
        return "none"
    try:
        aid = int(action[1])
    except (TypeError, ValueError, IndexError):
        return "none"
    return {1: "up", 2: "down", 3: "left", 4: "right"}.get(aid, "none")


def _axis_of(direction: str) -> str:
    if direction in ("left", "right"):
        return "x"
    if direction in ("up", "down"):
        return "y"
    return "none"


def bind_predicate(name: str, action, obs: dict, model: dict | None = None) -> dict | None:
    """Fill the primitive's predicate template from the live roles and the action."""
    template = _TEMPLATES.get(name)
    if template is None:
        return None
    kind, role, role_b = template
    have = _roles(obs)
    role = _present(role, have)
    role_b = _present(role_b, have)
    model = model or {}
    model_kind = str(model.get("predicate") or "")
    model_role = str(model.get("role") or "")
    model_b = str(model.get("role_b") or "")
    if model_kind == kind and model_role in have:
        role = model_role
    if model_kind == kind and model_b in have:
        role_b = model_b
    direction = _dir_of(action)
    if kind not in ("translate", "no_reverse"):
        direction = "none"
    axis = _axis_of(direction) if kind == "no_reverse" else "none"
    if kind == "translate":
        axis = "none"
    return {
        "kind": kind,
        "role": role,
        "role_b": role_b,
        "dir": direction,
        "axis": axis,
        "geom": _geom_of(obs, role),
        "geom_b": _geom_of(obs, role_b),
    }


def render(pred: dict | None) -> str:
    if not pred or pred.get("kind") not in KINDS:
        return ""
    kind = pred["kind"]
    role = pred.get("role") or "none"
    other = pred.get("role_b") or "none"
    if kind == "translate":
        return f"translate(role={role}, dir={pred.get('dir') or 'none'})"
    if kind == "no_reverse":
        return f"no_reverse(role={role}, axis={pred.get('axis') or 'none'})"
    if kind == "contact":
        return f"contact(roleA={role}, roleB={other})"
    if kind == "match":
        return f"match(object={role}, reference={other})"
    if kind == "changed":
        return f"changed(role={role})"
    return f"unchanged(role={role})"


def _geom(rec: dict):
    raw = rec.get("geom")
    if not raw or len(raw) != 3:
        return None
    return (int(raw[0]), int(raw[1]), int(raw[2]))


def _bbox(rec: dict):
    xy = rec.get("xy")
    wh = rec.get("wh")
    if not xy or not wh:
        return None
    return (int(xy[0]), int(xy[1]), int(wh[0]), int(wh[1]))


def _fill(rec: dict):
    sig = rec.get("sig") or ()
    if len(sig) < 2:
        return None
    try:
        return int(sig[1])
    except (TypeError, ValueError):
        return None


def _with_geom(records: list[dict], geom) -> list[dict]:
    if not geom or len(geom) != 3:
        return []
    want = (int(geom[0]), int(geom[1]), int(geom[2]))
    return [rec for rec in records or [] if _geom(rec) == want]


def _deltas(before: list[dict], after: list[dict], geom) -> list[tuple[int, int]] | None:
    """Motion of shapes with this geom. None when the role is not in the before frame."""
    targets = _with_geom(before, geom)
    if not targets:
        return None
    pools: dict[tuple, list[dict]] = {}
    for rec in after or []:
        pools.setdefault(tuple(rec.get("sig") or ()), []).append(rec)
    used: set[int] = set()
    out = []
    for rec in targets:
        pool = pools.get(tuple(rec.get("sig") or ()), [])
        choice = None
        best = None
        for other in pool:
            if id(other) in used:
                continue
            box = _bbox(rec)
            obox = _bbox(other)
            if box is None or obox is None:
                dist = 0
            else:
                dist = abs(obox[0] - box[0]) + abs(obox[1] - box[1])
            if best is None or dist < best:
                best = dist
                choice = other
        if choice is None:
            continue
        used.add(id(choice))
        box = _bbox(rec)
        obox = _bbox(choice)
        if box is None or obox is None:
            continue
        out.append((obox[0] - box[0], obox[1] - box[1]))
    return out


def _dir_ok(dx: int, dy: int, direction: str) -> bool:
    if direction == "left":
        return dx < 0 and abs(dx) >= abs(dy)
    if direction == "right":
        return dx > 0 and abs(dx) >= abs(dy)
    if direction == "up":
        return dy < 0 and abs(dy) >= abs(dx)
    if direction == "down":
        return dy > 0 and abs(dy) >= abs(dx)
    return False


def _moved_apart(before: list[dict], after: list[dict], geom) -> bool | None:
    """True when a shape with this geom translated, vanished, or appeared."""
    deltas = _deltas(before, after, geom)
    if deltas is None:
        return True if _with_geom(after, geom) else None
    if any(dx or dy for dx, dy in deltas):
        return True
    if len(_with_geom(before, geom)) != len(_with_geom(after, geom)):
        return True
    return False


def _touching(a, b) -> bool:
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    gap_x = max(0, max(ax, bx) - min(ax + aw, bx + bw))
    gap_y = max(0, max(ay, by) - min(ay + ah, by + bh))
    return gap_x <= 1 and gap_y <= 1


def evaluate(pred: dict | None, before: list[dict], after: list[dict]) -> bool | None:
    """True when the document shows the predicate. None when the role is unbound."""
    if not pred or pred.get("kind") not in KINDS:
        return None
    kind = pred["kind"]
    geom = pred.get("geom")
    other = pred.get("geom_b")
    if kind == "translate":
        deltas = _deltas(before, after, geom)
        if not deltas:
            return False if deltas == [] else None
        return any(_dir_ok(dx, dy, str(pred.get("dir") or "")) for dx, dy in deltas)
    if kind == "no_reverse":
        deltas = _deltas(before, after, geom)
        if deltas is None:
            return None
        banned = _OPP.get(str(pred.get("dir") or ""), "")
        if not banned:
            return not any(dx or dy for dx, dy in deltas)
        return not any(_dir_ok(dx, dy, banned) for dx, dy in deltas)
    if kind == "changed":
        return _moved_apart(before, after, geom)
    if kind == "unchanged":
        changed = _moved_apart(before, after, geom)
        if changed is None:
            return None
        return not changed
    if kind == "contact":
        left = [box for rec in _with_geom(after, geom) if (box := _bbox(rec)) is not None]
        right = [box for rec in _with_geom(after, other) if (box := _bbox(rec)) is not None]
        if not left or not right:
            return False
        return any(_touching(a, b) for a in left for b in right)
    if kind == "match":
        objs = _with_geom(after, geom)
        refs = _with_geom(after, other)
        if not objs or not refs:
            return False
        for obj in objs:
            og = _geom(obj)
            of = _fill(obj)
            for ref in refs:
                rg = _geom(ref)
                if og is not None and og == rg:
                    return True
                if of is not None and of == _fill(ref) and og and rg and og[0] == rg[0]:
                    return True
        return False
    return None
