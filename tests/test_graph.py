"""The node-link graph engine: deterministic layout, the braille canvas, rendering, selection and speed."""

import random
import time

from phaneris_cli import graphview as gv
from phaneris_cli.style import Style


def small():
    nodes = [{"id": "T-1", "kind": "disclosure", "label": "Test one", "degree": 3, "depth": 0},
             {"id": "pat:1", "kind": "patent", "label": "A held patent", "degree": 2, "depth": 1},
             {"id": "inv:a", "kind": "person", "label": "Ada Shared", "degree": 2, "depth": 1},
             {"id": "cpc:A01B", "kind": "class", "label": "A01B", "degree": 1, "depth": 1}]  # fmt: skip
    edges = [{"from": "T-1", "to": "pat:1", "relation": "protected_by"}, {"from": "pat:1", "to": "inv:a", "relation": "invented_by"},
             {"from": "T-1", "to": "cpc:A01B", "relation": "classified_as"}, {"from": "T-1", "to": "inv:a", "relation": "inventor"}]  # fmt: skip
    return {"nodes": nodes, "edges": edges, "center": "T-1"}


def big(n=300, seed=1):
    rng = random.Random(seed)
    nodes = [{"id": "c", "kind": "disclosure", "label": "Centre", "degree": 30, "depth": 0}]
    edges = []
    for i in range(n - 1):
        nodes.append({"id": f"n{i}", "kind": gv.KINDS[i % 9], "label": f"Record {i}", "degree": 1, "depth": 1 if i < 30 else 2})
        edges.append({"from": "c" if i < 30 else f"n{rng.randrange(30)}", "to": f"n{i}", "relation": "linked_to"})
    for _ in range(n // 2):
        a, b = rng.sample(range(n - 1), 2)
        edges.append({"from": f"n{a}", "to": f"n{b}", "relation": "cites"})
    return {"nodes": nodes, "edges": edges, "center": "c"}


def text(cells):
    return "\n".join("".join(ch for ch, _, _ in row) for row in cells)


def test_the_layout_is_the_same_every_time_and_centred():
    s = small()
    gv._cache.clear()
    one = gv.layout(s["nodes"], s["edges"], "T-1")
    gv._cache.clear()
    two = gv.layout(s["nodes"], s["edges"], "T-1")
    assert one == two and one["T-1"] == (0.0, 0.0)
    assert gv.layout(s["nodes"], s["edges"], "T-1", seed=8) != one  # the seed is what fixes it
    assert all(abs(x) < 3 and abs(y) < 3 for x, y in one.values())


def test_an_expansion_keeps_the_positions_it_had():
    s = small()
    before = gv.layout(s["nodes"], s["edges"], "T-1")
    more = {
        "nodes": [{"id": "pat:9", "kind": "patent", "label": "New", "degree": 1}],
        "edges": [{"from": "inv:a", "to": "pat:9", "relation": "invented_by"}],
    }
    merged = gv.merge(s, more)
    after = gv.layout(merged["nodes"], merged["edges"], "T-1", fixed=before)
    assert all(after[i] == before[i] for i in before) and "pat:9" in after
    assert len(gv.merge(merged, more)["nodes"]) == 5  # merging again adds nothing


def test_rendering_at_two_sizes():
    s = small()
    pos = gv.layout(s["nodes"], s["edges"], "T-1")
    for cols, rows in ((100, 30), (200, 60)):
        cells, at = gv.render(s, pos, cols, rows, selected="pat:1")
        assert len(cells) == rows and all(len(r) == cols for r in cells) and set(at) == {"T-1", "pat:1", "inv:a", "cpc:A01B"}
        out = text(cells)
        assert "★" in out and "◆" in out and "●" in out and "▲" in out  # a glyph per kind
        assert "A held patent" in out and "Test one" in out  # labels
        assert "protected by" in out or "invented by" in out  # the selected node's relations
        assert any(0x2800 < ord(ch) <= 0x28FF for ch in out)  # edges as braille dots
    cells, at = gv.render(s, pos, 100, 30, labels=False, hidden={"class"})
    assert "cpc:A01B" not in at and "Test one" not in text(cells)


def test_selection_moves_nearest_first_and_visits_everything():
    s = small()
    pos = gv.layout(s["nodes"], s["edges"], "T-1")
    _, at = gv.render(s, pos, 100, 30)
    seen, cur = [], "T-1"
    for _ in range(4):
        cur = gv.nearest(at, cur, anchor="T-1")
        seen.append(cur)
    assert set(seen) == set(at) and seen[-1] == "T-1"  # every node once, nearest first, then back to the start
    assert gv.nearest(at, gv.nearest(at, "T-1", anchor="T-1"), -1, anchor="T-1") == "T-1"


def test_view_pans_zooms_and_resets():
    v = gv.View()
    v.pan(1, 0)
    v.scale(1.25)
    assert v.cx > 0 and v.zoom == 1.25
    v.reset()
    assert (v.cx, v.cy, v.zoom) == (0.0, 0.0, 1.0)


def test_plain_output_has_no_escape_codes():
    s = small()
    cells, _ = gv.render(s, gv.layout(s["nodes"], s["edges"], "T-1"), 60, 20, color=False)
    lines = gv.to_ansi(cells, Style(color=False))
    assert not any("\033" in line for line in lines) and any("*" in line for line in lines)


def test_three_hundred_nodes_draw_under_200_ms():
    s = big()
    t = time.perf_counter()
    pos = gv.layout(s["nodes"], s["edges"], "c")
    assert time.perf_counter() - t < 5  # laid out once per subgraph, then cached
    for cols, rows in ((100, 30), (200, 60)):
        t = time.perf_counter()
        _, at = gv.render(s, pos, cols, rows, selected="n3")
        assert (time.perf_counter() - t) * 1000 < 200 and len(at) > 200
