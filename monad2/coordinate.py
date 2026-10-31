"""Thought stream, Qwen A'/B' proposals, and the Mistral executive.

Off unless MONAD2_COORDINATE=1. The flag is not a factorial column. A score
run that leaves it unset never calls a model and never changes the action.

Each step:
  cognitive pieces write structured lines
  Qwen A' proposes from the SCP projection and the canvas
  Qwen B' audits that proposal (the callosum exchange)
  Mistral accepts, combines, or inhibits, and states an expectation
  the D-ladder validates the move before it is returned
After the step, the SCP diff is compared with that expectation. A mismatch
goes back into the next stream and the working theory is revised. A theory
that matches twice is stored in the episode FMF by affordance features.
Holdout prefixes do not write.
"""
from __future__ import annotations

import json
import os
import re

from monad2.discovery import recall, remember, reset_store
from monad2.memory import (
    GOAL_TYPES,
    EpisodeLTP,
    _features,
    _goal,
    _is_schema,
    _text,
    corpus_path,
    eligible,
    grid_features,
    load_records,
)
from monad2.scp import project, validate_action

# Theories confirmed in this process. The next game's stream can read them.
CARRIED: list[dict] = []

_A_SYSTEM = (
    "You are Qwen A', the bottom-up proposer. Read the SCP projection and the canvas_doc "
    "shape list (type, sig, click anchor). model_a is a trajectory proposal, not an order. "
    "Propose one motor primitive and the role binding it uses. Do not copy a stored solution. "
    'Reply with JSON only: {"action":"SIMPLE 4","primitive":"approach","binding":"avatar,goal",'
    '"effect":"avatar translates toward the goal","reason":"..."} '
    "Actions are SIMPLE 1 up, SIMPLE 2 down, SIMPLE 3 left, SIMPLE 4 right, "
    "SIMPLE 5 interact, or CLICK x y."
)
_B_SYSTEM = (
    "You are Qwen B', the auditor. You see A's proposal and the model_b veto line. "
    "Uphold a veto of a wall, hazard, or a step that undoes progress. Otherwise challenge A "
    "and name your own primitive. "
    'Reply with JSON only: {"action":"SIMPLE 3","primitive":"hold_gradient","binding":"avatar,goal",'
    '"effect":"avatar does not reverse","reason":"...","verdict":"challenge"} '
    "Use verdict agree only when A's effect matches the canvas."
)
_E_SYSTEM = (
    "You are Mistral, the executive. Solver, Skinner, model_a, and the Qwen lines are "
    "proposals. You accept, combine, or inhibit them. They are not the action source. "
    "If A and B disagree, or model_b vetoes the solver, inhibit the solver and pick the "
    "proposal that fits the canvas and the retrieved concept. "
    "Explore only when you set decision to explore, and say why. "
    "Pick one primitive from the [primitives] line, or inhibit it. "
    "expectation is that primitive's effect: 'avatar translates toward the goal', "
    "'avatar does not reverse', or 'frame changes under labeled exploration'. "
    "A move that is not a primitive must be primitive explore. "
    "If a [schema] line names a role binding, reason in that frame: which object plays "
    "the avatar, the goal, or the receptor, and what was substituted. "
    "If the stream contains MISMATCH, change your theory. "
    "plan is up to two further actions to run only if this expectation matches. Use [] when unsure. "
    'Reply with JSON only: {"decision":"inhibit","action":"SIMPLE 3","primitive":"hold_gradient",'
    '"binding":"avatar,goal","plan":[],"expect_change":true,'
    '"expectation":"avatar does not reverse","reason":"...","theory":"...","goal":"REACH",'
    '"used":["qwen_b","schema"]}. '
    "goal is REACH, PLACE, or MATCH."
)


def reset_carried() -> None:
    CARRIED.clear()
    reset_store()
    from monad2.schema import reset_store as reset_schemas

    reset_schemas()


def _stats(agent) -> dict:
    stats = getattr(agent, "m2", None)
    if not isinstance(stats, dict):
        agent.m2 = {}
        stats = agent.m2
    return stats


def _bump(agent, key: str, n: int = 1) -> None:
    stats = _stats(agent)
    stats[key] = int(stats.get(key, 0) or 0) + n


def _state(agent) -> dict:
    state = getattr(agent, "_m2_coord", None)
    if not isinstance(state, dict):
        state = {"theory": {"goal": None, "text": ""}, "pending": None, "mismatch": None}
        agent._m2_coord = state
    return state


def _log(agent) -> list:
    log = getattr(agent, "m2_thought_log", None)
    if not isinstance(log, list):
        agent.m2_thought_log = []
        log = agent.m2_thought_log
    return log


