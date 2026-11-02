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

from monad2.discovery import recall, recall_unhashed, remember, reset_store
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
    retrieve_unhashed,
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
    "You are Mistral, the executive. Accept, combine, or inhibit one primitive from "
    "[primitives]. predicate is translate, no_reverse, contact, match, changed, or unchanged. "
    "Fill role, role_b, dir, and axis. expectation is a comment. "
    "action is an index or a role reference from [menu]. "
    "A non-primitive move is explore. A MISMATCH revises the theory. "
    'JSON: {"decision":"inhibit","action":"SIMPLE 3","primitive":"hold_gradient",'
    '"binding":"avatar,goal","predicate":"no_reverse","role":"avatar","role_b":"goal",'
    '"dir":"left","axis":"x","plan":[],"expect_change":true,"expectation":"comment",'
    '"reason":"why","theory":"why","goal":"REACH","used":["schema"]}.'
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


_JSON_STRING_KEYS = (
    "decision",
    "action",
    "primitive",
    "binding",
    "expectation",
    "effect",
    "reason",
    "predicate",
    "role",
    "role_b",
    "dir",
    "axis",
    "theory",
    "verdict",
    "goal",
)


def _json_obj(text: str) -> dict | None:
    """Parse a model object. A token cap can cut the closing brace; keep the fields already written."""
    if not text:
        return None
    start = text.find("{")
    if start < 0:
        return None
    blob = text[start:]
    end = blob.rfind("}")
    if end > 0:
        try:
            obj = json.loads(blob[: end + 1])
        except json.JSONDecodeError:
            obj = None
        if isinstance(obj, dict):
            return obj
    found: dict = {}
    for key in _JSON_STRING_KEYS:
        match = re.search(rf'"{key}"\s*:\s*"([^"\\]*)"', blob)
        if match:
            found[key] = match.group(1)
            continue
        partial = re.search(rf'"{key}"\s*:\s*"([^"\\]{{0,80}})', blob)
        if partial and partial.group(1):
            found[key] = partial.group(1)
    flag = re.search(r'"expect_change"\s*:\s*(true|false)', blob)
    if flag:
        found["expect_change"] = flag.group(1) == "true"
    for key in ("plan", "used"):
        match = re.search(rf'"{key}"\s*:\s*(\[[^\]]*\])', blob)
        if not match:
            continue
        try:
            value = json.loads(match.group(1))
        except json.JSONDecodeError:
            continue
        if isinstance(value, list):
            found[key] = value
    return found or None


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


def _unhash_fmf_for_planning(features: tuple[str, ...], holdout: str, agent=None) -> dict:
    """Unhash FMF corpus records, episode FMF memory, carried theories, and the 64-bit Fuzzy Merkle Forest
    into actionable planning primitives, role bindings, endorsed/refuted goals, and candidate priority."""
    try:
        records = eligible(load_records(corpus_path()), holdout)
    except (OSError, ValueError):
        records = []
    query = tuple(sorted(set(features) or {"aff:unknown"}))
    corpus_unhashed = retrieve_unhashed(query, records, k=5)
    ep_unhashed = recall_unhashed(query, k=3)
    goals: list[str] = []
    primitives: list[str] = []
    role_bindings: list[str] = list(corpus_unhashed.get("role_bindings") or [])
    endorsed_goals: list[str] = []
    refuted_goals: list[str] = []
    candidate_priority = str(corpus_unhashed.get("candidate_priority") or "REACH")
    candidate_bias = "canonical"
    merkle_operator = ""
    merkle_prim_id = ""
    for g in list(ep_unhashed.get("goals") or []):
        if g in GOAL_TYPES and g not in goals:
            goals.append(g)
            endorsed_goals.append(g)
    for p in list(ep_unhashed.get("primitives") or []):
        if p and p not in primitives:
            primitives.append(str(p))
    query_set = set(query)
    carried_notes: list[str] = []
    for row in CARRIED:
        if set(row.get("features") or ()) & query_set:
            cg = str(row.get("goal") or "")
            if cg in GOAL_TYPES and cg not in goals:
                goals.append(cg)
                endorsed_goals.append(cg)
            for cp in row.get("primitives") or ():
                if cp and str(cp) not in primitives:
                    primitives.append(str(cp))
            carried_notes.append(f"{cg} ({_clip(row.get('note') or '', 80)})")
    merkle_pkt = getattr(agent, "last_unhashed_merkle_packet", None) if agent is not None else None
    if not isinstance(merkle_pkt, dict) and agent is not None:
        mtree = getattr(agent, "associative_merkle_tree", None)
        if mtree is not None and hasattr(mtree, "unhash_packed_node"):
            try:
                dgraph = getattr(mtree, "dynamic_merkle_graph", None)
                if dgraph is not None and int(getattr(dgraph, "active_count", 0)) > 0:
                    last_u64 = int(dgraph.nodes_u64[int(dgraph.active_count) - 1])
                    merkle_pkt = mtree.unhash_packed_node(last_u64)
            except Exception:
                merkle_pkt = None
    if isinstance(merkle_pkt, dict):
        merkle_operator = str(merkle_pkt.get("top_down_operator") or "")
        merkle_prim_id = str(merkle_pkt.get("parent_primitive_id") or "")
        candidate_bias = str(merkle_pkt.get("candidate_bias") or "canonical")
        for eg in merkle_pkt.get("endorsed_goals") or ():
            if eg in GOAL_TYPES:
                if eg not in endorsed_goals:
                    endorsed_goals.append(eg)
                if eg not in goals:
                    goals.append(eg)
        for rg in merkle_pkt.get("refuted_goals") or ():
            if rg in GOAL_TYPES and rg not in refuted_goals:
                refuted_goals.append(rg)
        for mp in merkle_pkt.get("recommended_primitives") or ():
            if mp and str(mp) not in primitives:
                primitives.append(str(mp))
        if candidate_bias == "switch_first":
            candidate_priority = "SWITCH_FIRST"
    for g in list(corpus_unhashed.get("goals") or []):
        if g in GOAL_TYPES and g not in goals and g not in refuted_goals:
            goals.append(g)
    for p in list(corpus_unhashed.get("primitives") or []):
        if p and str(p) not in primitives:
            primitives.append(str(p))
    parts: list[str] = []
    schemas = list(corpus_unhashed.get("schemas") or [])
    if goals or schemas:
        lead_g = goals[0] if goals else "SCHEMA"
        quote = _clip(schemas[0], 70) if schemas else ""
        parts.append(f"corpus {lead_g}" + (f': "{quote}"' if quote else ""))
    if primitives:
        parts.append("unhashed_prims=" + ",".join(primitives[:3]))
    if role_bindings:
        parts.append("bindings=" + ";".join(role_bindings[:2]))
    if merkle_prim_id:
        parts.append(f"merkle={merkle_prim_id}->{merkle_operator or 'OBSERVE'}")
    if ep_unhashed.get("goals"):
        parts.append("episode " + ",".join(ep_unhashed["goals"]))
    if carried_notes:
        parts.append("carried " + "; ".join(carried_notes[:2]))
    if not parts:
        text = "no overlapping record for " + ",".join(query)
    else:
        text = _clip(" | ".join(parts), 320)
    return {
        "text": text,
        "goals": goals,
        "primitives": primitives,
        "role_bindings": role_bindings,
        "candidate_priority": candidate_priority,
        "candidate_bias": candidate_bias,
        "endorsed_goals": endorsed_goals,
        "refuted_goals": refuted_goals,
        "merkle_operator": merkle_operator,
        "merkle_primitive_id": merkle_prim_id,
    }


def _fmf_lines(features: tuple[str, ...], holdout: str, agent=None) -> tuple[str, list[str]]:
    unhashed = _unhash_fmf_for_planning(features, holdout, agent=agent)
    if agent is not None:
        state = _state(agent)
        state["fmf_unhashed"] = unhashed
    return unhashed["text"], list(unhashed["goals"])


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
    aid = metrics.get("audited_first_canonical_aid")
    if aid is None:
        raw_aid = metrics.get("audited_first_raw_aid")
        if raw_aid is not None:
            raw_to_can = getattr(agent, "raw_to_canonical_dpad", None)
            if isinstance(raw_to_can, dict):
                aid = raw_to_can.get(int(raw_aid), int(raw_aid))
            else:
                aid = raw_aid
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


def _field_state(agent, legal: list[int]) -> dict:
    """Extract top-down observer gauge field, GOHST oscillator, tonic depth, and control map state."""
    out = {
        "ricci": 0.0,
        "lorentz": (0.0, 0.0),
        "dark_w": 0.0,
        "omega_hz": 0.0,
        "sw_energy": 0.0,
        "sw_regime": "DORMANT",
        "coupling_mode": "UNCOUPLED",
        "coupling_r": 0.0,
        "tonic_depth": 0,
        "tonic_preset": "",
        "verdict": "",
        "top_down_cmd": "",
        "control_inverted": False,
        "canvas_key": None,
    }
    obs_eng = getattr(agent, "observer_field_engine", None)
    f_state = getattr(obs_eng, "last_field_state", None) if obs_eng is not None else None
    if f_state is not None:
        try:
            out["ricci"] = float(getattr(f_state, "ricci_curvature_r", 0.0) or 0.0)
            lv = getattr(f_state, "lorentz_force_vec", (0.0, 0.0)) or (0.0, 0.0)
            out["lorentz"] = (float(lv[0]), float(lv[1]))
            out["dark_w"] = float(getattr(f_state, "dark_matter_potential_w", 0.0) or 0.0)
            out["omega_hz"] = float(getattr(f_state, "top_down_omega_hz", 0.0) or 0.0)
            out["sw_energy"] = float(getattr(f_state, "standing_wave_energy", 0.0) or 0.0)
            out["sw_regime"] = str(getattr(f_state, "standing_wave_regime", "DORMANT") or "DORMANT")
        except (TypeError, ValueError, IndexError):
            pass
    narrative = getattr(agent, "self_narrative", None)
    if isinstance(narrative, dict):
        if narrative.get("gohst_coupling_mode"):
            out["coupling_mode"] = str(narrative["gohst_coupling_mode"])
        if narrative.get("gohst_coupling_r") is not None:
            try:
                out["coupling_r"] = float(narrative["gohst_coupling_r"])
            except (TypeError, ValueError):
                pass
        if narrative.get("inos_depth_budget") is not None:
            try:
                out["tonic_depth"] = int(narrative["inos_depth_budget"])
            except (TypeError, ValueError):
                pass
    inos_eng = getattr(agent, "inos_meta_engine", None)
    t_rep = getattr(inos_eng, "last_tonic_report", None) if inos_eng is not None else None
    if isinstance(t_rep, dict):
        if t_rep.get("optimal_depth_budget") is not None:
            try:
                out["tonic_depth"] = int(t_rep["optimal_depth_budget"])
            except (TypeError, ValueError):
                pass
        if t_rep.get("safety_preset"):
            out["tonic_preset"] = str(t_rep["safety_preset"])
    ab_pkt = getattr(agent, "last_ab_packet", None)
    if ab_pkt is not None:
        out["verdict"] = str(getattr(ab_pkt, "model_b_verdict", "") or "")
        out["top_down_cmd"] = str(getattr(ab_pkt, "recommended_top_down_action", "") or "")
    c_map = getattr(agent, "canonical_to_raw_dpad", None)
    if isinstance(c_map, dict) and any(int(k) != int(v) for k, v in c_map.items() if int(k) in (1, 2, 3, 4)):
        out["control_inverted"] = True
    _ctext, c_key = _canvas_line(agent, legal)
    out["canvas_key"] = c_key
    return out


