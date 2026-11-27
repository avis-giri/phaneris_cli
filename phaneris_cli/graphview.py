"""The knowledge graph as nodes and edges in a terminal: layout, braille canvas and rendering. Standard library only.

A subgraph (nodes with id, kind, label, degree; edges with from, to, relation) is laid out with a deterministic
Fruchterman-Reingold layout (fixed seed, the subject at the centre) and drawn on a braille canvas: each terminal cell
holds 2 x 4 dots, edges are Bresenham lines in a dim colour, nodes are coloured glyphs by kind with short labels placed
where they do not overlap. The selected node's edges are highlighted with their relation names. The same rendering is
used by the window (GRAPH pane) and by the line mode (phaneris ID GRAPH).
"""

import math
import random

from .style import THEMES

KINDS = ("disclosure", "patent", "person", "owner", "class", "trial", "grant", "paper", "other")
GLYPH = {"disclosure": "★", "patent": "◆", "person": "●", "owner": "■", "class": "▲", "trial": "✚", "grant": "◇", "paper": "□", "other": "•"}
PLAIN_GLYPH = {"disclosure": "*", "patent": "P", "person": "o", "owner": "#", "class": "^", "trial": "+", "grant": "G", "paper": "=", "other": "."}
ROLE = {"disclosure": "bad", "patent": "accent", "person": "good", "owner": "warn"}
EXTRA = {
    "phaneris": {"class": (110, 180, 230), "trial": (230, 140, 200), "grant": (205, 205, 120), "paper": (180, 180, 195),
                 "other": (124, 134, 149), "edge": (82, 90, 104), "label": (200, 204, 212)},
    "amber": {"class": (255, 160, 60), "trial": (255, 214, 102), "grant": (230, 150, 0), "paper": (200, 140, 30),
              "other": (166, 112, 0), "edge": (110, 74, 0), "label": (255, 176, 0)},
}  # fmt: skip
SEED = 7
BRAILLE = ((0x01, 0x08), (0x02, 0x10), (0x04, 0x20), (0x40, 0x80))  # [row][col] bit of a braille cell


def kind_rgb(theme, kind):
    palette = THEMES.get(theme, THEMES["phaneris"])
    if kind in ROLE:
        return palette[ROLE[kind]]
    return EXTRA.get(theme, EXTRA["phaneris"]).get(kind, EXTRA["phaneris"]["other"])


def extra_rgb(theme, name):
    return EXTRA.get(theme, EXTRA["phaneris"])[name]


# ------------------------------------------------------------------ layout

_cache = {}


def _key(nodes, edges, center, fixed, seed):
    return (tuple(sorted(n["id"] for n in nodes)), tuple(sorted((e["from"], e["to"]) for e in edges)), center,
            tuple(sorted((k, round(x, 4), round(y, 4)) for k, (x, y) in (fixed or {}).items())), seed)  # fmt: skip