def _norm(key):
    if not key:
        return None
    try:
        kind = key[0]
    except (TypeError, IndexError):
        return None
    if kind == "CLICK" and len(key) >= 3:
        return ("CLICK", int(key[1]), int(key[2]))
    if kind == "SIMPLE" and len(key) >= 2:
        try:
            return ("SIMPLE", int(key[1]))
        except (TypeError, ValueError):
            return None
    return None


def _action_id(key) -> int:
    key = _norm(key)
    if key is None:
        return -1
    if key[0] == "CLICK":
        return 6
    return int(key[1])


def _fmt(key) -> str:
    key = _norm(key)
    if key is None:
        return "none"
    if key[0] == "CLICK":
        return f"CLICK {key[1]} {key[2]}"
    names = {1: "up", 2: "down", 3: "left", 4: "right", 5: "interact"}
    return f"SIMPLE {key[1]} ({names.get(key[1], '?')})"


def _json_obj(text: str) -> dict | None:
    if not text:
        return None
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end <= start:
        return None
    blob = text[start : end + 1]
    try:
        obj = json.loads(blob)
    except json.JSONDecodeError:
        return None
    return obj if isinstance(obj, dict) else None


def _parse_action(raw, legal: list[int]):
    if raw is None:
        return None
    if isinstance(raw, int):
        text = str(raw)
    else:
        text = str(raw).strip().upper()
    click = re.search(r"CLICK\s+(\d+)\s+(\d+)", text)
    if click:
        key = ("CLICK", int(click.group(1)), int(click.group(2)))
        if 6 in legal:
            return key
        return None
    simple = re.search(r"\b([1-6])\b", text)
    if not simple:
        return None
    aid = int(simple.group(1))
    if aid == 6:
        return ("CLICK", 32, 32) if 6 in legal else None
    if aid not in legal:
        return None
    return ("SIMPLE", aid)


def _known_noop(agent, key) -> bool:
    state = getattr(agent, "_m2_state_hash", None)
    if state is None:
        state = getattr(agent, "prev_hash", None)
    dead = getattr(agent, "dead_actions", {}) or {}
    try:
        return bool(state is not None and key in dead.get(state, ()))
    except TypeError:
        return False


def _known_hazard(agent, key) -> bool:
    from monad2.runtime import _known_hazard as hazard

    return bool(hazard(agent, key))


def _legal(agent) -> list[int]:
    raw = getattr(agent, "_m2_avail", None) or []
    out = []
    for item in raw:
        try:
            aid = int(item)
        except (TypeError, ValueError):
            continue
        if aid != 0 and aid not in out:
            out.append(aid)
    return out or [1, 2, 3, 4, 5]


def _clip(text: str, n: int = 160) -> str:
    text = " ".join(str(text).split())
    if len(text) <= n:
        return text
    return text[: n - 1] + "…"


def _fmf_lines(features: tuple[str, ...], holdout: str) -> tuple[str, list[str]]:
    try:
        records = eligible(load_records(corpus_path()), holdout)
    except (OSError, ValueError):
        records = []
    query = set(features) or {"aff:unknown"}
    ranked = []
    for rec in records:
        overlap = len(query & set(_features(rec)))
        if overlap <= 0:
            continue
        goal = _goal(rec) or "SCHEMA"
        quote = _clip(_text(rec), 140)
        bonus = 2 if _is_schema(rec) else 0
        ranked.append((overlap + bonus, goal, quote))
    ranked.sort(key=lambda row: (-row[0], row[1]))
    episode = recall(tuple(sorted(query)), k=3)
    carried = []
    for row in CARRIED:
        if set(row.get("features") or ()) & query:
            carried.append(f"{row.get('goal')} ({_clip(row.get('note') or '', 80)})")
    parts = []
    goals = []
    if ranked:
        _score, goal, quote = ranked[0]
        goals.append(goal)
        parts.append(f"corpus {goal}: \"{quote}\"")
    if episode:
        parts.append("episode " + ",".join(episode))
        goals.extend(episode)
    if carried:
        parts.append("carried " + "; ".join(carried[:2]))
    if not parts:
        return "no overlapping record for " + ",".join(sorted(query)), []
    return _clip(" | ".join(parts), 280), goals


