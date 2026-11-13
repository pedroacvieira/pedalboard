"""feat/u-turn-plugs (owner decision 2026-11-13): a cable that has to go to the side its plug does not point to turns back ACROSS its own plug;
the plug sits high enough on the pedal for one thin cable to pass under it. No keep-out, no extra length (`min_mm` stays along the routed path on
the deck); the crossing is reported (information only: `under_own_a` / `under_own_b`, the README Exits column, a build log line).
Hand-made scenes; all lengths in mm."""
import functools
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import build  # noqa: E402
import common  # noqa: E402
import design  # noqa: E402
import routing  # noqa: E402
from conftest import GIG_FIXTURE  # noqa: E402
from test_routing import TYPES as TEST_TYPES, mm_item  # noqa: E402

TYPES = common.load_cable_types()
EB = TYPES["ernie_ball_flat_patch_ra"]


def option(ctype, side, jack=(0.0, 0.0), facing="right"):
    d = float(ctype["diameter_mm"])
    return {"side": side, **design.plug_geometry(jack, facing, ctype["plug"], d, d, side)}


# --- detection helpers -----------------------------------------------------------------------------------------------
def test_plug_body_of_a_right_angle_side_option_is_head_and_barrel():
    o = option(EB, "right")
    assert [p for p, _ in o["rects"]] == ["head", "barrel", "cable"]
    assert routing.plug_body_rects(o) == [r for p, r in o["rects"] if p in ("head", "barrel")] and len(routing.plug_body_rects(o)) == 2


def test_plug_body_of_a_down_option_a_fixed_box_or_nothing_is_empty_and_of_a_straight_plug_its_head():
    assert routing.plug_body_rects(option(EB, design.DOWN)) == []
    assert routing.plug_body_rects({"side": None, "rects": [("box", (0, 0, 5, 5))]}) == []
    assert routing.plug_body_rects(None) == []
    straight = {"plug": {"style": "straight", "head_depth_mm": 34.0, "head_width_mm": 10.0}, "diameter_mm": 3.2}
    o = option(straight, None)
    assert routing.plug_body_rects(o) == [o["rects"][0][1]]


def test_inside_length_is_the_part_of_the_segment_in_the_rectangle():
    r = (0.0, 0.0, 10.0, 10.0)
    assert routing.inside_length((-5.0, 5.0), (15.0, 5.0), r) == pytest.approx(10.0)
    assert routing.inside_length((5.0, 5.0), (5.0, 20.0), r) == pytest.approx(5.0)
    assert routing.inside_length((-5.0, -5.0), (15.0, 15.0), r) == pytest.approx(10 * 2 ** 0.5)
    assert routing.inside_length((-5.0, 12.0), (15.0, 12.0), r) == 0.0
    assert routing.inside_length((-5.0, 10.0), (15.0, 10.0), r) == 0.0                     # along an edge: touching only


def test_a_cable_across_the_head_passes_under_a_grazing_one_does_not():
    o = option(EB, "right")      # head x 0..6.4, y -6.35..6.35; barrel y 6.35..19; exit (3.2, 22.5)
    assert routing.passes_under_own_plug(o, [[(3.2, 22.5), (3.2, -30.0)]])          # straight across the barrel and the head
    assert routing.passes_under_own_plug(o, [[(3.2, 22.5)], [(3.2, 5.0), (3.2, -30.0)]])   # (one of several polylines)
    assert not routing.passes_under_own_plug(o, [[(3.2, 22.5), (3.2, 40.0)]])        # goes the way the plug points
    assert not routing.passes_under_own_plug(o, [[(3.2, 22.5), (8.15, 20.75), (8.15, -8.1), (3.2, -30.0)]])   # round the front, one radius off
    assert not routing.passes_under_own_plug(o, [[(6.4, 30.0), (6.4, -30.0)]])       # runs along the head's front edge: touching only
    assert not routing.passes_under_own_plug(option(EB, design.DOWN), [[(3.2, 22.5), (3.2, -30.0)]])   # a plug pointing down: its cable goes down
    assert not routing.passes_under_own_plug(None, [[(0.0, 0.0), (1.0, 1.0)]])


