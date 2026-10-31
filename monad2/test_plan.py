"""Menu legality, contradictory role bindings, and plan-once execution."""
from __future__ import annotations

import os

from llama_cpp import LlamaGrammar

from monad2.menu import build_menu, executive_grammar, menu_line, resolve_choice
from monad2.planmode import expand_action, note_result, parse_plan, plan_grammar
from monad2.schema import (
    assert_structure,
    drop_contradictions,
    induce,
    match,
    render,
    reset_store,
    upsert,
)
from monad2.test_roles import _click_scene, _dpad_scene


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
    grammar = executive_grammar(menu)
    assert "SIMPLE" not in grammar
    assert "click(clickable#0)" in grammar
    LlamaGrammar.from_string(grammar)
    LlamaGrammar.from_string(plan_grammar())
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
    obs = induce(click_recs, None, "", "bg=0 shapes=4 hud_rows=0 hud_cols=0")
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
    plan_json = (
        '{"goal":"REACH","steps":[{"primitive":"approach","binding":"avatar,goal",'
        '"predicate":"translate","role":"avatar","role_b":"goal","repeat":1}]}'
    )
    steps = parse_plan(plan_json, {"roles": dpad["roles"], "relations": dpad["relations"]}, {"progress_axis": None})
    assert steps and steps[0]["primitive"] == "approach" and steps[0]["repeat"] == 1
    state = {
        "mode": "execute",
        "script": steps,
        "script_i": 0,
        "stall_steps": 0,
        "affordances": dpad["affordances"],
        "plan_predicate": {
            "kind": "translate",
            "role": "avatar",
            "role_b": "goal",
            "dir": "left",
            "axis": "none",
            "geom": list(next(slot["geom"] for slot in dpad["roles"] if slot["role"] == "avatar")),
            "geom_b": None,
        },
        "last_ref": "simple#3",
    }
    action, ref = expand_action(steps[0], [1, 2, 3, 4, 5], state, build_menu([1, 2, 3, 4, 5], dpad["affordances"]))
    assert action[0] == "SIMPLE", action
    note_result(state, False, action, "continue", [], [])
    assert state.get("surprise_pending") == "predicate false", state.get("surprise_pending")

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
    held["discover_steps"] = 2
    held["stable_roles"] = held["role_line"]
    held["prev_roles"] = held["role_line"]
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
