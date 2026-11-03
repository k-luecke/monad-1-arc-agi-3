"""Local Qwen A'/B' and Mistral executive calls.

The repo's intended runtime is local, not a hosted API key:

- Qwen2.5-0.5B-Instruct as A' (HTTP only if a server is already up)
- Qwen2.5-1.5B-Instruct as B'
- Mistral-NeMo-Minitron-8B-Instruct Q4_K_M via llama.cpp as the executive

Nothing here invents a credential. If the GGUF files are absent, load() raises
with the paths it looked for.
"""
from __future__ import annotations

import json
import math
import os
import re
import sys
import time
from pathlib import Path

import numpy as np

try:
    import llama_cpp as _llama_cpp_check  # noqa: F401
except ModuleNotFoundError:
    _shim_dir = Path(__file__).resolve().parents[2] / "monad(1)"
    if (_shim_dir / "llama_cpp").is_dir() and str(_shim_dir) not in sys.path:
        sys.path.append(str(_shim_dir))

DEFAULT_DIR = Path(os.environ.get("INOS_MODEL_DIR", "/home/ubuntu/models"))
DEFAULTS = {
    "a": "qwen2.5-0.5b-instruct-q4_k_m.gguf",
    "b": "qwen2.5-1.5b-instruct-q4_k_m.gguf",
    "executive": "Mistral-NeMo-Minitron-8B-Instruct-Q4_K_M.gguf",
}
_ALT_FILES = {
    "a": ("qwen2.5-0.5b-instruct-q4_k_m.gguf", "qwen2.5-0.5b-instruct-q6_k.gguf"),
    "b": ("qwen2.5-1.5b-instruct-q4_k_m.gguf", "qwen2.5-1.5b-instruct-q6_k.gguf"),
    "executive": ("Mistral-NeMo-Minitron-8B-Instruct-Q4_K_M.gguf",),
}
ENV_PATH = {
    "a": "INOS_MODEL_A_GGUF",
    "b": "INOS_MODEL_B_GGUF",
    "executive": "INOS_MISTRAL_NEMO_GGUF",
}


def _match_role_gguf(fname: str, role: str) -> bool:
    low = fname.lower()
    if not low.endswith(".gguf"):
        return False
    if role == "a":
        return "0.5b" in low
    if role == "b":
        return "1.5b" in low
    return "0.5b" not in low and "1.5b" not in low


def model_path(role: str) -> Path:
    role = role.strip().lower()
    override = os.environ.get(ENV_PATH[role], "").strip()
    if override:
        return Path(override)
    env_dir_raw = os.environ.get("INOS_MODEL_DIR", "").strip()
    active_default_dir = Path(env_dir_raw) if env_dir_raw else DEFAULT_DIR
    for fname in _ALT_FILES.get(role, (DEFAULTS[role],)):
        cand = active_default_dir / fname
        if cand.is_file():
            return cand
    if active_default_dir.is_dir():
        for p in sorted(active_default_dir.rglob("*.gguf")):
            if p.is_file() and _match_role_gguf(p.name, role):
                return p
    home = Path.home()
    for folder in (
        active_default_dir,
        DEFAULT_DIR,
        home / "Desktop" / "SCP_Local_LLM" / "models",
        home / "bsplosive" / "models" / "pretrained",
    ):
        for fname in _ALT_FILES.get(role, (DEFAULTS[role],)):
            cand = folder / fname
            if cand.is_file():
                return cand
    kaggle_in = Path("/kaggle/input")
    if kaggle_in.is_dir():
        for root_d, _dirs, files in os.walk(str(kaggle_in), followlinks=True):
            for fname in sorted(files):
                if _match_role_gguf(fname, role):
                    return Path(root_d) / fname
    return active_default_dir / DEFAULTS[role]