# --- route_project -----------------------------------------------------------------------------------------------------
# Scene U (hand-made): A (20..70 x 60..100) with its output at (70, 80) facing right, B (20..70 x 160..260) with its input at (70, 180)
# facing right; the test cable "ra" (head 20 deep x 16 wide, no barrel, 6 mm cable): A's up exit (80, 66), A's down exit (80, 94), B's
# up exit (80, 166), B's down exit (80, 194); each end measures 8 + 6 = 14 mm. A's head: x 70..90, y 72..88; B's: x 70..90, y 172..188.
def scene_u(cables, extra=()):
    a, b = mm_item("i-a", "A", 20, 60, 50, 40), mm_item("i-b", "B", 20, 160, 50, 100)
    jd = {"a": [{"id": "out", "label": "Output", "function": "output", "x": 1.0, "y": 0.5, "facing": "right"}],
          "b": [{"id": "in", "label": "Input", "function": "input", "x": 1.0, "y": 0.2, "facing": "right"}]}
    layout = {"board": mm_item("i-board", "Board", 0, 0, 300, 300, "pedalboard"), "placed": {"a": a, "b": b},
              "obstacles": [a, b, *extra], "inst_item": {}, "jacks": jd, "outward_mm": 6.3}
    ctx = {"project": {"cables": {"type": "ra", **cables}}, "chain": ["a", "b"], "layout": layout, "errors": [], "warnings": [],
           "violations": [], "cables": {"power": []}}
    routing.route_project(ctx, {}, cable_types=TEST_TYPES)
    (c,) = [x for x in ctx["cable_list"] if x["kind"] == "signal"]
    return ctx, c


def test_a_free_direct_side_passes_under_nothing_and_its_length_is_unchanged():
    ctx, c = scene_u({})
    assert (c["exit_a"], c["exit_b"]) == ("right", "left") and c["status"] == "routed"
    assert not c["under_own_a"] and not c["under_own_b"]
    assert c["min_mm"] == pytest.approx(14 + 14 + 72.0, abs=0.01)         # exit (80, 94) straight down to B's exit (80, 166)
    assert c["path"][2:-2] == [(80.0, 94.0), (80.0, 166.0)]
    assert routing.under_own_cables(ctx["cable_list"]) == []


def test_a_fixed_side_away_from_the_target_turns_back_across_the_head_without_extra_length():
    ctx, c = scene_u({"overrides": {"S1": {"exit_a": "left"}}})              # A's up exit, the target lies below
    assert c["exit_a"] == "left" and c["status"] == "routed" and ctx["warnings"] == [] and ctx["errors"] == []
    assert c["under_own_a"] and not c["under_own_b"]
    # the cable runs straight from the exit (80, 66) down across A's head to B's exit (80, 166): 100 mm + the two plugs' 14 mm, nothing added for
    # passing under the plug (the owner's rule: no climb, no fold)
    assert c["path"][2:-2] == [(80.0, 66.0), (80.0, 166.0)]
    assert c["min_mm"] == pytest.approx(14 + 14 + 100.0, abs=0.01)
    assert routing.under_own_cables(ctx["cable_list"]) == ["S1"]


def test_both_ends_pass_under_their_own_plug_when_both_sides_are_fixed_away_from_the_target():
    ctx, c = scene_u({"overrides": {"S1": {"exit_a": "left", "exit_b": "right"}}})   # A up, B down: each plug lies between the cable and its target
    assert c["status"] == "routed" and c["under_own_a"] and c["under_own_b"]
    assert c["min_mm"] == pytest.approx(14 + 14 + 128.0, abs=0.01)                 # (80, 66) -> (80, 194), straight across both heads


def test_a_blocked_direct_side_sends_the_cable_the_other_way_across_the_plug():
    # C (72..88 x 90..140) holds A's down exit (80, 94) and its cable run: A's plug takes its up side, the cable turns back across the head
    ctx, c = scene_u({}, [mm_item("i-c", "C", 72, 90, 16, 50)])
    assert c["exit_a"] == "left" and c["status"] == "routed" and c["under_own_a"] and ctx["violations"] == []
    assert c["min_mm"] > 128.0                                                     # (longer than the straight line across the head: C is in the way)