def _field_line(field: dict) -> str:
    if not isinstance(field, dict):
        return "no field"
    ricci = float(field.get("ricci") or 0.0)
    lx, ly = field.get("lorentz") or (0.0, 0.0)
    regime = str(field.get("sw_regime") or "DORMANT")
    mode = str(field.get("coupling_mode") or "UNCOUPLED")
    verdict = str(field.get("verdict") or "")
    cmd = str(field.get("top_down_cmd") or "")
    inv = "inverted" if field.get("control_inverted") else "canonical"
    depth = int(field.get("tonic_depth") or 0)
    bits = [
        f"ricci={ricci:+.2f}",
        f"lorentz=({lx:+.2f},{ly:+.2f})",
        f"wave={regime}",
        f"gohst={mode}",
        f"dpad={inv}",
    ]
    if depth > 0:
        bits.append(f"depth={depth}")
    if verdict:
        bits.append(f"verdict={verdict}")
    if cmd and cmd != "NONE":
        bits.append(f"cmd={cmd}")
    return " ".join(bits)


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
    pred = mismatch.get("predicate") or mismatch.get("expectation") or ""
    return (
        f"MISMATCH predicate {pred} failed; frame was {mismatch.get('observed')}"
        + (f" document {doc}" if doc else "")
    )


def _watch_leader(agent, fmf_goals=None) -> str:
    ep = getattr(agent, "m2_watch", None)
    frozen = getattr(ep, "frozen", None) if ep is not None else None
    if frozen is None and ep is not None and getattr(ep, "scores", None):
        from monad2.discovery import leader

        frozen, _margin = leader(ep.scores)
    if frozen in GOAL_TYPES:
        return str(frozen)
    for goal in fmf_goals or []:
        if goal in GOAL_TYPES:
            return str(goal)
    return "REACH"


def _sync_candidates(agent, state: dict, legal: list[int], leader_goal: str) -> None:
    from monad2.candidates import enumerate_candidates

    field = _field_state(agent, legal)
    state["top_down_field"] = field
    if int(field.get("tonic_depth") or 0) > 0:
        state["tonic_depth"] = int(field["tonic_depth"])
    evidence = state.get("role_evidence") or {}
    if evidence.get("goal"):
        state["candidates"] = []
        state["hypothesis_target"] = None
        state["hypothesis_box"] = None
        return
    records = state.get("frame_records") or []
    cands = enumerate_candidates(
        records,
        evidence,
        leader_goal,
        legal,
        affordances=state.get("affordances"),
        refuted=state.get("refuted_candidates"),
        deferred=state.get("deferred_candidates"),
        state=state,
    )
    mbox = state.get("mover_box")
    fmf_u = state.get("fmf_unhashed") if isinstance(state.get("fmf_unhashed"), dict) else {}
    endorsed_g = set(fmf_u.get("endorsed_goals") or ())
    refuted_g = set(fmf_u.get("refuted_goals") or ())
    has_mov = bool(evidence.get("movable") or state.get("movable_box"))
    preferred_kind = cands[0].get("kind") if cands else "REACH"
    if has_mov and "PLACE" in endorsed_g and "PLACE" not in refuted_g:
        preferred_kind = "PLACE"
    elif "REACH" in endorsed_g and "PLACE" in refuted_g:
        preferred_kind = "REACH"
    sw_geom = tuple(int(x) for x in evidence["switch"]) if isinstance(evidence.get("switch"), (list, tuple)) and len(evidence["switch"]) == 3 else None
    prefer_switch = bool(
        fmf_u.get("candidate_priority") == "SWITCH_FIRST"
        or fmf_u.get("candidate_bias") in ("switch_first", "prefer_conditional")
        or str(field.get("coupling_mode") or "").startswith("COUPLED")
    )
    if len(cands) > 1 and (
        isinstance(mbox, (list, tuple)) and len(mbox) == 4
        or preferred_kind != cands[0].get("kind")
        or prefer_switch
    ):
        lx, ly = field.get("lorentz") or (0.0, 0.0)
        ricci = float(field.get("ricci") or 0.0)
        cmode = str(field.get("coupling_mode") or "")
        vx, vy = 0.0, 0.0
        if ricci < -0.05 or cmode == "DECOUPLED_ORTHOGONAL_EXPLORATION":
            vx += float(lx)
            vy += float(ly)
        ckey = field.get("canvas_key")
        if isinstance(ckey, (list, tuple)) and len(ckey) == 2 and ckey[0] == "SIMPLE":
            d_vec = {1: (0.0, -1.0), 2: (0.0, 1.0), 3: (-1.0, 0.0), 4: (1.0, 0.0)}.get(int(ckey[1]))
            if d_vec is not None and (ricci < -0.05 or cmode == "DECOUPLED_ORTHOGONAL_EXPLORATION"):
                vx += 0.5 * d_vec[0]
                vy += 0.5 * d_vec[1]
        use_vec = isinstance(mbox, (list, tuple)) and len(mbox) == 4 and (abs(vx) > 0.15 or abs(vy) > 0.15)
        if use_vec or preferred_kind != cands[0].get("kind") or prefer_switch:
            mx = (float(mbox[0]) + float(mbox[2]) / 2.0) if isinstance(mbox, (list, tuple)) and len(mbox) == 4 else 0.0
            my = (float(mbox[1]) + float(mbox[3]) / 2.0) if isinstance(mbox, (list, tuple)) and len(mbox) == 4 else 0.0

            def _field_tiebreak(idx_item):
                idx, item = idx_item
                c_geom = tuple(int(x) for x in (item.get("geom") or item.get("key") or ()))
                sw_rank = 0 if (prefer_switch and (item.get("role") == "switch" or (sw_geom and c_geom == sw_geom))) else 1
                conf_rank = 0 if item.get("confirmed_goal") else 1
                kind_rank = 0 if item.get("kind") == preferred_kind else 1
                bx = item.get("box")
                if use_vec and isinstance(bx, (list, tuple)) and len(bx) == 4:
                    tx = float(bx[0]) + float(bx[2]) / 2.0
                    ty = float(bx[1]) + float(bx[3]) / 2.0
                    dx = tx - mx
                    dy = ty - my
                    dist = max(1.0, (dx * dx + dy * dy) ** 0.5)
                    align = (dx * vx + dy * vy) / dist
                    return (sw_rank, conf_rank, kind_rank, -round(align, 1), idx)
                return (sw_rank, conf_rank, kind_rank, 0.0, idx)

            cands = [item for _idx, item in sorted(enumerate(cands), key=_field_tiebreak)]
    state["candidates"] = cands
    refuted_set = {
        (int(g[0]), int(g[1]), int(g[2]))
        for g in (state.get("refuted_candidates") or [])
        if isinstance(g, (list, tuple)) and len(g) == 3
    }
    deferred_set = {
        (int(g[0]), int(g[1]), int(g[2]))
        for g in (state.get("deferred_candidates") or [])
        if isinstance(g, (list, tuple)) and len(g) == 3
    }
    av_raw = evidence.get("avatar") or state.get("mover_geom")
    av_tuple = (
        (int(av_raw[0]), int(av_raw[1]), int(av_raw[2]))
        if isinstance(av_raw, (list, tuple)) and len(av_raw) == 3
        else None
    )
    part_tuples = {
        (int(p[0]), int(p[1]), int(p[2]))
        for p in (evidence.get("avatar_parts") or [])
        if isinstance(p, (list, tuple)) and len(p) == 3
    }
    hyp = state.get("hypothesis_target")
    if isinstance(hyp, (list, tuple)) and len(hyp) == 3:
        ht = (int(hyp[0]), int(hyp[1]), int(hyp[2]))
        if ht in refuted_set or ht in deferred_set or ht == av_tuple or ht in part_tuples:
            hyp = None
        else:
            for item in cands:
                g = item.get("geom")
                if g and (int(g[0]), int(g[1]), int(g[2])) == ht and item.get("box"):
                    state["hypothesis_box"] = tuple(item["box"])
                    break
            else:
                from monad2.primitives import _inside_box

                hbox = state.get("hypothesis_box")
                pbox = state.get("playfield_box")
                box_alive = False
                if isinstance(hbox, (list, tuple)) and len(hbox) == 4:
                    hb = (int(hbox[0]), int(hbox[1]), int(hbox[2]), int(hbox[3]))
                    if not (isinstance(pbox, (list, tuple)) and len(pbox) == 4) or _inside_box(hb, pbox):
                        for rec in records:
                            xy = rec.get("xy")
                            wh = rec.get("wh")
                            if xy and wh and len(xy) == 2 and len(wh) == 2:
                                if (int(xy[0]), int(xy[1]), int(wh[0]), int(wh[1])) == hb:
                                    box_alive = True
                                    break
                if not box_alive:
                    hyp = None
    else:
        hyp = None
    if hyp is None:
        if cands and cands[0].get("geom"):
            g = cands[0]["geom"]
            state["hypothesis_target"] = [int(g[0]), int(g[1]), int(g[2])]
            state["hypothesis_box"] = tuple(cands[0]["box"]) if cands[0].get("box") else None
        else:
            state["hypothesis_target"] = None
            state["hypothesis_box"] = None
    if state.get("hypothesis_target") and isinstance(state.get("role_evidence"), dict):
        state["role_evidence"]["candidate_geom"] = list(state["hypothesis_target"])


