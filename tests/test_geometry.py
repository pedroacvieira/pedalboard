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


# --- plug heads ----------------------------------------------------------------------------------
# Right-angle placeholder plug: head 20 deep x 16 wide; cable axis 10 mm out (depth/2); body ends at the head side
# (8 mm from the jack axis); 6 mm cable, then a 6 mm straight run -> exit 14 mm to the side, 10 mm out. Jack at (100, 50).
RA = {"style": "right_angle", "head_depth_mm": 20.0, "head_width_mm": 16.0}
P = (100.0, 50.0)


@pytest.mark.parametrize("facing,side,head,cable,exit_", [
    ("right", "left", (100, 42, 120, 58), (107, 36, 113, 42), (110, 36)),    # looking right, left is up
    ("right", "right", (100, 42, 120, 58), (107, 58, 113, 64), (110, 64)),
    ("left", "left", (80, 42, 100, 58), (87, 58, 93, 64), (90, 64)),         # looking left, left is down
    ("left", "right", (80, 42, 100, 58), (87, 36, 93, 42), (90, 36)),
    ("top", "left", (92, 30, 108, 50), (86, 37, 92, 43), (86, 40)),          # looking up, left is left
    ("top", "right", (92, 30, 108, 50), (108, 37, 114, 43), (114, 40)),
    ("down", "left", (92, 50, 108, 70), (108, 57, 114, 63), (114, 60)),      # looking down, left is canvas right
    ("down", "right", (92, 50, 108, 70), (86, 57, 92, 63), (86, 60)),
])
def test_right_angle_head_footprint_for_each_facing_and_side(facing, side, head, cable, exit_):
    g = design.plug_geometry(P, facing, RA, 6.0, 6.0, side)
    parts = dict(g["rects"])
    assert set(parts) == {"head", "cable"}
    assert close(parts["head"], head) and close(parts["cable"], cable) and close(g["exit"], exit_)
    assert g["lead_mm"] == pytest.approx(10 + 8 + 6)
    assert g["measure_mm"] == pytest.approx(8 + 6)            # from half the 20 mm head depth: the cable axis
    assert close(g["lead"][0], P) and close(g["lead"][-1], exit_)


def test_right_angle_barrel_beyond_the_head():
    plug = dict(RA, exit_offset_mm=13.0, body_reach_mm=20.0, barrel_width_mm=10.0)
    g = design.plug_geometry(P, "right", plug, 6.0, 6.0, "left")
    parts = dict(g["rects"])
    assert close(parts["barrel"], (108, 30, 118, 42))       # 13 +- 5 out, 8..20 up
    assert close(parts["cable"], (110, 24, 116, 30))        # 13 +- 3 out, 20..26 up
    assert close(g["exit"], (113, 24)) and g["lead_mm"] == pytest.approx(13 + 20 + 6)
    assert close(g["measure"], (110, 50)) and g["measure_mm"] == pytest.approx(3 + 20 + 6)   # 10 -> 13 out, then up


def test_straight_plug_leaves_along_the_facing():
    plug = {"style": "straight", "head_depth_mm": 40.0, "head_width_mm": 12.0}
    g = design.plug_geometry(P, "down", plug, 6.0, 6.0)
    parts = dict(g["rects"])
    assert close(parts["head"], (94, 50, 106, 90)) and close(parts["cable"], (97, 90, 103, 96))
    assert close(g["exit"], (100, 96)) and g["lead_mm"] == pytest.approx(46)
    assert close(g["measure"], (100, 70)) and g["measure_mm"] == pytest.approx(26)           # from 20 mm out


def test_right_angle_plug_needs_a_side():
    with pytest.raises(ValueError):
        design.plug_geometry(P, "right", RA, 6.0, 6.0)


@pytest.mark.parametrize("rot,facing,head,exit_", [
    # reference pedal, jack at fx 1, fy 0.5 facing right (unrotated); exit side left
    (90, "down", (42.8, 127.0, 58.8, 147.0), (64.8, 137.0)),    # jack at (50.8, 127.0), left of 'down' is +x
    (270, "top", (42.8, 56.2, 58.8, 76.2), (36.8, 66.2)),       # jack at (50.8, 76.2), left of 'top' is -x
])
def test_plug_on_a_rotated_pedal(rot, facing, head, exit_):
    it = item(rot=rot)
    pt, f = design.jack_point(it, 1.0, 0.5), design.jack_facing(it, "right")
    assert f == facing
    g = design.plug_geometry(pt, f, RA, 6.0, 6.0, "left")
    assert close(dict(g["rects"])["head"], head) and close(g["exit"], exit_)


# --- the real plug types (catalog/cables.json), hand-computed ------------------------------------
def _catalog_plug(tid):
    from common import load_cable_types
    t = load_cable_types()[tid]
    return t["plug"], t["diameter_mm"]


def test_ernie_ball_flat_patch_plug_facing_right_exit_left():
    # head 6.4 deep x 12.7 wide; ribbon axis 3.2 out; block to 19 mm from the jack axis (6.4 deep); 3.5 mm ribbon,
    # 3.5 mm run. Facing right: left is up (-y).
    plug, d = _catalog_plug("ernie_ball_flat_patch_ra")
    assert d == 3.5
    g = design.plug_geometry(P, "right", plug, d, d, "left")
    parts = dict(g["rects"])
    assert close(parts["head"], (100, 43.65, 106.4, 56.35))
    assert close(parts["barrel"], (100, 31, 106.4, 43.65))        # 6.35..19 up, 0..6.4 out
    assert close(parts["cable"], (101.45, 27.5, 104.95, 31))      # 3.2 +- 1.75 out, 19..22.5 up
    assert close(g["exit"], (103.2, 27.5)) and g["lead_mm"] == pytest.approx(3.2 + 19 + 3.5)
    assert close(g["measure"], (103.2, 50)) and g["measure_mm"] == pytest.approx(19 + 3.5)   # 3.2 mm in front of the jack


def test_dc_low_profile_plug_facing_top_exit_right():
    # head 11 x 11; cable axis 5.5 out; body to 14.5 mm (6 mm wide); 3.2 mm cable and run. Facing top: right is +x.
    plug, d = _catalog_plug("dc_ra_2_1_low_profile")
    g = design.plug_geometry(P, "top", plug, d, d, "right")
    parts = dict(g["rects"])
    assert close(parts["head"], (94.5, 39, 105.5, 50))
    assert close(parts["barrel"], (105.5, 41.5, 114.5, 47.5))
    assert close(parts["cable"], (114.5, 42.9, 117.7, 46.1))
    assert close(g["exit"], (117.7, 44.5)) and g["lead_mm"] == pytest.approx(5.5 + 14.5 + 3.2)
