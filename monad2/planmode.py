"""Plan once, then execute until a surprise.

The executive writes primitive steps with bindings and a predicate. Code expands
each step into legal actions and checks the predicate on the document diff.
Models are called again only for a new plan. The plan is live for this level:
no game id, no coordinates, no stored action sequence.
"""
from __future__ import annotations

import re

from monad2.predicates import KINDS, bind_predicate, render
from monad2.primitives import NAMES, precondition, suggest_action

_STALL = 4
_DISCOVER = 2

PLAN_SYSTEM = (
    "You are Mistral. Write a level plan as primitive steps. "
    "Each step has primitive, binding, predicate, role, role_b, and repeat from 1 to 6. "
    "predicate is translate, no_reverse, contact, match, changed, or unchanged. "
    "No coordinates and no stored route. "
    'JSON: {"goal":"REACH","steps":[{"primitive":"approach","binding":"avatar,goal",'
    '"predicate":"translate","role":"avatar","role_b":"goal","repeat":4}]}'
)

_STEP = re.compile(
    r'"primitive"\s*:\s*"(?P<prim>[a-z_]+)"\s*,\s*"binding"\s*:\s*"(?P<bind>[^"]*)"\s*,\s*'
    r'"predicate"\s*:\s*"(?P<pred>[a-z_]+)"\s*,\s*"role"\s*:\s*"(?P<role>[a-z_]+)"\s*,\s*'
    r'"role_b"\s*:\s*"(?P<roleb>[a-z_]+)"\s*,\s*"repeat"\s*:\s*(?P<rep>[1-6])',
)


def plan_grammar() -> str:
    return r'''
ws ::= " "?
string ::= "\"" ([^"\\\n ] | " "){0,24} "\""
goal ::= "\"REACH\"" | "\"PLACE\"" | "\"MATCH\""
prim ::= "\"approach\"" | "\"hold_gradient\"" | "\"convey\"" | "\"align\"" | "\"toggle\"" | "\"avoid\"" | "\"cycle_select\"" | "\"route\"" | "\"assemble\""
predkind ::= "\"translate\"" | "\"no_reverse\"" | "\"contact\"" | "\"match\"" | "\"changed\"" | "\"unchanged\""
role ::= "\"avatar\"" | "\"movable\"" | "\"goal\"" | "\"receptor\"" | "\"switch\"" | "\"hazard\"" | "\"wall\"" | "\"clickable\"" | "\"reference\"" | "\"none\""
digit ::= "1" | "2" | "3" | "4" | "5" | "6"
step ::= "{" ws "\"primitive\"" ws ":" ws prim ws "," ws "\"binding\"" ws ":" ws string ws "," ws "\"predicate\"" ws ":" ws predkind ws "," ws "\"role\"" ws ":" ws role ws "," ws "\"role_b\"" ws ":" ws role ws "," ws "\"repeat\"" ws ":" ws digit ws "}"
root ::= "{" ws "\"goal\"" ws ":" ws goal ws "," ws "\"steps\"" ws ":" ws "[" ws step (ws "," ws step){0,4} ws "]" ws "}"
'''


def ready(state: dict) -> bool:
    """Roles have held for two discovery steps and a goal-like role is bound."""
    if int(state.get("discover_steps") or 0) < _DISCOVER:
        return False
    if not state.get("stable_roles"):
        return False
    roles = {str(slot.get("role")) for slot in (state.get("schema_obs") or {}).get("roles") or [] if slot.get("role")}
    controllable = bool(roles & {"avatar", "clickable", "switch"})
    goalish = bool(roles & {"goal", "receptor", "reference"})
    return controllable and goalish


def note_discovery(state: dict) -> None:
    line = state.get("role_line") or ""
    state["stable_roles"] = line if line and line == state.get("prev_roles") else ""
    state["prev_roles"] = line
    state["discover_steps"] = int(state.get("discover_steps") or 0) + 1


def parse_plan(text: str, obs: dict, state: dict) -> list[dict]:
    """Steps the live roles can run. Digits in a binding are rejected."""
    steps = []
    for match in _STEP.finditer(text or ""):
        name = match.group("prim")
        if name not in NAMES or name == "explore":
            continue
        binding = match.group("bind")
        if any(ch.isdigit() for ch in binding):
            continue
        kind = match.group("pred")
        if kind not in KINDS:
            continue
        if not precondition(name, obs, state):
            continue
        role = match.group("role")
        role_b = match.group("roleb")
        repeat = int(match.group("rep"))
        steps.append(
            {
                "primitive": name,
                "binding": binding,
                "kind": kind,
                "role": role,
                "role_b": role_b,
                "repeat": repeat,
                "tries": 0,
                "tried": [],
            }
        )
        if len(steps) >= 5:
            break
    return steps