def _effect_line(agent) -> tuple[str, object]:
    table = getattr(agent, "fx_dpad", None)
    if not table:
        return "no learned shift yet", None
    bits = []
    proposal = None
    try:
        items = list(table.items())
    except Exception:
        return "effect table unreadable", None
    for aid, counter in items[:4]:
        try:
            common = counter.most_common(1)
        except Exception:
            continue
        if not common:
            continue
        shift, n = common[0]
        if int(n) <= 0 or shift in ((0, 0), (0, 0.0)):
            continue
        bits.append(f"SIMPLE {aid} -> {shift} x{n}")
        if proposal is None:
            try:
                proposal = ("SIMPLE", int(aid))
            except (TypeError, ValueError):
                proposal = None
    if not bits:
        return "no repeated shift yet", None
    return "; ".join(bits), proposal


def _dead_line(agent, legal: list[int]) -> tuple[str, list]:
    state = getattr(agent, "_m2_state_hash", None)
    dead = getattr(agent, "dead_actions", {}) or {}
    found = []
    try:
        bucket = list(dead.get(state, ()))
    except TypeError:
        bucket = []
    for key in bucket:
        norm = _norm(key)
        if norm is not None and _action_id(norm) in legal:
            found.append(norm)
    if not found:
        return "none in this state", []
    return "known no-ops: " + ", ".join(_fmt(k) for k in found[:4]), found


def _skinner_line(agent) -> str:
    model = getattr(agent, "skinner_model", None)
    rewards = getattr(model, "action_kind_rewards", None)
    if not rewards:
        return "no reinforced action yet"
    try:
        best = max(rewards.items(), key=lambda item: float(item[1]))
    except (TypeError, ValueError):
        return "no reinforced action yet"
    return f"highest reward {best[0]}={float(best[1]):.2f}"


def _canvas_line(agent, legal: list[int]):
    canvas = getattr(agent, "second_order_canvas", None)
    if canvas is None or not hasattr(canvas, "summary_metrics"):
        return "no canvas", None
    try:
        metrics = canvas.summary_metrics()
    except Exception:
        return "canvas unread", None
    aid = metrics.get("audited_first_raw_aid")
    passed = bool(metrics.get("audit_passed"))
    reason = metrics.get("audit_reason") or ""
    proposal = None
    try:
        if aid is not None and int(aid) in legal:
            proposal = ("SIMPLE", int(aid))
    except (TypeError, ValueError):
        proposal = None
    text = f"audit_passed={passed} first={_fmt(proposal) if proposal else 'none'} { _clip(reason, 80)}"
    return text, proposal if passed else None


def _tonic_line(agent) -> str:
    depth = None
    narrative = getattr(agent, "self_narrative", None)
    if isinstance(narrative, dict):
        depth = narrative.get("inos_depth_budget")
    engine = getattr(agent, "inos_meta_engine", None)
    report = getattr(engine, "last_tonic_report", None) if engine is not None else None
    if isinstance(report, dict) and report.get("optimal_depth_budget") is not None:
        depth = report.get("optimal_depth_budget")
        preset = report.get("safety_preset", "")
        return f"depth {depth} {preset}".strip()
    if depth is not None:
        return f"depth {depth}"
    return "no tonic sample on this step"


def _collapse_line(agent) -> str:
    guard = getattr(agent, "collapse_guard", None)
    state = getattr(agent, "_m2_state_hash", None)
    if guard is None or not hasattr(guard, "get_phi"):
        return "no collapse guard"
    try:
        phi = float(guard.get_phi(state if state is not None else 0))
    except Exception:
        return "collapse unread"
    return f"phi={phi:.1f}"


def _pll_line(state: dict) -> str:
    mismatch = state.get("mismatch")
    if not mismatch:
        return "no surprise yet"
    doc = mismatch.get("doc") or ""
    return (
        f"MISMATCH expected {mismatch.get('expectation')} "
        f"({mismatch.get('expect_change')}) but the frame was {mismatch.get('observed')}"
        + (f" document {doc}" if doc else "")
    )


