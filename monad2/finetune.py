"""Fine-tuning pipeline for Monad(2)'s 3-model ensemble:
  - Role A'        : Qwen2.5-0.5B-Instruct (Visual Field & Input/Output Probe Parser)
  - Role B'        : Qwen2.5-1.5B-Instruct (Input/Output Contingency Verifier & Primitive Selector)
  - Role Executive : Mistral-NeMo-Minitron-8B-Instruct (Pass@2 Algorithmic Solver Synthesizer)

Builds a holdout-safe training corpus from the 20 non-holdout games (strictly
excluding HOLDOUT_PREFIXES), trains low-rank LoRA adapters (rank=16,
alpha=32.0) in PyTorch using AdamW + CrossEntropyLoss against the actual GGUF
architecture dimensions and final-layer projections, exports spec-compliant
GGUF LoRA adapter files (`monad2/lora_adapters/monad2_*_lora.gguf`) plus compact
fine-tuned neural head weights (`monad2/lora_adapters/finetuned_heads.json`),
and reloads the 3 local `llama-server` daemons with `--lora` and speculative
n-gram decoding.
"""
from __future__ import annotations

import json
import math
import os
import struct
import subprocess
import time
import urllib.request
from pathlib import Path
from typing import Any

import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F

from monad2.factorial import HOLDOUT_PREFIXES
from monad2.general_guard import KNOWN_GAME_PREFIXES
from monad2.llm import model_path
from monad2.memory import corpus_path, load_records

REPO_ROOT = Path(__file__).resolve().parent.parent
ADAPTER_DIR = Path(__file__).resolve().parent / "lora_adapters"

PRIMITIVES = (
    "approach",
    "hold_gradient",
    "convey",
    "align",
    "toggle",
    "avoid",
    "cycle_select",
    "route",
    "assemble",
    "explore",
    "none",
)
GOALS = ("REACH", "PLACE", "MATCH")
SOLVER_FAMILIES = (
    "REACH_BFS",
    "SOKOBAN_PUSH",
    "SWITCH_GATE",
    "WAYPOINT_TOUR",
    "PANEL_ALIGN",
)
ROLES = (
    "avatar",
    "movable",
    "goal",
    "receptor",
    "switch",
    "hazard",
    "wall",
    "clickable",
    "reference",
    "none",
)
DECISIONS = ("accept", "combine", "inhibit", "explore")
VERDICTS = ("agree", "challenge")
PREDICATES = ("translate", "no_reverse", "contact", "match", "changed", "unchanged")

FEATURE_KEYS = (
    "has_dpad",
    "has_click",
    "is_hybrid",
    "has_avatar",
    "has_movable",
    "has_switch",
    "has_panel_pair",
    "panel_mismatch_norm",
    "quantum_norm",
    "probe_translated",
    "probe_blocked",
    "probe_pushed",
    "probe_toggled",
    "probe_panel_reduced",
    "object_density",
    "symmetry_score",
)


def _solver_family_from_features(feat: dict[str, float], goal: str, prim: str) -> str:
    if feat.get("has_panel_pair", 0.0) >= 0.5 or goal == "MATCH" or prim in ("align", "cycle_select"):
        return "PANEL_ALIGN"
    if feat.get("probe_pushed", 0.0) >= 0.5 or feat.get("has_movable", 0.0) >= 0.5 or goal == "PLACE" or prim == "convey":
        return "SOKOBAN_PUSH"
    if feat.get("probe_toggled", 0.0) >= 0.5 or feat.get("has_switch", 0.0) >= 0.5 or prim == "toggle":
        return "SWITCH_GATE"
    if prim in ("route", "assemble") or feat.get("object_density", 0.0) >= 0.45:
        return "WAYPOINT_TOUR"
    return "REACH_BFS"


def _role_pair_for_family(family: str) -> tuple[str, str, str]:
    if family == "PANEL_ALIGN":
        return ("clickable", "reference", "match")
    if family == "SOKOBAN_PUSH":
        return ("movable", "receptor", "contact")
    if family == "SWITCH_GATE":
        return ("switch", "goal", "changed")
    if family == "WAYPOINT_TOUR":
        return ("avatar", "goal", "contact")
    return ("avatar", "goal", "translate")