def _hypothesis_line(agent, fmf_goals, state: dict) -> str:
    """Watch and memory candidates. They stay labeled until a completion confirms a goal."""
    bits = []
    ep = getattr(agent, "m2_watch", None)
    frozen = getattr(ep, "frozen", None) if ep is not None else None
    if frozen is None and ep is not None and getattr(ep, "scores", None):
        from monad2.discovery import leader

        frozen, _margin = leader(ep.scores)
    if frozen in GOAL_TYPES:
        status = "confirmed" if (state.get("role_evidence") or {}).get("goal") else "unconfirmed"
        bits.append(f"watch {frozen} {status}")
    for goal in fmf_goals or []:
        if goal in GOAL_TYPES and f"memory {goal} unconfirmed" not in bits:
            bits.append(f"memory {goal} unconfirmed")
    if (state.get("role_evidence") or {}).get("goal"):
        bits.append("goal role confirmed by completion")
    else:
        bits.append("goal role unbound")
        hyp = state.get("hypothesis_target")
        if isinstance(hyp, (list, tuple)) and len(hyp) == 3:
            bits.append(f"candidate geom {int(hyp[0])},{int(hyp[1])},{int(hyp[2])}")
    return "; ".join(bits)


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
    fmf_text, fmf_goals = _fmf_lines(features, holdout, agent=agent)
    effect_text, effect_key = _effect_line(agent)
    dead_text, dead_keys = _dead_line(agent, legal)
    canvas_text, canvas_key = _canvas_line(agent, legal)
    state = _state(agent)
    scene = scene_brief(agent, state.get("last_diff"))
    scene["solver"] = f"{solver_name(reason, agent)} proposes {_fmt(_norm(heuristic))}"
    state["frame_records"] = list(scene.get("records") or [])
    if os.getenv("MONAD2_PASS") == "2" or getattr(agent, "m2_pass_idx", 1) == 2 or bool(state.get("intra_game_promoted")):
        try:
            from monad2.synthesizer import apply_synthesized_priors_to_state, lookup_synthesized_solver

            slot_env = os.getenv("MONAD2_GAME_SLOT", "").strip()
            slot_val = int(slot_env) if slot_env.lstrip("-").isdigit() else getattr(agent, "m2_game_slot", None)
            synth_spec = lookup_synthesized_solver(agent, state["frame_records"], legal, slot=slot_val)
            if synth_spec is not None:
                apply_synthesized_priors_to_state(
                    agent,
                    state,
                    synth_spec,
                    int(getattr(agent, "current_level", 0) or 0),
                )
        except Exception:
            pass
    schema_line = "schema unread"
    try:
        from monad2.schema import hypothesis_line, remember_scene

        remember_scene(agent, scene, state.get("last_diff"))
        schema_line = hypothesis_line(agent, scene, state.get("last_diff"))
    except Exception:
        schema_line = "schema unread"
    leader_goal = _watch_leader(agent, fmf_goals)
    try:
        _sync_candidates(agent, state, legal, leader_goal)
    except Exception:
        pass
    field = state.get("top_down_field") or _field_state(agent, legal)
    state["top_down_field"] = field
    if int(field.get("tonic_depth") or 0) > 0:
        state["tonic_depth"] = int(field["tonic_depth"])
    field_text = _field_line(field)
    if scene.get("playfield"):
        scp = f"{scp} canvas:{scene['playfield']}"
    entries = {
        "scp": scp,
        "canvas": canvas_text,
        "canvas_key": canvas_key,
        "field": field_text,
        "top_down_field": field,
        "pll": _pll_line(state),
        "tonic": _tonic_line(agent),
        "fmf": fmf_text,
        "fmf_goals": fmf_goals,
        "fmf_unhashed": state.get("fmf_unhashed") or {},
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
        "candidates": state.get("candidates") or [],
        "leader": leader_goal,
    }
    from monad2.primitives import proposals_for

    prim_line, prim_items = proposals_for(state.get("schema_obs") or {}, state, legal)
    entries["primitives"] = prim_line
    entries["primitive_list"] = prim_items
    entries["roles"] = state.get("role_line") or "none"
    entries["hypothesis"] = _hypothesis_line(agent, fmf_goals, state)
    names = {1: "SIMPLE 1", 2: "SIMPLE 2", 3: "SIMPLE 3", 4: "SIMPLE 4", 5: "SIMPLE 5"}
    legal_bits = [names[aid] for aid in legal if aid in names]
    if 6 in legal:
        legal_bits.append("CLICK")
    entries["legal"] = ", ".join(legal_bits) or "none"
    from monad2.menu import build_menu, menu_line

    menu = build_menu(legal, state.get("affordances") or {})
    entries["menu_items"] = menu
    entries["menu"] = menu_line(menu)
    lines = [
        f"[scp] {_clip(entries['scp'], 220)}",
        f"[canvas_doc] {_clip(scene['shapes'], 280)}",
        f"[playfield] {scene['playfield']}",
        f"[avatar] {scene['avatar']}",
        f"[control] {_clip(scene['control'], 160)}",
        f"[field] {_clip(entries['field'], 200)}",
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
        f"[roles] {_clip(entries.get('roles') or 'none', 220)}",
        f"[hypothesis] {_clip(entries.get('hypothesis') or 'goal role unbound', 180)}",
        f"[legal] {entries.get('legal') or 'none'}",
        f"[menu] {entries.get('menu') or 'none'}",
        f"[primitives] {_clip(entries['primitives'], 320)}",
    ]
    return "\n".join(lines), entries


def _backend_complete(backend, role: str, system: str, user: str, **kwargs) -> tuple[str, float]:
    try:
        return backend.complete(role, system, user, **kwargs)
    except TypeError:
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
    if any(word in text for word in ("field", "ricci", "lorentz", "omega", "standing_wave", "gohst")):
        sources.add("field")
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
        "field": "infl_field",
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
    """Shorter prompt for prefill. The logged stream stays complete.

    Primitive, schema, top-down field, and unhashed FMF lines stay at the front
    so the 700-character clip cannot drop the motion rules, field guidance, or memory.
    """
    first = (
        "[roles]",
        "[hypothesis]",
        "[legal]",
        "[menu]",
        "[primitives]",
        "[fmf]",
        "[field]",
        "[control]",
        "[canvas]",
        "[tonic]",
        "[pll]",
        "[schema]",
        "[avatar]",
        "[diff]",
        "[solver]",
    )
    head = []
    rest = []
    for line in text.splitlines():
        if line.startswith("[canvas_doc]") or line.startswith("[playfield]") or line.startswith("[meta]"):
            clipped = line[:160]
        else:
            clipped = line[:220]
        if line.startswith(first):
            head.append(clipped)
        else:
            rest.append(clipped)
    # 700 characters keeps prompt + generation inside the 1024 context. Role and predicate lines are already first.
    return "\n".join(head + rest)[:700]


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


def _touch_level(state: dict, level: int) -> None:
    seen = state.get("llm_level")
    if seen is None:
        state["llm_level"] = level
        state.setdefault("llm_calls_level", 0)
        state.setdefault("plan_writes_level", 0)
        return
    if seen == level:
        return
    state["llm_level"] = level
    state["llm_calls_level"] = 0
    state["plan_writes_level"] = 0
    state["script"] = []
    state["plan"] = []
    state["mode"] = "discover"
    state["discover_steps"] = 0
    state["stable_roles"] = ""
    state["surprise_pending"] = None
    state["stall_steps"] = 0
    state["hypothesis_target"] = None
    state["hypothesis_box"] = None
    state["playfield_box"] = None
    state["candidates"] = []
    state["refuted_candidates"] = []
    state["deferred_candidates"] = []
    state["conditional_blocks"] = []
    state["had_conditional_blocks"] = False
    state["last_conditional"] = None
    state["route_blocks"] = []
    state["route_prefix"] = []
    state["blocked_here"] = []
    state["probed_dirs"] = []
    state["active_anchor"] = None
    state["tried_anchors"] = []
    state["synth_tried_clicks"] = []
    state["click_only_ready"] = False
    state["mover_box"] = None
    state["prev_mover_box"] = None
    state["mover_geom"] = None
    state["movable_box"] = None
    state["moving_boxes"] = []
    state["dpad_moved"] = False
    state["hud_changed"] = False
    state["coop_handoff"] = False
    state["bridge_plan"] = None
    state["bridge_plan_target"] = None
    state["unrefuted_passes"] = 0
    state["interventions_level"] = 0
    state["exec_seen_states"] = {}
    state["replan_context"] = {}
    ev = dict(state.get("role_evidence") or {})
    ev.pop("goal", None)
    ev.pop("candidate_geom", None)
    ev.pop("hazard", None)
    state["role_evidence"] = ev


def _new_role_surprise(state: dict, step: dict | None) -> None:
    if state.get("mode") != "execute" or state.get("surprise_pending"):
        return
    planned = [part.strip() for part in str(state.get("plan_roles") or "").split(",") if part.strip()]
    now = [part.strip() for part in str(state.get("role_line") or "").split(",") if part.strip()]
    if not planned:
        return
    is_press = (step or {}).get("kind") == "press" or (step or {}).get("primitive") in ("toggle", "cycle_select")
    watch = ("hazard",) if is_press else ("switch", "hazard")
    extra = [name for name in now if name not in planned and name in watch]
    if extra:
        state["surprise_pending"] = "new role " + extra[0]


def _can_coop_handoff(agent, state: dict) -> bool:
    is_pass2 = os.getenv("MONAD2_PASS") == "2" or getattr(agent, "m2_pass_idx", 1) == 2
    if is_pass2:
        return True
    lvl = int(getattr(agent, "current_level", 0) or state.get("llm_level") or 0)
    if lvl > 0:
        return True
    ep_llm_calls = int(_stats(agent).get("llm_calls", 0) or state.get("llm_calls") or 0)
    lvl_llm_calls = int(state.get("llm_calls_level") or 0)
    return ep_llm_calls >= 1 and lvl_llm_calls >= 1


def _call_model(agent, backend, role: str, system: str, user: str, **kwargs) -> tuple[str, float]:
    text, ms = _backend_complete(backend, role, system, user, **kwargs)
    _bump(agent, "llm_calls")
    state = _state(agent)
    state["llm_calls"] = int(_stats(agent).get("llm_calls", 0) or 0)
    state["llm_calls_level"] = int(state.get("llm_calls_level") or 0) + 1
    return text, ms


def _finish_fast(agent, mode: str, action, ref: str, step: dict, entries: dict, heuristic, reason: str, stream: str, executive_ms: float):
    """Log a plan, execute, or replan step. Execute does not call a model."""
    from monad2.planmode import plan_text, predicate_for

    state = _state(agent)
    obs = state.get("schema_obs") or {}
    pred = predicate_for(step, action, obs)
    if isinstance(pred, dict) and pred.get("geom") is None and pred.get("role") in ("avatar", "movable"):
        ev_now = state.get("role_evidence") or {}
        bound_g = ev_now.get(pred.get("role")) or state.get("mover_geom")
        if bound_g and len(bound_g) == 3:
            pred = dict(pred)
            pred["geom"] = [int(bound_g[0]), int(bound_g[1]), int(bound_g[2])]
    from monad2.predicates import render

    expectation = render(pred)
    state["last_ref"] = ref
    state["plan_predicate"] = pred
    state["plan_primitive"] = step.get("primitive") or ""
    if mode == "execute":
        _bump(agent, "execute_steps")
    _bump(agent, "coord_steps")
    _bump(agent, "coord_plan_steps")
    goal = (state.get("theory") or {}).get("goal")
    state["pending"] = {
        "action": action,
        "expect_change": True,
        "expectation": expectation,
        "goal": goal,
        "features": entries.get("features"),
        "theory": (state.get("theory") or {}).get("text") or "",
        "shapes": list((entries.get("scene") or {}).get("records") or []),
        "primitive": step.get("primitive") or "",
        "predicate": pred,
        "comment": "",
    }
    script = plan_text(state.get("script") or [])
    if mode == "execute":
        why = "executing the level plan; models not called"
    elif mode == "replan":
        why = "replan after " + str(state.get("last_surprise") or "a surprise")
    else:
        why = "wrote a level plan"
    _log(agent).append(
        {
            "level": int(getattr(agent, "current_level", 0) or 0),
            "heuristic": _fmt(heuristic),
            "heuristic_reason": _clip(reason or "", 80),
            "solver": (entries.get("scene") or {}).get("solver"),
            "scene": _clip((entries.get("scene") or {}).get("shapes") or "", 280),
            "schema": entries.get("schema") or "",
            "primitives": entries.get("primitives") or "",
            "primitive": step.get("primitive") or "",
            "stream": stream,
            "decision": mode,
            "mode": mode,
            "action": _fmt(action),
            "action_key": list(action) if action else None,
            "reason": _clip(f"{why}. {script}", 200),
            "expectation": expectation,
            "expect_change": True,
            "predicate": expectation,
            "comment": "",
            "roles": entries.get("roles") or "",
            "plan": script,
            "binding": step.get("binding") or "",
            "llm_calls_level": int(state.get("llm_calls_level") or 0),
            "latency_ms": {
                "a": 0.0,
                "b": 0.0,
                "executive": round(float(executive_ms), 1),
                "step": round(float(executive_ms), 1),
            },
        }
    )
    return action


