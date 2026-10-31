"""Abstract game schemas learned from play.

A schema is a relational structure over canvas roles: avatar, goal, receptor,
movable, switch, wall, hazard, trail floor, and counter/HUD. Relations are
contact, containment, shape matching, painting, toggling, and an action-effect
mapping. Slots bind to shape_geom_sig only. Colors, absolute positions, game
ids, and action sequences are not stored.

On a later episode the executive matches the live structure to the closest
stored schema and writes the role binding, including a substitution when the
same role is a different shape. A document mismatch either rebinds that role
or rejects the schema. Holdout prefixes never write the store.
"""
from __future__ import annotations

import os
from collections import Counter

from monad2.factorial import HOLDOUT_PREFIXES

ROLES = (
    "avatar",
    "goal",
    "receptor",
    "movable",
    "switch",
    "wall",
    "hazard",
    "trail_floor",
    "counter_hud",
)

_SHAPE = {
    0: "none",
    1: "rect",
    2: "hollow_rect",
    3: "line",
    4: "ellipse",
    5: "sprite",
    6: "enclosed_cell",
}

# Keys that would make a schema a per-puzzle record.
_FORBIDDEN_KEYS = {
    "game_id",
    "task_id",
    "game",
    "game_ids",
    "color",
    "fill_color",
    "colours",
    "colors",
    "x",
    "y",
    "click",
    "click_x",
    "click_y",
    "xy",
    "coord",
    "coords",
    "row",
    "col",
    "absolute",
    "actions",
    "action_sequence",
    "sequence",
    "sig",
}

STORE: list[dict] = []
_EPISODES: dict[int, str] = {}
_EP_N = 0
LAST_FRAME: dict = {}


def reset_store() -> None:
    global _EP_N
    STORE.clear()
    _EPISODES.clear()
    _EP_N = 0
    LAST_FRAME.clear()


def episode_of(agent) -> str:
    """Episode id stored on the agent. Object ids get reused after a game ends."""
    global _EP_N
    found = getattr(agent, "_m2_schema_ep", None)
    if isinstance(found, str) and found:
        return found
    _EP_N += 1
    found = f"ep-{_EP_N}"
    try:
        setattr(agent, "_m2_schema_ep", found)
    except Exception:
        _EPISODES[id(agent)] = found
    return found


def _fmt(geom) -> str:
    if not geom:
        return "unbound"
    return ",".join(str(int(v)) for v in geom)


def _shape_name(geom) -> str:
    if not geom:
        return "shape"
    return _SHAPE.get(int(geom[0]), "shape")


def assert_structure(obj, path: str = "schema") -> None:
    """Reject game ids, colors, absolute coordinates, and action sequences."""
    if isinstance(obj, dict):
        for key, value in obj.items():
            if str(key).lower() in _FORBIDDEN_KEYS:
                raise ValueError(f"{path}.{key} is not allowed in a schema")
            assert_structure(value, f"{path}.{key}")
        return
    if isinstance(obj, (list, tuple)):
        ints = [item for item in obj if isinstance(item, int)]
        if len(obj) in (2, 4) and len(ints) == len(obj):
            raise ValueError(f"{path} looks like a coordinate or a color-bearing signature")
        if len(obj) == 3 and len(ints) == 3:
            return
        for index, value in enumerate(obj):
            assert_structure(value, f"{path}[{index}]")
        return
    if isinstance(obj, str) and any(token in obj.lower() for token in ("game_id", "click ", "simple ")):
        if "simple" in obj.lower() and "axis" not in path:
            raise ValueError(f"{path} names an action sequence")


def _geom(rec: dict) -> tuple[int, int, int] | None:
    raw = rec.get("geom")
    if not raw or len(raw) != 3:
        return None
    return (int(raw[0]), int(raw[1]), int(raw[2]))


def _bbox(rec: dict) -> tuple[int, int, int, int] | None:
    xy = rec.get("xy")
    wh = rec.get("wh")
    if not xy or not wh:
        return None
    return (int(xy[0]), int(xy[1]), int(wh[0]), int(wh[1]))


def _inside(inner, outer) -> bool:
    ix, iy, iw, ih = inner
    ox, oy, ow, oh = outer
    return ix >= ox and iy >= oy and ix + iw <= ox + ow and iy + ih <= oy + oh and (iw, ih) != (ow, oh)


