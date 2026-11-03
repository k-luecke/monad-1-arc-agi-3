"""Motor primitives mined from the old solvers.

Each primitive is a rule of motion: a precondition read from the current role
binding, an action pattern, and an expected effect. Bindings are role names.
There is no game id, no frame fingerprint, no palette entry, and no coordinate.

The old solver methods stay in the agent for reference. This module does not
call them. A move that is not one of these rules is the explore primitive,
and it has to be labeled as exploration.
"""
from __future__ import annotations

import ast
from pathlib import Path

# Action ids. 1 up, 2 down, 3 left, 4 right, 5 interact. Not coordinates.
_REVERSE = {1: 2, 2: 1, 3: 4, 4: 3}

NAMES = (
    "approach",
    "hold_gradient",
    "convey",
    "align",
    "toggle",
    "avoid",
    "cycle_select",
    "route",
    "assemble",
    "explore",
)

_EFFECT = {
    "approach": "avatar translates toward the goal",
    "hold_gradient": "avatar does not reverse",
    "convey": "movable translates toward the goal",
    "align": "the object matches the reference",
    "toggle": "the switch changes another role",
    "avoid": "avatar stays off the hazard",
    "cycle_select": "the selector matches the reference",
    "route": "avatar translates along the open axis",
    "assemble": "two roles make contact",
    "explore": "frame changes under labeled exploration",
}

_BINDING = {
    "approach": ("avatar", "goal"),
    "hold_gradient": ("avatar", "goal"),
    "convey": ("avatar", "movable", "goal"),
    "align": ("avatar", "receptor"),
    "toggle": ("switch",),
    "avoid": ("avatar", "hazard"),
    "cycle_select": ("switch", "goal"),
    "route": ("avatar", "wall"),
    "assemble": ("movable", "receptor"),
    "explore": (),
}


def _roles(obs: dict) -> set[str]:
    return {str(slot.get("role")) for slot in (obs or {}).get("roles") or [] if slot.get("role")}


def _relations(obs: dict) -> set[str]:
    return {str(rel.get("kind")) for rel in (obs or {}).get("relations") or [] if rel.get("kind")}


def _has(roles: set[str], *need: str) -> bool:
    return all(name in roles for name in need)


def _role_geom(obs: dict, role: str):
    for slot in (obs or {}).get("roles") or []:
        if slot.get("role") == role and slot.get("geom") and len(slot["geom"]) == 3:
            return (int(slot["geom"][0]), int(slot["geom"][1]), int(slot["geom"][2]))
    return None


def _rec_geom(rec: dict):
    raw = rec.get("geom")
    if not raw or len(raw) != 3:
        return None
    return (int(raw[0]), int(raw[1]), int(raw[2]))


def _rec_box(rec: dict):
    xy = rec.get("xy")
    wh = rec.get("wh")
    if not xy or not wh or len(xy) != 2 or len(wh) != 2:
        return None
    return (int(xy[0]), int(xy[1]), int(wh[0]), int(wh[1]))


def _boxes_for(records, geom) -> list:
    if geom is None:
        return []
    found = []
    for rec in records or []:
        if _rec_geom(rec) != geom:
            continue
        box = _rec_box(rec)
        if box is not None:
            found.append(box)
    return found


def _overlap(a, b) -> bool:
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    return ax < bx + bw and ax + aw > bx and ay < by + bh and ay + ah > by


def _neg() -> int:
    return 0 - 1


def _ahead(box, aid: int):
    x, y, w, h = box
    step = _neg()
    if aid == 1:
        return (x, y + step, w, 1)
    if aid == 2:
        return (x, y + h, w, 1)
    if aid == 3:
        return (x + step, y, 1, h)
    if aid == 4:
        return (x + w, y, 1, h)
    return None


def _dir_order(dx: int, dy: int) -> list[int]:
    step = _neg()
    deltas = ((1, 0, step), (2, 0, 1), (3, step, 0), (4, 1, 0))
    scored = []
    for aid, sx, sy in deltas:
        scored.append((sx * dx + sy * dy, aid))
    scored.sort(key=lambda item: (-item[0], item[1]))
    return [aid for _score, aid in scored]


def _quantum_of(state) -> int:
    try:
        value = int((state or {}).get("route_quantum") or 0)
    except (TypeError, ValueError):
        return 0
    if value < 1:
        return 0
    return value


def _block_set(state) -> set:
    found = set()
    for key in ("route_blocks", "conditional_blocks"):
        for item in (state or {}).get(key) or []:
            if not isinstance(item, (list, tuple)) or len(item) < 3:
                continue
            try:
                found.add((int(item[0]), int(item[1]), int(item[2])))
            except (TypeError, ValueError):
                continue
    return found


def _blocked_at(blocks: set, box) -> set:
    ox, oy = int(box[0]), int(box[1])
    return {aid for x, y, aid in blocks if x == ox and y == oy}


