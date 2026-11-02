"""Pedal bodies (feat/pedal-body): the usable board area holds a pedal's BODY (enclosure), not its jacks. The body from the image's alpha
mask (outlines.body_from_alpha), its canvas rectangle (design.body_rect), the build warning (jacks.outside_usable), the layout model
(Model.body, feasible_one, repair_start, free_distance), and the routing area that lets an overhanging plug's cable start
(routing.plug_zones, build_grid `zones`, layout.in_area). Hand-computed on small synthetic cases; all lengths in mm."""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import design  # noqa: E402
import jacks  # noqa: E402
import layout  # noqa: E402
import outlines  # noqa: E402
import routing  # noqa: E402
from test_bounds import BACK_5, LINES, PX, outside  # noqa: E402
from test_check import PDATA, PEDALS, SUPPLIES, project  # noqa: E402
from test_layout import BOARD, JACKS, canvas, ped  # noqa: E402
from test_layout import PEDALS as LPEDALS, TYPES as LTYPES  # noqa: E402
from test_routing import TYPES, plug_ctx  # noqa: E402


# --- the body from the alpha mask -------------------------------------------------------------------
def mask(w, h, rects):
    """A 2D list of alpha values (255 inside the rects [(x0, y0, x1, y1)], pixel indices, inclusive)."""
    return [[255 if any(a <= x <= c and b <= y <= d for a, b, c, d in rects) else 0 for x in range(w)] for y in range(h)]


def test_the_median_ignores_a_jack_bump_and_a_screw():
    # 20 x 10 px; the enclosure x 2..17, y 1..8; a jack bump on each side (rows 4-5 reach x 0..1 and 18..19); a screw below it (column 10, row 9)
    body = [(2, 1, 17, 8)]
    bumps = [(0, 4, 1, 5), (18, 4, 19, 5)]
    screw = [(10, 9, 10, 9)]
    assert outlines.body_from_alpha(mask(20, 10, body)) == [0.1, 0.1, 0.9, 0.9]
    # first x per row (9 rows: 1..9): 2 2 2 0 0 2 2 2 10 -> median 2; last x: 17 17 17 19 19 17 17 17 10 -> 17; per column first y: 4 4 1 x 16 4 4 ->
    # median 1; last y: 5 5 8 (x 15) 9 (column 10) 5 5 -> median 8
    assert outlines.body_from_alpha(mask(20, 10, body + bumps + screw)) == [0.1, 0.1, 0.9, 0.9]


def test_the_body_of_a_blank_image_is_the_box_and_the_far_edge_is_the_pixels_far_edge():
    assert outlines.body_from_alpha(mask(10, 10, [])) == [0, 0, 1, 1]
    assert outlines.body_from_alpha(mask(10, 4, [(0, 0, 9, 3)])) == [0.0, 0.0, 1.0, 1.0]
    assert outlines.body_from_alpha(mask(10, 4, [(5, 1, 6, 2)])) == [0.5, 0.25, 0.7, 0.75]
    half = [[0, 255, 255, 255], [255, 255, 255, 0]]            # an even count: the median averages the two middle values
    assert outlines.body_from_alpha(half) == [0.125, 0.0, 0.875, 1.0]


