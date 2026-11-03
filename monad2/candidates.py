"""General candidate enumeration and direction probing without per-game priors.

Enumerates REACH (unique non-avatar, non-wall, non-hazard shapes), PLACE
(movable shapes paired with hollow containers), and MATCH (equal-size regions
whose contents differ) from the raw document records. Orders candidates by
confirmed goal geom transfer first, then watch leader, then D4- and
palette-invariant geometry.
"""
from __future__ import annotations

from monad2.primitives import blocked_dirs
from monad2.roles import _click_of, _geom_counts, _span, _thin_wall, infer_roles
from monad2.schema import _bbox, _geom, _inside


def scope_records(
    records: list[dict],
    role_evidence: dict | list | None = None,
    playfield_box: tuple[int, int, int, int] | int | None = None,
    mover_box: tuple[int, int, int, int] | None = None,
) -> tuple[list[dict], tuple[int, int, int, int] | None]:
    """Scope records to the container holding the mover and drop interior ornaments of other boxes."""
    recs = [rec for rec in (records or []) if _geom(rec) is not None and _bbox(rec) is not None]
    if not recs:
        return [], (playfield_box if isinstance(playfield_box, tuple) else None)
    span_val = int(playfield_box) if isinstance(playfield_box, int) else _span(recs, None)
    pbox = playfield_box if isinstance(playfield_box, tuple) and len(playfield_box) == 4 else None
    if isinstance(role_evidence, list):
        evidence = {
            str(slot.get("role")): slot.get("geom")
            for slot in role_evidence
            if isinstance(slot, dict) and slot.get("role") and slot.get("geom")
        }
    else:
        evidence = role_evidence or {}
    resolved_mover = None
    avatar_geom = evidence.get("avatar")
    if avatar_geom and len(avatar_geom) == 3:
        want = (int(avatar_geom[0]), int(avatar_geom[1]), int(avatar_geom[2]))
        matches = [rec for rec in recs if _geom(rec) == want]
        if len(matches) == 1:
            resolved_mover = _bbox(matches[0])
    if resolved_mover is None and isinstance(mover_box, (list, tuple)) and len(mover_box) == 4:
        resolved_mover = (int(mover_box[0]), int(mover_box[1]), int(mover_box[2]), int(mover_box[3]))
    mover_box = resolved_mover

    container_box = None
    other_containers: list[tuple[int, int, int, int]] = []
    for rec in recs:
        box = _bbox(rec)
        if box is None or box == mover_box:
            continue
        if box[2] <= 1 and box[3] <= 1:
            continue
        inners = [
            other
            for other in recs
            if _bbox(other) is not None and _bbox(other) != box and _inside(_bbox(other), box)
        ]
        if not inners:
            continue
        if mover_box is not None and _inside(mover_box, box):
            if len(inners) >= 2 and box[2] * box[3] * 4 >= span_val * span_val:
                if container_box is None or (box[2] * box[3]) > (container_box[2] * container_box[3]):
                    container_box = box
        elif box[2] * box[3] * 2 < span_val * span_val:
            g_rec = _geom(rec)
            if g_rec is not None and (int(g_rec[0]) in (1, 2) or (pbox is not None and not _inside(box, pbox))):
                other_containers.append(box)

    if container_box is not None and pbox is not None:
        cx, cy, cw, ch = container_box
        px, py, pw, ph = pbox
        if px <= cx and py <= cy and px + pw >= cx + cw and py + ph >= cy + ch:
            container_box = pbox
    elif container_box is None and pbox is not None:
        if mover_box is None or _inside(mover_box, pbox):
            container_box = pbox

    pool = recs
    if container_box is not None:
        inside_pool = [
            rec
            for rec in recs
            if _bbox(rec) is not None and _bbox(rec) != container_box and _inside(_bbox(rec), container_box)
        ]
        if inside_pool:
            pool = inside_pool

    if other_containers:
        filtered = [
            rec
            for rec in pool
            if not any(_bbox(rec) != cbox and _inside(_bbox(rec), cbox) for cbox in other_containers)
        ]
        if filtered:
            pool = filtered

    return pool, container_box


