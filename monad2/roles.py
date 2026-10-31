"""Role binding from the live frame and from what actions just did.

What translates under a directional action is the avatar. What translates when
it was touching that avatar is movable. What changes under a click is a switch.
A region that ends or resets the level is a hazard. What blocks a step is a
wall. The goal stays unbound until a level completion names the object it
touched. A hypothesis is not a goal. A shape or fill match between a reference
and another region is the align relation. A geometry that matches more than
one object is not a binding.

Click games have no avatar. Their roles are the clickable objects and the
reference panel. Stored slots are geometry only: no palette entry, no
coordinate, no game id. Click anchors stay on the ephemeral affordance map.
"""
from __future__ import annotations

from monad2.schema import _bbox, _geom, _inside, _shape_name, _touch


def _area(rec: dict) -> int:
    try:
        return int(rec.get("area") or 0)
    except (TypeError, ValueError):
        return 0


def _fill(rec: dict):
    raw = rec.get("sig") or ()
    if len(raw) < 2:
        return None
    try:
        return int(raw[1])
    except (TypeError, ValueError):
        return None


def _span(records: list[dict], span: int | None) -> int:
    if span:
        try:
            return max(1, int(span))
        except (TypeError, ValueError):
            pass
    best = 1
    for rec in records or []:
        wh = rec.get("wh") or (0, 0)
        xy = rec.get("xy") or (0, 0)
        try:
            best = max(best, int(wh[0]), int(wh[1]), int(xy[0]) + int(wh[0]), int(xy[1]) + int(wh[1]))
        except (TypeError, ValueError):
            continue
    return best


def _has_dpad(legal: list[int] | None) -> bool:
    if not legal:
        return True
    return any(int(aid) in (1, 2, 3, 4) for aid in legal)


def _has_click(legal: list[int] | None) -> bool:
    return bool(legal) and any(int(aid) == 6 for aid in legal)


def _thin_wall(rec: dict, span: int) -> bool:
    geom = _geom(rec)
    if geom is None:
        return False
    short, long = int(geom[1]), int(geom[2])
    if long * 2 < span:
        return False
    if int(geom[0]) == 3:
        return True
    return short * 4 <= long