def test_the_bodies_file_part_round_trips_sorted_and_malformed_entries_are_dropped(tmp_path):
    path = tmp_path / "outlines.json"
    assert outlines.read_file(path)["bodies"] == {}
    outlines.save({"a.png": [[0, 0, 1, 1]]}, path, bodies={"b.png": [0.1, 0.0, 0.9, 1.0], "a.png": [0.0, 0.0, 1.0, 1.0]})
    outlines.save({"c.png": [[0, 0, 1, 1]]}, path)                                    # keeps the bodies
    data = outlines.read_file(path)
    assert sorted(data["bodies"]) == ["a.png", "b.png"] and sorted(data["outlines"]) == ["a.png", "c.png"]
    lines = path.read_text().splitlines()
    assert lines[lines.index('  "bodies": {') + 1] == '    "a.png": [0.0, 0.0, 1.0, 1.0],'
    bad = {"ok.png": [0.1, 0, 0.9, 1], "flip.png": [0.5, 0, 0.2, 1], "short.png": [0, 0, 1], "str.png": "x", "text.png": ["a", 0, 1, 1],
           "out.png": [0, 0, 1.5, 1]}
    assert outlines.usable_bodies(bad) == {"ok.png": [0.1, 0, 0.9, 1]}
    assert outlines.usable_bodies({"bodies": bad}) == {"ok.png": [0.1, 0, 0.9, 1]} and outlines.usable_bodies(None) == {}


# --- design.body_rect --------------------------------------------------------------------------------
def item(rot, image="x.png"):
    return {"id": "i", "left_mm": 20.0, "top_mm": 10.0, "w_mm": 100.0, "h_mm": 50.0, "rot": rot, "image": image}


BODY = {"x.png": [0.2, 0.1, 0.9, 0.8]}


def test_body_rect_rotations_and_the_box_without_data():
    # the same corners as test_bounds.test_board_bounds_rotations: the 100 x 50 box at (20, 10), centre (70, 35)
    assert design.body_rect(item(0), BODY) == pytest.approx((40, 15, 110, 50))
    assert design.body_rect(item(90), BODY) == pytest.approx((55, 5, 90, 75))
    assert design.body_rect(item(270), BODY) == pytest.approx((50, -5, 85, 65))
    assert design.body_rect(item(180), BODY) == pytest.approx((30, 20, 100, 55))      # (u, v) -> (-u, -v)
    for rot in (0, 90, 270):
        assert design.body_rect(item(rot), {}) == design.footprint(item(rot))
        assert design.body_rect(item(rot), None) == design.footprint(item(rot))
        assert design.body_rect(item(rot, image="other.png"), BODY) == design.footprint(item(rot))
        assert design.body_rect(item(rot, image=None), BODY) == design.footprint(item(rot))


# --- the build warning -------------------------------------------------------------------------------
def checked(tmp_path, bodies, validation=None):
    ctx = project(tmp_path, [BOARD, ped("T A", 0, 9)], validation=validation, chain=("a",))
    (tmp_path / "board.json").write_text(json.dumps({"bounds": {"back": BACK_5}}))
    jacks.check(ctx, PEDALS, SUPPLIES, PDATA, defer=True, board_data={}, outlines={}, bodies=bodies)
    return ctx


def test_a_box_past_the_line_with_the_body_inside_is_not_reported(tmp_path):
    # "T A" is 50.8 x 101.6 with its top at 5.08 mm, the back line at 10.08 (5 mm below the top)
    assert outside(checked(tmp_path, {})) == ["layout: T A is outside the usable board area by 5.0 mm (back)"]   # no body data: the box
    inside = tmp_path / "in"
    inside.mkdir()
    ctx = checked(inside, {"x.png": [0.0, 0.06, 1.0, 1.0]})                  # the body starts 6.1 mm below the top: 1.1 mm inside the line
    assert outside(ctx) == [] and ctx["outside_usable"] == []
    assert ctx["layout"]["bodies"]["item-1"] == pytest.approx((0.0, 5.08 + 0.06 * 101.6, 50.8, 5.08 + 101.6), abs=0.02)


def test_a_body_past_the_line_is_reported_by_the_body(tmp_path):
    ctx = checked(tmp_path, {"x.png": [0.0, 0.03, 1.0, 1.0]})                # the body starts 3.05 mm below the top: 1.95 mm past the line
    assert outside(ctx) == ["layout: T A is outside the usable board area by 2.0 mm (back)"]
    strict = tmp_path / "strict"
    strict.mkdir()
    ctx = checked(strict, {"x.png": [0.0, 0.03, 1.0, 1.0]}, validation={"strict_bounds": True})
    assert outside(ctx, errors=True) == ["layout: T A is outside the usable board area by 2.0 mm (back)"] and not outside(ctx)


