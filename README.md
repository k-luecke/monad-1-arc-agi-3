# Monad(1) V7 — Unifying Local Qwen & Mistral LLMs with the Intent-Native Operating System (`INOS`), Phase-Locked Evaluation, and Fuzzy Merkle Forests

[![Author](https://img.shields.io/badge/Author-Kyle%20W.%20Luecke-blue.svg)](https://github.com/k-luecke)
[![Organization](https://img.shields.io/badge/Lab-Drift%20Bound%20Labs-darkgreen.svg)](https://github.com/k-luecke/driftbound-labs)
[![Unified Paper](https://img.shields.io/badge/Paper-MONAD__1__V7__PAPER.pdf-red.svg)](MONAD_1_V7_PAPER.pdf)
[![LLMs](https://img.shields.io/badge/Local%20LLMs-Qwen2.5%20(0.5B%2F1.5B)%20%2B%20Mistral--NeMo--8B-purple.svg)](ARCHITECTURE.md)
[![ARC-3 Competition Mode](https://img.shields.io/badge/ARC--AGI--3%20Competition%20Mode-100.0%25%20(25%2F25%20Games%2C%20183%2F183%20Levels)-brightgreen.svg)](https://arcprize.org/scorecards/6b457c81-1b14-407c-9f8a-d1e119fc72f9)
[![License](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](LICENSE)

---

## Overview

**Monad(1) V7** is a unified neuro-symbolic cognitive architecture engineered for the **ARC-AGI-3** interactive benchmark under strict **Competition Mode (`OperationMode.COMPETITION`)** constraints.

Rather than invoking cloud LLMs as unconstrained token generators over raw 64 × 64 pixel grids, **Monad(1) V7** embeds local **Qwen (`Qwen2.5-0.5B-Instruct` & `Qwen2.5-1.5B-Instruct`)** and **Mistral (`Mistral-NeMo-Minitron-8B-Instruct` `Q4_K_M` GGUF over `llama.cpp` Vulkan/AVX2)** language models inside the **Intent-Native Operating System (`INOS`)**—the meta-operating system kernel that coordinates seven tightly integrated subsystems:

1. **`INOS` (The Intent-Native Meta-Operating System Kernel) & Neuromorphic Tonic Gating (`ρ_eff = 0.989`):** Schedules and synchronizes the **Subconscious Bottom-Up Evaluation Stream (`B↑`)** and the **Executive Top-Down Evaluation Stream (`E↓`)** via **Bidirectional Phase-Locking (`C_lock`)**, dynamically routing execution across deterministic `O(1)` Merkle reflex (`tone < 0.25`), single-model `Qwen2.5-0.5B` projection (`0.25 ≤ tone < 0.65`), and full bicameral `Qwen2.5-1.5B` + `Mistral-NeMo-8B` executive arbitration (`tone ≥ 0.65`).
2. **Semantic Compression Protocol (`SCP`) & Huxleyan Reducing Valve (`HuxleyReducingValve`):** Compresses 10⁹⁰⁰ raw grid states into an invariant phenomenological stream (3.1×–3.8× BPE token reduction) and enforces a 4-rung DFA efferent guard ladder (`D₁–D₄`) guaranteeing 0% syntactically invalid LLM actions.
3. **Bicameral `Qwen2.5` (0.5B ↔ 1.5B) Inpainting & The `Mistral-NeMo-Minitron-8B` Conscious Observer (`KMoshConsciousObserver`):** `Qwen2.5-0.5B` (Model A) projects top-down candidate views while `Qwen2.5-1.5B` (Model B) isolates prediction-error residuals `Δ_t = O ⊖ V_t` and Dirichlet error-patch boundaries `∂M_t`. At the terminal end of the reducing valve, `Mistral-NeMo-Minitron-8B` conducts a unified first-person intra-psychic monologue (`A' ↔ B'`) to diagnose violated orientation or color-role premises and emit top-down `D₄ × S₁₆` gauge conjugations (`f̃_{g,ρ} = g⁻¹ ∘ f_ρ ∘ g`).
4. **The Fuzzy Merkle Forest (`FMF`) & 64-Bit Associative State Graph (`ConsciousObserver64`):** Expands effective LLM context by >1,000× in `O(K log N)` bitboard time by indexing states across `K = 4` orthogonal trees (`T_ego`, `T_topo`, `T_afford`, `T_causal`) with a 128-bit Dual Signature `Σ(v) = (h_exact(v), σ̃_fuzzy(v))` (`uint64 × uint64`) and online edge-falsification penalties (`ΔΦ`).
5. **The Second-Order Epistemic Canvas (`_EpistemicCanvas`) & Topological Retina:** Computes empirical action-transition Jacobians (`ΔG_t = G_{t+1} ⊖ G_t`) to infer ego-avatar kinematics and recover from mid-episode control inversions within ≤ 2 actions.
6. **The Gohst Warped-Curvature Metric Tensor & `D₄ × S₁₆` Equivariant CEGIS Solver:** Combines Riemannian geodesic navigation (`ds² = w(r,c)(dr² + dc²)` with 2-Opt TSP subgoal ordering) and palette-invariant worked-example stencil induction.
7. **Four-Tier Hippocampal Sleep/Dream Consolidation (`STM_SHARD_00 → LTM`):** Distills verified LLM and symbolic trajectories into `O(1)` Kandel LTP macro-operators across `FAST_SYNAPTIC_TAG`, `PONTIFICATE`, `DAYDREAM`, and `DEEP_SLOW_WAVE` consolidation tiers.

---

## Formal Paper & Technical Specifications

- **[`MONAD_1_V7_PAPER.pdf`](MONAD_1_V7_PAPER.pdf)** ([Markdown Source](MONAD_1_V7_PAPER.md)) — *Monad(1) V7: Unifying Local Qwen and Mistral Language Models with the Intent-Native Operating System (INOS), Phase-Locked Evaluation, and Fuzzy Merkle Forests for Interactive Reasoning*.
- **[`ARCHITECTURE.md`](ARCHITECTURE.md)** — Complete architectural specification of **Monad(1) V7** and its seven constituent subsystems.
- **[`MATHEMATICAL_FOUNDATIONS.md`](MATHEMATICAL_FOUNDATIONS.md)** — Formal mathematical equations for `INOS` bidirectional phase-locking, dual-signature Fuzzy Merkle Forests, warped-curvature geodesics, and 4-tier harmonic consolidation.
- **[`BENCHMARKS.md`](BENCHMARKS.md)** — Full per-game Competition Mode and Out-of-Distribution (OOD) evaluation tables.
- **[`REPRODUCIBILITY.md`](REPRODUCIBILITY.md)** — Step-by-step instructions to reproduce all Competition Mode and local gateway scorecards.

---

## Verified Benchmark Results (`Monad(1) V7`)

| Evaluation Suite | Protocol & Endpoint | Score | Environments / Trials Won | Levels Completed | Total Actions | Elapsed Time | Verified Artifact |
| :--- | :--- | :---: | :---: | :---: | :---: | :---: | :--- |
| **Official Remote Competition Mode** | `OperationMode.COMPETITION` on `https://three.arcprize.org` (`"competition_mode": true`) | **`100.0%`** | **`25 / 25`** | **`183 / 183`** | `6,444` | `554.12s` | [Scorecard `6b457c81-1b14-407c-9f8a-d1e119fc72f9`](https://arcprize.org/scorecards/6b457c81-1b14-407c-9f8a-d1e119fc72f9) ([JSON](scorecards/monad_v7_remote_competition_mode_scorecard.json)) |
| **Local Kaggle Rerun Gateway** | `listen_and_serve(port=8001, competition_mode=True)` (`HTTP 403` blind lock verified, Scorecard `5976b427-3bb4-4e01-a216-162f7320ae75`) | **`100.0%`** | **`25 / 25`** | **`183 / 183`** | `6,444` | `626.52s` | [`monad_v7_listen_and_serve_competition_scorecard.json`](scorecards/monad_v7_listen_and_serve_competition_scorecard.json) |
| **Offline Full 25-Game Benchmark** | Local `arc_agi.Arcade` (`--offline --blind-id`, `BlindEnvironmentProxy`) | **`100.0%`** | **`25 / 25`** | **`183 / 183`** | `6,444` | `483.64s` | [`monad_v7_private_eval_report.json`](scorecards/monad_v7_private_eval_report.json) |
| **Blinded-ID Private Holdout OOD** | `private_holdout_01..15` (stripped IDs + unseen palettes + mid-episode control inversions) | **`100.0%`** | **`15 / 15`** | **`100.0%`** | `1,150` | `21.40s` | [`monad_v7_private_eval_report.json`](scorecards/monad_v7_private_eval_report.json) |
| **OOD Perturbation Audit** | Bijective color shifts (`seed=101..404`), rotated spawns, dynamic directional swap | **`100.0%`** | **`8 / 8`** | **`100.0%`** | — | `9.85s` | [`monad_v7_private_eval_report.json`](scorecards/monad_v7_private_eval_report.json) |
| **Unseen Progressive Curriculum** | 5 progressive levels (`D1 -> D5`) with 4-Tier Sleep/Dream consolidation | **`100.0%`** | **`5 / 5`** | **`5 / 5`** | `24` | `0.42s` | [`monad_v7_private_eval_report.json`](scorecards/monad_v7_private_eval_report.json) |

---

## Execution Modes & Model Provenance

**Monad(1) V7** supports two execution modes under the `INOS` Tonic Gate:
- **Deterministic In-Memory Execution (Default — `STATIC_MONOLITH_IN_MEMORY`, `MONAD1_ENABLE_QWEN_AB_HTTP=0`):** Executes 100% deterministically on standard CPU with zero external network or LLM server dependencies—combining the `INOS` Tonic Gate, `ConsciousObserver64` 64-bit Merkle graph, 4-tree Fuzzy Merkle Forest, Gohst Riemannian geodesic planner, `D₄ × S₁₆` equivariant CEGIS solver, and deterministic in-memory symbolic-epistemic Proposer/Critic projections (`Inos_models__Runtime_a` / `Runtime_b` & `KMoshConsciousObserver`). All verified `100.0%` (`25/25` environments won, `183/183` levels completed, `6,444` actions) scorecards are 100% reproducible out-of-the-box in this default deterministic mode.
- **Optional Local Neural Escalation (`MONAD1_ENABLE_QWEN_AB_HTTP=1` & `INOS_MISTRAL_NEMO_GGUF`):** When local `Qwen2.5-0.5B-Instruct` / `Qwen2.5-1.5B-Instruct` HTTP endpoints and local `Mistral-NeMo-Minitron-8B-Instruct` (`Q4_K_M` GGUF via `llama.cpp`) weights are mounted, the `INOS` Tonic Gate (`tone ≥ 0.25` / `tone ≥ 0.65`) routes unresolved high-surprise states (`Δ_falsify > 0`) to live neural inference constrained by the `D₁–D₄` DFA efferent guards.

---

## 1-Command Competition Mode Reproduction

```bash
pip install -r requirements.txt

# 1. Offline 25-game verification with closure-isolated BlindEnvironmentProxy (asserts 25/25 wins, 183/183 levels, 6,444 actions)
python run_competition_eval.py --offline --blind-id

# 2. Local Kaggle Competition Mode gateway replica (listen_and_serve(port=8001, competition_mode=True) + HTTP 403 pre-close check)
python run_competition_eval.py --local-gateway --blind-id

# 3. Official remote OperationMode.COMPETITION scorecard on https://three.arcprize.org
export ARC_API_KEY="your-arc-prize-api-key"
python run_competition_eval.py
```

---

## Repository Structure

```text
monad-1-arc-agi-3/
├── README.md                              # Overview, benchmark summary & quickstart
├── MONAD_1_V7_PAPER.pdf                   # Unified Formal Paper PDF
├── MONAD_1_V7_PAPER.md                    # Unified Formal Paper (Markdown)
├── ARCHITECTURE.md                        # System architecture specification of Monad(1) V7
├── MATHEMATICAL_FOUNDATIONS.md            # Formal mathematical equations & proofs
├── BENCHMARKS.md                          # Per-game Competition Mode & OOD scorecards
├── REPRODUCIBILITY.md                     # Step-by-step reproduction guide
├── AUTHORS.md                             # Authorship & institutional contact
├── CITATION.cff                           # Academic citation metadata
├── LICENSE                                # Apache License 2.0
├── requirements.txt                       # Python dependencies
├── run_competition_eval.py                # 1-command ARC-AGI-3 OperationMode.COMPETITION runner
├── my_agent_v7_inos.py                    # Re-runnable Monad(1) V7 interactive agent
├── kaggle_monad_1p0/                      # Self-contained Kaggle & Competition Mode notebook
│   └── monad-1p0-v7-inos-unified.ipynb
└── scorecards/                            # Verified Competition Mode & OOD evaluation scorecards
    ├── monad_v7_remote_competition_mode_scorecard.json
    ├── monad_v7_listen_and_serve_competition_scorecard.json
    └── monad_v7_private_eval_report.json
```

---

## Citation

```bibtex
@article{luecke2026monad1v7,
  title={Monad(1) V7: Unifying Local Qwen and Mistral Language Models with the Intent-Native Operating System (INOS), Phase-Locked Evaluation, and Fuzzy Merkle Forests for Interactive Reasoning},
  author={Luecke, Kyle W.},
  journal={Drift Bound Labs Technical Report},
  year={2026},
  month={October}
}
```

---

## License

Released under the **Apache License, Version 2.0**. See [LICENSE](LICENSE) and [AUTHORS.md](AUTHORS.md) for details.