def _stream(agent, heuristic, reason: str, legal: list[int]) -> tuple[str, dict]:
    from monad2.canvas_stream import scene_brief, solver_name

    grid = getattr(agent, "_m2_grid", None)
    prev = getattr(agent, "prev_grid", None)
    proj = project(grid, prev, legal=legal) if grid is not None else None
    if proj is None:
        scp = "no frame yet"
        features: tuple[str, ...] = ()
    else:
        scp = " ".join(proj.tokens())
        features = grid_features(proj, legal)
    holdout = os.getenv("MONAD2_HOLDOUT_GAME", "")
    fmf_text, fmf_goals = _fmf_lines(features, holdout)
    effect_text, effect_key = _effect_line(agent)
    dead_text, dead_keys = _dead_line(agent, legal)
    canvas_text, canvas_key = _canvas_line(agent, legal)
    state = _state(agent)
    scene = scene_brief(agent, state.get("last_diff"))
    scene["solver"] = f"{solver_name(reason, agent)} proposes {_fmt(_norm(heuristic))}"
    schema_line = "schema unread"
    try:
        from monad2.schema import hypothesis_line, remember_scene

        remember_scene(agent, scene, state.get("last_diff"))
        schema_line = hypothesis_line(agent, scene, state.get("last_diff"))
    except Exception:
        schema_line = "schema unread"
    if scene.get("playfield"):
        scp = f"{scp} canvas:{scene['playfield']}"
    entries = {
        "scp": scp,
        "canvas": canvas_text,
        "canvas_key": canvas_key,
        "pll": _pll_line(state),
        "tonic": _tonic_line(agent),
        "fmf": fmf_text,
        "fmf_goals": fmf_goals,
        "features": features,
        "effect": effect_text,
        "effect_key": effect_key,
        "dead": dead_text,
        "dead_keys": dead_keys,
        "collapse": _collapse_line(agent),
        "skinner": _skinner_line(agent),
        "heuristic": f"{_fmt(heuristic)} because {_clip(reason or 'unspecified', 80)}",
        "heuristic_key": _norm(heuristic),
        "theory": state["theory"].get("text") or "none yet",
        "theory_goal": state["theory"].get("goal"),
        "scene": scene,
        "schema": schema_line,
    }
    from monad2.primitives import proposals_for

    prim_line, prim_items = proposals_for(state.get("schema_obs") or {}, state, legal)
    entries["primitives"] = prim_line
    entries["primitive_list"] = prim_items
    lines = [
        f"[scp] {_clip(entries['scp'], 220)}",
        f"[canvas_doc] {_clip(scene['shapes'], 280)}",
        f"[playfield] {scene['playfield']}",
        f"[avatar] {scene['avatar']}",
        f"[control] {_clip(scene['control'], 160)}",
        f"[diff] {_clip(scene['events'], 220)}",
        f"[meta] {scene['meta']}",
        f"[model_a] {scene['model_a']}",
        f"[model_b] {scene['model_b']}",
        f"[solver] {scene['solver']}",
        f"[canvas] {entries['canvas']}",
        f"[pll] {entries['pll']}",
        f"[tonic] {entries['tonic']}",
        f"[fmf] {entries['fmf']}",
        f"[effect] {entries['effect']}",
        f"[dead] {entries['dead']}",
        f"[collapse] {entries['collapse']}",
        f"[skinner] {entries['skinner']}",
        f"[heuristic] {entries['heuristic']}",
        f"[theory] {entries['theory_goal'] or 'none'}: {_clip(entries['theory'], 160)}",
        f"[schema] {_clip(entries['schema'], 360)}",
        f"[primitives] {_clip(entries['primitives'], 320)}",
    ]
    return "\n".join(lines), entries


def _backend_complete(backend, role: str, system: str, user: str) -> tuple[str, float]:
    return backend.complete(role, system, user)


def _ladder_ok(agent, key, legal: list[int]) -> tuple[bool, str]:
    aid = _action_id(key)
    click = (int(key[1]), int(key[2])) if key and key[0] == "CLICK" else None
    verdict = validate_action(
        aid,
        legal,
        known_noop=_known_noop(agent, key),
        known_hazard=_known_hazard(agent, key),
        click=click,
    )
    return bool(verdict.ok), f"{verdict.rung}:{verdict.reason}"


def _fallback(agent, legal: list[int], rejected, qwen_keys: list):
    for key in qwen_keys:
        ok, _why = _ladder_ok(agent, key, legal)
        if ok and key not in rejected:
            return key
    for aid in legal:
        if aid == 6:
            key = ("CLICK", 32, 32)
        else:
            key = ("SIMPLE", aid)
        ok, _why = _ladder_ok(agent, key, legal)
        if ok and key not in rejected:
            return key
    return None