# --- the layout model --------------------------------------------------------------------------------
IMG_BODY = {"x.png": [0.1, 0.0, 0.9, 1.0]}    # 5.08 mm inset left and right of the 50.8 mm wide "T A" (2 x 2 in)


def with_bodies(specs, bodies, pins=(), chain=("a",)):
    proj = {"signal_chain": list(chain), "cables": {"type": "t"}, "jacks": {}, "layout": {"pins": list(pins)}}
    items = design.parse_canvas(canvas(BOARD, *specs))
    return layout.Model(proj, items, LPEDALS, {}, JACKS, {}, LTYPES, outlines={}, board_bounds=LINES, bodies=bodies)


def test_model_body_offsets_follow_the_rotation_and_feasibility_tests_the_body():
    m = with_bodies([ped("T A", 100, 40, w=2.0, h=2.0)], IMG_BODY)      # usable x 25.4..228.6, y 12.7..114.3
    assert m.body((100.0, 60.0, 0), 0) == pytest.approx((100 - 20.32, 60 - 25.4, 100 + 20.32, 60 + 25.4))
    assert m.body((100.0, 60.0, 90), 0) == pytest.approx((100 - 25.4, 60 - 20.32, 100 + 25.4, 60 + 20.32))
    asym = with_bodies([ped("T A", 100, 40, w=2.0, h=2.0)], {"x.png": [0.0, 0.0, 0.8, 1.0]})   # the right side inset: not symmetric
    for rot in (0, 90, 270):
        moved = design.move(asym.mitem["a"], 100.0, 60.0, rot, snap=False)
        assert asym.body((100.0, 60.0, rot), 0) == pytest.approx(design.body_rect(moved, asym.bodies))
    assert asym.body((100.0, 60.0, 0), 0) == pytest.approx((74.6, 34.6, 74.6 + 40.64, 85.4))
    # the box reaches 0.7 mm past the left line at x = 46 - 25.4 + ... : box left 20.6 < 25.4, body left 25.68 >= 25.4: feasible by its body
    assert m.feasible_one([(46.0, 60.0, 0)], 0) and not m.feasible_one([(45.0, 60.0, 0)], 0)            # body left 24.68
    plain = with_bodies([ped("T A", 100, 40, w=2.0, h=2.0)], {})
    assert not plain.feasible_one([(46.0, 60.0, 0)], 0) and plain.feasible_one([(51.0, 60.0, 0)], 0)    # without a body: the box (left 25.6)
    # the other items keep the box: two pedals 5 mm apart by their bodies still overlap by the boxes
    two = with_bodies([ped("T A", 100, 40, w=2.0, h=2.0), ped("T B", 100, 40, w=2.0, h=2.0)], IMG_BODY, chain=("a", "b"))
    assert not two.feasible([(100.0, 60.0, 0), (140.0, 60.0, 0)])           # boxes 50.8 wide, centres 40 apart: overlap 10.8 mm


def test_free_distance_stops_at_the_body_not_the_box():
    m = with_bodies([ped("T A", 100, 40, w=2.0, h=2.0)], IMG_BODY)
    st = [(60.0, 60.0, 0)]
    assert layout.free_distance(m, st, 0, (-1, 0)) == pytest.approx(60 - 20.32 - 25.4)        # the body, not the box (34.6 - 25.4)
    assert layout.free_distance(m, st, 0, (0, -1)) == pytest.approx(60 - 25.4 - 12.7)         # y: the body is the whole box
    assert layout.free_distance(m, st, 0, (1, 0)) == pytest.approx(228.6 - 60 - 20.32)


