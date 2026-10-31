"""Holdout and LTP checks for structural memory. Does not require the 469-record corpus."""
from __future__ import annotations

from monad2.memory import EpisodeLTP, eligible, retrieve

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
    from monad2.memory import _features

    leaked = _features({"observation": "the goal is to reach and match"})
    assert "aff:avatar" not in leaked and "aff:panel" not in leaked
    ltp = EpisodeLTP()
    assert ltp.confirm("REACH") is False
    assert ltp.confirm("REACH") is True
    assert ltp.promoted() == ["REACH"]
    print("MEMORY HOLDOUT PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