def _influence(agent, used: list[str], chosen, entries: dict, qwen: dict, reason: str) -> None:
    sources = {str(name).lower() for name in used}
    text = reason.lower()
    if chosen == entries.get("heuristic_key"):
        sources.add("heuristic")
    if chosen == entries.get("canvas_key") or "canvas" in text:
        sources.add("canvas")
    if chosen == entries.get("effect_key") or "effect" in text:
        sources.add("effect")
    if chosen == qwen.get("a") or "qwen a" in text or "a'" in text:
        sources.add("qwen_a")
    if chosen == qwen.get("b") or "qwen b" in text or "b'" in text or "auditor" in text:
        sources.add("qwen_b")
    if any(word in text for word in ("fmf", "retriev", "corpus", "memory")):
        sources.add("fmf")
    if any(word in text for word in ("mismatch", "surprise", "pll")):
        sources.add("pll")
    if "dead" in text or "no-op" in text or "noop" in text:
        sources.add("dead")
    if "skinner" in text:
        sources.add("skinner")
    if "scp" in text or "projection" in text:
        sources.add("scp")
    if "tonic" in text or "depth" in text:
        sources.add("tonic")
    if "collapse" in text or "phi" in text:
        sources.add("collapse")
    if "model a" in text or "model_a" in text:
        sources.add("model_a")
    if "model b" in text or "model_b" in text or "veto" in text:
        sources.add("model_b")
    if "solver" in text or "operant" in text or "bfs" in text:
        sources.add("solver")
    if "schema" in text or "rebound" in text or "binding" in text:
        sources.add("schema")
    if "sig" in text or "canvas_doc" in text or "shape" in text:
        sources.add("canvas")
    aliases = {
        "scp": "infl_scp",
        "canvas": "infl_canvas",
        "pll": "infl_pll",
        "surprise": "infl_pll",
        "tonic": "infl_tonic",
        "fmf": "infl_fmf",
        "memory": "infl_fmf",
        "effect": "infl_effect",
        "dead": "infl_dead",
        "collapse": "infl_collapse",
        "skinner": "infl_skinner",
        "heuristic": "infl_heuristic",
        "qwen_a": "infl_qwen_a",
        "a": "infl_qwen_a",
        "qwen_b": "infl_qwen_b",
        "b": "infl_qwen_b",
        "model_a": "infl_model_a",
        "model_b": "infl_model_b",
        "solver": "infl_solver",
        "schema": "infl_schema",
    }
    for name in sources:
        key = aliases.get(name)
        if key:
            _bump(agent, key)


def _for_model(text: str) -> str:
    """Shorter prompt for prefill. The logged stream stays complete."""
    kept = []
    for line in text.splitlines():
        if line.startswith("[canvas_doc]") or line.startswith("[playfield]") or line.startswith("[meta]"):
            kept.append(line[:160])
        else:
            kept.append(line[:220])
    return "\n".join(kept)[:1400]


def _follow_plan(agent, legal: list[int]):
    """Next action from the executive plan. A mismatch or a ladder veto drops it."""
    state = _state(agent)
    plan = list(state.get("plan") or [])
    if not plan or state.get("mismatch"):
        state["plan"] = []
        return None
    key = _norm(plan[0])
    if key is None:
        state["plan"] = []
        return None
    aid = _action_id(key)
    if aid not in legal:
        state["plan"] = []
        return None
    ok, _why = _ladder_ok(agent, key, legal)
    if not ok:
        state["plan"] = []
        return None
    state["plan"] = plan[1:]
    return key


def _remember_plan(state: dict, raw, chosen, legal: list[int]) -> None:
    plan = []
    if isinstance(raw, list):
        for item in raw[:2]:
            key = _parse_action(item, legal)
            if key is not None and key != chosen:
                plan.append(key)
    state["plan"] = plan


