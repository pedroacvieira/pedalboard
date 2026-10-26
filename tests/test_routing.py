"""Grid routing (scripts/routing.py), on small hand-made grids. All lengths in mm."""
import math
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import routing  # noqa: E402
import svgdraw  # noqa: E402

CFG = {**routing.DEFAULTS, "grid_mm": 6.0, "edge_margin_mm": 6.0}


def free_grid(nx=20, ny=10, cell=6.0):
    return routing.Grid(0, 0, nx * cell, ny * cell, cell)


def test_straight_path_on_an_empty_grid():
    g = free_grid()
    path = routing.astar(g, (0, 5), (9, 5), lambda c: 1.0)
    assert path[0] == (0, 5) and path[-1] == (9, 5)
    assert routing.path_length(g, path) == pytest.approx(9 * 6.0)


def test_diagonal_moves_are_used():
    g = free_grid()
    path = routing.astar(g, (0, 0), (5, 5), lambda c: 1.0)
    assert routing.path_length(g, path) == pytest.approx(5 * 6.0 * math.sqrt(2))


def test_path_goes_around_a_pedal_and_never_cuts_its_corner():
    g = free_grid()
    g.block_rect((30.0, 0.0, 42.0, 48.0))           # a wall from the back edge down to row 7 (cells x 5..6, y 0..7)
    path = routing.astar(g, (2, 2), (10, 2), lambda c: 1.0)
    assert path is not None and not (set(path) & g.blocked)
    assert max(c[1] for c in path) >= 8               # had to pass below the wall
    for a, b in zip(path, path[1:]):                   # no diagonal squeezes past a blocked corner
        if a[0] != b[0] and a[1] != b[1]:
            assert (b[0], a[1]) not in g.blocked and (a[0], b[1]) not in g.blocked


def test_no_path_when_walled_off():
    g = free_grid()
    g.block_rect((30.0, 0.0, 42.0, 60.0))            # full-height wall
    assert routing.astar(g, (2, 2), (10, 2), lambda c: 1.0) is None


def test_block_rect_blocks_cell_centres_inside_the_grown_rectangle():
    g = free_grid()
    g.block_rect((5.0, 5.0, 13.0, 7.0))               # cell centres are at 3, 9, 15 ...: none inside 5..13 x 5..7
    assert g.blocked == set()
    g.block_rect((5.0, 5.0, 13.0, 7.0), grow=3.0)      # grown to 2..16 x 2..10 -> centres x 3, 9, 15 and y 3, 9
    assert g.blocked == {(0, 0), (1, 0), (2, 0), (0, 1), (1, 1), (2, 1)}


@pytest.mark.parametrize("offset", [0.0, 0.3, 0.7, 1.0, 1.4, 1.9])
def test_a_gap_one_cable_diameter_wide_is_open_whatever_the_grid_alignment(offset):
    cfg = {**routing.DEFAULTS, "grid_mm": 2.0, "edge_margin_mm": 0.0}
    board = (0.0, 0.0, 60.0, 30.0)
    left, right = (0.0, 0.0, 27.0 + offset, 30.0), (33.0 + offset, 0.0, 60.0, 30.0)   # 6 mm apart
    g = routing.build_grid(board, [left, right], front_y=30.0, cfg=cfg)
    assert any(all(g.free((i, j)) for j in range(g.ny)) for i in range(g.nx))       # a full free column


@pytest.mark.parametrize("offset", [0.0, 0.5, 1.0, 1.5])
def test_a_gap_narrower_than_the_cable_minus_a_cell_is_closed(offset):  # < 6 mm - 2 mm cell
    cfg = {**routing.DEFAULTS, "grid_mm": 2.0, "edge_margin_mm": 0.0}
    left, right = (0.0, 0.0, 28.05 + offset, 30.0), (31.95 + offset, 0.0, 60.0, 30.0)  # 3.9 mm apart
    g = routing.build_grid((0.0, 0.0, 60.0, 30.0), [left, right], front_y=30.0, cfg=cfg)
    assert not any(g.free((i, j)) for i in range(g.nx) for j in range(g.ny))


def test_build_grid_area_has_margin_at_back_and_sides_and_stops_at_the_front():
    board = (100.0, 100.0, 400.0, 300.0)
    g = routing.build_grid(board, [], front_y=280.0, cfg=CFG)
    assert g.x0 == pytest.approx(94.0) and g.y0 == pytest.approx(94.0)       # one cable diameter outside left / back
    assert g.x0 + g.nx * g.cell >= 406.0 - 1e-9                              # and right
    assert g.y0 + g.ny * g.cell == pytest.approx(280.0, abs=6.0)             # cut at the lowest pedals
    assert not g.inside(g.cell_of(250.0, 290.0))                             # in front of the lowest row: outside


def test_stacking_limit_spreads_cables_over_a_corridor():
    g = free_grid(nx=12, ny=9)
    for r in ((18.0, 0.0, 54.0, 24.0), (18.0, 30.0, 54.0, 54.0)):           # a corridor two cells wide (rows 4..4 and 5)
        g.block_rect(r)
    nets = [(f"n{i}", (0, 4), (11, 4)) for i in range(3)]
    paths, users, overflow, _ = routing.route_all(g, nets, max_stack=2, iterations=20)
    assert all(paths.values())
    corridor = [c for c in users if 3 <= c[0] <= 8]
    assert max(len(users[c]) for c in corridor) <= 2 or overflow


def test_too_many_cables_through_a_one_cell_gap_report_overflow():
    g = free_grid(nx=12, ny=9)
    g.block_rect((30.0, 0.0, 36.0, 24.0))
    g.block_rect((30.0, 30.0, 36.0, 54.0))            # single free cell at (5, 4)
    nets = [(f"n{i}", (1, 4), (10, 4)) for i in range(3)]
    paths, users, overflow, _ = routing.route_all(g, nets, max_stack=2, iterations=10)
    assert (5, 4) in overflow and len(users[(5, 4)]) == 3