def layout(nodes, edges, center=None, fixed=None, iterations=None, seed=SEED):
    """Positions {id: (x, y)} roughly within [-1, 1], the same every time for the same subgraph. `center` stays at
    (0, 0); `fixed` positions (from an earlier layout, when a node is expanded) are kept and only new nodes move."""
    key = _key(nodes, edges, center, fixed, seed)
    if key in _cache:
        return dict(_cache[key])
    ids = sorted(n["id"] for n in nodes)
    if not ids:
        return {}
    rng = random.Random(seed)
    nbrs = {i: [] for i in ids}
    links = []
    for e in edges:
        a, b = e["from"], e["to"]
        if a in nbrs and b in nbrs and a != b:
            nbrs[a].append(b)
            nbrs[b].append(a)
            links.append((a, b))
    center = center if center in nbrs else max(ids, key=lambda i: len(nbrs[i]))
    fixed = {k: v for k, v in (fixed or {}).items() if k in nbrs}
    # start on rings by distance from the centre, so it settles quickly and the same way every time
    depth = {center: 0}
    queue = [center]
    while queue:
        n = queue.pop(0)
        for m in sorted(nbrs[n]):
            if m not in depth:
                depth[m] = depth[n] + 1
                queue.append(m)
    far = max(depth.values()) + 1
    pos = {}
    for i in ids:
        if i in fixed:
            pos[i] = list(fixed[i])
        elif i == center:
            pos[i] = [0.0, 0.0]
        else:
            anchor = next((fixed[m] for m in sorted(nbrs[i]) if m in fixed), None)
            if anchor is not None:  # a new node from an expansion starts beside the node it was expanded from
                a = rng.uniform(0, 2 * math.pi)
                pos[i] = [anchor[0] + 0.12 * math.cos(a), anchor[1] + 0.12 * math.sin(a)]
            else:
                r = 0.32 * depth.get(i, far)
                a = rng.uniform(0, 2 * math.pi)
                pos[i] = [r * math.cos(a), r * math.sin(a)]
    pinned = set(fixed) | {center}
    n = len(ids)
    k = math.sqrt(4.0 / n) * 0.75
    k2 = k * k
    iterations = iterations or (300 if n <= 120 else 220)
    cell = 2 * k
    t0 = 0.18
    for it in range(iterations):
        t = t0 * (1 - it / iterations) + 0.002
        disp = {i: [0.0, 0.0] for i in ids}
        grid = {}
        for i in ids:
            p = pos[i]
            grid.setdefault((int(math.floor(p[0] / cell)), int(math.floor(p[1] / cell))), []).append(i)
        for (gx, gy), members in grid.items():  # repulsion from nodes in this and the neighbouring cells only
            near = [m for dx in (-1, 0, 1) for dy in (-1, 0, 1) for m in grid.get((gx + dx, gy + dy), ())]
            for i in members:
                pi, di = pos[i], disp[i]
                for j in near:
                    if j == i:
                        continue
                    dx, dy = pi[0] - pos[j][0], pi[1] - pos[j][1]
                    d2 = dx * dx + dy * dy
                    if d2 < 1e-9:
                        dx, dy, d2 = rng.uniform(-1e-3, 1e-3), rng.uniform(-1e-3, 1e-3), 1e-6
                    f = k2 / d2
                    di[0] += dx * f
                    di[1] += dy * f
        for a, b in links:  # attraction along edges
            dx, dy = pos[a][0] - pos[b][0], pos[a][1] - pos[b][1]
            d = math.sqrt(dx * dx + dy * dy) or 1e-6
            f = d / k
            disp[a][0] -= dx * f
            disp[a][1] -= dy * f
            disp[b][0] += dx * f
            disp[b][1] += dy * f
        for i in ids:
            if i in pinned:
                continue
            p, d = pos[i], disp[i]
            d[0] -= p[0] * 0.6 * k  # a little gravity keeps loose parts near the centre
            d[1] -= p[1] * 0.6 * k
            length = math.sqrt(d[0] * d[0] + d[1] * d[1]) or 1e-9
            step = min(length, t)
            p[0] += d[0] / length * step
            p[1] += d[1] / length * step
    out = {i: (pos[i][0], pos[i][1]) for i in ids}
    if len(_cache) > 64:
        _cache.clear()
    _cache[key] = out
    return dict(out)


# ------------------------------------------------------------------ canvas


