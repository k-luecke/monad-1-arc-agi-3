"""Coordination wiring with a scripted backend. No model weights and no game."""
from __future__ import annotations

import os

from monad2 import runtime as rt
from monad2.coordinate import decide, format_sample, observe, reset_carried
from monad2.discovery import EPISODE_FMF


class Backend:
    def __init__(self, executive: str):
        self.executive = executive
        self.calls: list[str] = []

    def complete(self, role: str, system: str, user: str):
        self.calls.append(role)
        if role == "a":
            return (
                '{"action":"SIMPLE 4","effect":"shifts right","reason":"scp projection points right"}',
                3.0,
            )
        if role == "b":
            return (
                '{"action":"SIMPLE 3","effect":"shifts left","reason":"A walks into a dead move","verdict":"challenge"}',
                4.0,
            )
        if "MISMATCH" in user:
            return (
                '{"decision":"inhibit","action":"SIMPLE 2","expect_change":true,'
                '"expectation":"object moves down","reason":"mismatch revised the reach theory",'
                '"theory":"PLACE the object against the wall","goal":"PLACE","used":["pll","qwen_b"]}',
                5.0,
            )
        return self.executive, 5.0


def _grid():
    g = [[0] * 16 for _ in range(16)]
    for c in range(12):
        g[1][c] = 3
    g[8][2] = 4
    g[8][3] = 4
    g[12][14] = 5
    g[13][14] = 5
    return g


def _agent():
    agent = type("A", (), {})()
    agent.m2 = {k: 0 for k in rt.COUNTERS}
    agent.m2_thought_log = []
    agent._m2_avail = [1, 2, 3, 4, 5]
    agent._m2_grid = _grid()
    agent.prev_grid = _grid()
    agent._m2_state_hash = 7
    agent.dead_actions = {}
    agent.current_level = 0
    agent.m2_ltp = None
    agent._m2_coord = None
    return agent