def decide(agent, key, reason: str = "", backend=None):
    """Executive choice. Returns an action key. Never raises into the caller."""
    legal = _legal(agent)
    heuristic = _norm(key)
    stream, entries = _stream(agent, heuristic, reason, legal)
    if entries["fmf"] and not entries["fmf"].startswith("no overlapping"):
        _bump(agent, "fmf_in_stream")
    if "this is schema" in str(entries.get("schema") or ""):
        _bump(agent, "schema_in_stream")
    followed = _follow_plan(agent, legal)
    if followed is not None:
        state = _state(agent)
        expectation = _clip(str(state.get("plan_expect") or "no shape change"), 160)
        expect_change = bool(state.get("plan_expect_change"))
        _bump(agent, "coord_plan_steps")
        _bump(agent, "coord_steps")
        state["pending"] = {
            "action": followed,
            "expect_change": expect_change,
            "expectation": expectation,
            "goal": state.get("plan_goal"),
            "features": entries["features"],
            "theory": state["theory"].get("text") or "",
            "shapes": list((entries.get("scene") or {}).get("records") or []),
            "primitive": state.get("plan_primitive") or "",
        }
        _log(agent).append(
            {
                "level": int(getattr(agent, "current_level", 0) or 0),
                "heuristic": _fmt(heuristic),
                "solver": (entries.get("scene") or {}).get("solver"),
                "scene": _clip((entries.get("scene") or {}).get("shapes") or "", 280),
                "schema": entries.get("schema") or "",
                "stream": stream,
                "decision": "plan",
                "action": _fmt(followed),
                "action_key": list(followed),
                "reason": "continuing the executive plan; models not called",
                "expectation": expectation,
                "expect_change": expect_change,
                "goal": state.get("plan_goal"),
                "latency_ms": {"a": 0.0, "b": 0.0, "executive": 0.0, "step": 0.0},
            }
        )
        return followed
    if backend is None:
        from monad2.llm import get_backend

        backend = get_backend()
    row = {
        "level": int(getattr(agent, "current_level", 0) or 0),
        "heuristic": _fmt(heuristic),
            "heuristic_reason": _clip(reason or "", 80),
            "solver": (entries.get("scene") or {}).get("solver"),
            "scene": _clip((entries.get("scene") or {}).get("shapes") or "", 280),
            "schema": entries.get("schema") or "",
            "stream": stream,
        "features": list(entries["features"]),
    }
    try:
        a_user = _for_model(stream) + "\nPropose your own move from the projection and the canvas."
        a_text, a_ms = _backend_complete(backend, "a", _A_SYSTEM, a_user)
        a_obj = _json_obj(a_text) or {}
        a_key = _parse_action(a_obj.get("action") or a_text, legal)
        b_user = (
            _for_model(stream)
            + f"\n[qwen_a] {_fmt(a_key)} effect={_clip(a_obj.get('effect') or '', 80)} "
            + f"reason={_clip(a_obj.get('reason') or a_text, 80)}"
        )
        b_text, b_ms = _backend_complete(backend, "b", _B_SYSTEM, b_user)
        b_obj = _json_obj(b_text) or {}
        b_key = _parse_action(b_obj.get("action") or b_text, legal)
        e_user = (
            _for_model(stream)
            + f"\n[qwen_a] {_fmt(a_key)} effect={_clip(a_obj.get('effect') or '', 100)} "
            + f"reason={_clip(a_obj.get('reason') or '', 120)}"
            + f"\n[qwen_b] {_fmt(b_key)} verdict={b_obj.get('verdict') or ''} "
            + f"effect={_clip(b_obj.get('effect') or '', 100)} "
            + f"reason={_clip(b_obj.get('reason') or '', 120)}"
        )
        e_text, e_ms = _backend_complete(backend, "executive", _E_SYSTEM, e_user)
        e_obj = _json_obj(e_text) or {}
    except Exception as exc:
        _bump(agent, "coord_errors")
        _bump(agent, "coord_steps")
        row.update(
            {
                "decision": "error",
                "action": _fmt(heuristic),
                "reason": f"model call failed: {exc}",
                "expectation": "",
                "expect_change": None,
            }
        )
        _log(agent).append(row)
        return heuristic or key

    _bump(agent, "qwen_proposals", int(a_key is not None) + int(b_key is not None))
    if a_key is not None and b_key is not None and a_key != b_key:
        _bump(agent, "qwen_differ")
    decision = str(e_obj.get("decision") or "").strip().lower()
    if decision not in ("accept", "combine", "inhibit", "explore"):
        decision = "explore" if not e_obj else "accept"
    reason_preview = str(e_obj.get("reason") or "")
    if "inhibit" in reason_preview.lower() and decision == "accept":
        decision = "inhibit"
    chosen = _parse_action(e_obj.get("action") or e_text, legal)
    if chosen is None:
        chosen = b_key or a_key or heuristic
        decision = "explore"
        e_obj = dict(e_obj)
        e_obj["reason"] = _clip(
            (e_obj.get("reason") or "") + " executive output had no legal action; exploring the auditor proposal",
            180,
        )
    rejected = []
    ok, why = _ladder_ok(agent, chosen, legal)
    if not ok:
        _bump(agent, "coord_ladder_vetoes")
        rejected.append(chosen)
        alt = _fallback(agent, legal, rejected, [b_key, a_key])
        ladder_note = f"D-ladder rejected {_fmt(chosen)} ({why})"
        if alt is None:
            chosen = heuristic or ("SIMPLE", legal[0])
            decision = "explore"
        else:
            chosen = alt
            decision = "inhibit" if chosen != heuristic else decision
        prev_reason = str(e_obj.get("reason") or "")
        e_obj["reason"] = _clip(f"{ladder_note}. {prev_reason}", 200)
    from monad2.primitives import contradicts_gradient, effect_of, known, suggest_action

    prim = str(e_obj.get("primitive") or b_obj.get("primitive") or a_obj.get("primitive") or "").strip().lower()
    if not known(prim):
        prim = ""
    if decision == "explore":
        prim = "explore"
    if prim and prim != "explore" and contradicts_gradient(prim, chosen, _state(agent)):
        alt = suggest_action("hold_gradient", legal, _state(agent))
        if alt is not None and alt != chosen:
            chosen = alt
            decision = "inhibit"
            prim = "hold_gradient"
            e_obj = dict(e_obj)
            e_obj["reason"] = _clip(
                "inhibit the step that undoes progress. " + str(e_obj.get("reason") or ""),
                180,
            )
    expect_change = e_obj.get("expect_change")
    if not isinstance(expect_change, bool):
        expect_change = not _known_noop(agent, chosen)
    expectation = _clip(str(e_obj.get("expectation") or e_obj.get("effect") or ""), 160)
    if not expectation:
        expectation = effect_of(prim) or ("frame changes" if expect_change else "frame stays")
    if prim == "explore" and "explor" not in expectation.lower():
        expectation = effect_of("explore")
    theory = _clip(str(e_obj.get("theory") or ""), 180)
    goal = str(e_obj.get("goal") or "").upper()
    if goal not in GOAL_TYPES:
        goal = next((name for name in GOAL_TYPES if name in theory.upper()), None)
    reason_text = _clip(str(e_obj.get("reason") or e_text), 200)
    state = _state(agent)
    mismatch = state.get("mismatch")
    prev_theory = state["theory"].get("text") or ""
    prev_action = (mismatch or {}).get("action")
    if mismatch and (theory != prev_theory or (prev_action is not None and chosen != prev_action)):
        _bump(agent, "surprise_revisions")
        state["mismatch"] = None
    if theory or goal:
        state["theory"] = {"goal": goal, "text": theory or prev_theory}
    _remember_plan(state, e_obj.get("plan"), chosen, legal)
    state["plan_expect"] = expectation
    state["plan_expect_change"] = bool(expect_change)
    state["plan_goal"] = goal
    state["plan_primitive"] = prim
    if decision == "inhibit":
        _bump(agent, "coord_inhibit")
        if chosen != heuristic:
            _bump(agent, "coord_inhibit_changed")
    elif decision == "combine":
        _bump(agent, "coord_combine")
    elif decision == "explore":
        _bump(agent, "coord_explore")
    else:
        _bump(agent, "coord_accept")
    if chosen != heuristic and chosen in (a_key, b_key) and chosen is not None:
        _bump(agent, "qwen_influenced")
    used = e_obj.get("used") if isinstance(e_obj.get("used"), list) else []
    _influence(agent, used, chosen, entries, {"a": a_key, "b": b_key}, reason_text)
    _bump(agent, "coord_steps")
    state["pending"] = {
        "action": chosen,
        "expect_change": bool(expect_change),
        "expectation": expectation,
        "goal": goal,
        "features": entries["features"],
        "theory": theory,
        "shapes": list((entries.get("scene") or {}).get("records") or []),
        "primitive": prim,
    }
    row.update(
        {
            "decision": decision,
            "action": _fmt(chosen),
            "action_key": list(chosen) if chosen else None,
            "reason": reason_text,
            "expectation": expectation,
            "expect_change": bool(expect_change),
            "goal": goal,
            "theory": theory,
            "primitive": prim,
            "binding": _clip(str(e_obj.get("binding") or ""), 80),
            "qwen_a": _fmt(a_key),
            "qwen_a_reason": _clip(str(a_obj.get("reason") or ""), 160),
            "qwen_a_effect": _clip(str(a_obj.get("effect") or ""), 120),
            "qwen_b": _fmt(b_key),
            "qwen_b_reason": _clip(str(b_obj.get("reason") or ""), 160),
            "qwen_b_effect": _clip(str(b_obj.get("effect") or ""), 120),
            "qwen_b_verdict": str(b_obj.get("verdict") or ""),
            "used": [str(x) for x in used],
            "latency_ms": {
                "a": round(a_ms, 1),
                "b": round(b_ms, 1),
                "executive": round(e_ms, 1),
                "step": round(a_ms + b_ms + e_ms, 1),
            },
            "stream": e_user,
        }
    )
    _log(agent).append(row)
    return chosen