def test_two_cables_fit_through_a_one_cell_gap_with_the_default_limit():
    g = free_grid(nx=12, ny=9)
    g.block_rect((30.0, 0.0, 36.0, 24.0))
    g.block_rect((30.0, 30.0, 36.0, 54.0))
    nets = [(f"n{i}", (1, 4), (10, 4)) for i in range(2)]
    paths, users, overflow, _ = routing.route_all(g, nets, max_stack=2, iterations=10)
    assert not overflow and len(users[(5, 4)]) == 2


def test_settings_defaults_follow_the_cable_diameter():
    s = routing.settings({"cables": {"diameter_mm": 5}})
    assert s["grid_mm"] == 2.0 and s["edge_margin_mm"] == 5 and s["max_stack"] == 2 and s["default_tip"] == "TS"


# --- plug heads in route_project ------------------------------------------------------------------
TYPES = {"ra": {"name": "test right angle", "role": "patch", "diameter_mm": 6.0, "tips": "TS",
                "plug": {"style": "right_angle", "head_depth_mm": 20.0, "head_width_mm": 16.0}},
         "st": {"name": "test straight", "role": "reference", "diameter_mm": 5.0, "tips": "TS",
                "plug": {"style": "straight", "head_depth_mm": 40.0, "head_width_mm": 12.0}}}


def mm_item(iid, title, left, top, w, h, kind="pedal"):
    return {"id": iid, "kind": kind, "title": title, "rot": 0, "w_mm": w, "h_mm": h, "left_mm": left, "top_mm": top}


def plug_ctx(cables, extra_obstacles=()):
    """Board 0..300 x 0..200. A (20..70 x 60..160) out at (70, 80) facing right; B (200..250 x 60..160) in at
    (200, 140) facing left. With the 20 x 16 head (cable axis 10 mm out, exit 14 mm to the side):
    A exits left/up at (80, 66) or right/down at (80, 94); B exits left/down at (190, 154) or right/up at (190, 126)."""
    a, b = mm_item("i-a", "A", 20, 60, 50, 100), mm_item("i-b", "B", 200, 60, 50, 100)
    jd = {"a": [{"id": "out", "label": "Output", "function": "output", "x": 1.0, "y": 0.2, "facing": "right"}],
          "b": [{"id": "in", "label": "Input", "function": "input", "x": 0.0, "y": 0.8, "facing": "left"}]}
    layout = {"board": mm_item("i-board", "Board", 0, 0, 300, 200, "pedalboard"), "placed": {"a": a, "b": b},
              "obstacles": [a, b, *extra_obstacles], "inst_item": {}, "jacks": jd, "outward_mm": 6.3}
    return {"project": {"cables": cables}, "chain": ["a", "b"], "layout": layout, "errors": [], "warnings": [],
            "violations": [], "cables": {"power": []}}


def test_router_picks_the_shorter_exit_sides():
    ctx = plug_ctx({"type": "ra"})
    routing.route_project(ctx, {}, cable_types=TYPES)
    (c,) = [x for x in ctx["cable_list"] if x["kind"] == "signal"]
    assert c["status"] == "routed" and (c["exit_a"], c["exit_b"]) == ("right", "right")   # (80, 94) -> (190, 126)
    assert c["path"][0] == (70.0, 80.0) and c["path"][1] == (80.0, 80.0) and c["path"][2] == (80.0, 94.0)
    # measured from 10 mm in front of each jack (half the 20 mm head): 2 x (8 + 6) mm to the exits, then 110 mm
    # across and 32 mm down; the open field smooths to one segment: hypot(110, 32) = 114.56 mm (the grid path was
    # octile 110 + 0.414 x 32 = 123.3 mm)
    assert c["min_mm"] == pytest.approx(28 + math.hypot(110, 32), abs=0.01)
    assert c["path"][2:4] == [(80.0, 94.0), (190.0, 126.0)] and len(c["path"]) == 6
    assert ctx["violations"] == [] and ctx["errors"] == []
    fixed = plug_ctx({"type": "ra", "overrides": {"S1": {"exit_a": "left"}}})
    routing.route_project(fixed, {}, cable_types=TYPES)
    (f,) = [x for x in fixed["cable_list"] if x["kind"] == "signal"]
    assert f["exit_a"] == "left" and f["min_mm"] > c["min_mm"]


def test_a_corridor_that_only_exists_in_the_outline_is_routed():
    # a wall between A and B over the whole routing height: its box closes the way, its outline has a 40 mm notch
    wall = mm_item("i-c", "C", 120, -10, 40, 170)
    closed = plug_ctx({"type": "ra"}, extra_obstacles=[wall])
    routing.route_project(closed, {}, cable_types=TYPES)
    (c,) = [x for x in closed["cable_list"] if x["kind"] == "signal"]
    assert c["status"].startswith("unroutable")
    notched = plug_ctx({"type": "ra"}, extra_obstacles=[wall])
    notched["layout"]["shapes"] = {"i-c": [(120, -10, 160, 40), (120, 80, 160, 160)]}
    routing.route_project(notched, {}, cable_types=TYPES)
    (c,) = [x for x in notched["cable_list"] if x["kind"] == "signal"]
    assert c["status"] == "routed"
    (ys,) = [[p[1] + (q[1] - p[1]) * (140 - p[0]) / (q[0] - p[0]) for p, q in zip(c["path"], c["path"][1:])
              if p[0] < 140 <= q[0]]]                              # where the path crosses x = 140: inside the notch
    assert len(ys) == 1 and 40 < ys[0] < 80


