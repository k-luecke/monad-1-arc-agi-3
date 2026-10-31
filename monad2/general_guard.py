"""Guards for the coordination path.

Per-game solver methods are wrapped so a call is visible, and the tier that
invokes them is skipped while those solvers are disabled. A static scan rejects
known game-name literals on the modules that propose moves. Schema records are
checked for game ids, colors, and absolute coordinates. Holdout prefixes cannot
write a schema.
"""
from __future__ import annotations

import ast
from pathlib import Path

# Denylist only. These strings select nothing. They are what the scan forbids
# inside the modules that propose a move.
KNOWN_GAME_PREFIXES = frozenset(
    {
        "ar25",
        "bp35",
        "cd82",
        "cn04",
        "dc22",
        "ft09",
        "g50t",
        "ka59",
        "lf52",
        "lp85",
        "ls20",
        "m0r0",
        "r11l",
        "re86",
        "s5i5",
        "sb26",
        "sc25",
        "sk48",
        "sp80",
        "su15",
        "tn36",
        "tr87",
        "tu93",
        "vc33",
        "wa30",
    }
)

ACTIVE_MODULES = (
    "coordinate.py",
    "schema.py",
    "canvas_stream.py",
    "scp.py",
    "memory.py",
    "runtime.py",
    "llm.py",
    "discovery.py",
    "primitives.py",
    "roles.py",
    "predicates.py",
    "menu.py",
    "planmode.py",
)

HITS: list[str] = []


def reset_hits() -> None:
    HITS.clear()


def arm_solver_guard(agent) -> int:
    """Replace each per-game solver with a recorder. Returns how many were armed."""
    none_names = tuple(getattr(type(agent), "_GAME_SPECIFIC_SOLVERS_RETURN_NONE", ()) or ())
    empty_names = tuple(getattr(type(agent), "_GAME_SPECIFIC_SOLVERS_RETURN_EMPTY", ()) or ())
    armed = 0
    for name in none_names:
        setattr(agent, name, _recorder(name, None))
        armed += 1
    for name in empty_names:
        setattr(agent, name, _recorder(name, []))
        armed += 1
    agent._m2_solver_guard_armed = armed
    return armed


def _recorder(name: str, empty):
    def wrapped(*_args, **_kwargs):
        HITS.append(name)
        return empty

    wrapped.__name__ = name
    return wrapped


def assert_solvers_unreached() -> None:
    if HITS:
        names = ", ".join(HITS[:8])
        raise AssertionError(f"per-game solver path reached: {names}")


def static_violations(root: Path | None = None) -> list[str]:
    """AST scan: a known game prefix as a string literal on the active path."""
    base = root or Path(__file__).resolve().parent
    found = []
    for name in ACTIVE_MODULES:
        path = base / name
        if not path.is_file():
            found.append(f"{name}: missing")
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Compare):
                constants = [
                    item.value.lower()
                    for item in [node.left, *node.comparators]
                    if isinstance(item, ast.Constant) and isinstance(item.value, str)
                ]
                hit = [item for item in constants if item in KNOWN_GAME_PREFIXES]
                if hit:
                    found.append(f"{name}:{node.lineno}: compare {hit}")
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                if node.value.lower() in KNOWN_GAME_PREFIXES:
                    found.append(f"{name}:{node.lineno}: literal {node.value.lower()}")
            if isinstance(node, ast.Dict):
                for key in node.keys:
                    if isinstance(key, ast.Constant) and isinstance(key.value, str) and key.value.lower() in KNOWN_GAME_PREFIXES:
                        found.append(f"{name}:{key.lineno}: dispatch key {key.value.lower()}")
    return found


def solver_catalog_ok(agent_cls) -> bool:
    none_names = tuple(getattr(agent_cls, "_GAME_SPECIFIC_SOLVERS_RETURN_NONE", ()))
    empty_names = tuple(getattr(agent_cls, "_GAME_SPECIFIC_SOLVERS_RETURN_EMPTY", ()))
    return len(none_names) + len(empty_names) == 27