def _touch(a, b) -> bool:
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    gap_x = max(0, max(ax, bx) - min(ax + aw, bx + bw))
    gap_y = max(0, max(ay, by) - min(ay + ah, by + bh))
    return gap_x <= 1 and gap_y <= 1 and not _inside(a, b) and not _inside(b, a)


def _hud_present(playfield: str) -> bool:
    text = playfield or ""
    for part in text.split():
        if part.startswith("hud_rows=") or part.startswith("hud_cols="):
            try:
                if int(part.split("=", 1)[1]) > 0:
                    return True
            except ValueError:
                continue
    return False


def induce(records: list[dict], diff: dict | None, meta: str, playfield: str) -> dict:
    """Read roles and relations off one scene. Coordinates stay local to this call."""
    recs = [rec for rec in records or [] if _geom(rec) is not None]
    moved_sigs = {tuple(item.get("sig") or ()) for item in (diff or {}).get("moved") or []}
    vanished = list((diff or {}).get("vanished") or [])
    appeared = list((diff or {}).get("appeared") or [])
    meta_l = (meta or "").lower()

    def is_moved(rec: dict) -> bool:
        return tuple(rec.get("sig") or ()) in moved_sigs

    roles: list[dict] = []
    taken: set[int] = set()

    def add(role: str, rec: dict | None) -> None:
        slot = {"role": role}
        if rec is not None:
            geom = _geom(rec)
            if geom is not None:
                slot["geom"] = list(geom)
                slot["shape"] = _shape_name(geom)
            taken.add(id(rec))
        if any(item["role"] == role for item in roles):
            return
        roles.append(slot)

    for rec in recs:
        geom = _geom(rec)
        if geom is None:
            continue
        if int(geom[0]) == 2:
            add("receptor", rec)
            break
    for rec in recs:
        geom = _geom(rec)
        if geom is None or id(rec) in taken:
            continue
        if int(geom[0]) in (1, 3) and int(geom[2]) >= 8:
            add("wall", rec)
            break

    movers = [rec for rec in recs if is_moved(rec) and id(rec) not in taken]
    movers.sort(key=lambda rec: (int(rec.get("area") or 0), _geom(rec) or (0, 0, 0)))
    if movers:
        add("avatar", movers[0])
        for extra in movers[1:]:
            if not any(item["role"] == "movable" for item in roles):
                add("movable", extra)
    else:
        rest = [rec for rec in recs if id(rec) not in taken and _geom(rec) is not None]
        rest.sort(key=lambda rec: (int(rec.get("area") or 0), _geom(rec) or (0, 0, 0)))
        if rest:
            add("avatar", rest[0])
    for rec in recs:
        geom = _geom(rec)
        if geom is None or id(rec) in taken:
            continue
        if int(geom[0]) in (1, 6) and int(geom[2]) <= 3 and "responsive_switch" in meta_l:
            add("switch", rec)
            break
    if "hazard" in meta_l:
        for rec in recs:
            if id(rec) not in taken:
                add("hazard", rec)
                break
    if "terminal_goal" in meta_l or any(item["role"] == "receptor" for item in roles):
        receptor = next((rec for rec in recs if _geom(rec) and int(_geom(rec)[0]) == 2), None)
        if receptor is not None:
            if not any(item["role"] == "goal" for item in roles):
                roles.append(
                    {
                        "role": "goal",
                        "geom": list(_geom(receptor)),
                        "shape": "hollow_rect",
                    }
                )
        elif "terminal_goal" in meta_l:
            add("goal", None)
    if _hud_present(playfield):
        add("counter_hud", None)

    relations: list[dict] = []
    if movers:
        relations.append({"kind": "effect", "role": "avatar", "change": "translate"})
    appeared_geoms = []
    for rec in appeared:
        geom = _geom(rec) if isinstance(rec, dict) else None
        if geom is None and isinstance(rec, dict):
            for known in recs:
                if tuple(known.get("sig") or ()) == tuple(rec.get("sig") or ()):
                    geom = _geom(known)
                    break
        if geom is not None:
            appeared_geoms.append(geom)
    for rec in vanished:
        geom = None
        if isinstance(rec, dict):
            for known in recs:
                if tuple(known.get("sig") or ()) == tuple(rec.get("sig") or ()):
                    geom = _geom(known)
                    break
        if geom is not None and geom in appeared_geoms:
            relations.append({"kind": "paint", "role": "trail_floor", "geom": list(geom)})
            if not any(item["role"] == "trail_floor" for item in roles):
                roles.append({"role": "trail_floor", "geom": list(geom), "shape": _shape_name(geom)})
            break
    if any(item["role"] == "switch" for item in roles) and vanished:
        relations.append({"kind": "toggle", "role": "switch"})

    by_id = {id(rec): rec for rec in recs}
    role_of: dict[int, str] = {}
    for slot in roles:
        geom = tuple(slot["geom"]) if slot.get("geom") else None
        if geom is None:
            continue
        for rec in recs:
            if _geom(rec) == geom and id(rec) not in role_of:
                role_of[id(rec)] = slot["role"]
                break
    ids = list(by_id)
    for i, left_id in enumerate(ids):
        left_box = _bbox(by_id[left_id])
        left_role = role_of.get(left_id)
        if left_box is None or left_role is None:
            continue
        for right_id in ids[i + 1 :]:
            right_box = _bbox(by_id[right_id])
            right_role = role_of.get(right_id)
            if right_box is None or right_role is None or left_role == right_role:
                continue
            if _inside(left_box, right_box):
                relations.append({"kind": "containment", "inner": left_role, "outer": right_role})
            elif _inside(right_box, left_box):
                relations.append({"kind": "containment", "inner": right_role, "outer": left_role})
            elif _touch(left_box, right_box):
                pair = tuple(sorted((left_role, right_role)))
                relations.append({"kind": "contact", "left": pair[0], "right": pair[1]})

    receptor = next((slot for slot in roles if slot["role"] == "receptor"), None)
    if receptor and receptor.get("geom"):
        rtype = int(receptor["geom"][0])
        for slot in roles:
            geom = slot.get("geom")
            if slot["role"] in ("receptor", "goal") or not geom:
                continue
            if int(geom[0]) == rtype and list(geom) != list(receptor["geom"]):
                relations.append({"kind": "shape_match", "left": slot["role"], "right": "receptor"})
                break

    schema = {"roles": roles, "relations": _unique_rels(relations)}
    assert_structure(schema)
    return schema


