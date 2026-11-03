"""Monad(2) integration layer. Flags default off until a scorecard entry passes."""
from __future__ import annotations

import json
import os
import sys
import types
import urllib.request
from pathlib import Path

try:
    import llama_cpp as _llama_cpp_check  # noqa: F401
except ModuleNotFoundError:
    _shim_dir = Path(__file__).resolve().parents[2] / "monad(1)"
    if (_shim_dir / "llama_cpp").is_dir() and str(_shim_dir) not in sys.path:
        sys.path.append(str(_shim_dir))
    try:
        import llama_cpp as _llama_cpp_check  # noqa: F401
    except ModuleNotFoundError:
        _mod = types.ModuleType("llama_cpp")

        class _LlamaGrammar:
            def __init__(self, grammar_str: str) -> None:
                self._grammar = str(grammar_str)

            @classmethod
            def from_string(cls, grammar_str: str, verbose: bool = False) -> "_LlamaGrammar":
                if not isinstance(grammar_str, str) or not grammar_str.strip() or "root ::=" not in grammar_str:
                    raise ValueError("Invalid GBNF grammar")
                return cls(grammar_str)

            def __str__(self) -> str:
                return self._grammar

        class _Llama:
            def __init__(self, model_path: str, n_ctx: int = 1024, **kwargs) -> None:
                self.model_path = str(model_path)
                self.n_ctx = int(n_ctx)
                low = self.model_path.lower()
                if "0.5b" in low:
                    self.port = int(os.environ.get("INOS_PORT_A", "8087"))
                elif "1.5b" in low:
                    self.port = int(os.environ.get("INOS_PORT_B", "8088"))
                else:
                    self.port = int(os.environ.get("INOS_PORT_EXEC", "8089"))

            def create_chat_completion(
                self,
                messages: list[dict],
                temperature: float = 0.0,
                max_tokens: int = 128,
                seed: int = 0,
                grammar: _LlamaGrammar | str | None = None,
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
                    g_str = grammar._grammar if isinstance(grammar, _LlamaGrammar) else str(grammar)
                    if g_str:
                        payload["grammar"] = g_str
                req = urllib.request.Request(
                    f"http://127.0.0.1:{self.port}/v1/chat/completions",
                    data=json.dumps(payload).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                )
                with urllib.request.urlopen(req, timeout=120.0) as resp:
                    return json.loads(resp.read().decode("utf-8"))

        _mod.LlamaGrammar = _LlamaGrammar  # type: ignore[attr-defined]
        _mod.Llama = _Llama  # type: ignore[attr-defined]
        sys.modules["llama_cpp"] = _mod
