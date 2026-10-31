"""Holdout and LTP checks for structural memory. Does not require the 469-record corpus."""
from __future__ import annotations

from monad2.memory import EpisodeLTP, eligible, retrieve

RECORDS = [
    {"kind": "SCHEMA_REMOTE_AFFORDANCE", "text": "remote affordance, reach the distant object", "goal_type": "REACH"},
    {"kind": "SCHEMA_PANEL", "text": "panel match", "goal_type": "MATCH"},
    {"kind": "trace", "game_id": "ft09-0d8bbf25", "text": "debug ft09 match clicks", "goal_type": "MATCH"},
    {"kind": "trace", "text": "working on cd82 panels", "goal_type": "MATCH"},
    {"kind": "trace", "game_id": "sc25-635fd71a", "text": "avatar reach", "goal_type": "REACH"},
    {"kind": "trace", "text": "push the block into the hole", "goal_type": "PLACE"},
]


def main() -> int:
    kept = eligible(RECORDS, "ft09")
    blob = " ".join(str(r) for r in kept).lower()
    assert "ft09" not in blob
    kept_cd = eligible(RECORDS, "cd82")
    assert all("cd82" not in str(r).lower() for r in kept_cd)
    # SCHEMA records are listed before traces.
    assert str(kept[0].get("kind", "")).startswith("SCHEMA")
    hyp = retrieve(("aff:avatar", "aff:remote"), kept, k=2)
    assert hyp and hyp[0] == "REACH"
    ltp = EpisodeLTP()
    assert ltp.confirm("REACH") is False
    assert ltp.confirm("REACH") is True
    assert ltp.promoted() == ["REACH"]
    print("MEMORY HOLDOUT PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