def test_plug_parts_are_blocked_by_the_outline_not_the_box():
    box = mm_item("i-c", "C", 75, 0, 100, 200)                 # 5 mm in front of A's output
    head = ("head", (70, 60, 90, 76))                          # A's plug head: 20 deep, in front of the jack
    opt = {"rects": [head]}
    ((part, ob, ov),) = routing.blocked_parts(opt, "i-a", [box])
    assert (part, ob["id"], ov) == ("head", "i-c", (15.0, 16.0))    # the box: 15 mm in
    ((_, _, ov),) = routing.blocked_parts(opt, "i-a", [box], {"i-c": [(85, 0, 100, 200), (140, 0, 175, 200)]})
    assert ov == (5.0, 16.0)                                   # the outline: only 5 mm in
    assert routing.blocked_parts(opt, "i-a", [box], {"i-c": [(120, 0, 175, 200)]}) == []   # a plug over the box but not the outline
    best = routing.blocked_parts(opt, "i-a", [box], {"i-c": [(88, 0, 99, 200), (80, 0, 99, 70)]})   # one hit: the larger overlap
    assert [ov for _, _, ov in best] == [(10.0, 10.0)]
    ctx = plug_ctx({"type": "ra"}, extra_obstacles=[box])
    ctx["layout"]["shapes"] = {"i-c": [(120, 0, 175, 200)]}
    routing.route_project(ctx, {}, cable_types=TYPES)
    assert ctx["violations"] == [] and ctx["errors"] == []
    ctx = plug_ctx({"type": "ra"}, extra_obstacles=[box])
    ctx["layout"]["shapes"] = {"i-c": [(85, 0, 175, 200)]}
    routing.route_project(ctx, {}, cable_types=TYPES)
    v = next(v for v in ctx["violations"] if v["jack"] == "a.out")
    assert v["obstacle"] == "C" and v["part"] == "head" and v["depth_mm"] == pytest.approx(5.0)


def test_straight_plug_type_per_cable_and_its_diameter():
    ctx = plug_ctx({"type": "ra", "overrides": {"S1": {"type": "st"}}})
    routing.route_project(ctx, {}, cable_types=TYPES)
    (c,) = [x for x in ctx["cable_list"] if x["kind"] == "signal"]
    assert c["type"] == "st" and (c["exit_a"], c["exit_b"]) == (None, None)
    assert c["path"][1] == (70.0 + 40 + 5, 80.0)            # head 40 + one run of its own 5 mm diameter
    assert ctx["routing"]["settings"]["diameter_mm"] == 6.0  # the grid fits the widest type in use


def test_blocked_head_is_a_clearance_violation_naming_type_and_side():
    wall = mm_item("i-c", "C", 75, 0, 100, 200)              # 5 mm in front of A's output, the full board height
    ctx = plug_ctx({"type": "ra"}, extra_obstacles=[wall])
    routing.route_project(ctx, {}, cable_types=TYPES)
    v = next(v for v in ctx["violations"] if v["jack"] == "a.out")
    assert v["obstacle"] == "C" and v["part"] == "head" and v["depth_mm"] == pytest.approx(15.0)   # 20 deep - 5 mm gap
    assert v["cable_type"] == "ra" and v["side"] in ("left", "right")
    assert any("clearance: a.out" in w and "ra right-angle plug, cable exits" in w for w in ctx["warnings"])
    (c,) = [x for x in ctx["cable_list"] if x["kind"] == "signal"]
    assert c["status"].startswith("unroutable: the cable exit of the plug at a")


def test_strict_clearance_and_unknown_type_are_errors():
    ctx = plug_ctx({"type": "nope"})
    routing.route_project(ctx, {}, cable_types=TYPES)
    assert any("type=nope" in e for e in ctx["errors"])
    wall = mm_item("i-c", "C", 75, 0, 100, 200)
    ctx = plug_ctx({"type": "ra"}, extra_obstacles=[wall])
    ctx["project"]["validation"] = {"strict_clearance": True}
    routing.route_project(ctx, {}, cable_types=TYPES)
    assert any(e.startswith("clearance: a.out") for e in ctx["errors"])


def test_squeezing_through_a_narrow_gap_is_reported():
    # a wall from beyond the back margin down to y = 198: only a 2 mm gap is left in front of it (the area ends at
    # y = 200, the front of the lowest pedals); cell centres at y 197 / 199 are within 1.99 mm of the wall (closed),
    # but y 199 is outside its body, so squeezing gets through
    wall = mm_item("i-w", "W", 120, -10, 20, 198 + 10)
    ctx = plug_ctx({"type": "ra"}, extra_obstacles=[wall])
    ctx["layout"]["board"] = mm_item("i-board", "Board", 0, 0, 300, 200, "pedalboard")
    ctx["layout"]["placed"]["a"]["h_mm"] = ctx["layout"]["placed"]["b"]["h_mm"] = 140     # lowest pedals reach y = 200
    routing.route_project(ctx, {}, cable_types=TYPES)
    (c,) = [x for x in ctx["cable_list"] if x["kind"] == "signal"]
    assert c["status"] == "routed, squeezed (gap narrower than the cable)"
    assert any("only fits by squeezing" in w for w in ctx["warnings"])


def test_settings_take_the_diameter_from_the_cable_type():
    s = routing.settings({"cables": {"type": "st"}}, TYPES)
    assert s["diameter_mm"] == 5.0 and s["exit_run_mm"] == 5.0 and s["edge_margin_mm"] == 5.0
    s = routing.settings({"cables": {"type": "st", "diameter_mm": 7}}, TYPES)
    assert s["diameter_mm"] == 7


def test_real_cable_catalog_is_valid():
    from common import load_cable_types
    types = load_cable_types()
    assert routing.validate_types(types) == []
    assert {"ernie_ball_flat_patch_ra", "fender_pro_instrument_ra", "dc_ra_2_1_low_profile", "generic_straight"} <= set(types)


# --- power plugs (DC) ----------------------------------------------------------------------------
DC = {"dc": {"name": "test DC right angle", "role": "power", "diameter_mm": 3.5, "tips": "DC 2.1 mm",
             "plug": {"style": "right_angle", "head_depth_mm": 10.0, "head_width_mm": 10.0}}}