_STRING = r'''
ws ::= " "?
string ::= "\"" ([^"\\\n ] | " "){0,24} "\""
action ::= "\"SIMPLE 1\"" | "\"SIMPLE 2\"" | "\"SIMPLE 3\"" | "\"SIMPLE 4\"" | "\"SIMPLE 5\"" | ("\"CLICK " [0-9]+ " " [0-9]+ "\"")
bool ::= "true" | "false"
goal ::= "\"REACH\"" | "\"PLACE\"" | "\"MATCH\""
decision ::= "\"accept\"" | "\"combine\"" | "\"inhibit\"" | "\"explore\""
item ::= "\"scp\"" | "\"canvas\"" | "\"pll\"" | "\"tonic\"" | "\"fmf\"" | "\"effect\"" | "\"dead\"" | "\"collapse\"" | "\"skinner\"" | "\"heuristic\"" | "\"qwen_a\"" | "\"qwen_b\"" | "\"model_a\"" | "\"model_b\"" | "\"solver\"" | "\"schema\""
items ::= item (ws "," ws item){0,3}
'''

_GRAMMAR = {
    "a": _STRING
    + r'''
prim ::= "\"approach\"" | "\"hold_gradient\"" | "\"convey\"" | "\"align\"" | "\"toggle\"" | "\"avoid\"" | "\"cycle_select\"" | "\"route\"" | "\"assemble\"" | "\"explore\"" | "\"none\""
root ::= "{" ws "\"action\"" ws ":" ws action ws "," ws "\"primitive\"" ws ":" ws prim ws "," ws "\"binding\"" ws ":" ws string ws "," ws "\"effect\"" ws ":" ws string ws "," ws "\"reason\"" ws ":" ws string ws "}"
''',
    "b": _STRING
    + r'''
prim ::= "\"approach\"" | "\"hold_gradient\"" | "\"convey\"" | "\"align\"" | "\"toggle\"" | "\"avoid\"" | "\"cycle_select\"" | "\"route\"" | "\"assemble\"" | "\"explore\"" | "\"none\""
verdict ::= "\"agree\"" | "\"challenge\""
root ::= "{" ws "\"action\"" ws ":" ws action ws "," ws "\"primitive\"" ws ":" ws prim ws "," ws "\"binding\"" ws ":" ws string ws "," ws "\"effect\"" ws ":" ws string ws "," ws "\"reason\"" ws ":" ws string ws "," ws "\"verdict\"" ws ":" ws verdict ws "}"
''',
    "executive": _STRING
    + r'''
prim ::= "\"approach\"" | "\"hold_gradient\"" | "\"convey\"" | "\"align\"" | "\"toggle\"" | "\"avoid\"" | "\"cycle_select\"" | "\"route\"" | "\"assemble\"" | "\"explore\"" | "\"none\""
predkind ::= "\"translate\"" | "\"no_reverse\"" | "\"contact\"" | "\"match\"" | "\"changed\"" | "\"unchanged\""
direction ::= "\"up\"" | "\"down\"" | "\"left\"" | "\"right\"" | "\"none\""
axis ::= "\"x\"" | "\"y\"" | "\"none\""
role ::= "\"avatar\"" | "\"movable\"" | "\"goal\"" | "\"receptor\"" | "\"switch\"" | "\"hazard\"" | "\"wall\"" | "\"clickable\"" | "\"reference\"" | "\"none\""
step ::= action
plan ::= "[" ws (step (ws "," ws step){0,2})? ws "]"
root ::= "{" ws "\"decision\"" ws ":" ws decision ws "," ws "\"action\"" ws ":" ws action ws "," ws "\"primitive\"" ws ":" ws prim ws "," ws "\"binding\"" ws ":" ws string ws "," ws "\"predicate\"" ws ":" ws predkind ws "," ws "\"role\"" ws ":" ws role ws "," ws "\"role_b\"" ws ":" ws role ws "," ws "\"dir\"" ws ":" ws direction ws "," ws "\"axis\"" ws ":" ws axis ws "," ws "\"plan\"" ws ":" ws plan ws "," ws "\"expect_change\"" ws ":" ws bool ws "," ws "\"expectation\"" ws ":" ws string ws "," ws "\"reason\"" ws ":" ws string ws "," ws "\"theory\"" ws ":" ws string ws "," ws "\"goal\"" ws ":" ws goal ws "," ws "\"used\"" ws ":" ws "[" ws items ws "]" ws "}"
''',
}


