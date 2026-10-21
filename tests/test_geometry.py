"""Hand-computed checks for scripts/design.py (all geometry in mm).

Reference pedal: 2 x 4 in = 50.8 x 101.6 mm, at left 45 px / top 90 px, scale 45 px/in
-> left 25.4 mm, top 50.8 mm, centre (50.8, 101.6) mm.
"""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import design  # noqa: E402


def item(left_px=45, top_px=90, rot=0, w_in=2.0, h_in=4.0, scale=45, kind="pedal"):
    return {"id": "item-1", "kind": kind, "title": "x", "rot": rot, "scale": scale, "w_in": w_in, "h_in": h_in,
            "left_px": left_px, "top_px": top_px, "image": None,
            "w_mm": w_in * 25.4, "h_mm": h_in * 25.4,
            "left_mm": left_px * 25.4 / scale, "top_mm": top_px * 25.4 / scale}


def close(a, b, tol=0.05):
    return all(abs(x - y) <= tol for x, y in zip(a, b))


def test_unit_conversion_on_parse():
    html = ('<div id="item-1" class="item pedal undefined" title="P" data-width="2" data-height="4" data-scale="45" '
            'style="touch-action: none; left: 45px; top: 90px;"><div class="artwork" style="width:90px"></div></div>')
    (it,) = design.parse_canvas(html)
    assert it["left_mm"] == pytest.approx(25.4) and it["top_mm"] == pytest.approx(50.8)
    assert it["w_mm"] == pytest.approx(50.8) and it["h_mm"] == pytest.approx(101.6)


def test_each_item_uses_its_own_scale():
    html = ('<div id="a" class="item pedal" title="P" data-width="1" data-height="1" data-scale="50" '
            'style="left: 50px; top: 100px;"></div>')
    (it,) = design.parse_canvas(html)
    assert it["left_mm"] == pytest.approx(25.4) and it["top_mm"] == pytest.approx(50.8)


@pytest.mark.parametrize("rot,expected", [(0, (76.2, 50.8)), (90, (101.6, 127.0)), (180, (25.4, 152.4)), (270, (0.0, 76.2))])
def test_jack_point_rotation(rot, expected):
    assert close(design.jack_point(item(rot=rot), 1.0, 0.0), expected)


def test_footprint_swaps_for_90_and_270():
    assert close(design.footprint(item(rot=0)), (25.4, 50.8, 76.2, 152.4))
    for rot in (90, 270):
        assert close(design.footprint(item(rot=rot)), (0.0, 76.2, 101.6, 127.0))
    assert close(design.footprint(item(rot=180)), (25.4, 50.8, 76.2, 152.4))


@pytest.mark.parametrize("facing,rot,expected", [
    ("right", 0, "right"), ("right", 90, "down"), ("right", 180, "left"), ("right", 270, "top"),
    ("top", 90, "right"), ("left", 90, "top"), ("down", 90, "left"), ("top", 270, "left"),
])
def test_facing_rotates_with_the_pedal(facing, rot, expected):
    assert design.jack_facing(item(rot=rot), facing) == expected


def test_clearance_rect_rot0_facing_right():
    it = item(left_px=0, top_px=0)
    p = design.jack_point(it, 1.0, 0.5)
    assert close(p, (50.8, 50.8))
    assert close(design.clearance_rect(p, "right", 6.3, 7.0), (50.8, 43.8, 57.1, 57.8))


def test_clearance_rect_rot90_faces_down():
    it = item(left_px=0, top_px=0, rot=90)
    p = design.jack_point(it, 1.0, 0.5)
    assert close(p, (25.4, 76.2))
    f = design.jack_facing(it, "right")
    assert f == "down"
    assert close(design.clearance_rect(p, f, 6.3, 7.0), (18.4, 76.2, 32.4, 82.5))


@pytest.mark.parametrize("facing,expected", [
    ("left", (43.7, 43.0, 50.0, 57.0)), ("right", (50.0, 43.0, 56.3, 57.0)),
    ("top", (43.0, 43.7, 57.0, 50.0)), ("down", (43.0, 50.0, 57.0, 56.3)),
])
def test_clearance_rect_all_four_facings(facing, expected):
    assert close(design.clearance_rect((50.0, 50.0), facing, 6.3, 7.0), expected)


def test_stub_moves_along_facing():
    assert close(design.stub((10.0, 20.0), "left", 6.3), (3.7, 20.0))
    assert close(design.stub((10.0, 20.0), "down", 6.3), (10.0, 26.3))


@pytest.mark.parametrize("shift,expected", [(10.0, None), (9.7, None), (7.0, (3.0, 10.0)), (0.0, (10.0, 10.0))])
def test_overlap_tolerance(shift, expected):
    a, b = (0, 0, 10, 10), (shift, 0, shift + 10, 10)
    got = design.overlap(a, b)
    if expected is None:
        assert got is None
    else:
        assert close(got, expected)


def test_two_side_jack_pedals_at_zero_distance_block_each_other():
    a = item(left_px=0, top_px=0)                      # 2 x 4 in
    b = item(left_px=90, top_px=0)                     # starts exactly where a ends (2 in = 90 px)
    zone = design.clearance_rect(design.jack_point(a, 1.0, 0.5), "right", 6.3, 7.0)
    ov = design.overlap(zone, design.footprint(b))
    assert ov is not None
    assert design.overlap_depth("right", ov) == pytest.approx(6.3)


def test_side_jack_pedals_with_enough_gap_are_fine():
    a = item(left_px=0, top_px=0)
    b = item(left_px=90 + 12, top_px=0)               # 12 px = 6.77 mm gap > 6.3 mm
    zone = design.clearance_rect(design.jack_point(a, 1.0, 0.5), "right", 6.3, 7.0)
    assert design.overlap(zone, design.footprint(b)) is None


def test_parser_is_tolerant():
    html = (
        '<div id="item-1" class="item pedalboard undefined" title="Board" data-width="24" data-height="13" data-scale="45" style="left: 28px; top: 40px;">'
        '<div class="artwork" style="width: 1080px; background-image: url(&quot;public/images/pedalboards/b.png&quot;);"></div>'
        '<div class="actions"><a class="rotate"></a></div></div>'
        '<input id="multiplier" type="hidden" value="45">'
        '<div id="item-2" class="item pedal undefined rotate-270 selected" title="Beano" data-width="1.9" data-height="3.76" data-scale="45" style="left: 1002px; top: 196px;">'
        '<div class="artwork" style="width:85.5px;height:169.2px; background-image:url(public/images/pedals/analogman-mini-beano.png)"></div>'
        '<div class="shadow"></div><div class="actions"><a class="rotate"></a></div></div>'
    )
    board, beano = design.parse_canvas(html)
    assert board["kind"] == "pedalboard" and board["image"] == "b.png" and board["rot"] == 0
    assert beano["kind"] == "pedal" and beano["rot"] == 270 and beano["title"] == "Beano"
    assert beano["image"] == "analogman-mini-beano.png"


def test_real_design_file_parses():
    path = ROOT / "projects" / "guitar-gig" / "playground_design.json"
    if not path.exists():
        pytest.skip("no design file")
    items = design.parse_design(path)
    assert any(i["kind"] == "pedalboard" for i in items)
    assert sum(1 for i in items if i["title"] == "Strymon Ojai R30") == 2
    assert all(i["w_mm"] > 0 and i["h_mm"] > 0 and i["image"] for i in items)
    assert {i["rot"] for i in items} <= {0, 90, 180, 270}
