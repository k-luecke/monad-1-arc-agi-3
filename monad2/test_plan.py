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
    reset_store()
    os.environ.pop("MONAD2_COORDINATE", None)
    print("PLAN PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
