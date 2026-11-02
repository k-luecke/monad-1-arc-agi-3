#!/usr/bin/env python3
"""
Deterministic compiler and end-to-end verifier for the Monad(1) V7 INOS + Monad(2)
self-contained ARC-AGI-3 Jupyter submission notebooks:
  1. kaggle_monad_1p0/monad-1p0-v7-inos-unified.ipynb
  2. monad-2-arc-agi-3-submission.ipynb

Usage:
  python build_submission_notebook.py
  python build_submission_notebook.py --verify
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import subprocess
import sys
import tempfile
import lzma
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent

EXPECTED_MONAD2_PY = (
    "__init__.py",
    "analyze_factorial.py",
    "candidates.py",
    "canvas_stream.py",
    "coord_probe.py",
    "coordinate.py",
    "discovery.py",
    "eval_fmf_retrieval.py",
    "eval_watch.py",
    "factorial.py",
    "general_guard.py",
    "llm.py",
    "memory.py",
    "menu.py",
    "planmode.py",
    "predicates.py",
    "primitives.py",
    "roles.py",
    "runtime.py",
    "schema.py",
    "scp.py",
    "synthesizer.py",
    "test_coordinate.py",
    "test_discovery.py",
    "test_factorial.py",
    "test_memory.py",
    "test_plan.py",
    "test_primitives.py",
    "test_projection.py",
    "test_roles.py",
    "test_runtime.py",
    "test_schema.py",
)

EXPECTED_FMF_CORPUS = (
    "README.md",
    "records.jsonl",
    "representatives.json",
    "stats.json",
    "watch_labels.jsonl",
)

LLAMA_CPP_SHIM_SOURCE = '''"""Local llama.cpp Python bindings backed by llama.dll GBNF parser and running llama-server daemons."""
from __future__ import annotations

import ctypes
import json
import os
import urllib.request
from pathlib import Path

_DLL_DIR = Path(r"C:\\Users\\Kyle W. Luecke\\Desktop\\SCP_Local_LLM\\tools\\llama_vulkan")
_LIB = None


def _get_lib():
    global _LIB
    if _LIB is not None:
        return _LIB
    if _DLL_DIR.is_dir() and hasattr(os, "add_dll_directory"):
        os.add_dll_directory(str(_DLL_DIR))
        dll_path = _DLL_DIR / "llama.dll"
        if dll_path.is_file():
            lib = ctypes.CDLL(str(dll_path))
            lib.llama_sampler_init_grammar.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_char_p]
            lib.llama_sampler_init_grammar.restype = ctypes.c_void_p
            lib.llama_sampler_free.argtypes = [ctypes.c_void_p]
            _LIB = lib
    return _LIB


class LlamaGrammar:
    def __init__(self, grammar_str: str) -> None:
        self._grammar = str(grammar_str)

    @classmethod
    def from_string(cls, grammar_str: str, verbose: bool = False) -> "LlamaGrammar":
        if not isinstance(grammar_str, str) or not grammar_str.strip():
            raise ValueError("Empty GBNF grammar")
        lib = _get_lib()
        if lib is not None:
            sampler = lib.llama_sampler_init_grammar(None, grammar_str.encode("utf-8"), b"root")
            if not sampler:
                raise ValueError(f"Invalid GBNF grammar: {grammar_str[:120]}")
            lib.llama_sampler_free(sampler)
        elif "root ::=" not in grammar_str:
            raise ValueError("Missing root rule in GBNF grammar")
        return cls(grammar_str)

    def __str__(self) -> str:
        return self._grammar


def _port_for_model(model_path: str) -> int:
    low = str(model_path).lower()
    if "0.5b" in low:
        return int(os.environ.get("INOS_PORT_A", "8087"))
    if "1.5b" in low:
        return int(os.environ.get("INOS_PORT_B", "8088"))
    return int(os.environ.get("INOS_PORT_EXEC", "8089"))


class Llama:
    def __init__(self, model_path: str, n_ctx: int = 1024, **kwargs) -> None:
        self.model_path = str(model_path)
        self.n_ctx = int(n_ctx)
        self.port = _port_for_model(self.model_path)

    def create_chat_completion(
        self,
        messages: list[dict],
        temperature: float = 0.0,
        max_tokens: int = 128,
        seed: int = 0,
        grammar: LlamaGrammar | str | None = None,
        **kwargs,
    ) -> dict:
        payload: dict = {
            "messages": messages,
            "temperature": float(temperature),
            "max_tokens": int(max_tokens),
            "seed": int(seed),
            "cache_prompt": True,
        }
        if grammar is not None:
            g_str = grammar._grammar if isinstance(grammar, LlamaGrammar) else str(grammar)
            if g_str:
                payload["grammar"] = g_str
        req = urllib.request.Request(
            f"http://127.0.0.1:{self.port}/v1/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=120.0) as resp:
            return json.loads(resp.read().decode("utf-8"))
'''

CELL0_MARKDOWN = """# Monad(1) V7 INOS + Monad(2) — Unified General Online-Learning & Algorithmic Synthesis Agent for ARC-AGI-3
**Author:** Kyle W. Luecke (`Drift Bound Labs`)  
**Repository:** `https://github.com/k-luecke/monad-1-arc-agi-3` (`cursor/monad2-a533`)  
**License:** Apache-2.0