def _shift(aid: int, quantum: int):
    back = _neg()
    if aid == 1:
        return (0, back * quantum)
    if aid == 2:
        return (0, quantum)
    if aid == 3:
        return (back * quantum, 0)
    if aid == 4:
        return (quantum, 0)
    return None


def _snap(value: int, origin: int, quantum: int) -> int:
    if quantum < 1:
        return value
    delta = int(value) - int(origin)
    steps = int(round(delta / quantum))
    return int(origin) + steps * quantum


def _swept_box(box, nxt):
    x, y, w, h = int(box[0]), int(box[1]), int(box[2]), int(box[3])
    nx, ny = int(nxt[0]), int(nxt[1])
    x0 = x if x <= nx else nx
    y0 = y if y <= ny else ny
    x1 = (x + w) if (x + w) >= (nx + w) else (nx + w)
    y1 = (y + h) if (y + h) >= (ny + h) else (ny + h)
    return (x0, y0, x1 - x0, y1 - y0)


def _around_prefix(mover, target, quantum: int, blocks: set, legal: list[int], walls: list) -> list[int]:
    """Full step prefix of a path that treats known blocked edges as walls."""
    sx, sy = int(mover[0]), int(mover[1])
    mw, mh = int(mover[2]), int(mover[3])
    tx = int(target[0]) + (int(target[2]) - mw) // 2 if mw > int(target[2]) else int(target[0])
    ty = int(target[1]) + (int(target[3]) - mh) // 2 if mh > int(target[3]) else int(target[1])
    gx = _snap(tx, sx, quantum)
    gy = _snap(ty, sy, quantum)
    if (sx, sy) == (gx, gy):
        return []
    wide_x = mw > int(target[2])
    wide_y = mh > int(target[3])
    larger_target = int(target[2]) > mw and int(target[3]) > mh
    options = set(_dpad(legal))
    start = (sx, sy)
    came = {start: None}
    queue = [start]
    found = None
    limit = 6 * 6 * 6 * 6
    base_span = 4 * 4 * 4
    max_x = sx + mw if sx + mw > int(target[0]) + int(target[2]) else int(target[0]) + int(target[2])
    max_y = sy + mh if sy + mh > int(target[1]) + int(target[3]) else int(target[1]) + int(target[3])
    bound_x = base_span if base_span >= max_x else max_x + quantum
    bound_y = base_span if base_span >= max_y else max_y + quantum
    head = 0
    while head < len(queue) and len(came) < limit:
        x, y = queue[head]
        head = head + 1
        if (x, y) == (gx, gy) or (
            (x, y) != start
            and (not wide_x or x == gx)
            and (not wide_y or y == gy)
            and (_inside_box((x, y, mw, mh), target) if larger_target else _overlap((x, y, mw, mh), target))
        ):
            found = (x, y)
            break
        local_order = _dir_order(gx - x, gy - y)
        ranked = []
        for rank_i, aid in enumerate(local_order):
            if aid not in options:
                continue
            if (x, y, aid) in blocks:
                continue
            shift = _shift(aid, quantum)
            if shift is None:
                continue
            nxt = (x + shift[0], y + shift[1])
            if nxt[0] < 0 or nxt[1] < 0 or nxt[0] + mw > bound_x or nxt[1] + mh > bound_y:
                continue
            probe = _ahead((x, y, mw, mh), aid)
            swept = _swept_box((x, y, mw, mh), nxt)
            if (probe is not None and any(_overlap(probe, wall) for wall in walls)) or any(
                _overlap(swept, wall) for wall in walls
            ):
                continue
            ranked.append((abs(nxt[0] - gx) + abs(nxt[1] - gy), rank_i, aid, nxt))
        ranked.sort()
        for _dist, _rank_i, aid, nxt in ranked:
            if nxt in came:
                continue
            came[nxt] = (x, y, aid)
            queue.append(nxt)
    if found is None:
        return []
    node = found
    steps = []
    while node != start:
        parent = came.get(node)
        if parent is None:
            return []
        px, py, aid = parent
        steps.append(int(aid))
        node = (px, py)
    steps.reverse()
    return steps


def _around(mover, target, quantum: int, blocks: set, legal: list[int], walls: list):
    """First step of a path that treats known blocked edges as walls."""
    prefix = _around_prefix(mover, target, quantum, blocks, legal, walls)
    return prefix[0] if prefix else None


