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
    # Spatial fields the coarse object line used to drop: a 4x4 role map,
    # where the controllable sits, what is beside it, and which way the
    # largest other object lies. Roles, not raw color ids.
    layout: tuple[str, ...] = ()
    toward: str = "none"
    adjacent: str = ""
    dots_q: int = 0

    def tokens(self) -> list[str]:
        toks = [
            f"nobj:{min(self.n_objects, 12)}",
            f"ncol:{min(self.n_colors, 8)}",
            f"fb:{self.feedback}",
            f"legal:{','.join(str(a) for a in self.legal)}",
            f"hud:{self.hud_edge_frac_q}",
            f"panel:{min(self.panel_mismatch, 9)}",
            f"dir:{self.toward}",
            f"dots:{self.dots_q}",
        ]
        if self.controllable_role is not None:
            toks.append(f"ctrl:{self.controllable_role}")
        if self.adjacent:
            toks.append(self.adjacent)
        toks.extend(self.layout)
        # Position of the largest few objects at 4x4 resolution. The old
        # token kept only the origin's 32px quadrant, so a move inside a
        # quadrant was invisible.
        for i, obj in enumerate(self.objects[:4]):
            toks.append(f"p{i}:{_block(obj.r0, obj.c0)}:s{_size_bucket(obj.size)}")
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


def _block(r: int, c: int, h: int = 64, w: int = 64) -> str:
    br = min(3, int(r) * 4 // max(1, h))
    bc = min(3, int(c) * 4 // max(1, w))
    return f"{br}{bc}"


def _role_of(grid: list[list[int]], bg: int) -> dict[int, int]:
    counts: Counter[int] = Counter()
    for row in grid:
        for v in row:
            iv = int(v)
            if iv != bg:
                counts[iv] += 1
    return {c: i for i, c in enumerate(c for c, _n in counts.most_common())}


def _layout_tokens(grid: list[list[int]], bg: int, role_of: dict[int, int]) -> tuple[str, ...]:
    """4x4 majority role. Sixteen tokens, shared across palettes."""
    h = len(grid)
    w = len(grid[0]) if h else 0
    toks = []
    for br in range(4):
        for bc in range(4):
            r0, r1 = br * h // 4, max(br * h // 4 + 1, (br + 1) * h // 4)
            c0, c1 = bc * w // 4, max(bc * w // 4 + 1, (bc + 1) * w // 4)
            counts: Counter[int] = Counter()
            for r in range(r0, min(h, r1)):
                counts.update(int(v) for v in grid[r][c0:min(w, c1)])
            if not counts:
                toks.append(f"L{br}{bc}:bg")
                continue
            color = counts.most_common(1)[0][0]
            if color == bg:
                toks.append(f"L{br}{bc}:bg")
            else:
                toks.append(f"L{br}{bc}:r{role_of.get(color, 9)}")
    return tuple(toks)


def _ctrl_obj(objs: list[ObjectIR], role: int | None) -> ObjectIR | None:
    if role is None:
        return None
    cands = [o for o in objs if o.role == role]
    return min(cands, key=lambda o: o.size) if cands else None


def _toward(ctrl: ObjectIR | None, objs: list[ObjectIR]) -> str:
    if ctrl is None:
        return "none"
    target = None
    for obj in objs:
        if obj is ctrl:
            continue
        if target is None or obj.size > target.size:
            target = obj
    if target is None:
        return "none"
    dr = (target.r0 + target.h / 2) - (ctrl.r0 + ctrl.h / 2)
    dc = (target.c0 + target.w / 2) - (ctrl.c0 + ctrl.w / 2)
    if abs(dr) < 1 and abs(dc) < 1:
        return "same"
    if abs(dc) >= abs(dr):
        return "E" if dc > 0 else "W"
    return "S" if dr > 0 else "N"


def _adjacent(grid: list[list[int]], bg: int, ctrl: ObjectIR | None) -> str:
    if ctrl is None:
        return ""
    h = len(grid)
    w = len(grid[0]) if h else 0
    r = min(h - 1, max(0, ctrl.r0 + ctrl.h // 2))
    c = min(w - 1, max(0, ctrl.c0 + ctrl.w // 2))
    bits = []
    for dr, dc in ((-1, 0), (1, 0), (0, 1), (0, -1)):
        nr, nc = r + dr, c + dc
        if not (0 <= nr < h and 0 <= nc < w) or int(grid[nr][nc]) != bg:
            bits.append("1")
        else:
            bits.append("0")
    return "adj:" + "".join(bits)


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
    roles = _role_of(grid, bg)
    ctrl = _ctrl_obj(objs, controllable)
    fg = sum(1 for row in grid for v in row if int(v) != bg)
    dots = max(0, fg - sum(o.size for o in objs))
    if dots <= 2:
        dots_q = 0
    elif dots <= 16:
        dots_q = 1
    elif dots <= 64:
        dots_q = 2
    else:
        dots_q = 3
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
        layout=_layout_tokens(grid, bg, roles),
        toward=_toward(ctrl, objs),
        adjacent=_adjacent(grid, bg, ctrl),
        dots_q=dots_q,
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
