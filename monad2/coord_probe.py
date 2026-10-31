"""Coordination probe: a few actions on three games. Not a score run.

Loads the local Qwen A'/B' and Mistral GGUFs, then plays ls20, lp85, and vc33
with solvers off and a hard action cap. The blind 25-game harness is not used.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

GAMES = ("ls20", "lp85", "vc33")
OUT = Path(os.environ.get("MONAD2_COORD_OUT", "/tmp/exp/m2_coord_probe.json"))


def _quiet_flags() -> None:
    from monad2.factorial import FACTORS

    cap = os.environ.get("MONAD2_COORD_MAX_ACTIONS", "6")
    sample = os.environ.get("MONAD2_COORD_SAMPLE", "")
    for name in list(os.environ):
        if name.startswith("MONAD2_") or name.startswith("MONAD1_"):
            os.environ.pop(name, None)
    os.environ["MONAD2_COORDINATE"] = "1"
    os.environ["MONAD2_COORD_MAX_ACTIONS"] = cap
    if sample:
        os.environ["MONAD2_COORD_SAMPLE"] = sample
    os.environ["MONAD1_DISABLE_GAME_SOLVERS"] = "1"
    # FACTORS stays off. Importing it above only documents the set we refuse to enable.
    for name in FACTORS:
        os.environ[name] = "0"


def main() -> int:
    _quiet_flags()
    from monad2.llm import get_backend

    loaded = get_backend().warmup()
    print("models", json.dumps(loaded), flush=True)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    from run_competition_eval import main as eval_main

    rc = eval_main(
        [
            "--offline",
            "--blind-id",
            "--no-game-solvers",
            "--game-order",
            ",".join(GAMES),
            "--max-game-seconds",
            "900",
            "--environments-dir",
            "/workspace/environment_files",
            "--output",
            str(OUT),
        ]
    )
    if not OUT.is_file():
        print("coord probe produced no output", file=sys.stderr)
        return rc or 1
    payload = json.loads(OUT.read_text(encoding="utf-8"))
    summary = _summarize(payload, loaded)
    summary_path = OUT.with_name("m2_coord_summary.json")
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    guard, transfer, recognition = _schema_check()
    summary["guard"] = guard
    summary["schema_transfer"] = transfer
    if recognition:
        summary["recognition_decision"] = recognition.get("decision")
        summary["recognition_schema"] = recognition.get("schema")
    sample = _sample(payload, recognition)
    sample_path = Path(os.environ.get("MONAD2_COORD_SAMPLE", "/workspace/monad2/COORD_SAMPLE.md"))
    sample_path.write_text(sample, encoding="utf-8")
    print(json.dumps({k: v for k, v in summary.items() if k != "schema_transfer"}, indent=2), flush=True)
    print(json.dumps({"schema_transfer": {k: transfer.get(k) for k in ("ok", "identity_geoms", "rebound", "schema_id", "line", "pure")}}, indent=2), flush=True)
    print(f"sample {sample_path}", flush=True)
    return rc


def _summarize(payload: dict, loaded: dict) -> dict:
    keys = (
        "coord_steps",
        "coord_inhibit",
        "coord_inhibit_changed",
        "coord_accept",
        "coord_combine",
        "coord_explore",
        "coord_errors",
        "qwen_proposals",
        "qwen_differ",
        "qwen_influenced",
        "fmf_in_stream",
        "expect_scored",
        "expect_hits",
        "expect_doc_scored",
        "expect_doc_hits",
        "surprise_revisions",
        "coord_ladder_vetoes",
        "carried_theories",
        "infl_scp",
        "infl_canvas",
        "infl_pll",
        "infl_tonic",
        "infl_fmf",
        "infl_effect",
        "infl_dead",
        "infl_collapse",
        "infl_skinner",
        "infl_heuristic",
        "infl_qwen_a",
        "infl_qwen_b",
        "infl_model_a",
        "infl_model_b",
        "infl_solver",
        "infl_schema",
        "schema_in_stream",
        "schema_revisions",
    )
    totals = {key: 0 for key in keys}
    latencies = []
    games = []
    traced = 0
    rows_n = 0
    for result in payload.get("per_game_results") or []:
        stats = (result.get("monad2") or {})
        for key in keys:
            totals[key] += int(stats.get(key, 0) or 0)
        thoughts = stats.get("thought_log") or []
        rows_n += len(thoughts)
        for row in thoughts:
            if row.get("decision") and row.get("reason") and row.get("expectation") and row.get("decision") != "error":
                traced += 1
            step_ms = (row.get("latency_ms") or {}).get("step")
            if isinstance(step_ms, (int, float)):
                latencies.append(float(step_ms))
        games.append(
            {
                "game": str(result.get("game_id", "")).split("-")[0],
                "actions": result.get("actions"),
                "levels": result.get("levels_completed"),
                "state": result.get("state"),
                "elapsed_s": result.get("elapsed_s"),
                "thoughts": len(thoughts),
            }
        )
    scored = totals["expect_scored"]
    return {
        "kind": "coordination_test_not_a_score_run",
        "models": loaded,
        "runtime": "llama.cpp CPU via llama-cpp-python, temperature 0, seed 0",
        "games": games,
        "actions": payload.get("actions"),
        "levels": payload.get("levels_completed"),
        "wins": payload.get("wins"),
        "elapsed_s": payload.get("elapsed_s"),
        "totals": totals,
        "thought_rows": rows_n,
        "rows_with_decision_reason_expectation": traced,
        "expectation_accuracy": (totals["expect_hits"] / scored) if scored else None,
        "document_expectation_accuracy": (
            totals["expect_doc_hits"] / totals["expect_doc_scored"]
            if totals["expect_doc_scored"]
            else None
        ),
        "latency_ms_mean": (sum(latencies) / len(latencies)) if latencies else None,
        "latency_ms_max": max(latencies) if latencies else None,
    }


def _schema_check() -> tuple[dict, dict, dict | None]:
    """Runtime and static guards, then one executive step on a recolored rotated frame."""
    from monad2.general_guard import HITS, assert_solvers_unreached, static_violations
    from monad2.schema import STORE, audit_store, transformed_case

    guard = {"runtime_hits": len(HITS), "runtime_ok": False, "static": [], "static_ok": False}
    try:
        assert_solvers_unreached()
        guard["runtime_ok"] = True
    except AssertionError as exc:
        guard["runtime_error"] = str(exc)
    guard["static"] = static_violations()
    guard["static_ok"] = guard["static"] == []
    guard["schema_problems"] = audit_store()
    guard["schemas"] = [
        {
            "id": row.get("id"),
            "episode": row.get("episode"),
            "roles": [slot.get("role") for slot in row.get("roles") or []],
            "relations": [rel.get("kind") for rel in row.get("relations") or []],
        }
        for row in STORE
    ]
    case = transformed_case()
    public = {key: value for key, value in case.items() if key != "grid"}
    recognition = None
    grid = case.get("grid")
    if isinstance(grid, list) and grid:
        recognition = _recognition_step(grid, case.get("hud_rows") or [], case.get("hud_cols") or [])
    return guard, public, recognition


def _recognition_step(grid, hud_rows, hud_cols) -> dict | None:
    from monad2 import runtime as rt
    from monad2.coordinate import decide

    agent = type("A", (), {})()
    agent.m2 = {key: 0 for key in rt.COUNTERS}
    agent.m2_thought_log = []
    agent._m2_avail = [1, 2, 3, 4, 5]
    agent._m2_grid = grid
    agent.prev_grid = grid
    agent._m2_state_hash = 1
    agent.dead_actions = {}
    agent.current_level = 0
    agent.m2_ltp = None
    agent._m2_coord = None
    agent.hud_rows = set(hud_rows)
    agent.hud_cols = set(hud_cols)
    agent.hud_coords = set()
    decide(agent, ("SIMPLE", 4), "move the avatar onto the unique shape")
    if not agent.m2_thought_log:
        return None
    return agent.m2_thought_log[-1]


def _sample(payload: dict, recognition: dict | None = None) -> str:
    from monad2.coordinate import format_sample

    picked = None
    binding = None
    for result in payload.get("per_game_results") or []:
        thoughts = (result.get("monad2") or {}).get("thought_log") or []
        game = str(result.get("game_id", "")).split("-")[0]
        if thoughts and (picked is None or len(thoughts) > len(picked[1])):
            picked = (game, thoughts)
        for row in thoughts:
            text = str(row.get("schema") or "")
            if "this is schema" in text and (binding is None or "rebound" in text):
                binding = (game, row)
                if "rebound" in text:
                    break
    parts = ["# Thought stream sample\n", "Coordination excerpt, not a score.\n"]
    if picked is None:
        parts.append("No executive steps were recorded.\n")
    else:
        game, rows = picked
        level = rows[0].get("level", 0)
        parts.append(f"## Live play on `{game}`, level {level}\n")
        parts.append("Blinded ids are on. The schema store is not keyed by this prefix.\n")
        parts.append(format_sample(rows, limit=3))
        parts.append("")
    if binding is not None:
        game, row = binding
        parts.append(f"## Schema binding seen during play (`{game}`)\n")
        parts.append(format_sample([row], limit=1))
        parts.append("")
    if recognition:
        parts.append("## Schema from play, recognized on a recolored and rotated frame\n")
        parts.append(
            "The frame is a palette permutation and a quarter turn of a frame from this run, "
            "with the avatar shape grown by one cell. The schema store has no game id.\n"
        )
        parts.append(format_sample([recognition], limit=1))
        parts.append("")
    return "\n".join(parts) + "\n"


if __name__ == "__main__":
    raise SystemExit(main())
