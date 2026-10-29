# Monad(1) V7 — Reproduction & Verification Guide

**Author:** Kyle W. Luecke (`Drift Bound Labs`)  
**Repository:** [https://github.com/k-luecke/monad-1-arc-agi-3](https://github.com/k-luecke/monad-1-arc-agi-3)

---

## 1. System Requirements

- **Python:** Python $\ge 3.10$
- **Packages:** `arc-agi>=0.9.5`, `arcengine>=0.9.0`, `numpy>=1.24.0`, `requests>=2.31.0`, `flask>=3.0.0`
- **Hardware:** Standard CPU (zero GPU or external LLM API required; `< 300 MB` RAM)

```bash
git clone https://github.com/k-luecke/monad-1-arc-agi-3.git
cd monad-1-arc-agi-3
pip install -r requirements.txt
```

---

## 2. Reproducing the Official Remote `OperationMode.COMPETITION` Scorecard

To generate a live, server-verified **Competition Mode (`OperationMode.COMPETITION`)** scorecard on `https://three.arcprize.org` (reproducing Scorecard [`6b457c81-1b14-407c-9f8a-d1e119fc72f9`](https://arcprize.org/scorecards/6b457c81-1b14-407c-9f8a-d1e119fc72f9) — **`100.0%`, `25/25` environments won, `183/183` levels completed**):

```bash
export ARC_API_KEY="your-arc-prize-api-key"
python run_competition_eval.py
```

When the run completes (`~9` minutes with 4 parallel workers), `run_competition_eval.py` closes the scorecard, prints the official `https://arcprize.org/scorecards/<card_id>` URL, and saves the full JSON receipt to `scorecards/latest_competition_scorecard.json`.

---

## 3. Reproducing the Local Kaggle Competition Mode Rerun Gateway (`listen_and_serve`)

In the official Kaggle evaluation container, the agent communicates over HTTP with a local `listen_and_serve(port=8001, competition_mode=True)` server with local environment files disabled (`environments_dir=""`) on the client. To reproduce this exact setup locally (reproducing [`scorecards/monad_v7_listen_and_serve_competition_scorecard.json`](scorecards/monad_v7_listen_and_serve_competition_scorecard.json)):

```bash
python run_competition_eval.py --local-gateway --environments-dir /path/to/environment_files
```

---

## 4. Running the Self-Contained Kaggle Competition Notebook

The complete, self-contained notebook is located at [`kaggle_monad_1p0/monad-1p0-v7-inos-unified.ipynb`](kaggle_monad_1p0/monad-1p0-v7-inos-unified.ipynb) (`566,577` B):
- **Cell 1:** Self-contained `MyAgent` (**Monad(1) V7**) implementation.
- **Cell 2:** Unseen `D1 -> D5` Progressive Curriculum & 4-Tier Sleep/Dream consolidation verification (`5/5` won in `24` actions).
- **Cell 3:** Automatic Competition Mode entry point (connects to `http://localhost:8001` inside the Kaggle rerun container or `https://three.arcprize.org` when `ARC_API_KEY` is provided).