def _expand_valid(agent, step: dict, legal: list[int], state: dict, menu: list[dict]):
    """Expand a plan step, skipping directions or click anchors known to be no-ops at the current state."""
    from monad2.planmode import expand_action

    action, ref = expand_action(step, legal, state, menu)
    aff = state.get("affordances") or {}
    max_tries = max(4, len(aff.get("clickable") or []), len(aff.get("switch") or [])) + 2
    tries = 0
    while action is not None and not _ladder_ok(agent, action, legal)[0] and tries < max_tries:
        tries += 1
        if action[0] == "SIMPLE" and int(action[1]) in (1, 2, 3, 4):
            bh = state.setdefault("blocked_here", [])
            if int(action[1]) not in bh:
                bh.append(int(action[1]))
        elif action[0] == "CLICK" and (step.get("primitive") or "") in ("toggle", "cycle_select"):
            pt = [int(action[1]), int(action[2])]
            tried_anc = step.setdefault("tried_anchors", [])
            if pt not in tried_anc:
                tried_anc.append(pt)
            state["tried_anchors"] = list(tried_anc)
            step["active_anchor"] = None
            state["active_anchor"] = None
            step["fails"] = 0
            step["walked"] = 0
            step["anchor_i"] = int(step.get("anchor_i") or 0) + 1
        else:
            break
        action, ref = expand_action(step, legal, state, menu)
    return action, ref


def _try_synthesized_step(agent, state: dict, legal: list[int], entries: dict, heuristic, stream: str):
    """Execute one step of the Pass-2 / intra-game promoted synthesized solver if applicable."""
    is_pass2 = os.getenv("MONAD2_PASS") == "2" or getattr(agent, "m2_pass_idx", 1) == 2
    cur_lvl_idx = int(getattr(agent, "current_level", 0) or 0)
    if int(state.get("interventions_level") or 0) > 2 or not (
        is_pass2
        or (cur_lvl_idx > 0 and bool(state.get("intra_game_promoted")) and not state.get("coop_handoff"))
    ):
        return None
    obs_roles = {slot.get("role") for slot in (state.get("schema_obs") or {}).get("roles") or [] if slot.get("role")}
    has_mover = ("avatar" in obs_roles) or bool(state.get("mover_box"))
    try:
        from monad2.synthesizer import lookup_synthesized_solver, plan_with_synthesized_solver

        slot_env = os.getenv("MONAD2_GAME_SLOT", "").strip()
        slot_val = int(slot_env) if slot_env.lstrip("-").isdigit() else getattr(agent, "m2_game_slot", None)
        synth_spec = lookup_synthesized_solver(agent, state.get("frame_records") or [], legal, slot=slot_val)
        lv_now = synth_spec.levels.get(cur_lvl_idx) if synth_spec is not None else None
        if synth_spec is not None and (
            has_mover
            or synth_spec.has_panel_pair
            or bool(synth_spec.responsive_geoms)
            or bool(lv_now and lv_now.causal_policy)
        ):
            synth_plan = plan_with_synthesized_solver(
                synth_spec,
                state,
                legal,
                grid=getattr(agent, "_m2_grid", None),
            )
            if synth_plan:
                s_act = _norm(synth_plan[0])
                if s_act is not None and _ladder_ok(agent, s_act, legal)[0]:
                    s_prim = (
                        "align"
                        if synth_spec.solver_family == "PANEL_ALIGN"
                        else (
                            "convey"
                            if synth_spec.solver_family == "SOKOBAN_PUSH"
                            else ("toggle" if s_act[0] == "CLICK" else "approach")
                        )
                    )
                    s_role = "clickable" if s_act[0] == "CLICK" else ("movable" if s_prim == "convey" else "avatar")
                    s_step = {
                        "primitive": s_prim,
                        "binding": s_role,
                        "kind": "changed" if s_act[0] == "CLICK" else "translate",
                        "role": s_role,
                        "role_b": "none",
                        "repeat": len(synth_plan),
                    }
                    if s_act[0] == "CLICK":
                        tried_c = state.setdefault("synth_tried_clicks", [])
                        if s_act not in tried_c:
                            tried_c.append(s_act)
                    state["plan"] = [a for a in synth_plan[1:8] if _norm(a) is not None]
                    return _finish_fast(
                        agent,
                        "execute",
                        s_act,
                        f"synth:{synth_spec.solver_family}",
                        s_step,
                        entries,
                        heuristic,
                        f"pass-2 synthesized solver ({synth_spec.solver_family})",
                        stream,
                        0.0,
                    )
    except Exception:
        pass
    return None


def try_execute_step(agent):
    """Short-circuit plan execution before GGL and BFS run on the host agent."""
    from monad2.planmode import current_step

    state = _state(agent)
    cur_lvl_idx = int(getattr(agent, "current_level", 0) or 0)
    _touch_level(state, cur_lvl_idx)
    if state.get("surprise_pending") or state.get("coop_handoff"):
        return None
    is_pass2 = os.getenv("MONAD2_PASS") == "2" or getattr(agent, "m2_pass_idx", 1) == 2
    if int(state.get("interventions_level") or 0) <= 2 and (
        is_pass2 or (cur_lvl_idx > 0 and bool(state.get("intra_game_promoted")))
    ):
        legal = _legal(agent)
        stream, entries = _stream(agent, None, "execute", legal)
        synth_res = _try_synthesized_step(agent, state, legal, entries, None, stream)
        if synth_res is not None:
            return synth_res
    if state.get("mode") != "execute":
        return None
    step = current_step(state)
    if step is None:
        return None
    legal = _legal(agent)
    stream, entries = _stream(agent, None, "execute", legal)
    _new_role_surprise(state, step)
    if state.get("surprise_pending"):
        return None
    action, ref = _expand_valid(agent, step, legal, state, entries.get("menu_items") or [])
    if action is None or not _ladder_ok(agent, action, legal)[0]:
        state["surprise_pending"] = "no progress"
        return None
    return _finish_fast(agent, "execute", action, ref, step, entries, None, "execute", stream, 0.0)


def _probe_step(agent, legal: list[int], entries: dict, heuristic, reason: str, stream: str):
    """Zero-LLM directional probe during initial discovery, or cooperative heuristic handoff after level plan budget."""
    from monad2.candidates import next_direction_probe
    from monad2.planmode import note_discovery
    from monad2.predicates import bind_predicate, render
    from monad2.primitives import suggest_action

    state = _state(agent)
    obs = state.get("schema_obs") or {}
    roles = {slot.get("role") for slot in obs.get("roles") or [] if slot.get("role")}
    has_mover = ("avatar" in roles) or bool(state.get("mover_box"))
    dpad_set = {int(aid) for aid in legal if int(aid) in (1, 2, 3, 4)}
    probed_set = {int(aid) for aid in (state.get("probed_dirs") or []) if int(aid) in (1, 2, 3, 4)}
    chosen = None
    budget_spent = _can_coop_handoff(agent, state) and (
        bool(state.get("coop_handoff"))
        or int(state.get("llm_calls_level") or 0) >= 3
        or int(state.get("plan_writes_level") or 0) >= 3
        or (int(state.get("discover_steps") or 0) >= 2 and has_mover and not state.get("candidates") and "goal" not in roles)
        or (bool(dpad_set) and dpad_set <= probed_set and not has_mover and bool(state.get("dpad_moved")) and not state.get("click_only_ready"))
    )
    if budget_spent:
        state["coop_handoff"] = True
    if budget_spent and heuristic is not None and _ladder_ok(agent, heuristic, legal)[0]:
        chosen = heuristic
    if chosen is None and has_mover:
        if state.get("hypothesis_target") or state.get("hypothesis_box"):
            chosen = suggest_action("explore", legal, state)
        elif heuristic is not None and _ladder_ok(agent, heuristic, legal)[0]:
            chosen = heuristic
        else:
            chosen = suggest_action("explore", legal, state)
    if chosen is None or not _ladder_ok(agent, chosen, legal)[0]:
        field = state.get("top_down_field") or {}
        ckey = field.get("canvas_key")
        dead_set = set(_dead_line(agent, legal)[1])
        if (
            isinstance(ckey, (list, tuple))
            and len(ckey) == 2
            and ckey[0] == "SIMPLE"
            and int(ckey[1]) in dpad_set
            and int(ckey[1]) not in probed_set
            and tuple(ckey) not in dead_set
            and _ladder_ok(agent, tuple(ckey), legal)[0]
        ):
            probed_list = state.setdefault("probed_dirs", [])
            if int(ckey[1]) not in probed_list:
                probed_list.append(int(ckey[1]))
            chosen = ("SIMPLE", int(ckey[1]))
        else:
            chosen = next_direction_probe(state, legal, dead_set)
    if chosen is None and budget_spent:
        if heuristic is not None and _ladder_ok(agent, heuristic, legal)[0]:
            chosen = heuristic
        if chosen is None:
            alt = suggest_action("explore", legal, state)
            if alt is not None and _ladder_ok(agent, alt, legal)[0]:
                chosen = alt
        if chosen is None:
            state["probed_dirs"] = []
            state["tried_anchors"] = []
            chosen = next_direction_probe(state, legal, set(_dead_line(agent, legal)[1]))
        if chosen is None:
            chosen = next_direction_probe(state, legal, set())
        if chosen is None:
            chosen = suggest_action("explore", legal, state)
    if chosen is None:
        return None
    predicate = bind_predicate("explore", chosen, obs, None)
    if isinstance(predicate, dict) and predicate.get("geom") is None and predicate.get("role") == "avatar" and state.get("mover_geom"):
        predicate = dict(predicate)
        predicate["geom"] = list(state["mover_geom"])
    expectation = render(predicate) or "frame changes under labeled exploration"
    if chosen == heuristic and budget_spent:
        _bump(agent, "coord_accept")
        _bump(agent, "infl_heuristic")
    else:
        _bump(agent, "coord_explore")
    _bump(agent, "coord_steps")
    state["pending"] = {
        "action": chosen,
        "expect_change": True,
        "expectation": expectation,
        "goal": None,
        "features": entries.get("features"),
        "theory": (state.get("theory") or {}).get("text") or "",
        "shapes": list((entries.get("scene") or {}).get("records") or []),
        "primitive": "explore",
        "predicate": predicate,
        "comment": "direction probe",
    }
    _log(agent).append(
        {
            "level": int(getattr(agent, "current_level", 0) or 0),
            "heuristic": _fmt(heuristic),
            "heuristic_reason": _clip(reason or "", 80),
            "solver": (entries.get("scene") or {}).get("solver"),
            "scene": _clip((entries.get("scene") or {}).get("shapes") or "", 280),
            "schema": entries.get("schema") or "",
            "primitives": entries.get("primitives") or "",
            "primitive": "explore",
            "stream": stream,
            "decision": "accept" if (chosen == heuristic and budget_spent) else "explore",
            "mode": "discover",
            "action": _fmt(chosen),
            "action_key": list(chosen),
            "reason": "deterministic direction probe during discovery; models not called",
            "expectation": expectation,
            "expect_change": True,
            "predicate": expectation,
            "comment": "direction probe",
            "roles": entries.get("roles") or "",
            "binding": "avatar" if has_mover else "",
            "llm_calls_level": int(state.get("llm_calls_level") or 0),
            "latency_ms": {"a": 0.0, "b": 0.0, "executive": 0.0, "step": 0.0},
        }
    )
    note_discovery(state)
    return chosen


