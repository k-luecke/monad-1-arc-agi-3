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
prim ::= "\"approach\"" | "\"hold_gradient\"" | "\"convey\"" | "\"align\"" | "\"toggle\"" | "\"avoid\"" | "\"cycle_select\"" | "\"route\"" | "\"assemble\"" | "\"explore\""
predkind ::= "\"translate\"" | "\"no_reverse\"" | "\"contact\"" | "\"match\"" | "\"changed\"" | "\"unchanged\""
role ::= "\"avatar\"" | "\"movable\"" | "\"goal\"" | "\"receptor\"" | "\"switch\"" | "\"hazard\"" | "\"wall\"" | "\"clickable\"" | "\"reference\"" | "\"none\""
digit ::= "1" | "2" | "3" | "4" | "5" | "6"
step ::= "{" ws "\"primitive\"" ws ":" ws prim ws "," ws "\"binding\"" ws ":" ws string ws "," ws "\"predicate\"" ws ":" ws predkind ws "," ws "\"role\"" ws ":" ws role ws "," ws "\"role_b\"" ws ":" ws role ws "," ws "\"repeat\"" ws ":" ws digit ws "}"
root ::= "{" ws "\"goal\"" ws ":" ws goal ws "," ws "\"steps\"" ws ":" ws "[" ws step (ws "," ws step){0,1} ws "]" ws "}"
'''
    if not click_only:
        return grammar
    from monad2.llm import drop_directional_roles

    return drop_directional_roles(grammar)


def ready(state: dict) -> bool:
    """Roles have held for two discovery steps and a goal or live candidate is bound."""
    if state.get("coop_handoff"):
        return False
    if not state.get("click_only_ready"):
        if int(state.get("discover_steps") or 0) < _DISCOVER:
            return False
        if not state.get("stable_roles") and not state.get("mover_box"):
            return False
    roles = {str(slot.get("role")) for slot in (state.get("schema_obs") or {}).get("roles") or [] if slot.get("role")}
    aff = state.get("affordances") or {}
    controllable = (
        bool(roles & {"avatar", "clickable", "switch"})
        or bool(state.get("mover_box"))
        or bool(state.get("click_only_ready") and (aff.get("clickable") or aff.get("switch")))
    )
    needs_initial_llm = (
        "llm_calls_level" in state
        and int(state.get("llm_calls") or 0) == 0
        and int(state.get("llm_calls_level") or 0) == 0
        and int(state.get("llm_level") or 0) == 0
    )
    has_candidate = bool(
        state.get("hypothesis_target")
        or state.get("candidates")
        or (state.get("click_only_ready") and (aff.get("clickable") or aff.get("switch")))
        or (controllable and needs_initial_llm)
    )
    goalish = ("goal" in roles) or has_candidate
    return controllable and goalish


def note_discovery(state: dict) -> None:
    line = state.get("role_line") or ""
    if (not line or line == "none") and state.get("mover_box"):
        line = "avatar"
    state["stable_roles"] = line if line and line == state.get("prev_roles") else ""
    state["prev_roles"] = line
    state["discover_steps"] = int(state.get("discover_steps") or 0) + 1


def _live_candidates(state: dict) -> list[dict]:
    refuted = {
        (int(g[0]), int(g[1]), int(g[2]))
        for g in (state.get("refuted_candidates") or [])
        if isinstance(g, (list, tuple)) and len(g) == 3
    }
    deferred = {
        (int(g[0]), int(g[1]), int(g[2]))
        for g in (state.get("deferred_candidates") or [])
        if isinstance(g, (list, tuple)) and len(g) == 3
    }
    out = []
    for item in state.get("candidates") or []:
        if not isinstance(item, dict):
            continue
        geom = item.get("geom")
        if geom and len(geom) == 3:
            key = (int(geom[0]), int(geom[1]), int(geom[2]))
            if key in refuted or key in deferred:
                continue
        out.append(item)
    return out


def parse_plan(text: str, obs: dict, state: dict) -> list[dict]:
    """Steps the live roles can run. Digits in a binding are rejected."""
    roles = {str(slot.get("role")) for slot in (obs or {}).get("roles") or [] if slot.get("role")}
    has_avatar = ("avatar" in roles) or bool((state or {}).get("mover_box"))
    has_movable = (
        ("movable" in roles)
        or bool(((state or {}).get("role_evidence") or {}).get("movable"))
        or bool((state or {}).get("movable_box"))
    )
    live_cands = _live_candidates(state or {})
    reach_cand = None
    cand_kind = "REACH"
    if (state or {}).get("hypothesis_target"):
        reach_cand = list(state["hypothesis_target"])
        for cand in live_cands:
            cg = cand.get("geom")
            if cg and len(cg) == 3 and [int(cg[0]), int(cg[1]), int(cg[2])] == [int(x) for x in reach_cand[:3]]:
                cand_kind = str(cand.get("kind") or "REACH")
                break
    else:
        for cand in live_cands:
            if cand.get("kind") in ("REACH", "PLACE") and cand.get("geom"):
                reach_cand = list(cand["geom"])
                cand_kind = str(cand.get("kind") or "REACH")
                if isinstance(state, dict):
                    state["hypothesis_target"] = list(reach_cand)
                    if cand.get("box"):
                        state["hypothesis_box"] = tuple(cand["box"])
                break
    fmf_u = (state or {}).get("fmf_unhashed") if isinstance((state or {}).get("fmf_unhashed"), dict) else {}
    field_u = (state or {}).get("top_down_field") if isinstance((state or {}).get("top_down_field"), dict) else {}
    tonic_d = int((state or {}).get("tonic_depth") or field_u.get("tonic_depth") or 0)
    step_fail_budget = max(_FAIL_BUDGET, min(8, tonic_d)) if tonic_d > 0 else _FAIL_BUDGET
    endorsed_g = set(fmf_u.get("endorsed_goals") or ())
    refuted_g = set(fmf_u.get("refuted_goals") or ())
    if has_movable and "PLACE" in endorsed_g and "PLACE" not in refuted_g:
        cand_kind = "PLACE"
    elif "REACH" in endorsed_g and "PLACE" in refuted_g:
        cand_kind = "REACH"
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
        role = match.group("role")
        role_b = match.group("roleb")
        repeat = int(match.group("rep"))
        if "goal" not in roles and reach_cand is not None and has_avatar:
            has_switch = ("switch" in roles) or bool(((state or {}).get("affordances") or {}).get("switch"))
            path_gated = bool(
                (state or {}).get("conditional_blocks")
                or (state or {}).get("deferred_candidates")
                or (state or {}).get("route_blocks")
            )
            want_switch_first = (
                fmf_u.get("candidate_priority") == "SWITCH_FIRST"
                or fmf_u.get("candidate_bias") == "switch_first"
                or fmf_u.get("merkle_primitive_id") == "PRIM_04_COUPLED_REMOTE_SWITCH_GATE"
            )
            if has_switch and path_gated and want_switch_first and 6 in ((state or {}).get("legal") or [6]):
                steps.append(
                    {
                        "primitive": "toggle",
                        "binding": "switch",
                        "kind": "changed",
                        "role": "switch",
                        "role_b": "none",
                        "repeat": 1,
                        "tries": 0,
                        "tried": [],
                        "walked": 0,
                        "fails": 0,
                        "anchor_i": 0,
                        "fail_budget": step_fail_budget,
                        "labeled": False,
                    }
                )
            if cand_kind == "PLACE" and has_movable:
                steps.append(
                    {
                        "primitive": "convey",
                        "binding": "avatar,movable",
                        "kind": "translate",
                        "role": "movable",
                        "role_b": "none",
                        "repeat": max(repeat, 4),
                        "tries": 0,
                        "tried": [],
                        "walked": 0,
                        "fails": 0,
                        "anchor_i": 0,
                        "fail_budget": step_fail_budget,
                        "labeled": False,
                        "candidate": list(reach_cand),
                    }
                )
            else:
                steps.append(
                    {
                        "primitive": "explore",
                        "binding": "avatar",
                        "kind": "translate",
                        "role": "avatar",
                        "role_b": "none",
                        "repeat": repeat,
                        "tries": 0,
                        "tried": [],
                        "walked": 0,
                        "fails": 0,
                        "anchor_i": 0,
                        "fail_budget": step_fail_budget,
                        "labeled": True,
                        "candidate": list(reach_cand),
                    }
                )
            break
        aff_click = bool(((state or {}).get("affordances") or {}).get("clickable"))
        only_click_cands = bool(live_cands) and all(c.get("kind") == "CLICK" for c in live_cands)
        if "goal" not in roles and (not has_avatar or (reach_cand is None and only_click_cands)) and aff_click and (not has_avatar or name in ("align", "explore", "toggle", "cycle_select")):
            steps.append(
                {
                    "primitive": "toggle",
                    "binding": "clickable",
                    "kind": "changed",
                    "role": "switch",
                    "role_b": "none",
                    "repeat": max(repeat, 3),
                    "tries": 0,
                    "tried": [],
                    "walked": 0,
                    "fails": 0,
                    "anchor_i": 0,
                    "fail_budget": step_fail_budget,
                    "labeled": name == "explore",
                }
            )
            break
        if "goal" not in roles and reach_cand is None and has_avatar and not only_click_cands:
            name = "explore"
            kind = "translate"
            role = "avatar"
            role_b = "none"
            binding = "avatar"
        elif name == "explore":
            if has_avatar and (reach_cand is not None or role == "avatar" or "goal" not in roles):
                kind = "translate"
                role = "avatar"
                role_b = "none"
                binding = binding or "avatar"
        elif not precondition(name, obs, state):
            continue
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
                "fail_budget": step_fail_budget,
                "labeled": name == "explore",
                "candidate": list(reach_cand) if (name == "explore" and reach_cand is not None) else None,
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


def _target_role(step: dict, state: dict | None = None) -> str:
    if step.get("primitive") in ("explore", "convey") and state and (state.get("hypothesis_target") or state.get("hypothesis_box")):
        return "goal"
    other = str(step.get("role_b") or "")
    role = str(step.get("role") or "")
    if other and other != "none":
        return other
    if step.get("primitive") in _PRESS:
        return role
    return ""


def _arm_step(step: dict, state: dict) -> None:
    state["step_target"] = _target_role(step, state)
    role = str(step.get("role") or "")
    if step.get("primitive") == "explore" and (state.get("hypothesis_target") or state.get("hypothesis_box")) and (not role or role == "none"):
        role = "avatar"
    state["step_role"] = role
    state["plan_primitive"] = step.get("primitive") or ""
    state["anchor_i"] = int(step.get("anchor_i") or 0)
    state["active_anchor"] = step.get("active_anchor")
    state["tried_anchors"] = list(step.get("tried_anchors") or [])


def _bare_ref(key) -> str:
    if key and key[0] == "SIMPLE":
        return f"simple#{int(key[1])}"
    if key and key[0] == "CLICK":
        return "click"
    return ""


def expand_action(step: dict, legal: list[int], state: dict, items: list[dict]):
    """One legal action for this primitive. A press repeats its current anchor."""
    from monad2.menu import build_menu
    from monad2.primitives import action_legal, blocked_dirs

    _arm_step(step, state)
    if step.get("primitive") == "explore":
        step["labeled"] = True
    tried = set(step.get("tried") or [])
    menu = items or build_menu(legal, state.get("affordances") or {})
    name = step.get("primitive") or ""
    preferred = None
    is_walk = name in _WALK or (
        name == "explore" and bool(state.get("hypothesis_target") or state.get("hypothesis_box") or step.get("role") == "avatar")
    )
    prefix = state.get("route_prefix")
    if is_walk and isinstance(prefix, list) and prefix:
        try:
            next_aid = int(prefix[0])
        except (TypeError, ValueError):
            next_aid = 0
        if next_aid in (1, 2, 3, 4) and next_aid not in blocked_dirs(state) and action_legal(("SIMPLE", next_aid), legal):
            preferred = ("SIMPLE", next_aid)
        else:
            state["route_prefix"] = []
    if preferred is None:
        preferred = suggest_action(name, legal, state)
    if name in _WALK or name in _PRESS or name == "explore":
        if preferred is not None and action_legal(preferred, legal):
            return preferred, _ref_for(preferred, menu) or _bare_ref(preferred)
        if name in _PRESS and state.get("tried_anchors"):
            return None, ""
        if name in _WALK or (
            name == "explore"
            and (state.get("hypothesis_target") or state.get("hypothesis_box") or step.get("role") == "avatar")
        ):
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
    moving = [(dx, dy) for dx, dy in (deltas or []) if dx != 0 or dy != 0]
    if not moving:
        return False
    return not any(_dir_ok(dx, dy, str(pred.get("dir") or "")) for dx, dy in moving)


def _advance(state: dict) -> None:
    state["stall_steps"] = 0
    state["blocked_here"] = []
    state["route_blocks"] = []
    state["route_quantum"] = 0
    state["route_prev"] = None
    state["active_anchor"] = None
    state["tried_anchors"] = []
    state["script_i"] = int(state.get("script_i") or 0) + 1
    if current_step(state) is None:
        state["script"] = []
        state["mode"] = "discover"
        state["discover_steps"] = 0
        state["stable_roles"] = ""


def _with_click(records) -> list[dict]:
    out = []
    for rec in records or []:
        if not isinstance(rec, dict):
            continue
        if "click" in rec and rec["click"] is not None:
            out.append(rec)
            continue
        xy = rec.get("xy") or (0, 0)
        wh = rec.get("wh") or (0, 0)
        copy = dict(rec)
        copy["click"] = (int(xy[0]) + int(wh[0]) // 2, int(xy[1]) + int(wh[1]) // 2)
        out.append(copy)
    return out


def _moved_geom(before, after) -> str:
    from monad2.canvas_stream import diff_records

    diff = diff_records(_with_click(before), _with_click(after))
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


def _playfield_sig(records, state: dict) -> tuple:
    from monad2.primitives import _inside_box
    from monad2.roles import _span

    if not records:
        return ()
    ev = state.get("role_evidence") or {}
    av = ev.get("avatar") or state.get("mover_geom") or None
    mov = ev.get("movable") or None
    skip = set()
    if av and len(av) == 3:
        skip.add((int(av[0]), int(av[1]), int(av[2])))
    if mov and len(mov) == 3:
        skip.add((int(mov[0]), int(mov[1]), int(mov[2])))
    for part in ev.get("avatar_parts") or []:
        if isinstance(part, (list, tuple)) and len(part) == 3:
            skip.add((int(part[0]), int(part[1]), int(part[2])))
    pbox = state.get("playfield_box")
    has_pbox = isinstance(pbox, (list, tuple)) and len(pbox) == 4
    width = _span(records, None)
    items = []
    for rec in records:
        g = rec.get("geom")
        xy = rec.get("xy")
        wh = rec.get("wh")
        if g and len(g) == 3 and (int(g[0]), int(g[1]), int(g[2])) not in skip:
            if xy and wh and len(xy) == 2 and len(wh) == 2:
                cx, cy, cw, ch = int(xy[0]), int(xy[1]), int(wh[0]), int(wh[1])
                if has_pbox and not _inside_box((cx, cy, cw, ch), pbox):
                    continue
                if width >= 32 and (
                    (cy <= 1 and ch <= 2)
                    or (cy + ch >= width - 1 and ch <= 2)
                    or (cx <= 1 and cw <= 2)
                    or (cx + cw >= width - 1 and cw <= 2)
                    or cw >= width - 2
                    or ch >= width - 2
                ):
                    continue
            sig = rec.get("sig") or ()
            fill = int(sig[1]) if len(sig) > 1 else -1
            items.append(((int(g[0]), int(g[1]), int(g[2])), fill, tuple(xy or ()), tuple(wh or ())))
    return tuple(sorted(items))


def _non_avatar_changed(before, after, state: dict, ignore_hud: bool = False) -> bool:
    if not ignore_hud and state.get("hud_changed"):
        return True
    if not before or not after:
        return False
    return _playfield_sig(before, state) != _playfield_sig(after, state)


def _reached_candidate(state: dict, before, after) -> bool:
    from monad2.predicates import _touching as touch_box
    from monad2.primitives import _boxes_for, _inside_box, _mover_box, _overlap, _quantum_of, _role_box, _target_box

    if not state.get("hypothesis_target") or not after:
        return False
    if state.get("plan_primitive") == "convey":
        mover = _role_box(state, after, "movable") or _mover_box(state, after)
    else:
        mover = _mover_box(state, after)
    if mover is None:
        return False
    obs = state.get("schema_obs") or {}
    tbox = state.get("hypothesis_box") or _target_box(state, before or after, obs, "goal")
    if tbox is None:
        return False
    q = max(1, _quantum_of(state))
    if q > 1 and tbox[2] > mover[2] and tbox[3] > mover[3]:
        return _inside_box(mover, tbox)
    mc = (mover[0] + mover[2] / 2.0, mover[1] + mover[3] / 2.0)
    tc = (tbox[0] + tbox[2] / 2.0, tbox[1] + tbox[3] / 2.0)
    if q > 1 and (abs(tc[0] - mc[0]) >= q or abs(tc[1] - mc[1]) >= q):
        return False
    if _overlap(mover, tbox):
        return True
    for part in ((state.get("role_evidence") or {}).get("avatar_parts")) or []:
        if isinstance(part, (list, tuple)) and len(part) == 3:
            for pbox in _boxes_for(after, (int(part[0]), int(part[1]), int(part[2]))):
                if _overlap(pbox, tbox):
                    return True
    if q <= 1 and touch_box(mover, tbox):
        return True
    return False


def _advance_candidate(state: dict, step: dict, before, after, action=None, why: str = "predicate false") -> bool:
    """Switch to the next live candidate in execute mode without calling the model."""
    state["route_prefix"] = []
    live = _live_candidates(state)
    if not live:
        state["hypothesis_target"] = None
        state["hypothesis_box"] = None
        _remember_failure(state, step, action, before, after, why)
        return False
    nxt = live[0]
    geom = nxt.get("geom")
    state["hypothesis_target"] = [int(geom[0]), int(geom[1]), int(geom[2])] if geom else None
    state["hypothesis_box"] = tuple(nxt["box"]) if nxt.get("box") else None
    if isinstance(state.get("role_evidence"), dict) and state["hypothesis_target"]:
        state["role_evidence"]["candidate_geom"] = list(state["hypothesis_target"])
    step["candidate"] = list(state["hypothesis_target"]) if state["hypothesis_target"] else None
    step["walked"] = 0
    step["fails"] = 0
    state["blocked_here"] = []
    state["stall_steps"] = 0
    sig = plan_signature(state.get("script") or [])
    banned = [tuple(item) for item in (state.get("rejected_sigs") or [])]
    if sig and sig in banned:
        _remember_failure(state, step, action, before, after, why)
        return False
    state["surprise_pending"] = None
    return True


def _refute_current_candidate(state: dict, step: dict, before, after, action=None, why: str = "predicate false") -> bool:
    from monad2.primitives import _boxes_for

    if state.get("conditional_blocks") or state.get("deferred_candidates"):
        state["had_conditional_blocks"] = True
    hyp = state.get("hypothesis_target")
    if hyp and len(hyp) == 3:
        entry = [int(hyp[0]), int(hyp[1]), int(hyp[2])]
        gt = (entry[0], entry[1], entry[2])
        b_boxes = _boxes_for(before or [], gt)
        a_boxes = _boxes_for(after or [], gt)
        consumable_remaining = bool(why == "candidate refuted" and 0 < len(a_boxes) < len(b_boxes))
        refuted = state.setdefault("refuted_candidates", [])
        if not consumable_remaining and entry not in refuted:
            refuted.append(entry)
        elif consumable_remaining:
            for item in state.get("candidates") or []:
                if isinstance(item, dict) and item.get("geom") == entry:
                    item["box"] = a_boxes[0]
                    break
        if why == "candidate refuted" and _non_avatar_changed(before, after, state):
            ev = state.setdefault("role_evidence", {}) if isinstance(state.get("role_evidence"), dict) else {}
            if isinstance(ev, dict):
                if consumable_remaining or (int(entry[0]) == 2 and bool(state.get("hud_changed"))):
                    ev["collectible"] = list(entry)
                elif state.get("conditional_blocks") or state.get("deferred_candidates") or state.get("had_conditional_blocks"):
                    ev["switch"] = list(entry)
                    state["had_conditional_blocks"] = True
            pref = (state.get("role_evidence") or {}).get("preferred_goal")
            if isinstance(pref, (list, tuple)) and len(pref) == 3:
                pref_entry = [int(pref[0]), int(pref[1]), int(pref[2])]
                if pref_entry != entry and pref_entry in refuted and int(state.get("unrefuted_passes") or 0) < 2:
                    refuted.remove(pref_entry)
                    state["unrefuted_passes"] = int(state.get("unrefuted_passes") or 0) + 1
    if (state.get("conditional_blocks") or state.get("deferred_candidates")) and _non_avatar_changed(before, after, state):
        state["had_conditional_blocks"] = True
        state["conditional_blocks"] = []
        state["deferred_candidates"] = []
    return _advance_candidate(state, step, before, after, action=action, why=why)


def note_result(state: dict, pred_hit, action, outcome: str, before=None, after=None) -> None:
    """Walk length counts successes. The failure budget is separate."""
    from monad2.primitives import _mover_box

    if state.get("conditional_blocks") or state.get("deferred_candidates"):
        state["had_conditional_blocks"] = True
    if state.get("mode") != "execute":
        return
    step = current_step(state)
    if step is None:
        return
    if outcome == "reset":
        _remember_failure(state, step, action, before, after, "level reset")
        return
    if outcome == "completed":
        return
    mover_stationary = _mover_box(state, before) == _mover_box(state, after)
    if (
        pred_hit is not False
        and (state.get("conditional_blocks") or state.get("deferred_candidates"))
        and (mover_stationary or bool(state.get("hud_changed")))
        and (_non_avatar_changed(before, after, state) or bool(state.get("hud_changed")))
    ):
        state["had_conditional_blocks"] = True
        hyp = state.get("hypothesis_target")
        if hyp and len(hyp) == 3 and mover_stationary and isinstance(state.get("role_evidence"), dict):
            state["role_evidence"]["switch"] = [int(hyp[0]), int(hyp[1]), int(hyp[2])]
        state["conditional_blocks"] = []
        state["deferred_candidates"] = []
        state["route_prefix"] = []
        pref_g = (state.get("role_evidence") or {}).get("preferred_goal")
        if (
            isinstance(pref_g, (list, tuple))
            and len(pref_g) == 3
            and int(state.get("unrefuted_passes") or 0) < 3
        ):
            pg_entry = [int(pref_g[0]), int(pref_g[1]), int(pref_g[2])]
            ref_list = state.get("refuted_candidates") or []
            if pg_entry in ref_list:
                ref_list.remove(pg_entry)
                state["unrefuted_passes"] = int(state.get("unrefuted_passes") or 0) + 1
        live = _live_candidates(state)
        if live:
            nxt = live[0]
            geom = nxt.get("geom")
            state["hypothesis_target"] = [int(geom[0]), int(geom[1]), int(geom[2])] if geom else None
            state["hypothesis_box"] = tuple(nxt["box"]) if nxt.get("box") else None
            step["candidate"] = list(state["hypothesis_target"]) if state["hypothesis_target"] else None
    name = step.get("primitive") or ""
    is_cand_walk = name == "explore" and bool(
        state.get("hypothesis_target") or state.get("hypothesis_box") or step.get("role") == "avatar"
    )
    if name in _WALK or is_cand_walk:
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
    from monad2.primitives import _mover_box, _quantum_of, _role_box, note_route

    aid = None
    if action and action[0] == "SIMPLE":
        try:
            aid = int(action[1])
        except (TypeError, ValueError, IndexError):
            aid = None
    avatar_only_convey = False
    if step.get("primitive") == "convey" and aid in (1, 2, 3, 4):
        b_av = _role_box(state, before, "avatar")
        a_av = _role_box(state, after, "avatar")
        b_mv = _role_box(state, before, "movable")
        a_mv = _role_box(state, after, "movable")
        av_moved = b_av is not None and a_av is not None and (int(b_av[0]), int(b_av[1])) != (int(a_av[0]), int(a_av[1]))
        mv_moved = b_mv is not None and a_mv is not None and (int(b_mv[0]), int(b_mv[1])) != (int(a_mv[0]), int(a_mv[1]))
        if av_moved and not mv_moved:
            avatar_only_convey = True
            pred_hit = True
        elif mv_moved:
            pred_hit = True
    q_now = _quantum_of(state)
    b_m = _mover_box(state, before)
    a_m = _mover_box(state, after)
    b_plan = state.get("bridge_plan")
    was_bridge_step = False
    if isinstance(b_plan, list) and b_plan and b_m is not None and aid is not None:
        bp0 = b_plan[0]
        if (
            isinstance(bp0, (list, tuple))
            and len(bp0) == 3
            and (int(b_m[0]), int(b_m[1])) == (int(bp0[0]), int(bp0[1]))
            and int(aid) == int(bp0[2])
        ):
            was_bridge_step = True
            state["bridge_plan"] = list(b_plan[1:])
            if (
                a_m is not None
                and (int(a_m[0]), int(a_m[1])) == (int(b_m[0]), int(b_m[1]))
                and _non_avatar_changed(before, after, state)
            ):
                step["walked"] = int(step.get("walked") or 0) + 1
                step["fails"] = 0
                state["blocked_here"] = []
                state["stall_steps"] = 0
                return
    teleported = bool(
        q_now > 0
        and not was_bridge_step
        and not state.get("bridge_plan")
        and b_m is not None
        and a_m is not None
        and (int(a_m[0]), int(a_m[1])) != (int(b_m[0]), int(b_m[1]))
        and (abs(int(a_m[0]) - int(b_m[0])) + abs(int(a_m[1]) - int(b_m[1]))) != q_now
    )
    if teleported:
        state["route_prefix"] = []
        state["blocked_here"] = []
        state["stall_steps"] = 0
        state["refuted_candidates"] = []
        step["fails"] = 0
        step["walked"] = 0
        step["pos_steps"] = 0
        return
    if pred_hit is True and (was_bridge_step or avatar_only_convey or not _wrong_way(state.get("plan_predicate"), before, after)):
        if aid in (1, 2, 3, 4):
            note_route(state, before, after, aid, True)
        prefix = state.get("route_prefix")
        if isinstance(prefix, list) and prefix and aid is not None and int(prefix[0]) == aid:
            state["route_prefix"] = list(prefix[1:])
        else:
            state["route_prefix"] = []
        field = state.get("top_down_field") if isinstance(state.get("top_down_field"), dict) else {}
        fmf_u = state.get("fmf_unhashed") if isinstance(state.get("fmf_unhashed"), dict) else {}
        reframe_walk = bool(
            field.get("verdict") == "CHALLENGE_HAZARD_TRAJECTORY"
            or field.get("reframe")
            or (
                field.get("coupling_mode") == "DECOUPLED_ORTHOGONAL_EXPLORATION"
                and field.get("sw_regime") == "DESTRUCTIVE_INTERFERENCE_REFRAME"
            )
            or fmf_u.get("candidate_bias") == "refute_decoy"
        )
        walk_cap = max(int(step.get("repeat") or 1), 8) if reframe_walk else max(int(step.get("repeat") or 1) * 8, 40)
        if avatar_only_convey:
            step["pos_steps"] = int(step.get("pos_steps") or 0) + 1
            if step["pos_steps"] >= walk_cap:
                step["walked"] = int(step.get("walked") or 0) + 1
        else:
            step["pos_steps"] = 0
            step["walked"] = int(step.get("walked") or 0) + 1
        step["fails"] = 0
        state["blocked_here"] = []
        state["stall_steps"] = 0
        if state.get("hypothesis_target"):
            if _reached_candidate(state, before, after):
                _refute_current_candidate(state, step, before, after, action=action, why="candidate refuted")
                return
            if step["walked"] >= walk_cap or int(step.get("pos_steps") or 0) >= walk_cap:
                _refute_current_candidate(state, step, before, after, action=action, why="walk budget spent")
            return
        if step.get("primitive") == "explore" and step.get("role") == "avatar" and state.get("mover_box"):
            if step["walked"] >= walk_cap or _touching(step, after, state):
                _advance(state)
            return
        if step["walked"] >= int(step["repeat"]) or _touching(step, after, state):
            _advance(state)
        return
    state["route_prefix"] = []
    if aid in (1, 2, 3, 4, 5) and pred_hit is False:
        note_route(state, before, after, aid, False)
    if state.get("last_conditional") and state.get("hypothesis_target"):
        state["had_conditional_blocks"] = True
        hyp = state.get("hypothesis_target")
        if hyp and len(hyp) == 3:
            entry = [int(hyp[0]), int(hyp[1]), int(hyp[2])]
            deferred = state.setdefault("deferred_candidates", [])
            if entry not in deferred:
                deferred.append(entry)
        state["last_conditional"] = None
        if _advance_candidate(state, step, before, after, action=action, why="conditional edge"):
            return
    blocked = state.setdefault("blocked_here", [])
    if aid in (1, 2, 3, 4, 5) and aid not in blocked:
        blocked.append(aid)
    if aid == 5:
        return
    step["fails"] = int(step.get("fails") or 0) + 1
    state["stall_steps"] = int(state.get("stall_steps") or 0) + 1
    open_dirs = [item for item in (1, 2, 3, 4) if item not in blocked]
    field = state.get("top_down_field") if isinstance(state.get("top_down_field"), dict) else {}
    fmf_u = state.get("fmf_unhashed") if isinstance(state.get("fmf_unhashed"), dict) else {}
    early_reframe = bool(
        field.get("verdict") == "CHALLENGE_HAZARD_TRAJECTORY"
        or (
            step["fails"] >= 2
            and (
                (
                    field.get("coupling_mode") == "DECOUPLED_ORTHOGONAL_EXPLORATION"
                    and field.get("sw_regime") == "DESTRUCTIVE_INTERFERENCE_REFRAME"
                )
                or fmf_u.get("candidate_bias") == "refute_decoy"
            )
        )
    )
    if step["fails"] >= _budget(step) or not open_dirs or early_reframe:
        if state.get("hypothesis_target"):
            _refute_current_candidate(state, step, before, after, action=action, why="predicate false")
        else:
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


def _is_square_button_pt(records, pt: list[int] | tuple[int, int]) -> bool:
    px, py = int(pt[0]), int(pt[1])
    for r in records or []:
        xy = r.get("xy")
        wh = r.get("wh")
        if not xy or not wh:
            continue
        rx, ry, rw, rh = int(xy[0]), int(xy[1]), int(wh[0]), int(wh[1])
        if rx <= px < rx + rw and ry <= py < ry + rh and rw == rh and 2 <= rw <= 4:
            return True
    return False


def _unlocked_bar_anchor(step: dict, before, after, pt: list[int] | tuple[int, int]) -> list[int] | None:
    if not before or not after:
        return None
    px, py = int(pt[0]), int(pt[1])
    init_bars = step.setdefault("init_bar_fills", {})
    b_bars: dict[tuple[int, int, int, int], int] = {}
    b_boxes: set[tuple[int, int, int, int]] = set()
    for r in before:
        xy = r.get("xy")
        wh = r.get("wh")
        sig = r.get("sig")
        if not xy or not wh or not sig or len(sig) < 2:
            continue
        bx, by, bw, bh = int(xy[0]), int(xy[1]), int(wh[0]), int(wh[1])
        b_boxes.add((bx, by, bw, bh))
        if bw != bh and min(bw, bh) >= 2 and max(bw, bh) >= 6 and bw * bh <= 96:
            key = (bx, by, bw, bh)
            fill = int(sig[1])
            b_bars[key] = fill
            init_bars.setdefault(key, fill)
    other_moved = False
    unlocked_pt: list[int] | None = None
    for r in after:
        xy = r.get("xy")
        wh = r.get("wh")
        sig = r.get("sig")
        if not xy or not wh or not sig or len(sig) < 2:
            continue
        ax, ay, aw, ah = int(xy[0]), int(xy[1]), int(wh[0]), int(wh[1])
        key = (ax, ay, aw, ah)
        if key not in b_boxes:
            other_moved = True
        if key in b_bars:
            if ax <= px < ax + aw and ay <= py < ay + ah:
                continue
            a_fill = int(sig[1])
            b_fill = b_bars[key]
            if a_fill != b_fill and a_fill != init_bars.get(key):
                unlocked_pt = [ax + aw // 2, ay + ah // 2]
    return unlocked_pt if other_moved else None


def _small_shapes_by_fill(records) -> dict[int, list[tuple[int, int, int, int]]]:
    by_fill: dict[int, list[tuple[int, int, int, int]]] = {}
    for r in records or []:
        xy = r.get("xy")
        wh = r.get("wh")
        sig = r.get("sig")
        if not xy or not wh or not sig or len(sig) < 2:
            continue
        fill = int(sig[1])
        if fill <= 0:
            continue
        bx, by, bw, bh = int(xy[0]), int(xy[1]), int(wh[0]), int(wh[1])
        if 1 <= bw <= 6 and 1 <= bh <= 6 and 1 <= bw * bh <= 36 and bw != bh:
            by_fill.setdefault(fill, []).append((bx, by, bw, bh))
    return by_fill


def _rider_alignment_status(before, after) -> tuple[set[int], bool, bool, bool]:
    """Return (moved_fills, reached_stop_alignment, approaching, retreating) for translating indicator shapes vs stationary same-fill markers."""
    b_map = _small_shapes_by_fill(before)
    a_map = _small_shapes_by_fill(after)
    moved_fills: set[int] = set()
    newly_aligned = False
    still_approaching = False
    any_retreating = False
    for fill, b_list in b_map.items():
        a_list = a_map.get(fill) or []
        if len(b_list) != 2 or len(a_list) != 2:
            continue
        b_set = set(b_list)
        a_set = set(a_list)
        common = list(b_set & a_set)
        b_only = list(b_set - a_set)
        a_only = list(a_set - b_set)
        if len(common) != 1 or len(b_only) != 1 or len(a_only) != 1:
            continue
        sx, sy, sw, sh = common[0]
        bx, by, bw, bh = b_only[0]
        ax, ay, aw, ah = a_only[0]
        if (bw, bh) != (aw, ah):
            continue
        dx = ax - bx
        dy = ay - by
        if not ((dx != 0) ^ (dy != 0)):
            continue
        moved_fills.add(fill)
        if dy != 0 and bh == sh and bw != sw:
            d_before = abs(by - sy)
            d_after = abs(ay - sy)
            if d_before > 0 and d_after == 0:
                newly_aligned = True
            elif 0 < d_after < d_before:
                still_approaching = True
            elif d_after > d_before:
                any_retreating = True
        elif dx != 0 and bw == sw and bh != sh:
            d_before = abs(bx - sx)
            d_after = abs(ax - sx)
            if d_before > 0 and d_after == 0:
                newly_aligned = True
            elif 0 < d_after < d_before:
                still_approaching = True
            elif d_after > d_before:
                any_retreating = True
    stop_align = bool(newly_aligned and not still_approaching)
    retreating = bool(any_retreating and not still_approaching and not newly_aligned)
    return moved_fills, stop_align, still_approaching, retreating


def _aligned_rider_fills(records) -> set[int]:
    aligned: set[int] = set()
    for fill, boxes in _small_shapes_by_fill(records).items():
        if len(boxes) != 2:
            continue
        (x1, y1, w1, h1), (x2, y2, w2, h2) = boxes[0], boxes[1]
        if y1 == y2 and h1 == h2 and w1 != w2:
            aligned.add(fill)
        elif x1 == x2 and w1 == w2 and h1 != h2:
            aligned.add(fill)
    return aligned


def _note_press(state: dict, step: dict, pred_hit, action, before, after) -> None:
    pred_geom = (state.get("plan_predicate") or {}).get("geom")
    is_clickable_bind = step.get("binding") == "clickable"
    pf_changed = _non_avatar_changed(before, after, state, ignore_hud=True) if is_clickable_bind else False
    cycled_anchor = False
    if is_clickable_bind and before and after:
        b_sig = _playfield_sig(before, state)
        a_sig = _playfield_sig(after, state)
        seen = step.setdefault("anchor_seen_sigs", [])
        if b_sig and b_sig not in seen:
            seen.append(b_sig)
        if pf_changed:
            if a_sig in seen:
                cycled_anchor = True
                pf_changed = False
            elif a_sig:
                seen.append(a_sig)
    clickable_moved = (
        is_clickable_bind
        and pf_changed
        and not cycled_anchor
        and (pred_hit is not True)
    )
    if is_clickable_bind and cycled_anchor:
        pred_hit = False
    if pred_hit is True or clickable_moved:
        step["walked"] = int(step.get("walked") or 0) + 1
        step["anchor_clicks"] = int(step.get("anchor_clicks") or 0) + 1
        step["progressed_in_pass"] = True
        step["fails"] = 0
        state["stall_steps"] = 0
        pt_now = [int(action[1]), int(action[2])] if (action and action[0] == "CLICK" and len(action) >= 3) else None
        if is_clickable_bind and step.get("triggered_once"):
            step["triggered_once"] = False
            step["active_anchor"] = None
            state["active_anchor"] = None
            step["anchor_clicks"] = 0
            step["anchor_seen_sigs"] = []
            inert = [list(p) for p in (step.get("inert_anchors") or [])]
            if pt_now is not None and pt_now not in inert:
                inert.append(pt_now)
            step["tried_anchors"] = list(inert)
            state["tried_anchors"] = list(inert)
            step["anchor_i"] = len(inert)
            return
        if pt_now is not None:
            step["active_anchor"] = pt_now
            state["active_anchor"] = step["active_anchor"]
            if is_clickable_bind:
                moved_fills, stop_align, approaching, retreating = _rider_alignment_status(before, after)
                if moved_fills:
                    f_map = step.setdefault("anchor_moved_fills", {})
                    prev_f = set(f_map.get((pt_now[0], pt_now[1])) or ())
                    f_map[(pt_now[0], pt_now[1])] = list(prev_f | moved_fills)
                    aff_pts = (state.get("affordances") or {}).get("clickable") or []
                    sq_pts = [
                        [int(p[0]), int(p[1])]
                        for p in aff_pts
                        if isinstance(p, (list, tuple)) and len(p) == 2 and _is_square_button_pt(after or before, p)
                    ]
                    if (
                        len(sq_pts) >= 2
                        and len(sq_pts) % 2 == 0
                        and pt_now in sq_pts
                        and (approaching or stop_align or retreating)
                    ):
                        sq_idx = sq_pts.index(pt_now)
                        inert = step.setdefault("inert_anchors", [])
                        tried_anc = step.setdefault("tried_anchors", [])
                        if (approaching or stop_align) and not step.get("parity_locked"):
                            bad_parity = 1 - (sq_idx % 2)
                            step["parity_locked"] = True
                            for j, sp in enumerate(sq_pts):
                                if j % 2 == bad_parity:
                                    if sp not in inert:
                                        inert.append(sp)
                                    if sp not in tried_anc:
                                        tried_anc.append(sp)
                        elif retreating:
                            if pt_now not in inert:
                                inert.append(pt_now)
                            if pt_now not in tried_anc:
                                tried_anc.append(pt_now)
                            partner = sq_pts[sq_idx ^ 1]
                            if partner in inert:
                                inert.remove(partner)
                            if partner in tried_anc:
                                tried_anc.remove(partner)
                            stop_align = True
                        state["tried_anchors"] = list(tried_anc)
                trig_pt = _unlocked_bar_anchor(step, before, after, pt_now)
                if trig_pt is not None:
                    step["active_anchor"] = trig_pt
                    state["active_anchor"] = trig_pt
                    step["triggered_once"] = True
                    step["anchor_seen_sigs"] = []
                    return
                if stop_align:
                    tried_anc = step.setdefault("tried_anchors", [])
                    if pt_now not in tried_anc:
                        tried_anc.append(pt_now)
                    state["tried_anchors"] = list(tried_anc)
                    step["active_anchor"] = None
                    state["active_anchor"] = None
                    step["anchor_clicks"] = 0
                    step["anchor_seen_sigs"] = []
                    step["anchor_i"] = int(step.get("anchor_i") or 0) + 1
                    step["walked"] = 0
                    return
        from monad2.predicates import _deltas

        deltas = _deltas(list(before or []), list(after or []), pred_geom) if pred_geom else None
        translating = bool(deltas and any(dx or dy for dx, dy in deltas)) or clickable_moved
        cap = (
            max(int(step["repeat"]) * (12 if is_clickable_bind else 4), 48 if is_clickable_bind else 16)
            if (translating and len(state.get("script") or []) == 1)
            else int(step["repeat"])
        )
        if step["walked"] >= cap:
            step["active_anchor"] = None
            state["active_anchor"] = None
            _advance(state)
        return
    if is_clickable_bind and step.get("triggered_once"):
        step["triggered_once"] = False
    step["fails"] = int(step.get("fails") or 0) + 1
    state["stall_steps"] = int(state.get("stall_steps") or 0) + 1
    fast_advance = is_clickable_bind and bool(
        cycled_anchor or int(step.get("anchor_clicks") or 0) > 0 or (before and not pf_changed)
    )
    if not fast_advance and step["fails"] < _budget(step):
        return
    if action and action[0] == "CLICK" and len(action) >= 3:
        pt = [int(action[1]), int(action[2])]
        tried_anc = step.setdefault("tried_anchors", [])
        if pt not in tried_anc:
            tried_anc.append(pt)
        state["tried_anchors"] = list(tried_anc)
        if (
            is_clickable_bind
            and int(step.get("anchor_clicks") or 0) == 0
            and before
            and not pf_changed
            and not _is_square_button_pt(before, pt)
        ):
            inert = step.setdefault("inert_anchors", [])
            if pt not in inert:
                inert.append(pt)
    step["active_anchor"] = None
    state["active_anchor"] = None
    step["anchor_clicks"] = 0
    step["anchor_seen_sigs"] = []
    step["anchor_i"] = int(step.get("anchor_i") or 0) + 1
    step["fails"] = 0
    step["walked"] = 0
    aff_pts = (state.get("affordances") or {}).get("clickable") or []
    sq_pts = (
        [
            [int(p[0]), int(p[1])]
            for p in aff_pts
            if isinstance(p, (list, tuple)) and len(p) == 2 and _is_square_button_pt(after or before, p)
        ]
        if is_clickable_bind
        else []
    )
    tried_now = step.get("tried_anchors") or []
    sq_exhausted = bool(len(sq_pts) >= 2 and step.get("progressed_in_pass") and all(sp in tried_now for sp in sq_pts))
    if step["anchor_i"] >= _aff_count(state, step) or sq_exhausted:
        if is_clickable_bind and step.get("progressed_in_pass") and int(step.get("passes") or 0) < 6:
            step["passes"] = int(step.get("passes") or 0) + 1
            step["progressed_in_pass"] = False
            inert = [list(p) for p in (step.get("inert_anchors") or [])]
            aligned_f = _aligned_rider_fills(after or before)
            f_map = step.get("anchor_moved_fills") or {}
            skip_pts = list(inert)
            if aligned_f and f_map:
                for p in aff_pts:
                    if not isinstance(p, (list, tuple)) or len(p) != 2:
                        continue
                    pk = (int(p[0]), int(p[1]))
                    mf = set(f_map.get(pk) or ())
                    if mf and mf <= aligned_f and [pk[0], pk[1]] not in skip_pts:
                        skip_pts.append([pk[0], pk[1]])
            eff_total = len(sq_pts) if len(sq_pts) >= 2 else _aff_count(state, step)
            if len(skip_pts) >= eff_total:
                skip_pts = list(inert)
            step["tried_anchors"] = list(skip_pts)
            state["tried_anchors"] = list(skip_pts)
            step["anchor_i"] = len(skip_pts)
            step["anchor_seen_sigs"] = []
            state["stall_steps"] = 0
            return
        if state.get("hypothesis_target"):
            _refute_current_candidate(state, step, before, after, action=action, why="predicate false")
        else:
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
    if name == "explore" and (state or {}).get("hypothesis_target"):
        roles = {str(slot.get("role")) for slot in (obs or {}).get("roles") or [] if slot.get("role")}
        if "avatar" in roles or (state or {}).get("mover_box"):
            kind, role, role_b = ("translate", "avatar", "none")
    return {
        "primitive": name,
        "binding": _binding_text(name, obs) or ("avatar" if role == "avatar" else ""),
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
    if (state or {}).get("hypothesis_target"):
        roles = {str(slot.get("role")) for slot in (obs or {}).get("roles") or [] if slot.get("role")}
        if ("avatar" in roles or (state or {}).get("mover_box")) and "goal" not in roles:
            return [_step_for("explore", obs, state)]
    used = {step.get("primitive") for step in old or []}
    fmf_u = (state or {}).get("fmf_unhashed") if isinstance((state or {}).get("fmf_unhashed"), dict) else {}
    fmf_prims = [str(p) for p in (fmf_u.get("primitives") or ()) if str(p) in NAMES]
    ordered_names = fmf_prims + [n for n in NAMES if n not in fmf_prims]
    for name in ordered_names:
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


def _fmt_candidates(raw) -> str:
    if not raw:
        return ""
    if isinstance(raw, str):
        return raw
    parts = []
    for item in list(raw)[:8]:
        geom = item.get("geom") if isinstance(item, dict) else item
        if isinstance(geom, (list, tuple)) and len(geom) == 3:
            text = f"{int(geom[0])},{int(geom[1])},{int(geom[2])}"
            kind = item.get("kind") if isinstance(item, dict) else ""
            parts.append(f"{kind}:{text}" if kind else text)
    return "; ".join(parts)


def prompt(entries: dict, surprise: str = "", context: dict | None = None) -> str:
    roles = entries.get("roles") or "none"
    primitives = entries.get("primitives") or "none"
    menu = entries.get("menu") or "none"
    theory = entries.get("theory") or ""
    hypothesis = entries.get("hypothesis") or ""
    fmf = str(entries.get("fmf") or "")
    field = str(entries.get("field") or "")
    tonic = str(entries.get("tonic") or "")
    candidates = _fmt_candidates(entries.get("candidates") or entries.get("candidate_list"))
    leader = str(entries.get("leader") or entries.get("leader_goal") or "")
    bits = [
        f"Roles: {roles}.",
        f"Primitives: {primitives}.",
        f"Menu: {menu}.",
        "Write the plan for this level.",
    ]
    if candidates:
        bits.append(f"Candidates: {candidates}.")
    if leader:
        bits.append(f"Leader: {leader}.")
    if hypothesis:
        bits.append(f"Hypothesis: {hypothesis}.")
    if fmf and not fmf.startswith("no overlapping"):
        bits.append(f"FMF: {fmf}.")
    if field and field != "no field":
        bits.append(f"Field: {field}.")
    if tonic and not tonic.startswith("no tonic"):
        bits.append(f"Tonic: {tonic}.")
    if theory:
        bits.append(f"Theory: {theory}.")
    if surprise:
        ctx = context or {}
        bits.append(f"Surprise: {surprise}.")
        if ctx.get("solver_issue"):
            bits.append(f"Solver issue: {ctx['solver_issue']}.")
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