def _role_box(state, records, role: str):
    obs = (state or {}).get("schema_obs") or {}
    geom = _role_geom(obs, role)
    if geom is None:
        raw = ((state or {}).get("role_evidence") or {}).get(role)
        if raw and len(raw) == 3:
            geom = (int(raw[0]), int(raw[1]), int(raw[2]))
    boxes = _boxes_for(records, geom)
    if len(boxes) == 1:
        return boxes[0]
    is_before = False
    if isinstance(state, dict) and records:
        f_recs = state.get("frame_records")
        if isinstance(f_recs, list) and f_recs and records is not f_recs and records != f_recs:
            is_before = True
        else:
            mv_box = state.get("movable_box")
            if isinstance(mv_box, (list, tuple)) and len(mv_box) == 4:
                want_mv = (int(mv_box[0]), int(mv_box[1]), int(mv_box[2]), int(mv_box[3]))
                if not any(_rec_box(r) == want_mv for r in records):
                    is_before = True
    if role == "avatar":
        av_keys = ("prev_mover_box", "mover_box") if is_before else ("mover_box", "prev_mover_box")
        for key in av_keys:
            saved = (state or {}).get(key)
            if isinstance(saved, (list, tuple)) and len(saved) == 4:
                want_box = (int(saved[0]), int(saved[1]), int(saved[2]), int(saved[3]))
                for rec in records or []:
                    if _rec_box(rec) == want_box:
                        return want_box
        if len(boxes) > 1:
            from monad2.synthesizer import resolve_shared_avatar_box
            resolved = resolve_shared_avatar_box(state, records, boxes)
            if resolved is not None:
                return resolved
        for key in av_keys:
            saved = (state or {}).get(key)
            if isinstance(saved, (list, tuple)) and len(saved) == 4:
                return (int(saved[0]), int(saved[1]), int(saved[2]), int(saved[3]))
        for part in ((state or {}).get("role_evidence") or {}).get("avatar_parts") or []:
            if isinstance(part, (list, tuple)) and len(part) == 3:
                pboxes = _boxes_for(records, (int(part[0]), int(part[1]), int(part[2])))
                if len(pboxes) == 1:
                    return pboxes[0]
    if role == "movable":
        mv_keys = ("prev_movable_box", "movable_box") if is_before else ("movable_box", "prev_movable_box")
        for key in mv_keys:
            saved = (state or {}).get(key)
            if isinstance(saved, (list, tuple)) and len(saved) == 4:
                want_box = (int(saved[0]), int(saved[1]), int(saved[2]), int(saved[3]))
                for rec in records or []:
                    if _rec_box(rec) == want_box:
                        return want_box
    return None


def _mover_box(state, records):
    role = str((state or {}).get("step_role") or "")
    if not role or role == "none" or (state or {}).get("plan_primitive") == "convey":
        role = "avatar"
    box = _role_box(state, records, role)
    if box is None and role != "avatar":
        box = _role_box(state, records, "avatar")
    return box


def _inside_box(inner, outer) -> bool:
    ix, iy, iw, ih = inner
    ox, oy, ow, oh = outer
    return ix >= ox and iy >= oy and ix + iw <= ox + ow and iy + ih <= oy + oh and (iw, ih) != (ow, oh)


def _target_box(state, records, obs: dict, target_role: str):
    pbox = (state or {}).get("playfield_box")
    pbox_tuple = (
        (int(pbox[0]), int(pbox[1]), int(pbox[2]), int(pbox[3]))
        if isinstance(pbox, (list, tuple)) and len(pbox) == 4
        else None
    )
    role_g = _role_geom(obs, target_role)
    if role_g is not None:
        boxes = _boxes_for(records, role_g)
        if len(boxes) == 1:
            return boxes[0]
    if target_role == "goal":
        hyp = (state or {}).get("hypothesis_target")
        if hyp and len(hyp) == 3:
            want = (int(hyp[0]), int(hyp[1]), int(hyp[2]))
            boxes = _boxes_for(records, want)
            if len(boxes) > 1 and pbox_tuple is not None:
                scoped = [b for b in boxes if _inside_box(b, pbox_tuple)]
                if len(scoped) == 1:
                    boxes = scoped
            if len(boxes) == 1:
                if isinstance(state, dict):
                    state["hypothesis_box"] = boxes[0]
                return boxes[0]
            for cand in (state or {}).get("candidates") or []:
                cg = cand.get("geom") if isinstance(cand, dict) else None
                cbox = cand.get("box") if isinstance(cand, dict) else None
                if (
                    isinstance(cg, (list, tuple))
                    and len(cg) == 3
                    and (int(cg[0]), int(cg[1]), int(cg[2])) == want
                    and isinstance(cbox, (list, tuple))
                    and len(cbox) == 4
                ):
                    resolved = (int(cbox[0]), int(cbox[1]), int(cbox[2]), int(cbox[3]))
                    if isinstance(state, dict):
                        state["hypothesis_box"] = resolved
                    return resolved
        saved = (state or {}).get("hypothesis_box")
        if isinstance(saved, (list, tuple)) and len(saved) == 4:
            return (int(saved[0]), int(saved[1]), int(saved[2]), int(saved[3]))
    return None