def test_a_pedal_whose_box_is_past_the_line_but_whose_body_is_inside_is_not_moved():
    m = with_bodies([ped("T A", 37, 30, w=2.0, h=2.0)], IMG_BODY)       # box left 20.9 (4.5 mm past the line), body left 25.97
    m.max_move = 40.0
    assert m.footprint(m.owner[0], 0)[0] < 25.4 <= m.body(m.owner[0], 0)[0]
    assert layout.repair_start(m, m.owner) == list(m.owner)


def test_a_pedal_whose_body_is_past_the_line_is_pushed_the_least_distance_by_the_body():
    m = with_bodies([ped("T A", 30, 30, w=2.0, h=2.0)], IMG_BODY)       # box left 16.9, body left 21.99: 3.4 mm past the line
    m.max_move = 40.0
    cx, cy, _ = m.owner[0]
    start = layout.repair_start(m, m.owner)
    assert m.body(m.owner[0], 0)[0] == pytest.approx(25.4 - 3.4, abs=0.05)
    assert 3.4 - 1e-6 <= start[0][0] - cx <= 3.4 + PX and abs(start[0][1] - cy) <= PX + 1e-6     # forward 3.4 mm, straight (whole px)
    assert m.body(start[0], 0)[0] >= 25.4 - 1e-6 and m.feasible_one(start, 0)
    plain = with_bodies([ped("T A", 30, 30, w=2.0, h=2.0)], {})          # the box: 8.5 mm
    moved = layout.repair_start(plain, plain.owner)
    assert 8.5 - 1e-6 <= moved[0][0] - plain.owner[0][0] <= 8.5 + PX


# --- the routing area --------------------------------------------------------------------------------
def test_in_area_counts_the_own_footprint_only_for_an_overhanging_jack_and_never_in_front():
    area = (-6.0, -6.0, 106.0, 80.0)                      # the grown usable area; the usable area itself is (0, 0, 100, 80)
    usable = (0.0, 0.0, 100.0, 80.0)
    rects = [("head", (-20.0, 10.0, 0.0, 30.0)), ("cable", (-12.0, 30.0, -8.0, 36.0))]
    inner = {"exit": (-10.0, 20.0), "rects": rects, "jack": (0.0, 20.0)}                    # the jack point (0, 20) is on the usable edge: not overhanging
    over = {**inner, "jack": (-1.0, 20.0)}                                                    # 1 mm past it: overhanging
    ok = lambda o, st=(0.0, 0.0), r=2.0: layout.in_area(area, o, st, r, usable)
    assert ok({"exit": (50.0, 20.0), "rects": [], "jack": None})                              # inside the area
    assert not ok(inner)                       # an INTERIOR jack: its exit outside the grown area stays outside, whatever its footprint
    assert ok(over)                            # an overhanging jack: the exit on its own head counts as inside
    assert not ok({**over, "rects": []}) and not ok({**over, "jack": None})
    assert ok({**over, "exit": (-21.5, 20.0)}) and not ok({**over, "exit": (-23.0, 20.0)})   # within the radius of the head
    assert ok({**over, "exit": (-23.0, 20.0), "diam": 8.0})                                    # a DC plug: its own cable radius (4)
    front = {"exit": (50.0, 85.0), "rects": [("cable", (45.0, 80.0, 55.0, 90.0))], "jack": (50.0, 82.0)}
    assert not ok(front)                                                                       # the front: never
    assert not ok(over, st=(2.0, 0.0))                                                          # the pedal moved 2 mm in: its jack is inside, no zone


CFG = {**routing.DEFAULTS, "grid_mm": 2.0, "edge_margin_mm": 4.0, "diameter_mm": 2.0}
BRD = (0.0, 0.0, 60.0, 30.0)


