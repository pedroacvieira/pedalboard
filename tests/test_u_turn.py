"""feat/u-turn-plugs: a cable never crosses its own plug (the keep-out) and goes round the front of the head instead (the U-turn).
Hand-computed cases; the jack of the geometry cases is at (0, 0) facing right (side "right" = +y, "left" = -y), mm."""
import math
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import common  # noqa: E402
import design  # noqa: E402
import routing  # noqa: E402

TYPES = common.load_cable_types()
EB, DC = TYPES["ernie_ball_flat_patch_ra"], TYPES["dc_ra_owner_baseline"]


def option(ctype, side, jack=(0.0, 0.0), facing="right", run=None):
    d = float(ctype["diameter_mm"])
    g = design.plug_geometry(jack, facing, ctype["plug"], d, d if run is None else run, side)
    return {"side": side, **g}


def test_keepout_of_a_right_angle_side_option_is_head_and_barrel_only():
    o = option(EB, "right")
    assert [p for p, _ in o["rects"]] == ["head", "barrel", "cable"]
    assert routing.keepout_rects(o) == [r for p, r in o["rects"] if p in ("head", "barrel")]
    assert len(routing.keepout_rects(o)) == 2


def test_keepout_of_a_plug_pointing_down_is_empty():
    o = option(EB, design.DOWN)
    assert o.get("down") and routing.keepout_rects(o) == []


def test_keepout_of_a_straight_plug_is_its_head():
    straight = {"plug": {"style": "straight", "head_depth_mm": 34.0, "head_width_mm": 10.0}, "diameter_mm": 3.2}
    o = option(straight, None)
    assert [p for p, _ in o["rects"]] == ["head", "cable"]
    assert routing.keepout_rects(o) == [o["rects"][0][1]]


def test_keepout_of_a_fixed_box_or_a_missing_option_is_empty():
    assert routing.keepout_rects({"side": None, "rects": [("box", (0, 0, 5, 5))]}) == []
    assert routing.keepout_rects({"side": None, "rects": []}) == []
    assert routing.keepout_rects(None) == []


def test_ernie_ball_turn_is_56_55_mm_round_the_front_of_the_head():
    o = option(EB, "right")
    assert o["exit"] == pytest.approx((3.2, 22.5)) and o["measure_mm"] == pytest.approx(22.5)
    r = routing.keepout_rects(o)
    q = (3.2, -30.0)
    extra = routing.around_own_plug(o["exit"], q, r, 1.75, "right", (0.0, 0.0))
    assert extra == pytest.approx(5.2502 + 28.85 + 22.4524 - 52.5, abs=1e-3)       # 56.5527 - 52.5 = 4.0527
    assert 52.5 + extra == pytest.approx(56.5527, abs=1e-3)
    assert o["measure_mm"] + 52.5 + extra == pytest.approx(79.05, abs=5e-3)        # min_mm of the whole cable (measure + the route)


def test_dc_baseline_turn_is_56_03_mm():
    o = option(DC, "right")
    assert o["exit"] == pytest.approx((8.4, 22.2)) and o["measure_mm"] == pytest.approx(24.6)
    r = routing.keepout_rects(o)
    q = (8.4, -30.0)
    extra = routing.around_own_plug(o["exit"], q, r, 1.6, "right", (0.0, 0.0))
    assert 52.2 + extra == pytest.approx(4.8703 + 15.0120 + 11.2 + 24.9479, abs=2e-3)   # 56.0302 (the bounding box would give 56.5894)


def test_a_target_on_the_plugs_own_side_costs_nothing_extra():
    o = option(EB, "right")
    assert routing.around_own_plug(o["exit"], (3.2, 40.0), routing.keepout_rects(o), 1.75, "right", (0.0, 0.0)) == 0.0


def test_a_segment_that_clears_the_hull_costs_nothing_extra():
    o = option(EB, "right")
    r = routing.keepout_rects(o)
    assert routing.around_own_plug(o["exit"], (60.0, 22.5), r, 1.75, "right", (0.0, 0.0)) == 0.0     # sideways, past the barrel's far end
    assert routing.around_own_plug(o["exit"], (60.0, 10.0), r, 1.75, "right", (0.0, 0.0)) == 0.0    # passes above the hull's front corner


def test_the_turn_never_uses_hull_vertices_behind_the_jack_face():
    o = option(EB, "right")
    r = routing.keepout_rects(o)
    # the target lies behind the face (in the pedal): the way round the front vertices only is still the answer
    extra = routing.around_own_plug(o["exit"], (-20.0, -30.0), r, 1.75, "right", (0.0, 0.0))
    front = math.hypot(8.15 - 3.2, 20.75 - 22.5) + (20.75 + 8.1) + math.hypot(8.15 + 20.0, -8.1 + 30.0)
    assert extra == pytest.approx(front - math.hypot(23.2, 52.5), abs=1e-3)


def test_turns_back_is_true_for_a_cable_that_crosses_the_axis_in_front_of_the_head():
    o = option(EB, "right")
    window = 6.4 + 2 * 3.5 + 2.0
    pts = [o["exit"], (8.15, 20.75), (8.15, -8.1), (3.2, -30.0)]
    assert routing.turns_back(o, "right", (0.0, 0.0), pts, window)
    assert not routing.turns_back(o, "right", (0.0, 0.0), [o["exit"], (3.2, 40.0)], window)            # goes the way the plug points
    assert not routing.turns_back(o, "right", (0.0, 0.0), [o["exit"], (60.0, 22.5), (60.0, -30.0)], window)   # crosses the axis far away
    assert not routing.turns_back(option(EB, design.DOWN), "right", (0.0, 0.0), pts, window)