def blocked_dirs(state) -> set:
    """Directions already blocked at the current mover. Ephemeral; not a schema."""
    box = _mover_box(state, (state or {}).get("frame_records") or [])
    found = set()
    if box is not None:
        found.update(_blocked_at(_block_set(state), box))
    for item in (state or {}).get("blocked_here") or []:
        try:
            found.add(int(item))
        except (TypeError, ValueError):
            continue
    return found


def _seal(state, box) -> None:
    quantum = _quantum_of(state)
    if quantum < 1:
        return
    here = _blocked_at(_block_set(state), box)
    if len(here) < 3:
        return
    prev = (state or {}).get("route_prev")
    if not isinstance(prev, (list, tuple)) or len(prev) < 3:
        return
    try:
        px, py, aid = int(prev[0]), int(prev[1]), int(prev[2])
    except (TypeError, ValueError):
        return
    shift = _shift(aid, quantum)
    if shift is None:
        return
    if (px + shift[0], py + shift[1]) != (int(box[0]), int(box[1])):
        return
    entry = [px, py, aid]
    store = state.setdefault("route_blocks", [])
    if entry not in store:
        store.append(entry)


def _conditional_hit(state, before, origin, aid: int) -> bool:
    if (state or {}).get("mode") == "discover" or not (state or {}).get("hypothesis_target"):
        return False
    obs = (state or {}).get("schema_obs") or {}
    wall_geom = _role_geom(obs, "wall")
    walls = [
        w
        for w in _boxes_for(before, wall_geom)
        if not _overlap(origin, w) and (wall_geom is None or int(wall_geom[0]) in (1, 3))
    ]
    probe = _ahead(origin, aid)
    quantum = _quantum_of(state)
    shift = _shift(aid, quantum if quantum > 0 else 1)
    stepped = (origin[0] + shift[0], origin[1] + shift[1], origin[2], origin[3]) if shift else probe
    if probe is not None and any(_overlap(probe, w) for w in walls):
        return False
    if stepped is not None and any(_overlap(stepped, w) for w in walls):
        return False
    tbox = _target_box(state, before, obs, "goal")
    if tbox is not None:
        if probe is not None and _overlap(probe, tbox):
            return True
        if stepped is not None and _overlap(stepped, tbox):
            if _overlap(origin, tbox) or tbox[2] > origin[2] or tbox[3] > origin[3]:
                return True
    excluded = set()
    for rname in ("wall", "avatar", "movable", "reference", "receptor"):
        rg = _role_geom(obs, rname)
        if rg is not None:
            excluded.add(rg)
    ev = (state or {}).get("role_evidence") or {}
    for part in ev.get("avatar_parts") or []:
        if isinstance(part, (list, tuple)) and len(part) == 3:
            excluded.add((int(part[0]), int(part[1]), int(part[2])))
    for cand in (state or {}).get("candidates") or []:
        cg = cand.get("geom") if isinstance(cand, dict) else None
        if isinstance(cg, (list, tuple)) and len(cg) == 3:
            excluded.add((int(cg[0]), int(cg[1]), int(cg[2])))
    for rec in before or []:
        g = _rec_geom(rec)
        box = _rec_box(rec)
        if g is None or box is None or g in excluded or box == origin:
            continue
        if int(g[0]) not in (1, 2) or box[2] * box[3] > 6 * 6:
            continue
        if _overlap(origin, box) or _inside_box(origin, box):
            continue
        if probe is not None and _overlap(probe, box):
            if tbox is None or int(g[0]) == 2 or _overlap(box, tbox):
                return True
            gap_x = (
                box[0] - (tbox[0] + tbox[2])
                if box[0] >= tbox[0] + tbox[2]
                else (tbox[0] - (box[0] + box[2]) if tbox[0] >= box[0] + box[2] else 0)
            )
            gap_y = (
                box[1] - (tbox[1] + tbox[3])
                if box[1] >= tbox[1] + tbox[3]
                else (tbox[1] - (box[1] + box[3]) if tbox[1] >= box[1] + box[3] else 0)
            )
            limit_gap = quantum if quantum > 2 else 2
            if gap_x <= limit_gap and gap_y <= limit_gap:
                return True
    return False


def note_route(state, before, after, aid: int, moved: bool) -> None:
    """A failed step stays blocked at that cell. A move teaches the step size."""
    if not isinstance(state, dict):
        return
    origin = _mover_box(state, before)
    if origin is None:
        return
    landed = _mover_box(state, after)
    if not moved:
        if landed is not None and (int(landed[0]), int(landed[1])) != (int(origin[0]), int(origin[1])):
            return
        entry = [int(origin[0]), int(origin[1]), int(aid)]
        if aid != 5 and _conditional_hit(state, before, origin, aid):
            cond = state.setdefault("conditional_blocks", [])
            if entry not in cond:
                cond.append(entry)
            state["last_conditional"] = entry
            return
        state["last_conditional"] = None
        store = state.setdefault("route_blocks", [])
        if entry not in store:
            store.append(entry)
        if aid != 5:
            _seal(state, origin)
        return
    state["last_conditional"] = None
    if landed is None:
        return
    dx = int(landed[0]) - int(origin[0])
    dy = int(landed[1]) - int(origin[1])
    dist = abs(dx) if abs(dx) >= abs(dy) else abs(dy)
    q_now = _quantum_of(state)
    if dist > 0 and not q_now:
        state["route_quantum"] = dist
        q_now = dist
    if q_now > 0 and (abs(dx) + abs(dy)) != q_now:
        state["route_prev"] = None
        return
    state["route_prev"] = [int(origin[0]), int(origin[1]), int(aid)]