def test_zone_cells_are_no_walls_and_the_extent_grows_by_whole_cells():
    plain = routing.build_grid(BRD, [], 30.0, CFG)
    same = routing.build_grid(BRD, [], 30.0, CFG, [(10.0, 10.0, 20.0, 20.0)])      # a zone inside the area: nothing changes
    assert (same.x0, same.y0, same.nx, same.ny) == (plain.x0, plain.y0, plain.nx, plain.ny) and same.blocked == plain.blocked
    zone = (-12.0, 12.0, -2.0, 16.0)                                                # a plug past the board edge + margin (x -4)
    g = routing.build_grid(BRD, [], 30.0, CFG, [zone])
    assert g.x0 < plain.x0 and (plain.x0 - g.x0) % g.cell == pytest.approx(0) and g.y0 == plain.y0 and g.ny == plain.ny   # grew left by whole cells
    assert g.cell_of(-9, 13) not in g.blocked                                       # a zone cell beyond the board + margin: open
    assert g.cell_of(-9, 25) in g.blocked                                           # the other added cells are walls
    assert g.cell_of(-3, 25) not in g.blocked and g.cell_of(20, 10) not in g.blocked   # the board + margin: open as before
    wall = routing.build_grid(BRD, [(-12.0, 10.0, -6.0, 20.0)], 30.0, CFG, [zone])
    assert wall.cell_of(-9, 13) in wall.blocked                                     # a pedal over a zone cell still blocks


def overhang_ctx():
    """plug_ctx with A moved to x -10..40 (past the board's left edge: its body is inside, its box overhangs) and its output at the top
    left corner (-10, 60) facing left: the jack lies outside the usable area (the board), the plug's head (x -30..-10), its cable run
    and the exit (-20, 46) lie beyond the board + margin (x -6)."""
    ctx = plug_ctx({"type": "ra"})
    lay = ctx["layout"]
    lay["placed"]["a"]["left_mm"] = -10.0
    lay["jacks"]["a"][0].update(x=0.0, y=0.0, facing="left")
    lay["usable"] = (0.0, 0.0, 300.0, 200.0)
    return ctx


def test_an_overhanging_side_jack_still_gets_its_cable_routed():
    ctx = overhang_ctx()
    routing.route_project(ctx, {}, cable_types=TYPES)
    (c,) = [x for x in ctx["cable_list"] if x["kind"] == "signal"]
    assert c["status"] == "routed" and c["path"][0] == (-10.0, 60.0)
    assert ctx["errors"] == [] and not [w for w in ctx["warnings"] if w.startswith("routing:")]
    assert min(p[0] for p in c["path"]) < -10.0 - 5                                         # the cable really leaves over the overhang
    zones = ctx["routing"]["plug_zones"]
    assert (-20.0, 46.0, -20.0, 46.0) in zones and (-30.0, 52.0, -10.0, 68.0) in zones     # the exit point and the head


def test_without_the_plug_zones_the_same_cable_has_no_place_to_start(monkeypatch):
    monkeypatch.setattr(routing, "plug_zones", lambda *a, **k: [])
    ctx = overhang_ctx()
    routing.route_project(ctx, {}, cable_types=TYPES)
    (c,) = [x for x in ctx["cable_list"] if x["kind"] == "signal"]
    assert c["status"].startswith("unroutable")
    assert any(w.startswith("routing: S1") for w in ctx["warnings"])


def test_plug_zones_cover_every_option_of_an_overhanging_jack_and_nothing_else():
    ctx = overhang_ctx()
    routing.route_project(ctx, {}, cable_types=TYPES)
    zones = [tuple(z) for z in ctx["routing"]["plug_zones"]]
    assert (-20.0, 46.0, -20.0, 46.0) in zones and (-20.0, 74.0, -20.0, 74.0) in zones         # both exit sides of A's plug
    assert not [z for z in zones if z[0] > 100]                                                  # B's plug (x ~190, inside the area): none