def power_ctx(extra_obstacles=(), power_type="dc", overrides=None):
    """plug_ctx plus a power jack on A at (45, 60) facing top and one power cable to it. DC head 10 x 10 -> head
    (40, 50, 50, 60); cable axis 5 mm out (y 55), body to 5 mm from the axis, then a 3.5 mm run: left (-x) cable
    (36.5, 53.25, 40, 56.75), right (+x) cable (50, 53.25, 53.5, 56.75)."""
    ctx = plug_ctx({"type": "ra", "power_type": power_type, "overrides": overrides or {}}, extra_obstacles)
    ctx["layout"]["jacks"]["a"].append({"id": "power", "label": "9V", "function": "power", "x": 0.5, "y": 0.0, "facing": "top"})
    ctx["cables"] = {"power": [{"from": "psu1.1", "to": "a.power"}]}
    return ctx


def test_power_plug_takes_the_free_exit_side():
    wall = mm_item("i-c", "C", 30, 0, 9.9, 58)               # reaches x 39.9: 3.4 mm into the left cable run only
    ctx = power_ctx([wall])
    routing.route_project(ctx, {}, cable_types={**TYPES, **DC})
    (p,) = [x for x in ctx["cable_list"] if x["kind"] == "power"]
    assert p["type"] == "dc" and p["exit_b"] == "right"
    assert not [v for v in ctx["violations"] if v["jack"] == "a.power"]
    heads = [h for h in ctx["routing"]["heads"] if h["cable"] == "P1"]
    assert dict(heads[0]["rects"])["head"] == pytest.approx((40, 50, 50, 60))


def test_power_plug_blocked_on_both_sides_reports_the_smaller_overlap():
    left = mm_item("i-c", "C", 30, 0, 9.9, 58)                # 3.4 mm into the left run
    right = mm_item("i-d", "D", 51, 0, 29, 58)                # 2.5 mm into the right run
    ctx = power_ctx([left, right])
    routing.route_project(ctx, {}, cable_types={**TYPES, **DC})
    (v,) = [v for v in ctx["violations"] if v["jack"] == "a.power"]
    assert (v["obstacle"], v["side"], v["part"], v["cable_type"], v["cable"]) == ("D", "right", "cable", "dc", "P1")
    assert v["depth_mm"] == pytest.approx(2.5)
    assert any("clearance: a.power" in w and "dc right-angle plug, cable exits right" in w for w in ctx["warnings"])


def test_power_plug_head_blocked_and_side_fixed_by_override():
    shelf = mm_item("i-e", "E", 0, 0, 300, 52)               # ends 8 mm in front of the jack face: 2 mm into the head
    ctx = power_ctx([shelf], overrides={"P1": {"exit_b": "right"}})
    routing.route_project(ctx, {}, cable_types={**TYPES, **DC})
    (v,) = [v for v in ctx["violations"] if v["jack"] == "a.power"]
    assert v["part"] == "head" and v["side"] == "right" and v["depth_mm"] == pytest.approx(2.0)


def test_project_type_roles_are_checked():
    types = {**TYPES, **DC, "inst": {**TYPES["ra"], "role": "instrument"}}
    ctx = plug_ctx({"type": "inst", "power_type": "ra"})
    routing.route_project(ctx, {}, cable_types=types)
    assert any("cables.type: inst is a instrument cable" in e for e in ctx["errors"])
    assert any("cables.power_type: ra" in e for e in ctx["errors"])
    ctx = plug_ctx({"type": "ra", "power_type": "dc", "overrides": {"S1": {"type": "dc"}}})
    routing.route_project(ctx, {}, cable_types=types)
    assert any("cables.overrides.S1.type: dc is a DC power cable" in e for e in ctx["errors"])


def test_power_cable_polarity_follows_the_pedal():
    ctx = power_ctx()
    routing.route_project(ctx, {"a": {"power_consumption": {"polarity": "center_positive"}}}, cable_types={**TYPES, **DC})
    (p,) = [x for x in ctx["cable_list"] if x["kind"] == "power"]
    assert p["polarity"] == "center_positive" and ctx["errors"] == []
    ctx = power_ctx()
    routing.route_project(ctx, {}, cable_types={**TYPES, **DC})          # unknown stays unknown (never guessed)
    assert [x for x in ctx["cable_list"] if x["kind"] == "power"][0]["polarity"] is None and ctx["errors"] == []


def test_null_override_keeps_the_default_and_does_not_crash():
    ctx = plug_ctx({"type": "ra", "overrides": {"S1": None}})
    routing.route_project(ctx, {}, cable_types=TYPES)
    ctx2 = plug_ctx({"type": "ra", "overrides": {"S1": {"type": None}}})
    routing.route_project(ctx2, {}, cable_types=TYPES)
    for x in (ctx, ctx2):
        (c,) = [c for c in x["cable_list"] if c["kind"] == "signal"]
        assert c["type"] == "ra" and c["status"] == "routed" and x["errors"] == []


def test_clearance_reports_the_deepest_part_per_obstacle():
    opt = {"side": "left", "hits": [("head", {"id": "x"}, (0.2, 5.0)), ("cable", {"id": "x"}, (3.0, 8.0))]}
    (hit,) = routing.deepest_hits(opt, "right")     # facing right: head depth along x (0.2), cable along y (8.0)
    assert hit[0] == "cable" and hit[2] == pytest.approx(8.0)


# --- smoothing (string pulling) -------------------------------------------------------------------
def min_dist(points, rect):
    return min(routing.seg_rect_distance(p, q, rect) for p, q in zip(points, points[1:]))


def test_seg_rect_distance_is_exact():
    r = (0.0, 0.0, 10.0, 10.0)
    assert routing.seg_rect_distance((-5, 5), (15, 5), r) == 0.0                       # through it
    assert routing.seg_rect_distance((2, 2), (4, 4), r) == 0.0                         # inside
    assert routing.seg_rect_distance((0, 14), (10, 14), r) == pytest.approx(4.0)       # parallel, 4 mm above
    assert routing.seg_rect_distance((-4, 0), (-4, 10), r) == pytest.approx(4.0)       # left, 4 mm away
    # diagonal segment past the corner (10, 10): from (13, 20) to (20, 13) the nearest point is (16.5, 16.5)
    assert routing.seg_rect_distance((13, 20), (20, 13), r) == pytest.approx(math.hypot(6.5, 6.5))
    # segment ends short of the rectangle: the end point (12, 5) is 2 mm from the right side
    assert routing.seg_rect_distance((30, 5), (12, 5), r) == pytest.approx(2.0)