def _norm_geom(geom) -> tuple[int, int, int] | None:
    if not geom or len(geom) != 3:
        return None
    try:
        return (int(geom[0]), int(geom[1]), int(geom[2]))
    except (TypeError, ValueError):
        return None


def _kind_order(leader_goal: str | None) -> dict[str, int]:
    base = ["REACH", "PLACE", "MATCH", "CLICK"]
    if leader_goal in ("REACH", "PLACE", "MATCH"):
        base.remove(leader_goal)
        base.insert(0, leader_goal)
    return {name: idx for idx, name in enumerate(base)}


def _stored_goal_geom() -> tuple[int, int, int] | None:
    from monad2.schema import STORE

    for row in reversed(STORE):
        for slot in row.get("roles") or []:
            if slot.get("role") == "goal" and slot.get("geom") and len(slot["geom"]) == 3:
                return _norm_geom(slot["geom"])
    return None


def enumerate_candidates(
    records: list[dict],
    role_evidence: dict | list | None = None,
    leader_goal: str | dict | None = None,
    legal: list[int] | str | None = None,
    affordances: dict | None = None,
    refuted: list | None = None,
    deferred: list | None = None,
    preferred_geom=None,
    playfield_box: tuple[int, int, int, int] | None = None,
    state: dict | None = None,
    span: int | None = None,
) -> list[dict]:
    """Return live candidate objects ordered by transfer geom, watch leader, and invariant geometry."""
    roles_list: list[dict] = []
    if isinstance(role_evidence, list):
        roles_list = list(role_evidence)
        if isinstance(leader_goal, dict):
            evidence = leader_goal
            leader_goal = legal if isinstance(legal, str) else "REACH"
            legal = affordances if isinstance(affordances, list) else None
            affordances = None
        else:
            evidence = {
                str(slot.get("role")): slot.get("geom")
                for slot in roles_list
                if isinstance(slot, dict) and slot.get("role") and slot.get("geom")
            }
    else:
        evidence = role_evidence or {}
        if isinstance(state, dict):
            roles_list = list(((state.get("schema_obs") or {}).get("roles")) or [])
    if evidence.get("goal"):
        return []
    mover_box = None
    movable_box = None
    moving_boxes: set[tuple[int, int, int, int]] = set()
    if isinstance(state, dict):
        mb = state.get("mover_box")
        if isinstance(mb, (list, tuple)) and len(mb) == 4:
            mover_box = (int(mb[0]), int(mb[1]), int(mb[2]), int(mb[3]))
            moving_boxes.add(mover_box)
        mvb = state.get("movable_box")
        if isinstance(mvb, (list, tuple)) and len(mvb) == 4:
            movable_box = (int(mvb[0]), int(mvb[1]), int(mvb[2]), int(mvb[3]))
            moving_boxes.add(movable_box)
        for mbox in state.get("moving_boxes") or []:
            if isinstance(mbox, (list, tuple)) and len(mbox) == 4:
                moving_boxes.add((int(mbox[0]), int(mbox[1]), int(mbox[2]), int(mbox[3])))
    if mover_box is None and isinstance(evidence, dict):
        mb = evidence.get("mover_box")
        if isinstance(mb, (list, tuple)) and len(mb) == 4:
            mover_box = (int(mb[0]), int(mb[1]), int(mb[2]), int(mb[3]))
            moving_boxes.add(mover_box)
    if movable_box is None and isinstance(evidence, dict):
        mvb = evidence.get("movable_box")
        if isinstance(mvb, (list, tuple)) and len(mvb) == 4:
            movable_box = (int(mvb[0]), int(mvb[1]), int(mvb[2]), int(mvb[3]))
            moving_boxes.add(movable_box)
    if playfield_box is None and isinstance(state, dict):
        pbox = state.get("playfield_box")
        if isinstance(pbox, (list, tuple)) and len(pbox) == 4:
            playfield_box = (int(pbox[0]), int(pbox[1]), int(pbox[2]), int(pbox[3]))
    scoped, cbox = scope_records(
        records,
        evidence,
        playfield_box if playfield_box is not None else span,
        mover_box=mover_box,
    )
    if isinstance(state, dict) and cbox is not None:
        state["playfield_box"] = cbox
    if not scoped:
        return []
    width = _span(records or scoped, span)
    counts = _geom_counts(scoped)
    def _in_moving(b: tuple[int, int, int, int] | None) -> bool:
        return b is not None and (b in moving_boxes or any(_inside(b, mb) for mb in moving_boxes))

    non_mover_counts = (
        _geom_counts([r for r in scoped if not _in_moving(_bbox(r))])
        if moving_boxes
        else counts
    )
    moving_geoms = {
        _geom(r) for r in scoped if _in_moving(_bbox(r)) and _geom(r) is not None
    }

    excluded: set[tuple[int, int, int]] = set()
    for role_key in ("avatar", "movable", "wall", "hazard"):
        g = _norm_geom(evidence.get(role_key))
        if g is not None:
            excluded.add(g)
    for part in evidence.get("avatar_parts") or []:
        g = _norm_geom(part)
        if g is not None:
            excluded.add(g)
    for slot in roles_list:
        if isinstance(slot, dict) and slot.get("role") == "reference":
            g = _norm_geom(slot.get("geom"))
            if g is not None and int(g[0]) != 2 and g not in moving_geoms:
                excluded.add(g)
    for rec in scoped:
        g = _geom(rec)
        if g is not None and _thin_wall(rec, width):
            excluded.add(g)

    refuted_set: set[tuple[int, int, int]] = set()
    for item in refuted or []:
        g = _norm_geom(item)
        if g is not None:
            refuted_set.add(g)

    deferred_set: set[tuple[int, int, int]] = set()
    for item in deferred or []:
        g = _norm_geom(item)
        if g is not None:
            deferred_set.add(g)

    pref = _norm_geom(preferred_geom or evidence.get("preferred_goal") or _stored_goal_geom())
    ranks = _kind_order(leader_goal)

    sig_counts: dict[tuple, int] = {}
    for rec in scoped:
        if _in_moving(_bbox(rec)):
            continue
        g = _geom(rec)
        sig = rec.get("sig") or ()
        if g is not None and len(sig) > 1:
            key = (g, int(sig[1]))
            sig_counts[key] = sig_counts.get(key, 0) + 1

    legal_list = [int(a) for a in (legal or []) if int(a) != 0]
    click_only = 6 in legal_list and not any(a in (1, 2, 3, 4) for a in legal_list)

    def _extract_dpad_candidates(pool_recs: list[dict]) -> tuple[list[dict], list[dict], list[dict]]:
        p_counts = _geom_counts(pool_recs)
        p_non_mover = (
            _geom_counts([r for r in pool_recs if not _in_moving(_bbox(r))])
            if moving_boxes
            else p_counts
        )
        p_excluded = set(excluded)
        for rec in pool_recs:
            g = _geom(rec)
            if g is not None and _thin_wall(rec, width):
                p_excluded.add(g)
        p_sig_counts: dict[tuple, int] = {}
        p_fill_counts: dict[int, int] = {}
        for rec in pool_recs:
            if _in_moving(_bbox(rec)):
                continue
            g = _geom(rec)
            sig = rec.get("sig") or ()
            if len(sig) > 1:
                f_val = int(sig[1])
                p_fill_counts[f_val] = p_fill_counts.get(f_val, 0) + 1
                if g is not None:
                    key = (g, f_val)
                    p_sig_counts[key] = p_sig_counts.get(key, 0) + 1

        # 1. REACH: unique non-avatar, non-wall, non-hazard solid shapes (never hollow type-2)
        r_items: list[dict] = []
        if not click_only:
            raw_reach: list[tuple[tuple[int, int, int], tuple[int, int, int, int]]] = []
            for rec in pool_recs:
                g = _geom(rec)
                box = _bbox(rec)
                if g is None or box is None:
                    continue
                if _in_moving(box) or box == cbox:
                    continue
                is_hud_pickup = (
                    int(g[0]) == 2
                    and box[2] * box[3] <= 25
                    and isinstance(state, dict)
                    and bool(state.get("hud_changed"))
                )
                if p_non_mover.get(g, 0) != 1 and not is_hud_pickup:
                    continue
                if g in p_excluded or g in refuted_set:
                    continue
                if (int(g[0]) == 2 and not is_hud_pickup) or box[2] * box[3] > 100 or box[2] * box[3] * 2 >= width * width:
                    continue
                raw_reach.append((g, box))

            if mover_box is not None and len(raw_reach) > 1:
                mcx = mover_box[0] + mover_box[2] // 2
                mcy = mover_box[1] + mover_box[3] // 2
                raw_reach.sort(
                    key=lambda gb: (
                        gb[0],
                        abs((gb[1][0] + gb[1][2] // 2) - mcx) + abs((gb[1][1] + gb[1][3] // 2) - mcy),
                    )
                )

            if not any(int(g[0]) == 1 for g, _ in raw_reach) or (
                pref is not None and int(pref[0]) == 1 and not any(g == pref for g, _ in raw_reach)
            ):
                for rec in pool_recs:
                    g = _geom(rec)
                    box = _bbox(rec)
                    sig = rec.get("sig") or ()
                    if g is None or box is None or int(g[0]) != 1 or len(sig) < 2:
                        continue
                    if _in_moving(box) or box == cbox:
                        continue
                    if p_sig_counts.get((g, int(sig[1])), 0) != 1:
                        continue
                    singletons = sum(1 for (gg, _f), cnt in p_sig_counts.items() if gg == g and cnt == 1)
                    has_tile_bg = any(cnt >= 2 for (gg, _f), cnt in p_sig_counts.items() if gg == g)
                    if not has_tile_bg:
                        continue
                    if singletons != 1:
                        unique_fill_singletons = sum(
                            1
                            for (gg, _f), cnt in p_sig_counts.items()
                            if gg == g and cnt == 1 and p_fill_counts.get(_f, 0) == 1
                        )
                        if unique_fill_singletons != 1 or p_fill_counts.get(int(sig[1]), 0) != 1:
                            continue
                    if g in p_excluded or g in refuted_set:
                        continue
                    if box[2] * box[3] > 100 or box[2] * box[3] * 2 >= width * width:
                        continue
                    if (g, box) not in raw_reach:
                        raw_reach.append((g, box))

            # Suppress internal ornament shapes inside a rectangular candidate, and drop floor/border sprites enclosing another candidate
            for g, box in raw_reach:
                if any(other_box != box and int(_og[0]) in (1, 2) and _inside(box, other_box) for _og, other_box in raw_reach):
                    continue
                if int(g[0]) in (5, 6) and any(other_box != box and _inside(other_box, box) for _og, other_box in raw_reach):
                    continue
                r_items.append({"kind": "REACH", "geom": [g[0], g[1], g[2]], "box": box})

        # 2. PLACE: pairs movable with a static unique geom of the same shape, or with a unique hollow container
        pl_items: list[dict] = []
        movable_geom = _norm_geom(evidence.get("movable"))
        if movable_geom is None and movable_box is not None:
            for rec in pool_recs:
                if _bbox(rec) == movable_box and _geom(rec) is not None:
                    movable_geom = _geom(rec)
                    break
        if not click_only and movable_geom is not None:
            for rec in pool_recs:
                g = _geom(rec)
                box = _bbox(rec)
                if g is None or box is None:
                    continue
                if _in_moving(box) or box == cbox:
                    continue
                if p_non_mover.get(g, 0) != 1 or g in p_excluded or g in refuted_set:
                    continue
                if int(g[0]) == 2 or int(g[0]) == int(movable_geom[0]):
                    pl_items.append(
                        {
                            "kind": "PLACE",
                            "geom": [g[0], g[1], g[2]],
                            "box": box,
                            "mover_geom": [movable_geom[0], movable_geom[1], movable_geom[2]],
                        }
                    )

        # 3. MATCH: equal-dimension regions whose type/fill differs (no stored color)
        m_items: list[dict] = []
        if not click_only:
            seen_match: set[tuple[int, int, int]] = set()
            for i, rec_a in enumerate(pool_recs):
                ga = _geom(rec_a)
                box_a = _bbox(rec_a)
                if ga is None or box_a is None or ga in p_excluded or ga in refuted_set:
                    continue
                if _in_moving(box_a) or box_a == cbox or p_non_mover.get(ga, 0) != 1:
                    continue
                for rec_b in pool_recs[i + 1 :]:
                    gb = _geom(rec_b)
                    box_b = _bbox(rec_b)
                    if gb is None or box_b is None or gb in p_excluded:
                        continue
                    if _in_moving(box_b) or box_b == cbox:
                        continue
                    if (int(ga[1]), int(ga[2])) != (int(gb[1]), int(gb[2])):
                        continue
                    sig_a = rec_a.get("sig") or ()
                    sig_b = rec_b.get("sig") or ()
                    if ga != gb or (len(sig_a) > 1 and len(sig_b) > 1 and sig_a[1] != sig_b[1]):
                        if ga not in seen_match:
                            seen_match.add(ga)
                            m_items.append(
                                {
                                    "kind": "MATCH",
                                    "geom": [ga[0], ga[1], ga[2]],
                                    "box": box_a,
                                    "ref_geom": [gb[0], gb[1], gb[2]],
                                }
                            )
        return r_items, pl_items, m_items

    reach_items, place_items, match_items = _extract_dpad_candidates(scoped)

    # 4. Click-only and hybrid blocked-D-pad CLICK candidates: yield affordances["clickable"] one anchor at a time
    click_items: list[dict] = []
    dpad_set = {a for a in legal_list if a in (1, 2, 3, 4)}
    blocked_at_mover: set[int] = set()
    if mover_box is not None and isinstance(state, dict):
        for edge in (state.get("route_blocks") or []) + (state.get("conditional_blocks") or []):
            if isinstance(edge, (list, tuple)) and len(edge) == 3:
                if int(edge[0]) == mover_box[0] and int(edge[1]) == mover_box[1]:
                    blocked_at_mover.add(int(edge[2]))
    hybrid_click_needed = (
        6 in legal_list
        and not click_only
        and bool(dpad_set)
        and dpad_set <= blocked_at_mover
    )
    if click_only or hybrid_click_needed:
        full_recs = list(records or scoped)
        sw_geom = _norm_geom(evidence.get("switch"))
        full_counts = _geom_counts(full_recs)
        if sw_geom is not None and full_counts.get(sw_geom, 0) == 1 and sw_geom not in refuted_set:
            for rec in full_recs:
                if _geom(rec) == sw_geom and _bbox(rec) is not None and _bbox(rec) not in moving_boxes:
                    click_items.append(
                        {
                            "kind": "CLICK",
                            "geom": [sw_geom[0], sw_geom[1], sw_geom[2]],
                            "box": _bbox(rec),
                            "anchor": _click_of(rec),
                            "_order": -1,
                        }
                    )
                    break
        aff_map = affordances
        if not isinstance(aff_map, dict) and isinstance(state, dict):
            aff_map = state.get("affordances")
        if not isinstance(aff_map, dict) or "clickable" not in aff_map:
            aff_map = infer_roles(full_recs, evidence, legal_list, width).get("affordances") or {}
        for idx, anchor in enumerate(aff_map.get("clickable") or []):
            if not isinstance(anchor, (list, tuple)) or len(anchor) != 2:
                continue
            target_xy = [int(anchor[0]), int(anchor[1])]
            for rec in full_recs:
                g = _geom(rec)
                box = _bbox(rec)
                if g is None or box is None or g in refuted_set:
                    continue
                if not click_only and (box in moving_boxes or box == cbox or g in excluded):
                    continue
                if _click_of(rec) == target_xy:
                    click_items.append(
                        {
                            "kind": "CLICK",
                            "geom": [g[0], g[1], g[2]],
                            "box": box,
                            "anchor": target_xy,
                            "_order": idx,
                        }
                    )
                    break

    all_items = reach_items + place_items + match_items + click_items
    # Deduplicate by (kind, anchor) for CLICK and (kind, geom) for non-CLICK while keeping deterministic order
    deduped: list[dict] = []
    seen_keys: set[tuple] = set()
    for item in all_items:
        g = _norm_geom(item.get("geom"))
        if g is None:
            continue
        if item.get("kind") == "CLICK" and isinstance(item.get("anchor"), (list, tuple)) and len(item["anchor"]) == 2:
            key: tuple = ("CLICK", (int(item["anchor"][0]), int(item["anchor"][1])))
        else:
            key = (str(item["kind"]), g)
        if key in seen_keys:
            continue
        seen_keys.add(key)
        if pref is not None and g == pref:
            item["confirmed_goal"] = True
        deduped.append(item)

    hud_metered = isinstance(state, dict) and bool(state.get("hud_changed")) and mover_box is not None
    unrefuted_done = isinstance(state, dict) and int(state.get("unrefuted_passes") or 0) > 0

    def _sort_key(item: dict):
        g = _norm_geom(item.get("geom")) or (99, 99, 99)
        is_def = 1 if g in deferred_set else 0
        is_not_pref = 0 if (pref is not None and g == pref and (not hud_metered or unrefuted_done)) else 1
        k_rank = ranks.get(str(item.get("kind")), 9)
        order_idx = int(item.get("_order", 0)) if item.get("kind") == "CLICK" else 0
        dist_rank = 0
        if hud_metered and mover_box is not None and item.get("kind") == "REACH":
            bx = item.get("box")
            if isinstance(bx, (list, tuple)) and len(bx) == 4:
                dist_rank = abs((int(bx[0]) + int(bx[2]) // 2) - (mover_box[0] + mover_box[2] // 2)) + abs(
                    (int(bx[1]) + int(bx[3]) // 2) - (mover_box[1] + mover_box[3] // 2)
                )
        return (is_def, is_not_pref, k_rank, dist_rank, order_idx, g)

    deduped.sort(key=_sort_key)
    for item in deduped:
        item.pop("_order", None)
    return deduped


def next_direction_probe(
    state: dict | list,
    legal: list[int] | dict | None,
    dead_actions: set | None = None,
) -> tuple[str, int] | None:
    """Return the next untried legal d-pad direction before avatar is bound."""
    if isinstance(state, (list, tuple)) and isinstance(legal, dict):
        state, legal = legal, list(state)
    if not isinstance(state, dict):
        return None
    obs = state.get("schema_obs")
    if isinstance(obs, dict) and obs.get("roles") is not None:
        has_avatar = any(slot.get("role") == "avatar" for slot in (obs.get("roles") or []) if isinstance(slot, dict))
    else:
        has_avatar = bool((state.get("role_evidence") or {}).get("avatar"))
    if has_avatar or state.get("mover_box"):
        return None
    dpad = [int(a) for a in (legal or []) if int(a) in (1, 2, 3, 4)]
    if not dpad:
        return None
    probed = {int(a) for a in (state.get("probed_dirs") or []) if int(a) in (1, 2, 3, 4)}
    blocked = blocked_dirs(state)
    dead = set()
    for act in dead_actions or ():
        if isinstance(act, (list, tuple)) and len(act) >= 2 and act[0] == "SIMPLE":
            try:
                dead.add(int(act[1]))
            except (TypeError, ValueError):
                continue
    for aid in dpad:
        if aid in probed or aid in blocked or aid in dead:
            continue
        state.setdefault("probed_dirs", []).append(aid)
        return ("SIMPLE", aid)
    return None
