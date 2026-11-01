"""Role inference, legal-action repair, and predicate checks."""
from __future__ import annotations

from monad2.predicates import bind_predicate, evaluate, render
from monad2.primitives import action_legal, repair_action, suggest_action
from monad2.roles import infer_roles, note_effect
from monad2.schema import _permute, _records_from_grid, _rot90, assert_structure


def _blank(size=16):
    return [[0] * size for _ in range(size)]


def _paint(grid, color, cells):
    for row, col in cells:
        grid[row][col] = color


def _rect(row, col, height, width):
    return [(row + dr, col + dc) for dr in range(height) for dc in range(width)]


def _names(result):
    return {slot["role"] for slot in result["roles"]}


def _geom(result, role):
    for slot in result["roles"]:
        if slot["role"] == role and slot.get("geom"):
            return tuple(slot["geom"])
    return None


def _click_scene():
    grid = _blank()
    # Hollow reference panel and two clickable objects, one sharing the swatch fill.
    for row in range(2, 11):
        for col in range(2, 12):
            if row in (2, 10) or col in (2, 11):
                grid[row][col] = 1
    _paint(grid, 2, _rect(4, 4, 2, 2))
    _paint(grid, 2, _rect(12, 12, 2, 2))
    _paint(grid, 3, _rect(12, 3, 2, 2))
    return grid


def _dpad_scene():
    grid = _blank()
    for col in range(16):
        grid[1][col] = 3
    _paint(grid, 4, _rect(8, 4, 2, 2))
    for row in range(12, 16):
        for col in range(12, 16):
            if row in (12, 15) or col in (12, 15):
                grid[row][col] = 5
    return grid


def _shift_avatar(grid):
    out = [list(row) for row in grid]
    for row in range(len(out)):
        for col in range(len(out[0])):
            if out[row][col] == 4:
                out[row][col] = 0
    _paint(out, 4, _rect(8, 6, 2, 2))
    return out


def _same_roles(grid, legal):
    records = _records_from_grid(grid)
    span = max(len(grid), len(grid[0]))
    base = infer_roles(records, {}, legal, span)
    turned = _permute(_rot90(grid))
    other = infer_roles(_records_from_grid(turned), {}, legal, max(len(turned), len(turned[0])))
    assert _names(base) == _names(other), (_names(base), _names(other))
    for role in _names(base):
        assert _geom(base, role) == _geom(other, role), role
    body = {"roles": base["roles"], "relations": base["relations"]}
    assert_structure(body)
    assert "click" not in body
    return base