def plan_text(steps: list[dict]) -> str:
    parts = []
    for step in steps:
        parts.append(f"{step['primitive']}({step['binding'] or step['role']})")
    return " -> ".join(parts)


def current_step(state: dict) -> dict | None:
    steps = state.get("script") or []
    index = int(state.get("script_i") or 0)
    if index < 0 or index >= len(steps):
        return None
    return steps[index]


def _ref_for(key, items: list[dict]) -> str:
    for item in items:
        if item["key"] == key:
            return item["ref"]
    return ""


def expand_action(step: dict, legal: list[int], state: dict, items: list[dict]):
    """One legal action for this primitive. Tried references are skipped."""
    from monad2.menu import build_menu

    tried = set(step.get("tried") or [])
    menu = items or build_menu(legal, state.get("affordances") or {})
    preferred = suggest_action(step.get("primitive") or "", legal, state)
    ordered = []
    if preferred is not None:
        ordered.append(preferred)
    for item in menu:
        if item["key"] not in ordered:
            ordered.append(item["key"])
    binding = {part.strip() for part in str(step.get("binding") or "").split(",") if part.strip()}
    for key in ordered:
        ref = _ref_for(key, menu)
        if ref and ref in tried:
            continue
        if key[0] == "CLICK" and binding:
            role = next((item["role"] for item in menu if item["key"] == key), "")
            if role and role not in binding and "clickable" not in binding and "switch" not in binding:
                continue
        if ref or key[0] == "SIMPLE":
            return key, ref or f"simple#{key[1]}"
    for item in menu:
        if item["ref"] not in tried:
            return item["key"], item["ref"]
    return None, ""


def predicate_for(step: dict, action, obs: dict) -> dict | None:
    model = {"predicate": step.get("kind"), "role": step.get("role"), "role_b": step.get("role_b")}
    return bind_predicate(step.get("primitive") or "", action, obs, model)


def _wrong_way(pred: dict | None, before, after) -> bool:
    if not pred or pred.get("kind") != "translate":
        return False
    from monad2.predicates import _deltas, _dir_ok

    deltas = _deltas(list(before or []), list(after or []), pred.get("geom"))
    if not deltas:
        return False
    return not any(_dir_ok(dx, dy, str(pred.get("dir") or "")) for dx, dy in deltas)


def note_result(state: dict, pred_hit, action, outcome: str, before=None, after=None) -> None:
    """Advance a step, or mark a surprise that the next decision must replan."""
    if state.get("mode") != "execute":
        return
    step = current_step(state)
    if step is None:
        return
    if outcome == "reset":
        state["surprise_pending"] = "level reset"
        return
    if pred_hit is True:
        state["stall_steps"] = 0
        state["script_i"] = int(state.get("script_i") or 0) + 1
        if current_step(state) is None:
            state["script"] = []
            state["mode"] = "discover"
            state["discover_steps"] = 0
            state["stable_roles"] = ""
        return
    step["tries"] = int(step.get("tries") or 0) + 1
    ref = state.get("last_ref") or ""
    if ref and ref not in step["tried"]:
        step["tried"].append(ref)
    state["stall_steps"] = int(state.get("stall_steps") or 0) + 1
    kind = step.get("kind")
    wrong = _wrong_way(state.get("plan_predicate"), before, after)
    # A reversed or wrong-direction move is a surprise. A blocked step retries until repeat.
    if pred_hit is False and (kind == "no_reverse" or wrong):
        state["surprise_pending"] = "predicate false"
        return
    if pred_hit is False and step["tries"] >= int(step["repeat"]):
        state["surprise_pending"] = "predicate false"
        return
    if int(state.get("stall_steps") or 0) >= _STALL:
        state["surprise_pending"] = "no progress"


def prompt(entries: dict, surprise: str) -> str:
    roles = entries.get("roles") or "none"
    primitives = entries.get("primitives") or "none"
    menu = entries.get("menu") or "none"
    theory = entries.get("theory") or ""
    bits = [
        f"Roles: {roles}.",
        f"Primitives: {primitives}.",
        f"Menu: {menu}.",
        "Write the plan for this level.",
    ]
    if theory:
        bits.append(f"Theory: {theory}.")
    if surprise:
        bits.append(f"Surprise: {surprise}. Replan from this state.")
    return " ".join(bits)


def rendered(step: dict, action, obs: dict) -> str:
    return render(predicate_for(step, action, obs))
