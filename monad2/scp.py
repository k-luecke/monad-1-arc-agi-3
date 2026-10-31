"""SCP-for-ARC: grid -> object IR -> compact projection, plus a D0-D4 move ladder.

Port of the T11 design (observation IR, semantic IR, compact projection, and a
legality / no-op / hazard ladder) onto ARC grids. No game id is read. Colors are
ranked by frequency so a palette permutation does not change the projection.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field


@dataclass
class ObjectIR:
    role: int
    size: int
    h: int
    w: int
    fill_q: int
    cells: int
    r0: int
    c0: int
    color: int


@dataclass
class Projection:
    bg_role: int
    n_objects: int
    n_colors: int
    objects: list[ObjectIR] = field(default_factory=list)
    controllable_role: int | None = None
    hud_edge_frac_q: int = 0
    feedback: str = "start"
    legal: tuple[int, ...] = ()
    panel_mismatch: int = 0

    def tokens(self) -> list[str]:
        toks = [
            f"nobj:{min(self.n_objects, 12)}",
            f"ncol:{min(self.n_colors, 8)}",
            f"fb:{self.feedback}",
            f"legal:{','.join(str(a) for a in self.legal)}",
            f"hud:{self.hud_edge_frac_q}",
            f"panel:{min(self.panel_mismatch, 9)}",
        ]
        if self.controllable_role is not None:
            toks.append(f"ctrl:{self.controllable_role}")
        for obj in self.objects[:8]:
            toks.append(
                f"o:{obj.role}:{_size_bucket(obj.size)}:{_aspect(obj.h, obj.w)}:{obj.fill_q}:{_quad(obj.r0, obj.c0)}"
            )
        return toks


def _size_bucket(n: int) -> int:
    if n <= 4:
        return 0
    if n <= 16:
        return 1
    if n <= 64:
        return 2
    return 3


def _aspect(h: int, w: int) -> int:
    lo, hi = min(h, w), max(h, w)
    if hi <= 0:
        return 0
    q = lo / hi
    if q > 0.8:
        return 2
    if q > 0.4:
        return 1
    return 0


def _quad(r: int, c: int) -> int:
    return (0 if r < 32 else 2) + (0 if c < 32 else 1)


def _grid(grid) -> list[list[int]]:
    if hasattr(grid, "tolist"):
        grid = grid.tolist()
    return grid


def _mode_color(grid: list[list[int]]) -> int:
    counts: Counter[int] = Counter()
    for row in grid:
        counts.update(int(v) for v in row)
    return counts.most_common(1)[0][0] if counts else 0


def _components(grid: list[list[int]], bg: int) -> list[ObjectIR]:
    h = len(grid)
    w = len(grid[0]) if h else 0
    seen = [[False] * w for _ in range(h)]
    color_count: Counter[int] = Counter()
    for row in grid:
        for v in row:
            if int(v) != bg:
                color_count[int(v)] += 1
    ranked = [c for c, _n in color_count.most_common()]
    role_of = {c: i for i, c in enumerate(ranked)}
    found: list[ObjectIR] = []
    for r in range(h):
        for c in range(w):
            if seen[r][c] or int(grid[r][c]) == bg:
                continue
            color = int(grid[r][c])
            stack = [(r, c)]
            seen[r][c] = True
            cells: list[tuple[int, int]] = []
            while stack:
                y, x = stack.pop()
                cells.append((y, x))
                for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                    ny, nx = y + dy, x + dx
                    if 0 <= ny < h and 0 <= nx < w and not seen[ny][nx] and int(grid[ny][nx]) == color:
                        seen[ny][nx] = True
                        stack.append((ny, nx))
            if len(cells) < 2:
                continue
            rs = [p[0] for p in cells]
            cs = [p[1] for p in cells]
            r0, r1 = min(rs), max(rs)
            c0, c1 = min(cs), max(cs)
            bh, bw = r1 - r0 + 1, c1 - c0 + 1
            fill_q = min(3, int(4 * len(cells) / max(1, bh * bw)))
            found.append(
                ObjectIR(
                    role=role_of.get(color, 9),
                    size=len(cells),
                    h=bh,
                    w=bw,
                    fill_q=fill_q,
                    cells=len(cells),
                    r0=r0,
                    c0=c0,
                    color=color,
                )
            )
    found.sort(key=lambda o: -o.size)
    return found[:16]


def _panel_mismatch(grid: list[list[int]], objs: list[ObjectIR]) -> int:
    """Mismatch between the two largest same-shape objects, if any."""
    if len(objs) < 2:
        return 0
    a, b = objs[0], objs[1]
    if abs(a.h - b.h) > 1 or abs(a.w - b.w) > 1 or a.h < 3 or a.w < 3:
        return 0
    h, w = len(grid), len(grid[0])
    mism = 0
    for dy in range(min(a.h, b.h)):
        for dx in range(min(a.w, b.w)):
            ra, ca = a.r0 + dy, a.c0 + dx
            rb, cb = b.r0 + dy, b.c0 + dx
            if ra >= h or ca >= w or rb >= h or cb >= w:
                continue
            if int(grid[ra][ca]) != int(grid[rb][cb]):
                mism += 1
    return mism


def _feedback(prev: list[list[int]] | None, grid: list[list[int]]) -> str:
    if prev is None or len(prev) != len(grid):
        return "start"
    changed = 0
    h, w = len(grid), len(grid[0])
    for r in range(h):
        pr, gr = prev[r], grid[r]
        for c in range(w):
            if int(pr[c]) != int(gr[c]):
                changed += 1
                if changed > 400:
                    return "jump"
    if changed == 0:
        return "noop"
    if changed <= 40:
        return "local"
    return "shift"


def project(grid, prev=None, legal: list[int] | None = None) -> Projection:
    grid = _grid(grid)
    prev_g = _grid(prev) if prev is not None else None
    if not grid or not grid[0]:
        return Projection(bg_role=0, n_objects=0, n_colors=0, legal=tuple(legal or ()))
    bg = _mode_color(grid)
    objs = _components(grid, bg)
    colors = {int(v) for row in grid for v in row}
    h, w = len(grid), len(grid[0])
    edge = 0
    edge_n = 0
    for r in range(h):
        for c in (0, w - 1):
            edge_n += 1
            if int(grid[r][c]) != bg:
                edge += 1
    hud_q = min(3, int(4 * edge / max(1, edge_n)))
    # Controllable guess: smallest object that is not the largest mass.
    controllable = None
    if len(objs) >= 2:
        small = [o for o in objs if o.size <= 36]
        if small:
            controllable = min(small, key=lambda o: o.size).role
    return Projection(
        bg_role=0,
        n_objects=len(objs),
        n_colors=len(colors),
        objects=objs,
        controllable_role=controllable,
        hud_edge_frac_q=hud_q,
        feedback=_feedback(prev_g, grid),
        legal=tuple(int(a) for a in (legal or []) if int(a) != 0),
        panel_mismatch=_panel_mismatch(grid, objs),
    )


def raw_tokens(grid) -> list[str]:
    """8x8 block-majority downsample. 64 tokens, the raw-grid baseline."""
    grid = _grid(grid)
    h = len(grid)
    w = len(grid[0]) if h else 0
    toks = []
    for br in range(8):
        for bc in range(8):
            r0, r1 = br * h // 8, (br + 1) * h // 8
            c0, c1 = bc * w // 8, (bc + 1) * w // 8
            counts: Counter[int] = Counter()
            for r in range(r0, max(r0 + 1, r1)):
                counts.update(int(v) for v in grid[r][c0:max(c0 + 1, c1)])
            toks.append(f"b{br}{bc}:{counts.most_common(1)[0][0] if counts else 0}")
    return toks


def delta_label(prev, grid) -> str:
    prev_g = _grid(prev)
    grid_g = _grid(grid)
    fb = _feedback(prev_g, grid_g)
    if fb == "noop":
        return "noop"
    if fb == "jump":
        return "jump"
    bg0 = _mode_color(prev_g)
    bg1 = _mode_color(grid_g)
    a = _components(prev_g, bg0)
    b = _components(grid_g, bg1)
    if len(b) > len(a) + 1:
        return "appear"
    if len(a) > len(b) + 1:
        return "vanish"
    if fb == "local":
        return "local"
    return "shift"


@dataclass
class LadderVerdict:
    ok: bool
    rung: str
    reason: str


def validate_action(
    action_id: int,
    legal: list[int],
    *,
    known_noop: bool = False,
    known_hazard: bool = False,
    click: tuple[int, int] | None = None,
) -> LadderVerdict:
    """D0 legal, D1 no-op, D2 hazard, D3 on-grid click, D4 not an unsolicited reset."""
    if action_id == 0:
        return LadderVerdict(False, "D4", "reset")
    if action_id not in legal:
        return LadderVerdict(False, "D0", "illegal")
    if click is not None and not (0 <= click[0] < 64 and 0 <= click[1] < 64):
        return LadderVerdict(False, "D3", "offgrid")
    if known_hazard:
        return LadderVerdict(False, "D2", "hazard")
    if known_noop:
        return LadderVerdict(False, "D1", "noop")
    return LadderVerdict(True, "pass", "ok")