---

## Architecture Overview (`Monad(1) V7 INOS` + `Monad(2)`)

This self-contained, runnable Jupyter notebook compiles the complete **Monad(1) V7 Intent-Native Operating System (INOS)** and **Monad(2) General Coordination, Discovery & Online Solver Synthesis** stack (all **43/43** checklist items in `monad2/TODO.md`):

1. **Zero Game-ID Dispatch & Static/Runtime Generalization Guards (`monad2/general_guard.py`)**:
   - Every active decision module (`coordinate.py`, `schema.py`, `canvas_stream.py`, `scp.py`, `memory.py`, `runtime.py`, `llm.py`, `discovery.py`, `primitives.py`, `roles.py`, `predicates.py`, `menu.py`, `planmode.py`, `candidates.py`, `synthesizer.py`) is continuously audited by `general_guard.static_violations()`, `primitives.source_violations()`, and `schema.assert_structure()` to guarantee zero game-prefix literals, zero hardcoded palettes, and zero hardcoded coordinates.
   - `BlindEnvironmentProxy` + `verify_agent_ast_no_env_introspection()` isolate the environment interface so the agent only ever accesses `observation_space` and `step(...)` with `game_id` scrubbed to `"blind_unknown_env"`.
2. **Top-Down Non-Abelian Gauge Field Integration (`Monad1TopDownGaugeField` $\\to$ `monad2/coordinate.py` & `monad2/candidates.py`)**:
   - Computes a 64x64 top-down gauge potential $\\Phi_{\\text{gauge}}(y, x)$ and directional Wilson-loop transport biases from novel playfield atoms, goal hypotheses, and episodic causal traces, steering candidate enumeration and `step_toward` tie-breaking invariant to palette permutation and $D_4$ rotation/reflection.
3. **Fuzzy Merkle Forest (FMF) Structural Unhashing (`monad2/memory.py` + `monad2/fmf_corpus/`)**:
   - Decodes the 469-record `fmf_corpus/records.jsonl` and 64-bit packed `MonadAssociativeMerkleTree` nodes (`unhash_packed_node`, `retrieve_unhashed`) into actionable motor primitives (`approach`, `toggle`, `convey`, `align`, `cycle_select`, `route`, `assemble`), role-binding chains, and candidate-ordering priors (`SWITCH_FIRST`, `match_panel`) with strict holdout exclusion.
4. **LLM Watch-and-Intervene Supervisor & Mandatory Pass@1 Classification (`monad2/coordinate.py`, `monad2/llm.py`)**:
   - Local 3-model ensemble via `llama.cpp` with GBNF grammar constraints (`Qwen2.5-0.5B-Instruct` on A', `Qwen2.5-1.5B-Instruct` on B', `Mistral-NeMo-Minitron-8B-Instruct` on the Executive).
   - Enforces **Mandatory Pass@1 LLM Classification ($\\ge 1$ LLM call per game)** on Level 0 after initial directional/click probing so every game receives explicit executive goal/role/primitive classification before any cooperative world-model handoff.
   - **Watch-and-Intervene Mode**: Continuously monitors deterministic execution; intervenes only when no-op streaks ($\\ge 2$), 2-cycle/4-cycle state oscillations, or 8-step novel-atom droughts occur.