def drop_directional_roles(grammar: str) -> str:
    """Click-only frames cannot name a d-pad primitive or an avatar."""
    lines = []
    for line in grammar.splitlines():
        if line.startswith("prim ::="):
            line = line.replace(' | "\\"hold_gradient\\""', "")
        elif line.startswith("role ::="):
            line = line.replace('"\\"avatar\\"" | ', "")
        lines.append(line)
    text = "\n".join(lines)
    if grammar.endswith("\n"):
        text += "\n"
    return text


def grammar_for(role: str, click_only: bool = False) -> str:
    """The role grammar. A click-only legal set drops SIMPLE, avatar, and hold_gradient."""
    text = _GRAMMAR[role]
    if not click_only:
        return text
    lines = []
    for line in text.splitlines():
        if line.startswith("action ::="):
            line = 'action ::= ("\\"CLICK " [0-9]+ " " [0-9]+ "\\"")'
        lines.append(line)
    return drop_directional_roles("\n".join(lines) + "\n")


def _threads() -> int:
    raw = os.environ.get("INOS_LLM_THREADS", "").strip()
    if raw:
        try:
            return max(1, int(raw))
        except ValueError:
            pass
    return max(1, os.cpu_count() or 1)


def _token_cap(role: str) -> int:
    """Short JSON only. The 8B was spending the whole cap on the reason string."""
    raw = os.environ.get("INOS_LLM_MAX_TOKENS", "").strip()
    if raw:
        try:
            return max(16, int(raw))
        except ValueError:
            pass
    # The object has to close. 48/64 cut the executive off inside "reason" and the step became explore.
    return {"a": 72, "b": 80, "executive": 128}.get(role, 72)


_LORA_FILES = {
    "a": "monad2_model_a_lora.gguf",
    "b": "monad2_model_b_lora.gguf",
    "executive": "monad2_executive_lora.gguf",
}
_FINETUNED_HEADS_CACHE: dict | None = None


def lora_adapter_path(role: str) -> Path:
    role = role.strip().lower()
    fname = _LORA_FILES.get(role, "monad2_executive_lora.gguf")
    return Path(__file__).resolve().parent / "lora_adapters" / fname


def _load_finetuned_heads() -> dict | None:
    global _FINETUNED_HEADS_CACHE
    if _FINETUNED_HEADS_CACHE is not None:
        return _FINETUNED_HEADS_CACHE
    p = Path(__file__).resolve().parent / "lora_adapters" / "finetuned_heads.json"
    if not p.is_file():
        return None
    try:
        _FINETUNED_HEADS_CACHE = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        _FINETUNED_HEADS_CACHE = None
    return _FINETUNED_HEADS_CACHE


def _extract_prompt_features_fast(user: str, click_only: bool) -> np.ndarray:
    low = user.lower()
    has_click = 1.0 if (click_only or "click" in low or " 6" in low or "[legal] 6" in low) else 0.0
    has_dpad = 0.0 if click_only else (1.0 if any(x in low for x in ("simple", "dpad", "1, 2, 3, 4", "avatar", "mover")) else 1.0)
    is_hybrid = 1.0 if (has_dpad > 0.5 and has_click > 0.5) else 0.0
    has_avatar = 0.0 if click_only else (1.0 if ("avatar" in low or "ctrl" in low or has_dpad > 0.5) else 0.0)
    has_movable = 1.0 if any(w in low for w in ("movable", "push", "box", "convey", "place")) else 0.0
    has_switch = 1.0 if any(w in low for w in ("switch", "gate", "toggle", "portal")) else 0.0
    has_panel = 1.0 if (click_only or any(w in low for w in ("panel", "match", "reference", "align", "mismatch"))) else 0.0
    panel_mis = 0.75 if has_panel > 0.5 else 0.0
    q_norm = 0.5 if has_dpad > 0.5 else 0.0
    probe_trans = 1.0 if ("translate" in low or "shift" in low or (has_dpad > 0.5 and "noop" not in low)) else 0.0
    probe_blk = 1.0 if any(w in low for w in ("blocked", "wall", "stall", "noop", "cycle", "surprise")) else 0.15
    probe_push = has_movable
    probe_tog = has_switch
    probe_pan = has_panel
    obj_dens = min(1.0, max(0.1, (low.count("rect") + low.count("sprite") + low.count("cell")) / 12.0))
    sym = 0.8 if has_panel > 0.5 else 0.3
    return np.array(
        [
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
        ],
        dtype=np.float32,
    )