def test_smooth_turns_a_staircase_in_the_open_into_one_segment():
    stairs = [(0, 0), (10, 0), (10, 10), (20, 10), (20, 20)]
    out = routing.smooth(stairs, [], 3.0, {})
    assert out == [(0, 0), (20, 20)] and routing.polyline_length(out) == pytest.approx(20 * math.sqrt(2))
    assert routing.smooth([(0, 0), (5, 5)], [], 3.0, {}) == [(0, 0), (5, 5)]            # nothing to remove


def test_smooth_keeps_one_corner_at_the_grown_pedal_corner():
    pedal = (0.0, 0.0, 20.0, 20.0)
    path = [(5, 23), (14, 23), (23, 23), (23, 14), (23, 5)]                  # 3 mm (= radius) below / right of it
    out = routing.smooth(path, [pedal], 3.0, {})
    # (5,23)->(23,23) is 3 mm from the pedal (valid); (5,23)->(23,14) cuts through it. Then (23,23)->(23,5) is valid.
    assert out == [(5, 23), (23, 23), (23, 5)] and routing.polyline_length(out) == pytest.approx(36.0)
    assert min_dist(out, pedal) >= 3.0 - 1e-6


def test_smooth_never_moves_a_squeezed_stretch_closer_to_the_pedal():
    pedal = (0.0, 0.0, 20.0, 20.0)
    path = [(10, 22), (16, 22), (22, 22), (22, 16), (22, 10)]                 # 2 mm from the pedal: squeezed (radius 3)
    out = routing.smooth(path, [pedal], 3.0, {})
    # the corner stays (the diagonal (10,22)->(22,10) crosses the pedal) and nothing comes closer than the 2 mm of the path
    assert out == [(10, 22), (22, 22), (22, 10)]
    assert min_dist(out, pedal) >= 2.0 - 1e-6
    # a slightly rounded corner at 2.83 mm (the true corner distance of (22, 22)) is not cut closer than 2 mm either
    out = routing.smooth([(10, 22), (20, 23), (23, 20), (22, 10)], [pedal], 3.0, {})
    assert min_dist(out, pedal) >= min(2.0, 2.0) - 1e-6 and (20, 23) in out and (23, 20) in out


def test_smooth_refuses_a_shortcut_across_a_plug_the_path_did_not_cross():
    plug = {"k": [(40.0, -5.0, 50.0, 5.0)]}
    path = [(30, 0), (30, 15), (60, 15), (60, 0)]                           # detour round the plug, 10 mm away from it
    assert routing.smooth(path, [], 3.0, plug) == path                      # (30,0)->(60,0) would cross it
    assert routing.smooth(path, [], 3.0, plug, own_plugs=("k",)) == [(30, 0), (60, 0)]   # an own plug may be crossed
    # a path that already touched it may be shortened across it
    assert routing.smooth([(30, 0), (45, 0), (60, 0)], [], 3.0, plug) == [(30, 0), (60, 0)]


# --- the plug limit in route_all -------------------------------------------------------------------
def test_three_cables_through_a_one_cell_gap_over_a_plug_are_reported_but_the_owner_never_counts():
    g = free_grid(nx=12, ny=9)
    g.block_rect((30.0, 0.0, 36.0, 24.0))
    g.block_rect((30.0, 30.0, 36.0, 54.0))            # single free cell at (5, 4), which is the plug
    nets = [(f"n{i}", (1, 4), (10, 4)) for i in range(3)]
    paths, _, _, over = routing.route_all(g, nets, max_stack=5, iterations=10, plugs={"p.out": (None, {(5, 4)})})
    assert all(paths.values()) and over == {"p.out": ["n0", "n1", "n2"]}
    # the same gap is the plug of n0: only n1 and n2 count against the limit of 2
    _, _, _, over = routing.route_all(g, nets, max_stack=5, iterations=10, plugs={"p.out": ("n0", {(5, 4)})})
    assert over == {}
    _, _, _, over = routing.route_all(g, nets, max_stack=5, iterations=10, plugs={"p.out": (None, {(5, 4)})}, max_over_plug=3)
    assert over == {}


def test_a_third_cable_detours_round_a_plug_when_it_can():
    g = free_grid(nx=12, ny=9)
    plug = {(5, 3), (5, 4), (5, 5)}
    nets = [(f"n{i}", (1, 4), (10, 4)) for i in range(3)]
    paths, _, overflow, over = routing.route_all(g, nets, max_stack=5, iterations=20, plugs={"p.out": (None, plug)})
    assert over == {} and not overflow and all(paths.values())
    assert sum(1 for p in paths.values() if set(p) & plug) == 2               # two cross it, one goes round
    # without plugs the three take the same straight line
    paths, _, _, over = routing.route_all(g, nets, max_stack=5, iterations=20)
    assert over == {} and all(set(p) & plug for p in paths.values())


def test_plug_cells_follow_the_grown_rectangle():
    g = free_grid()
    assert routing.rect_cells(g, (5.0, 5.0, 13.0, 7.0)) == set()              # no cell centre (3, 9, 15 ...) inside
    assert routing.rect_cells(g, (5.0, 5.0, 13.0, 7.0), 3.0) == {(0, 0), (1, 0), (2, 0), (0, 1), (1, 1), (2, 1)}