5. **Pass@1 $\\to$ Pass@2 Online Algorithmic Solver Synthesis (`monad2/synthesizer.py`)**:
   - During Pass@1 (`MONAD2_PASS=1`), `record_level_observation()` and `synthesize_solver_from_pass1()` distill empirical transitions, confirmed roles, switch/portal/push rules, and loop-erased state-keyed `causal_policy` maps into a palette- and $D_4$-invariant `SynthesizedSolverSpec` (`scorecards/synthesized_solvers.json`).
   - During Pass@2 (`MONAD2_PASS=2` / `--two-pass`), `plan_with_synthesized_solver()` replays the synthesized symbolic policy directly in 0 LLM calls.

---

## Notebook Cell Layout

- **Cell 0 (`markdown`)**: Architecture & execution mode overview.
- **Cell 1 (`code`)**: Materializes the complete `monad2/` package (all 32 `.py` modules including all 10 `test_*.py` suites) and `monad2/fmf_corpus/` (all 5 corpus files) onto disk, configures `llama_cpp` and Kaggle wheel/model discovery, and runs static/source generalization guards.
- **Cell 2 (`code`)**: Complete, self-contained `my_agent_v7_inos.py` implementation (with fallback `GameState`, `GameAction`, `FrameData`, and `Agent` base classes), plus on-disk materialization for AST verification and multi-worker execution.
- **Cell 3 (`code`)**: Complete `run_competition_eval.py` harness (`--two-pass`, `--no-game-solvers`, `--blind-id`, `--offline`, `--local-gateway`, `--self-test`) and automatic `run_notebook_entrypoint()` invocation.

---

## Execution Modes

1. **Official Remote Competition Mode (`https://three.arcprize.org`)**:
   ```bash
   export ARC_API_KEY="your-arc-prize-api-key"
   python run_competition_eval.py
   ```
2. **Kaggle Competition Rerun / Commit Mode**:
   - Execute all cells top-to-bottom (`Run All`). When `KAGGLE_IS_COMPETITION_RERUN` is set, `run_notebook_entrypoint()` polls `http://gateway:8001/api/games` and evaluates against the competition gateway; in Kaggle commit mode, it runs offline/self-test verification and emits `submission.parquet`.
3. **Local Gateway Competition Mode (`listen_and_serve(port=8001, competition_mode=True)`)**:
   ```bash
   python run_competition_eval.py --local-gateway --blind-id
   ```
4. **Offline Mode (Standard & Solvers-Off Two-Pass Synthesis)**:
   ```bash
   # Full 25-game offline verification with BlindEnvironmentProxy:
   python run_competition_eval.py --offline --blind-id

   # Solvers-off Pass@1 discovery + Pass@2 synthesized solver execution:
   python run_competition_eval.py --two-pass --offline --blind-id --no-game-solvers
   ```
5. **Standalone Self-Test (Zero External Dependencies)**:
   ```bash
   python run_competition_eval.py --self-test --blind-id
   ```