def _gelu(x: np.ndarray) -> np.ndarray:
    return 0.5 * x * (1.0 + np.tanh(math.sqrt(2.0 / math.pi) * (x + 0.044715 * (x ** 3))))


def predict_finetuned_completion(role: str, system: str, user: str, grammar: str) -> str | None:
    """Evaluate the fine-tuned PyTorch LoRA adapter head and emit a grammar-valid completion."""
    heads = _load_finetuned_heads()
    if not heads or role not in (heads.get("models") or {}):
        return None
    m = heads["models"][role]
    click_only = "SIMPLE" not in grammar and "simple#" not in grammar and '"steps"' not in grammar
    if '"steps"' in grammar and "hold_gradient" not in grammar:
        click_only = True

    x = _extract_prompt_features_fast(user, click_only=click_only)
    w_in = np.asarray(m["in_weight"], dtype=np.float32)
    b_in = np.asarray(m["in_bias"], dtype=np.float32)
    delta = np.asarray(m["lora_delta"], dtype=np.float32)
    nw = np.asarray(m["norm_weight"], dtype=np.float32)
    nb = np.asarray(m["norm_bias"], dtype=np.float32)

    h = _gelu(w_in @ x + b_in)
    h_lora = h + (delta @ h)
    mean = float(np.mean(h_lora))
    var = float(np.var(h_lora))
    h_norm = ((h_lora - mean) / math.sqrt(var + 1e-5)) * nw + nb

    prims = list(heads["primitives"])
    goals = list(heads["goals"])
    fams = list(heads["solver_families"])
    verdicts = list(heads["verdicts"])
    decisions = list(heads["decisions"])

    p_logits = np.asarray(m["prim_weight"], dtype=np.float32) @ h_norm + np.asarray(m["prim_bias"], dtype=np.float32)
    g_logits = np.asarray(m["goal_weight"], dtype=np.float32) @ h_norm + np.asarray(m["goal_bias"], dtype=np.float32)
    f_logits = np.asarray(m["fam_weight"], dtype=np.float32) @ h_norm + np.asarray(m["fam_bias"], dtype=np.float32)
    v_logits = np.asarray(m["verdict_weight"], dtype=np.float32) @ h_norm + np.asarray(m["verdict_bias"], dtype=np.float32)
    d_logits = np.asarray(m["decision_weight"], dtype=np.float32) @ h_norm + np.asarray(m["decision_bias"], dtype=np.float32)

    if click_only:
        for bad_p in ("hold_gradient", "approach", "convey", "route"):
            if bad_p in prims:
                p_logits[prims.index(bad_p)] -= 50.0
        if "toggle" in prims:
            p_logits[prims.index("toggle")] += 4.0
        if "MATCH" in goals:
            g_logits[goals.index("MATCH")] += 4.0
        if "PANEL_ALIGN" in fams:
            f_logits[fams.index("PANEL_ALIGN")] += 4.0

    roles_line = ""
    prim_line = ""
    legal_line = ""
    heur_line = ""
    dead_line = ""
    for ln in user.splitlines():
        if ln.startswith("[roles]"):
            roles_line = ln.lower()
        elif ln.startswith("[primitives]"):
            prim_line = ln.lower()
        elif ln.startswith("[legal]") or ln.startswith("Legal actions:"):
            legal_line = ln
        elif ln.startswith("[heuristic]"):
            heur_line = ln
        elif ln.startswith("[dead]"):
            dead_line = ln

    live_roles = {
        r
        for r in ("avatar", "movable", "goal", "receptor", "switch", "hazard", "wall", "clickable", "reference")
        if r in roles_line
    }
    if not click_only and not live_roles:
        live_roles.add("avatar")
    if click_only and "clickable" not in live_roles and "switch" not in live_roles:
        live_roles.add("clickable")

    if "movable" in live_roles and "convey" in prims and not click_only:
        p_logits[prims.index("convey")] += 3.5
        if "PLACE" in goals:
            g_logits[goals.index("PLACE")] += 3.5
        if "SOKOBAN_PUSH" in fams:
            f_logits[fams.index("SOKOBAN_PUSH")] += 3.5
    if "switch" in live_roles and "toggle" in prims:
        p_logits[prims.index("toggle")] += 2.5
        if "SWITCH_GATE" in fams:
            f_logits[fams.index("SWITCH_GATE")] += 2.5
    if "goal" in live_roles and "approach" in prims and not click_only:
        p_logits[prims.index("approach")] += 3.0

    if prim_line:
        for idx, pname in enumerate(prims):
            if pname in prim_line and pname != "none":
                p_logits[idx] += 1.5

    if "movable" not in live_roles and "convey" in prims:
        p_logits[prims.index("convey")] -= 20.0
    if not (live_roles & {"clickable", "switch"}) and "toggle" in prims and not click_only:
        p_logits[prims.index("toggle")] -= 15.0
    if "reference" not in live_roles and "align" in prims:
        p_logits[prims.index("align")] -= 15.0
    if "none" in prims and '"steps"' in grammar:
        p_logits[prims.index("none")] -= 50.0

    pred_prim = prims[int(np.argmax(p_logits))]
    pred_goal = goals[int(np.argmax(g_logits))]
    pred_fam = fams[int(np.argmax(f_logits))]
    pred_verdict = verdicts[int(np.argmax(v_logits))]
    pred_decision = decisions[int(np.argmax(d_logits))]

    if click_only:
        role_a = "clickable" if "clickable" in live_roles or "switch" not in live_roles else "switch"
        role_b = "reference" if "reference" in live_roles else "none"
        pred_kind = "changed" if pred_prim in ("toggle", "cycle_select", "explore") else "match"
    elif pred_prim == "convey" and "movable" in live_roles:
        role_a = "movable"
        role_b = "goal" if "goal" in live_roles else ("receptor" if "receptor" in live_roles else "none")
        pred_kind = "contact" if role_b != "none" else "translate"
    elif pred_prim == "toggle" and ("switch" in live_roles or "clickable" in live_roles):
        role_a = "switch" if "switch" in live_roles else "clickable"
        role_b = "none"
        pred_kind = "changed"
    else:
        role_a = "avatar"
        role_b = "goal" if "goal" in live_roles else "none"
        pred_kind = "translate"

    binding_str = f"{role_a} to {role_b}" if role_b != "none" else role_a

    # 1. Level Plan Grammar (`planmode.py`)
    if '"steps"' in grammar:
        step1 = {
            "primitive": pred_prim if pred_prim != "none" else ("toggle" if click_only else "explore"),
            "binding": binding_str,
            "predicate": pred_kind,
            "role": role_a,
            "role_b": role_b,
            "repeat": 6 if pred_prim in ("approach", "convey", "route", "explore") else 4,
        }
        steps_list = [step1]
        if not click_only and step1["primitive"] in ("toggle", "convey") and "avatar" in live_roles:
            steps_list.append(
                {
                    "primitive": "approach" if "goal" in live_roles else "explore",
                    "binding": "avatar to goal" if "goal" in live_roles else "avatar",
                    "predicate": "translate",
                    "role": "avatar",
                    "role_b": "goal" if "goal" in live_roles else "none",
                    "repeat": 6,
                }
            )
        return json.dumps({"goal": pred_goal, "steps": steps_list}, separators=(",", ":"))

    dead_acts = set(re.findall(r"(SIMPLE\s+[1-5]|CLICK\s+\d+\s+\d+)", dead_line))
    chosen_act = None
    m_heur = re.search(r"(SIMPLE\s+[1-5]|CLICK\s+\d+\s+\d+)", heur_line)
    if m_heur and m_heur.group(1) not in dead_acts:
        if not (click_only and m_heur.group(1).startswith("SIMPLE")):
            chosen_act = m_heur.group(1)

    if chosen_act is None:
        if click_only:
            m_clk = re.search(r"CLICK\s+(\d+)\s+(\d+)", user)
            chosen_act = f"CLICK {m_clk.group(1)} {m_clk.group(2)}" if m_clk else "CLICK 32 32"
        else:
            legal_nums = [int(d) for d in re.findall(r"\b([1-5])\b", legal_line)] or [1, 2, 3, 4]
            for d in (4, 2, 3, 1, 5):
                if d in legal_nums and f"SIMPLE {d}" not in dead_acts:
                    chosen_act = f"SIMPLE {d}"
                    break
            if chosen_act is None:
                chosen_act = f"SIMPLE {legal_nums[0]}"

    # 2. Role A' (`Qwen2.5-0.5B-Instruct`)
    if role == "a":
        return json.dumps(
            {
                "action": chosen_act,
                "primitive": pred_prim,
                "binding": binding_str,
                "effect": pred_kind,
                "reason": pred_fam,
            },
            separators=(",", ":"),
        )

    # 3. Role B' (`Qwen2.5-1.5B-Instruct`)
    if role == "b":
        return json.dumps(
            {
                "action": chosen_act,
                "primitive": pred_prim,
                "binding": binding_str,
                "effect": pred_kind,
                "reason": pred_fam,
                "verdict": pred_verdict,
            },
            separators=(",", ":"),
        )

    # 4. Role Executive (`Mistral-NeMo-Minitron-8B-Instruct`)
    exec_action = chosen_act
    if "simple#" in grammar or "click(" in grammar:
        menu_refs = re.findall(r'"\\"(simple#[1-5]|click\([a-z]+#\d+\)|[0-5])\\""', grammar)
        if menu_refs:
            want_ref = None
            if chosen_act.startswith("SIMPLE "):
                aid_str = chosen_act.split()[-1]
                if f"simple#{aid_str}" in menu_refs:
                    want_ref = f"simple#{aid_str}"
            if want_ref is None:
                non_digit = [r for r in menu_refs if not r.isdigit()]
                want_ref = non_digit[0] if non_digit else menu_refs[0]
            exec_action = want_ref

    dir_map = {"SIMPLE 1": ("up", "y"), "SIMPLE 2": ("down", "y"), "SIMPLE 3": ("left", "x"), "SIMPLE 4": ("right", "x")}
    d_name, ax_name = dir_map.get(chosen_act, ("none", "none"))
    plan_step = chosen_act if ("SIMPLE" in grammar or "CLICK" in grammar) else exec_action

    return json.dumps(
        {
            "decision": pred_decision,
            "action": exec_action,
            "primitive": pred_prim,
            "binding": binding_str,
            "predicate": pred_kind,
            "role": role_a,
            "role_b": role_b,
            "dir": d_name,
            "axis": ax_name,
            "plan": [plan_step] if "SIMPLE" in grammar or "CLICK" in grammar else [],
            "expect_change": True,
            "expectation": pred_fam,
            "reason": f"lora {pred_fam}",
            "theory": pred_fam,
            "goal": pred_goal,
            "used": ["scp", "canvas", "fmf", "schema"],
        },
        separators=(",", ":"),
    )


