"""Legal action menu for one frame.

The executive picks an index or a role reference. Coordinates stay on the
ephemeral item and are never written into a schema or a plan.
"""
from __future__ import annotations

import re

_SIMPLE = {1: "up", 2: "down", 3: "left", 4: "right", 5: "interact"}
_CLICK_ROLES = ("clickable", "switch", "reference", "receptor", "goal", "movable", "avatar")
_LIMIT = 6


def build_menu(legal: list[int] | None, affordances: dict | None) -> list[dict]:
    """Indexed choices. A click-only legal set has no directional entries."""
    items: list[dict] = []
    allowed = []
    for aid in legal or []:
        try:
            number = int(aid)
        except (TypeError, ValueError):
            continue
        if number not in allowed:
            allowed.append(number)
    for aid, label in _SIMPLE.items():
        if aid not in allowed or len(items) >= _LIMIT:
            continue
        items.append(
            {
                "index": len(items),
                "ref": f"simple#{aid}",
                "key": ("SIMPLE", aid),
                "role": "avatar",
                "label": label,
            }
        )
    if 6 in allowed:
        aff = affordances or {}
        for role in _CLICK_ROLES:
            points = aff.get(role) or []
            if not isinstance(points, (list, tuple)):
                continue
            for ordinal, point in enumerate(points):
                if len(items) >= _LIMIT:
                    break
                if not isinstance(point, (list, tuple)) or len(point) != 2:
                    continue
                try:
                    key = ("CLICK", int(point[0]), int(point[1]))
                except (TypeError, ValueError):
                    continue
                items.append(
                    {
                        "index": len(items),
                        "ref": f"click({role}#{ordinal})",
                        "key": key,
                        "role": role,
                        "label": f"click {role}#{ordinal}",
                    }
                )
            if len(items) >= _LIMIT:
                break
    return items


def menu_line(items: list[dict]) -> str:
    if not items:
        return "none"
    return " | ".join(f"{item['index']} {item['ref']}" for item in items)


def resolve_choice(raw, items: list[dict], legal: list[int] | None) -> tuple | None:
    """Map a menu index or a role reference to an action. Legacy SIMPLE text still parses."""
    if raw is None:
        return None
    text = str(raw).strip().strip('"')
    if not text:
        return None
    folded = text.lower().replace(" ", "")
    for item in items or []:
        if text == str(item["index"]) or folded == str(item["ref"]).lower():
            return item["key"]
    click = re.search(r"click\(([a-z_]+)#(\d+)\)", folded)
    if click:
        ref = f"click({click.group(1)}#{click.group(2)})"
        for item in items or []:
            if item["ref"] == ref:
                return item["key"]
    simple = re.search(r"simple#(\d+)", folded)
    if simple:
        ref = f"simple#{simple.group(1)}"
        for item in items or []:
            if item["ref"] == ref:
                return item["key"]
    return _legacy(text, legal)


def _legacy(text: str, legal: list[int] | None):
    allowed = []
    for aid in legal or []:
        try:
            number = int(aid)
        except (TypeError, ValueError):
            continue
        if number not in allowed:
            allowed.append(number)
    upper = text.upper()
    click = re.search(r"CLICK\s+(\d+)\s+(\d+)", upper)
    if click and 6 in allowed:
        return ("CLICK", int(click.group(1)), int(click.group(2)))
    simple = re.search(r"\b([1-6])\b", upper)
    if not simple:
        return None
    aid = int(simple.group(1))
    if aid == 6:
        return None
    if aid not in allowed:
        return None
    return ("SIMPLE", aid)


def _term(text: str) -> str:
    return '"\\"' + text + '\\""'


def executive_grammar(items: list[dict]) -> str:
    """GBNF whose action field is only a menu index or a role reference."""
    from monad2.llm import _GRAMMAR

    choices = []
    for item in items:
        choices.append(_term(str(item["index"])))
        choices.append(_term(item["ref"]))
    action = "action ::= " + (" | ".join(choices) if choices else _term("0"))
    lines = []
    for line in _GRAMMAR["executive"].splitlines():
        if line.startswith("action ::="):
            lines.append(action)
        elif line:
            lines.append(line)
    return "\n".join(lines) + "\n"