def test_an_interior_plug_whose_exit_is_beyond_the_area_is_still_unroutable_and_has_no_zone():
    ctx = plug_ctx({"type": "ra"})
    lay = ctx["layout"]
    lay["placed"]["a"]["left_mm"] = 250.0                          # A's output at (300, 80) facing right: inside the board + margin (306)
    routing.route_project(ctx, {}, cable_types=TYPES)               # both exits (x 310) lie beyond the margin
    (c,) = [x for x in ctx["cable_list"] if x["kind"] == "signal"]
    assert ctx["routing"]["plug_zones"] == []                                                # nothing overhangs: no zone, the plain area test
    assert c["status"].startswith("unroutable") and "outside the routing area" in c["status"]
    assert any(w.startswith("routing: S1") and "outside the routing area" in w for w in ctx["warnings"])


def test_without_zones_the_grid_is_the_plain_one_even_with_a_fractional_extent():
    board = (0.0, 0.0, 61.0, 31.0)                                  # the extent 69 x 39 mm is no whole number of 2 mm cells (35 x 20)
    pedals = [(20.0, 10.0, 30.0, 20.0)]
    ref = routing.Grid(-4.0, -4.0, 65.0, 31.0, 2.0)
    for r in pedals:
        ref.block_rect(r, grow=routing.grow_of(CFG))
    for zones in ((), [(10.0, 10.0, 20.0, 20.0)]):
        g = routing.build_grid(board, pedals, 31.0, CFG, zones)
        assert (g.x0, g.y0, g.nx, g.ny) == (-4.0, -4.0, 35, 18) == (ref.x0, ref.y0, ref.nx, ref.ny)
        assert g.blocked == ref.blocked and g.body == ref.body                                  # no wall from rounding
    assert routing.area_rect(ref, board, 31.0, CFG) == (-4.0, -4.0, 66.0, 31.0)


def test_the_area_rect_ignores_the_cells_the_zones_added():
    g = routing.build_grid(BRD, [], 30.0, CFG, [(-12.0, 12.0, -2.0, 16.0)])
    assert g.x0 < -4.0
    assert routing.area_rect(g, BRD, 30.0, CFG) == (-4.0, -4.0, 64.0, 30.0)


def test_a_caller_with_its_own_outlines_and_no_bodies_gets_no_bodies():
    m = with_bodies([ped("T A", 100, 40, w=2.0, h=2.0)], None)           # outlines={} and bodies=None: no catalog bodies (the boxes)
    assert m.bodies == {} and m.body((100.0, 60.0, 0), 0) == pytest.approx(m.footprint((100.0, 60.0, 0), 0))
    items = design.parse_canvas(canvas(BOARD, ped("T A", 100, 40, w=2.0, h=2.0)))
    lay = jacks.layout_from_items(items, ["a"], [], LPEDALS, {}, {}, [], [], outlines={})
    assert lay["bodies"]["item-1"] == design.footprint(lay["placed"]["a"])


def test_a_missing_body_of_an_image_with_an_outline_is_a_warning_not_a_failure(monkeypatch, capsys):
    def fail(name):
        raise RuntimeError("no network")
    saved = {}
    monkeypatch.setattr(outlines, "fetch_image", fail)
    monkeypatch.setattr(outlines, "database", lambda name: {})
    monkeypatch.setattr(outlines, "wanted", lambda *a: {"a.png": (10.0, 10.0)})
    monkeypatch.setattr(outlines, "save", lambda *a, **k: saved.update(k))
    monkeypatch.setattr(sys, "argv", ["outlines.py"])
    monkeypatch.setattr(outlines, "read_file", lambda: {"outlines": {"a.png": [[0, 0, 1, 1]]}, "bodies": {}})
    assert outlines.main() == 0 and "WARNING no body" in capsys.readouterr().out and not saved       # the outline exists: a warning
    monkeypatch.setattr(outlines, "read_file", lambda: {"outlines": {}, "bodies": {}})
    assert outlines.main() == 1 and "FAILED" in capsys.readouterr().out                             # no outline either: a failure