class Canvas:
    """A grid of terminal cells, each a braille character of 2 x 4 dots or a text character, with one colour."""

    def __init__(self, cols, rows):
        self.cols, self.rows = max(1, cols), max(1, rows)
        self.bits = [[0] * self.cols for _ in range(self.rows)]
        self.dot_rgb = [[None] * self.cols for _ in range(self.rows)]
        self.dot_rank = [[0] * self.cols for _ in range(self.rows)]
        self.text = {}  # (row, col) -> (char, rgb, bold, rank)

    def dot(self, x, y, rgb, rank=1):
        if 0 <= x < self.cols * 2 and 0 <= y < self.rows * 4:
            r, c = y >> 2, x >> 1
            self.bits[r][c] |= BRAILLE[y & 3][x & 1]
            if rank >= self.dot_rank[r][c]:
                self.dot_rgb[r][c], self.dot_rank[r][c] = rgb, rank

    def line(self, x0, y0, x1, y1, rgb, rank=1):
        """Bresenham's line between two dots."""
        dx, dy = abs(x1 - x0), -abs(y1 - y0)
        sx, sy = (1 if x0 < x1 else -1), (1 if y0 < y1 else -1)
        err = dx + dy
        for _ in range(4 * (self.cols + self.rows) * 4):
            self.dot(x0, y0, rgb, rank)
            if x0 == x1 and y0 == y1:
                return
            e2 = 2 * err
            if e2 >= dy:
                err += dy
                x0 += sx
            if e2 <= dx:
                err += dx
                y0 += sy

    def free(self, row, col, length):
        return 0 <= row < self.rows and col >= 0 and col + length <= self.cols and all((row, c) not in self.text for c in range(col, col + length))

    def put(self, row, col, text, rgb=None, bold=False, rank=2):
        for i, ch in enumerate(text):
            c = col + i
            if 0 <= row < self.rows and 0 <= c < self.cols:
                old = self.text.get((row, c))
                if old is None or rank >= old[3]:
                    self.text[(row, c)] = (ch, rgb, bold, rank)

    def cells(self):
        """Rows of (char, rgb, bold)."""
        out = []
        for r in range(self.rows):
            row = []
            for c in range(self.cols):
                t = self.text.get((r, c))
                if t:
                    row.append(t[:3])
                elif self.bits[r][c]:
                    row.append((chr(0x2800 + self.bits[r][c]), self.dot_rgb[r][c], False))
                else:
                    row.append((" ", None, False))
            out.append(row)
        return out


# ------------------------------------------------------------------ the view


class View:
    """Where the camera looks: the centre in layout units and the zoom (1 fits the whole subgraph)."""

    def __init__(self):
        self.cx, self.cy, self.zoom = 0.0, 0.0, 1.0

    def reset(self):
        self.cx, self.cy, self.zoom = 0.0, 0.0, 1.0

    def pan(self, dx, dy):
        self.cx += dx * 0.15 / self.zoom
        self.cy += dy * 0.15 / self.zoom

    def scale(self, factor):
        self.zoom = max(0.25, min(12.0, self.zoom * factor))


def short(label, width):
    label = " ".join(str(label or "").split())
    return label if len(label) <= width else label[: max(1, width - 1)] + "…"


def project(positions, view, cols, rows):
    """{id: (x dot, y dot)} for a canvas of cols x rows cells."""
    if not positions:
        return {}
    xs = [p[0] for p in positions.values()]
    ys = [p[1] for p in positions.values()]
    span = max(max(xs) - min(xs), max(ys) - min(ys), 0.2)
    w, h = cols * 2, rows * 4
    scale = min((w - 6) / span, (h - 6) / span) * view.zoom
    mx, my = (max(xs) + min(xs)) / 2 + view.cx, (max(ys) + min(ys)) / 2 + view.cy
    return {i: (int(round((x - mx) * scale + w / 2)), int(round((y - my) * scale + h / 2))) for i, (x, y) in positions.items()}