def observe(agent, changed: bool) -> None:
    """Compare the executive expectation with the frame that just arrived."""
    state = _state(agent)
    pending = state.get("pending")
    if not pending:
        return
    state["pending"] = None
    observed = "changed" if changed else "unchanged"
    hit = bool(pending.get("expect_change")) == bool(changed)
    _bump(agent, "expect_scored")
    if hit:
        _bump(agent, "expect_hits")
    doc_text = ""
    doc_hit = None
    before = pending.get("shapes")
    log = _log(agent)
    if before is not None:
        from monad2.canvas_stream import document_result

        doc_text, doc_hit, doc_diff = document_result(
            agent, list(before), str(pending.get("expectation") or "")
        )
        state["last_diff"] = doc_diff
        try:
            from monad2.schema import account

            revision = account(agent, doc_hit, doc_diff, list(before))
        except Exception:
            revision = ""
        if revision:
            _bump(agent, "schema_revisions")
            if log:
                log[-1]["schema_revision"] = revision
        prim_name = str(pending.get("primitive") or "")
        if prim_name:
            from monad2.primitives import credit

            conf, note = credit(state, prim_name, doc_hit if doc_hit is not None else hit, pending.get("action"))
            if log:
                log[-1]["primitive_confidence"] = conf
                log[-1]["primitive_check"] = note
        if doc_hit is not None:
            _bump(agent, "expect_doc_scored")
            if doc_hit:
                _bump(agent, "expect_doc_hits")
    if log:
        log[-1]["result"] = observed
        log[-1]["expectation_hit"] = hit
        log[-1]["doc_diff"] = doc_text
        log[-1]["doc_hit"] = doc_hit
    goal = pending.get("goal")
    features = tuple(pending.get("features") or ())
    if not hit or doc_hit is False:
        state["mismatch"] = {
            "expectation": pending.get("expectation"),
            "expect_change": pending.get("expect_change"),
            "observed": observed,
            "action": pending.get("action"),
            "doc": doc_text,
        }
        if not hit or doc_hit is False:
            return
    if goal not in GOAL_TYPES or not features:
        return
    ltp = getattr(agent, "m2_ltp", None)
    if not isinstance(ltp, EpisodeLTP):
        ltp = EpisodeLTP()
        agent.m2_ltp = ltp
    if not ltp.confirm(goal):
        return
    holdout = os.getenv("MONAD2_HOLDOUT_GAME", "")
    before = None
    from monad2.discovery import EPISODE_FMF

    before = len(EPISODE_FMF)
    remember(features, goal, holdout=holdout)
    if len(EPISODE_FMF) > before:
        note = pending.get("theory") or pending.get("expectation") or goal
        CARRIED.append({"features": list(features), "goal": goal, "note": note})
        _bump(agent, "carried_theories")