def _maybe_script(agent, legal, entries, heuristic, reason, stream, backend):
    """Execute the current plan, or ask the executive to write one. None stays in discovery."""
    from monad2.planmode import (
        PLAN_SYSTEM,
        current_step,
        parse_plan,
        plan_grammar,
        plan_signature,
        prompt,
        ready,
        reject_same,
    )

    state = _state(agent)
    if backend is None and state.get("coop_handoff"):
        state["surprise_pending"] = None
        state["mode"] = "discover"
        state["script"] = []
        return None
    surprise = str(state.get("surprise_pending") or "")
    if state.get("mode") == "execute" and not surprise:
        step = current_step(state)
        if step is not None:
            action, ref = _expand_valid(agent, step, legal, state, entries.get("menu_items") or [])
            ok = action is not None and _ladder_ok(agent, action, legal)[0]
            if ok:
                return _finish_fast(agent, "execute", action, ref, step, entries, heuristic, reason, stream, 0.0)
            surprise = "no progress"
            state["surprise_pending"] = surprise
    want = bool(surprise) or (ready(state) and not state.get("script"))
    if not want:
        return None
    max_llm_lvl = 1
    ep_llm_calls = int(_stats(agent).get("llm_calls", 0) or 0)
    if backend is None and _can_coop_handoff(agent, state) and (
        bool(state.get("coop_handoff"))
        or int(state.get("plan_writes_level") or 0) >= 3
        or int(state.get("interventions_level") or 0) > (1 if state.get("intra_game_promoted") else 2)
        or int(state.get("llm_calls_level") or 0) >= max_llm_lvl
        or ep_llm_calls >= 3
    ):
        state["coop_handoff"] = True
        state["surprise_pending"] = None
        state["mode"] = "discover"
        state["script"] = []
        return None
    if backend is None and int(state.get("plan_writes_level") or 0) >= 1 and not surprise:
        surprise = "plan finished"
    mode = "replan" if surprise else "plan"
    if mode == "replan":
        _bump(agent, "replan_calls")
    state["last_surprise"] = surprise
    is_pass2 = os.getenv("MONAD2_PASS") == "2" or getattr(agent, "m2_pass_idx", 1) == 2
    is_promoted = bool(state.get("intra_game_promoted"))
    synth_text = None
    if backend is None and (is_pass2 or (is_promoted and not surprise)):
        try:
            from monad2.synthesizer import lookup_synthesized_solver, synthesize_plan_json

            slot_env = os.getenv("MONAD2_GAME_SLOT", "").strip()
            slot_val = int(slot_env) if slot_env.lstrip("-").isdigit() else getattr(agent, "m2_game_slot", None)
            synth_spec = lookup_synthesized_solver(agent, state.get("frame_records") or [], legal, slot=slot_val)
            if synth_spec is not None:
                synth_text = synthesize_plan_json(synth_spec, state, legal)
        except Exception:
            synth_text = None
    if synth_text is not None:
        text, ms = synth_text, 0.0
    elif backend is None and is_pass2:
        state["coop_handoff"] = True
        state["surprise_pending"] = None
        state["mode"] = "discover"
        state["script"] = []
        return None
    else:
        if backend is None:
            from monad2.llm import get_backend

            backend = get_backend()
        click_only = not any(int(aid) in (1, 2, 3, 4) for aid in legal)
        try:
            text, ms = _call_model(
                agent,
                backend,
                "executive",
                PLAN_SYSTEM,
                prompt(entries, surprise if mode == "replan" else "", state.get("replan_context")),
                grammar=plan_grammar(click_only=click_only),
                max_tokens=80,
                strict_grammar=True,
            )
        except Exception:
            text, ms = (
                '{"goal":"REACH","steps":[{"primitive":"explore","binding":"avatar",'
                '"predicate":"translate","role":"avatar","role_b":"none","repeat":4}]}',
                0.0,
            )
    obs = state.get("schema_obs") or {}
    steps = parse_plan(text, obs, state)
    if mode == "replan":
        proposed = list(steps)
        steps, banned = reject_same(state.get("script") or [], steps, obs, state, state.get("rejected_sigs"))
        state["rejected_sigs"] = banned
        if plan_signature(steps) != plan_signature(proposed):
            state["plan_rejected"] = "identical"
    _bump(agent, "plan_writes")
    state["plan_writes_level"] = int(state.get("plan_writes_level") or 0) + 1
    state["surprise_pending"] = None
    state["mismatch"] = None
    if not steps:
        state["mode"] = "discover"
        state["script"] = []
        return None
    state["script"] = steps
    state["plan_sig"] = plan_signature(steps)
    state["script_i"] = 0
    state["plan"] = []
    state["plan_roles"] = state.get("role_line") or ("avatar" if state.get("mover_box") else "")
    state["stall_steps"] = 0
    state.setdefault("blocked_here", [])
    state.setdefault("route_blocks", [])
    state["route_prefix"] = []
    if not state.get("route_quantum"):
        state["route_quantum"] = int((state.get("role_evidence") or {}).get("quantum") or 0)
    state["mode"] = "execute"
    if getattr(agent, "game_specific_solvers_disabled", False) and int(state.get("llm_calls") or 0) >= 1:
        try:
            from monad2.synthesizer import record_level_observation

            record_level_observation(agent, state, int(getattr(agent, "current_level", 0) or 0))
            state["intra_game_promoted"] = True
        except Exception:
            pass
    action, ref = _expand_valid(agent, steps[0], legal, state, entries.get("menu_items") or [])
    if action is None or not _ladder_ok(agent, action, legal)[0]:
        state["mode"] = "discover"
        state["script"] = []
        return None
    return _finish_fast(agent, mode, action, ref, steps[0], entries, heuristic, reason, stream, ms)


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
    state = _state(agent)
    _touch_level(state, int(getattr(agent, "current_level", 0) or 0))
    state["llm_calls"] = int(_stats(agent).get("llm_calls", 0) or 0)
    has_dpad = any(int(aid) in (1, 2, 3, 4) for aid in legal)
    if backend is None and not has_dpad and 6 in legal:
        state["click_only_ready"] = True
    stream, entries = _stream(agent, heuristic, reason, legal)
    from monad2.planmode import current_step

    _new_role_surprise(state, current_step(state))
    if entries["fmf"] and not entries["fmf"].startswith("no overlapping"):
        _bump(agent, "fmf_in_stream")
    if "this is schema" in str(entries.get("schema") or ""):
        _bump(agent, "schema_in_stream")
    obs_roles = {slot.get("role") for slot in (state.get("schema_obs") or {}).get("roles") or [] if slot.get("role")}
    has_mover = ("avatar" in obs_roles) or bool(state.get("mover_box"))
    dpad_set = {int(aid) for aid in legal if int(aid) in (1, 2, 3, 4)}
    probed_set = {int(aid) for aid in (state.get("probed_dirs") or []) if int(aid) in (1, 2, 3, 4)}
    if (
        backend is None
        and 6 in legal
        and not has_mover
        and not state.get("dpad_moved")
        and dpad_set
        and dpad_set <= probed_set
    ):
        state["click_only_ready"] = True
    if backend is None:
        synth_res = _try_synthesized_step(agent, state, legal, entries, heuristic, stream)
        if synth_res is not None:
            return synth_res
    max_llm_lvl = 1
    ep_llm_calls = int(_stats(agent).get("llm_calls", 0) or 0)
    if backend is None and _can_coop_handoff(agent, state) and (
        (int(state.get("llm_calls_level") or 0) >= max_llm_lvl and (not state.get("script") or bool(state.get("surprise_pending"))))
        or ep_llm_calls >= 3
        or int(state.get("plan_writes_level") or 0) >= 3
        or int(state.get("interventions_level") or 0) > (1 if state.get("intra_game_promoted") else 2)
        or (int(state.get("discover_steps") or 0) >= 2 and has_mover and not state.get("candidates") and "goal" not in obs_roles)
        or (bool(dpad_set) and dpad_set <= probed_set and not has_mover and bool(state.get("dpad_moved")) and not state.get("click_only_ready"))
    ):
        state["coop_handoff"] = True
    scripted = _maybe_script(agent, legal, entries, heuristic, reason, stream, backend)
    if scripted is not None:
        return scripted
    if backend is None and has_dpad and not state.get("surprise_pending"):
        if not has_mover or int(state.get("discover_steps") or 0) < 2:
            probed = _probe_step(agent, legal, entries, heuristic, reason, stream)
            if probed is not None:
                return probed
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
                "primitives": entries.get("primitives") or "",
                "primitive": state.get("plan_primitive") or "",
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
    ep_llm_calls = int(_stats(agent).get("llm_calls", 0) or 0)
    if backend is None and _can_coop_handoff(agent, state) and (
        bool(state.get("coop_handoff"))
        or is_pass2
        or int(state.get("llm_calls_level") or 0) >= max_llm_lvl
        or ep_llm_calls >= 3
        or (int(state.get("discover_steps") or 0) >= 2 and has_mover and not state.get("candidates") and "goal" not in obs_roles)
        or (bool(dpad_set) and dpad_set <= probed_set and not has_mover and bool(state.get("dpad_moved")) and not state.get("click_only_ready"))
    ):
        state["coop_handoff"] = True
        probed = _probe_step(agent, legal, entries, heuristic, reason, stream)
        if probed is not None:
            return probed
        if heuristic is not None:
            fb_act = heuristic
        elif 6 in legal:
            aff_pts = (state.get("affordances") or {}).get("clickable") or [[32, 32]]
            pt = aff_pts[0] if aff_pts else [32, 32]
            fb_act = ("CLICK", int(pt[0]), int(pt[1]))
        else:
            fb_act = ("SIMPLE", int(legal[0])) if legal else ("SIMPLE", 1)
        _bump(agent, "coord_accept")
        _bump(agent, "coord_steps")
        state["pending"] = {
            "action": fb_act,
            "expect_change": True,
            "expectation": "cooperative fallback action",
            "goal": (state.get("theory") or {}).get("goal"),
            "features": entries.get("features"),
            "theory": (state.get("theory") or {}).get("text") or "",
            "shapes": list((entries.get("scene") or {}).get("records") or []),
            "primitive": "explore",
            "predicate": None,
            "comment": "coop fallback",
        }
        return fb_act
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
        "primitives": entries.get("primitives") or "",
        "stream": stream,
        "features": list(entries["features"]),
        "roles": entries.get("roles") or "",
    }
    a_fixed = False
    b_fixed = False
    try:
        from monad2.primitives import repair_action

        click_only = not any(int(aid) in (1, 2, 3, 4) for aid in legal)
        from monad2.llm import grammar_for

        click_note = ""
        if click_only:
            click_note = " This frame has no directional actions. Do not use SIMPLE, avatar, or hold_gradient."
        a_user = (
            _for_model(stream)
            + f"\nLegal actions: {entries.get('legal') or 'none'}."
            + "\nPropose one primitive from the [primitives] line and the role binding it uses."
            + " The action must be one of the legal actions."
            + click_note
        )
        a_text, a_ms = _call_model(
            agent,
            backend,
            "a",
            _A_SYSTEM,
            a_user,
            grammar=grammar_for("a", click_only) if click_only else None,
            strict_grammar=click_only,
        )
        a_obj = _json_obj(a_text) or {}
        a_key = _parse_action(a_obj.get("action") or a_text, legal)
        a_key, a_fixed = repair_action(a_key, legal, str(a_obj.get("primitive") or ""), _state(agent))
        if a_fixed:
            _bump(agent, "qwen_repaired")
        b_user = (
            _for_model(stream)
            + f"\nLegal actions: {entries.get('legal') or 'none'}."
            + f"\n[qwen_a] {_fmt(a_key)} primitive={a_obj.get('primitive') or 'none'} "
            + f"binding={_clip(str(a_obj.get('binding') or ''), 40)} "
            + f"effect={_clip(a_obj.get('effect') or '', 80)} "
            + f"reason={_clip(a_obj.get('reason') or a_text, 80)}"
            + (" repaired" if a_fixed else "")
        )
        b_text, b_ms = _call_model(
            agent,
            backend,
            "b",
            _B_SYSTEM,
            b_user + click_note,
            grammar=grammar_for("b", click_only) if click_only else None,
            strict_grammar=click_only,
        )
        b_obj = _json_obj(b_text) or {}
        b_key = _parse_action(b_obj.get("action") or b_text, legal)
        b_key, b_fixed = repair_action(b_key, legal, str(b_obj.get("primitive") or "explore"), _state(agent))
        if b_fixed:
            _bump(agent, "qwen_repaired")
        e_user = (
            _for_model(stream)
            + f"\n[qwen_a] {_fmt(a_key)} primitive={a_obj.get('primitive') or 'none'} "
            + f"binding={_clip(str(a_obj.get('binding') or ''), 40)} "
            + f"effect={_clip(a_obj.get('effect') or '', 80)} "
            + f"reason={_clip(a_obj.get('reason') or '', 80)}"
            + f"\n[qwen_b] {_fmt(b_key)} primitive={b_obj.get('primitive') or 'none'} "
            + f"binding={_clip(str(b_obj.get('binding') or ''), 40)} "
            + f"verdict={b_obj.get('verdict') or ''} "
            + f"effect={_clip(b_obj.get('effect') or '', 80)} "
            + f"reason={_clip(b_obj.get('reason') or '', 80)}"
            + (" repaired" if b_fixed else "")
        )
        from monad2.menu import executive_grammar

        menu = entries.get("menu_items") or []
        e_text, e_ms = _call_model(
            agent,
            backend,
            "executive",
            _E_SYSTEM,
            e_user,
            grammar=executive_grammar(menu, click_only=click_only) if menu else None,
            strict_grammar=bool(menu),
        )
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
    from monad2.menu import resolve_choice

    menu = entries.get("menu_items") or []
    chosen = resolve_choice(e_obj.get("action"), menu, legal)
    if chosen is None:
        chosen = resolve_choice(e_text, menu, legal)
    if chosen is None and menu:
        chosen = menu[0]["key"]
        e_obj = dict(e_obj)
        e_obj["reason"] = _clip((e_obj.get("reason") or "") + " resolved to menu 0", 180)
    elif chosen is None:
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

    named_primitive = str(e_obj.get("primitive") or b_obj.get("primitive") or a_obj.get("primitive") or "").strip().lower()
    prim = named_primitive if known(named_primitive) else ""
    if decision == "explore":
        prim = "explore"
    obs_now = _state(agent).get("schema_obs") or {}
    from monad2.primitives import precondition

    # A named primitive that the live roles do not support is inhibited in favor of one that does.
    if named_primitive and (not prim or not precondition(prim, obs_now, _state(agent))):
        listed = entries.get("primitive_list") or []
        alt = next((item.get("id") for item in listed if item.get("id") and item.get("id") != "explore"), "explore")
        if alt != prim:
            prim = alt
            if decision == "accept":
                decision = "inhibit"
    if (
        not click_only
        and decision != "explore"
        and contradicts_gradient("approach", chosen, _state(agent))
    ):
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
    comment = _clip(str(e_obj.get("expectation") or e_obj.get("effect") or ""), 80)
    predicate = None
    if prim:
        from monad2.predicates import bind_predicate, render

        predicate = bind_predicate(prim, chosen, _state(agent).get("schema_obs") or {}, e_obj)
        expectation = render(predicate) or comment or effect_of(prim)
    else:
        expectation = comment or effect_of(prim) or ("frame changes" if expect_change else "frame stays")
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
    if theory in ("PANEL_ALIGN", "SOKOBAN_PUSH", "SWITCH_GATE", "WAYPOINT_TOUR", "REACH_BFS"):
        state["llm_solver_family"] = theory
    if getattr(agent, "game_specific_solvers_disabled", False) and int(state.get("llm_calls") or 0) >= 1:
        try:
            from monad2.synthesizer import record_level_observation

            record_level_observation(agent, state, int(getattr(agent, "current_level", 0) or 0))
            state["intra_game_promoted"] = True
        except Exception:
            pass
    _remember_plan(state, e_obj.get("plan"), chosen, legal)
    state["plan_expect"] = expectation
    state["plan_expect_change"] = bool(expect_change)
    state["plan_goal"] = goal
    state["plan_primitive"] = prim
    state["plan_predicate"] = predicate
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
        "predicate": predicate,
        "comment": comment,
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
            "predicate": expectation if predicate else "",
            "comment": comment,
            "roles": entries.get("roles") or "",
            "mode": "discover",
            "llm_calls_level": int(state.get("llm_calls_level") or 0),
            "qwen_a_repaired": bool(a_fixed),
            "qwen_b_repaired": bool(b_fixed),
            "binding": _clip(str(e_obj.get("binding") or b_obj.get("binding") or a_obj.get("binding") or ""), 80),
            "qwen_a_primitive": str(a_obj.get("primitive") or ""),
            "qwen_a_binding": _clip(str(a_obj.get("binding") or ""), 80),
            "qwen_b_primitive": str(b_obj.get("primitive") or ""),
            "qwen_b_binding": _clip(str(b_obj.get("binding") or ""), 80),
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
        }
    )
    _log(agent).append(row)
    from monad2.planmode import note_discovery

    note_discovery(state)
    return chosen