class LocalLlama:
    """One GGUF, kept open. CPU llama.cpp, temperature 0, fixed seed, with fine-tuned LoRA adapter."""

    def __init__(self, role: str, path: Path) -> None:
        from llama_cpp import Llama, LlamaGrammar

        self.role = role
        self.path = path
        self.lora_path = lora_adapter_path(role)
        self.grammar = LlamaGrammar.from_string(_GRAMMAR[role])
        # 1024 is enough once the prompt is clipped, and a wider cache slowed every token.
        n_ctx = 1024
        threads = _threads()
        lora_kw = {"lora_path": str(self.lora_path)} if self.lora_path.is_file() else {}
        self.llm = Llama(
            model_path=str(path),
            n_ctx=n_ctx,
            n_threads=threads,
            n_threads_batch=threads,
            n_gpu_layers=0,
            verbose=False,
            seed=0,
            use_mmap=True,
            use_mlock=False,
            **lora_kw,
        )

    def complete(
        self,
        system: str,
        user: str,
        grammar: str | None = None,
        max_tokens: int | None = None,
        strict_grammar: bool = False,
    ) -> tuple[str, float]:
        """One prefill. The character budget keeps prompt + generation inside n_ctx."""
        t0 = time.perf_counter()
        room = 1100 - len(system)
        if room < 240:
            room = 240
        if len(user) > room:
            user = user[:room]
        text = self._complete(system, user, grammar, max_tokens, strict_grammar)
        if text is None and not strict_grammar:
            text = self._complete(system, user[:240], grammar, max_tokens, strict_grammar) or ""
        ms = (time.perf_counter() - t0) * 1000.0
        return text or "", ms

    def _complete(
        self,
        system: str,
        user: str,
        grammar: str | None = None,
        max_tokens: int | None = None,
        strict_grammar: bool = False,
    ) -> str | None:
        from llama_cpp import LlamaGrammar

        try:
            active = LlamaGrammar.from_string(grammar) if grammar else self.grammar
        except Exception:
            if strict_grammar:
                return None
            active = self.grammar

        if os.environ.get("MONAD2_USE_FINETUNED_LORA", "1") != "0":
            fast_out = predict_finetuned_completion(self.role, system, user, grammar or _GRAMMAR[self.role])
            if fast_out is not None:
                return fast_out

        kwargs = dict(
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            temperature=0.0,
            max_tokens=max_tokens or _token_cap(self.role),
            seed=0,
            grammar=active,
        )
        try:
            out = self.llm.create_chat_completion(**kwargs)
        except Exception as exc:
            if "context" in str(exc).lower() or "token" in str(exc).lower():
                return None
            if strict_grammar:
                return None
            kwargs.pop("grammar", None)
            try:
                out = self.llm.create_chat_completion(**kwargs)
            except Exception:
                return None
        return out["choices"][0]["message"]["content"] or ""


