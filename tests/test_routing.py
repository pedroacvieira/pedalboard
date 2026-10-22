"""Grid routing (scripts/routing.py), on small hand-made grids. All lengths in mm."""
import math
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import routing  # noqa: E402

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
    paths, users, overflow = routing.route_all(g, nets, max_stack=2, iterations=20)
    assert all(paths.values())
    corridor = [c for c in users if 3 <= c[0] <= 8]
    assert max(len(users[c]) for c in corridor) <= 2 or overflow


def test_too_many_cables_through_a_one_cell_gap_report_overflow():
    g = free_grid(nx=12, ny=9)
    g.block_rect((30.0, 0.0, 36.0, 24.0))
    g.block_rect((30.0, 30.0, 36.0, 54.0))            # single free cell at (5, 4)
    nets = [(f"n{i}", (1, 4), (10, 4)) for i in range(3)]
    paths, users, overflow = routing.route_all(g, nets, max_stack=2, iterations=10)
    assert (5, 4) in overflow and len(users[(5, 4)]) == 3


def test_two_cables_fit_through_a_one_cell_gap_with_the_default_limit():
    g = free_grid(nx=12, ny=9)
    g.block_rect((30.0, 0.0, 36.0, 24.0))
    g.block_rect((30.0, 30.0, 36.0, 54.0))
    nets = [(f"n{i}", (1, 4), (10, 4)) for i in range(2)]
    paths, users, overflow = routing.route_all(g, nets, max_stack=2, iterations=10)
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
    # measured from 10 mm in front of each jack (half the 20 mm head): 2 x (8 + 6) mm to the exits, then about
    # 110 mm across and 32 mm down (octile ~ 123 mm, grid accuracy ~ a few mm)
    assert 28 + 123 - 4 <= c["min_mm"] <= 28 + 123 + 8
    assert ctx["violations"] == [] and ctx["errors"] == []
    fixed = plug_ctx({"type": "ra", "overrides": {"S1": {"exit_a": "left"}}})
    routing.route_project(fixed, {}, cable_types=TYPES)
    (f,) = [x for x in fixed["cable_list"] if x["kind"] == "signal"]
    assert f["exit_a"] == "left" and f["min_mm"] > c["min_mm"]


def test_straight_plug_type_per_cable_and_its_diameter():
    ctx = plug_ctx({"type": "ra", "overrides": {"S1": {"type": "st"}}})
    routing.route_project(ctx, {}, cable_types=TYPES)
    (c,) = [x for x in ctx["cable_list"] if x["kind"] == "signal"]
    assert c["type"] == "st" and (c["exit_a"], c["exit_b"]) == (None, None)
    assert c["path"][1] == (70.0 + 40 + 6, 80.0)            # head 40 + one 6 mm run (the project default type's diameter)


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
    routing.route_project(ctx, {}, cable_types={**TYPES, **DC})          # unknown -> the project default
    assert [x for x in ctx["cable_list"] if x["kind"] == "power"][0]["polarity"] == "center_negative"