def _track_shared_mover(state: dict, before: list[dict], after: list[dict], action, outcome: str) -> None:
    """Track the controllable mover box when its geometry is shared with other shapes on the board."""
    from monad2.roles import _geom_counts, _span, _thin_wall, _touched
    from monad2.schema import _bbox, _geom, _inside

    if not action or action[0] != "SIMPLE" or outcome not in ("continue", "reset"):
        return
    try:
        aid = int(action[1])
    except (TypeError, ValueError, IndexError):
        return
    if aid not in (1, 2, 3, 4):
        return
    ev = state.get("role_evidence") or {}
    if outcome == "reset":
        state["blocked_here"] = []
        state["route_prefix"] = []
        state["bridge_plan"] = None
        if ev.get("avatar") and len(ev["avatar"]) == 3:
            av_g = (int(ev["avatar"][0]), int(ev["avatar"][1]), int(ev["avatar"][2]))
            a_boxes = [_bbox(r) for r in (after or []) if _geom(r) == av_g and _bbox(r) is not None]
            if len(a_boxes) == 1:
                state["mover_box"] = a_boxes[0]
                state["prev_mover_box"] = a_boxes[0]
            elif len(a_boxes) > 1:
                try:
                    from monad2.synthesizer import resolve_shared_avatar_box

                    resolved = resolve_shared_avatar_box(state, after, a_boxes)
                    if resolved is not None:
                        state["mover_box"] = resolved
                        state["prev_mover_box"] = resolved
                except Exception:
                    pass
        return
    prev_mb = state.get("mover_box")
    prev_mb_tuple = (
        (int(prev_mb[0]), int(prev_mb[1]), int(prev_mb[2]), int(prev_mb[3]))
        if isinstance(prev_mb, (list, tuple)) and len(prev_mb) == 4
        else None
    )
    if state.get("movable_box"):
        state["prev_movable_box"] = state["movable_box"]
    av_g = None
    if ev.get("avatar") and len(ev["avatar"]) == 3:
        av_g = (int(ev["avatar"][0]), int(ev["avatar"][1]), int(ev["avatar"][2]))
        b_boxes = [_bbox(r) for r in (before or []) if _geom(r) == av_g and _bbox(r) is not None]
        a_recs = [r for r in (after or []) if _geom(r) == av_g and _bbox(r) is not None]
        a_boxes = [_bbox(r) for r in a_recs if _bbox(r) is not None]
        if len(a_boxes) == 1:
            a_sig = a_recs[0].get("sig")
            a_fill = int(a_sig[1]) if isinstance(a_sig, (list, tuple)) and len(a_sig) >= 2 else None
            known_fill = state.get("avatar_fill")
            if known_fill is None or len(b_boxes) <= 1 or a_fill == int(known_fill):
                state["mover_box"] = a_boxes[0]
                state["mover_geom"] = list(av_g)
                if a_fill is not None and known_fill is None:
                    state["avatar_fill"] = a_fill
                if len(b_boxes) == 1:
                    state["prev_mover_box"] = b_boxes[0]
                    if b_boxes[0][:2] != a_boxes[0][:2]:
                        state["dpad_moved"] = True
    b_pool = [(rec, _geom(rec), _bbox(rec)) for rec in (before or []) if _geom(rec) is not None and _bbox(rec) is not None]
    a_pool = [(rec, _geom(rec), _bbox(rec)) for rec in (after or []) if _geom(rec) is not None and _bbox(rec) is not None]
    a_stat_used: set[int] = set()
    b_moving = []
    for b_rec, bg, bbox in b_pool:
        matched = False
        for idx, (_a_rec, ag, abox) in enumerate(a_pool):
            if idx not in a_stat_used and bg == ag and bbox == abox and b_rec.get("sig") == _a_rec.get("sig"):
                a_stat_used.add(idx)
                matched = True
                break
        if not matched:
            b_moving.append((b_rec, bg, bbox))
    a_moving = [(a_rec, ag, abox) for idx, (a_rec, ag, abox) in enumerate(a_pool) if idx not in a_stat_used]
    if not b_moving or not a_moving:
        if av_g is None and state.get("mover_box"):
            state["prev_mover_box"] = state["mover_box"]
        return
    cand_matches = []
    for b_idx, (b_rec, bg, bbox) in enumerate(b_moving):
        for a_idx, (a_rec, ag, abox) in enumerate(a_moving):
            if bg != ag:
                continue
            dx = int(abox[0]) - int(bbox[0])
            dy = int(abox[1]) - int(bbox[1])
            if dx == 0 and dy == 0:
                continue
            same_sig = 0 if b_rec.get("sig") == a_rec.get("sig") else 1
            is_prev = 0 if (prev_mb_tuple is not None and bbox == prev_mb_tuple) else 1
            cand_matches.append((same_sig, is_prev, abs(dx) + abs(dy), b_idx, a_idx, dx, dy))
    cand_matches.sort()
    pairs = []
    used_b: set[int] = set()
    used_a: set[int] = set()
    for _ss, _ip, _d, b_idx, a_idx, dx, dy in cand_matches:
        if b_idx in used_b or a_idx in used_a:
            continue
        used_b.add(b_idx)
        used_a.add(a_idx)
        b_rec, bg, bbox = b_moving[b_idx]
        a_rec, _ag, abox = a_moving[a_idx]
        pairs.append((b_rec, bg, bbox, a_rec, abox, dx, dy))
    if not pairs:
        width = _span(before or after, None)
        if (
            av_g is None
            and any(not _thin_wall(r, width) for r, _g, _b in b_moving)
            and any(not _thin_wall(r, width) for r, _g, _b in a_moving)
        ):
            state["dpad_moved"] = True
        if av_g is None and state.get("mover_box"):
            state["prev_mover_box"] = state["mover_box"]
        return
    chosen_pair = None
    if prev_mb_tuple is not None and outcome != "reset":
        for p in pairs:
            if p[2] == prev_mb_tuple:
                chosen_pair = p
                break
        if chosen_pair is None and any(abox == prev_mb_tuple for _r, _g, abox in a_pool):
            state["prev_mover_box"] = prev_mb_tuple
            return
    if chosen_pair is None and av_g is not None and state.get("avatar_fill") is not None:
        want_fill = int(state["avatar_fill"])
        for p in pairs:
            p_sig = p[0].get("sig")
            if p[1] == av_g and isinstance(p_sig, (list, tuple)) and len(p_sig) >= 2 and int(p_sig[1]) == want_fill:
                chosen_pair = p
                break
    if chosen_pair is None and av_g is not None:
        for p in pairs:
            if p[1] == av_g:
                chosen_pair = p
                break
        if chosen_pair is None and len(a_boxes) == 1:
            return
    state["moving_boxes"] = [p[4] for p in pairs]
    mv_g = (
        (int(ev["movable"][0]), int(ev["movable"][1]), int(ev["movable"][2]))
        if ev.get("movable") and len(ev["movable"]) == 3
        else None
    )
    if chosen_pair is None:
        before_boxes = {p[2] for p in pairs}
        pairs.sort(
            key=lambda p: (
                1 if mv_g is not None and p[1] == mv_g else 0,
                0 if p[4] in before_boxes and p[2] not in {q[4] for q in pairs} else 1,
                -(p[2][2] * p[2][3]),
                p[1],
            )
        )
        chosen_pair = pairs[0]
    b_rec, bg, bbox, _a_rec, abox, dx, dy = chosen_pair
    state["prev_mover_box"] = bbox
    state["mover_box"] = abox
    state["mover_geom"] = [bg[0], bg[1], bg[2]]
    state["dpad_moved"] = True
    b_sig = b_rec.get("sig")
    if state.get("avatar_fill") is None and isinstance(b_sig, (list, tuple)) and len(b_sig) >= 2:
        state["avatar_fill"] = int(b_sig[1])
    if av_g is not None and bg == av_g and state.get("avatar_fill") is not None:
        av_f = int(state["avatar_fill"])
        moving_recs = {id(p[0]) for p in pairs if p[0].get("sig") == p[3].get("sig")}
        vanish_recs = {id(r) for r, _g, _b in b_moving} - moving_recs
        stat_fills = state.setdefault("stationary_sentry_fills", set())
        patrol_fills = state.setdefault("patrol_sentry_fills", set())
        seen_s_fills = state.setdefault("seen_sentry_fills", [])
        for r, rg, _rb in b_pool:
            if rg != av_g or r is b_rec or id(r) in vanish_recs:
                continue
            rsig = r.get("sig")
            if isinstance(rsig, (list, tuple)) and len(rsig) >= 2:
                rf = int(rsig[1])
                if rf == av_f:
                    continue
                if rf not in seen_s_fills:
                    seen_s_fills.append(rf)
                if id(r) in moving_recs:
                    patrol_fills.add(rf)
                else:
                    stat_fills.add(rf)
    step_q = max(abs(dx), abs(dy))
    if step_q > 0 and not state.get("route_quantum"):
        state["route_quantum"] = int(step_q)
    counts = _geom_counts(before)
    part_set = {
        (int(p[0]), int(p[1]), int(p[2]))
        for p in ((state.get("role_evidence") or {}).get("avatar_parts") or [])
        if isinstance(p, (list, tuple)) and len(p) == 3
    }
    for ob_rec, obg, _obbox, _oa_rec, oabox, _odx, _ody in pairs:
        if ob_rec is b_rec:
            continue
        if _touched(b_rec, ob_rec):
            is_inner = _inside(_obbox, bbox) or _inside(oabox, abox) or _inside(bbox, _obbox)
            is_push = prev_mb_tuple is not None or obg == mv_g or abox == _obbox
            if not is_inner and is_push and (_odx, _ody) == (dx, dy) and obg not in part_set:
                state["prev_movable_box"] = _obbox
                state["movable_box"] = oabox
                if counts.get(obg, 0) == 1 and isinstance(state.get("role_evidence"), dict):
                    state["role_evidence"]["movable"] = [obg[0], obg[1], obg[2]]
                break
            elif (is_inner or counts.get(obg, 0) == 1) and isinstance(state.get("role_evidence"), dict):
                parts = list(state["role_evidence"].get("avatar_parts") or [])
                entry = [obg[0], obg[1], obg[2]]
                if entry not in parts:
                    parts.append(entry)
                state["role_evidence"]["avatar_parts"] = parts