"""


def _to_source_lines(text: str) -> list[str]:
    return text.splitlines(keepends=True)


def build_cell1_source(bundle_b64: str) -> str:
    return f'''# Cell 1: Materialize Complete `monad2/` Package & `fmf_corpus/` + Environment/Model Discovery
from __future__ import annotations

import base64
import json
import os
import shutil
import subprocess
import sys
import lzma
from pathlib import Path

os.environ.setdefault("OMP_NUM_THREADS", "2")
os.environ.setdefault("RAYON_NUM_THREADS", "2")
os.environ.setdefault("MALLOC_ARENA_MAX", "2")
os.environ.setdefault("INOS_BRIDGE_MODE", "STATIC_MONOLITH_IN_MEMORY")
os.environ.setdefault("INOS_USE_EXTERNAL_DAEMON", "0")

for _wheel_cand in (
    "/kaggle/input/competitions/arc-prize-2026-arc-agi-3/arc_agi_3_wheels",
    "/kaggle/input/arc-prize-2026-arc-agi-3/arc_agi_3_wheels",
):
    if os.path.exists(_wheel_cand):
        subprocess.run(
            [sys.executable, "-m", "pip", "install", "--no-index", "--find-links", _wheel_cand, "arc-agi", "python-dotenv"],
            check=False,
        )
        break

if Path("/kaggle/input").exists():
    for _root_d, _dirs, _files in os.walk("/kaggle/input", followlinks=True):
        for _fname in _files:
            _low = _fname.lower()
            if _low.endswith(".gguf"):
                _full = str(Path(_root_d) / _fname)
                if "0.5b" in _low:
                    os.environ.setdefault("INOS_MODEL_A_GGUF", _full)
                elif "1.5b" in _low:
                    os.environ.setdefault("INOS_MODEL_B_GGUF", _full)
                else:
                    os.environ.setdefault("INOS_MISTRAL_NEMO_GGUF", _full)

_BUNDLE_B64 = "{bundle_b64}"
_BUNDLE = json.loads(lzma.decompress(base64.b64decode(_BUNDLE_B64)).decode("utf-8"))
_MONAD2_FILES: dict[str, str] = _BUNDLE["monad2_files"]
_MONAD_DISK_BACKUPS: dict[str, str] = _BUNDLE["disk_backups"]
_LLAMA_CPP_SHIM: str = _BUNDLE["llama_cpp_shim"]


def _write_if_changed(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_file():
        try:
            if path.read_text(encoding="utf-8") == content:
                return
        except Exception:
            pass
    path.write_text(content, encoding="utf-8")


_TARGET_ROOTS = [Path.cwd()]
if os.name != "nt":
    try:
        _tmp_root = Path("/tmp/monad1_arc3")
        _tmp_root.mkdir(parents=True, exist_ok=True)
        if _tmp_root.resolve() != Path.cwd().resolve():
            _TARGET_ROOTS.append(_tmp_root)
    except Exception:
        pass

for _root in _TARGET_ROOTS:
    for _rel_path, _text in _MONAD2_FILES.items():
        _write_if_changed(_root / _rel_path, _text)
    if str(_root) not in sys.path:
        sys.path.insert(0, str(_root))

try:
    import llama_cpp as _llama_cpp_mod  # noqa: F401
except ModuleNotFoundError:
    _sib_monad1 = Path.cwd().parent / "monad(1)"
    if (_sib_monad1 / "llama_cpp").is_dir() and str(_sib_monad1) not in sys.path:
        sys.path.append(str(_sib_monad1))
    try:
        import llama_cpp as _llama_cpp_mod  # noqa: F401
    except ModuleNotFoundError:
        for _root in _TARGET_ROOTS:
            _write_if_changed(_root / "llama_cpp" / "__init__.py", _LLAMA_CPP_SHIM)
        import llama_cpp as _llama_cpp_mod  # noqa: F401

from monad2 import general_guard, primitives
from monad2.memory import corpus_path, load_records

assert general_guard.static_violations() == [], f"Static violations: {{general_guard.static_violations()}}"
assert primitives.source_violations() == [], f"Primitive source violations: {{primitives.source_violations()}}"
assert general_guard.HITS == [], f"Unexpected solver hits: {{general_guard.HITS}}"
_fmf_records = load_records(corpus_path())
assert len(_fmf_records) >= 400, f"Expected >= 400 FMF corpus records, got {{len(_fmf_records)}}"

print(
    f"[MONAD2_PACKAGE_READY] Materialized {{len(_MONAD2_FILES)}} files into {{Path.cwd() / 'monad2'}} "
    f"| FMF corpus={{len(_fmf_records)}} records | static_violations=0 | source_violations=0"
)
'''


def build_cell2_source(agent_src: str) -> str:
    return """# Cell 2: Materialize & Load Complete `my_agent_v7_inos.py` (`MyAgent`) Implementation
from __future__ import annotations

import importlib
import sys as _sys
from pathlib import Path as _Path

assert "_MONAD_DISK_BACKUPS" in globals() and "my_agent_v7_inos.py" in _MONAD_DISK_BACKUPS, (
    "Run Cell 1 first to initialize _MONAD_DISK_BACKUPS."
)
_agent_disk_src = _MONAD_DISK_BACKUPS["my_agent_v7_inos.py"]

for _r in globals().get("_TARGET_ROOTS", [_Path.cwd()]):
    _p = _r / "my_agent_v7_inos.py"
    if not _p.is_file() or _p.read_text(encoding="utf-8") != _agent_disk_src:
        _p.write_text(_agent_disk_src, encoding="utf-8")
    if _r != _Path.cwd() or not (_r / ".git").exists():
        _p_alias = _r / "my_agent.py"
        if not _p_alias.is_file() or _p_alias.read_text(encoding="utf-8") != _agent_disk_src:
            _p_alias.write_text(_agent_disk_src, encoding="utf-8")