# --- smoothing + plug limit in route_project --------------------------------------------------------
def test_route_project_smooths_the_path_and_never_lengthens_it(monkeypatch):
    wall = mm_item("i-c", "C", 120, 0, 20, 130)               # between A and B, open below y = 130 (front of the pedals: 160)
    ctx = plug_ctx({"type": "ra"}, extra_obstacles=[wall])
    routing.route_project(ctx, {}, cable_types=TYPES)
    (c,) = [x for x in ctx["cable_list"] if x["kind"] == "signal"]
    monkeypatch.setattr(routing, "smooth", lambda pts, *a, **k: list(pts))  # the old, unsmoothed formula
    old = plug_ctx({"type": "ra"}, extra_obstacles=[wall])
    routing.route_project(old, {}, cable_types=TYPES)
    (o,) = [x for x in old["cable_list"] if x["kind"] == "signal"]
    assert c["status"] == "routed" and c["min_mm"] < o["min_mm"] - 2.0
    assert len(c["path"]) < len(o["path"]) / 3
    # the path is the lead, the corners and the other lead; it stays as far from the wall as the grid path did
    wall_r = (120.0, 0.0, 140.0, 130.0)
    grid_min = min(routing.point_rect_distance(p, wall_r) for p in o["path"][2:-2])
    assert min_dist(c["path"][2:-2], wall_r) >= min(3.0, grid_min) - 1e-6
    assert c["path"][0] == (70.0, 80.0) and c["path"][-1] == (200.0, 140.0)
    # min_mm = both measure lengths + the smoothed polyline from exit to exit
    exits = c["path"][2:-2]
    assert c["min_mm"] == pytest.approx(2 * (8 + 6) + routing.polyline_length(exits), abs=1e-6)


def test_a_cable_starting_next_to_a_plug_does_not_cross_it():
    ctx = power_ctx()
    ctx["project"]["cables"]["max_over_plug"] = 0
    # A's power jack moves to its right side at y = 100: the DC head (70..80 x 95..105), grown by 2 mm, holds S1's
    # cable exit cell (80, 94) only: the end cells of a cable never count as crossing
    ctx["layout"]["jacks"]["a"][-1].update(x=1.0, y=0.4, facing="right")
    routing.route_project(ctx, {}, cable_types={**TYPES, **DC})
    (c,) = [x for x in ctx["cable_list"] if x["kind"] == "signal"]
    assert ctx["routing"]["plug_over"] == {} and c["status"] == "routed"


def test_plug_over_the_limit_is_a_routing_finding_and_an_appended_status(monkeypatch):
    real = routing.route_all

    def over(*a, **k):   # the router's crossing logic is tested on route_all; here only the reporting
        paths, users, overflow, _ = real(*a, **k)
        return paths, users, overflow, {"a.power": ["S1"]}
    monkeypatch.setattr(routing, "route_all", over)
    ctx = power_ctx()
    routing.route_project(ctx, {}, cable_types={**TYPES, **DC})
    (c,) = [x for x in ctx["cable_list"] if x["kind"] == "signal"]
    assert any(w.startswith("routing: S1 crosses the plug at a.power") and "(limit 2 other cables)" in w for w in ctx["warnings"])
    assert c["status"] == "routed, over the plug limit"


# --- lanes (drawing geometry for cables in the same corridor) ---------------------------------------
AREA = (0.0, 0.0, 400.0, 300.0)


def seg_cross(p, q, r, s):
    """True when segments pq and rs properly intersect."""
    def o(a, b, c):
        return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])
    return o(p, q, r) * o(p, q, s) < 0 and o(r, s, p) * o(r, s, q) < 0


def test_two_cables_on_the_same_line_get_lanes_one_width_apart():
    # both run (0, 100) -> (100, 100): lanes at y = 100 -/+ 3 (width 6), exits (first and last corner) stay put
    routes = {"S1": ([(0.0, 100.0), (100.0, 100.0)], set()), "S2": ([(0.0, 100.0), (100.0, 100.0)], set())}
    res = routing.lanes(routes, [], {}, AREA, 6.0)
    a, b = res["S1"]["corners"], res["S2"]["corners"]
    assert res["S1"]["stacked"] == [] and res["S2"]["stacked"] == []
    for c in (a, b):
        assert c[0] == (0.0, 100.0) and c[-1] == (100.0, 100.0)
        assert len(c) == 4 and c[1][1] == c[2][1] and (c[1][0], c[2][0]) == (0.0, 100.0)   # extra corners at the exits
    assert (a[1][1], b[1][1]) == pytest.approx((97.0, 103.0))      # tie in position: S1 before S2, the lower y first
    assert b[1][1] - a[1][1] == pytest.approx(6.0)                    # centre distance = one width


def test_three_cables_get_offsets_minus_width_zero_plus_width():
    routes = {f"S{i}": ([(0.0, 100.0), (100.0, 100.0)], set()) for i in (1, 2, 3)}
    res = routing.lanes(routes, [], {}, AREA, 6.0)
    assert res["S1"]["corners"][1][1] == pytest.approx(94.0) and res["S3"]["corners"][1][1] == pytest.approx(106.0)
    assert res["S2"]["corners"] == [(0.0, 100.0), (100.0, 100.0)]        # the middle lane is the centreline itself


def test_lanes_follow_the_side_the_cables_come_from_and_do_not_cross():
    # S1 comes from above (y 70) and leaves above, S2 from below (y 130) and leaves below; the bundle is the straight
    # part y = 100, x 60..140. Position along the normal (down): S1 -30 + -30 = -60, S2 +60 -> S1 gets the upper lane
    # (y = 97), S2 y = 103. Mitre of S1's first corner: its entering segment (50,70)->(60,100) meets y = 97 at x = 59.
    routes = {"S2": ([(50.0, 130.0), (60.0, 100.0), (140.0, 100.0), (150.0, 130.0)], set()),
              "S1": ([(50.0, 70.0), (60.0, 100.0), (140.0, 100.0), (150.0, 70.0)], set())}
    res = routing.lanes(routes, [], {}, AREA, 6.0)
    s1, s2 = res["S1"]["corners"], res["S2"]["corners"]
    assert s1 == pytest.approx([(50.0, 70.0), (59.0, 97.0), (141.0, 97.0), (150.0, 70.0)])
    assert s2 == pytest.approx([(50.0, 130.0), (59.0, 103.0), (141.0, 103.0), (150.0, 130.0)])
    assert not any(seg_cross(p, q, r, s) for p, q in zip(s1, s1[1:]) for r, s in zip(s2, s2[1:]))