def gap_scene(gap):
    """The practice board's S3 case: two pedals `gap` mm apart, A's output and B's input in the gap, the real Ernie Ball plug."""
    a, b = mm_item("i-a", "A", 20, 60, 50, 100), mm_item("i-b", "B", 70 + gap, 60, 50, 100)
    jd = {"a": [{"id": "out", "label": "Output", "function": "output", "x": 1.0, "y": 0.2, "facing": "right"}],
          "b": [{"id": "in", "label": "Input", "function": "input", "x": 0.0, "y": 0.5, "facing": "left"}]}
    layout = {"board": mm_item("i-board", "Board", 0, 0, 300, 200, "pedalboard"), "placed": {"a": a, "b": b},
              "obstacles": [a, b], "inst_item": {}, "jacks": jd, "outward_mm": 6.3}
    ctx = {"project": {"cables": {"type": "ernie_ball_flat_patch_ra"}}, "chain": ["a", "b"], "layout": layout, "errors": [], "warnings": [],
           "violations": [], "cables": {"power": []}}
    routing.route_project(ctx, {}, cable_types=TYPES)
    (c,) = [x for x in ctx["cable_list"] if x["kind"] == "signal"]
    return ctx, c


def test_in_a_narrow_gap_the_cable_passes_under_its_plugs_and_a_wide_gap_needs_none():
    ctx, narrow = gap_scene(6.5)       # both heads (6.4 deep) span the gap: the cable can only cross them
    assert narrow["status"] == "routed" and narrow["under_own_a"] and ctx["warnings"] == []
    ctx, wide = gap_scene(30.0)
    assert wide["status"] == "routed" and not wide["under_own_a"] and not wide["under_own_b"]


# --- the gig fixture: signal and DC cables --------------------------------------------------------------------------------
@functools.lru_cache(maxsize=1)
def gig_fixture_ctx():
    pedals, supplies = common.load_catalog()
    return build.validate(GIG_FIXTURE, pedals, supplies), pedals


def test_gig_fixture_cables_that_pass_under_their_own_plug():
    # (the plan's scan of the frozen gig: 2 signal and 2-3 DC legs cross their own plug; their lengths are the routed paths as before)
    ctx, _ = gig_fixture_ctx()
    got = routing.under_own_cables(ctx["cable_list"])
    assert got == ["S11", "S15", "P3", "P5", "P8.3"]
    by_id = {c["id"]: c for c in ctx["cable_list"]}
    assert (by_id["S11"]["under_own_a"], by_id["S11"]["under_own_b"]) == (False, True)
    assert (by_id["P3"]["under_own_a"], by_id["P3"]["under_own_b"]) == (False, True)     # a DC leg: the plug at the pedal
    assert (by_id["P8.3"]["under_own_a"], by_id["P8.3"]["under_own_b"]) == (True, False)  # a serial leg that starts at a pedal's plug


# --- the report ---------------------------------------------------------------------------------------------------------------
def test_the_exits_cell_says_which_end_passes_under_its_plug():
    c = {"exit_a": "left", "exit_b": "right", "under_own_a": True, "under_own_b": False}
    assert build.exits_cell(c) == "left (passes under its own plug) / right"
    assert build.exits_cell({**c, "under_own_a": False, "under_own_b": True}) == "left / right (passes under its own plug)"
    assert build.exits_cell({"exit_a": None, "exit_b": "down"}) == "- / down"          # (no flags: today's cell)
    assert build.exits_cell({"exit_a": None, "exit_b": "left", "under_own_b": True}) == "- / left (passes under its own plug)"


def test_the_readme_and_the_log_report_the_crossing_as_information():
    ctx, pedals = gig_fixture_ctx()
    text = "\n".join(build.routing_section(ctx))
    assert "| S11 |" in text and "(passes under its own plug)" in text
    assert "Passes under its own plug: S11, S15, P3, P5, P8.3." in text and "no extra length" in text
    assert build.under_own_line(ctx) == "routing: 5 cables pass under their own plug (S11, S15, P3, P5, P8.3)"
    assert not any("own plug" in w for w in ctx["warnings"] + ctx["errors"])           # information only
    empty, _ = scene_u({})
    assert build.under_own_line(empty) == "" and build.under_own_text(empty) == []
