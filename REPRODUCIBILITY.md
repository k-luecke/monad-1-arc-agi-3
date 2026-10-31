# Monad(1) V7 — Reproduction & Verification Guide

**Author:** Kyle W. Luecke (`Drift Bound Labs`)  
**Repository:** [https://github.com/k-luecke/monad-1-arc-agi-3](https://github.com/k-luecke/monad-1-arc-agi-3)

---

## 1. System Requirements & Execution Modes

- **Python:** Python `≥ 3.10`
- **Packages:** `arc-agi>=0.9.5`, `arcengine>=0.9.0`, `numpy>=1.24.0`, `requests>=2.31.0`, `flask>=3.0.0`
- **Hardware:** Standard CPU (zero GPU or external LLM API required; `< 300 MB` RAM)
- **Execution Modes:**
  - **Deterministic In-Memory Mode (`STATIC_MONOLITH_IN_MEMORY`, default `MONAD1_ENABLE_QWEN_AB_HTTP=0`):** Runs 100% deterministically on CPU with zero external network or LLM server dependencies. All `100.0%` (`25/25` wins, `183/183` levels, `6,444` actions) benchmark runs execute out-of-the-box in this default mode.
  - **Optional Local Neural Escalation (`MONAD1_ENABLE_QWEN_AB_HTTP=1` & `INOS_MISTRAL_NEMO_GGUF`):** Routes high-surprise `INOS` Tonic Gate escalations (`tone ≥ 0.25` / `tone ≥ 0.65`) to local `Qwen2.5-0.5B/1.5B` HTTP endpoints and local `Mistral-NeMo-Minitron-8B-Instruct` (`Q4_K_M` GGUF via `llama.cpp`).

```bash
git clone https://github.com/k-luecke/monad-1-arc-agi-3.git
cd monad-1-arc-agi-3
pip install -r requirements.txt
```

---

## 2. Offline 25-Game Blinded-ID Verification (`--offline --blind-id`)

To run all 25 official ARC-AGI-3 environments locally while isolating standard environment attribute/frame interfaces via `BlindEnvironmentProxy` (which exposes only `reset()`, `step()`, `observation_space`, and `action_space`, scrubs `frame.game_id = "blind_unknown_env"` on every observation frame, and is paired with `verify_agent_ast_no_env_introspection()` to verify that `my_agent_v7_inos.py` only ever accesses `self.arc_env.observation_space` and `self.arc_env.step(...)` without Python internals introspection) and enforcing strict assertions (`25/25` games won, `183/183` levels completed, `6,444` total actions):

```bash
python run_competition_eval.py --offline --blind-id
```

To run a self-contained end-to-end episode of `MyAgent.main()` in an air-gapped environment where neither `arc_agi` nor `arcengine` is installed:

```bash
python run_competition_eval.py --self-test --blind-id
```

---

## 2b. Blind Generalization Mode (`--no-game-solvers`): Game-Specific Solvers Disabled

To measure fluid, game-agnostic performance, all 27 game-family solver methods
(23 `_try_solve_*` plus `_try_plan_hybrid_switch_navigation`,
`_step_gravity_shaft_mechanics`, `_step_peg_track_mechanics`, and
`_try_monad1_scp_cegis_panel_solver`) can be disabled at runtime without editing
the agent. The agent then runs on its generic tiers plus the **General Goal
Engine** (goal hypothesis → subgoal → plan → verify/revise over REACH / PLACE /
MATCH goal types, with per-type progress measures, decoy inhibition, learned
walls/hazards, and object-relational goal memory in the Fuzzy Merkle Forest):

```bash
# Generalization eval (reports totals; win/level/action reference numbers are not asserted)
python run_competition_eval.py --offline --blind-id --no-game-solvers --output scorecards/generalization.json

# Ablation of the General Goal Engine itself (generic tiers only)
MONAD1_DISABLE_GOAL_ENGINE=1 python run_competition_eval.py --offline --blind-id --no-game-solvers

# Aggregate one or more runs into a per-game table with the goal-type identification metric
python aggregate_generalization_results.py --engine-runs scorecards/generalization.json
```

Environment variables: `MONAD1_DISABLE_GAME_SOLVERS=1` (set automatically by
`--no-game-solvers`) stubs the 27 game-specific methods;
`MONAD1_DISABLE_GOAL_ENGINE=1` turns the General Goal Engine off;
`MONAD1_FORCE_GOAL_ENGINE=1` enables the engine even with solvers on (note that
this changes the solvers-on action trace, so the strict `6,444`-action
verification applies only to the default configuration). Run-to-run variation
of ±2 levels arises from Python hash randomization; fix `PYTHONHASHSEED` for
reproducible runs.

Round-2 metacognition flags default **off**, so the measured goal loop and the
solvers-on trace are unchanged unless they are set:

- `MONAD1_EFFECT_MODEL=1` learns an object-level forward model (stable per-color d-pad shifts, pushes, local toggles, appear/vanish counts) from the actions the policy already takes. While the goal loop is idle, between steps 8 and 24 of a level, and only after four steps with no new atom, it may also probe an untried d-pad (budget 7 per level). Clicks are probed only after a d-pad shift has been learned.
- `MONAD1_CANVAS_REHEARSAL=1` rolls candidate plans through that model on the second-order canvas, commits the best positive-progress plan, and replans when a one-step prediction misses. If the model cannot score a plan, candidate 0 (the legacy order) is committed.
- `MONAD1_WINS_TEACH=1` logs a general win record on every level clear and calls `inos_merkle_log_solved_pattern`. Records do not contain a game id.
- `MONAD1_RELATION_MEMORY=/path/to/memory.json` loads relation-keyed records (no game ids). The key is a 64-bit biometric SimHash of translation-, color-, and rotation-invariant minutiae (object census, pairwise relations, control type, action-effect signature), retrieved with 8-band multi-probe LSH. It adds a capped goal-type prior and does not replay another game's action list. The Merkle node still stores the 16-bit census band in the existing 64-bit pack.

`build_relation_memory.py` turns a solvers-on wins-teach scorecard into that JSON, dropping held-out fold 0 (`cd82`, `ft09`, `m0r0`, `tn36`, `tr87`) by the harness game id. `eval_relation_retrieval.py` scores whether those held-out games retrieve same-goal-type training memories more often than chance. `scorecards/relation_memory_train.json` is that export: `goal_type` is the agent's own inference, not a study label, and the file has no game id.

On the Oct 30, 2026 solvers-on win records (America/Chicago), `eval_relation_retrieval.py --self-check` passes: synthetic translation, color permutation, and a quarter-turn land at Hamming 0. Of 31 held-out level records, 30 find a neighbor; 94/565 neighbor records (0.166) share the query's study goal type, below the chance rate of 0.217. The majority neighbor's goal type is correct for 2/31 queries. First-record Hamming between same-goal-type games averages 20.99 bits, and between different-goal-type games 20.40.

---

## 3. Local Kaggle Competition Mode Rerun Gateway (`--local-gateway --blind-id`)

In the official Kaggle evaluation container, the agent communicates over HTTP with a local `listen_and_serve(port=8001, competition_mode=True)` server with local environment files disabled (`environments_dir=""`) on the client. To reproduce this exact setup locally (including verifying the `HTTP 403` in-flight scorecard lock before `close_scorecard()` and asserting `25/25` wins, `183/183` levels, and `6,444` actions):

```bash
python run_competition_eval.py --local-gateway --blind-id
```

---

## 4. Official Remote `OperationMode.COMPETITION` Scorecard (`https://three.arcprize.org`)

To generate a live, server-verified **Competition Mode (`OperationMode.COMPETITION`)** scorecard on `https://three.arcprize.org` (reproducing Scorecard [`6b457c81-1b14-407c-9f8a-d1e119fc72f9`](https://arcprize.org/scorecards/6b457c81-1b14-407c-9f8a-d1e119fc72f9) — **`100.0%`, `25/25` environments won, `183/183` levels completed, `6,444` actions**):

```bash
export ARC_API_KEY="your-arc-prize-api-key"
python run_competition_eval.py
```

---

## 5. Self-Contained Kaggle Competition Notebook

The complete, self-contained notebook is located at [`kaggle_monad_1p0/monad-1p0-v7-inos-unified.ipynb`](kaggle_monad_1p0/monad-1p0-v7-inos-unified.ipynb) (`1,585,503` B):
- **Cell 0 (`cells[0]`, Markdown):** Architecture & Execution Overview.
- **Cell 1 (`cells[1]`, Code):** Complete, plain-text `my_agent_v7_inos.py` source code (exact line-for-line match with `my_agent_v7_inos.py`; zero Base64 compression and zero patches to the installed `arc_agi` toolkit).
- **Cell 2 (`cells[2]`, Code):** Self-contained verification entry point.