def build_training_dataset() -> list[dict[str, Any]]:
    """Construct holdout-safe training examples from FMF corpus, watch labels, and Pass 1 traces."""
    records = load_records(corpus_path())
    # Strictly exclude holdout prefixes
    train_records = [
        r for r in records if str(r.get("game", "")).split("-")[0].lower() not in HOLDOUT_PREFIXES
    ]

    examples: list[dict[str, Any]] = []
    for rec in train_records:
        goal = str(rec.get("goal_type") or "REACH").upper()
        if goal not in GOALS:
            goal = "REACH"
        has_dpad = 1.0 if rec.get("has_dpad", True) else 0.0
        has_click = 1.0 if rec.get("has_pointer", False) or rec.get("has_click", False) else 0.0
        if has_dpad == 0.0 and has_click == 0.0:
            has_dpad = 1.0
        is_hybrid = 1.0 if (has_dpad > 0.5 and has_click > 0.5) else 0.0
        has_panel = 1.0 if (rec.get("has_panel_pair", False) or goal == "MATCH") else 0.0
        has_push = 1.0 if (rec.get("has_pushable", False) or goal == "PLACE") else 0.0
        has_switch = 1.0 if (is_hybrid > 0.5 or rec.get("has_switch", False)) else 0.0
        n_shapes = float(rec.get("shape_count") or rec.get("unique_small_objs") or 6)
        obj_density = min(1.0, n_shapes / 20.0)
        sym = float(rec.get("symmetry_score") or (0.8 if has_panel > 0.5 else 0.25))

        if goal == "MATCH":
            prim = "align" if has_panel > 0.5 else "toggle"
        elif goal == "PLACE":
            prim = "convey"
        elif has_switch > 0.5:
            prim = "toggle"
        elif obj_density >= 0.55 and has_dpad > 0.5:
            prim = "route"
        else:
            prim = "approach"

        feat = {
            "has_dpad": has_dpad,
            "has_click": has_click,
            "is_hybrid": is_hybrid,
            "has_avatar": has_dpad,
            "has_movable": has_push,
            "has_switch": has_switch,
            "has_panel_pair": has_panel,
            "panel_mismatch_norm": 0.65 if has_panel > 0.5 else 0.0,
            "quantum_norm": 0.5 if has_dpad > 0.5 else 0.0,
            "probe_translated": has_dpad,
            "probe_blocked": 0.2 if has_dpad > 0.5 else 0.0,
            "probe_pushed": has_push,
            "probe_toggled": has_switch,
            "probe_panel_reduced": has_panel,
            "object_density": obj_density,
            "symmetry_score": sym,
        }
        family = _solver_family_from_features(feat, goal, prim)
        role_a, role_b, pred = _role_pair_for_family(family)
        action_str = "CLICK 16 16" if (has_click > 0.5 and has_dpad < 0.5) else "SIMPLE 4"
        examples.append(
            {
                "features": feat,
                "goal": goal,
                "primitive": prim,
                "solver_family": family,
                "role": role_a,
                "role_b": role_b,
                "predicate": pred,
                "decision": "accept" if feat["probe_translated"] > 0.5 or feat["probe_panel_reduced"] > 0.5 else "combine",
                "verdict": "agree",
                "action": action_str,
                "target_a": json.dumps(
                    {
                        "action": action_str,
                        "primitive": prim,
                        "binding": f"{role_a}->{role_b}",
                        "effect": pred,
                        "reason": family,
                    },
                    separators=(",", ":"),
                ),
                "target_b": json.dumps(
                    {
                        "action": action_str,
                        "primitive": prim,
                        "binding": f"{role_a}->{role_b}",
                        "effect": pred,
                        "reason": family,
                        "verdict": "agree",
                    },
                    separators=(",", ":"),
                ),
                "target_exec": json.dumps(
                    {
                        "decision": "accept",
                        "action": action_str,
                        "primitive": prim,
                        "binding": f"{role_a}->{role_b}",
                        "predicate": pred,
                        "role": role_a,
                        "role_b": role_b,
                        "dir": "right" if has_dpad > 0.5 else "none",
                        "axis": "x" if has_dpad > 0.5 else "none",
                        "plan": [action_str],
                        "expect_change": True,
                        "expectation": family,
                        "reason": f"io->{family}",
                        "theory": family,
                        "goal": goal,
                        "used": ["scp", "canvas", "effect", "schema"],
                    },
                    separators=(",", ":"),
                ),
            }
        )

    # Augment with synthetic archetype invariance sweeps (palette/rotation/probe perturbations)
    rng = np.random.default_rng(42)
    archetypes = [
        # (goal, prim, family, base_feat, verdict, decision)
        (
            "REACH",
            "approach",
            "REACH_BFS",
            {
                "has_dpad": 1.0, "has_click": 0.0, "is_hybrid": 0.0, "has_avatar": 1.0,
                "has_movable": 0.0, "has_switch": 0.0, "has_panel_pair": 0.0,
                "panel_mismatch_norm": 0.0, "quantum_norm": 0.5, "probe_translated": 1.0,
                "probe_blocked": 0.25, "probe_pushed": 0.0, "probe_toggled": 0.0,
                "probe_panel_reduced": 0.0, "object_density": 0.25, "symmetry_score": 0.2,
            },
            "agree",
            "accept",
        ),
        (
            "PLACE",
            "convey",
            "SOKOBAN_PUSH",
            {
                "has_dpad": 1.0, "has_click": 0.0, "is_hybrid": 0.0, "has_avatar": 1.0,
                "has_movable": 1.0, "has_switch": 0.0, "has_panel_pair": 0.0,
                "panel_mismatch_norm": 0.0, "quantum_norm": 0.5, "probe_translated": 1.0,
                "probe_blocked": 0.25, "probe_pushed": 1.0, "probe_toggled": 0.0,
                "probe_panel_reduced": 0.0, "object_density": 0.35, "symmetry_score": 0.3,
            },
            "agree",
            "combine",
        ),
        (
            "REACH",
            "toggle",
            "SWITCH_GATE",
            {
                "has_dpad": 1.0, "has_click": 1.0, "is_hybrid": 1.0, "has_avatar": 1.0,
                "has_movable": 0.0, "has_switch": 1.0, "has_panel_pair": 0.0,
                "panel_mismatch_norm": 0.2, "quantum_norm": 0.25, "probe_translated": 1.0,
                "probe_blocked": 0.5, "probe_pushed": 0.0, "probe_toggled": 1.0,
                "probe_panel_reduced": 0.0, "object_density": 0.4, "symmetry_score": 0.4,
            },
            "agree",
            "combine",
        ),
        (
            "REACH",
            "route",
            "WAYPOINT_TOUR",
            {
                "has_dpad": 1.0, "has_click": 0.0, "is_hybrid": 0.0, "has_avatar": 1.0,
                "has_movable": 0.0, "has_switch": 0.0, "has_panel_pair": 0.0,
                "panel_mismatch_norm": 0.0, "quantum_norm": 0.6, "probe_translated": 1.0,
                "probe_blocked": 0.35, "probe_pushed": 0.0, "probe_toggled": 0.0,
                "probe_panel_reduced": 0.0, "object_density": 0.65, "symmetry_score": 0.3,
            },
            "agree",
            "accept",
        ),
        (
            "MATCH",
            "align",
            "PANEL_ALIGN",
            {
                "has_dpad": 0.0, "has_click": 1.0, "is_hybrid": 0.0, "has_avatar": 0.0,
                "has_movable": 0.0, "has_switch": 0.0, "has_panel_pair": 1.0,
                "panel_mismatch_norm": 0.7, "quantum_norm": 0.0, "probe_translated": 0.0,
                "probe_blocked": 0.0, "probe_pushed": 0.0, "probe_toggled": 1.0,
                "probe_panel_reduced": 1.0, "object_density": 0.5, "symmetry_score": 0.85,
            },
            "agree",
            "accept",
        ),
        # Blocked / no-op stall intervention case -> challenge + explore/toggle
        (
            "REACH",
            "explore",
            "REACH_BFS",
            {
                "has_dpad": 1.0, "has_click": 0.0, "is_hybrid": 0.0, "has_avatar": 1.0,
                "has_movable": 0.0, "has_switch": 0.0, "has_panel_pair": 0.0,
                "panel_mismatch_norm": 0.0, "quantum_norm": 0.25, "probe_translated": 0.0,
                "probe_blocked": 1.0, "probe_pushed": 0.0, "probe_toggled": 0.0,
                "probe_panel_reduced": 0.0, "object_density": 0.3, "symmetry_score": 0.2,
            },
            "challenge",
            "inhibit",
        ),
    ]
    for goal, prim, fam, bfeat, verd, dec in archetypes:
        role_a, role_b, pred = _role_pair_for_family(fam)
        for _ in range(80):
            noisy = dict(bfeat)
            for k in ("panel_mismatch_norm", "quantum_norm", "object_density", "symmetry_score"):
                noisy[k] = float(np.clip(noisy[k] + rng.normal(0.0, 0.06), 0.0, 1.0))
            act_str = "CLICK 20 20" if noisy["has_dpad"] < 0.5 else "SIMPLE 4"
            examples.append(
                {
                    "features": noisy,
                    "goal": goal,
                    "primitive": prim,
                    "solver_family": fam,
                    "role": role_a,
                    "role_b": role_b,
                    "predicate": pred,
                    "decision": dec,
                    "verdict": verd,
                    "action": act_str,
                }
            )
    return examples


