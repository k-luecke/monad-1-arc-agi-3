# Monad(2) scorecard

Fresh ledger. Earlier Monad(1) totals are not entries here. The machine-readable log is `scorecard.jsonl` (one JSON object per line).

Primary metric: blind levels (`--offline --blind-id --no-game-solvers`) at no more actions than the previous best. Solvers-on is a regression check that the per-game solvers still solve every game.

Every entry records America/Chicago time, commit, flags, seeds, per-game time limit, wins/25, levels/183, actions, levels per 1,000 actions, the gap item under test, and whether that item's test passed.

`PYTHONHASHSEED` is fixed per seed. Game order is the harness default (sorted prefixes) unless the entry names a permutation.
