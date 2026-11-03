"""Menu legality, contradictory role bindings, and plan-once execution."""
from __future__ import annotations

import os

from llama_cpp import LlamaGrammar

from monad2.menu import build_menu, executive_grammar, menu_line, resolve_choice
from monad2.llm import grammar_for
from monad2.planmode import (
    expand_action,
    note_result,
    parse_plan,
    plan_grammar,
    reject_same,
    same_plan,
)
from monad2.primitives import step_toward
from monad2.schema import (
    assert_structure,
    drop_contradictions,
    induce,
    match,
    render,
    reset_store,
    upsert,
)
from monad2.test_roles import _click_scene, _dpad_scene, _shift_avatar


def _records(grid):
    from monad2.schema import _records_from_grid

    return _records_from_grid(grid)


def main() -> int:
    reset_store()
    os.environ["MONAD2_COORDINATE"] = "1"
    click_recs = _records(_click_scene())
    from monad2.roles import infer_roles

    click = infer_roles(click_recs, {}, [6], 16)
    menu = build_menu([6], click["affordances"])
    assert menu and all(item["key"][0] == "CLICK" for item in menu), menu
    assert all(not item["ref"].startswith("simple#") for item in menu)
    grammar = executive_grammar(menu, click_only=True)
    assert "SIMPLE" not in grammar
    assert "hold_gradient" not in grammar
    assert "avatar" not in grammar
    assert "click(clickable#0)" in grammar
    LlamaGrammar.from_string(grammar)
    LlamaGrammar.from_string(plan_grammar())
    click_plan = plan_grammar(click_only=True)
    assert "hold_gradient" not in click_plan and "avatar" not in click_plan
    LlamaGrammar.from_string(click_plan)
    for role in ("a", "b", "executive"):
        limited = grammar_for(role, click_only=True)
        assert "SIMPLE" not in limited
        assert "hold_gradient" not in limited
        assert "avatar" not in limited
        LlamaGrammar.from_string(limited)
    resolved = resolve_choice("click(clickable#0)", menu, [6])
    assert resolved == menu[0]["key"] and resolved[0] == "CLICK"
    assert resolve_choice("SIMPLE 1", menu, [6]) is None
    assert "click(clickable#0)" in menu_line(menu)
    import re

    assert re.search(r"\d+ \d+", menu_line(menu)) is None
    body = {"roles": click["roles"], "relations": click["relations"]}
    assert_structure(body)

    base = {
        "roles": [
            {"role": "avatar", "geom": [4, 1, 1], "shape": "ellipse"},
            {"role": "wall", "geom": [1, 1, 16], "shape": "rect"},
            {"role": "goal", "geom": [2, 4, 4], "shape": "hollow_rect"},
        ],
        "relations": [],
    }
    assert upsert(base, "ep-menu") == "S0"
    counts = {}
    for rec in click_recs:
        geom = tuple(rec.get("geom") or ())
        if len(geom) == 3:
            counts[geom] = counts.get(geom, 0) + 1
    mover = next(
        rec
        for rec in click_recs
        if len(tuple(rec.get("geom") or ())) == 3
        and counts[tuple(rec["geom"])] == 1
        and int(rec["geom"][0]) != 2
    )
    obs = induce(
        click_recs,
        {"moved": [{"sig": mover["sig"]}], "vanished": [], "appeared": []},
        "",
        "bg=0 shapes=4 hud_rows=0 hud_cols=0",
    )
    hit = match(obs, "ep-click")
    assert hit is not None
    live = {slot["role"] for slot in click["roles"]}
    assert "avatar" not in live
    revised, dropped = drop_contradictions(hit, [6], live)
    assert "avatar" in dropped, dropped
    text = render(revised) if revised else ""
    assert "the avatar" not in text
    kept, still = drop_contradictions(hit, [1, 2, 3, 4, 5], live | {"avatar", "wall", "goal"})
    assert "avatar" not in still
    assert any(binding["role"] == "avatar" for binding in (kept or {}).get("bindings") or []) or "avatar" not in {
        slot["role"] for slot in obs["roles"]
    }

    from monad2 import runtime as rt
    from monad2.coordinate import decide, observe
    from monad2.test_coordinate import _agent

    agent = _agent()
    agent._m2_avail = [6]
    agent._m2_grid = _click_scene()
    agent.prev_grid = _click_scene()

    class ClickBackend:
        def complete(self, role, system, user, **_kwargs):
            if role == "executive":
                return (
                    '{"decision":"accept","action":"SIMPLE 1","primitive":"align","binding":"clickable,reference",'
                    '"predicate":"match","role":"clickable","role_b":"reference","dir":"none","axis":"none",'
                    '"plan":[],"expect_change":true,"expectation":"comment","reason":"click the object",'
                    '"theory":"MATCH the reference","goal":"MATCH","used":["schema"]}',
                    5.0,
                )
            return (
                '{"action":"SIMPLE 4","primitive":"align","binding":"clickable","effect":"match","reason":"try"}',
                1.0,
            )

    chosen = decide(agent, ("CLICK", 1, 1), "heuristic", backend=ClickBackend())
    assert chosen[0] == "CLICK", chosen
    row = agent.m2_thought_log[-1]
    assert "no legal action" not in (row.get("reason") or "")
    assert row.get("mode") == "discover"
    assert row.get("decision") != "explore"

    dpad = infer_roles(_records(_dpad_scene()), {}, [1, 2, 3, 4, 5], 16)
    assert "goal" not in {slot["role"] for slot in dpad["roles"]}
    assert "avatar" not in {slot["role"] for slot in dpad["roles"]}
    bound_roles = list(dpad["roles"]) + [
        {"role": "avatar", "geom": [1, 2, 2], "shape": "rect"},
        {"role": "goal", "geom": [2, 2, 2], "shape": "hollow_rect"},
    ]
    plan_json = (
        '{"goal":"REACH","steps":[{"primitive":"approach","binding":"avatar,goal",'
        '"predicate":"translate","role":"avatar","role_b":"goal","repeat":3}]}'
    )
    steps = parse_plan(
        plan_json,
        {"roles": bound_roles, "relations": dpad["relations"]},
        {"progress_axis": None},
    )
    assert steps and steps[0]["primitive"] == "approach" and steps[0]["repeat"] == 3
    state = {
        "mode": "execute",
        "script": steps,
        "script_i": 0,
        "stall_steps": 0,
        "affordances": dpad["affordances"],
        "schema_obs": {
            "roles": [
                {"role": "avatar", "geom": [1, 2, 2]},
                {"role": "goal", "geom": [2, 2, 2]},
                {"role": "wall", "geom": [3, 1, 4]},
            ],
            "relations": [],
        },
        "frame_records": [
            {"geom": (1, 2, 2), "xy": (8, 8), "wh": (2, 2), "sig": (1, 4, 2, 2)},
            {"geom": (2, 2, 2), "xy": (8, 1), "wh": (2, 2), "sig": (2, 1, 2, 2)},
            {"geom": (3, 1, 4), "xy": (8, 6), "wh": (2, 2), "sig": (3, 3, 2, 2)},
        ],
        "plan_predicate": {
            "kind": "translate",
            "role": "avatar",
            "role_b": "goal",
            "dir": "up",
            "axis": "none",
            "geom": [1, 2, 2],
            "geom_b": [2, 2, 2],
        },
        "last_ref": "simple#1",
    }
    aimed = step_toward("approach", [1, 2, 3, 4], state)
    assert aimed in (3, 4), aimed
    action, ref = expand_action(steps[0], [1, 2, 3, 4, 5], state, build_menu([1, 2, 3, 4, 5], dpad["affordances"]))
    assert action == ("SIMPLE", aimed), action
    note_result(state, True, action, "continue", [], [])
    assert state.get("script_i") == 0, state.get("script_i")
    assert steps[0]["walked"] == 1
    note_result(state, False, action, "continue", [], [])
    assert state.get("surprise_pending") is None
    assert  action[1] in state.get("blocked_here")
    route = {
        "mode": "execute",
        "script": [
            {
                "primitive": "approach",
                "binding": "avatar,goal",
                "kind": "translate",
                "role": "avatar",
                "role_b": "goal",
                "repeat": 6,
                "tries": 0,
                "tried": [],
                "walked": 0,
                "fails": 0,
                "anchor_i": 0,
                "fail_budget": 4,
                "labeled": False,
            }
        ],
        "script_i": 0,
        "stall_steps": 0,
        "blocked_here": [],
        "schema_obs": {
            "roles": [
                {"role": "avatar", "geom": [1, 2, 2]},
                {"role": "goal", "geom": [2, 2, 2]},
            ]
        },
        "frame_records": [
            {"geom": (1, 2, 2), "xy": (8, 8), "wh": (2, 2), "sig": (1, 4, 2, 2)},
            {"geom": (2, 2, 2), "xy": (8, 0), "wh": (2, 2), "sig": (2, 1, 2, 2)},
        ],
        "plan_predicate": {
            "kind": "translate",
            "role": "avatar",
            "role_b": "goal",
            "dir": "up",
            "axis": "none",
            "geom": [1, 2, 2],
            "geom_b": [2, 2, 2],
        },
        "step_role": "avatar",
        "step_target": "goal",
    }
    parked = [{"geom": (1, 2, 2), "xy": (8, 8), "wh": (2, 2), "sig": (1, 4, 2, 2)}]
    note_result(route, False, ("SIMPLE", 1), "continue", parked, parked)
    assert [8, 8, 1] in route["route_blocks"], route["route_blocks"]
    route["route_quantum"] = 2
    around = step_toward("approach", [1, 2, 3, 4], route)
    assert around in (3, 4), around
    shifted = [{"geom": (1, 2, 2), "xy": (6, 8), "wh": (2, 2), "sig": (1, 4, 2, 2)}]
    route["plan_predicate"]["dir"] = "left"
    route["frame_records"] = shifted + [
        {"geom": (2, 2, 2), "xy": (8, 0), "wh": (2, 2), "sig": (2, 1, 2, 2)}
    ]
    note_result(route, True, ("SIMPLE", 3), "continue", parked, shifted)
    assert [8, 8, 1] in route["route_blocks"], route["route_blocks"]
    assert route["route_quantum"] == 2
    assert route.get("script_i") == 0
    later = step_toward("approach", [1, 2, 3, 4], route)
    assert later == 1, later
    steps[0]["fail_budget"] = 1
    steps[0]["fails"] = 0
    note_result(state, False, action, "continue", [], [])
    assert state.get("surprise_pending") == "predicate false", state.get("surprise_pending")
    assert state["replan_context"]["predicate"].startswith("translate(")
    assert state["replan_context"]["moved"] == "none"
    assert state["replan_context"]["action"]
    again, _banned = reject_same(steps, steps, {"roles": bound_roles}, state, [])
    assert not same_plan(steps, again)
    assert again[0]["primitive"] != "approach"
    presses = {
        "mode": "execute",
        "script": [
            {
                "primitive": "toggle",
                "binding": "switch",
                "kind": "changed",
                "role": "switch",
                "role_b": "none",
                "repeat": 3,
                "tries": 0,
                "tried": [],
                "walked": 0,
                "fails": 0,
                "anchor_i": 0,
                "fail_budget": 2,
                "labeled": False,
            }
        ],
        "script_i": 0,
        "stall_steps": 0,
        "affordances": {"switch": [[4, 4], [9, 9]], "clickable": [[4, 4], [9, 9]]},
        "schema_obs": {"roles": [{"role": "switch", "geom": [1, 2, 2]}]},
        "plan_predicate": {"kind": "changed", "role": "switch", "role_b": "none", "geom": [1, 2, 2], "geom_b": None},
    }
    first, _ref = expand_action(presses["script"][0], [6], presses, [])
    second, _ref = expand_action(presses["script"][0], [6], presses, [])
    assert first == second == ("CLICK", 4, 4), (first, second)
    note_result(presses, False, first, "continue", [], [])
    note_result(presses, False, first, "continue", [], [])
    assert presses["script"][0]["anchor_i"] == 1
    third, _ref = expand_action(presses["script"][0], [6], presses, [])
    assert third == ("CLICK", 9, 9), third

    agent = _agent()
    agent._m2_grid = _dpad_scene()
    agent.prev_grid = _dpad_scene()
    agent.m2 = {k: 0 for k in rt.COUNTERS}

    class PlanBackend:
        def __init__(self):
            self.calls = []

        def complete(self, role, system, user, **_kwargs):
            self.calls.append(role)
            if "level plan" in system:
                return plan_json, 4.0
            return (
                '{"decision":"accept","action":"SIMPLE 4","primitive":"approach","binding":"avatar,goal",'
                '"predicate":"translate","role":"avatar","role_b":"goal","dir":"right","axis":"none",'
                '"plan":[],"expect_change":true,"expectation":"comment","reason":"discover",'
                '"theory":"REACH the goal","goal":"REACH","used":["schema"]}',
                2.0,
            )

    backend = PlanBackend()
    decide(agent, ("SIMPLE", 1), "heuristic", backend=backend)
    held = agent._m2_coord
    assert held.get("role_line")
    from monad2.roles import note_effect

    before = _records(_dpad_scene())
    shifted = _records(_shift_avatar(_dpad_scene()))
    evidence = note_effect({}, before, shifted, ("SIMPLE", 4), "continue")
    for rec in before:
        geom = rec.get("geom")
        if geom and int(geom[0]) == 2:
            evidence["goal"] = [int(geom[0]), int(geom[1]), int(geom[2])]
            break
    held["role_evidence"] = evidence
    held["discover_steps"] = 2
    held["stable_roles"] = held["role_line"] or "avatar"
    held["prev_roles"] = held["stable_roles"]
    before = len(backend.calls)
    planned = decide(agent, ("SIMPLE", 1), "heuristic", backend=backend)
    assert agent.m2_thought_log[-1]["mode"] == "plan", agent.m2_thought_log[-1]["mode"]
    assert "approach(" in (agent.m2_thought_log[-1].get("plan") or "")
    assert planned[0] in ("SIMPLE", "CLICK")
    assert len(backend.calls) == before + 1
    assert backend.calls[-1] == "executive"
    mid = len(backend.calls)
    executed = decide(agent, ("SIMPLE", 1), "heuristic", backend=backend)
    assert agent.m2_thought_log[-1]["mode"] == "execute"
    assert len(backend.calls) == mid
    assert agent.m2["execute_steps"] >= 1
    assert agent.m2["llm_calls"] == before + 1 or agent.m2["llm_calls"] >= 1
    agent._m2_coord["script"][0]["fail_budget"] = 1
    observe(agent, False)
    assert agent._m2_coord.get("surprise_pending") == "predicate false"
    decide(agent, ("SIMPLE", 1), "heuristic", backend=backend)
    assert agent.m2_thought_log[-1]["mode"] == "replan", agent.m2_thought_log[-1]
    assert agent.m2["replan_calls"] >= 1
    assert executed is not None

    from monad2.candidates import enumerate_candidates, next_direction_probe, scope_records
    from monad2.schema import _permute, _rot90

    # Candidate scoping and D4 + palette invariance
    split_grid = [[0] * 16 for _ in range(16)]
    for r in range(1, 5):
        for c in range(1, 5):
            split_grid[r][c] = 8
    split_grid[2][2] = 9  # inside reference container
    split_grid[10][3] = 4
    split_grid[10][4] = 4  # avatar 1x2
    for r in range(6, 9):
        for c in range(10, 14):
            split_grid[r][c] = 2  # candidate 3x4
    split_grid[7][11] = 6  # internal ornament inside 3x4 candidate
    recs_base = _records(split_grid)
    roles_base = infer_roles(recs_base, {"avatar": [3, 1, 2]}, [1, 2, 3, 4], 16)
    scoped_base, pbox = scope_records(recs_base, roles_base["roles"], 16)
    assert all(rec.get("xy") != (2, 2) for rec in scoped_base), scoped_base
    cands_base = enumerate_candidates(
        recs_base,
        roles_base["roles"],
        {"avatar": [3, 1, 2]},
        "REACH",
        span=16,
    )
    assert cands_base and cands_base[0]["geom"] == [1, 3, 4], cands_base
    assert all(c["geom"] != [4, 1, 1] for c in cands_base), cands_base

    rot_grid = _permute(_rot90(split_grid))
    recs_rot = _records(rot_grid)
    roles_rot = infer_roles(recs_rot, {"avatar": [3, 1, 2]}, [1, 2, 3, 4], 16)
    cands_rot = enumerate_candidates(
        recs_rot,
        roles_rot["roles"],
        {"avatar": [3, 1, 2]},
        "REACH",
        span=16,
    )
    assert [(c["kind"], c["geom"]) for c in cands_base] == [(c["kind"], c["geom"]) for c in cands_rot]

    # Deterministic direction probe
    probe_state = {"role_evidence": {}, "blocked_here": [1], "probed_dirs": []}
    p1 = next_direction_probe(probe_state, [1, 2, 3, 4])
    assert p1 == ("SIMPLE", 2), p1
    p2 = next_direction_probe(probe_state, [1, 2, 3, 4])
    assert p2 == ("SIMPLE", 3), p2

    # Unbound goal -> labeled hypothesis step + refutation on contact without completion
    hyp_obs = {"roles": [{"role": "avatar", "geom": [3, 1, 2]}], "relations": []}
    hyp_state = {
        "mode": "execute",
        "hypothesis_target": [1, 3, 4],
        "hypothesis_box": (10, 6, 4, 3),
        "candidates": [
            {"kind": "REACH", "geom": [1, 3, 4], "box": (10, 6, 4, 3)},
            {"kind": "REACH", "geom": [1, 2, 2], "box": (2, 12, 2, 2)},
        ],
        "refuted_candidates": [],
        "deferred_candidates": [],
        "role_evidence": {"avatar": [3, 1, 2]},
        "schema_obs": hyp_obs,
    }
    hyp_steps = parse_plan(plan_json, hyp_obs, hyp_state)
    assert hyp_steps and hyp_steps[0]["primitive"] == "explore" and hyp_steps[0]["labeled"] is True
    hyp_state["script"] = hyp_steps
    hyp_state["script_i"] = 0
    contact_after = [
        {"geom": (3, 1, 2), "xy": (8, 6), "wh": (2, 1), "sig": (3, 4, 2, 1)},
        {"geom": (1, 3, 4), "xy": (10, 6), "wh": (4, 3), "sig": (1, 2, 4, 3)},
    ]
    note_result(hyp_state, True, ("SIMPLE", 4), "continue", contact_after, contact_after)
    assert [1, 3, 4] in hyp_state["refuted_candidates"], hyp_state["refuted_candidates"]
    assert hyp_state["hypothesis_target"] == [1, 2, 2], hyp_state["hypothesis_target"]
    assert hyp_state.get("surprise_pending") is None
    contact_second = [
        {"geom": (3, 1, 2), "xy": (0, 12), "wh": (2, 1), "sig": (3, 4, 2, 1)},
        {"geom": (1, 2, 2), "xy": (2, 12), "wh": (2, 2), "sig": (1, 2, 2, 2)},
    ]
    hyp_state["hypothesis_box"] = (2, 12, 2, 2)
    note_result(hyp_state, True, ("SIMPLE", 4), "continue", contact_second, contact_second)
    assert hyp_state["surprise_pending"] == "candidate refuted"

    # Conditional barrier deferral and clearing on state change
    cond_state = {
        "mode": "execute",
        "script": hyp_steps,
        "script_i": 0,
        "hypothesis_target": [1, 2, 2],
        "hypothesis_box": (2, 12, 2, 2),
        "candidates": [
            {"kind": "REACH", "geom": [1, 2, 2], "box": (2, 12, 2, 2)},
            {"kind": "REACH", "geom": [1, 2, 3], "box": (12, 12, 3, 2)},
        ],
        "refuted_candidates": [],
        "deferred_candidates": [],
        "conditional_blocks": [],
        "role_evidence": {"avatar": [3, 1, 2]},
        "schema_obs": hyp_obs,
        "step_role": "avatar",
        "step_target": "goal",
    }
    door_recs = [
        {"geom": (3, 1, 2), "xy": (2, 10), "wh": (2, 1), "sig": (3, 4, 2, 1)},
        {"geom": (1, 1, 2), "xy": (2, 11), "wh": (2, 1), "sig": (1, 5, 2, 1)},
        {"geom": (1, 2, 2), "xy": (2, 12), "wh": (2, 2), "sig": (1, 2, 2, 2)},
    ]
    note_result(cond_state, False, ("SIMPLE", 2), "continue", door_recs, door_recs)
    assert [1, 2, 2] in cond_state["deferred_candidates"], cond_state["deferred_candidates"]
    assert cond_state["hypothesis_target"] == [1, 2, 3], cond_state["hypothesis_target"]
    assert cond_state.get("surprise_pending") is None
    opened_recs = [
        {"geom": (3, 1, 2), "xy": (2, 10), "wh": (2, 1), "sig": (3, 4, 2, 1)},
        {"geom": (1, 2, 2), "xy": (2, 12), "wh": (2, 2), "sig": (1, 2, 2, 2)},
    ]
    note_result(cond_state, True, ("SIMPLE", 4), "continue", door_recs, opened_recs)
    assert cond_state["deferred_candidates"] == [], cond_state["deferred_candidates"]
    assert cond_state["conditional_blocks"] == [], cond_state["conditional_blocks"]

    # Prompt includes live geoms and leader type; script beats state["plan"]
    from monad2.planmode import prompt
    from monad2.predicates import evaluate

    prompt_txt = prompt(
        {
            "candidates": [
                {"kind": "REACH", "geom": [1, 3, 4]},
                {"kind": "REACH", "geom": [1, 2, 2]},
            ],
            "leader_goal": "REACH",
        }
    )
    assert "1,3,4" in prompt_txt and "1,2,2" in prompt_txt and "REACH" in prompt_txt
    assert evaluate({"kind": "changed", "role": "switch", "geom": [9, 9, 9]}, door_recs, opened_recs) is None

    # Confirmed-goal transfer via schema.STORE across levels
    reset_store()
    upsert({"roles": [{"role": "goal", "geom": [1, 2, 2], "shape": "rect"}], "relations": []}, "ep-goal")
    transfer_recs = [
        {"geom": (3, 1, 2), "xy": (2, 2), "wh": (2, 1), "sig": (3, 4, 2, 1)},
        {"geom": (1, 3, 4), "xy": (10, 6), "wh": (4, 3), "sig": (1, 2, 4, 3)},
        {"geom": (1, 2, 2), "xy": (12, 12), "wh": (2, 2), "sig": (1, 7, 2, 2)},
    ]
    transfer_cands = enumerate_candidates(
        transfer_recs,
        [{"role": "avatar", "geom": [3, 1, 2]}],
        {"avatar": [3, 1, 2]},
        "REACH",
        span=16,
    )
    assert transfer_cands and transfer_cands[0]["geom"] == [1, 2, 2], transfer_cands
    assert transfer_cands[0].get("confirmed_goal") is True

    # route_prefix commitment (<= 3 steps) and runtime.short_circuit_execute
    assert route.get("route_prefix") is not None
    agent._m2_coord["mode"] = "execute"
    agent._m2_coord["surprise_pending"] = None
    agent._m2_coord["script"] = hyp_steps
    agent._m2_coord["script_i"] = 0
    agent._m2_coord["plan"] = [("SIMPLE", 2)]
    before_skip = agent.m2.get("execute_skipped_ggl", 0)
    sc_action = rt.short_circuit_execute(agent)
    assert sc_action is not None, sc_action
    assert agent.m2.get("execute_skipped_ggl", 0) == before_skip + 1
    assert agent._m2_coord["plan"] == [("SIMPLE", 2)]

    # Leader ordering (REACH vs PLACE) and palette invariance
    rp_grid = [[0] * 16 for _ in range(16)]
    rp_grid[2][2] = 4
    rp_grid[2][3] = 4  # avatar 1x2 -> geom [4, 1, 2]
    for r in range(5, 7):
        for c in range(5, 8):
            rp_grid[r][c] = 6  # movable 2x3 rect -> geom [1, 2, 3]
    for r in range(10, 13):
        for c in range(10, 13):
            rp_grid[r][c] = 7  # static 3x3 rect -> geom [1, 3, 3] (same shape type 1 as movable)
    rp_grid[14][2] = 9
    rp_grid[14][3] = 9
    rp_grid[14][4] = 9  # static 1x3 line -> geom [3, 1, 3]
    rp_recs = _records(rp_grid)
    rp_ev = {"avatar": [4, 1, 2], "movable": [1, 2, 3]}
    rp_roles = infer_roles(rp_recs, rp_ev, [1, 2, 3, 4], 16)["roles"]
    cands_reach = enumerate_candidates(rp_recs, rp_roles, rp_ev, "REACH", [1, 2, 3, 4], span=16)
    cands_place = enumerate_candidates(rp_recs, rp_roles, rp_ev, "PLACE", [1, 2, 3, 4], span=16)
    assert cands_reach[0]["kind"] == "REACH", cands_reach
    assert cands_place[0]["kind"] == "PLACE", cands_place
    rp_perm = _records(_permute(rp_grid))
    cands_reach_perm = enumerate_candidates(rp_perm, rp_roles, rp_ev, "REACH", [1, 2, 3, 4], span=16)
    assert [(c["kind"], c["geom"]) for c in cands_reach] == [(c["kind"], c["geom"]) for c in cands_reach_perm]

    # Unique translated geom keeps anchor_i at 0 across two frame-changing clicks; None predicate spends 1 failure
    press_keep = {
        "mode": "execute",
        "script": [
            {
                "primitive": "toggle",
                "binding": "switch",
                "kind": "changed",
                "role": "switch",
                "role_b": "none",
                "repeat": 3,
                "tries": 0,
                "tried": [],
                "walked": 0,
                "fails": 0,
                "anchor_i": 0,
                "fail_budget": 2,
                "labeled": False,
            }
        ],
        "script_i": 0,
        "stall_steps": 0,
        "affordances": {"switch": [[4, 4], [9, 9]], "clickable": [[4, 4], [9, 9]]},
        "schema_obs": {"roles": [{"role": "switch", "geom": [1, 2, 2]}]},
        "plan_predicate": {"kind": "changed", "role": "switch", "role_b": "none", "geom": [1, 2, 2], "geom_b": None},
    }
    note_result(press_keep, True, ("CLICK", 4, 4), "continue", door_recs, opened_recs)
    note_result(press_keep, True, ("CLICK", 4, 4), "continue", opened_recs, door_recs)
    assert press_keep["script"][0]["anchor_i"] == 0 and press_keep["script"][0]["walked"] == 2
    note_result(press_keep, None, ("CLICK", 4, 4), "continue", door_recs, opened_recs)
    assert press_keep["script"][0]["fails"] == 1

    # New role introduced during execute triggers replan once
    from monad2.coordinate import _new_role_surprise

    role_state = {
        "mode": "execute",
        "surprise_pending": None,
        "plan_roles": "avatar, wall",
        "role_line": "avatar, wall, switch",
    }
    _new_role_surprise(role_state, {"kind": "walk", "primitive": "explore"})
    assert role_state["surprise_pending"] == "new role switch"

    # Split-panel palette canonicalizer remaps when enabled and leaves _m2_grid == _grid_from_frame(frame) when disabled
    from my_agent_v7_inos import MyAgent, _grid_from_frame

    remap_grid = [[9] * 64 for _ in range(64)]
    for c in range(38):
        remap_grid[0][c] = 7
    for r in range(2, 58):
        for c in range(2, 36):
            remap_grid[r][c] = 8
    for r in range(10, 16):
        for c in range(10, 18):
            remap_grid[r][c] = 6
    for dr in (0, 1):
        for dc in (0, 1):
            remap_grid[8 + dr][10 + dc] = 1
            remap_grid[16 + dr][10 + dc] = 12
    host_enabled = type("H", (), {"game_specific_solvers_disabled": False})()
    host_disabled = type("H", (), {"game_specific_solvers_disabled": True})()
    assert MyAgent._scp_canonicalize_split_panel_palette(host_enabled, remap_grid) != remap_grid
    assert MyAgent._scp_canonicalize_split_panel_palette(host_disabled, remap_grid) == remap_grid
    dummy_frame = type("F", (), {"frame": [remap_grid]})()
    assert MyAgent._scp_canonicalize_split_panel_palette(host_disabled, _grid_from_frame(dummy_frame)) == _grid_from_frame(dummy_frame)

    # Hollow type-2 shape is never a REACH target; click-only legal set yields affordances["clickable"] one anchor at a time
    hollow_recs = [
        {"geom": (1, 2, 2), "xy": (2, 2), "wh": (2, 2), "sig": (1, 4, 2, 2)},
        {"geom": (2, 4, 4), "xy": (10, 10), "wh": (4, 4), "sig": (2, 5, 4, 4)},
    ]
    assert enumerate_candidates(hollow_recs, {"avatar": [1, 2, 2]}, "REACH", [1, 2, 3, 4], span=16) == []
    assert all(
        int(c["geom"][0]) != 2
        for c in enumerate_candidates(_records(_dpad_scene()), {"avatar": [1, 2, 2]}, "REACH", [1, 2, 3, 4])
        if c["kind"] == "REACH"
    )
    click_only_cands = enumerate_candidates(click_recs, {}, "REACH", [6], affordances=click["affordances"])
    assert [c["anchor"] for c in click_only_cands] == click["affordances"]["clickable"], click_only_cands
    assert all(c["kind"] == "CLICK" for c in click_only_cands)

    # Shared geom on 64x64 without repeated tile background is skipped and D4-invariant
    shared64 = [[0] * 64 for _ in range(64)]
    shared64[2][2] = 4
    shared64[2][3] = 4
    for r in range(4, 7):
        for c in range(4, 7):
            shared64[r][c] = 2
            shared64[r][c + 36] = 3
    for r in range(20, 22):
        for c in range(20, 24):
            shared64[r][c] = 5
    s64_a = enumerate_candidates(_records(shared64), {"avatar": [4, 1, 2]}, "REACH", [1, 2, 3, 4], span=64)
    s64_b = enumerate_candidates(_records(_permute(_rot90(_rot90(shared64)))), {"avatar": [4, 1, 2]}, "REACH", [1, 2, 3, 4], span=64)
    assert [c["geom"] for c in s64_a if c["kind"] == "REACH"] == [[1, 2, 4]], s64_a
    assert [(c["kind"], c["geom"]) for c in s64_a] == [(c["kind"], c["geom"]) for c in s64_b]

    # MATCH pairs equal-size regions whose contents differ and emits no stored color
    match_cands = [c for c in s64_a if c["kind"] == "MATCH"]
    for mc in match_cands:
        clean_mc = {k: v for k, v in mc.items() if k != "box"}
        assert_structure(clean_mc)

    # route_prefix first step matches _around, later steps do not cross blocked edge, and execute mode consumes prefix
    from monad2.primitives import _around, _around_prefix, _block_set, _mover_box, _target_box

    rp_mover = _mover_box(route, route["frame_records"])
    rp_target = _target_box(route, route["frame_records"], route["schema_obs"], "goal")
    rp_blocks = _block_set(route)
    sim_prefix = _around_prefix(rp_mover, rp_target, route["route_quantum"], rp_blocks, [1, 2, 3, 4], [])
    assert sim_prefix and sim_prefix[0] == _around(rp_mover, rp_target, route["route_quantum"], rp_blocks, [1, 2, 3, 4], [])
    cx, cy = int(rp_mover[0]), int(rp_mover[1])
    for step_aid in sim_prefix:
        assert (cx, cy, step_aid) not in rp_blocks
        if step_aid == 1:
            cy -= route["route_quantum"]
        elif step_aid == 2:
            cy += route["route_quantum"]
        elif step_aid == 3:
            cx -= route["route_quantum"]
        elif step_aid == 4:
            cx += route["route_quantum"]
    prefix_state = {
        "mode": "execute",
        "script": hyp_steps,
        "script_i": 0,
        "hypothesis_target": [1, 3, 4],
        "hypothesis_box": (10, 6, 4, 3),
        "route_prefix": [4, 2],
        "blocked_here": [],
        "role_evidence": {"avatar": [3, 1, 2]},
        "schema_obs": hyp_obs,
        "frame_records": [{"geom": (3, 1, 2), "xy": (2, 2), "wh": (2, 1), "sig": (3, 4, 2, 1)}],
        "plan_predicate": {"kind": "translate", "role": "avatar", "role_b": "none", "dir": "right", "axis": "none", "geom": [3, 1, 2], "geom_b": None},
    }
    act1, _ = expand_action(hyp_steps[0], [1, 2, 3, 4], prefix_state, [])
    assert act1 == ("SIMPLE", 4)
    note_result(
        prefix_state,
        True,
        ("SIMPLE", 4),
        "continue",
        [{"geom": (3, 1, 2), "xy": (2, 2), "wh": (2, 1), "sig": (3, 4, 2, 1)}],
        [{"geom": (3, 1, 2), "xy": (4, 2), "wh": (2, 1), "sig": (3, 4, 2, 1)}],
    )
    assert prefix_state["route_prefix"] == [2], prefix_state["route_prefix"]
    act2, _ = expand_action(hyp_steps[0], [1, 2, 3, 4], prefix_state, [])
    assert act2 == ("SIMPLE", 2)

    # After two d-pad translations, enumerator knows moving geom and agent.fx_dpad is still empty
    dpad_agent = _agent()
    s0 = _dpad_scene()
    s1 = _shift_avatar(s0)
    s2 = _shift_avatar(s1)
    ev1 = note_effect({}, _records(s0), _records(s1), ("SIMPLE", 4), "continue")
    ev2 = note_effect(ev1, _records(s1), _records(s2), ("SIMPLE", 4), "continue")
    assert ev2.get("avatar") == [4, 2, 2], ev2
    assert not getattr(dpad_agent, "fx_dpad", {})
    enum_after_two = enumerate_candidates(
        _records(s2),
        ev2,
        "REACH",
        [1, 2, 3, 4],
        span=16,
    )
    assert all(c["geom"] != [4, 2, 2] for c in enum_after_two)

    # observe with non-empty document passes non-empty before and after to evaluate
    obs_agent = _agent()
    obs_agent._m2_avail = [1, 2, 3, 4]
    obs_agent._m2_grid = s0
    obs_agent.prev_grid = s0
    decide(obs_agent, ("SIMPLE", 4), "heuristic", backend=PlanBackend())
    assert obs_agent._m2_coord["pending"]["shapes"], obs_agent._m2_coord["pending"]
    obs_agent.prev_grid = s0
    obs_agent._m2_grid = s1
    observe(obs_agent, True)

    # Shared-geometry mover tracking: when two shapes share geom, _track_shared_mover binds mover_box
    from monad2.coordinate import _track_shared_mover
    from monad2.planmode import ready

    shared_before = [
        {"geom": (1, 2, 2), "xy": (2, 2), "wh": (2, 2), "sig": (1, 4, 2, 2)},
        {"geom": (1, 2, 2), "xy": (10, 10), "wh": (2, 2), "sig": (1, 7, 2, 2)},
    ]
    shared_after = [
        {"geom": (1, 2, 2), "xy": (4, 2), "wh": (2, 2), "sig": (1, 4, 2, 2)},
        {"geom": (1, 2, 2), "xy": (10, 10), "wh": (2, 2), "sig": (1, 7, 2, 2)},
    ]
    shared_state = {"role_evidence": {}, "discover_steps": 2, "schema_obs": {"roles": []}}
    _track_shared_mover(shared_state, shared_before, shared_after, ("SIMPLE", 4), "continue")
    assert shared_state["mover_box"] == (4, 2, 2, 2), shared_state
    assert shared_state["prev_mover_box"] == (2, 2, 2, 2)
    assert shared_state["route_quantum"] == 2
    shared_cands = enumerate_candidates(shared_after, {}, "REACH", [1, 2, 3, 4], state=shared_state, span=16)
    assert shared_cands and shared_cands[0]["box"] == (10, 10, 2, 2), shared_cands
    shared_state["candidates"] = shared_cands
    assert ready(shared_state) is True
    shared_steps = parse_plan(plan_json, {"roles": []}, shared_state)
    assert shared_steps and shared_steps[0]["primitive"] == "explore", shared_steps

    # Convey push-into-receptor routing: routes avatar around movable to push position, then pushes movable
    convey_state = {
        "mode": "execute",
        "plan_primitive": "convey",
        "step_role": "movable",
        "step_target": "goal",
        "route_quantum": 2,
        "hypothesis_target": [2, 2, 2],
        "hypothesis_box": (10, 4, 2, 2),
        "role_evidence": {"avatar": [4, 2, 2], "movable": [1, 2, 2]},
        "schema_obs": {
            "roles": [
                {"role": "avatar", "geom": [4, 2, 2]},
                {"role": "movable", "geom": [1, 2, 2]},
                {"role": "receptor", "geom": [2, 2, 2]},
            ]
        },
        "frame_records": [
            {"geom": (4, 2, 2), "xy": (8, 4), "wh": (2, 2), "sig": (4, 3, 2, 2)},
            {"geom": (1, 2, 2), "xy": (6, 4), "wh": (2, 2), "sig": (1, 6, 2, 2)},
            {"geom": (2, 2, 2), "xy": (10, 4), "wh": (2, 2), "sig": (2, 5, 2, 2)},
        ],
    }
    # Avatar is at (8,4) to the RIGHT of movable at (6,4), while receptor is at (10,4).
    # Must NOT step left (3) into movable; must route around movable (1 or 2) toward push box (4,4).
    around_push = step_toward("convey", [1, 2, 3, 4], convey_state)
    assert around_push in (1, 2), around_push
    # Once avatar is at push position (4,4) behind movable (6,4), convey steps right (4) to push movable toward (10,4).
    convey_state["frame_records"][0]["xy"] = (4, 4)
    push_step = step_toward("convey", [1, 2, 3, 4], convey_state)
    assert push_step == 4, push_step

    # HUD change un-defers conditional locks
    hud_lock_state = {
        "mode": "execute",
        "script": hyp_steps,
        "script_i": 0,
        "hypothesis_target": [1, 2, 3],
        "hypothesis_box": (12, 12, 3, 2),
        "candidates": [
            {"kind": "REACH", "geom": [1, 2, 2], "box": (2, 12, 2, 2)},
            {"kind": "REACH", "geom": [1, 2, 3], "box": (12, 12, 3, 2)},
        ],
        "refuted_candidates": [],
        "deferred_candidates": [[1, 2, 2]],
        "conditional_blocks": [[2, 10, 2]],
        "hud_changed": True,
        "role_evidence": {"avatar": [3, 1, 2]},
        "schema_obs": hyp_obs,
    }
    switch_contact = [
        {"geom": (3, 1, 2), "xy": (12, 12), "wh": (2, 1), "sig": (3, 4, 2, 1)},
        {"geom": (1, 2, 3), "xy": (12, 12), "wh": (3, 2), "sig": (1, 6, 3, 2)},
    ]
    note_result(hud_lock_state, True, ("SIMPLE", 4), "continue", switch_contact, switch_contact)
    assert hud_lock_state["deferred_candidates"] == [], hud_lock_state["deferred_candidates"]
    assert hud_lock_state["conditional_blocks"] == [], hud_lock_state["conditional_blocks"]
    assert hud_lock_state["hypothesis_target"] == [1, 2, 2], hud_lock_state["hypothesis_target"]

    # Multi-part avatar turning on step 1 records avatar_parts and moving_boxes so nose is not a REACH target
    mp_before = [
        {"geom": (1, 2, 4), "xy": (10, 4), "wh": (2, 4), "sig": (1, 8, 2, 4)},
        {"geom": (4, 1, 2), "xy": (10, 3), "wh": (2, 1), "sig": (4, 9, 2, 1)},
    ]
    mp_after = [
        {"geom": (1, 2, 4), "xy": (10, 6), "wh": (2, 4), "sig": (1, 8, 2, 4)},
        {"geom": (4, 1, 2), "xy": (10, 10), "wh": (2, 1), "sig": (4, 9, 2, 1)},
    ]
    mp_state = {"role_evidence": {}, "discover_steps": 2, "schema_obs": {"roles": []}}
    _track_shared_mover(mp_state, mp_before, mp_after, ("SIMPLE", 2), "continue")
    assert [4, 1, 2] in (mp_state["role_evidence"].get("avatar_parts") or []), mp_state
    assert enumerate_candidates(mp_after, mp_state["role_evidence"], "REACH", [1, 2, 3, 4], state=mp_state, span=32) == []

    # Multiple moving sprites sharing geom with one stationary target yields the stationary target as REACH
    tri_before = [
        {"geom": (5, 3, 3), "xy": (2, 2), "wh": (3, 3), "sig": (5, 4, 3, 3)},
        {"geom": (5, 3, 3), "xy": (8, 2), "wh": (3, 3), "sig": (5, 4, 3, 3)},
        {"geom": (5, 3, 3), "xy": (20, 20), "wh": (3, 3), "sig": (5, 4, 3, 3)},
    ]
    tri_after = [
        {"geom": (5, 3, 3), "xy": (4, 2), "wh": (3, 3), "sig": (5, 4, 3, 3)},
        {"geom": (5, 3, 3), "xy": (10, 2), "wh": (3, 3), "sig": (5, 4, 3, 3)},
        {"geom": (5, 3, 3), "xy": (20, 20), "wh": (3, 3), "sig": (5, 4, 3, 3)},
    ]
    tri_state = {"role_evidence": {}, "discover_steps": 2, "schema_obs": {"roles": []}}
    _track_shared_mover(tri_state, tri_before, tri_after, ("SIMPLE", 4), "continue")
    tri_cands = enumerate_candidates(tri_after, {}, "REACH", [1, 2, 3, 4], state=tri_state, span=32)
    assert len(tri_cands) == 1 and tri_cands[0]["box"] == (20, 20, 3, 3), tri_cands

    # Deformable playfield shape under d-pad sets dpad_moved=True even when geom changes
    def_before = [{"geom": (5, 4, 6), "xy": (8, 8), "wh": (6, 4), "sig": (5, 12, 6, 4)}]
    def_after = [{"geom": (5, 5, 7), "xy": (4, 8), "wh": (7, 5), "sig": (5, 12, 7, 5)}]
    def_state = {"role_evidence": {}}
    _track_shared_mover(def_state, def_before, def_after, ("SIMPLE", 3), "continue")
    assert def_state.get("dpad_moved") is True, def_state

    # Once coop_handoff is latched after initial discovery finds no candidates, ready(state) stays False mid-level
    coop_state = dict(shared_state)
    coop_state["coop_handoff"] = True
    assert ready(coop_state) is False

    # 1. avatar_parts are never bound as wall in infer_roles or note_effect on blocked steps
    hat_recs = [
        {"geom": (1, 3, 5), "xy": (14, 37), "wh": (5, 3), "sig": (1, 4, 5, 3), "area": 15, "type": 1},
        {"geom": (1, 2, 5), "xy": (14, 35), "wh": (5, 2), "sig": (1, 9, 5, 2), "area": 10, "type": 1},
    ]
    hat_ev = {"avatar": [1, 3, 5], "avatar_parts": [[1, 2, 5]]}
    hat_ev = note_effect(hat_ev, hat_recs, hat_recs, ("SIMPLE", 1), "continue")
    assert hat_ev.get("wall") is None, hat_ev
    hat_roles = infer_roles(hat_recs, hat_ev, [1, 2, 3, 4], 64)
    assert all(slot.get("role") != "wall" for slot in hat_roles["roles"]), hat_roles

    # 2. Shared-geometry avatar pushing a unique movable binds movable (not avatar), tracks movable_box, and enumerates PLACE
    push_before = [
        {"geom": (5, 3, 3), "xy": (4, 4), "wh": (3, 3), "sig": (5, 4, 3, 3), "area": 9, "type": 5},
        {"geom": (5, 3, 3), "xy": (20, 20), "wh": (3, 3), "sig": (5, 4, 3, 3), "area": 9, "type": 5},
        {"geom": (1, 3, 3), "xy": (7, 4), "wh": (3, 3), "sig": (1, 6, 3, 3), "area": 9, "type": 1},
        {"geom": (2, 5, 5), "xy": (15, 4), "wh": (5, 5), "sig": (2, 8, 5, 5), "area": 16, "type": 2},
    ]
    push_after = [
        {"geom": (5, 3, 3), "xy": (7, 4), "wh": (3, 3), "sig": (5, 4, 3, 3), "area": 9, "type": 5},
        {"geom": (5, 3, 3), "xy": (20, 20), "wh": (3, 3), "sig": (5, 4, 3, 3), "area": 9, "type": 5},
        {"geom": (1, 3, 3), "xy": (10, 4), "wh": (3, 3), "sig": (1, 6, 3, 3), "area": 9, "type": 1},
        {"geom": (2, 5, 5), "xy": (15, 4), "wh": (5, 5), "sig": (2, 8, 5, 5), "area": 16, "type": 2},
    ]
    push_ev = note_effect({}, push_before, push_after, ("SIMPLE", 4), "continue")
    assert push_ev.get("movable") == [1, 3, 3] and push_ev.get("avatar") is None, push_ev
    push_state = {"role_evidence": dict(push_ev), "discover_steps": 2, "schema_obs": {"roles": []}}
    _track_shared_mover(push_state, push_before, push_after, ("SIMPLE", 4), "continue")
    assert push_state["mover_box"] == (7, 4, 3, 3) and push_state["prev_mover_box"] == (4, 4, 3, 3), push_state
    assert push_state["movable_box"] == (10, 4, 3, 3), push_state
    place_cands = enumerate_candidates(push_after, push_ev, "PLACE", [1, 2, 3, 4], state=push_state, span=32)
    assert any(c["kind"] == "PLACE" and c["box"] == (15, 4, 5, 5) for c in place_cands), place_cands

    # 3. _role_box disambiguates before vs after on push steps, and _wrong_way ignores stationary movable during convey positioning
    from monad2.primitives import _push_box, _role_box, _swept_box, note_route
    from monad2.planmode import _wrong_way

    assert _role_box(push_state, push_before, "avatar") == (4, 4, 3, 3)
    assert _role_box(push_state, push_after, "avatar") == (7, 4, 3, 3)
    pos_before = [
        {"geom": (5, 3, 3), "xy": (7, 7), "wh": (3, 3), "sig": (5, 4, 3, 3)},
        {"geom": (1, 3, 3), "xy": (10, 4), "wh": (3, 3), "sig": (1, 6, 3, 3)},
    ]
    pos_after = [
        {"geom": (5, 3, 3), "xy": (7, 4), "wh": (3, 3), "sig": (5, 4, 3, 3)},
        {"geom": (1, 3, 3), "xy": (10, 4), "wh": (3, 3), "sig": (1, 6, 3, 3)},
    ]
    convey_pred = {"kind": "translate", "role": "movable", "role_b": "goal", "dir": "up", "geom": [1, 3, 3]}
    assert _wrong_way(convey_pred, pos_before, pos_after) is False
    convey_walk_state = {
        "mode": "execute",
        "script": [
            {
                "primitive": "convey",
                "binding": "movable,goal",
                "kind": "translate",
                "role": "movable",
                "role_b": "goal",
                "repeat": 2,
                "tries": 0,
                "tried": [],
                "walked": 0,
                "fails": 0,
                "anchor_i": 0,
                "fail_budget": 4,
                "labeled": False,
            }
        ],
        "script_i": 0,
        "plan_primitive": "convey",
        "plan_predicate": convey_pred,
        "hypothesis_target": [2, 5, 5],
        "hypothesis_box": (15, 4, 5, 5),
        "role_evidence": {"avatar": [5, 3, 3], "movable": [1, 3, 3]},
        "schema_obs": {"roles": [{"role": "avatar", "geom": [5, 3, 3]}, {"role": "movable", "geom": [1, 3, 3]}]},
    }
    note_result(convey_walk_state, False, ("SIMPLE", 1), "continue", pos_before, pos_after)
    assert convey_walk_state["script"][0]["fails"] == 0 and convey_walk_state["script"][0]["walked"] == 0
    assert convey_walk_state["script"][0].get("pos_steps") == 1

    # 4. Quantum-aware _push_box and wall-checked push side in step_toward("convey")
    assert _push_box((10, 4, 2, 2), (6, 4, 2, 2), 4, 4) == (2, 4, 2, 2)
    wall_convey = dict(convey_state)
    wall_convey["schema_obs"] = {
        "roles": [
            {"role": "avatar", "geom": [4, 2, 2]},
            {"role": "movable", "geom": [1, 2, 2]},
            {"role": "receptor", "geom": [2, 2, 2]},
            {"role": "wall", "geom": [1, 2, 4]},
        ]
    }
    wall_convey["hypothesis_box"] = (10, 8, 2, 2)
    wall_convey["frame_records"] = [
        {"geom": (4, 2, 2), "xy": (6, 2), "wh": (2, 2), "sig": (4, 3, 2, 2)},
        {"geom": (1, 2, 2), "xy": (6, 4), "wh": (2, 2), "sig": (1, 6, 2, 2)},
        {"geom": (2, 2, 2), "xy": (10, 8), "wh": (2, 2), "sig": (2, 5, 2, 2)},
        {"geom": (1, 2, 4), "xy": (2, 4), "wh": (4, 2), "sig": (1, 9, 4, 2)},
    ]
    # Pushing right (4) requires push_box (4,4), which overlaps wall (2,4,4,2); convey must push down (2) from (6,2) instead.
    assert step_toward("convey", [1, 2, 3, 4], wall_convey) == 2

    # 5. _swept_box prevents quantum > 1 from jumping across or landing on a wall in _around_prefix
    assert _swept_box((0, 0, 2, 2), (4, 0)) == (0, 0, 6, 2)
    swept_prefix = _around_prefix((0, 4, 2, 2), (8, 4, 2, 2), 4, set(), [1, 2, 3, 4], [(3, 4, 2, 2)])
    assert swept_prefix and swept_prefix[0] in (1, 2), swept_prefix

    # 6. Blocked wall hit (pred_hit=False) with hud_changed=True does not clear conditional_blocks; teleport resets walked without adding wall
    blocked_hud = dict(hud_lock_state)
    blocked_hud["deferred_candidates"] = [[1, 2, 2]]
    blocked_hud["conditional_blocks"] = [[2, 10, 2]]
    note_result(blocked_hud, False, ("SIMPLE", 1), "continue", switch_contact, switch_contact)
    assert blocked_hud["conditional_blocks"] == [[2, 10, 2]], blocked_hud["conditional_blocks"]
    tp_state = {
        "mode": "execute",
        "script": [dict(hyp_steps[0], walked=15)],
        "script_i": 0,
        "route_quantum": 5,
        "route_blocks": [],
        "route_prefix": [2, 2],
        "refuted_candidates": [[4, 2, 2]],
        "hypothesis_target": [1, 7, 7],
        "role_evidence": {"avatar": [1, 3, 5]},
        "schema_obs": {"roles": [{"role": "avatar", "geom": [1, 3, 5]}]},
    }
    tp_before = [{"geom": (1, 3, 5), "xy": (14, 22), "wh": (5, 3), "sig": (1, 4, 5, 3)}]
    tp_after = [{"geom": (1, 3, 5), "xy": (29, 42), "wh": (5, 3), "sig": (1, 4, 5, 3)}]
    note_route(tp_state, tp_before, tp_after, 3, False)
    assert tp_state["route_blocks"] == [], tp_state["route_blocks"]
    note_result(tp_state, False, ("SIMPLE", 3), "continue", tp_before, tp_after)
    assert tp_state["script"][0]["walked"] == 0 and tp_state["route_prefix"] == [] and tp_state["refuted_candidates"] == []

    # 7. ar25 fix: 1-frame hypothesis_target=None flicker while mover_box is bound does not abort explore(avatar)
    flicker_state = {
        "mode": "execute",
        "script": [
            {
                "primitive": "explore",
                "binding": "avatar",
                "kind": "translate",
                "role": "avatar",
                "role_b": "none",
                "repeat": 3,
                "tries": 0,
                "tried": [],
                "walked": 2,
                "fails": 0,
                "anchor_i": 0,
                "fail_budget": 4,
                "labeled": False,
            }
        ],
        "script_i": 0,
        "plan_primitive": "explore",
        "plan_predicate": {"kind": "translate", "role": "avatar", "role_b": "none", "dir": "right", "geom": [5, 9, 9]},
        "hypothesis_target": None,
        "mover_box": (12, 12, 9, 9),
        "role_evidence": {"avatar": [5, 9, 9]},
        "schema_obs": {"roles": [{"role": "avatar", "geom": [5, 9, 9]}]},
    }
    fl_before = [{"geom": (5, 9, 9), "xy": (9, 12), "wh": (9, 9), "sig": (5, 20, 9, 9)}]
    fl_after = [{"geom": (5, 9, 9), "xy": (12, 12), "wh": (9, 9), "sig": (5, 20, 9, 9)}]
    note_result(flicker_state, True, ("SIMPLE", 4), "continue", fl_before, fl_after)
    assert flicker_state["script_i"] == 0 and flicker_state["script"][0]["walked"] == 3, flicker_state

    # 8. Top-down field hazard/reframe or FMF refute_decoy refutes stuck candidate early at walked >= 8
    decoy_state = {
        "mode": "execute",
        "script": [
            {
                "primitive": "approach",
                "binding": "avatar,goal",
                "kind": "translate",
                "role": "avatar",
                "role_b": "goal",
                "repeat": 6,
                "tries": 0,
                "tried": [],
                "walked": 7,
                "fails": 0,
                "anchor_i": 0,
                "fail_budget": 4,
                "labeled": False,
            }
        ],
        "script_i": 0,
        "plan_primitive": "approach",
        "plan_predicate": {"kind": "translate", "role": "avatar", "role_b": "goal", "dir": "right", "geom": [1, 2, 2]},
        "hypothesis_target": [2, 2, 2],
        "hypothesis_box": (20, 12, 2, 2),
        "candidates": [
            {"geom": [2, 2, 2], "box": (20, 12, 2, 2), "role": "goal"},
            {"geom": [3, 2, 2], "box": (4, 12, 2, 2), "role": "switch"},
        ],
        "refuted_candidates": [],
        "top_down_field": {"hazard": True, "reframe": True, "interference": "destructive"},
        "role_evidence": {"avatar": [1, 2, 2]},
        "schema_obs": {"roles": [{"role": "avatar", "geom": [1, 2, 2]}, {"role": "goal", "geom": [2, 2, 2]}]},
    }
    note_result(decoy_state, True, ("SIMPLE", 4), "continue", fl_before, fl_after)
    assert [2, 2, 2] in decoy_state["refuted_candidates"], decoy_state["refuted_candidates"]
    assert decoy_state["hypothesis_target"] == [3, 2, 2], decoy_state["hypothesis_target"]
    assert decoy_state["script"][0]["walked"] == 0

    # 9. Fuzzy Merkle Forest unhashing (64-bit Associative Merkle Tree + cold_payload_store + coordinate/planmode wiring)
    from my_agent_v7_inos import BitPackedMerkleNodeCodec, MonadAssociativeMerkleTree
    from monad2.coordinate import _field_line, _field_state, _fmf_lines, _for_model, _sync_candidates
    from monad2.planmode import prompt as plan_prompt

    tree = MonadAssociativeMerkleTree()
    board_sig16 = 0b1010_1001_0010_0011
    w_place = tree.inos_merkle_log_solved_pattern(
        board_sig16=board_sig16,
        procedure_name="SOLVED:PLACE",
        level_idx=0,
        payload={"goal": "PLACE", "primitive": "convey"},
    )
    p16_place = tree.register_procedure_name("SOLVED:PLACE")
    c32_place = ((board_sig16 << 16) | p16_place) & 0xFFFFFFFF
    pid_win = tree.parent_prim_to_id16.get("PRIM_11_AUTOBIOGRAPHICAL_CAUSAL_WIN_CHAIN", 11)
    u64_place = BitPackedMerkleNodeCodec.pack_u64(c32_place, pid_win, w_place)
    unhashed_node = tree.unhash_packed_node(u64_place, relational_sig16=board_sig16)
    assert unhashed_node["decoded_procedure"] == "SOLVED:PLACE", unhashed_node
    assert "PLACE" in unhashed_node["endorsed_goals"], unhashed_node
    assert "convey" in unhashed_node["recommended_primitives"], unhashed_node
    assert unhashed_node["cold_payload"]["goal"] == "PLACE", unhashed_node
    assert unhashed_node["decoded_board_relations"]["has_dpad"] is True
    assert unhashed_node["decoded_board_relations"]["has_avatar"] is True
    assert unhashed_node["decoded_board_relations"]["has_pushable"] is True

    # Shift centroid via sibling collapse and verify cold_payload_store survives signature collapse
    shifted_u64, status_str, _eps = tree.dynamic_merkle_graph.ingest_streaming_hash(
        fuzzy_sig32=c32_place ^ 0x00010000,
        parent_id16=pid_win,
        initial_weight16=0x0400,
        weight_boost16=0x0200,
        payload_meta={"extra_tag": "preserved"},
    )
    assert status_str == "COLLAPSED_SIBLING", status_str
    shifted_exp = tree.dynamic_merkle_graph.expand_node_payload_on_demand(shifted_u64, tree.parent_id16_to_parent)
    assert shifted_exp["cold_store_payload"].get("goal") == "PLACE", shifted_exp
    assert shifted_exp["cold_store_payload"].get("extra_tag") == "preserved", shifted_exp

    pid_gate = tree.parent_prim_to_id16.get("PRIM_04_COUPLED_REMOTE_SWITCH_GATE", 4)
    u64_gate, _st, _ep = tree.dynamic_merkle_graph.ingest_streaming_hash(
        fuzzy_sig32=((board_sig16 << 16) | tree.register_procedure_name("PRIM:toggle")) & 0xFFFFFFFF,
        parent_id16=pid_gate,
        initial_weight16=0x0800,
        weight_boost16=0x0100,
        payload_meta={"procedure": "PRIM:toggle", "b2_minutiae": (1 << 5) | (1 << 7)},
    )
    agent_fmf = _agent()
    agent_fmf.associative_merkle_tree = tree
    agent_fmf.last_unhashed_merkle_packet = tree.unhash_packed_node(u64_gate, relational_sig16=board_sig16)
    assert "GATED" in agent_fmf.last_unhashed_merkle_packet["decoded_minutiae"]
    assert "COUPLED" in agent_fmf.last_unhashed_merkle_packet["decoded_minutiae"]
    agent_fmf.observer_field_engine = type(
        "ObsStub",
        (),
        {
            "last_field_state": type(
                "FieldStateStub",
                (),
                {
                    "ricci_curvature_r": -0.35,
                    "lorentz_force_vec": (0.8, -0.2),
                    "dark_matter_potential_w": 1.2,
                    "top_down_omega_hz": 4.0,
                    "standing_wave_energy": 1.5,
                    "standing_wave_regime": "DESTRUCTIVE_INTERFERENCE_REFRAME",
                },
            )()
        },
    )()
    agent_fmf.self_narrative = {
        "gohst_coupling_mode": "COUPLED_RESONANCE",
        "gohst_coupling_r": 0.72,
        "inos_depth_budget": 6,
    }
    agent_fmf.inos_meta_engine = type("InosStub", (), {"last_tonic_report": {"optimal_depth_budget": 6, "safety_preset": "DEEP"}})()
    agent_fmf.last_ab_packet = type(
        "AbStub",
        (),
        {"model_b_verdict": "CHALLENGE_HAZARD_TRAJECTORY", "recommended_top_down_action": "INVERT_CANONICAL_DPAD_IMMEDIATELY"},
    )()
    agent_fmf.canonical_to_raw_dpad = {1: 2, 2: 1, 3: 4, 4: 3, 5: 5}

    from monad2.coordinate import _state as _coord_state_fn

    coord_state = _coord_state_fn(agent_fmf)
    coord_state.update(
        {
            "mode": "discover",
            "discover_steps": 3,
            "legal": [1, 2, 3, 4, 6],
            "mover_box": (2, 2, 2, 2),
            "role_evidence": {"avatar": [1, 2, 2], "switch": [3, 2, 2]},
            "affordances": {"switch": [[6, 2]]},
            "schema_obs": {
                "roles": [
                    {"role": "avatar", "geom": [1, 2, 2]},
                    {"role": "switch", "geom": [3, 2, 2]},
                ],
                "relations": [],
            },
            "frame_records": [
                {"geom": (1, 2, 2), "xy": (2, 2), "wh": (2, 2), "sig": (1, 4, 2, 2)},
                {"geom": (2, 4, 4), "xy": (14, 14), "wh": (4, 4), "sig": (2, 8, 4, 4)},
                {"geom": (3, 2, 2), "xy": (6, 2), "wh": (2, 2), "sig": (3, 4, 2, 2)},
            ],
            "conditional_blocks": [[8, 8, 4]],
            "refuted_candidates": [],
            "deferred_candidates": [],
        }
    )
    fmf_text, fmf_goals = _fmf_lines(("aff:avatar", "aff:remote", "aff:switch"), "", agent=agent_fmf)
    assert "toggle" in fmf_text and "PRIM_04_COUPLED_REMOTE_SWITCH_GATE" in fmf_text, fmf_text
    assert coord_state["fmf_unhashed"]["candidate_priority"] == "SWITCH_FIRST", coord_state["fmf_unhashed"]
    assert coord_state["fmf_unhashed"]["candidate_bias"] == "switch_first", coord_state["fmf_unhashed"]
    f_dict = _field_state(agent_fmf, [1, 2, 3, 4, 6])
    f_line = _field_line(f_dict)
    assert "DESTRUCTIVE_INTERFERENCE_REFRAME" in f_line and "COUPLED_RESONANCE" in f_line and "dpad=inverted" in f_line, f_line

    # Candidate ordering promotes switch (3, 2, 2) ahead of larger distant shape (2, 4, 4) when SWITCH_FIRST / COUPLED is active
    _sync_candidates(agent_fmf, coord_state, [1, 2, 3, 4, 6], "REACH")
    assert coord_state["tonic_depth"] == 6
    assert coord_state["candidates"] and tuple(coord_state["candidates"][0]["geom"]) == (3, 2, 2), coord_state["candidates"]

    # _for_model preserves [fmf] and [field] in first and planmode.prompt includes FMF:, Field:, Tonic:
    stream_lines = [
        "[board] bg=0 shapes=3",
        "[roles] avatar:(1, 2, 2) switch:(3, 2, 2)",
        f"[fmf] {fmf_text}",
        f"[field] {f_line}",
    ]
    model_ctx = _for_model("\n".join(stream_lines))
    assert "[fmf]" in model_ctx and "[field]" in model_ctx, model_ctx
    p_usr = plan_prompt(
        {
            "board": "bg=0 shapes=3",
            "roles": "avatar:(1, 2, 2) switch:(3, 2, 2)",
            "fmf": fmf_text,
            "field": f_line,
            "tonic": "depth=6",
        },
        coord_state,
    )
    assert "FMF:" in p_usr and "Field:" in p_usr and "Tonic:" in p_usr, p_usr

    # parse_plan prepends toggle(switch) when switch_first + conditional_blocks are active and scales fail_budget with tonic_depth
    gated_steps = parse_plan(
        plan_json,
        coord_state["schema_obs"],
        coord_state,
    )
    assert len(gated_steps) >= 2 and gated_steps[0]["primitive"] == "toggle", gated_steps
    assert gated_steps[1]["fail_budget"] == 6, gated_steps[1]

    # 10. Pass 1 -> Pass 2 Online Solver Synthesis (REACH_BFS, SOKOBAN_PUSH, PANEL_ALIGN, SWITCH_GATE)
    from monad2.general_guard import static_violations
    from monad2.synthesizer import (
        SynthesizedSolverSpec,
        apply_synthesized_priors_to_state,
        plan_with_synthesized_solver,
        record_level_observation,
        reset_synthesized_store,
        synthesize_solver_from_pass1,
    )

    assert static_violations() == [], static_violations()
    reset_synthesized_store()

    # Pass 1 records avatar (1,2,2), wall (3,2,4), quantum=2, refuted decoy (4,2,2), and confirmed goal (2,2,2)
    p1_agent = _agent()
    p1_state = {
        "level": 0,
        "legal": [1, 2, 3, 4],
        "route_quantum": 2,
        "role_evidence": {
            "avatar": [1, 2, 2],
            "wall": [3, 2, 4],
            "goal": [2, 2, 2],
        },
        "refuted_candidates": [[4, 2, 2]],
        "hypothesis_target": [2, 2, 2],
        "frame_records": [
            {"geom": (1, 2, 2), "xy": (4, 8), "wh": (2, 2), "sig": (1, 4, 2, 2)},
            {"geom": (3, 2, 4), "xy": (4, 4), "wh": (4, 2), "sig": (3, 3, 4, 2)},
            {"geom": (4, 2, 2), "xy": (4, 12), "wh": (2, 2), "sig": (4, 5, 2, 2)},
            {"geom": (2, 2, 2), "xy": (4, 0), "wh": (2, 2), "sig": (2, 2, 2, 2)},
        ],
    }
    p1_agent._m2_coord = p1_state
    record_level_observation(p1_agent, p1_state, 0, cleared=True)
    spec_reach = synthesize_solver_from_pass1(p1_agent, slot=1)
    roundtrip = SynthesizedSolverSpec.from_dict(spec_reach.to_dict())
    assert roundtrip.solver_family == "REACH_BFS" and roundtrip.quantum == 2, roundtrip
    assert (4, 2, 2) in roundtrip.refuted_geoms and (2, 2, 2) in roundtrip.goal_geoms

    # Pass 2 starts on fresh Level 0 state: applies priors and routes around wall (4,4,4,2) to goal (4,0,2,2)
    p2_state = {
        "level": 0,
        "legal": [1, 2, 3, 4],
        "frame_records": list(p1_state["frame_records"]),
    }
    apply_synthesized_priors_to_state(p1_agent, p2_state, roundtrip, 0)
    assert p2_state["mover_box"] == (4, 8, 2, 2) and p2_state["route_quantum"] == 2
    assert [4, 2, 2] in p2_state["refuted_candidates"]
    reach_plan = plan_with_synthesized_solver(roundtrip, p2_state, [1, 2, 3, 4])
    assert reach_plan and ("SIMPLE", 3) in reach_plan and ("SIMPLE", 1) in reach_plan, reach_plan
    assert ("SIMPLE", 2) not in reach_plan, reach_plan

    # Sokoban push solver synthesizes box-push plan onto target receptor
    spec_push = SynthesizedSolverSpec(
        solver_family="SOKOBAN_PUSH",
        goal_type="PLACE",
        avatar_geom=(5, 2, 2),
        movable_geoms=[(1, 2, 2)],
        goal_geoms=[(2, 2, 2)],
        quantum=2,
    )
    push_s2 = {
        "level": 0,
        "legal": [1, 2, 3, 4],
        "mover_box": (2, 4, 2, 2),
        "route_quantum": 2,
        "role_evidence": {"avatar": [5, 2, 2], "movable": [1, 2, 2], "goal": [2, 2, 2]},
        "frame_records": [
            {"geom": (5, 2, 2), "xy": (2, 4), "wh": (2, 2), "sig": (5, 4, 2, 2)},
            {"geom": (1, 2, 2), "xy": (4, 4), "wh": (2, 2), "sig": (1, 6, 2, 2)},
            {"geom": (2, 2, 2), "xy": (8, 4), "wh": (2, 2), "sig": (2, 8, 2, 2)},
        ],
    }
    sokoban_plan = plan_with_synthesized_solver(spec_push, push_s2, [1, 2, 3, 4])
    assert sokoban_plan == [("SIMPLE", 4), ("SIMPLE", 4)], sokoban_plan

    # Panel alignment solver diffs equal-sized panels and clicks the mismatching editable cell
    panel_grid = [[0] * 16 for _ in range(16)]
    for r in range(2, 6):
        for c in range(2, 6):
            panel_grid[r][c] = 3
            panel_grid[r][c + 6] = 3
    panel_grid[3][9] = 4  # Mismatch at (x=9, y=3) in right panel (x=8..11, y=2..5)
    spec_panel = SynthesizedSolverSpec(
        solver_family="PANEL_ALIGN",
        goal_type="MATCH",
        has_panel_pair=True,
        panel_dims=(4, 4),
    )
    panel_s2 = {
        "level": 0,
        "legal": [6],
        "affordances": {"clickable": [[9, 3]]},
        "frame_records": [
            {"geom": (1, 4, 4), "xy": (2, 2), "wh": (4, 4), "sig": (1, 3, 4, 4)},
            {"geom": (1, 4, 4), "xy": (8, 2), "wh": (4, 4), "sig": (1, 3, 4, 4)},
        ],
    }
    align_plan = plan_with_synthesized_solver(spec_panel, panel_s2, [6], grid=panel_grid)
    assert align_plan == [("CLICK", 9, 3)], align_plan

    # Hybrid corridor + click board: when all 4 D-pad moves at mover_box are blocked, CLICK candidates are emitted
    from monad2.candidates import enumerate_candidates

    hybrid_recs = [
        {"geom": [1, 44, 41], "xy": [13, 19], "wh": [41, 44], "click": [33, 41], "sig": [1, 14, 41, 44]},
        {"geom": [4, 2, 3], "xy": [32, 39], "wh": [3, 2], "click": [33, 40], "sig": [4, 8, 3, 2]},
        {"geom": [5, 2, 2], "xy": [20, 39], "wh": [2, 2], "click": [21, 40], "sig": [5, 4, 2, 2]},
        {"geom": [3, 2, 5], "xy": [23, 13], "wh": [5, 2], "click": [25, 14], "sig": [3, 9, 5, 2]},
        {"geom": [3, 2, 5], "xy": [32, 13], "wh": [5, 2], "click": [34, 14], "sig": [3, 11, 5, 2]},
    ]
    hybrid_cands = enumerate_candidates(
        hybrid_recs,
        {"avatar": [4, 2, 3]},
        "REACH",
        [1, 2, 3, 4, 6],
        affordances={"clickable": [[25, 14], [34, 14]]},
        state={
            "mover_box": (32, 39, 3, 2),
            "route_blocks": [(32, 39, 1), (32, 39, 2), (32, 39, 3), (32, 39, 4)],
        },
        span=64,
    )
    assert any(c["kind"] == "CLICK" and c["anchor"] == [25, 14] for c in hybrid_cands), hybrid_cands

    # Pass 1 -> Pass 2 responsive vs inert click telemetry synthesis
    p1_click_agent = _agent()
    p1_click_agent.level_inert_coords = {(10, 10): 2}
    p1_click_agent.level_responsive_coords = {(20, 20): 1}
    p1_click_state = {
        "level": 0,
        "legal": [6],
        "affordances": {"clickable": [[10, 10], [20, 20]]},
        "frame_records": [
            {"geom": (2, 4, 4), "xy": (8, 8), "wh": (4, 4), "sig": (2, 3, 4, 4)},
            {"geom": (3, 4, 4), "xy": (18, 18), "wh": (4, 4), "sig": (3, 5, 4, 4)},
        ],
    }
    p1_click_agent._m2_coord = p1_click_state
    spec_click = synthesize_solver_from_pass1(p1_click_agent, slot=2)
    assert (2, 4, 4) in spec_click.inert_geoms and (3, 4, 4) in spec_click.responsive_geoms, spec_click
    click_plan = plan_with_synthesized_solver(spec_click, dict(p1_click_state), [6])
    assert click_plan == [("CLICK", 20, 20)], click_plan

    # 11. LLM Watch-and-Intervene Supervisor (_supervise_execution) & Solver Issue Prompt
    from monad2.coordinate import _supervise_execution
    from monad2.synthesizer import plan_bridge_lattice_prefix, resolve_shared_avatar_box

    sup_state = {
        "mode": "execute",
        "script": [{"primitive": "approach", "binding": "avatar,goal", "repeat": 4, "walked": 1, "fails": 0}],
        "script_i": 0,
        "plan_primitive": "approach",
        "mover_box": (4, 4, 3, 3),
        "hypothesis_box": (16, 4, 3, 3),
        "interventions_level": 0,
        "exec_seen_states": {},
    }
    sup_recs = [
        {"geom": (2, 3, 3), "xy": (4, 4), "wh": (3, 3), "sig": (2, 8, 3, 3)},
        {"geom": (1, 3, 3), "xy": (16, 4), "wh": (3, 3), "sig": (1, 8, 3, 3)},
    ]
    # Unexpected reset triggers LLM intervention with solver_issue containing "level reset"
    _supervise_execution(sup_state, "reset", sup_recs, "approach")
    assert sup_state.get("surprise_pending") == "level reset", sup_state
    assert "level reset" in str((sup_state.get("replan_context") or {}).get("solver_issue") or ""), sup_state
    issue_prompt = plan_prompt(
        {"board": "bg=0", "roles": "avatar:(2, 3, 3)"},
        str(sup_state["surprise_pending"]),
        sup_state.get("replan_context"),
    )
    assert "Solver issue: level reset" in issue_prompt, issue_prompt

    # Loop detection triggers LLM intervention after 4 visits to the same state, and caps at 2 interventions
    sup_loop_state = {
        "mode": "execute",
        "script": [{"primitive": "approach", "binding": "avatar,goal", "repeat": 8, "walked": 1, "fails": 0}],
        "script_i": 0,
        "plan_primitive": "approach",
        "mover_box": (4, 4, 3, 3),
        "hypothesis_box": (16, 4, 3, 3),
        "interventions_level": 1,
        "exec_seen_states": {},
    }
    for _ in range(4):
        _supervise_execution(sup_loop_state, "continue", sup_recs, "approach")
    assert sup_loop_state.get("surprise_pending") == "solver loop", sup_loop_state
    assert "solver loop" in str((sup_loop_state.get("replan_context") or {}).get("solver_issue") or ""), sup_loop_state
    # Once interventions_level reaches 2, a 3rd intervention latches coop_handoff instead of requesting another LLM call
    sup_loop_state["surprise_pending"] = None
    sup_loop_state["exec_seen_states"] = {}
    for _ in range(4):
        _supervise_execution(sup_loop_state, "continue", sup_recs, "approach")
    assert sup_loop_state.get("coop_handoff") is True and not sup_loop_state.get("surprise_pending"), sup_loop_state

    # 12. Inner-part rotation in roles.note_effect and resolve_shared_avatar_box
    eye_before = [
        {"geom": (2, 3, 3), "xy": (10, 10), "wh": (3, 3), "sig": (2, 8, 3, 3)},
        {"geom": (4, 1, 1), "xy": (11, 10), "wh": (1, 1), "sig": (4, 5, 1, 1)},
    ]
    eye_after = [
        {"geom": (2, 3, 3), "xy": (10, 14), "wh": (3, 3), "sig": (2, 8, 3, 3)},
        {"geom": (4, 1, 1), "xy": (11, 16), "wh": (1, 1), "sig": (4, 5, 1, 1)},
    ]
    eye_ev = note_effect({}, eye_before, eye_after, ("SIMPLE", 2), "continue")
    assert eye_ev.get("avatar") == [2, 3, 3] and [4, 1, 1] in (eye_ev.get("avatar_parts") or []), eye_ev
    # Preserves known avatar even when a sentry shares (2, 3, 3) on deeper levels
    sentry_before = eye_before + [{"geom": (2, 3, 3), "xy": (22, 10), "wh": (3, 3), "sig": (2, 6, 3, 3)}]
    sentry_after = eye_after + [{"geom": (2, 3, 3), "xy": (22, 14), "wh": (3, 3), "sig": (2, 6, 3, 3)}]
    sentry_ev = note_effect(eye_ev, sentry_before, sentry_after, ("SIMPLE", 2), "continue")
    assert sentry_ev.get("avatar") == [2, 3, 3], sentry_ev
    resolved_av = resolve_shared_avatar_box(
        {"avatar_fill": 8},
        sentry_after,
        [(10, 14, 3, 3), (22, 14, 3, 3)],
    )
    assert resolved_av == (10, 14, 3, 3), resolved_av

    # 13. Bridge-lattice planner (with palette and D4 transpose invariance)
    def _make_bridge_records(palette_shift: int = 0, transpose: bool = False) -> tuple[list[dict], tuple[int, int, int, int], tuple[int, int, int, int]]:
        def _c(v: int) -> int:
            return ((v + palette_shift) % 9) + 1

        def _xywh(x: int, y: int, w: int, h: int) -> tuple[tuple[int, int], tuple[int, int]]:
            return ((y, x), (h, w)) if transpose else ((x, y), (w, h))

        # Bridge-connected lattice with mw=mh=3, quantum=6:
        # Avatar node at (4,4), bridge at (7,4), middle node at (10,4), bridge at (10,7), goal node at (10,10)
        recs: list[dict] = []
        av_xy, av_wh = _xywh(4, 4, 3, 3)
        recs.append({"geom": (2, av_wh[1], av_wh[0]), "xy": av_xy, "wh": av_wh, "sig": (2, _c(2), av_wh[0], av_wh[1])})
        for fx, fy in ((7, 4), (10, 4), (10, 7)):
            xy, wh = _xywh(fx, fy, 3, 3)
            recs.append({"geom": (1, wh[1], wh[0]), "xy": xy, "wh": wh, "sig": (1, _c(1), wh[0], wh[1])})
        gl_xy, gl_wh = _xywh(10, 10, 3, 3)
        recs.append({"geom": (1, gl_wh[1], gl_wh[0]), "xy": gl_xy, "wh": gl_wh, "sig": (1, _c(7), gl_wh[0], gl_wh[1])})
        av_box = (av_xy[0], av_xy[1], av_wh[0], av_wh[1])
        gl_box = (gl_xy[0], gl_xy[1], gl_wh[0], gl_wh[1])
        return recs, av_box, gl_box

    b_recs0, b_av0, b_gl0 = _make_bridge_records(palette_shift=0, transpose=False)
    b_path0 = plan_bridge_lattice_prefix({}, b_recs0, b_av0, b_gl0, 6, set(), [1, 2, 3, 4])
    b_recs_pal, b_av_pal, b_gl_pal = _make_bridge_records(palette_shift=3, transpose=False)
    b_path_pal = plan_bridge_lattice_prefix({}, b_recs_pal, b_av_pal, b_gl_pal, 6, set(), [1, 2, 3, 4])
    assert b_path0 == [4, 2] and b_path_pal == b_path0, (b_path0, b_path_pal)
    b_recs_tr, b_av_tr, b_gl_tr = _make_bridge_records(palette_shift=5, transpose=True)
    b_path_tr = plan_bridge_lattice_prefix({}, b_recs_tr, b_av_tr, b_gl_tr, 6, set(), [1, 2, 3, 4])
    assert b_path_tr == [2, 4], b_path_tr

    # 14. Multi-valve parity locking & rider-marker alignment
    from monad2.planmode import _aligned_rider_fills, _rider_alignment_status

    valve_before = [
        {"geom": (1, 2, 2), "xy": (12, 56), "wh": (2, 2), "sig": (1, 1, 2, 2)},
        {"geom": (1, 2, 2), "xy": (16, 56), "wh": (2, 2), "sig": (1, 1, 2, 2)},
        {"geom": (1, 2, 2), "xy": (24, 56), "wh": (2, 2), "sig": (1, 1, 2, 2)},
        {"geom": (1, 2, 2), "xy": (28, 56), "wh": (2, 2), "sig": (1, 1, 2, 2)},
        {"geom": (1, 2, 1), "xy": (8, 32), "wh": (1, 2), "sig": (1, 8, 1, 2)},
        {"geom": (1, 2, 4), "xy": (12, 36), "wh": (4, 2), "sig": (1, 8, 4, 2)},
    ]
    valve_after = [
        {"geom": (1, 2, 2), "xy": (12, 56), "wh": (2, 2), "sig": (1, 1, 2, 2)},
        {"geom": (1, 2, 2), "xy": (16, 56), "wh": (2, 2), "sig": (1, 1, 2, 2)},
        {"geom": (1, 2, 2), "xy": (24, 56), "wh": (2, 2), "sig": (1, 1, 2, 2)},
        {"geom": (1, 2, 2), "xy": (28, 56), "wh": (2, 2), "sig": (1, 1, 2, 2)},
        {"geom": (1, 2, 1), "xy": (8, 32), "wh": (1, 2), "sig": (1, 8, 1, 2)},
        {"geom": (1, 2, 4), "xy": (12, 32), "wh": (4, 2), "sig": (1, 8, 4, 2)},
    ]
    mf, st_al, appr, retr = _rider_alignment_status(valve_before, valve_after)
    assert mf == {8} and st_al is True and not appr and not retr
    assert _aligned_rider_fills(valve_after) == {8}
    valve_state = {
        "mode": "execute",
        "step_i": 0,
        "stall_steps": 0,
        "affordances": {"clickable": [[12, 56], [16, 56], [24, 56], [28, 56]]},
        "script": [{"primitive": "toggle", "binding": "clickable", "kind": "press", "repeat": 6, "anchor_i": 0}],
        "plan_predicate": {"kind": "changed", "role": "clickable", "role_b": "none", "geom": [1, 2, 2]},
    }
    note_result(valve_state, False, ("CLICK", 12, 56), "continue", valve_before, valve_after)
    v_step = valve_state["script"][0]
    assert v_step.get("parity_locked") is True
    assert [16, 56] in v_step.get("inert_anchors", []) and [28, 56] in v_step.get("inert_anchors", [])
    assert [24, 56] not in v_step.get("tried_anchors", [])

    # Per-pair retreating button recovery: if [24, 56] retreats, it un-inerts its partner [28, 56]
    valve_retreat_after = [
        {"geom": (1, 2, 2), "xy": (12, 56), "wh": (2, 2), "sig": (1, 1, 2, 2)},
        {"geom": (1, 2, 2), "xy": (16, 56), "wh": (2, 2), "sig": (1, 1, 2, 2)},
        {"geom": (1, 2, 2), "xy": (24, 56), "wh": (2, 2), "sig": (1, 1, 2, 2)},
        {"geom": (1, 2, 2), "xy": (28, 56), "wh": (2, 2), "sig": (1, 1, 2, 2)},
        {"geom": (1, 2, 1), "xy": (8, 32), "wh": (1, 2), "sig": (1, 8, 1, 2)},
        {"geom": (1, 2, 4), "xy": (12, 40), "wh": (4, 2), "sig": (1, 8, 4, 2)},
    ]
    note_result(valve_state, False, ("CLICK", 24, 56), "continue", valve_before, valve_retreat_after)
    assert [24, 56] in v_step.get("inert_anchors", [])
    assert [28, 56] not in v_step.get("inert_anchors", [])

    # Mandatory Level 0 LLM call gate and ready() with empty candidates
    from monad2.coordinate import _can_coop_handoff
    from monad2.planmode import ready

    dummy_ag = _agent()
    init_st = {
        "llm_level": 0,
        "llm_calls": 0,
        "llm_calls_level": 0,
        "discover_steps": 2,
        "stable_roles": "avatar",
        "mover_box": (10, 10, 2, 2),
        "candidates": [],
        "schema_obs": {"roles": [{"role": "avatar", "geom": [1, 2, 2]}]},
    }
    assert _can_coop_handoff(dummy_ag, init_st) is False
    assert ready(init_st) is True
    init_st["llm_calls"] = 1
    init_st["llm_calls_level"] = 1
    assert _can_coop_handoff(dummy_ag, init_st) is True
    assert ready(init_st) is False

    # Loop-erased causal_policy recording and symbolic resolution
    from monad2.synthesizer import plan_with_synthesized_solver, record_level_observation

    f0 = [{"geom": (1, 2, 2), "xy": (10, 10), "wh": (2, 2), "sig": (1, 4, 2, 2), "click": 1, "area": 4}]
    f1 = [{"geom": (1, 2, 2), "xy": (12, 10), "wh": (2, 2), "sig": (1, 4, 2, 2), "click": 1, "area": 4}]
    f2 = [{"geom": (1, 2, 2), "xy": (12, 12), "wh": (2, 2), "sig": (1, 4, 2, 2), "click": 1, "area": 4}]
    pol_ag = _agent()
    pol_st = {"llm_level": 0, "span": 64, "role_evidence": {"avatar": [1, 2, 2]}, "frame_records": f0}
    record_level_observation(pol_ag, pol_st, 0, cleared=False, before=f0, after=f1, action=("SIMPLE", 4), outcome="continue")
    record_level_observation(pol_ag, pol_st, 0, cleared=False, before=f1, after=f0, action=("SIMPLE", 3), outcome="continue")
    record_level_observation(pol_ag, pol_st, 0, cleared=False, before=f0, after=f1, action=("CLICK", 10, 10), outcome="continue")
    spec_pol = record_level_observation(pol_ag, pol_st, 0, cleared=True, before=f1, after=f2, action=("SIMPLE", 2), outcome="completed")
    assert len(spec_pol.levels[0].causal_policy) == 2
    pol_st["frame_records"] = f0
    assert plan_with_synthesized_solver(spec_pol, pol_st, [1, 2, 3, 4, 6]) == [("CLICK", 10, 10)]
    pol_st["frame_records"] = f1
    assert plan_with_synthesized_solver(spec_pol, pol_st, [1, 2, 3, 4, 6]) == [("SIMPLE", 2)]

    reset_synthesized_store()
    reset_store()
    os.environ.pop("MONAD2_COORDINATE", None)
    print("PLAN PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