def main() -> int:
    click = _same_roles(_click_scene(), [6])
    assert "reference" in _names(click) or "receptor" in _names(click)
    assert "avatar" not in _names(click)
    assert "goal" not in _names(click)
    assert "clickable" not in _names(click)
    assert click["affordances"].get("clickable")

    dpad = _same_roles(_dpad_scene(), [1, 2, 3, 4, 5])
    assert "avatar" not in _names(dpad)
    assert "goal" not in _names(dpad)
    assert "wall" in _names(dpad)
    assert "receptor" in _names(dpad) or "reference" in _names(dpad)

    before = _records_from_grid(_dpad_scene())
    after = _records_from_grid(_shift_avatar(_dpad_scene()))
    evidence = note_effect({}, before, after, ("SIMPLE", 4), "continue")
    assert evidence.get("avatar"), evidence
    learned = infer_roles(after, evidence, [1, 2, 3, 4, 5], 16)
    assert _geom(learned, "avatar") == tuple(evidence["avatar"])

    blocked = note_effect({"avatar": evidence["avatar"]}, before, before, ("SIMPLE", 1), "continue")
    assert blocked.get("wall"), blocked

    pushed = [dict(rec) for rec in before]
    # A second shape beside the avatar translates with it: that one was touched.
    box = {"sig": (1, 8, 3, 2), "geom": (1, 2, 3), "xy": (6, 8), "wh": (3, 2), "area": 6, "click": (7, 9), "type": 1}
    pushed.append(box)
    moved_box = dict(box)
    moved_box["xy"] = (8, 8)
    moved_box["click"] = (9, 9)
    after_push = [dict(rec) for rec in after] + [moved_box]
    # The avatar record in `after` already shifted. The box started touching x=6 next to avatar x=4,w=2.
    touched = note_effect({"avatar": evidence["avatar"]}, pushed, after_push, ("SIMPLE", 4), "continue")
    assert touched.get("movable"), touched
    same_a = {"sig": (1, 4, 2, 2), "geom": (1, 2, 2), "xy": (1, 1), "wh": (2, 2), "area": 4, "click": (2, 2), "type": 1}
    same_b = {"sig": (1, 7, 2, 2), "geom": (1, 2, 2), "xy": (6, 1), "wh": (2, 2), "area": 4, "click": (7, 2), "type": 1}
    same_b_moved = dict(same_b)
    same_b_moved["xy"] = (7, 1)
    crowded = note_effect({}, [same_a, same_b], [same_a, same_b_moved], ("SIMPLE", 4), "continue")
    assert not crowded.get("avatar"), crowded
    part_a = {"sig": (1, 9, 5, 3), "geom": (1, 3, 5), "xy": (4, 4), "wh": (5, 3), "area": 15, "click": (6, 5), "type": 1}
    part_b = {"sig": (1, 12, 5, 2), "geom": (1, 2, 5), "xy": (4, 2), "wh": (5, 2), "area": 10, "click": (6, 3), "type": 1}
    part_a2 = dict(part_a)
    part_a2["xy"] = (4, 3)
    part_a2["click"] = (6, 4)
    part_b2 = dict(part_b)
    part_b2["xy"] = (4, 1)
    part_b2["click"] = (6, 2)
    together = note_effect({}, [part_a, part_b], [part_a2, part_b2], ("SIMPLE", 1), "continue")
    assert together.get("avatar") == [1, 3, 5], together
    part_b3 = dict(part_b)
    part_b3["xy"] = (6, 2)
    part_b3["click"] = (8, 3)
    split = note_effect({}, [part_a, part_b], [part_a2, part_b3], ("SIMPLE", 1), "continue")
    assert not split.get("avatar"), split

    clicked_before = _records_from_grid(_click_scene())
    clicked_after = [dict(rec) for rec in clicked_before]
    for rec in clicked_after:
        if rec.get("xy") == (12, 12) or (rec.get("xy") and rec["xy"][0] >= 12 and rec.get("sig") and rec["sig"][1] == 2):
            rec["xy"] = (rec["xy"][0], rec["xy"][1] + 1)
            break
    else:
        clicked_after.append(
            {"sig": (4, 9, 1, 1), "geom": (4, 1, 1), "xy": (1, 1), "wh": (1, 1), "area": 1, "click": (1, 1), "type": 4}
        )
    point = None
    for rec in clicked_before:
        if rec.get("xy") and rec["xy"][0] >= 12 and rec.get("sig") and rec["sig"][1] == 2:
            point = rec.get("click") or rec["xy"]
            break
    assert point is not None
    shared = note_effect({}, clicked_before, clicked_after, ("CLICK", point[0], point[1]), "continue")
    assert not shared.get("switch"), shared
    lone_before = [
        {"sig": (4, 9, 1, 1), "geom": (4, 1, 1), "xy": (3, 3), "wh": (1, 1), "area": 1, "click": (3, 3), "type": 4},
    ]
    lone_after = [
        {"sig": (4, 9, 1, 1), "geom": (4, 1, 1), "xy": (3, 4), "wh": (1, 1), "area": 1, "click": (3, 4), "type": 4},
    ]
    switched = note_effect({}, lone_before, lone_after, ("CLICK", 3, 3), "continue")
    assert switched.get("switch"), switched
    twin_before = lone_before + [
        {"sig": (4, 8, 1, 1), "geom": (4, 1, 1), "xy": (8, 8), "wh": (1, 1), "area": 1, "click": (8, 8), "type": 4},
    ]
    twin_after = [
        {"sig": (4, 9, 1, 1), "geom": (4, 1, 1), "xy": (3, 5), "wh": (1, 1), "area": 1, "click": (3, 5), "type": 4},
        twin_before[1],
    ]
    ambiguous = note_effect({}, twin_before, twin_after, ("CLICK", 3, 3), "continue")
    assert not ambiguous.get("switch"), ambiguous

    ended = note_effect(dict(switched), clicked_before, clicked_before, ("CLICK", point[0], point[1]), "reset")
    assert ended.get("hazard"), ended
    done = note_effect(dict(evidence), before, after, ("SIMPLE", 4), "completed")
    assert done.get("goal"), done

    state = {"affordances": click["affordances"], "progress_axis": None}
    illegal = ("SIMPLE", 3)
    assert not action_legal(illegal, [6])
    repaired, changed = repair_action(illegal, [6], "align", state)
    assert changed and repaired[0] == "CLICK", repaired
    assert action_legal(repaired, [6])
    assert suggest_action("toggle", [6], state)[0] == "CLICK"

    avatar = _geom(learned, "avatar")
    still = [rec for rec in before if tuple(rec.get("geom") or ()) == avatar]
    pred = {
        "kind": "translate",
        "role": "avatar",
        "role_b": "goal",
        "dir": "left",
        "axis": "none",
        "geom": list(avatar),
        "geom_b": list(_geom(learned, "receptor") or avatar),
    }
    assert evaluate(pred, still, still) is False
    moved = [dict(rec) for rec in still]
    moved[0]["xy"] = (int(moved[0]["xy"][0]) - 2, int(moved[0]["xy"][1]))
    assert evaluate(pred, still, moved) is True
    pred["dir"] = "right"
    assert evaluate(pred, still, moved) is False
    assert render(pred) == "translate(role=avatar, dir=right)"

    bound = bind_predicate("hold_gradient", ("SIMPLE", 4), {"roles": learned["roles"]}, {})
    assert bound["kind"] == "no_reverse" and bound["dir"] == "right" and bound["axis"] == "x"
    assert evaluate(bound, still, moved) is False
    assert evaluate(bound, still, still) is True

    click_recs = _records_from_grid(_click_scene())
    obj_rec = next(rec for rec in click_recs if rec.get("geom") and int(rec["geom"][0]) != 2)
    ref_rec = next(rec for rec in click_recs if rec.get("geom") and int(rec["geom"][0]) == 2)
    same = {
        "kind": "match",
        "role": "clickable",
        "role_b": "reference",
        "dir": "none",
        "axis": "none",
        "geom": list(obj_rec["geom"]),
        "geom_b": list(ref_rec["geom"]),
    }
    # A clickable whose geometry differs from the reference fails the match.
    if tuple(same["geom"]) != tuple(same["geom_b"]):
        fills_differ = True
        obj = next(rec for rec in click_recs if tuple(rec["geom"]) == tuple(same["geom"]))
        ref = next(rec for rec in click_recs if tuple(rec["geom"]) == tuple(same["geom_b"]))
        fills_differ = not (len(obj["sig"]) > 1 and len(ref["sig"]) > 1 and obj["sig"][1] == ref["sig"][1] and obj["geom"][0] == ref["geom"][0])
        if fills_differ:
            assert evaluate(same, click_recs, click_recs) is False
    wrong = dict(same)
    wrong["geom"] = [4, 1, 1]
    wrong["geom_b"] = [1, 2, 6]
    lone = [
        {"sig": (4, 9, 1, 1), "geom": (4, 1, 1), "xy": (1, 1), "wh": (1, 1), "area": 1, "type": 4},
        {"sig": (1, 3, 6, 2), "geom": (1, 2, 6), "xy": (4, 4), "wh": (6, 2), "area": 12, "type": 1},
    ]
    assert evaluate(wrong, lone, lone) is False
    print("ROLES PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
