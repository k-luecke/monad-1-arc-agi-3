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
        return "receptor" in roles or "shape_match" in rels
    if name == "toggle":
        return "switch" in roles or "toggle" in rels
    if name == "avoid":
        return "hazard" in roles and "avatar" in roles
    if name == "cycle_select":
        return "switch" in roles and ("goal" in roles or "receptor" in roles)
    if name == "route":
        return "avatar" in roles and ("wall" in roles or "containment" in rels)
    if name == "assemble":
        return "movable" in roles or ("receptor" in roles and "avatar" in roles)
    if name == "explore":
        return True
    return False


def _dpad(legal: list[int]) -> list[int]:
    return [aid for aid in legal if aid in _REVERSE]


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
        return ("SIMPLE", int(options[0])) if options else None
    if name == "avoid":
        blocked = state.get("hazard_axis")
        for aid in options:
            if aid != blocked and aid != reverse:
                return ("SIMPLE", int(aid))
        return ("SIMPLE", int(options[0])) if options else None
    if name in ("toggle", "cycle_select"):
        if 5 in legal:
            return ("SIMPLE", 5)
        return None
    if name in ("align", "assemble"):
        if progress in options:
            return ("SIMPLE", int(progress))
        if 5 in legal:
            return ("SIMPLE", 5)
        return ("SIMPLE", int(options[0])) if options else None
    if name == "explore":
        for aid in options:
            if aid != progress:
                return ("SIMPLE", int(aid))
        if 5 in legal:
            return ("SIMPLE", 5)
        return None
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
        found.append(
            {
                "id": name,
                "binding": ",".join(_BINDING[name]),
                "effect": _EFFECT[name],
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


def line(items: list[dict]) -> str:
    parts = []
    for item in items:
        if item["id"] == "explore":
            continue
        parts.append(
            f"{item['id']} binds {item['binding'] or 'none'} "
            f"effect {item['effect']} conf {item['confidence']:.1f}"
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