def _supervise_execution(state: dict, outcome: str, after: list[dict], prim_name: str) -> None:
    """Watch deterministic execution at 0ms and trigger capped LLM intervention only on an issue."""
    is_exec_or_synth = state.get("mode") == "execute" or str(state.get("last_ref") or "").startswith("synth:")
    if outcome == "reset":
        state["bridge_plan"] = None
        state["bridge_plan_target"] = None
        state["route_prefix"] = []
        state["blocked_here"] = []
        state["exec_seen_states"] = {}
        if is_exec_or_synth and not state.get("surprise_pending"):
            state["surprise_pending"] = "level reset"
    elif (
        is_exec_or_synth
        and outcome == "continue"
        and not state.get("surprise_pending")
        and not state.get("corridor_tour_queue")
        and prim_name in ("approach", "explore", "convey", "route", "hold_gradient")
        and state.get("mover_box")
    ):
        visit_key = (
            tuple(state.get("mover_box") or ()),
            tuple(state.get("hypothesis_box") or ()),
            tuple((r.get("geom"), r.get("xy"), (r.get("sig") or (None, None))[1]) for r in (after or [])[:24]),
        )
        seen_map = state.setdefault("exec_seen_states", {})
        seen_map[visit_key] = int(seen_map.get(visit_key) or 0) + 1
        if seen_map[visit_key] >= 4:
            state["route_prefix"] = []
            state["bridge_plan"] = None
            state["surprise_pending"] = "solver loop"
    if state.get("surprise_pending"):
        issue = str(state.get("surprise_pending"))
        ctx = state.get("replan_context")
        if not isinstance(ctx, dict):
            ctx = {}
            state["replan_context"] = ctx
        ctx["solver_issue"] = (
            f"{issue} during {prim_name or 'execute'} "
            f"(target={state.get('hypothesis_target')}, mover={state.get('mover_box')})"
        )
        state["interventions_level"] = int(state.get("interventions_level") or 0) + 1
        max_interv = 1 if state.get("intra_game_promoted") else 2
        if int(state["interventions_level"]) > max_interv:
            state["coop_handoff"] = True
            state["surprise_pending"] = None
            state["mode"] = "discover"
            state["script"] = []


