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


def precondition(name: str, obs: dict, state: dict) -> bool:
    roles = _roles(obs)
    rels = _relations(obs)
    progress = state.get("progress_axis")
    if name == "approach":
        return "avatar" in roles and ("goal" in roles or "receptor" in roles)
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
        if 5 in legal:
            return ("SIMPLE", 5)
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
        elif role == "goal" and "reference" in have:
            picked.append("reference")
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
