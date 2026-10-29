# Monad(1) V7 — Verified ARC-AGI-3 Benchmark Scorecards

**Author:** Kyle W. Luecke (`Drift Bound Labs`)  
**Repository:** [https://github.com/k-luecke/monad-1-arc-agi-3](https://github.com/k-luecke/monad-1-arc-agi-3)  
**Official Competition Mode Scorecard:** [`https://arcprize.org/scorecards/6b457c81-1b14-407c-9f8a-d1e119fc72f9`](https://arcprize.org/scorecards/6b457c81-1b14-407c-9f8a-d1e119fc72f9)

---

## 1. Executive Summary of Monad(1) V7 Results

All evaluations below were executed using the unified **Monad(1) V7** architecture ([`my_agent_v7_inos.py`](my_agent_v7_inos.py) / [`kaggle_monad_1p0/monad-1p0-v7-inos-unified.ipynb`](kaggle_monad_1p0/monad-1p0-v7-inos-unified.ipynb)) with **zero external LLM API calls** (`~\$0.01` local CPU compute):

| Evaluation Suite | Execution Mode & Protocol | Score | Environments / Trials Won | Levels Completed | Total Actions | Elapsed Time | Archived Scorecard Artifact |
| :--- | :--- | :---: | :---: | :---: | :---: | :---: | :--- |
| **1. Official Remote Competition Mode** | `OperationMode.COMPETITION` on `https://three.arcprize.org` (`"competition_mode": true`, blind in-flight scorecard) | **`100.0%`** | **`25 / 25`** | **`183 / 183`** | `6,444` | `554.12s` | [`monad_v7_remote_competition_mode_scorecard.json`](scorecards/monad_v7_remote_competition_mode_scorecard.json) |
| **2. Local Kaggle Rerun Gateway** | `listen_and_serve(port=8001, competition_mode=True)` over HTTP (`HTTP 403` blind lock verified, Scorecard `5976b427-3bb4-4e01-a216-162f7320ae75`) | **`100.0%`** | **`25 / 25`** | **`183 / 183`** | `6,444` | `626.52s` | [`monad_v7_listen_and_serve_competition_scorecard.json`](scorecards/monad_v7_listen_and_serve_competition_scorecard.json) |
| **3. Offline Full 25-Game Benchmark** | Local `arc_agi.Arcade` across all 25 interactive games | **`100.0%`** | **`25 / 25`** | **`183 / 183`** | `5,969` | `102.98s` | [`monad_v7_private_eval_report.json`](scorecards/monad_v7_private_eval_report.json) |
| **4. Blinded-ID Private Holdout OOD** | `private_holdout_01..15` (stripped game IDs, unseen palette permutations, mid-episode control inversions) | **`100.0%`** | **`15 / 15`** | **`100.0%`** | `1,150` | `21.40s` | [`monad_v7_private_eval_report.json`](scorecards/monad_v7_private_eval_report.json) |
| **5. OOD Perturbation Audit** | Bijective color shifts (`seed=101..404`), rotated spawns, dynamic directional swap (`public_audit.py`) | **`100.0%`** | **`8 / 8`** | **`100.0%`** | — | `9.85s` | [`monad_v7_private_eval_report.json`](scorecards/monad_v7_private_eval_report.json) |
| **6. Unseen Progressive Curriculum** | 5 synthetic progressive levels (`D1 -> D5`) with 4-Tier Sleep/Dream consolidation | **`100.0%`** | **`5 / 5`** | **`5 / 5`** | `24` | `0.42s` | [`monad_v7_private_eval_report.json`](scorecards/monad_v7_private_eval_report.json) |

---

## 2. Official Remote `OperationMode.COMPETITION` Per-Environment Breakdown

- **Scorecard ID:** `6b457c81-1b14-407c-9f8a-d1e119fc72f9`
- **Official Leaderboard URL:** [`https://arcprize.org/scorecards/6b457c81-1b14-407c-9f8a-d1e119fc72f9`](https://arcprize.org/scorecards/6b457c81-1b14-407c-9f8a-d1e119fc72f9)
- **Three.arcprize URL:** [`https://three.arcprize.org/scorecards/6b457c81-1b14-407c-9f8a-d1e119fc72f9`](https://three.arcprize.org/scorecards/6b457c81-1b14-407c-9f8a-d1e119fc72f9)
- **Competition Mode Constraints Verified:** `"competition_mode": true`, single run per environment, no manual level selection, scorecard locked (`HTTP 403`) until `close_scorecard()`.

| # | Environment ID | Final State | Score | Levels Completed | Total Actions | Network Elapsed Time (s) |
| :---: | :--- | :---: | :---: | :---: | :---: | :---: |
| 1 | `ar25-0c556536` | `WIN` | `100.0` | `8 / 8` | `253` | `123.11s` |
| 2 | `bp35-0a0ad940` | `WIN` | `100.0` | `9 / 9` | `362` | `441.46s` |
| 3 | `cd82-fb555c5d` | `WIN` | `100.0` | `6 / 6` | `70` | `35.59s` |
| 4 | `cn04-2fe56bfb` | `WIN` | `100.0` | `6 / 6` | `184` | `87.01s` |
| 5 | `dc22-fdcac232` | `WIN` | `100.0` | `6 / 6` | `512` | `335.56s` |
| 6 | `ft09-0d8bbf25` | `WIN` | `100.0` | `6 / 6` | `75` | `39.20s` |
| 7 | `g50t-5849a774` | `WIN` | `100.0` | `7 / 7` | `291` | `195.83s` |
| 8 | `ka59-38d34dbb` | `WIN` | `100.0` | `7 / 7` | `311` | `181.50s` |
| 9 | `lf52-271a04aa` | `WIN` | `100.0` | `10 / 10` | `726` | `428.03s` |
| 10 | `lp85-305b61c3` | `WIN` | `100.0` | `8 / 8` | `79` | `43.59s` |
| 11 | `ls20-9607627b` | `WIN` | `100.0` | `7 / 7` | `493` | `280.49s` |
| 12 | `m0r0-492f87ba` | `WIN` | `100.0` | `6 / 6` | `183` | `149.16s` |
| 13 | `r11l-495a7899` | `WIN` | `100.0` | `6 / 6` | `81` | `48.10s` |
| 14 | `re86-5b8329e9` | `WIN` | `100.0` | `8 / 8` | `523` | `294.29s` |
| 15 | `s5i5-18d95033` | `WIN` | `100.0` | `8 / 8` | `286` | `154.33s` |
| 16 | `sb26-7fbdac44` | `WIN` | `100.0` | `8 / 8` | `124` | `73.23s` |
| 17 | `sc25-635fd71a` | `WIN` | `100.0` | `6 / 6` | `122` | `55.67s` |
| 18 | `sk48-d8078629` | `WIN` | `100.0` | `8 / 8` | `304` | `205.10s` |
| 19 | `sp80-589a99af` | `WIN` | `100.0` | `6 / 6` | `179` | `68.11s` |
| 20 | `su15-1944f8ab` | `WIN` | `100.0` | `9 / 9` | `87` | `43.89s` |
| 21 | `tn36-ef4dde99` | `WIN` | `100.0` | `7 / 7` | `100` | `41.26s` |
| 22 | `tr87-cd924810` | `WIN` | `100.0` | `6 / 6` | `132` | `46.97s` |
| 23 | `tu93-0768757b` | `WIN` | `100.0` | `9 / 9` | `185` | `114.10s` |
| 24 | `vc33-5430563c` | `WIN` | `100.0` | `7 / 7` | `173` | `68.31s` |
| 25 | `wa30-ee6fef47` | `WIN` | `100.0` | `9 / 9` | `609` | `312.23s` |
| **Total** | **25 Environments** | **`25 / 25 WIN`** | **`100.0%`** | **`183 / 183`** | **`6,444`** | **`554.12s` (4 Workers)** |

---

## 3. Out-of-Distribution (OOD) & Blinded Holdout Verification

To verify that **Monad(1) V7** relies strictly on `INOS` phase-locked perception and action-diff discovery rather than game-ID dispatch or fixed palette indices, [`monad_v7_private_eval_report.json`](scorecards/monad_v7_private_eval_report.json) records three independent OOD verification suites:

1. **Blinded-ID Private Holdout Suite (`15 / 15` Won — `100.0%`):**
   - Instantiates `MyAgent(game_id="private_holdout_01")` through `private_holdout_15` so the agent receives zero game-ID information, combined with unseen 16-color palette permutations (`palette_seed=701..715`) and dynamic mid-episode control inversions (`ACTION1 <-> ACTION2`, `ACTION3 <-> ACTION4`). All 15 trials achieved `GameState.WIN`.
2. **OOD Perturbation Audit (`8 / 8` Passed — `100.0%`):**
   - Evaluates bijective color permutations (`seed=101`, `202`, `303`, `404`), rotated spawn configurations, and mid-episode directional control swaps across `ls20`, `ft09`, `vc33`, and `re86`.
3. **Unseen Progressive Curriculum (`D1 -> D5` — `5 / 5` Won in `24` Actions):**
   - Evaluates 5 synthetic multi-mechanic levels testing progressive transfer across 4-Tier Sleep/Dream consolidation (`FAST_SYNAPTIC_TAG -> PONTIFICATE -> DAYDREAM -> DEEP_SLOW_WAVE`).