def test_a_bundle_squeezed_between_two_pedals_stays_stacked():
    # pedals leave a 6 mm gap (y 97..103): the centreline at y = 100 is exactly one radius (3) from both; a lane at
    # +-3 would touch, +-1.5 is still closer than the radius
    gap = [(0.0, 0.0, 400.0, 97.0), (0.0, 103.0, 400.0, 200.0)]
    routes = {"S1": ([(0.0, 100.0), (100.0, 100.0)], set()), "S2": ([(0.0, 100.0), (100.0, 100.0)], set())}
    res = routing.lanes(routes, gap, {}, AREA, 6.0)
    assert res["S1"]["corners"] == routes["S1"][0] and res["S2"]["corners"] == routes["S2"][0]
    assert res["S1"]["stacked"] == ["S2"] and res["S2"]["stacked"] == ["S1"]
    assert res["S1"]["stacked_runs"] == [routes["S1"][0]]


def test_stacked_runs_cover_only_the_stacked_stretch():
    # S1 runs on through the 6 mm gap (x 0..100) and then turns down into open space: only the gap is stacked
    gap = [(0.0, 0.0, 100.0, 97.0), (0.0, 103.0, 100.0, 200.0)]
    routes = {"S1": ([(0.0, 100.0), (100.0, 100.0), (150.0, 250.0)], set()),
              "S2": ([(0.0, 100.0), (100.0, 100.0)], set())}
    res = routing.lanes(routes, gap, {}, AREA, 6.0)
    assert res["S1"]["stacked_runs"] == [[(0.0, 100.0), (100.0, 100.0)]] and res["S2"]["stacked_runs"] == [routes["S2"][0]]


def test_half_spacing_is_tried_when_the_full_one_does_not_fit():
    # a 9 mm gap (y 95.5..104.5): +-3 would leave 1.5 mm to a pedal (radius 3), +-1.5 keeps 3.0
    gap = [(0.0, 0.0, 400.0, 95.5), (0.0, 104.5, 400.0, 200.0)]
    routes = {"S1": ([(0.0, 100.0), (100.0, 100.0)], set()), "S2": ([(0.0, 100.0), (100.0, 100.0)], set())}
    res = routing.lanes(routes, gap, {}, AREA, 6.0)
    assert res["S1"]["stacked"] == [] and res["S2"]["stacked"] == []
    assert res["S2"]["corners"][1][1] - res["S1"]["corners"][1][1] == pytest.approx(3.0)


def test_lanes_stay_inside_the_routing_area():
    routes = {"S1": ([(0.0, 1.0), (100.0, 1.0)], set()), "S2": ([(0.0, 1.0), (100.0, 1.0)], set())}   # 1 mm from the edge
    res = routing.lanes(routes, [], {}, AREA, 6.0)       # +-3 leaves the area: the lane set shifts away from the edge
    ys = sorted(res[c]["corners"][1][1] for c in ("S1", "S2"))
    assert res["S1"]["stacked"] == [] and ys[0] >= AREA[1] and ys[1] - ys[0] == pytest.approx(6.0)
    assert ys[0] == pytest.approx(AREA[1])               # closest to centred: the inner lane right at the edge
    wall = {"S1": ([(0.0, 1.0), (100.0, 1.0)], set()), "S2": ([(0.0, 1.0), (100.0, 1.0)], set())}
    res = routing.lanes(wall, [(0.0, 3.0, 100.0, 20.0)], {}, AREA, 6.0)   # a pedal 2 mm below, the edge 1 mm above
    assert res["S1"]["stacked"] == ["S2"] and res["S1"]["corners"] == wall["S1"][0]


def test_crossing_and_distant_cables_are_not_bundled():
    cross = {"S1": ([(0.0, 100.0), (100.0, 100.0)], set()), "S2": ([(50.0, 50.0), (60.0, 150.0)], set())}
    assert routing.lane_bundles(cross, 6.0) == []
    res = routing.lanes(cross, [], {}, AREA, 6.0)
    assert res["S1"]["corners"] == cross["S1"][0] and res["S2"]["corners"] == cross["S2"][0] and res["S1"]["stacked"] == []
    far = {"S1": ([(0.0, 100.0), (100.0, 100.0)], set()), "S2": ([(0.0, 106.0), (100.0, 106.0)], set())}   # exactly one width apart
    assert routing.lane_bundles(far, 6.0) == []
    short = {"S1": ([(0.0, 100.0), (100.0, 100.0)], set()), "S2": ([(96.0, 100.0), (200.0, 100.0)], set())}   # 4 mm overlap < 6
    assert routing.lane_bundles(short, 6.0) == []


def test_a_cable_gets_one_lane_for_all_its_segments_in_a_bundle_and_ids_sort_naturally():
    # S10 runs along S2 twice (a 4 deg bend between its two segments): one lane, offsets stay equal; S2 < S10
    routes = {"S10": ([(10.0, 100.0), (60.0, 100.0), (110.0, 103.0)], set()), "S2": ([(10.0, 100.0), (110.0, 101.5)], set())}
    (bundle,) = routing.lane_bundles(routes, 6.0)
    assert bundle == [("S2", 0), ("S10", 0), ("S10", 1)]
    res = routing.lanes(routes, [], {}, AREA, 6.0)
    assert res["S2"]["stacked"] == [] and res["S10"]["stacked"] == []
    assert res["S10"]["corners"][1][1] - res["S2"]["corners"][1][1] == pytest.approx(6.0, abs=0.2)   # S2 sorts first (upper)