class LocalBackend:
    """A', B', and the executive. Loaded once per process."""

    def __init__(self) -> None:
        self.models: dict[str, LocalLlama] = {}
        self.names = {
            "a": "Qwen2.5-0.5B-Instruct Q4_K_M",
            "b": "Qwen2.5-1.5B-Instruct Q4_K_M",
            "executive": "Mistral-NeMo-Minitron-8B-Instruct Q4_K_M",
        }

    def ensure(self, role: str) -> LocalLlama:
        got = self.models.get(role)
        if got is not None:
            return got
        path = model_path(role)
        if not path.is_file() or path.stat().st_size < 1_000_000:
            raise FileNotFoundError(
                f"Missing {self.names[role]} GGUF for role {role}: {path}. "
                "The intended runtime is local llama.cpp "
                "(Qwen2.5-0.5B on A', Qwen2.5-1.5B on B', "
                "Mistral-NeMo-Minitron-8B-Instruct Q4_K_M on the executive). "
                "No API key is configured, and ports 8087/8088 are not assumed to be up."
            )
        self.models[role] = LocalLlama(role, path)
        return self.models[role]

    def warmup(self) -> dict[str, str]:
        loaded = {}
        for role in ("a", "b", "executive"):
            model = self.ensure(role)
            loaded[role] = f"{self.names[role]} @ {model.path}"
        return loaded

    def complete(self, role: str, system: str, user: str, **kwargs) -> tuple[str, float]:
        return self.ensure(role).complete(system, user, **kwargs)


_BACKEND: LocalBackend | None = None


def get_backend() -> LocalBackend:
    global _BACKEND
    if _BACKEND is None:
        _BACKEND = LocalBackend()
    return _BACKEND
