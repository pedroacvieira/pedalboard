"""scripts/svgdraw.py: the routing picture, on small hand-made contexts. Lengths in mm."""
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import routing  # noqa: E402
import svgdraw  # noqa: E402
from test_routing import TYPES, plug_ctx  # noqa: E402

NS = "{http://www.w3.org/2000/svg}"


def routed(**cables):
    """plug_ctx routed (A out -> B in), plus an unused 'other' jack on A."""
    ctx = plug_ctx({"type": "ra", **cables})
    ctx["layout"]["jacks"]["a"].append({"id": "exp", "label": "Exp", "function": "other", "x": 0.5, "y": 0.0, "facing": "top"})
    routing.route_project(ctx, {}, cable_types=TYPES)
    return ctx


def parse(svg):
    root = ET.fromstring(svg)
    return root, [e for e in root.iter() if e.tag.startswith(NS)]


def by_class(root, cls, tag=None):
    return [e for e in root.iter() if cls in (e.get("class") or "").split() and (tag is None or e.tag == NS + tag)]


def pts(poly):
    return [tuple(float(v) for v in p.split(",")) for p in poly.get("points").split()]


def test_document_is_sized_in_mm_and_parses():
    svg = svgdraw.render(routed(), {"a": "Alpha", "b": "Beta"})
    root, _ = parse(svg)
    w, h = root.get("width"), root.get("height")
    assert w.endswith("mm") and h.endswith("mm")
    vb = [float(v) for v in root.get("viewBox").split()]
    assert float(w[:-2]) == pytest.approx(vb[2], abs=0.05) and float(h[:-2]) == pytest.approx(vb[3], abs=0.05)
    assert "<image" not in svg
    assert {"Alpha", "Beta"} <= {t.text for t in by_class(root, "pedal-name")}


def test_no_picture_without_a_grid():
    ctx = plug_ctx({"type": "ra"})
    assert svgdraw.render(ctx, {}) is None


def test_one_cable_line_per_routed_cable_on_its_draw_path():
    ctx = routed()
    (c,) = [x for x in ctx["cable_list"] if x["kind"] == "signal"]
    c["draw_path"] = [(70.0, 80.0), (100.0, 80.0), (190.0, 126.0)]   # lanes are drawing only
    root, _ = parse(svgdraw.render(ctx, {}))
    (line,) = by_class(root, "cable", "polyline")
    assert pts(line) == c["draw_path"] and line.get("data-id") == "S1"
    assert len(by_class(root, "casing")) == 1 and not by_class(root, "cable-missing")
    assert [t.text for t in by_class(root, "cable-label")] == ["S1"]


def test_legend_rows_match_the_signal_cables_and_their_rounded_length():
    ctx = routed()
    (c,) = [x for x in ctx["cable_list"] if x["kind"] == "signal"]
    ctx["cable_list"].append({"id": "P1", "kind": "power", "from": "a.power", "to": "b.power", "min_mm": None, "path": None, "status": "x"})
    root, _ = parse(svgdraw.render(ctx, {"a": "Alpha", "b": "Beta"}))
    rows = by_class(root, "legend-row")
    assert [r.get("data-id") for r in rows] == ["S1"]
    texts = [t.text for t in rows[0].iter(NS + "text")]
    assert texts == ["S1", "Alpha out -> Beta in", f"{c['min_mm']:.0f} mm", None]


def test_jack_symbols_filled_when_used():
    root, _ = parse(svgdraw.render(routed(), {}))
    marks = {(g.get("data-jack"), g.get("data-used")) for g in by_class(root, "jack")}
    assert marks == {("out", "1"), ("exp", "0"), ("in", "1")}
    exp = next(g for g in by_class(root, "jack") if g.get("data-jack") == "exp")
    assert next(exp.iter(NS + "circle")).get("fill") == "#ffffff"