def _unique_rels(relations: list[dict]) -> list[dict]:
    seen = set()
    out = []
    for rel in relations:
        key = tuple(sorted((str(k), str(v)) for k, v in rel.items()))
        if key in seen:
            continue
        seen.add(key)
        out.append(rel)
    return out


def _merge(base: dict, extra: dict) -> dict:
    roles = {slot["role"]: dict(slot) for slot in base.get("roles") or []}
    votes: dict[str, Counter] = {}
    saved = base.get("_votes") or {}
    for role, counts in saved.items():
        votes[role] = Counter({tuple(int(p) for p in key.split(",")): int(n) for key, n in counts.items()})
    for source in (base, extra):
        if source is base and saved:
            continue
        for slot in source.get("roles") or []:
            role = slot["role"]
            geom = tuple(slot["geom"]) if slot.get("geom") else None
            votes.setdefault(role, Counter())
            if geom is not None:
                votes[role][geom] += 1
            if role not in roles:
                roles[role] = {"role": role}
    for role, counter in votes.items():
        if role not in roles:
            roles[role] = {"role": role}
        if not counter:
            continue
        geom, _n = counter.most_common(1)[0]
        roles[role]["geom"] = list(geom)
        roles[role]["shape"] = _shape_name(geom)
    relations = _unique_rels(list(base.get("relations") or []) + list(extra.get("relations") or []))
    merged = {
        "roles": list(roles.values()),
        "relations": relations,
        "_votes": {role: {",".join(str(p) for p in geom): n for geom, n in counter.items()} for role, counter in votes.items()},
    }
    assert_structure({"roles": merged["roles"], "relations": merged["relations"]})
    return merged


def _holdout(explicit: str = "") -> str:
    return (explicit or os.getenv("MONAD2_HOLDOUT_GAME", "") or "").lower().strip()


def holding_out(prefix: str = "") -> bool:
    return _holdout(prefix) in HOLDOUT_PREFIXES