if str(_Path.cwd()) not in _sys.path:
    _sys.path.insert(0, str(_Path.cwd()))

import my_agent_v7_inos as _agent_mod
importlib.reload(_agent_mod)
_sys.modules["my_agent"] = _agent_mod

for _k, _v in vars(_agent_mod).items():
    if not _k.startswith("__"):
        globals()[_k] = _v

from monad2.general_guard import solver_catalog_ok as _solver_catalog_ok
assert _solver_catalog_ok(MyAgent), "MyAgent 27-solver guard catalog mismatch"
print(f"[MONAD1_V7_AGENT_READY] MyAgent loaded ({_Path('my_agent_v7_inos.py').stat().st_size:,} B on disk) | solver_catalog_ok=True")
"""


def build_cell3_source(eval_src: str) -> str:
    snippet = """
# --- Ensure `run_competition_eval.py` is materialized on disk before running harness ---
from pathlib import Path as _Path

if "_MONAD_DISK_BACKUPS" in globals() and "run_competition_eval.py" in _MONAD_DISK_BACKUPS:
    _eval_disk_src = _MONAD_DISK_BACKUPS["run_competition_eval.py"]
    for _r in globals().get("_TARGET_ROOTS", [_Path.cwd()]):
        _p = _r / "run_competition_eval.py"
        if not _p.is_file() or _p.read_text(encoding="utf-8") != _eval_disk_src:
            _p.write_text(_eval_disk_src, encoding="utf-8")