def format_sample(rows: list[dict], limit: int = 6) -> str:
    """Readable excerpt of one level's thought stream."""
    if not rows:
        return "(no thought stream)"
    chunks = []
    for row in rows[:limit]:
        latency = row.get("latency_ms") or {}
        step_ms = latency.get("step")
        result = row.get("result")
        hit = row.get("expectation_hit")
        result_bit = ""
        if result is not None:
            result_bit = f" Result: frame {result} ({'match' if hit else 'mismatch'})."
        doc_bit = ""
        if row.get("doc_diff"):
            mark = row.get("doc_hit")
            doc_bit = f" Document: {row.get('doc_diff')} ({'match' if mark else 'mismatch' if mark is False else 'unparsed'})."
        chunks.append(
            "\n".join(
                [
                    f"Scene: {row.get('scene') or 'no canvas document'}.",
                    f"Solver proposal {row.get('solver') or row.get('heuristic')} ({row.get('heuristic_reason') or 'unspecified'}).",
                    f"Schema: {row.get('schema') or 'none'}.",
                    f"Primitive: {row.get('primitive') or 'none'} binds {row.get('binding') or 'none'}.",
                    f"Qwen A' proposed {row.get('qwen_a')}: {row.get('qwen_a_reason') or ''} "
                    f"Effect: {row.get('qwen_a_effect') or ''}.",
                    f"Qwen B' {row.get('qwen_b_verdict') or 'replied'} {row.get('qwen_b')}: "
                    f"{row.get('qwen_b_reason') or ''}",
                    f"Executive {row.get('decision')} -> {row.get('action')}. "
                    f"Reason: {row.get('reason')}",
                    f"Expectation: {row.get('expectation')}.{result_bit}{doc_bit}",
                    f"Latency: A' {latency.get('a')} ms, B' {latency.get('b')} ms, "
                    f"executive {latency.get('executive')} ms, step {step_ms} ms.",
                ]
            )
        )
    return "\n\n".join(chunks)


def influence_counts(stats: dict) -> dict[str, int]:
    keys = (
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
    )
    return {key: int(stats.get(key, 0) or 0) for key in keys}