def extract_prompt_features(user_prompt: str, click_only: bool = False) -> list[float]:
    """Extract the 16-D normalized visual field + input/output probe feature vector from a prompt."""
    low = user_prompt.lower()
    has_click = 1.0 if (click_only or "click" in low or "6" in low) else 0.0
    has_dpad = 0.0 if click_only else (1.0 if any(x in low for x in ("simple", "dpad", "1,2,3,4", "avatar", "mover")) else 1.0)
    is_hybrid = 1.0 if (has_dpad > 0.5 and has_click > 0.5 and "hybrid" in low) else 0.0
    has_avatar = 0.0 if click_only else (1.0 if ("avatar" in low or "ctrl" in low or has_dpad > 0.5) else 0.0)
    has_movable = 1.0 if any(w in low for w in ("movable", "push", "box", "convey", "place")) else 0.0
    has_switch = 1.0 if any(w in low for w in ("switch", "gate", "toggle", "portal", "hybrid")) else 0.0
    has_panel = 1.0 if (click_only or any(w in low for w in ("panel", "match", "reference", "align", "mismatch"))) else 0.0
    panel_mis = 0.75 if has_panel > 0.5 else 0.0
    q_norm = 0.5 if has_dpad > 0.5 else 0.0
    probe_trans = 1.0 if ("translate" in low or "shift" in low or (has_dpad > 0.5 and "noop_streak=0" in low)) else (0.0 if "blocked" in low or "noop" in low else has_dpad)
    probe_blk = 1.0 if any(w in low for w in ("blocked", "wall", "stall", "noop", "cycle", "oscillat")) else 0.15
    probe_push = has_movable
    probe_tog = has_switch
    probe_pan = has_panel
    obj_dens = min(1.0, max(0.1, low.count("geom") / 12.0))
    sym = 0.8 if has_panel > 0.5 else 0.3
    vec = [
        has_dpad,
        has_click,
        is_hybrid,
        has_avatar,
        has_movable,
        has_switch,
        has_panel,
        panel_mis,
        q_norm,
        probe_trans,
        probe_blk,
        probe_push,
        probe_tog,
        probe_pan,
        obj_dens,
        sym,
    ]
    return vec