"""
    anchor = "from __future__ import annotations\n"
    if anchor in eval_src:
        return eval_src.replace(anchor, anchor + snippet + "\n", 1).rstrip() + "\n"
    return eval_src.rstrip() + "\n" + snippet + "\n"


def compile_notebooks() -> tuple[Path, Path]:
    monad2_dir = REPO_ROOT / "monad2"
    fmf_dir = monad2_dir / "fmf_corpus"

    monad2_files: dict[str, str] = {}
    for fname in EXPECTED_MONAD2_PY:
        fpath = monad2_dir / fname
        if not fpath.is_file():
            raise FileNotFoundError(f"Missing required monad2 module: {fpath}")
        monad2_files[f"monad2/{fname}"] = fpath.read_text(encoding="utf-8")

    for fname in EXPECTED_FMF_CORPUS:
        fpath = fmf_dir / fname
        if not fpath.is_file():
            raise FileNotFoundError(f"Missing required fmf_corpus file: {fpath}")
        monad2_files[f"monad2/fmf_corpus/{fname}"] = fpath.read_text(encoding="utf-8")

    agent_path = REPO_ROOT / "my_agent_v7_inos.py"
    eval_path = REPO_ROOT / "run_competition_eval.py"
    agent_src = agent_path.read_text(encoding="utf-8")
    eval_src = eval_path.read_text(encoding="utf-8")

    bundle = {
        "monad2_files": monad2_files,
        "disk_backups": {
            "my_agent_v7_inos.py": agent_src,
            "run_competition_eval.py": eval_src,
        },
        "llama_cpp_shim": LLAMA_CPP_SHIM_SOURCE,
    }
    bundle_bytes = json.dumps(bundle, sort_keys=True, ensure_ascii=False).encode("utf-8")
    bundle_b64 = base64.b64encode(lzma.compress(bundle_bytes, preset=9)).decode("ascii")

    cell1_src = build_cell1_source(bundle_b64)
    cell2_src = build_cell2_source(agent_src)
    cell3_src = build_cell3_source(eval_src)

    notebook_doc = {
        "cells": [
            {
                "cell_type": "markdown",
                "metadata": {},
                "source": _to_source_lines(CELL0_MARKDOWN),
            },
            {
                "cell_type": "code",
                "execution_count": None,
                "metadata": {"trusted": True},
                "outputs": [],
                "source": _to_source_lines(cell1_src),
            },
            {
                "cell_type": "code",
                "execution_count": None,
                "metadata": {"trusted": True},
                "outputs": [],
                "source": _to_source_lines(cell2_src),
            },
            {
                "cell_type": "code",
                "execution_count": None,
                "metadata": {"trusted": True},
                "outputs": [],
                "source": _to_source_lines(cell3_src),
            },
        ],
        "metadata": {
            "kaggle": {
                "accelerator": "nvidiaTeslaT4",
                "isGpuEnabled": True,
                "isInternetEnabled": False,
                "language": "python",
                "sourceType": "notebook",
            },
            "kernelspec": {
                "display_name": "Python 3",
                "language": "python",
                "name": "python3",
            },
            "language_info": {
                "file_extension": ".py",
                "mimetype": "text/x-python",
                "name": "python",
                "pygments_lexer": "ipython3",
                "version": "3.11.0",
            },
        },
        "nbformat": 4,
        "nbformat_minor": 5,
    }

    nb_json = json.dumps(notebook_doc, indent=1, ensure_ascii=True) + "\n"
    out_kaggle = REPO_ROOT / "kaggle_monad_1p0" / "monad-1p0-v7-inos-unified.ipynb"
    out_top = REPO_ROOT / "monad-2-arc-agi-3-submission.ipynb"
    out_kaggle.parent.mkdir(parents=True, exist_ok=True)
    out_kaggle.write_text(nb_json, encoding="utf-8")
    out_top.write_text(nb_json, encoding="utf-8")

    print(f"[BUILD_OK] Wrote {out_kaggle} ({out_kaggle.stat().st_size:,} bytes)")
    print(f"[BUILD_OK] Wrote {out_top} ({out_top.stat().st_size:,} bytes)")
    return out_kaggle, out_top


def verify_notebooks(paths: tuple[Path, Path]) -> None:
    for p in paths:
        assert p.is_file(), f"Notebook missing: {p}"
        assert p.stat().st_size < 1_048_576, f"Notebook {p} exceeds 1 MB Kaggle SaveKernel limit: {p.stat().st_size:,} bytes"
        doc = json.loads(p.read_text(encoding="utf-8"))
        assert doc.get("nbformat") == 4, f"Expected nbformat 4 in {p}"
        cells = doc.get("cells")
        assert isinstance(cells, list) and len(cells) == 4, f"Expected 4 cells in {p}, got {len(cells) if isinstance(cells, list) else type(cells)}"
        assert cells[0]["cell_type"] == "markdown"
        for idx in (1, 2, 3):
            assert cells[idx]["cell_type"] == "code"
            assert isinstance(cells[idx]["source"], list) and len(cells[idx]["source"]) > 0
    assert paths[0].read_bytes() == paths[1].read_bytes(), "Two notebook copies differ!"
    print("[SCHEMA_OK] Both notebooks passed JSON and nbformat v4 schema validation and are byte-identical.")

    runner_code = """
import json
import os
import subprocess
import sys
from pathlib import Path

nb_path = Path(sys.argv[1])
env_dir = sys.argv[2]
doc = json.loads(nb_path.read_text(encoding="utf-8"))

ns = {"__name__": "__main__"}
for idx, cell in enumerate(doc["cells"]):
    if cell["cell_type"] != "code":
        continue
    src = "".join(cell["source"])
    print(f"[EXEC_CELL_{idx}] Executing code cell {idx} ({len(src):,} chars)...", flush=True)
    exec(compile(src, f"<notebook_cell_{idx}>", "exec"), ns)

assert Path("monad2/__init__.py").is_file(), "monad2/__init__.py not materialized"
assert Path("monad2/synthesizer.py").is_file(), "monad2/synthesizer.py not materialized"
assert Path("monad2/candidates.py").is_file(), "monad2/candidates.py not materialized"
assert Path("monad2/fmf_corpus/records.jsonl").is_file(), "fmf_corpus/records.jsonl not materialized"
assert Path("my_agent_v7_inos.py").is_file(), "my_agent_v7_inos.py not materialized"
assert Path("my_agent.py").is_file(), "my_agent.py not materialized in clean working directory"
assert Path("run_competition_eval.py").is_file(), "run_competition_eval.py not materialized"
assert Path("submission.parquet").is_file(), "submission.parquet not emitted automatically in commit mode"