def _push_box(avatar, movable, push_aid: int, quantum: int = 0):
    mx, my, mw, mh = int(movable[0]), int(movable[1]), int(movable[2]), int(movable[3])
    aw, ah = int(avatar[2]), int(avatar[3])
    q = int(quantum or 0)
    step_w = aw if aw >= q else q
    step_h = ah if ah >= q else q
    if push_aid == 1:
        return (mx, my + (mh if mh >= q else q), aw, ah)
    if push_aid == 2:
        return (mx, my - step_h, aw, ah)
    if push_aid == 3:
        return (mx + (mw if mw >= q else q), my, aw, ah)
    if push_aid == 4:
        return (mx - step_w, my, aw, ah)
    return None


def step_toward(name: str, legal: list[int], state: dict):
    """One d-pad step toward the bound target. None when that target has no unique box."""
    if name not in ("approach", "convey", "route", "explore"):
        return None
    obs = (state or {}).get("schema_obs") or {}
    records = (state or {}).get("frame_records") or []
    mover_role = str((state or {}).get("step_role") or "")
    target_role = str((state or {}).get("step_target") or "")
    if name == "convey" and not mover_role:
        mover_role = "movable"
    if not mover_role or mover_role == "none":
        mover_role = "avatar"
    if not target_role or target_role == "none":
        target_role = "goal" if name != "route" else "wall"
    mover = _mover_box(state, records)
    target = _target_box(state, records, obs, target_role)
    if target is None and name == "convey":
        target = _target_box(state, records, obs, "receptor") or _target_box(state, records, obs, "goal")
    if mover is None or target is None:
        if isinstance(state, dict):
            state["route_prefix"] = []
        return None
    wall_g = _role_geom(obs, "wall")
    walls = [
        w
        for w in _boxes_for(records, wall_g)
        if not _overlap(mover, w) and (wall_g is None or int(wall_g[0]) in (1, 3))
    ]
    blocked = blocked_dirs(state)
    options = _dpad(legal)
    quantum = _quantum_of(state)
    if name == "convey":
        avatar_box = _role_box(state, records, "avatar")
        movable_box = _role_box(state, records, "movable")
        if avatar_box is not None and movable_box is not None and avatar_box != movable_box:
            push_aid = None
            m_blocks = _block_set(state)
            if quantum:
                m_prefix = _around_prefix(movable_box, target, quantum, m_blocks, options, walls)
                if m_prefix:
                    cand_pbox = _push_box(avatar_box, movable_box, m_prefix[0], quantum)
                    if cand_pbox is not None and not any(_overlap(cand_pbox, wall) for wall in walls):
                        push_aid = m_prefix[0]
            if push_aid is None:
                mcx = movable_box[0] + movable_box[2] // 2
                mcy = movable_box[1] + movable_box[3] // 2
                tgx = target[0] + target[2] // 2
                tgy = target[1] + target[3] // 2
                for cand_aid in _dir_order(tgx - mcx, tgy - mcy):
                    if cand_aid not in options or (movable_box[0], movable_box[1], cand_aid) in m_blocks:
                        continue
                    m_probe = _ahead(movable_box, cand_aid)
                    if m_probe is not None and any(_overlap(m_probe, wall) for wall in walls):
                        continue
                    cand_pbox = _push_box(avatar_box, movable_box, cand_aid, quantum)
                    if cand_pbox is not None and any(_overlap(cand_pbox, wall) for wall in walls):
                        continue
                    push_aid = cand_aid
                    break
            if push_aid is not None:
                step_q = quantum if quantum > 0 else 1
                shift = _shift(push_aid, step_q)
                stepped = (
                    (avatar_box[0] + shift[0], avatar_box[1] + shift[1], avatar_box[2], avatar_box[3])
                    if shift
                    else None
                )
                probe = _ahead(avatar_box, push_aid)
                if (probe is not None and _overlap(probe, movable_box)) or (
                    stepped is not None and _overlap(stepped, movable_box)
                ):
                    if push_aid not in blocked and push_aid in options:
                        if isinstance(state, dict):
                            state["route_prefix"] = [push_aid]
                        return push_aid
                pbox = _push_box(avatar_box, movable_box, push_aid, quantum)
                if pbox is not None:
                    mover = avatar_box
                    target = pbox
                    if not _overlap(avatar_box, movable_box):
                        walls = list(walls) + [movable_box]
    if 5 in legal and 5 not in blocked and not _overlap(mover, target):
        x_aligned = mover[0] < target[0] + target[2] and mover[0] + mover[2] > target[0]
        y_aligned = mover[1] < target[1] + target[3] and mover[1] + mover[3] > target[1]
        v_dir = 1 if target[1] < mover[1] else 2
        h_dir = 3 if target[0] < mover[0] else 4
        if (x_aligned and v_dir in blocked) or (y_aligned and h_dir in blocked):
            return 5
    if quantum:
        from monad2.synthesizer import plan_bridge_lattice_prefix
        b_prefix = plan_bridge_lattice_prefix(state, records, mover, target, quantum, _block_set(state), options)
        prefix = b_prefix if b_prefix is not None else _around_prefix(mover, target, quantum, _block_set(state), options, walls)
        if prefix and prefix[0] not in blocked and prefix[0] in options:
            if isinstance(state, dict):
                state["route_prefix"] = list(prefix)
            return prefix[0]
    if isinstance(state, dict):
        state["route_prefix"] = []
    cx = mover[0] + mover[2] // 2
    cy = mover[1] + mover[3] // 2
    gx = target[0] + target[2] // 2
    gy = target[1] + target[3] // 2
    for aid in _dir_order(gx - cx, gy - cy):
        if aid not in options or aid in blocked:
            continue
        probe = _ahead(mover, aid)
        if probe is not None and any(_overlap(probe, wall) for wall in walls):
            continue
        if quantum > 0:
            shift = _shift(aid, quantum)
            if shift is not None:
                swept = _swept_box(mover, (mover[0] + shift[0], mover[1] + shift[1]))
                if any(_overlap(swept, wall) for wall in walls):
                    continue
        return aid
    return None