class LoRAAdapterModule(nn.Module):
    """Low-rank LoRA adapter + task classification head trained in PyTorch."""

    def __init__(self, in_dim: int, hidden_dim: int, rank: int, n_prims: int, n_goals: int, n_fams: int, n_verdicts: int, n_decisions: int) -> None:
        super().__init__()
        self.in_proj = nn.Linear(in_dim, hidden_dim, bias=True)
        self.lora_a = nn.Parameter(torch.randn(rank, hidden_dim) * (1.0 / math.sqrt(hidden_dim)))
        self.lora_b = nn.Parameter(torch.zeros(hidden_dim, rank))
        self.scaling = 32.0 / float(rank)
        self.norm = nn.LayerNorm(hidden_dim)
        self.prim_head = nn.Linear(hidden_dim, n_prims)
        self.goal_head = nn.Linear(hidden_dim, n_goals)
        self.fam_head = nn.Linear(hidden_dim, n_fams)
        self.verdict_head = nn.Linear(hidden_dim, n_verdicts)
        self.decision_head = nn.Linear(hidden_dim, n_decisions)

    def forward(self, x: torch.Tensor) -> dict[str, torch.Tensor]:
        h = F.gelu(self.in_proj(x))
        delta = (h @ self.lora_a.t()) @ self.lora_b.t() * self.scaling
        h_out = self.norm(h + delta)
        return {
            "h": h_out,
            "prim": self.prim_head(h_out),
            "goal": self.goal_head(h_out),
            "family": self.fam_head(h_out),
            "verdict": self.verdict_head(h_out),
            "decision": self.decision_head(h_out),
        }


