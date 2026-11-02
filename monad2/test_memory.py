"""Holdout and LTP checks for structural memory. Does not require the 469-record corpus."""
from __future__ import annotations

from monad2.memory import EpisodeLTP, eligible, retrieve, retrieve_unhashed, unhash_record

RECORDS = [
    {
        "record_kind": "dream_schema",
        "observation": "SCHEMA_REMOTE_AFFORDANCE",
        "hypothesis": "remote affordance, the avatar moves to the distant object",
        "inferred_goal": "REACH",
    },
    {"kind": "SCHEMA_PANEL", "text": "panel pair", "goal_type": "MATCH"},
    {
        "record_kind": "assistant_thought",
        "game_id": "ft09-0d8bbf25",
        "game_ids": ["ft09", "sb26"],
        "observation": "debug ft09 clicks",
        "inferred_goal": "MATCH",
    },
    {"kind": "trace", "observation": "working on cd82 panels", "goal_type": "MATCH"},
    {"kind": "trace", "game_id": "sc25-635fd71a", "text": "avatar in a corridor", "goal_type": "REACH"},
    {"kind": "trace", "text": "push the block into the hole", "goal_type": "PLACE"},
    {
        "record_kind": "dream_schema",
        "observation": "remote trigger switch unlocks the gate corridor for the avatar",
        "inferred_goal": "ACTIVATE",
    },
]


def main() -> int:
    kept = eligible(RECORDS, "ft09")
    blob = " ".join(str(r) for r in kept).lower()
    assert "ft09" not in blob
    kept_cd = eligible(RECORDS, "cd82")
    assert all("cd82" not in str(r).lower() for r in kept_cd)
    # SCHEMA records are listed before traces. Goal words are not features.
    assert kept[0].get("record_kind") == "dream_schema" or str(kept[0].get("kind", "")).startswith("SCHEMA")
    hyp = retrieve(("aff:avatar", "aff:remote"), kept, k=2)
    assert hyp and hyp[0] == "REACH", hyp
    unhashed_rec = unhash_record(RECORDS[-1])
    assert unhashed_rec["goal"] == "REACH", unhashed_rec
    assert "toggle" in unhashed_rec["primitives"], unhashed_rec
    assert "switch->barrier:toggle(switch)->approach(avatar,goal)" in unhashed_rec["role_bindings"], unhashed_rec
    assert unhashed_rec["candidate_priority"] == "SWITCH_FIRST", unhashed_rec
    unhashed = retrieve_unhashed(("aff:avatar", "aff:remote", "aff:switch"), kept, k=4)
    assert "REACH" in unhashed["goals"], unhashed
    assert "approach" in unhashed["primitives"], unhashed
    assert "toggle" in unhashed["primitives"], unhashed
    assert "switch->barrier:toggle(switch)->approach(avatar,goal)" in unhashed["role_bindings"], unhashed
    assert unhashed["candidate_priority"] == "SWITCH_FIRST", unhashed
    assert "ft09" not in str(unhashed).lower()
    from monad2.memory import _features

    leaked = _features({"observation": "the goal is to reach and match"})
    assert "aff:avatar" not in leaked and "aff:panel" not in leaked
    ltp = EpisodeLTP()
    assert ltp.confirm("REACH") is False
    assert ltp.confirm("REACH") is True
    assert ltp.promoted() == ["REACH"]
    from monad2.memory import unhash_packed_node

    packed_prim08 = (0xF0000000 << 32) | (8 << 16) | 0x0800
    dec08 = unhash_packed_node(packed_prim08, relational_sig16=0x5000)
    assert dec08["parent_primitive_id"] == "PRIM_08_DEMONSTRATION_PANEL_CEGIS_SYNTHESIS", dec08
    assert dec08["candidate_bias"] == "match_panel", dec08
    assert "MATCH" in dec08["endorsed_goals"], dec08
    assert "align" in dec08["recommended_primitives"] and "toggle" in dec08["recommended_primitives"], dec08
    assert dec08["decoded_board_relations"]["has_pointer"] is True, dec08
    assert dec08["decoded_board_relations"]["has_panel_pair"] is True, dec08

    from my_agent_v7_inos import MonadAssociativeMerkleTree

    mtree = MonadAssociativeMerkleTree()
    dec08_tree = unhash_packed_node(packed_prim08, tree=mtree, relational_sig16=0x5000)
    assert dec08_tree["parent_primitive_id"] == "PRIM_08_DEMONSTRATION_PANEL_CEGIS_SYNTHESIS", dec08_tree
    assert dec08_tree["candidate_bias"] == "match_panel", dec08_tree
    assert "MATCH" in dec08_tree["endorsed_goals"], dec08_tree
    assert "align" in dec08_tree["recommended_primitives"], dec08_tree
    print("MEMORY HOLDOUT PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