def upsert(schema: dict, episode: str, holdout: str = "") -> str | None:
    """Store a schema for this episode. Holdout play writes nothing."""
    if holding_out(holdout):
        return None
    if not schema.get("roles"):
        return None
    body = {
        "roles": [dict(slot) for slot in schema.get("roles") or []],
        "relations": list(schema.get("relations") or []),
    }
    assert_structure(body)
    for row in STORE:
        if row.get("episode") == episode:
            merged = _merge(row, body)
            row["roles"] = merged["roles"]
            row["relations"] = merged["relations"]
            assert_structure(row)
            return str(row["id"])
    row = {
        "id": f"S{len(STORE)}",
        "episode": episode,
        "roles": body["roles"],
        "relations": body["relations"],
    }
    assert_structure(row)
    STORE.append(row)
    return str(row["id"])


def _bindings(schema: dict, obs: dict) -> tuple[int, list[dict]]:
    have = {slot["role"]: slot for slot in obs.get("roles") or []}
    score = 0
    bindings = []
    for slot in schema.get("roles") or []:
        role = slot["role"]
        other = have.get(role)
        if other is None:
            continue
        left = tuple(slot["geom"]) if slot.get("geom") else None
        right = tuple(other["geom"]) if other.get("geom") else None
        if left is not None and left == right:
            score += 2
            bindings.append({"role": role, "kind": "same", "geom": list(left), "shape": _shape_name(left)})
        elif left is None or right is None:
            score += 1
            geom = list(right or left) if (right or left) else None
            bindings.append({"role": role, "kind": "open", "geom": geom, "shape": _shape_name(geom)})
        else:
            score += 1
            bindings.append(
                {
                    "role": role,
                    "kind": "rebind",
                    "schema": list(left),
                    "observed": list(right),
                    "shape": other.get("shape") or _shape_name(right),
                }
            )
    kinds_s = {rel.get("kind") for rel in schema.get("relations") or []}
    kinds_o = {rel.get("kind") for rel in obs.get("relations") or []}
    score += len(kinds_s & kinds_o)
    return score, bindings


def match(obs: dict, episode: str, rejected: set[str] | None = None) -> dict | None:
    rejected = rejected or set()
    best = None
    best_score = 0
    for row in STORE:
        if row.get("episode") == episode or row.get("id") in rejected:
            continue
        score, bindings = _bindings(row, obs)
        if score > best_score and bindings:
            best_score = score
            best = {"id": row["id"], "score": score, "bindings": bindings, "schema": row}
    return best


def render(hit: dict) -> str:
    bits = [f"this is schema {hit['id']}"]
    for binding in hit["bindings"]:
        role = binding["role"].replace("_", " ")
        if binding["kind"] == "same":
            bits.append(f"the {role} bound to {_shape_name(binding.get('geom'))} geom {_fmt(binding.get('geom'))}")
        elif binding["kind"] == "rebind":
            bits.append(
                f"the {role} rebound to {binding.get('shape')} geom {_fmt(binding.get('observed'))} "
                f"where the schema had geom {_fmt(binding.get('schema'))}"
            )
        else:
            bits.append(f"the {role} binding is open")
    rels = {rel.get("kind") for rel in (hit.get("schema") or {}).get("relations") or []}
    if "effect" in rels:
        expectation = "bound avatar moves"
    elif "paint" in rels:
        expectation = "trail floor changes"
    elif "shape_match" in rels:
        expectation = "the shape matches the receptor"
    elif "toggle" in rels:
        expectation = "the switch toggles"
    else:
        expectation = "no shape change"
    text = " with ".join([bits[0], ", ".join(bits[1:])]) if len(bits) > 1 else bits[0]
    return f"hypothesis {text}. Expectation: {expectation}. Colors and positions are not in the schema."


def capture_frame(agent) -> None:
    grid = getattr(agent, "_m2_grid", None)
    if not isinstance(grid, list) or not grid or not isinstance(grid[0], list):
        return
    LAST_FRAME["grid"] = [list(row) for row in grid]
    LAST_FRAME["hud_rows"] = set(getattr(agent, "hud_rows", None) or [])
    LAST_FRAME["hud_cols"] = set(getattr(agent, "hud_cols", None) or [])
    LAST_FRAME["episode"] = episode_of(agent)


