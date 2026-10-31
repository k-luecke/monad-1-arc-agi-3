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
    "repeat is how many successful steps to take. It is not a failure limit. "
    "Name the goal role only when the prompt lists goal. A hypothesis is not a goal. "
    "predicate is translate, no_reverse, contact, match, changed, or unchanged. "
    "No coordinates and no stored route. "
    'JSON: {"goal":"REACH","steps":[{"primitive":"approach","binding":"avatar,goal",'
    '"predicate":"translate","role":"avatar","role_b":"goal","repeat":4}]}'
)

_FAIL_BUDGET = 4
_WALK = ("approach", "convey", "route")
_PRESS = ("toggle", "cycle_select")

_STEP = re.compile(
    r'"primitive"\s*:\s*"(?P<prim>[a-z_]+)"\s*,\s*"binding"\s*:\s*"(?P<bind>[^"]*)"\s*,\s*'
    r'"predicate"\s*:\s*"(?P<pred>[a-z_]+)"\s*,\s*"role"\s*:\s*"(?P<role>[a-z_]+)"\s*,\s*'
    r'"role_b"\s*:\s*"(?P<roleb>[a-z_]+)"\s*,\s*"repeat"\s*:\s*(?P<rep>[1-6])',
)


def plan_grammar(click_only: bool = False) -> str:
    grammar = r'''
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
    if not click_only:
        return grammar
    from monad2.llm import drop_directional_roles

    return drop_directional_roles(grammar)


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
        if name not in NAMES:
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
                "walked": 0,
                "fails": 0,
                "anchor_i": 0,
                "fail_budget": _FAIL_BUDGET,
                "labeled": name == "explore",
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


def _target_role(step: dict) -> str:
    other = str(step.get("role_b") or "")
    role = str(step.get("role") or "")
    if other and other != "none":
        return other
    if step.get("primitive") in _PRESS:
        return role
    return ""


def _arm_step(step: dict, state: dict) -> None:
    state["step_target"] = _target_role(step)
    state["step_role"] = str(step.get("role") or "")
    state["anchor_i"] = int(step.get("anchor_i") or 0)


def _bare_ref(key) -> str:
    if key and key[0] == "SIMPLE":
        return f"simple#{int(key[1])}"
    if key and key[0] == "CLICK":
        return "click"
    return ""


def expand_action(step: dict, legal: list[int], state: dict, items: list[dict]):
    """One legal action for this primitive. A press repeats its current anchor."""
    from monad2.menu import build_menu
    from monad2.primitives import action_legal

    _arm_step(step, state)
    tried = set(step.get("tried") or [])
    menu = items or build_menu(legal, state.get("affordances") or {})
    name = step.get("primitive") or ""
    preferred = suggest_action(name, legal, state)
    if name in _WALK or name in _PRESS or name == "explore":
        if preferred is not None and action_legal(preferred, legal):
            return preferred, _ref_for(preferred, menu) or _bare_ref(preferred)
        if name in _WALK:
            from monad2.primitives import blocked_dirs

            blocked = blocked_dirs(state)
            for aid in legal:
                number = int(aid)
                if number in (1, 2, 3, 4) and number not in blocked:
                    key = ("SIMPLE", number)
                    return key, _ref_for(key, menu) or _bare_ref(key)
            return None, ""
    preferred = preferred if preferred is not None else suggest_action(name, legal, state)
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


def _advance(state: dict) -> None:
    state["stall_steps"] = 0
    state["blocked_here"] = []
    state["route_blocks"] = []
    state["route_quantum"] = 0
    state["route_prev"] = None
    state["script_i"] = int(state.get("script_i") or 0) + 1
    if current_step(state) is None:
        state["script"] = []
        state["mode"] = "discover"
        state["discover_steps"] = 0
        state["stable_roles"] = ""


def _moved_geom(before, after) -> str:
    from monad2.canvas_stream import diff_records

    diff = diff_records(list(before or []), list(after or []))
    found = []
    for move in diff.get("moved") or []:
        mark = tuple(move.get("sig") or ())
        for rec in before or []:
            if tuple(rec.get("sig") or ()) != mark:
                continue
            geom = rec.get("geom")
            if geom and len(geom) == 3:
                text = ",".join(str(int(v)) for v in geom)
                if text not in found:
                    found.append(text)
            break
    if not found:
        return "none"
    if len(found) == 1:
        return "geom " + found[0]
    return "several"


def _fmt_action(action, ref: str) -> str:
    if ref:
        return str(ref)
    if not action:
        return "none"
    if action[0] == "SIMPLE":
        return f"SIMPLE {int(action[1])}"
    if action[0] == "CLICK":
        return "CLICK"
    return str(action[0])


def _remember_failure(state: dict, step: dict, action, before, after, why: str) -> None:
    from monad2.predicates import render

    state["surprise_pending"] = why
    state["replan_context"] = {
        "predicate": render(state.get("plan_predicate")),
        "moved": _moved_geom(before, after),
        "action": _fmt_action(action, str(state.get("last_ref") or "")),
        "primitive": step.get("primitive") or "",
    }


def _budget(step: dict) -> int:
    try:
        return max(1, int(step.get("fail_budget") or _FAIL_BUDGET))
    except (TypeError, ValueError):
        return _FAIL_BUDGET


def _aff_count(state: dict, step: dict) -> int:
    aff = state.get("affordances") or {}
    best = 0
    for role in (step.get("role"), step.get("role_b"), "switch", "clickable"):
        points = aff.get(role) or []
        if isinstance(points, (list, tuple)):
            best = max(best, len(points))
    return best


def note_result(state: dict, pred_hit, action, outcome: str, before=None, after=None) -> None:
    """Walk length counts successes. The failure budget is separate."""
    if state.get("mode") != "execute":
        return
    step = current_step(state)
    if step is None:
        return
    if outcome == "reset":
        _remember_failure(state, step, action, before, after, "level reset")
        return
    name = step.get("primitive") or ""
    if name in _WALK:
        _note_walk(state, step, pred_hit, action, before, after)
        return
    if name in _PRESS:
        _note_press(state, step, pred_hit, action, before, after)
        return
    if pred_hit is True:
        step["walked"] = int(step.get("walked") or 0) + 1
        state["stall_steps"] = 0
        if step["walked"] >= int(step["repeat"]):
            _advance(state)
        return
    _note_miss(state, step, pred_hit, action, before, after)


def _note_walk(state: dict, step: dict, pred_hit, action, before, after) -> None:
    from monad2.primitives import note_route

    aid = None
    if action and action[0] == "SIMPLE":
        try:
            aid = int(action[1])
        except (TypeError, ValueError, IndexError):
            aid = None
    if pred_hit is True and not _wrong_way(state.get("plan_predicate"), before, after):
        if aid in (1, 2, 3, 4):
            note_route(state, before, after, aid, True)
        step["walked"] = int(step.get("walked") or 0) + 1
        step["fails"] = 0
        state["blocked_here"] = []
        state["stall_steps"] = 0
        if step["walked"] >= int(step["repeat"]) or _touching(step, after, state):
            _advance(state)
        return
    if aid in (1, 2, 3, 4) and pred_hit is False:
        note_route(state, before, after, aid, False)
    blocked = state.setdefault("blocked_here", [])
    if aid in (1, 2, 3, 4) and aid not in blocked:
        blocked.append(aid)
    step["fails"] = int(step.get("fails") or 0) + 1
    state["stall_steps"] = int(state.get("stall_steps") or 0) + 1
    open_dirs = [item for item in (1, 2, 3, 4) if item not in blocked]
    if step["fails"] >= _budget(step) or not open_dirs:
        _remember_failure(state, step, action, before, after, "predicate false")


def _touching(step: dict, after, state: dict) -> bool:
    from monad2.predicates import evaluate

    pred = state.get("plan_predicate") or {}
    geom = pred.get("geom")
    other = pred.get("geom_b")
    if not geom or not other or not after:
        return False
    check = {
        "kind": "contact",
        "role": step.get("role") or "none",
        "role_b": step.get("role_b") or "none",
        "dir": "none",
        "axis": "none",
        "geom": geom,
        "geom_b": other,
    }
    return evaluate(check, list(after), list(after)) is True


def _note_press(state: dict, step: dict, pred_hit, action, before, after) -> None:
    if pred_hit is True:
        step["walked"] = int(step.get("walked") or 0) + 1
        step["fails"] = 0
        state["stall_steps"] = 0
        if step["walked"] >= int(step["repeat"]):
            _advance(state)
        return
    step["fails"] = int(step.get("fails") or 0) + 1
    state["stall_steps"] = int(state.get("stall_steps") or 0) + 1
    if step["fails"] < _budget(step):
        return
    step["anchor_i"] = int(step.get("anchor_i") or 0) + 1
    step["fails"] = 0
    step["walked"] = 0
    if step["anchor_i"] >= _aff_count(state, step):
        _remember_failure(state, step, action, before, after, "predicate false")


def _note_miss(state: dict, step: dict, pred_hit, action, before, after) -> None:
    step["tries"] = int(step.get("tries") or 0) + 1
    step["fails"] = int(step.get("fails") or 0) + 1
    ref = state.get("last_ref") or ""
    if ref and ref not in step["tried"]:
        step["tried"].append(ref)
    state["stall_steps"] = int(state.get("stall_steps") or 0) + 1
    wrong = _wrong_way(state.get("plan_predicate"), before, after)
    if pred_hit is False and (step.get("kind") == "no_reverse" or wrong or step["fails"] >= _budget(step)):
        _remember_failure(state, step, action, before, after, "predicate false")
        return
    if int(state.get("stall_steps") or 0) >= _STALL:
        _remember_failure(state, step, action, before, after, "no progress")


def plan_signature(steps: list[dict]) -> tuple:
    rows = []
    for step in steps or []:
        rows.append(
            (
                step.get("primitive"),
                step.get("binding"),
                step.get("kind"),
                step.get("role"),
                step.get("role_b"),
                int(step.get("repeat") or 0),
            )
        )
    return tuple(rows)


def same_plan(left: list[dict], right: list[dict]) -> bool:
    return bool(left) and plan_signature(left) == plan_signature(right)


def _step_for(name: str, obs: dict, state: dict) -> dict:
    from monad2.predicates import _TEMPLATES
    from monad2.primitives import _binding_text

    kind, role, role_b = _TEMPLATES.get(name, ("changed", "none", "none"))
    return {
        "primitive": name,
        "binding": _binding_text(name, obs),
        "kind": kind,
        "role": role,
        "role_b": role_b,
        "repeat": 1,
        "tries": 0,
        "tried": [],
        "walked": 0,
        "fails": 0,
        "anchor_i": 0,
        "fail_budget": _FAIL_BUDGET,
        "labeled": name == "explore",
    }


def alternate_plan(old: list[dict], obs: dict, state: dict) -> list[dict]:
    """A different primitive, or one labeled explore step when nothing else applies."""
    used = {step.get("primitive") for step in old or []}
    for name in NAMES:
        if name in used:
            continue
        if not precondition(name, obs, state):
            continue
        return [_step_for(name, obs, state)]
    return [_step_for("explore", obs, state)]


def reject_same(old: list[dict], proposed: list[dict], obs: dict, state: dict, banned) -> tuple[list[dict], list]:
    """Drop a replan whose steps match a plan that already failed."""
    seen = [tuple(item) for item in (banned or [])]
    old_sig = plan_signature(old)
    if old_sig and old_sig not in seen:
        seen.append(old_sig)
    if proposed and plan_signature(proposed) not in seen:
        return proposed, seen
    alt = alternate_plan(old or proposed, obs, state)
    if plan_signature(alt) in seen:
        alt = [_step_for("explore", obs, state)]
    return alt, seen


def prompt(entries: dict, surprise: str, context: dict | None = None) -> str:
    roles = entries.get("roles") or "none"
    primitives = entries.get("primitives") or "none"
    menu = entries.get("menu") or "none"
    theory = entries.get("theory") or ""
    hypothesis = entries.get("hypothesis") or ""
    bits = [
        f"Roles: {roles}.",
        f"Primitives: {primitives}.",
        f"Menu: {menu}.",
        "Write the plan for this level.",
    ]
    if hypothesis:
        bits.append(f"Hypothesis: {hypothesis}.")
    if theory:
        bits.append(f"Theory: {theory}.")
    if surprise:
        ctx = context or {}
        bits.append(f"Surprise: {surprise}.")
        if ctx.get("predicate"):
            bits.append(f"Failed predicate: {ctx['predicate']}.")
        if ctx.get("moved"):
            bits.append(f"Moved: {ctx['moved']}.")
        if ctx.get("action"):
            bits.append(f"Failing action: {ctx['action']}.")
        bits.append("Replan with a different primitive. Do not repeat the same steps.")
    return " ".join(bits)


def rendered(step: dict, action, obs: dict) -> str:
    return render(predicate_for(step, action, obs))