def precondition(name: str, obs: dict, state: dict) -> bool:
    roles = _roles(obs)
    if (state or {}).get("mover_box"):
        roles = set(roles) | {"avatar"}
    if (state or {}).get("movable_box") or ((state or {}).get("role_evidence") or {}).get("movable"):
        roles = set(roles) | {"movable"}
    rels = _relations(obs)
    progress = state.get("progress_axis")
    if name == "approach":
        return "avatar" in roles and "goal" in roles
    if name == "hold_gradient":
        return progress in _REVERSE and "avatar" in roles
    if name == "convey":
        return "movable" in roles and ("goal" in roles or "receptor" in roles or bool((state or {}).get("hypothesis_target")))
    if name == "align":
        return "receptor" in roles or "reference" in roles or "shape_match" in rels
    if name == "toggle":
        return (
            "switch" in roles
            or "clickable" in roles
            or "toggle" in rels
            or bool((state.get("affordances") or {}).get("clickable"))
        )
    if name == "avoid":
        return "hazard" in roles and ("avatar" in roles or "clickable" in roles)
    if name == "cycle_select":
        return ("switch" in roles or "clickable" in roles) and (
            "goal" in roles or "receptor" in roles or "reference" in roles
        )
    if name == "route":
        return "avatar" in roles and ("wall" in roles or "containment" in rels)
    if name == "assemble":
        return (
            "movable" in roles
            or ("receptor" in roles and "avatar" in roles)
            or ("clickable" in roles and ("reference" in roles or "receptor" in roles))
        )
    if name == "explore":
        return True
    return False


def _dpad(legal: list[int]) -> list[int]:
    return [aid for aid in legal if aid in _REVERSE]


def _click_at(state: dict, *roles: str):
    """A click anchor from the live affordance map. Not stored on the primitive."""
    aff = (state or {}).get("affordances") or {}
    tried_pts = {
        (int(p[0]), int(p[1]))
        for p in ((state or {}).get("tried_anchors") or [])
        if isinstance(p, (list, tuple)) and len(p) == 2
    }
    for c_act in (state or {}).get("synth_tried_clicks") or []:
        if isinstance(c_act, (list, tuple)) and len(c_act) >= 3 and c_act[0] == "CLICK":
            tried_pts.add((int(c_act[1]), int(c_act[2])))
    for role in roles:
        points = aff.get(role) or []
        if isinstance(points, (list, tuple)) and points:
            for point in points:
                if isinstance(point, (list, tuple)) and len(point) == 2:
                    pt = (int(point[0]), int(point[1]))
                    if pt not in tried_pts:
                        return ("CLICK", pt[0], pt[1])
    return None


def action_legal(key, legal: list[int]) -> bool:
    if not key:
        return False
    if key[0] == "CLICK":
        return 6 in legal
    if key[0] == "SIMPLE":
        try:
            return int(key[1]) in legal
        except (TypeError, ValueError, IndexError):
            return False
    return False