def main() -> int:
    from monad2.canvas_stream import diff_records, expectation_matches

    before = [{"sig": (3, 3, 12, 1), "click": (0, 1), "xy": (0, 1)}]
    after = [{"sig": (3, 3, 12, 1), "click": (4, 1), "xy": (4, 1)}]
    diff = diff_records(before, after)
    assert diff["moved"] and diff["moved"][0]["dx"] == 4
    assert expectation_matches("sig 3,3,12,1 moves +4x +0y", diff) is True
    assert expectation_matches("sig 3,3,12,1 vanishes", diff) is False
    assert expectation_matches("no shape change", diff_records(before, before)) is True
    assert expectation_matches("avatar translates toward the goal", diff) is True
    assert expectation_matches("frame changes under labeled exploration", diff) is True

    os.environ.pop("MONAD2_COORDINATE", None)
    os.environ.pop("MONAD2_HOLDOUT_GAME", None)
    reset_carried()
    agent = _agent()
    backend = Backend("")
    assert rt.maybe_replace_key(agent, ("SIMPLE", 1), "heuristic") == ("SIMPLE", 1)
    assert backend.calls == []

    os.environ["MONAD2_COORDINATE"] = "1"
    import monad2.coordinate as coord

    routed = {}

    def _route(agent, key, reason="", backend=None):
        routed["reason"] = reason
        return ("SIMPLE", 4)

    coord.decide = _route
    assert rt.maybe_replace_key(agent, ("SIMPLE", 1), "canvas-vector-least-visited") == ("SIMPLE", 4)
    assert routed["reason"] == "canvas-vector-least-visited"
    coord.decide = decide

    accept = (
        '{"decision":"inhibit","action":"SIMPLE 3","expect_change":true,'
        '"expectation":"avatar shifts left","reason":"inhibit the heuristic; B fits the fmf retrieval",'
        '"theory":"REACH the far object","goal":"REACH","used":["qwen_b","fmf"]}'
    )
    backend = Backend(accept)
    chosen = decide(agent, ("SIMPLE", 1), "canvas-vector-least-visited", backend=backend)
    assert chosen == ("SIMPLE", 3)
    assert chosen != ("SIMPLE", 1)
    assert agent.m2["coord_steps"] == 1
    assert agent.m2["coord_inhibit_changed"] == 1
    assert agent.m2["qwen_differ"] == 1
    assert agent.m2["qwen_influenced"] == 1
    assert agent.m2["fmf_in_stream"] == 1
    assert agent.m2["infl_fmf"] >= 1
    assert agent.m2["infl_qwen_b"] >= 1
    row = agent.m2_thought_log[-1]
    assert row["reason"] and row["expectation"]
    assert row["decision"] == "inhibit"
    assert "[canvas_doc]" in row["stream"] and "sig=" in row["stream"]
    assert "[solver]" in row["stream"] and "[model_a]" in row["stream"] and "[model_b]" in row["stream"]
    assert "Qwen A'" in format_sample(agent.m2_thought_log)

    observe(agent, False)
    assert agent.m2["expect_scored"] == 1
    assert agent.m2["expect_hits"] == 0
    assert row["result"] == "unchanged"
    assert row["expectation_hit"] is False

    chosen = decide(agent, ("SIMPLE", 1), "canvas-vector-least-visited", backend=backend)
    assert chosen == ("SIMPLE", 2)
    assert agent.m2["surprise_revisions"] == 1
    assert agent.m2_thought_log[-1]["goal"] == "PLACE"
    assert agent.m2_thought_log[-1]["theory"] != agent.m2_thought_log[0]["theory"]

    reset_carried()
    agent = _agent()
    quiet = (
        '{"decision":"accept","action":"SIMPLE 3","expect_change":false,'
        '"expectation":"no shape change","reason":"hold; the fmf retrieval is still REACH",'
        '"theory":"REACH the far object","goal":"REACH","used":["fmf"]}'
    )
    backend = Backend(quiet)
    decide(agent, ("SIMPLE", 1), "heuristic", backend=backend)
    observe(agent, False)
    assert agent.m2["expect_hits"] == 1
    assert agent.m2["expect_doc_hits"] == 1
    assert EPISODE_FMF == []
    decide(agent, ("SIMPLE", 1), "heuristic", backend=backend)
    observe(agent, False)
    assert agent.m2["carried_theories"] == 1
    assert EPISODE_FMF and EPISODE_FMF[-1][1] == "REACH"

    os.environ["MONAD2_HOLDOUT_GAME"] = "cd82"
    before = len(EPISODE_FMF)
    agent.m2_ltp.confirms["REACH"] = 1
    decide(agent, ("SIMPLE", 1), "heuristic", backend=backend)
    observe(agent, False)
    assert len(EPISODE_FMF) == before

    agent = _agent()
    agent.dead_actions = {7: {("SIMPLE", 1)}}
    dead_exec = (
        '{"decision":"accept","action":"SIMPLE 1","expect_change":true,'
        '"expectation":"moves up","reason":"take the heuristic","theory":"REACH","goal":"REACH","used":["heuristic"]}'
    )
    blocked = decide(agent, ("SIMPLE", 4), "heuristic", backend=Backend(dead_exec))
    assert blocked != ("SIMPLE", 1)
    assert agent.m2["coord_ladder_vetoes"] == 1
    assert agent.m2_thought_log[-1]["reason"].startswith("D-ladder rejected")

    agent = _agent()
    agent._m2_coord = {
        "theory": {"goal": "REACH", "text": "keep going"},
        "pending": None,
        "mismatch": None,
        "plan": [("SIMPLE", 2)],
        "plan_expect": "no shape change",
        "plan_expect_change": False,
        "plan_goal": "REACH",
    }
    quiet_backend = Backend(quiet)
    assert decide(agent, ("SIMPLE", 1), "heuristic", backend=quiet_backend) == ("SIMPLE", 2)
    assert quiet_backend.calls == []
    assert agent.m2["coord_plan_steps"] == 1
    assert agent.m2_thought_log[-1]["decision"] == "plan"
    assert agent.m2_thought_log[-1]["latency_ms"]["step"] == 0.0

    agent = _agent()
    cut_off = (
        '{"decision":"inhibit","action":"SIMPLE 3","primitive":"approach","binding":"avatar,goal",'
        '"expect_change":true,"expectation":"avatar translates toward the goal","reason":"The solver'
    )
    held = decide(agent, ("SIMPLE", 1), "heuristic", backend=Backend(cut_off))
    assert held == ("SIMPLE", 3), held
    row = agent.m2_thought_log[-1]
    assert row["decision"] == "inhibit"
    assert row["primitive"]
    assert row["predicate"]

    reset_carried()
    os.environ.pop("MONAD2_COORDINATE", None)
    os.environ.pop("MONAD2_HOLDOUT_GAME", None)
    print("COORDINATE UNIT PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