def test_image_only_with_images_and_rotated_with_the_pedal(tmp_path):
    png = tmp_path / "a.png"
    Image.new("RGBA", (40, 80), (200, 30, 30, 255)).save(png)
    ctx = routed()
    ctx["layout"]["placed"]["a"]["rot"] = 90
    root, _ = parse(svgdraw.render(ctx, {}, images={"a": png}))
    (im,) = [e for e in root.iter(NS + "image")]
    assert im.get("transform") == "rotate(90 45.00 110.00)" and im.get("preserveAspectRatio") == "none"
    assert (im.get("x"), im.get("y"), im.get("width"), im.get("height")) == ("20.0", "60.0", "50.0", "100.0")
    assert im.get("href").startswith("data:image/png;base64,")
    assert "<image" not in svgdraw.render(ctx, {})


def test_image_is_downscaled(tmp_path):
    png = tmp_path / "big.png"
    Image.new("RGB", (1200, 300), (10, 10, 10)).save(png)
    import base64
    import io
    uri = svgdraw.image_uri(png)
    im = Image.open(io.BytesIO(base64.b64decode(uri.split(",", 1)[1])))
    assert im.size == (svgdraw.IMAGE_PX, svgdraw.IMAGE_PX // 4)
    assert svgdraw.image_uri(tmp_path / "missing.png") is None


def test_unroutable_cable_is_dotted_between_its_jacks():
    ctx = routed()
    (c,) = [x for x in ctx["cable_list"] if x["kind"] == "signal"]
    c.update(path=None, draw_path=None, min_mm=None, status="unroutable: no free path between the pedals")
    root, _ = parse(svgdraw.render(ctx, {}))
    (line,) = by_class(root, "cable-missing")
    # A out at (70, 80), B in at (200, 140)
    assert pts(line) == [(70.0, 80.0), (200.0, 140.0)] and "0.1" in line.get("stroke-dasharray")
    assert not by_class(root, "cable") and [t.text for t in by_class(root, "cable-label")] == ["S1"]
    row = by_class(root, "legend-row")[0]
    assert [t.text for t in row.iter(NS + "text")][-2:] == ["-", "unroutable"]


def test_squeezed_is_dashed_over_limit_has_a_red_halo_stacked_has_white_dashes():
    ctx = routed()
    (c,) = [x for x in ctx["cable_list"] if x["kind"] == "signal"]
    plain, _ = parse(svgdraw.render(ctx, {}))
    assert not by_class(plain, "halo") and not by_class(plain, "stacked")
    assert by_class(plain, "cable")[0].get("stroke-dasharray") is None
    c["status"] = "routed, squeezed (gap narrower than the cable)"
    root, _ = parse(svgdraw.render(ctx, {}))
    assert by_class(root, "cable")[0].get("stroke-dasharray")
    c.update(status="routed, over the plug limit", stacked_with=["S2"])
    root, _ = parse(svgdraw.render(ctx, {}))
    assert len(by_class(root, "halo")) == 1 and len(by_class(root, "stacked")) == 1
    assert [t.text for t in by_class(root, "legend-row")[0].iter(NS + "text")][-1] == "over the plug limit"


def test_palette_is_long_distinct_and_readable_on_white():
    assert len(set(svgdraw.PALETTE)) >= 16
    for col in svgdraw.PALETTE:
        r, g, b = (int(col[i:i + 2], 16) / 255 for i in (1, 3, 5))
        assert 0.2126 * r + 0.7152 * g + 0.0722 * b < 0.55, col


def test_labels_fit_and_are_shortened():
    fs, lines = svgdraw.fit_label("Harmonious Monk Mk2", 60, 100)
    assert fs == 4.5 and lines == ["Harmonious Monk Mk2"]
    fs, lines = svgdraw.fit_label("Harmonious Monk Mk2", 30, 40)
    assert len(lines) > 1 and all(len(x) * svgdraw.CHAR * fs <= 30 for x in lines)
    fs, lines = svgdraw.fit_label("Extraordinarily", 12, 8)
    assert fs == 2.5 and lines[0].endswith("…") and len(lines) == 1


def test_short_status():
    assert svgdraw.short_status("routed") == "" and svgdraw.short_status("routed, squeezed (gap)") == "squeezed"
    assert svgdraw.short_status("unroutable: x") == "unroutable"
    assert svgdraw.short_status("not routed (no pedalboard in the layout)") == "not routed"


def test_names_are_escaped():
    svg = svgdraw.render(routed(), {"a": "A & <B>"})
    parse(svg)
    assert "A &amp; &lt;B&gt;" in svg


# --- the outline path ------------------------------------------------------------------------------
def test_union_outline_of_touching_overlapping_and_separate_rectangles():
    assert svgdraw.union_outline([]) == []
    assert svgdraw.union_outline([(0, 0, 10, 20)]) == [[(0, 0), (10, 0), (10, 20), (0, 20)]]
    # two touching rectangles of the same height: one loop of 4 points (the seam disappears, collinear points merge)
    assert svgdraw.union_outline([(0, 0, 10, 10), (10, 0, 20, 10)]) == [[(0, 0), (20, 0), (20, 10), (0, 10)]]
    # touching with different heights: one loop of 6 points
    (loop,) = svgdraw.union_outline([(0, 0, 10, 10), (10, 0, 20, 5)])
    assert sorted(loop) == sorted([(0, 0), (20, 0), (20, 5), (10, 5), (10, 10), (0, 10)]) and len(loop) == 6
    # an L (overlapping rectangles): 6 points
    (loop,) = svgdraw.union_outline([(0, 0, 30, 10), (0, 5, 10, 30)])
    assert sorted(loop) == sorted([(0, 0), (30, 0), (30, 10), (10, 10), (10, 30), (0, 30)])
    # a gap: two loops; float noise at a seam still joins
    assert len(svgdraw.union_outline([(0, 0, 10, 10), (20, 0, 30, 10)])) == 2
    assert len(svgdraw.union_outline([(0, 0, 10.0000000001, 10), (10, 0, 20, 10)])) == 1
    # a hole is a second loop, the other way round
    ring = svgdraw.union_outline([(0, 0, 30, 10), (0, 10, 10, 30), (20, 10, 30, 30), (0, 30, 30, 40)])
    assert len(ring) == 2

    def area(loop):   # shoelace, signed
        return sum(x0 * y1 - x1 * y0 for (x0, y0), (x1, y1) in zip(loop, loop[1:] + loop[:1])) / 2
    assert sorted(area(l) for l in ring) == pytest.approx([-200, 1200])   # outer 30 x 40 clockwise, hole 10 x 20 reversed


def test_a_pedal_outline_is_one_path_without_seams():
    item = {"id": "i", "title": "P", "rot": 0, "w_mm": 20, "h_mm": 20, "left_mm": 0, "top_mm": 0}
    svg = svgdraw.pedal(item, "P", shapes=[(0, 0, 10, 20), (10, 5, 20, 15)])
    assert svg.count('class="pedal-outline"') == 1 and svg.count("<path") == 1
    d = re.search(r' d="([^"]+)"', svg).group(1)
    assert d.count("M") == 1 and d.count("L") == 7                    # 8 corners of a two-rectangle plus shape
    assert 'class="pedal-box"' in svg                                 # Pedal Playground's box stays as a dashed hint


@pytest.mark.parametrize("rects", [[(0, 0, 10, 10), (10, 10, 20, 20)], [(10, 10, 20, 20), (0, 0, 10, 10)],
                                   [(10, 0, 20, 10), (0, 10, 10, 20)], [(0, 10, 10, 20), (10, 0, 20, 10)]])
def test_union_outline_splits_rectangles_touching_only_at_a_corner(rects):
    loops = svgdraw.union_outline(rects)
    assert sorted(sorted(loop) for loop in loops) == sorted(sorted([(r[0], r[1]), (r[2], r[1]), (r[2], r[3]), (r[0], r[3])])
                                                           for r in rects)