def repair_action(key, legal: list[int], primitive: str, state: dict):
    """Keep a proposal only when it is legal. Otherwise substitute a legal pattern."""
    if action_legal(key, legal):
        return key, False
    for name in (primitive, "explore"):
        if name not in NAMES and name != "explore":
            continue
        alt = suggest_action(name if name in NAMES else "explore", legal, state)
        if action_legal(alt, legal):
            return alt, True
    for aid in legal:
        if aid in _REVERSE or aid == 5:
            return ("SIMPLE", int(aid)), True
    click = _click_at(state, "clickable", "switch", "reference", "receptor")
    if click is not None and 6 in legal:
        return click, True
    return None, True


def suggest_action(name: str, legal: list[int], state: dict):
    """An action id pattern. Explore is the only primitive that may leave the gradient."""
    progress = state.get("progress_axis")
    reverse = _REVERSE.get(progress)
    options = _dpad(legal)
    if name == "explore" and options and (state.get("hypothesis_target") or state.get("hypothesis_box")):
        aimed = step_toward("explore", legal, state)
        if aimed is not None:
            return ("SIMPLE", int(aimed))
    if name in ("approach", "convey", "route") and (state.get("step_target") or state.get("step_role")):
        aimed = step_toward(name, legal, state)
        if aimed is not None:
            return ("SIMPLE", int(aimed))
        return None
    if name in ("approach", "hold_gradient", "convey", "route"):
        if progress in options:
            return ("SIMPLE", int(progress))
        for aid in options:
            if aid != reverse:
                return ("SIMPLE", int(aid))
        if options:
            return ("SIMPLE", int(options[0]))
        return _click_at(state, "clickable", "switch", "reference")
    if name == "avoid":
        blocked = state.get("hazard_axis")
        for aid in options:
            if aid != blocked and aid != reverse:
                return ("SIMPLE", int(aid))
        if options:
            return ("SIMPLE", int(options[0]))
        return _click_at(state, "avatar", "clickable")
    if name in ("toggle", "cycle_select"):
        if 5 in legal and not state.get("step_role"):
            return ("SIMPLE", 5)
        active = state.get("active_anchor")
        if isinstance(active, (list, tuple)) and len(active) == 2 and 6 in legal:
            return ("CLICK", int(active[0]), int(active[1]))
        index = 0
        try:
            index = int(state.get("anchor_i") or 0)
        except (TypeError, ValueError):
            index = 0
        if index < 0:
            index = 0
        tried_pts = {
            (int(p[0]), int(p[1]))
            for p in (state.get("tried_anchors") or [])
            if isinstance(p, (list, tuple)) and len(p) == 2
        }
        aff = (state or {}).get("affordances") or {}
        roles = []
        if len(aff.get("clickable") or []) > len(aff.get("switch") or []):
            roles.append("clickable")
        for role in (state.get("step_role"), state.get("step_target"), "switch", "clickable"):
            if role and role not in roles and role != "none":
                roles.append(role)
        for role in roles:
            points = aff.get(role) or []
            if not isinstance(points, (list, tuple)):
                continue
            if tried_pts:
                avail = [
                    p
                    for p in points
                    if isinstance(p, (list, tuple)) and len(p) == 2 and (int(p[0]), int(p[1])) not in tried_pts
                ]
                if avail:
                    return ("CLICK", int(avail[0][0]), int(avail[0][1]))
                continue
            if index >= len(points):
                continue
            point = points[index]
            if isinstance(point, (list, tuple)) and len(point) == 2:
                return ("CLICK", int(point[0]), int(point[1]))
        if tried_pts:
            return None
        return _click_at(state, "switch", "clickable", "reference")
    if name in ("align", "assemble"):
        if progress in options:
            return ("SIMPLE", int(progress))
        if 5 in legal:
            return ("SIMPLE", 5)
        if options:
            return ("SIMPLE", int(options[0]))
        return _click_at(state, "clickable", "switch", "movable", "reference")
    if name == "explore":
        for aid in options:
            if aid != progress:
                return ("SIMPLE", int(aid))
        if 5 in legal:
            return ("SIMPLE", 5)
        return _click_at(state, "clickable", "switch", "reference", "avatar")
    return None


def _confidence(state: dict, name: str) -> float:
    table = state.get("primitive_confidence")
    if not isinstance(table, dict):
        return 1.0
    try:
        return float(table.get(name, 1.0))
    except (TypeError, ValueError):
        return 1.0


