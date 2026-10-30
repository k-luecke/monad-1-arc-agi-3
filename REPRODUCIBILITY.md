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

To run all 25 official ARC-AGI-3 environments locally while isolating the environment inside a closure-backed `BlindEnvironmentProxy` (blocking any attribute inspection of `_game` / `game_id` and scrubbing `frame.game_id = "blind_unknown_env"` on every observation frame) and enforcing strict assertions (`25/25` games won, `183/183` levels completed, `6,444` total actions):

```bash
python run_competition_eval.py --offline --blind-id
```

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