def hypothesis_line(agent, scene: dict, diff: dict | None) -> str:
    """Match the live scene to a schema from another episode and draft this one."""
    capture_frame(agent)
    state = getattr(agent, "_m2_coord", None)
    if not isinstance(state, dict):
        state = {}
        agent._m2_coord = state
    records = list(scene.get("records") or [])
    obs = induce(records, diff, str(scene.get("meta") or ""), str(scene.get("playfield") or ""))
    episode = episode_of(agent)
    state["schema_obs"] = obs
    rejected = set(state.get("schema_rejected") or [])
    override = state.get("schema_rebind") or {}
    hit = match(obs, episode, rejected)
    if hit and override.get("id") == hit["id"]:
        for binding in hit["bindings"]:
            if binding["role"] == override.get("role") and override.get("geom"):
                binding["kind"] = "rebind"
                binding["observed"] = list(override["geom"])
                binding["shape"] = _shape_name(override["geom"])
    if hit:
        state["schema_hyp"] = {
            "id": hit["id"],
            "bindings": hit["bindings"],
            "misses": int((state.get("schema_hyp") or {}).get("misses") or 0)
            if (state.get("schema_hyp") or {}).get("id") == hit["id"]
            else 0,
        }
        line = render(hit)
    else:
        state["schema_hyp"] = None
        line = "no stored schema from another episode yet; abstracting this play into roles"
    note = state.get("schema_note")
    if note:
        line = f"{line} {note}"
        state["schema_note"] = ""
    return line


def account(agent, doc_hit: bool | None, diff: dict | None, before: list[dict]) -> str:
    """Fold the step into the draft schema. A miss rebinds the avatar or rejects it."""
    state = getattr(agent, "_m2_coord", None)
    if not isinstance(state, dict):
        return ""
    records = list(before or [])
    meta = ""
    playfield = ""
    scene = state.get("schema_scene") or {}
    if isinstance(scene, dict):
        meta = str(scene.get("meta") or "")
        playfield = str(scene.get("playfield") or "")
    obs = induce(records, diff, meta, playfield)
    episode = episode_of(agent)
    draft = state.get("schema_draft")
    merged = _merge(draft, obs) if isinstance(draft, dict) else obs
    state["schema_draft"] = merged
    stored = upsert(merged, episode)
    note = ""
    hyp = state.get("schema_hyp")
    if hyp and doc_hit is False:
        moved = []
        for item in (diff or {}).get("moved") or []:
            sig = tuple(item.get("sig") or ())
            for rec in records:
                if tuple(rec.get("sig") or ()) == sig and _geom(rec) is not None:
                    moved.append(_geom(rec))
                    break
        bound = None
        for binding in hyp.get("bindings") or []:
            if binding.get("role") == "avatar":
                bound = tuple(binding.get("geom") or binding.get("observed") or binding.get("schema") or ())
                break
        if moved and (not bound or moved[0] != tuple(bound)):
            state["schema_rebind"] = {"id": hyp["id"], "role": "avatar", "geom": list(moved[0])}
            note = f"binding refined: avatar rebound to geom {_fmt(moved[0])}"
        else:
            rejected = set(state.get("schema_rejected") or [])
            rejected.add(hyp["id"])
            state["schema_rejected"] = sorted(rejected)
            state["schema_hyp"] = None
            note = f"rejected schema {hyp['id']}"
        state["schema_note"] = note
    return note


def remember_scene(agent, scene: dict, diff: dict | None) -> None:
    state = getattr(agent, "_m2_coord", None)
    if isinstance(state, dict):
        state["schema_scene"] = {
            "meta": scene.get("meta"),
            "playfield": scene.get("playfield"),
        }


def audit_store() -> list[str]:
    """Every stored schema must stay free of game ids, colors, and coordinates."""
    problems = []
    for row in STORE:
        try:
            assert_structure(row)
        except ValueError as exc:
            problems.append(str(exc))
        for key in ("game_id", "task_id", "game", "color", "fill_color"):
            if key in row:
                problems.append(f"{row.get('id')} has {key}")
    return problems