def _click_of(rec: dict):
    raw = rec.get("click")
    if isinstance(raw, (list, tuple)) and len(raw) == 2:
        return [int(raw[0]), int(raw[1])]
    xy = rec.get("xy")
    wh = rec.get("wh")
    if not xy or not wh:
        return None
    return [int(xy[0]) + int(wh[0]) // 2, int(xy[1]) + int(wh[1]) // 2]


def _add(roles: list[dict], taken: set[int], role: str, rec: dict | None, geom=None) -> None:
    if any(slot.get("role") == role for slot in roles):
        return
    slot: dict = {"role": role}
    if rec is not None:
        found = _geom(rec)
        if found is not None:
            slot["geom"] = [found[0], found[1], found[2]]
            slot["shape"] = _shape_name(found)
        taken.add(id(rec))
    elif geom is not None and len(geom) == 3:
        slot["geom"] = [int(geom[0]), int(geom[1]), int(geom[2])]
        slot["shape"] = _shape_name(slot["geom"])
    roles.append(slot)


def _find_geom(records: list[dict], geom, taken: set[int] | None = None):
    if not geom or len(geom) != 3:
        return None
    want = (int(geom[0]), int(geom[1]), int(geom[2]))
    for rec in records:
        if taken is not None and id(rec) in taken:
            continue
        if _geom(rec) == want:
            return rec
    return None


def _geom_counts(records: list[dict]) -> dict:
    counts: dict = {}
    for rec in records or []:
        geom = _geom(rec)
        if geom is None:
            continue
        counts[geom] = counts.get(geom, 0) + 1
    return counts


def _unique_geom(records: list[dict], geom) -> bool:
    if not geom or len(geom) != 3:
        return False
    want = (int(geom[0]), int(geom[1]), int(geom[2]))
    return _geom_counts(records).get(want, 0) == 1


def _largest_part(records: list[dict], geoms: list):
    """The biggest unique part of one shared motion. Not a smallest-mark prior."""
    best = None
    best_key = None
    for geom in geoms:
        rec = _find_geom(records, geom)
        wh = (rec or {}).get("wh") or (0, 0)
        try:
            area = int(wh[0]) * int(wh[1])
        except (TypeError, ValueError):
            area = 0
        key = (area, geom)
        if best_key is None or key > best_key:
            best_key = key
            best = geom
    return best


def _largest(records: list[dict], taken: set[int]) -> dict | None:
    pool = [rec for rec in records if id(rec) not in taken and _geom(rec) is not None]
    if not pool:
        return None
    pool.sort(key=lambda rec: (_area(rec), _geom(rec) or (0, 0, 0)))
    return pool[-1]


def infer_roles(
    records: list[dict],
    evidence: dict | None = None,
    legal: list[int] | None = None,
    span: int | None = None,
) -> dict:
    """Roles and relations for this frame. Affordances are not part of the schema."""
    recs = [rec for rec in records or [] if _geom(rec) is not None]
    evidence = evidence or {}
    width = _span(recs, span)
    dpad = _has_dpad(legal)
    click = _has_click(legal)
    roles: list[dict] = []
    taken: set[int] = set()

    for rec in recs:
        geom = _geom(rec)
        if geom is not None and int(geom[0]) == 2:
            _add(roles, taken, "receptor", rec)
            _add(roles, set(), "reference", rec)
            break
    evidence_wall = _find_geom(recs, evidence.get("wall"))
    if evidence_wall is not None:
        _add(roles, taken, "wall", evidence_wall)
    if not any(slot.get("role") == "wall" for slot in roles):
        walls = [rec for rec in recs if id(rec) not in taken and _thin_wall(rec, width)]
        walls.sort(key=lambda rec: _geom(rec)[2] if _geom(rec) else 0)
        if walls:
            _add(roles, taken, "wall", walls[-1])

    reference = next((rec for rec in recs if _geom(rec) and int(_geom(rec)[0]) == 2), None)
    if reference is None:
        containers = []
        for rec in recs:
            box = _bbox(rec)
            if box is None or id(rec) in taken:
                continue
            if any(_inside(_bbox(other), box) for other in recs if other is not rec and _bbox(other) is not None):
                containers.append(rec)
        if containers:
            containers.sort(key=_area)
            reference = containers[-1]
        else:
            ranked = sorted(recs, key=_area)
            if len(ranked) >= 2 and _area(ranked[-1]) >= _area(ranked[-2]) * 2 and _thin_wall(ranked[-1], width) is False:
                geom = _geom(ranked[-1])
                if geom is not None and int(geom[2]) * 2 >= width:
                    reference = ranked[-1]
            elif ranked and not dpad and click:
                reference = ranked[-1]
    if reference is not None and not any(slot.get("role") == "reference" for slot in roles):
        _add(roles, set(), "reference", reference)
        if id(reference) not in taken and not any(slot.get("role") == "receptor" for slot in roles):
            taken.add(id(reference))

    evidence_avatar = _find_geom(recs, evidence.get("avatar"), taken)
    if dpad and evidence_avatar is not None and _unique_geom(recs, evidence.get("avatar")):
        _add(roles, taken, "avatar", evidence_avatar)

    evidence_movable = _find_geom(recs, evidence.get("movable"), taken)
    if evidence_movable is not None and _unique_geom(recs, evidence.get("movable")):
        _add(roles, taken, "movable", evidence_movable)
    evidence_hazard = _find_geom(recs, evidence.get("hazard"), taken)
    if evidence_hazard is not None and _unique_geom(recs, evidence.get("hazard")):
        _add(roles, taken, "hazard", evidence_hazard)

    clickables = []
    if click or not dpad:
        for rec in recs:
            if id(rec) in taken:
                continue
            if reference is not None and rec is reference:
                continue
            if any(slot.get("role") == "wall" and slot.get("geom") == list(_geom(rec) or ()) for slot in roles):
                continue
            clickables.append(rec)
    if evidence.get("switch") and _unique_geom(recs, evidence.get("switch")):
        host = _find_geom(recs, evidence.get("switch"))
        if host is not None:
            _add(roles, set(), "switch", host)
            _add(roles, taken, "clickable", host)
    elif evidence.get("clickable") and _unique_geom(recs, evidence.get("clickable")):
        host = _find_geom(recs, evidence.get("clickable"))
        if host is not None:
            _add(roles, taken, "clickable", host)

    goal_rec = _find_geom(recs, evidence.get("goal"))
    if goal_rec is not None and _unique_geom(recs, evidence.get("goal")):
        _add(roles, set(), "goal", goal_rec)

    relations: list[dict] = []
    if evidence.get("avatar"):
        relations.append({"kind": "effect", "role": "avatar", "change": "translate"})
    if any(slot.get("role") == "switch" for slot in roles) and evidence.get("switch"):
        relations.append({"kind": "toggle", "role": "switch"})

    role_of: dict[int, str] = {}
    for slot in roles:
        geom = tuple(slot["geom"]) if slot.get("geom") else None
        if geom is None:
            continue
        for rec in recs:
            if _geom(rec) == geom and id(rec) not in role_of:
                role_of[id(rec)] = slot["role"]
                break
    for rec in clickables:
        role_of.setdefault(id(rec), "clickable")
    ids = [id(rec) for rec in recs]
    by_id = {id(rec): rec for rec in recs}
    for index, left_id in enumerate(ids):
        left_box = _bbox(by_id[left_id])
        left_role = role_of.get(left_id)
        if left_box is None or left_role is None:
            continue
        for right_id in ids[index + 1 :]:
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

    ref_slot = next((slot for slot in roles if slot.get("role") in ("reference", "receptor") and slot.get("geom")), None)
    if ref_slot is not None:
        ref_rec = _find_geom(recs, ref_slot.get("geom"))
        regions = []
        if ref_rec is not None:
            regions.append(ref_rec)
            ref_box = _bbox(ref_rec)
            for rec in recs:
                box = _bbox(rec)
                if rec is ref_rec or box is None or ref_box is None:
                    continue
                if _inside(box, ref_box) or _touch(box, ref_box):
                    regions.append(rec)
        for rec in recs:
            owner = role_of.get(id(rec))
            if not owner or owner in ("reference", "receptor", "goal", "wall"):
                continue
            geom = _geom(rec)
            if geom is None:
                continue
            for region in regions:
                rgeom = _geom(region)
                if rgeom is None:
                    continue
                same_shape = geom == rgeom
                same_fill = _fill(rec) is not None and _fill(rec) == _fill(region) and int(geom[0]) == int(rgeom[0])
                if same_shape or same_fill:
                    relations.append({"kind": "shape_match", "left": owner, "right": ref_slot["role"]})
                    break

    affordances: dict[str, list] = {}
    for slot in roles:
        geom = tuple(slot["geom"]) if slot.get("geom") else None
        if geom is None:
            continue
        points = []
        for rec in recs:
            if _geom(rec) == geom:
                point = _click_of(rec)
                if point is not None:
                    points.append(point)
        if points:
            affordances[slot["role"]] = points
    for rec in clickables:
        point = _click_of(rec)
        if point is None:
            continue
        affordances.setdefault("clickable", [])
        if point not in affordances["clickable"]:
            affordances["clickable"].append(point)

    names = [slot["role"] for slot in roles]
    return {
        "roles": roles,
        "relations": _unique(relations),
        "affordances": affordances,
        "line": ", ".join(names) if names else "none",
    }


def _unique(relations: list[dict]) -> list[dict]:
    seen = set()
    out = []
    for rel in relations:
        key = tuple(sorted((str(k), str(v)) for k, v in rel.items()))
        if key in seen:
            continue
        seen.add(key)
        out.append(rel)
    return out


def _deltas_of(before: list[dict], after: list[dict]) -> list[tuple[dict, int, int]]:
    from monad2.canvas_stream import diff_records

    diff = diff_records(before, after)
    found = []
    for move in diff.get("moved") or []:
        mark = tuple(move.get("sig") or ())
        for rec in before:
            if tuple(rec.get("sig") or ()) == mark:
                found.append((rec, int(move.get("dx") or 0), int(move.get("dy") or 0)))
                break
    return found


def _changed(before: list[dict], after: list[dict]) -> bool:
    from monad2.canvas_stream import diff_records

    diff = diff_records(before, after)
    return bool(diff.get("moved") or diff.get("vanished") or diff.get("appeared"))


def _clicked(records: list[dict], action) -> dict | None:
    if not action or action[0] != "CLICK" or len(action) < 3:
        return None
    try:
        x, y = int(action[1]), int(action[2])
    except (TypeError, ValueError):
        return None
    best = None
    best_d = None
    for rec in records:
        point = _click_of(rec)
        if point is None:
            continue
        dist = abs(point[0] - x) + abs(point[1] - y)
        if best_d is None or dist < best_d:
            best_d = dist
            best = rec
    return best


def _blocker(records: list[dict], avatar_geom, aid: int):
    avatar = _find_geom(records, avatar_geom)
    box = _bbox(avatar) if avatar is not None else None
    if box is None:
        return None
    ax, ay, aw, ah = box
    best = None
    best_gap = None
    for rec in records:
        if rec is avatar:
            continue
        other = _bbox(rec)
        if other is None:
            continue
        ox, oy, ow, oh = other
        gap = None
        if aid == 1 and oy + oh <= ay and ox < ax + aw and ox + ow > ax:
            gap = ay - (oy + oh)
        elif aid == 2 and oy >= ay + ah and ox < ax + aw and ox + ow > ax:
            gap = oy - (ay + ah)
        elif aid == 3 and ox + ow <= ax and oy < ay + ah and oy + oh > ay:
            gap = ax - (ox + ow)
        elif aid == 4 and ox >= ax + aw and oy < ay + ah and oy + oh > ay:
            gap = ox - (ax + aw)
        if gap is None:
            continue
        if best_gap is None or gap < best_gap:
            best_gap = gap
            best = _geom(rec)
    return best


def _touched(mover: dict, other: dict) -> bool:
    left = _bbox(mover)
    right = _bbox(other)
    if left is None or right is None:
        return False
    return _touch(left, right) or _inside(left, right) or _inside(right, left)


def note_effect(evidence: dict | None, before: list[dict], after: list[dict], action, outcome: str) -> dict:
    """Fold one action's document diff into role evidence. Geometry only."""
    kept = dict(evidence or {})
    moved = _deltas_of(list(before or []), list(after or []))
    kind = action[0] if action else ""
    counts = _geom_counts(list(before or []))
    if kind == "SIMPLE" and action and int(action[1]) in (1, 2, 3, 4):
        deltas = {}
        for rec, dx, dy in moved:
            geom = _geom(rec)
            if geom is None or geom in deltas or not (dx or dy):
                continue
            if counts.get(geom, 0) != 1:
                continue
            deltas[geom] = (int(dx), int(dy))
        geoms = list(deltas)
        known = tuple(kept["avatar"]) if kept.get("avatar") else None
        if known is not None and counts.get(known, 0) != 1:
            known = None
            kept.pop("avatar", None)
        avatar_geom = None
        if known is not None and known in geoms:
            avatar_geom = known
        elif len(geoms) == 1:
            avatar_geom = geoms[0]
        elif geoms and len(set(deltas.values())) == 1:
            # One motion split across colors. Each geom is still unique.
            avatar_geom = _largest_part(list(before or []), geoms)
        if avatar_geom is not None:
            kept["avatar"] = [avatar_geom[0], avatar_geom[1], avatar_geom[2]]
            for rec, _dx, _dy in moved:
                geom = _geom(rec)
                if geom is None or geom == avatar_geom or counts.get(geom, 0) != 1:
                    continue
                host = _find_geom(before, avatar_geom)
                if host is not None and _touched(host, rec):
                    kept["movable"] = [geom[0], geom[1], geom[2]]
                    break
        if not geoms and kept.get("avatar"):
            wall = _blocker(list(before or []), kept.get("avatar"), int(action[1]))
            if wall is not None and _unique_geom(list(before or []), wall):
                kept["wall"] = [wall[0], wall[1], wall[2]]
    if kind == "CLICK":
        target = _clicked(list(before or []), action)
        geom = _geom(target) if target is not None else None
        changed = _changed(list(before or []), list(after or []))
        if geom is not None and changed and counts.get(geom, 0) == 1:
            kept["switch"] = [geom[0], geom[1], geom[2]]
            kept["clickable"] = [geom[0], geom[1], geom[2]]
    if outcome == "reset":
        hazard = kept.get("avatar") or kept.get("switch") or kept.get("clickable")
        if hazard and _geom_counts(list(before or [])).get(tuple(int(v) for v in hazard), 0) <= 1:
            kept["hazard"] = list(hazard)
    if outcome == "completed":
        after_counts = _geom_counts(list(after or before or []))
        for key in ("movable", "avatar", "switch", "clickable"):
            goal = kept.get(key)
            if not goal or len(goal) != 3:
                continue
            want = (int(goal[0]), int(goal[1]), int(goal[2]))
            seen = after_counts.get(want, counts.get(want, 0))
            if seen <= 1:
                kept["goal"] = [want[0], want[1], want[2]]
                break
    return kept