def applicable(obs: dict, state: dict, legal: list[int]) -> list[dict]:
    """Primitives whose precondition holds and whose confidence is still usable."""
    found = []
    for name in NAMES:
        if name == "explore":
            continue
        if not precondition(name, obs, state):
            continue
        if _confidence(state, name) < 0.25:
            continue
        action = suggest_action(name, legal, state)
        if action is None:
            continue
        from monad2.predicates import bind_predicate, render

        pred = bind_predicate(name, action, obs, None)
        found.append(
            {
                "id": name,
                "binding": _binding_text(name, obs),
                "effect": _EFFECT[name],
                "predicate": render(pred),
                "action": action,
                "confidence": _confidence(state, name),
            }
        )
    explore = suggest_action("explore", legal, state)
    found.append(
        {
            "id": "explore",
            "binding": "",
            "effect": _EFFECT["explore"],
            "action": explore,
            "confidence": _confidence(state, "explore"),
            "labeled": True,
        }
    )
    return found


def _binding_text(name: str, obs: dict) -> str:
    have = _roles(obs)
    picked = []
    for role in _BINDING.get(name, ()):
        if role in have:
            picked.append(role)
        elif role == "receptor" and "reference" in have:
            picked.append("reference")
        elif role == "avatar" and "clickable" in have and name in ("align", "toggle", "assemble"):
            picked.append("clickable")
        elif role == "goal" and "goal" in have:
            picked.append("goal")
    if name in ("toggle", "cycle_select", "align") and "clickable" in have and "clickable" not in picked:
        picked.insert(0, "clickable")
    return ",".join(picked or _BINDING.get(name, ()))


def line(items: list[dict]) -> str:
    parts = []
    for item in items:
        if item["id"] == "explore":
            continue
        parts.append(
            f"{item['id']} binds {item['binding'] or 'none'} "
            f"{item.get('predicate') or item['effect']} conf {item['confidence']:.1f}"
        )
    if not parts:
        return "no motion primitive yet; explore is the labeled fallback"
    return "; ".join(parts[:4])


def proposals_for(obs: dict, state: dict, legal: list[int]) -> tuple[str, list[dict]]:
    items = applicable(obs, state or {}, legal)
    return line(items), items


def contradicts_gradient(name: str, action, state: dict) -> bool:
    """True when a non-explore primitive would undo the last productive step."""
    if name == "explore":
        return False
    progress = state.get("progress_axis")
    if progress not in _REVERSE or not action:
        return False
    try:
        aid = int(action[1])
    except (TypeError, ValueError, IndexError):
        return False
    return aid == _REVERSE[progress]


def credit(state: dict, name: str, hit: bool | None, action=None) -> tuple[float, str]:
    """Raise or lower confidence from the expectation diff. Explore does not become a habit."""
    if name not in NAMES:
        return 0.0, "unchecked"
    table = state.get("primitive_confidence")
    if not isinstance(table, dict):
        table = {}
        state["primitive_confidence"] = table
    value = _confidence(state, name)
    if hit is True:
        value = min(3.0, value + 0.25)
        note = "confirmed"
        if name in ("approach", "convey", "route") and action and action[0] == "SIMPLE":
            try:
                aid = int(action[1])
            except (TypeError, ValueError, IndexError):
                aid = 0
            if aid in _REVERSE:
                state["progress_axis"] = aid
        if name == "avoid" and action and action[0] == "SIMPLE":
            state["hazard_axis"] = None
    elif hit is False:
        value = max(0.0, value - 0.5)
        note = "demoted"
        if name == "avoid" and action and action[0] == "SIMPLE":
            try:
                state["hazard_axis"] = int(action[1])
            except (TypeError, ValueError, IndexError):
                pass
        if name in ("approach", "convey", "route"):
            state["progress_axis"] = None
    else:
        note = "unchecked"
    table[name] = value
    return value, note


def known(name: str) -> bool:
    return name in NAMES


def effect_of(name: str) -> str:
    return _EFFECT.get(name, "")


def source_violations(path: Path | None = None) -> list[str]:
    """Fail on game ids, fingerprints, palette entries, or coordinates in this file."""
    from monad2.general_guard import KNOWN_GAME_PREFIXES

    src = path or Path(__file__)
    tree = ast.parse(src.read_text(encoding="utf-8"), filename=str(src))
    found = []
    banned_names = {
        "game_id",
        "fingerprint",
        "sig",
        "color",
        "fill_color",
        "palette",
        "coord",
        "click_x",
        "click_y",
    }
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            tokens = set(node.value.lower().replace(",", " ").split())
            hit = tokens & KNOWN_GAME_PREFIXES
            if node.value.lower() in KNOWN_GAME_PREFIXES:
                hit = set(hit)
                hit.add(node.value.lower())
            if hit:
                found.append(f"{src.name}:{node.lineno}: game id {sorted(hit)}")
        if isinstance(node, ast.Constant) and isinstance(node.value, int) and not isinstance(node.value, bool):
            if int(node.value) not in (0, 1, 2, 3, 4, 5, 6):
                found.append(f"{src.name}:{node.lineno}: literal {node.value}")
        if isinstance(node, ast.Name) and node.id.lower() in banned_names:
            found.append(f"{src.name}:{node.lineno}: name {node.id}")
    return found
