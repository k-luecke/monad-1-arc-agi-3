"""Local Qwen A'/B' and Mistral executive calls.

The repo's intended runtime is local, not a hosted API key:

- Qwen2.5-0.5B-Instruct as A' (HTTP only if a server is already up)
- Qwen2.5-1.5B-Instruct as B'
- Mistral-NeMo-Minitron-8B-Instruct Q4_K_M via llama.cpp as the executive

Nothing here invents a credential. If the GGUF files are absent, load() raises
with the paths it looked for.
"""
from __future__ import annotations

import os
import time
from pathlib import Path

DEFAULT_DIR = Path(os.environ.get("INOS_MODEL_DIR", "/home/ubuntu/models"))
DEFAULTS = {
    "a": "qwen2.5-0.5b-instruct-q4_k_m.gguf",
    "b": "qwen2.5-1.5b-instruct-q4_k_m.gguf",
    "executive": "Mistral-NeMo-Minitron-8B-Instruct-Q4_K_M.gguf",
}
ENV_PATH = {
    "a": "INOS_MODEL_A_GGUF",
    "b": "INOS_MODEL_B_GGUF",
    "executive": "INOS_MISTRAL_NEMO_GGUF",
}


def model_path(role: str) -> Path:
    override = os.environ.get(ENV_PATH[role], "").strip()
    if override:
        return Path(override)
    return DEFAULT_DIR / DEFAULTS[role]


_STRING = r'''
ws ::= " "?
string ::= "\"" ([^"\\\n ] | " ")* "\""
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
root ::= "{" ws "\"action\"" ws ":" ws action ws "," ws "\"effect\"" ws ":" ws string ws "," ws "\"reason\"" ws ":" ws string ws "}"
''',
    "b": _STRING
    + r'''
verdict ::= "\"agree\"" | "\"challenge\""
root ::= "{" ws "\"action\"" ws ":" ws action ws "," ws "\"effect\"" ws ":" ws string ws "," ws "\"reason\"" ws ":" ws string ws "," ws "\"verdict\"" ws ":" ws verdict ws "}"
''',
    "executive": _STRING
    + r'''
step ::= action
plan ::= "[" ws (step (ws "," ws step){0,2})? ws "]"
root ::= "{" ws "\"decision\"" ws ":" ws decision ws "," ws "\"action\"" ws ":" ws action ws "," ws "\"plan\"" ws ":" ws plan ws "," ws "\"expect_change\"" ws ":" ws bool ws "," ws "\"expectation\"" ws ":" ws string ws "," ws "\"reason\"" ws ":" ws string ws "," ws "\"theory\"" ws ":" ws string ws "," ws "\"goal\"" ws ":" ws goal ws "," ws "\"used\"" ws ":" ws "[" ws items ws "]" ws "}"
''',
}


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
    return {"a": 48, "b": 48, "executive": 64}.get(role, 48)


class LocalLlama:
    """One GGUF, kept open. CPU llama.cpp, temperature 0, fixed seed."""

    def __init__(self, role: str, path: Path) -> None:
        from llama_cpp import Llama, LlamaGrammar

        self.role = role
        self.path = path
        self.grammar = LlamaGrammar.from_string(_GRAMMAR[role])
        n_ctx = 1024 if role == "executive" else 768
        threads = _threads()
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
        )

    def complete(self, system: str, user: str) -> tuple[str, float]:
        t0 = time.perf_counter()
        kwargs = dict(
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            temperature=0.0,
            max_tokens=_token_cap(self.role),
            seed=0,
            grammar=self.grammar,
        )
        try:
            out = self.llm.create_chat_completion(**kwargs)
        except Exception:
            kwargs.pop("grammar", None)
            out = self.llm.create_chat_completion(**kwargs)
        text = out["choices"][0]["message"]["content"] or ""
        ms = (time.perf_counter() - t0) * 1000.0
        return text, ms


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

    def complete(self, role: str, system: str, user: str) -> tuple[str, float]:
        return self.ensure(role).complete(system, user)


_BACKEND: LocalBackend | None = None


def get_backend() -> LocalBackend:
    global _BACKEND
    if _BACKEND is None:
        _BACKEND = LocalBackend()
    return _BACKEND