def render(sub, positions, cols, rows, theme="phaneris", view=None, selected=None, labels=True, hidden=(), color=True):
    """The subgraph drawn on a cols x rows canvas: rows of (char, rgb, bold), and the drawn positions in cells."""
    view = view or View()
    canvas = Canvas(cols, rows)
    nodes = {n["id"]: n for n in sub["nodes"] if n["kind"] not in hidden and n["id"] in positions}
    dots = project({i: positions[i] for i in nodes}, view, cols, rows)
    edge_rgb, label_rgb, sel_rgb = extra_rgb(theme, "edge"), extra_rgb(theme, "label"), THEMES[theme]["accent"]
    mine = []
    for e in sub["edges"]:
        a, b = e["from"], e["to"]
        if a in dots and b in dots:
            if selected in (a, b):
                mine.append(e)
            else:
                canvas.line(*dots[a], *dots[b], edge_rgb, 1)
    for e in mine:  # the selected node's edges over the others, with their relations
        canvas.line(*dots[e["from"]], *dots[e["to"]], sel_rgb, 3)
    glyphs = GLYPH if color else PLAIN_GLYPH
    at = {}
    order = sorted(nodes, key=lambda i: (i != selected, i != sub.get("center"), nodes[i].get("depth", 9), -nodes[i].get("degree", 0), i))
    for i in reversed(order):  # the most important last, so it wins a shared cell
        x, y = dots[i]
        r, c = y >> 2, x >> 1
        if 0 <= r < rows and 0 <= c < cols:
            n = nodes[i]
            canvas.put(r, c, glyphs.get(n["kind"], "•"), kind_rgb(theme, n["kind"]), i == selected or i == sub.get("center"), rank=5)
            at[i] = (r, c)
    if labels:
        width = 12 if cols < 120 else 18
        budget = max(8, (cols * rows) // 90)
        for i in order[:budget]:
            if i not in at:
                continue
            r, c = at[i]
            text = short(nodes[i]["label"], 28 if i == selected else width)
            rgb = sel_rgb if i == selected else label_rgb
            for col in (c + 2, c - len(text) - 1):  # right of the glyph, else left of it
                if canvas.free(r, col, len(text)):
                    canvas.put(r, col, text, rgb, i == selected, rank=4)
                    break
    for e in mine[:8]:
        a, b = at.get(e["from"]), at.get(e["to"])
        if a and b:
            rel = short(e["relation"].replace("_", " "), 16)
            r, c = (a[0] + b[0]) // 2, (a[1] + b[1]) // 2 - len(rel) // 2
            if canvas.free(r, c, len(rel)):
                canvas.put(r, c, rel, sel_rgb, False, rank=3)
    return canvas.cells(), at


def legend(sub, hidden=()):
    counts = {}
    for n in sub["nodes"]:
        counts[n["kind"]] = counts.get(n["kind"], 0) + 1
    return [(k, counts[k], k in hidden) for k in KINDS if k in counts]


def nearest(at, selected, step=1, anchor=None):
    """The next node after the selection (Tab), or before it (Shift-Tab), in order of distance from the anchor (where
    cycling started), so repeated Tabs visit every node, nearest first."""
    if not at:
        return None
    if selected not in at:
        return min(at, key=lambda i: (at[i][0], at[i][1]))
    anchor = anchor if anchor in at else selected
    r0, c0 = at[anchor]
    ring = sorted(at, key=lambda i: ((at[i][0] - r0) ** 2 * 4 + (at[i][1] - c0) ** 2, i))
    return ring[(ring.index(selected) + step) % len(ring)]


def merge(sub, more):
    """Add another subgraph's nodes and edges (an expansion)."""
    have = {n["id"] for n in sub["nodes"]}
    edges = {(e["from"], e["to"], e["relation"]) for e in sub["edges"]}
    out = {**sub, "nodes": list(sub["nodes"]), "edges": list(sub["edges"])}
    for n in more["nodes"]:
        if n["id"] not in have:
            out["nodes"].append(n)
            have.add(n["id"])
    for e in more["edges"]:
        if (e["from"], e["to"], e["relation"]) not in edges:
            out["edges"].append(e)
            edges.add((e["from"], e["to"], e["relation"]))
    out["truncated"] = sub.get("truncated") or more.get("truncated")
    return out


def to_ansi(cells, style):
    """Rows of ANSI text (plain when the style has no colour)."""
    lines = []
    for row in cells:
        parts, run, rgb0, bold0 = [], "", None, False
        for ch, rgb, bold in row + [("", "end", False)]:
            if (rgb, bold) != (rgb0, bold0) and run:
                piece = style.rgb(rgb0, run) if rgb0 else run
                parts.append(style.bold(piece) if bold0 else piece)
                run = ""
            rgb0, bold0 = rgb, bold
            run += ch
        lines.append("".join(parts).rstrip())
    return lines