def observe(agent, changed: bool) -> None:
    """Compare the executive expectation with the frame that just arrived."""
    state = _state(agent)
    pending = state.get("pending")
    if not pending:
        return
    try:
        from monad2.discovery import watch_step

        watch_step(agent, changed, force=True)
    except Exception:
        pass
    state["pending"] = None
    observed = "changed" if changed else "unchanged"
    hit = bool(pending.get("expect_change")) == bool(changed)
    pred_hit = None
    _bump(agent, "expect_scored")
    if hit:
        _bump(agent, "expect_hits")
    doc_text = ""
    doc_hit = None
    before = pending.get("shapes")
    log = _log(agent)
    if before is not None:
        from monad2.canvas_stream import current_document, document_result, shape_record

        doc_text, doc_hit, doc_diff = document_result(
            agent, list(before), str(pending.get("comment") or pending.get("expectation") or "")
        )
        state["last_diff"] = doc_diff
        state["hud_changed"] = bool(
            changed
            and isinstance(doc_diff, dict)
            and not (doc_diff.get("moved") or doc_diff.get("vanished") or doc_diff.get("appeared"))
        )
        try:
            from monad2.schema import account

            revision = account(agent, doc_hit, doc_diff, list(before))
        except Exception:
            revision = ""
        if revision:
            _bump(agent, "schema_revisions")
            if log:
                log[-1]["schema_revision"] = revision
        pred_hit = None
        predicate = pending.get("predicate")
        after = []
        try:
            doc = current_document(agent)
            after = [shape_record(s) for s in list(getattr(doc, "shapes", []) or [])]
        except Exception:
            after = []
        if after:
            state["frame_records"] = after
        outcome = "continue"
        try:
            from monad2.roles import infer_roles, note_effect

            outcome = _outcome(agent, state)
            prev_ev = dict(state.get("role_evidence") or {})
            had_avatar = bool(prev_ev.get("avatar")) or bool(state.get("mover_box"))
            had_switch = bool(prev_ev.get("switch"))
            if state.get("hypothesis_target") and not prev_ev.get("goal"):
                prev_ev["candidate_geom"] = list(state["hypothesis_target"])
            new_ev = note_effect(
                prev_ev,
                list(before),
                after,
                pending.get("action"),
                outcome,
            )
            if outcome == "reset" and int(state.get("level_steps") or 0) > 4 and not prev_ev.get("hazard"):
                new_ev.pop("hazard", None)
            state["role_evidence"] = new_ev
            if new_ev.get("quantum"):
                state["route_quantum"] = int(new_ev["quantum"])
            _track_shared_mover(state, list(before), after, pending.get("action"), outcome)
            now_has_avatar = bool(new_ev.get("avatar")) or bool(state.get("mover_box"))
            if (not had_avatar and now_has_avatar) or (not had_switch and new_ev.get("switch")):
                inferred = infer_roles(after, new_ev, _legal(agent))
                rline = ", ".join(s.get("role", "") for s in inferred.get("roles") or [] if s.get("role"))
                if not rline and state.get("mover_box"):
                    rline = "avatar"
                if rline:
                    state["prev_roles"] = rline
                    if int(state.get("discover_steps") or 0) >= 2:
                        state["stable_roles"] = rline
            if outcome == "completed" and new_ev.get("goal"):
                from monad2.schema import _shape_name, upsert

                g = [int(x) for x in new_ev["goal"][:3]]
                upsert(
                    {"roles": [{"role": "goal", "geom": g, "shape": _shape_name(tuple(g))}], "relations": []},
                    str(getattr(agent, "game_id", "") or "ep"),
                )
            if outcome == "completed":
                mtree = getattr(agent, "associative_merkle_tree", None)
                if mtree is not None and hasattr(mtree, "inos_merkle_log_solved_pattern"):
                    try:
                        solved_g = str(pending.get("goal") or (state.get("theory") or {}).get("goal") or "REACH")
                        if solved_g not in GOAL_TYPES:
                            solved_g = "REACH"
                        grid_now = getattr(agent, "_m2_grid", None)
                        b16_win = mtree.compute_board_fuzzy_sig16(grid_now) if grid_now is not None else 0x0001
                        script_prims = [
                            str(s.get("primitive"))
                            for s in (state.get("script") or [])
                            if isinstance(s, dict) and s.get("primitive")
                        ]
                        mtree.inos_merkle_log_solved_pattern(
                            b16_win,
                            f"SOLVED:{solved_g}",
                            level_idx=int(getattr(agent, "current_level", 0) or 0),
                            payload={"primitives": script_prims, "roles": str(state.get("role_line") or "")},
                        )
                    except Exception:
                        pass
        except Exception:
            pass
        if predicate:
            from monad2.predicates import evaluate

            ev_now = state.get("role_evidence") or {}
            if predicate.get("geom") is None and predicate.get("role") in ("avatar", "switch", "movable", "goal"):
                bound_g = ev_now.get(predicate.get("role"))
                if not bound_g and predicate.get("role") in ("avatar", "movable"):
                    bound_g = state.get("mover_geom")
                if bound_g and len(bound_g) == 3:
                    predicate = dict(predicate)
                    predicate["geom"] = [int(bound_g[0]), int(bound_g[1]), int(bound_g[2])]
            pred_hit = evaluate(predicate, list(before), after)
            _bump(agent, "predicate_checks")
            if pred_hit:
                _bump(agent, "predicate_hits")
        prim_name = str(pending.get("primitive") or "")
        if prim_name == "convey" and pred_hit is not True:
            try:
                from monad2.primitives import _role_box

                b_av = _role_box(state, list(before), "avatar")
                a_av = _role_box(state, after, "avatar")
                if b_av is not None and a_av is not None and (int(b_av[0]), int(b_av[1])) != (int(a_av[0]), int(a_av[1])):
                    pred_hit = True
                    if predicate:
                        _bump(agent, "predicate_hits")
            except Exception:
                pass
        try:
            act_now = pending.get("action")
            if outcome == "continue" and state.get("mode") != "execute" and act_now and act_now[0] == "SIMPLE" and int(act_now[1]) in (1, 2, 3, 4):
                from monad2.planmode import _non_avatar_changed, _reached_candidate
                from monad2.primitives import _boxes_for, _mover_box, note_route

                aid_now = int(act_now[1])
                b_box = _mover_box(state, list(before))
                a_box = _mover_box(state, after)
                if b_box is not None and a_box is not None:
                    moved_now = (int(b_box[0]), int(b_box[1])) != (int(a_box[0]), int(a_box[1]))
                    note_route(state, list(before), after, aid_now, moved_now)
                    b_plan = state.get("bridge_plan")
                    if not moved_now and isinstance(b_plan, list) and b_plan:
                        state["bridge_plan"] = None
                    if moved_now:
                        if (
                            isinstance(b_plan, list)
                            and b_plan
                            and (int(b_plan[0][0]), int(b_plan[0][1]), int(b_plan[0][2])) == (int(b_box[0]), int(b_box[1]), aid_now)
                        ):
                            state["bridge_plan"] = b_plan[1:]
                        state["blocked_here"] = []
                        if outcome == "continue" and state.get("hypothesis_target") and _reached_candidate(state, list(before), after):
                            hyp = state.get("hypothesis_target")
                            if hyp and len(hyp) == 3:
                                entry = [int(hyp[0]), int(hyp[1]), int(hyp[2])]
                                gt = (entry[0], entry[1], entry[2])
                                b_boxes = _boxes_for(list(before), gt)
                                a_boxes = _boxes_for(after or [], gt)
                                consumable_rem = bool(0 < len(a_boxes) < len(b_boxes))
                                refuted = state.setdefault("refuted_candidates", [])
                                if not consumable_rem and entry not in refuted:
                                    refuted.append(entry)
                                elif consumable_rem:
                                    for item in state.get("candidates") or []:
                                        if isinstance(item, dict) and item.get("geom") == entry:
                                            item["box"] = a_boxes[0]
                                            break
                                if _non_avatar_changed(list(before), after, state):
                                    ev_d = state.setdefault("role_evidence", {}) if isinstance(state.get("role_evidence"), dict) else {}
                                    if isinstance(ev_d, dict):
                                        if consumable_rem or (int(entry[0]) == 2 and bool(state.get("hud_changed"))):
                                            ev_d["collectible"] = list(entry)
                                        elif state.get("conditional_blocks") or state.get("deferred_candidates") or state.get("had_conditional_blocks"):
                                            ev_d["switch"] = list(entry)
                                            state["had_conditional_blocks"] = True
                            if (state.get("conditional_blocks") or state.get("deferred_candidates")) and _non_avatar_changed(list(before), after, state):
                                state["had_conditional_blocks"] = True
                                state["conditional_blocks"] = []
                                state["deferred_candidates"] = []
                            state["hypothesis_target"] = None
                            state["hypothesis_box"] = None
                    else:
                        bh = state.setdefault("blocked_here", [])
                        if aid_now not in bh:
                            bh.append(aid_now)
                        if state.get("last_conditional") and state.get("hypothesis_target"):
                            state["had_conditional_blocks"] = True
                            hyp = state.get("hypothesis_target")
                            if hyp and len(hyp) == 3:
                                entry = [int(hyp[0]), int(hyp[1]), int(hyp[2])]
                                deferred = state.setdefault("deferred_candidates", [])
                                if entry not in deferred:
                                    deferred.append(entry)
                            state["last_conditional"] = None
                            state["hypothesis_target"] = None
                            state["hypothesis_box"] = None
                        elif (
                            (state.get("conditional_blocks") or state.get("deferred_candidates"))
                            and (_non_avatar_changed(list(before), after, state) or bool(state.get("hud_changed")))
                        ):
                            state["had_conditional_blocks"] = True
                            state["conditional_blocks"] = []
                            state["deferred_candidates"] = []
            from monad2.planmode import note_result

            note_result(state, pred_hit, pending.get("action"), outcome, list(before), after)
            _supervise_execution(state, outcome, after, prim_name)
            try:
                from monad2.synthesizer import record_level_observation, synthesize_solver_from_pass1

                obs_lvl = int(getattr(agent, "current_level", 0) or 0)
                if outcome == "completed" and obs_lvl > 0:
                    obs_lvl -= 1
                record_level_observation(
                    agent,
                    state,
                    obs_lvl,
                    cleared=(outcome == "completed"),
                    before=list(before),
                    after=after,
                    action=pending.get("action"),
                    outcome=outcome,
                )
                if outcome == "completed":
                    slot_env = os.getenv("MONAD2_GAME_SLOT", "").strip()
                    slot_val = int(slot_env) if slot_env.lstrip("-").isdigit() else getattr(agent, "m2_game_slot", None)
                    synthesize_solver_from_pass1(agent, slot=slot_val, level_idx=obs_lvl)
                    state["intra_game_promoted"] = True
            except Exception:
                pass
        except Exception:
            pass
        if prim_name:
            from monad2.primitives import credit

            # A structured predicate is the only confidence signal. Frame change is not.
            scored = pred_hit if predicate else (doc_hit if doc_hit is not None else hit)
            conf, note = credit(state, prim_name, scored, pending.get("action"))
            if log:
                log[-1]["primitive_confidence"] = conf
                log[-1]["primitive_check"] = note
                log[-1]["predicate_hit"] = pred_hit
        if doc_hit is not None:
            _bump(agent, "expect_doc_scored")
            if doc_hit:
                _bump(agent, "expect_doc_hits")
        if predicate and pred_hit is False:
            from monad2.predicates import render

            text = render(predicate)
            surprises = state.setdefault("surprises", [])
            surprises.append(text)
            del surprises[:-6]
            _bump(agent, "predicate_surprises")
            ltp = getattr(agent, "m2_ltp", None)
            if not isinstance(ltp, EpisodeLTP):
                ltp = EpisodeLTP()
                agent.m2_ltp = ltp
            bag = getattr(ltp, "surprises", None)
            if bag is None:
                ltp.surprises = []
                bag = ltp.surprises
            bag.append(text)
            state["mismatch"] = {
                "expectation": text,
                "predicate": text,
                "expect_change": True,
                "observed": observed,
                "action": pending.get("action"),
                "doc": doc_text,
            }
            if log:
                log[-1]["surprise"] = text
    if log:
        log[-1]["result"] = observed
        log[-1]["expectation_hit"] = pred_hit if pending.get("predicate") else hit
        log[-1]["doc_diff"] = doc_text
        log[-1]["doc_hit"] = doc_hit
    goal = pending.get("goal")
    features = tuple(pending.get("features") or ())
    if pending.get("predicate"):
        if pred_hit is not True:
            return
    elif not hit or doc_hit is False:
        state["mismatch"] = {
            "expectation": pending.get("expectation"),
            "expect_change": pending.get("expect_change"),
            "observed": observed,
            "action": pending.get("action"),
            "doc": doc_text,
        }
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
    confirmed_prims = [
        str(s.get("primitive"))
        for s in (state.get("script") or [])
        if isinstance(s, dict) and s.get("primitive")
    ]
    if not confirmed_prims and pending.get("primitive"):
        confirmed_prims = [str(pending.get("primitive"))]
    confirmed_roles = str(state.get("role_line") or "")
    remember(features, goal, holdout=holdout, primitives=confirmed_prims, roles=confirmed_roles)
    if len(EPISODE_FMF) > before:
        note = pending.get("theory") or pending.get("expectation") or goal
        CARRIED.append(
            {
                "features": list(features),
                "goal": goal,
                "note": note,
                "primitives": confirmed_prims,
                "roles": confirmed_roles,
            }
        )
        _bump(agent, "carried_theories")


def _outcome(agent, state: dict) -> str:
    """Level completion correlates with the goal. A reset or a game-over correlates with a hazard."""
    level = int(getattr(agent, "current_level", 0) or 0)
    resets = int(getattr(agent, "_consecutive_game_over_resets", 0) or 0)
    prev_level = state.get("seen_level")
    prev_resets = state.get("seen_resets")
    outcome = "continue"
    if prev_level is not None and level > int(prev_level):
        outcome = "completed"
    elif prev_resets is not None and resets > int(prev_resets):
        outcome = "reset"
    state["seen_level"] = level
    state["seen_resets"] = resets
    return outcome


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
                    f"Mode: {row.get('mode') or 'discover'}.",
                    f"Roles: {row.get('roles') or 'none'}.",
                    f"Schema: {row.get('schema') or 'none'}.",
                    f"Proposed: {row.get('primitives') or 'none'}.",
                    f"Qwen A' primitive {row.get('qwen_a_primitive') or 'none'} "
                    f"binds {row.get('qwen_a_binding') or 'none'}, action {row.get('qwen_a')}"
                    f"{' repaired' if row.get('qwen_a_repaired') else ''}: "
                    f"{row.get('qwen_a_reason') or ''} Effect: {row.get('qwen_a_effect') or ''}.",
                    f"Qwen B' primitive {row.get('qwen_b_primitive') or 'none'} "
                    f"binds {row.get('qwen_b_binding') or 'none'}, "
                    f"{row.get('qwen_b_verdict') or 'replied'} {row.get('qwen_b')}: "
                    f"{row.get('qwen_b_reason') or ''}",
                    f"Executive {row.get('decision')} -> {row.get('action')} "
                    f"via {row.get('primitive') or 'none'} binds {row.get('binding') or 'none'}. "
                    f"Reason: {row.get('reason')}",
                    f"Predicate: {row.get('predicate') or row.get('expectation') or 'none'}."
                    f"{result_bit}{doc_bit}",
                    f"Comment: {row.get('comment') or ''}.",
                    f"Check: {row.get('primitive_check') or 'pending'} "
                    f"(confidence {row.get('primitive_confidence')})"
                    f"{' surprise ' + row.get('surprise') if row.get('surprise') else ''}.",
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
        "infl_field",
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