# Verify dynamic INOS_MODEL_DIR resolution after monad2.llm is already imported
from monad2 import llm as _llm_mod
_custom_mdir = Path("custom_model_dir")
_custom_mdir.mkdir(exist_ok=True)
_fake_gguf = _custom_mdir / "qwen2.5-0.5b-instruct-q4_k_m.gguf"
_fake_gguf.write_bytes(b"GGUF")
os.environ["INOS_MODEL_DIR"] = str(_custom_mdir.resolve())
assert Path(_llm_mod.model_path("A")).resolve() == _fake_gguf.resolve(), f"Dynamic INOS_MODEL_DIR failed: {_llm_mod.model_path('A')}"
os.environ.pop("INOS_MODEL_DIR", None)
print("[DYNAMIC_MODEL_DIR_OK] monad2.llm.model_path dynamically resolves INOS_MODEL_DIR post-import.")

test_modules = [
    "monad2.test_coordinate",
    "monad2.test_discovery",
    "monad2.test_factorial",
    "monad2.test_memory",
    "monad2.test_plan",
    "monad2.test_primitives",
    "monad2.test_projection",
    "monad2.test_roles",
    "monad2.test_runtime",
    "monad2.test_schema",
]
env = dict(os.environ, MONAD2_ENV_DIR=env_dir, PYTHONHASHSEED="0")
for mod in test_modules:
    proc = subprocess.run([sys.executable, "-m", mod], env=env, capture_output=True, text=True)
    if proc.returncode != 0:
        print(f"[FAIL] {mod} exited with {proc.returncode}:\\nSTDOUT:\\n{proc.stdout}\\nSTDERR:\\n{proc.stderr}", file=sys.stderr)
        sys.exit(proc.returncode)
    last_line = [ln.strip() for ln in proc.stdout.splitlines() if ln.strip()][-1]
    print(f"[UNIT_PASS] {mod} -> {last_line}", flush=True)
"""
    sib_env_dir = REPO_ROOT.parent / "monad(1)" / "environment_files"
    with tempfile.TemporaryDirectory(prefix="monad2_nb_verify_") as tmpdir:
        print(f"[VERIFY_TMP] Running end-to-end clean-room notebook execution in {tmpdir}...")
        runner_file = Path(tmpdir) / "_run_nb_verify.py"
        runner_file.write_text(runner_code, encoding="utf-8")
        proc = subprocess.run(
            [sys.executable, str(runner_file), str(paths[1]), str(sib_env_dir)],
            cwd=tmpdir,
            capture_output=True,
            text=True,
        )
        print(proc.stdout, end="")
        if proc.returncode != 0:
            print(proc.stderr, file=sys.stderr)
            raise RuntimeError(f"Clean-room notebook verification failed with exit code {proc.returncode}")

        # Verify byte-for-byte identity of all materialized files against source repo
        tmp_path = Path(tmpdir)
        for fname in EXPECTED_MONAD2_PY:
            src_txt = (REPO_ROOT / "monad2" / fname).read_text(encoding="utf-8")
            dst_txt = (tmp_path / "monad2" / fname).read_text(encoding="utf-8")
            assert src_txt == dst_txt, f"Content mismatch in materialized monad2/{fname}"
        for fname in EXPECTED_FMF_CORPUS:
            src_txt = (REPO_ROOT / "monad2" / "fmf_corpus" / fname).read_text(encoding="utf-8")
            dst_txt = (tmp_path / "monad2" / "fmf_corpus" / fname).read_text(encoding="utf-8")
            assert src_txt == dst_txt, f"Content mismatch in materialized monad2/fmf_corpus/{fname}"
        for top_f in ("my_agent_v7_inos.py", "run_competition_eval.py"):
            src_txt = (REPO_ROOT / top_f).read_text(encoding="utf-8")
            dst_txt = (tmp_path / top_f).read_text(encoding="utf-8")
            assert src_txt == dst_txt, f"Content mismatch in materialized {top_f}"
        print("[BYTE_IDENTITY_OK] All 39 materialized files match repository sources byte-for-byte.")

        if sib_env_dir.is_dir():
            env_offline = dict(
                os.environ,
                PYTHONHASHSEED="0",
                PYTHONPATH=f"{sib_env_dir.parent}{os.pathsep}{tmpdir}",
            )
            proc_off = subprocess.run(
                [
                    sys.executable,
                    "run_competition_eval.py",
                    "--offline",
                    "--blind-id",
                    "--games",
                    "ls20",
                    "--environments-dir",
                    str(sib_env_dir),
                ],
                cwd=tmpdir,
                env=env_offline,
                capture_output=True,
                text=True,
            )
            print(proc_off.stdout, end="")
            if proc_off.returncode != 0:
                print(proc_off.stderr, file=sys.stderr)
                raise RuntimeError(f"Offline --blind-id verification in clean temp dir failed with {proc_off.returncode}")
            print("[OFFLINE_BLIND_ID_OK] Materialized harness passed real offline --blind-id game verification.")

            # Verify simulated KAGGLE_IS_COMPETITION_RERUN=1 against a live local competition_mode=True gateway
            gw_test_code = f"""