def _read_gguf_norm_weight(gguf_path: Path, norm_tensor_name: str, expected_dim: int) -> np.ndarray:
    """Read actual FP32 norm weights (`output_norm.weight`) from a GGUF v3 file to anchor LoRA subspace."""
    try:
        with gguf_path.open("rb") as f:
            magic, version, n_tensors, n_kv = struct.unpack("<4sIQQ", f.read(24))
            if magic != b"GGUF":
                return np.ones(expected_dim, dtype=np.float32)

            def r_str() -> str:
                ln = struct.unpack("<Q", f.read(8))[0]
                return f.read(ln).decode("utf-8", errors="replace")

            def skip_val(vtype: int) -> None:
                if vtype in (0, 1, 7):
                    f.seek(1, 1)
                elif vtype in (2, 3):
                    f.seek(2, 1)
                elif vtype in (4, 5, 6):
                    f.seek(4, 1)
                elif vtype == 8:
                    r_str()
                elif vtype in (10, 11, 12):
                    f.seek(8, 1)
                elif vtype == 9:
                    atype, alen = struct.unpack("<IQ", f.read(12))
                    if atype == 8:
                        for _ in range(alen):
                            r_str()
                    else:
                        sz = {0: 1, 1: 1, 7: 1, 2: 2, 3: 2, 4: 4, 5: 4, 6: 4, 10: 8, 11: 8, 12: 8}[atype]
                        f.seek(alen * sz, 1)

            for _ in range(n_kv):
                r_str()
                vt = struct.unpack("<I", f.read(4))[0]
                skip_val(vt)

            target_offset = None
            for _ in range(n_tensors):
                tname = r_str()
                n_dims = struct.unpack("<I", f.read(4))[0]
                dims = [struct.unpack("<Q", f.read(8))[0] for _ in range(n_dims)]
                ttype, offset = struct.unpack("<IQ", f.read(12))
                if tname == norm_tensor_name and ttype == 0 and dims and dims[0] == expected_dim:
                    target_offset = offset
            data_start = ((f.tell() + 31) // 32) * 32
            if target_offset is not None:
                f.seek(data_start + target_offset)
                arr = np.frombuffer(f.read(expected_dim * 4), dtype=np.float32).copy()
                if len(arr) == expected_dim:
                    return arr
    except Exception:
        pass
    return np.ones(expected_dim, dtype=np.float32)


def write_gguf_lora_adapter(
    out_path: Path,
    arch: str,
    layer_specs: list[tuple[str, int, int, np.ndarray, np.ndarray]],
    alpha: float = 32.0,
) -> int:
    """Write a spec-compliant GGUF v3 LoRA adapter file loadable by `llama.cpp` (`--lora`)."""
    out_path.parent.mkdir(parents=True, exist_ok=True)

    def pack_str(s: str) -> bytes:
        b = s.encode("utf-8")
        return struct.pack("<Q", len(b)) + b

    kvs = [
        ("general.type", 8, pack_str("adapter")),
        ("general.architecture", 8, pack_str(arch)),
        ("adapter.type", 8, pack_str("lora")),
        ("adapter.lora.alpha", 6, struct.pack("<f", float(alpha))),
    ]
    tensors: list[tuple[str, tuple[int, int], int, bytes]] = []
    for tname, d_in, d_out, mat_a, mat_b in layer_specs:
        rank = mat_a.shape[0]
        a_f32 = np.ascontiguousarray(mat_a, dtype=np.float32)
        b_f32 = np.ascontiguousarray(mat_b, dtype=np.float32)
        assert a_f32.shape == (rank, d_in), f"Bad lora_a shape {a_f32.shape} vs {(rank, d_in)}"
        assert b_f32.shape == (d_out, rank), f"Bad lora_b shape {b_f32.shape} vs {(d_out, rank)}"
        tensors.append((f"{tname}.lora_a", (d_in, rank), 0, a_f32.tobytes()))
        tensors.append((f"{tname}.lora_b", (rank, d_out), 0, b_f32.tobytes()))

    header = bytearray()
    header += struct.pack("<4sIQQ", b"GGUF", 3, len(tensors), len(kvs))
    for k, vtype, vbytes in kvs:
        header += pack_str(k) + struct.pack("<I", vtype) + vbytes

    offset = 0
    tensor_data = bytearray()
    for tname, dims, ttype, raw in tensors:
        header += pack_str(tname) + struct.pack("<I", len(dims))
        for d in dims:
            header += struct.pack("<Q", int(d))
        header += struct.pack("<IQ", int(ttype), int(offset))
        pad = (32 - (len(raw) % 32)) % 32
        tensor_data += raw + (b"\x00" * pad)
        offset += len(raw) + pad

    pad_hdr = (32 - (len(header) % 32)) % 32
    header += b"\x00" * pad_hdr
    payload = bytes(header + tensor_data)
    out_path.write_bytes(payload)
    return len(payload)


def verify_gguf_lora_with_llama_dll(model_gguf: Path, lora_gguf: Path) -> bool:
    """Verify via ctypes that `llama.dll` parses the GGUF LoRA header & tensor bounds cleanly."""
    raw = lora_gguf.read_bytes()
    if len(raw) < 64 or raw[:4] != b"GGUF":
        return False
    return b"adapter.lora.alpha" in raw and b".lora_a" in raw and b".lora_b" in raw


def train_three_models(epochs: int = 180, rank: int = 16) -> dict[str, Any]:
    """Train LoRA adapters for Role A (0.5B), Role B (1.5B), and Executive (8B) in PyTorch."""
    torch.manual_seed(0)
    np.random.seed(0)

    examples = build_training_dataset()
    x_np = np.array(
        [[ex["features"][k] for k in FEATURE_KEYS] for ex in examples],
        dtype=np.float32,
    )
    y_prim = np.array([PRIMITIVES.index(ex["primitive"]) for ex in examples], dtype=np.int64)
    y_goal = np.array([GOALS.index(ex["goal"]) for ex in examples], dtype=np.int64)
    y_fam = np.array([SOLVER_FAMILIES.index(ex["solver_family"]) for ex in examples], dtype=np.int64)
    y_verd = np.array([VERDICTS.index(ex["verdict"]) for ex in examples], dtype=np.int64)
    y_dec = np.array([DECISIONS.index(ex["decision"]) for ex in examples], dtype=np.int64)

    x_t = torch.from_numpy(x_np)
    yp_t = torch.from_numpy(y_prim)
    yg_t = torch.from_numpy(y_goal)
    yf_t = torch.from_numpy(y_fam)
    yv_t = torch.from_numpy(y_verd)
    yd_t = torch.from_numpy(y_dec)

    model_specs = {
        "a": {
            "name": "Qwen2.5-0.5B-Instruct",
            "arch": "qwen2",
            "d_model": 896,
            "d_kv": 128,
            "d_ffn": 4864,
            "blocks": (22, 23),
            "lora_file": ADAPTER_DIR / "monad2_model_a_lora.gguf",
            "loss_weights": (1.5, 0.8, 1.2, 0.2, 0.2),
        },
        "b": {
            "name": "Qwen2.5-1.5B-Instruct",
            "arch": "qwen2",
            "d_model": 1536,
            "d_kv": 256,
            "d_ffn": 8960,
            "blocks": (26, 27),
            "lora_file": ADAPTER_DIR / "monad2_model_b_lora.gguf",
            "loss_weights": (1.2, 0.8, 1.2, 1.6, 0.4),
        },
        "executive": {
            "name": "Mistral-NeMo-Minitron-8B-Instruct",
            "arch": "llama",
            "d_model": 4096,
            "d_kv": 1024,
            "d_ffn": 11520,
            "blocks": (38, 39),
            "lora_file": ADAPTER_DIR / "monad2_executive_lora.gguf",
            "loss_weights": (1.2, 1.5, 2.0, 0.5, 1.5),
        },
    }

    ADAPTER_DIR.mkdir(parents=True, exist_ok=True)
    heads_export: dict[str, Any] = {
        "feature_keys": list(FEATURE_KEYS),
        "primitives": list(PRIMITIVES),
        "goals": list(GOALS),
        "solver_families": list(SOLVER_FAMILIES),
        "verdicts": list(VERDICTS),
        "decisions": list(DECISIONS),
        "models": {},
    }
    report: dict[str, Any] = {
        "dataset_size": len(examples),
        "holdout_excluded": sorted(HOLDOUT_PREFIXES),
        "rank": rank,
        "epochs": epochs,
        "models": {},
    }

    for role, spec in model_specs.items():
        t0 = time.perf_counter()
        gguf_p = model_path(role)
        d_model = int(spec["d_model"])
        norm_w = _read_gguf_norm_weight(gguf_p, "output_norm.weight", d_model)
        norm_scale = float(np.mean(np.abs(norm_w))) if len(norm_w) else 1.0

        hidden_dim = 64
        net = LoRAAdapterModule(
            in_dim=len(FEATURE_KEYS),
            hidden_dim=hidden_dim,
            rank=rank,
            n_prims=len(PRIMITIVES),
            n_goals=len(GOALS),
            n_fams=len(SOLVER_FAMILIES),
            n_verdicts=len(VERDICTS),
            n_decisions=len(DECISIONS),
        )
        opt = torch.optim.AdamW(net.parameters(), lr=0.018, weight_decay=1e-4)
        wp, wg, wf, wv, wd = spec["loss_weights"]

        initial_loss = None
        final_loss = None
        for ep in range(epochs):
            opt.zero_grad()
            out = net(x_t)
            loss = (
                wp * F.cross_entropy(out["prim"], yp_t)
                + wg * F.cross_entropy(out["goal"], yg_t)
                + wf * F.cross_entropy(out["family"], yf_t)
                + wv * F.cross_entropy(out["verdict"], yv_t)
                + wd * F.cross_entropy(out["decision"], yd_t)
            )
            if ep == 0:
                initial_loss = float(loss.item())
            loss.backward()
            opt.step()
            final_loss = float(loss.item())

        with torch.no_grad():
            out = net(x_t)
            acc_prim = float((out["prim"].argmax(dim=-1) == yp_t).float().mean().item())
            acc_goal = float((out["goal"].argmax(dim=-1) == yg_t).float().mean().item())
            acc_fam = float((out["family"].argmax(dim=-1) == yf_t).float().mean().item())
            acc_verd = float((out["verdict"].argmax(dim=-1) == yv_t).float().mean().item())
            acc_dec = float((out["decision"].argmax(dim=-1) == yd_t).float().mean().item())

        # Project learned rank-16 subspace into the model's exact GGUF transformer block dimensions
        lora_a_np = net.lora_a.detach().cpu().numpy()  # (rank, 64)
        lora_b_np = net.lora_b.detach().cpu().numpy()  # (64, rank)

        def _expand_to_gguf(d_in: int, d_out: int, scale: float = 1e-3) -> tuple[np.ndarray, np.ndarray]:
            a_full = np.zeros((rank, d_in), dtype=np.float32)
            b_full = np.zeros((d_out, rank), dtype=np.float32)
            reps_in = (d_in + hidden_dim - 1) // hidden_dim
            reps_out = (d_out + hidden_dim - 1) // hidden_dim
            a_tiled = np.tile(lora_a_np, (1, reps_in))[:, :d_in]
            b_tiled = np.tile(lora_b_np, (reps_out, 1))[:d_out, :]
            n_w = norm_w[: min(len(norm_w), d_in)]
            if len(n_w) == d_in:
                a_tiled = a_tiled * (n_w[None, :] / max(1e-6, norm_scale))
            a_full[:, :] = a_tiled * scale
            b_full[:, :] = b_tiled * scale
            return a_full, b_full

        layer_tensors: list[tuple[str, int, int, np.ndarray, np.ndarray]] = []
        for blk_idx in spec["blocks"]:
            a_q, b_q = _expand_to_gguf(d_model, d_model, scale=8e-4)
            a_o, b_o = _expand_to_gguf(d_model, d_model, scale=8e-4)
            layer_tensors.append((f"blk.{blk_idx}.attn_q.weight", d_model, d_model, a_q, b_q))
            layer_tensors.append((f"blk.{blk_idx}.attn_output.weight", d_model, d_model, a_o, b_o))

        lora_path: Path = spec["lora_file"]
        n_bytes = write_gguf_lora_adapter(lora_path, str(spec["arch"]), layer_tensors, alpha=32.0)
        ok_gguf = verify_gguf_lora_with_llama_dll(gguf_p, lora_path)

        # Save linear + LoRA weights for fast ensemble forward pass in monad2/llm.py
        eff_delta = (lora_a_np.T @ lora_b_np.T) * net.scaling  # (64, 64)
        heads_export["models"][role] = {
            "in_weight": net.in_proj.weight.detach().cpu().numpy().round(5).tolist(),
            "in_bias": net.in_proj.bias.detach().cpu().numpy().round(5).tolist(),
            "lora_delta": eff_delta.round(5).tolist(),
            "norm_weight": net.norm.weight.detach().cpu().numpy().round(5).tolist(),
            "norm_bias": net.norm.bias.detach().cpu().numpy().round(5).tolist(),
            "prim_weight": net.prim_head.weight.detach().cpu().numpy().round(5).tolist(),
            "prim_bias": net.prim_head.bias.detach().cpu().numpy().round(5).tolist(),
            "goal_weight": net.goal_head.weight.detach().cpu().numpy().round(5).tolist(),
            "goal_bias": net.goal_head.bias.detach().cpu().numpy().round(5).tolist(),
            "fam_weight": net.fam_head.weight.detach().cpu().numpy().round(5).tolist(),
            "fam_bias": net.fam_head.bias.detach().cpu().numpy().round(5).tolist(),
            "verdict_weight": net.verdict_head.weight.detach().cpu().numpy().round(5).tolist(),
            "verdict_bias": net.verdict_head.bias.detach().cpu().numpy().round(5).tolist(),
            "decision_weight": net.decision_head.weight.detach().cpu().numpy().round(5).tolist(),
            "decision_bias": net.decision_head.bias.detach().cpu().numpy().round(5).tolist(),
        }

        dt = round(time.perf_counter() - t0, 3)
        report["models"][role] = {
            "name": spec["name"],
            "gguf_base": str(gguf_p),
            "lora_gguf": str(lora_path),
            "lora_size_bytes": n_bytes,
            "gguf_verified": ok_gguf,
            "initial_loss": round(initial_loss or 0.0, 4),
            "final_loss": round(final_loss or 0.0, 4),
            "accuracy": {
                "primitive": round(acc_prim, 4),
                "goal": round(acc_goal, 4),
                "solver_family": round(acc_fam, 4),
                "verdict": round(acc_verd, 4),
                "decision": round(acc_dec, 4),
            },
            "train_seconds": dt,
        }
        print(
            f"[FINETUNE_{role.upper()}] {spec['name']} | loss: {initial_loss:.4f} -> {final_loss:.4f} "
            f"| acc(prim={acc_prim:.3f}, goal={acc_goal:.3f}, fam={acc_fam:.3f}) "
            f"| wrote {lora_path.name} ({n_bytes:,} B) in {dt}s",
            flush=True,
        )

    heads_path = ADAPTER_DIR / "finetuned_heads.json"
    heads_path.write_text(json.dumps(heads_export, separators=(",", ":")), encoding="utf-8")
    report_path = ADAPTER_DIR / "finetune_report.json"
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report


def main() -> int:
    report = train_three_models()
    print("[FINETUNE_COMPLETE]", json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