def test_other_plugs_may_not_be_touched_by_a_lane_but_own_plugs_may():
    # a plug rect 6 mm below the line (y 104..110, x 40..60): the original at y = 100 is 4 mm away (> radius 3); the
    # lane at +3 would be 1 mm away -> touches -> invalid, even the half lane (+1.5: 2.5 mm) touches
    routes = {"S1": ([(0.0, 100.0), (100.0, 100.0)], set()), "S2": ([(0.0, 100.0), (100.0, 100.0)], set())}
    plugs = {"x.in": [(40.0, 104.0, 60.0, 110.0)]}
    res = routing.lanes(routes, [], plugs, AREA, 6.0)    # the lane set shifts up, away from the plug
    assert res["S1"]["stacked"] == []
    assert all(routing.seg_rect_distance(p, q, plugs["x.in"][0]) > 3.0                # never within the radius
               for c in ("S1", "S2") for p, q in zip(res[c]["corners"], res[c]["corners"][1:]))
    own = {"S1": (routes["S1"][0], {"x.in"}), "S2": (routes["S2"][0], {"x.in"})}
    assert routing.lanes(own, [], plugs, AREA, 6.0)["S1"]["stacked"] == []


def test_route_project_lanes_only_fill_draw_path(monkeypatch):
    # two parallel cables A -> B and C -> D side by side in the open: same min_mm and path with and without lanes
    def build():
        ctx = plug_ctx({"type": "ra"})
        routing.route_project(ctx, {}, cable_types=TYPES)
        return {c["id"]: c for c in ctx["cable_list"] if c["kind"] == "signal"}
    laned = build()["S1"]
    monkeypatch.setattr(routing, "lanes", lambda routes, *a, **k: {cid: {"corners": list(pts), "stacked": [], "stacked_runs": []}
                                                                  for cid, (pts, _) in routes.items()})
    plain = build()["S1"]
    assert laned["min_mm"] == plain["min_mm"] and laned["path"] == plain["path"]
    assert plain["draw_path"] == plain["path"] and plain["stacked_with"] == []
    assert not any(k.startswith("_") for k in laned)


def test_route_project_moves_lanes_away_from_the_pedal_edge_they_hug():
    # A -> B -> C with S1 and S2 both passing over B's back edge (y = 60) at y = 56, 4 mm from B (radius 3): centred
    # lanes would put one 1 mm from B, so the lane set shifts away from B (one lane stays 3..4 mm from it)
    a, b, c = mm_item("i-a", "A", 20, 60, 50, 100), mm_item("i-b", "B", 120, 60, 50, 100), mm_item("i-c", "C", 220, 60, 50, 100)
    jd = {"a": [{"id": "out", "label": "Output", "function": "output", "x": 1.0, "y": 0.1, "facing": "right"}],
          "b": [{"id": "in", "label": "Input", "function": "input", "x": 1.0, "y": 0.9, "facing": "right"},
                {"id": "out", "label": "Output", "function": "output", "x": 0.0, "y": 0.1, "facing": "left"}],
          "c": [{"id": "in", "label": "Input", "function": "input", "x": 0.0, "y": 0.9, "facing": "left"}]}
    layout = {"board": mm_item("i-board", "Board", 0, 0, 300, 200, "pedalboard"), "placed": {"a": a, "b": b, "c": c},
              "obstacles": [a, b, c], "inst_item": {}, "jacks": jd, "outward_mm": 6.3}
    ctx = {"project": {"cables": {"type": "ra"}}, "chain": ["a", "b", "c"], "layout": layout, "errors": [], "warnings": [],
           "violations": [], "cables": {"power": []}}
    routing.route_project(ctx, {}, cable_types=TYPES)
    s1, s2 = (next(x for x in ctx["cable_list"] if x["id"] == i) for i in ("S1", "S2"))
    assert s1["status"] == s2["status"] == "routed"
    assert s1["stacked_with"] == s2["stacked_with"] == []
    assert s1["draw_path"] != s1["path"] or s2["draw_path"] != s2["path"]
    box_b = (120.0, 60.0, 170.0, 160.0)
    for s in (s1, s2):                                   # never closer to B than the centreline (capped at the radius)
        assert min(routing.seg_rect_distance(p, q, box_b) for p, q in zip(s["draw_path"], s["draw_path"][1:])) >= \
            min(3.0, min(routing.seg_rect_distance(p, q, box_b) for p, q in zip(s["path"], s["path"][1:]))) - 1e-6
    assert 'class="cable"' in svgdraw.render(ctx, {}) and 'class="stacked"' not in svgdraw.render(ctx, {})


def test_smoothing_never_cuts_through_a_pedal_a_plug_exit_lies_in():
    # the exit (8, 5) lies inside pedal R (0..10 x 0..10); the grid path leaves it to the right and turns down: the
    # shortcut from the exit to (12, 15) would cross R, so the first corner stays at (12, 5)
    r = (0.0, 0.0, 10.0, 10.0)
    out = routing.smooth([(8.0, 5.0), (12.0, 5.0), (12.0, 15.0), (12.0, 25.0)], [r], 1.5, {})
    assert out[1] == (12.0, 5.0)
    assert all(routing.seg_rect_distance(p, q, r) > 0 for p, q in zip(out[1:], out[2:]))


def test_a_lane_never_moves_into_a_pedal_the_centreline_touches():
    # both cables run along R's front edge (y = 10, distance 0): the centred lanes (+-3) would put one inside R,
    # so the lane set moves away from R
    r = (0.0, 0.0, 100.0, 10.0)
    routes = {"S1": ([(0.0, 10.0), (100.0, 10.0)], set()), "S2": ([(0.0, 10.0), (100.0, 10.0)], set())}
    res = routing.lanes(routes, [r], {}, AREA, 6.0)
    for c in ("S1", "S2"):
        assert all(routing.seg_rect_distance(p, q, r) > 0 for p, q in zip(res[c]["corners"][1:-2], res[c]["corners"][2:-1]))