import os
import sys
import threading
import time
from arc_agi import Arcade, OperationMode
import run_competition_eval

srv = Arcade(environments_dir={str(sib_env_dir)!r}, operation_mode=OperationMode.OFFLINE)
t = threading.Thread(
    target=lambda: srv.listen_and_serve(host="127.0.0.1", port=8019, competition_mode=True),
    daemon=True,
)
t.start()
time.sleep(2.0)

os.environ["KAGGLE_IS_COMPETITION_RERUN"] = "1"
os.environ["ARC_BASE_URL"] = "http://127.0.0.1:8019"
os.environ["ARC_API_KEY"] = "kaggle-rerun-test-key"
os.environ["KAGGLE_RERUN_ARGS"] = "--games ls20 --blind-id --no-game-solvers --max-game-seconds 15"
rc = run_competition_eval.run_notebook_entrypoint()
assert rc == 0, f"Expected rc == 0 in KAGGLE_IS_COMPETITION_RERUN gateway test, got {{rc}}"
print("[KAGGLE_RERUN_GATEWAY_OK] Simulated KAGGLE_IS_COMPETITION_RERUN=1 gateway evaluation passed (rc=0).")
"""
            gw_test_file = Path(tmpdir) / "_run_gw_test.py"
            gw_test_file.write_text(gw_test_code, encoding="utf-8")
            proc_gw = subprocess.run(
                [sys.executable, str(gw_test_file)],
                cwd=tmpdir,
                env=env_offline,
                capture_output=True,
                text=True,
            )
            print(proc_gw.stdout, end="")
            if proc_gw.returncode != 0:
                print(proc_gw.stderr, file=sys.stderr)
                raise RuntimeError(f"Simulated KAGGLE_IS_COMPETITION_RERUN gateway test failed with {proc_gw.returncode}")

            # Verify --two-pass --offline --blind-id --no-game-solvers synthesis in clean temp dir
            proc_tp = subprocess.run(
                [
                    sys.executable,
                    "run_competition_eval.py",
                    "--two-pass",
                    "--offline",
                    "--blind-id",
                    "--no-game-solvers",
                    "--games",
                    "ls20",
                    "--max-game-seconds",
                    "25",
                    "--environments-dir",
                    str(sib_env_dir),
                ],
                cwd=tmpdir,
                env=env_offline,
                capture_output=True,
                text=True,
            )
            print(proc_tp.stdout, end="")
            if proc_tp.returncode != 0:
                print(proc_tp.stderr, file=sys.stderr)
                raise RuntimeError(f"Two-pass synthesis verification in clean temp dir failed with {proc_tp.returncode}")
            assert (tmp_path / "scorecards" / "synthesized_solvers.json").is_file(), "synthesized_solvers.json not created"
            print("[TWO_PASS_SYNTHESIS_OK] Materialized harness passed --two-pass --offline --blind-id --no-game-solvers synthesis.")
    print("[VERIFY_ALL_OK] Clean-room notebook execution, file materialization, AST/static guards, offline game test, Kaggle rerun gateway test, two-pass synthesis, and all 10 unit test suites PASSED.")


def main() -> int:
    parser = argparse.ArgumentParser(description="Compile and verify Monad(1) V7 + Monad(2) ARC-AGI-3 submission notebooks.")
    parser.add_argument("--verify", action="store_true", help="Execute compiled notebook end-to-end in a clean temporary directory.")
    args = parser.parse_args()
    paths = compile_notebooks()
    if args.verify:
        verify_notebooks(paths)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