def _records_from_grid(grid, hud_rows=None, hud_cols=None) -> list[dict]:
    from my_agent_v7_inos import CanvasDocument

    from monad2.canvas_stream import shape_record

    doc = CanvasDocument(grid, set(hud_rows or []), set(), set(hud_cols or []))
    return [shape_record(shape) for shape in doc.shapes]


def _rot90(grid):
    height = len(grid)
    width = len(grid[0]) if height else 0
    return [[grid[height - 1 - r][c] for r in range(height)] for c in range(width)]


def _rot_hud(height, hud_rows, hud_cols):
    new_cols = {height - 1 - int(r) for r in hud_rows or []}
    new_rows = {int(c) for c in hud_cols or []}
    return new_rows, new_cols


def _permute(grid):
    return [[(int(value) + 1) % 16 for value in row] for row in grid]


def _enlarge_avatar(grid, records: list[dict], prefer: tuple | None = None) -> list[list[int]]:
    """Grow the avatar shape by one cell, so the role binds a different geom."""
    out = [list(row) for row in grid]
    if prefer is not None:
        ranked = [rec for rec in records if _geom(rec) == tuple(prefer)]
    else:
        ranked = []
    if not ranked:
        ranked = sorted(
            (rec for rec in records if _geom(rec) is not None and int(_geom(rec)[2]) < 8),
            key=lambda rec: (int(rec.get("area") or 0), _geom(rec)),
        )
    if not ranked:
        return out
    rec = ranked[0]
    sig = rec.get("sig") or ()
    if len(sig) < 2:
        return out
    color = int(sig[1])
    x, y = (int(rec["xy"][0]), int(rec["xy"][1])) if rec.get("xy") else (0, 0)
    w = int(rec["wh"][0]) if rec.get("wh") else 1
    height = len(out)
    width = len(out[0]) if height else 0
    nx = x + w
    if 0 <= y < height and 0 <= nx < width and int(out[y][nx]) != color:
        out[y][nx] = color
    return out


def transformed_case(grid=None, hud_rows=None, hud_cols=None) -> dict:
    """Recolor and rotate a played frame, then substitute one shape's geometry."""
    frame = grid if grid is not None else LAST_FRAME.get("grid")
    if not frame:
        return {"ok": False, "reason": "no played frame"}
    rows = hud_rows if hud_rows is not None else LAST_FRAME.get("hud_rows") or set()
    cols = hud_cols if hud_cols is not None else LAST_FRAME.get("hud_cols") or set()
    base_records = _records_from_grid(frame, rows, cols)
    base = induce(base_records, None, "", _playfield(rows, cols))
    turned = _permute(_rot90(frame))
    t_rows, t_cols = _rot_hud(len(frame), rows, cols)
    turned_records = _records_from_grid(turned, t_rows, t_cols)
    base_geoms = sorted(_fmt(_geom(rec)) for rec in base_records if _geom(rec))
    turned_geoms = sorted(_fmt(_geom(rec)) for rec in turned_records if _geom(rec))
    identity = base_geoms == turned_geoms
    avatar_geom = next(
        (tuple(slot["geom"]) for slot in base.get("roles") or [] if slot.get("role") == "avatar" and slot.get("geom")),
        None,
    )
    larger = _permute(_rot90(_enlarge_avatar(frame, base_records, avatar_geom)))
    alt_records = _records_from_grid(larger, t_rows, t_cols)
    alt = induce(alt_records, None, "", _playfield(t_rows, t_cols))
    source = upsert(base, episode="ep-frame")
    hit = None
    if source:
        for row in STORE:
            if row.get("id") == source:
                score, bindings = _bindings(row, alt)
                if bindings:
                    hit = {"id": row["id"], "score": score, "bindings": bindings, "schema": row}
                break
    line = render(hit) if hit else ""
    rebound = "rebound" in line
    return {
        "ok": bool(hit) and identity,
        "identity_geoms": identity,
        "base_geoms": base_geoms,
        "turned_geoms": turned_geoms,
        "schema_id": source,
        "line": line,
        "rebound": rebound,
        "pure": audit_store() == [],
        "grid": larger,
        "hud_rows": sorted(t_rows),
        "hud_cols": sorted(t_cols),
    }


def _playfield(rows, cols) -> str:
    return f"bg=stripped shapes=0 hud_rows={len(set(rows or []))} hud_cols={len(set(cols or []))}"
