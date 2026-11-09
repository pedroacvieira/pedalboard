"""Composed boards (`feat/board-pieces`): a layout with several pedalboard items, summed and evaluated as ONE board. The geometry of a union
of rectangles (design.inside_union / outside_union / slide_room), board.json `pieces` (boards.load_pieces), `jacks.layout_from_items`,
the bounds test (jacks.outside_usable and the layout model agree), the top and under routing grids, the edge links, a routed cable across
a joint and the drawing. Hand-computed on small synthetic boards; all lengths in mm."""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import boards as boards_mod  # noqa: E402
import design  # noqa: E402
import jacks  # noqa: E402
import layout  # noqa: E402
import routing  # noqa: E402
import svgdraw  # noqa: E402
from test_check import canvas  # noqa: E402
from test_layout import BOARD, JACKS, PEDALS, TYPES, ped  # noqa: E402
from test_routing import TYPES as RA_TYPES, mm_item, plug_ctx  # noqa: E402

# an L: A on top (0..100 x 0..50), B under its left half (0..50 x 50..100); the notch is x 50..100 x y 50..100
A = (0.0, 0.0, 100.0, 50.0)
B = (0.0, 50.0, 50.0, 100.0)
L = [A, B]
# two abutting pieces: P (0..100 x 0..50) and Q (100..200 x 0..50)
P, Q = (0.0, 0.0, 100.0, 50.0), (100.0, 0.0, 200.0, 50.0)
ROW = [P, Q]


# --- the geometry --------------------------------------------------------------------------------------
def test_a_rect_across_the_joint_of_two_abutting_pieces_is_inside():
    assert design.inside_union((90.0, 10.0, 130.0, 40.0), ROW)
    assert not design.inside_union((90.0, 10.0, 130.0, 60.0), ROW)           # 10 mm past the front
    assert not design.inside_union((-1.0, 10.0, 130.0, 40.0), ROW)           # 1 mm past the left
    assert design.inside_union((90.0, 10.0, 130.0, 40.0), [P, (100.2, 0.0, 200.0, 50.0)], tol=0.2)   # a hair of a seam does not count


def test_a_rect_in_the_notch_of_an_l_is_outside_by_the_least_shift():
    assert design.inside_union((10.0, 10.0, 40.0, 90.0), L)                  # down the left leg across the joint
    assert design.inside_union((60.0, 10.0, 90.0, 40.0), L)                  # in A
    body = (60.0, 60.0, 90.0, 90.0)                                          # wholly in the notch
    assert not design.inside_union(body, L)
    # left 40 (its right edge to B's right at 50) or up 40 (its bottom edge to A's front at 50): a tie, "right" before "front"
    assert design.outside_union(body, L) == pytest.approx(("right", 40.0))
    half = (45.0, 40.0, 70.0, 60.0)                                          # sticks 20 mm into the notch at its corner
    assert design.outside_union(half, L) == pytest.approx(("front", 10.0))   # up 10 puts it back into A (left 20 would too)
    assert design.outside_union((10.0, 10.0, 40.0, 40.0), L) is None


def test_outside_union_across_a_joint_and_with_one_rect_is_todays_measure():
    # the body across the P / Q joint and 10 mm past the front: the shift is 10 mm, side "front" (not "left" of Q)
    assert design.outside_union((90.0, 10.0, 130.0, 60.0), ROW) == pytest.approx(("front", 10.0))
    assert design.outside_union((90.0, -7.0, 130.0, 40.0), ROW) == pytest.approx(("back", 7.0))
    assert design.outside_union((190.0, 10.0, 215.0, 40.0), ROW) == pytest.approx(("right", 15.0))
    # one rect: the worst of the four sides (as the single-board test always did), ties left, right, back, front
    assert design.outside_union((-3.0, -5.0, 40.0, 40.0), [A]) == pytest.approx(("back", 5.0))
    assert design.outside_union((-5.0, -5.0, 40.0, 40.0), [A]) == pytest.approx(("left", 5.0))
    assert design.outside_union((10.0, 10.0, 40.0, 40.0), [A]) is None


def test_a_rect_that_sticks_out_on_two_axes_is_measured_against_the_nearest_piece():
    assert design.outside_union((-3.0, -5.0, 40.0, 40.0), ROW) == pytest.approx(("back", 5.0))


def test_slide_room_stops_at_the_edge_of_the_union():
    r = (10.0, 10.0, 40.0, 40.0)
    assert design.slide_room(r, ROW, (1, 0)) == pytest.approx(200.0 - 40.0)            # across the joint to Q's right edge
    assert design.slide_room(r, ROW, (-1, 0)) == pytest.approx(10.0)
    assert design.slide_room(r, ROW, (0, 1)) == pytest.approx(10.0)
    assert design.slide_room(r, ROW, (0, -1)) == pytest.approx(10.0)
    assert design.slide_room((10.0, 10.0, 40.0, 40.0), L, (0, 1)) == pytest.approx(60.0)     # down the left leg: B's front at 100
    assert design.slide_room((60.0, 10.0, 90.0, 40.0), L, (0, 1)) == pytest.approx(10.0)     # A's front at 50 (the notch below)
    assert design.slide_room((10.0, 10.0, 40.0, 40.0), L, (1, 0)) == pytest.approx(60.0)     # A's right edge at 100
    assert design.slide_room((60.0, 60.0, 90.0, 90.0), L, (1, 0)) == 0.0                     # not inside to begin with


def test_bounding_rect_and_the_layout_helpers():
    assert design.bounding_rect(L) == (0.0, 0.0, 100.0, 100.0) and design.bounding_rect([]) is None
    one = {"board": mm_item("b", "Board", 5, 6, 10, 20, "pedalboard")}
    assert design.layout_board_rects(one) == [(5, 6, 15, 26)] and design.layout_board_rect(one) == (5, 6, 15, 26)
    assert design.layout_board_rects({"board_rects": ROW, "board": object()}) == ROW and design.layout_board_rects({}) == []


# --- board.json `pieces` ---------------------------------------------------------------------------------
def test_pieces_are_read_per_image_and_the_top_level_stays_the_first_piece(tmp_path):
    hole = {"type": "hole", "x0": 0.1, "y0": 0.1, "x1": 0.2, "y1": 0.2}
    (tmp_path / "board.json").write_text(json.dumps({
        "boxes": [hole], "bounds": {"left": 0.1},
        "pieces": {"q.png": {"boxes": [{"type": "edge", "side": "back", "from": 0.0, "to": 0.5}], "bounds": {"right": 0.8}},
                   "r.png": {}}}))
    warnings = []
    assert boards_mod.load_edits(tmp_path, warnings) == [hole] and boards_mod.load_bounds(tmp_path)["left"] == 0.1
    pieces = boards_mod.load_pieces(tmp_path, warnings)
    assert warnings == []
    assert pieces["q.png"]["boxes"] == [{"type": "edge", "side": "back", "from": 0.0, "to": 0.5}]
    assert pieces["q.png"]["bounds"] == {"back": 0.0, "front": 1.0, "left": 0.0, "right": 0.8}
    assert pieces["r.png"] == {"boxes": [], "bounds": dict(boards_mod.BOUNDS_EDGE)}


def test_pieces_with_bad_values_warn_and_never_crash(tmp_path):
    (tmp_path / "board.json").write_text(json.dumps({"pieces": {
        "q.png": {"boxes": [{"type": "hole", "x0": 0.5, "y0": 0.1, "x1": 0.2, "y1": 0.2}], "bounds": {"back": 0.9, "front": 0.1}},
        "r.png": 3}}))
    warnings = []
    pieces = boards_mod.load_pieces(tmp_path, warnings)
    assert pieces == {"q.png": {"boxes": [], "bounds": dict(boards_mod.BOUNDS_EDGE)}}
    assert len(warnings) == 3 and any("box 0 ignored" in w for w in warnings) and any("bounds ignored" in w for w in warnings)
    assert any("pieces.r.png is not an object" in w for w in warnings)
    (tmp_path / "board.json").write_text(json.dumps({"pieces": [1]}))
    assert boards_mod.load_pieces(tmp_path, []) == {}
    assert boards_mod.load_pieces(tmp_path / "none") == {} and boards_mod.load_pieces(None) == {}
    assert boards_mod.unknown_pieces({"q.png": {}, "z.png": {}}, ["q.png"]) == [
        "board.json: pieces.z.png is not a pedalboard image of the layout (its pieces: q.png), ignored"]


# --- jacks.layout_from_items ------------------------------------------------------------------------------
def piece(iid, image, left, top, w, h):
    return {**mm_item(iid, "Board", left, top, w, h, "pedalboard"), "image": image}


def lay_of(items, **kw):
    return jacks.layout_from_items(items, [], [], {}, {}, {}, kw.pop("warnings", []), [], outlines={}, bodies={}, **kw)


def test_the_pieces_are_summed_in_one_layout():
    items = [piece("p1", "a.png", 0, 0, 100, 50), piece("p2", "b.png", 0, 50, 50, 50)]
    data = {"a.png": {"holes": [[0.1, 0.2, 0.3, 0.4]], "hole_transit_mm": 12.0},
            "b.png": {"holes": [[0.5, 0.5, 1.0, 1.0]], "hole_transit_mm": 99.0, "edge_transit_mm": 30.0}}
    pieces = {"b.png": {"boxes": [{"type": "edge", "side": "front", "from": 0.0, "to": 1.0}], "bounds": {"right": 0.8, "back": 0.2}}}
    lay = lay_of(items, board_data=data, board_edits=[{"type": "edge", "side": "back", "from": 0.0, "to": 0.5}],
                 board_bounds={"left": 0.1, "right": 1.0, "back": 0.0, "front": 1.0}, board_pieces=pieces)
    assert lay["board"] is items[0] and lay["pieces"] == items
    assert lay["board_rects"] == [A, B] and lay["board_rect"] == (0.0, 0.0, 100.0, 100.0)
    # the first piece: left bound 0.1 -> x 10; the second: right bound 0.8 -> x 40, back bound 0.2 -> y 60
    assert lay["usable_rects"] == pytest.approx([(10.0, 0.0, 100.0, 50.0), (0.0, 60.0, 40.0, 100.0)])
    assert lay["usable"] == pytest.approx((0.0, 0.0, 100.0, 100.0))
    assert lay["holes"] == pytest.approx([(10.0, 10.0, 30.0, 20.0), (25.0, 75.0, 50.0, 100.0)])     # both pieces' holes, in layout order
    assert lay["edge_segments"] == [((0.0, 0.0), (50.0, 0.0), "back"), ((0.0, 100.0), (50.0, 100.0), "front")]
    assert lay["hole_transit_mm"] == 12.0 and lay["edge_transit_mm"] == 30.0       # the first piece's entry that has one
    assert design.has_bounds(lay)


def test_one_piece_is_what_it_always_was():
    items = [piece("p1", "a.png", 20, 10, 100, 50)]
    lay = lay_of(items, board_data={"a.png": {"holes": [[0.1, 0.2, 0.3, 0.4]], "hole_transit_mm": 12.0}}, board_bounds={"back": 0.5})
    assert lay["board_rects"] == [(20.0, 10.0, 120.0, 60.0)] == [lay["board_rect"]] and lay["usable_rects"] == [lay["usable"]]
    assert lay["usable"] == pytest.approx((20.0, 35.0, 120.0, 60.0)) and lay["hole_transit_mm"] == 12.0 and "edge_transit_mm" in lay
    none = lay_of([], board_data={})
    assert none["board"] is None and none["pieces"] == [] and none["board_rect"] is None and none["usable"] is None and not design.has_bounds(none)


def test_a_piece_edit_for_an_image_that_is_no_piece_is_a_warning():
    warnings = []
    lay_of([piece("p1", "a.png", 0, 0, 100, 50)], board_data={}, board_pieces={"zz.png": {"boxes": [], "bounds": {}}}, warnings=warnings)
    assert warnings == ["board.json: pieces.zz.png is not a pedalboard image of the layout (its pieces: a.png), ignored"]


def test_has_bounds_is_true_when_any_pieces_usable_rect_differs():
    base = {"board": object(), "board_rects": ROW}
    assert not design.has_bounds({**base, "usable_rects": ROW, "usable": design.bounding_rect(ROW)})
    assert design.has_bounds({**base, "usable_rects": [P, (110.0, 0.0, 200.0, 50.0)], "usable": (0.0, 0.0, 200.0, 50.0)})


# --- the bounds test: jacks.outside_usable and the layout model --------------------------------------------
def l_items():
    """The test_layout board (254 x 127 mm at 0, 0) as the top piece plus a 127 x 127 piece under its left half: an L whose notch is
    x 127..254 x y 127..254."""
    items = design.parse_canvas(canvas(BOARD, ped("T A", 100, 40, w=2.0, h=2.0)))
    second = {**next(i for i in items if i["kind"] == "pedalboard"), "id": "item-piece-2", "image": "b.png", "w_mm": 127.0, "h_mm": 127.0,
              "left_mm": 0.0, "top_mm": 127.0}
    return items + [second]


def l_model(pieces=None):
    proj = {"signal_chain": ["a"], "cables": {"type": "t"}, "jacks": {}}
    return layout.Model(proj, l_items(), PEDALS, {}, JACKS, {}, TYPES, outlines={}, board_data={}, board_pieces=pieces)


def test_a_body_across_the_joint_is_inside_and_one_in_the_notch_is_outside():
    m = l_model()
    assert m.board == (0.0, 0.0, 254.0, 254.0) and len(m.usable_rects) == 2
    # the 50.8 x 50.8 pedal "T A" (a body = its box without body data)
    across = [(60.0, 127.0, 0)]            # x 34.6..85.4, y 101.6..152.4: across the joint at y = 127, inside the left half of the L
    notch = [(200.0, 190.0, 0)]            # x 174.6..225.4, y 164.6..215.4: wholly in the notch
    corner = [(110.0, 120.0, 0)]           # x 84.6..135.4, y 94.6..145.4: 8.4 mm into the notch (right of the 127 mm piece)
    assert m.feasible_one(across, 0) and not m.feasible_one(notch, 0) and not m.feasible_one(corner, 0)
    assert m.inside_usable(m.body(across[0], 0)) and not m.inside_usable(m.body(corner[0], 0))
    assert m.feasible_one([(60.0, 200.0, 0)], 0) and not m.feasible_one([(60.0, 235.0, 0)], 0)       # the left leg ends at y 254
    # sliding: down the left leg across the joint to its front, right along the top piece
    assert layout.free_distance(m, across, 0, (0, 1)) == pytest.approx(254.0 - 152.4)
    assert layout.free_distance(m, across, 0, (1, 0)) == pytest.approx(127.0 - 85.4)               # the lower piece ends at x 127
    assert layout.free_distance(m, [(60.0, 50.0, 0)], 0, (1, 0)) == pytest.approx(254.0 - 85.4)    # in the top piece: to its right edge
    m.cfg["board_margin_mm"] = 2.0
    assert layout.free_distance(m, across, 0, (0, 1)) == pytest.approx(254.0 - 152.4 - 2.0)
    assert not m.feasible_one([(26.0, 127.0, 0)], 0) and m.feasible_one([(28.0, 127.0, 0)], 0)   # left edge 0.6 / 2.6 mm vs the margin 2


@pytest.mark.parametrize("centre", [(60.0, 127.0), (200.0, 190.0), (110.0, 120.0), (60.0, 235.0), (60.0, 50.0), (230.0, 100.0), (240.0, 40.0)])
def test_the_layout_models_feasibility_agrees_with_the_builds_bounds_test(centre):
    m = l_model()
    m.cfg["board_margin_mm"] = 0.0
    state = [(*centre, 0)]
    items = m.items_for(state)
    lay = jacks.layout_from_items(items, ["a"], [], PEDALS, {}, {}, [], [], outlines={}, board_data={}, bodies={})
    inside = not jacks.outside_usable(lay)
    assert m.inside_usable(m.body(state[0], 0)) == inside


def test_outside_usable_reports_the_least_shift_and_its_side():
    m = l_model()
    lay = jacks.layout_from_items(m.items_for([(110.0, 120.0, 0)], snap=False), ["a"], [], PEDALS, {}, {}, [], [], outlines={}, board_data={}, bodies={})
    (it, side, mm), = jacks.outside_usable(lay)
    # the box x 84.6..135.4, y 94.6..145.4: 8.4 mm over the lower piece's right edge (left 8.4 fixes it); up 18.4 would put it in the top piece
    assert (it["title"], side, mm) == ("T A", "right", pytest.approx(8.4))


def test_the_pieces_bounds_are_the_models_union():
    m = l_model({"b.png": {"boxes": [], "bounds": {"back": 0.5}}})           # the lower piece's back line at y 127 + 63.5
    assert m.usable_rects[1] == pytest.approx((0.0, 190.5, 127.0, 254.0))
    assert m.feasible_one([(60.0, 220.0, 0)], 0) and m.feasible_one([(60.0, 60.0, 0)], 0)
    assert not m.feasible_one([(60.0, 190.0, 0)], 0)                         # body y 164.6..215.4 spans the unusable strip 127..190.5 of the left leg
    # the box y 164.6..215.4 has to move 25.9 mm to the front to start at the lower piece's back line (190.5); to the back it would be 88.4
    lay = jacks.layout_from_items(m.items_for([(60.0, 190.0, 0)], snap=False), ["a"], [], PEDALS, {}, {}, [], [], outlines={}, bodies={}, board_data={},
                                  board_pieces={"b.png": {"boxes": [], "bounds": {"back": 0.5}}})
    (it, side, mm), = jacks.outside_usable(lay)
    assert (side, mm) == ("back", pytest.approx(25.9))


# --- routing: the top grid, the under layer, the edge links ----------------------------------------------------
CFG = {**routing.DEFAULTS, "grid_mm": 2.0, "edge_margin_mm": 4.0, "diameter_mm": 2.0}
BBOX = (0.0, 0.0, 300.0, 200.0)
LPIECES = [(0.0, 0.0, 300.0, 100.0), (0.0, 100.0, 150.0, 200.0)]      # an L: the notch is x 150..300 x y 100..200


def test_the_top_grid_has_no_free_cell_beyond_the_margin_of_the_union():
    g = routing.build_grid(BBOX, [], 200.0, CFG, pieces=LPIECES)
    assert g.cell_of(250.0, 150.0) in g.blocked                          # the notch, far from both pieces
    assert g.cell_of(153.0, 150.0) not in g.blocked                      # 3 mm right of the lower piece: inside the margin
    assert g.cell_of(157.0, 150.0) in g.blocked                          # 7 mm: beyond it
    assert g.cell_of(200.0, 102.0) not in g.blocked and g.cell_of(200.0, 107.0) in g.blocked   # 2 mm below the top piece / 7 mm
    for i in range(g.nx):
        for j in range(g.ny):
            if (i, j) not in g.blocked:
                x, y = g.centre((i, j))
                assert any(r[0] - 4.0 <= x <= r[2] + 4.0 and r[1] - 4.0 <= y <= r[3] + 4.0 for r in LPIECES)
    plain = routing.build_grid(BBOX, [], 200.0, CFG)                      # one piece / none: the bounding box, as before
    assert routing.build_grid(BBOX, [], 200.0, CFG, pieces=[BBOX]).blocked == plain.blocked and g.nx == plain.nx and g.ny == plain.ny
    assert g.blocked > plain.blocked


def test_a_plug_zone_in_the_notch_stays_open():
    zone = (200.0, 120.0, 220.0, 130.0)
    g = routing.build_grid(BBOX, [], 200.0, CFG, zones=[zone], pieces=LPIECES)
    assert g.cell_of(210.0, 125.0) not in g.blocked and g.cell_of(250.0, 150.0) in g.blocked


def test_the_under_layer_is_blocked_outside_every_piece():
    g = routing.build_grid(BBOX, [], 200.0, CFG, pieces=LPIECES)
    ug = routing.under_grid(g, BBOX, [], CFG, LPIECES)
    assert ug.cell_of(250.0, 150.0) in ug.blocked and ug.cell_of(250.0, 50.0) not in ug.blocked
    assert ug.cell_of(100.0, 150.0) not in ug.blocked and ug.cell_of(149.0, 199.0) not in ug.blocked
    assert routing.under_grid(g, BBOX, [], CFG).blocked < ug.blocked      # (without pieces the whole bounding box is the layer)


def test_a_joint_is_no_edge_but_the_pieces_borders_are():
    ROW2 = [(0.0, 0.0, 100.0, 50.0), (100.0, 0.0, 200.0, 50.0)]
    bbox = (0.0, 0.0, 200.0, 50.0)
    g = routing.build_grid(bbox, [], 50.0, CFG, pieces=ROW2)
    ug = routing.under_grid(g, bbox, [], CFG, ROW2)
    back = routing.edge_links(g, ug, bbox, [((0.0, 0.0), (200.0, 0.0), "back")], 30.0, pieces=ROW2)
    plain = routing.edge_links(g, routing.under_grid(g, bbox, [], CFG), bbox, [((0.0, 0.0), (200.0, 0.0), "back")], 30.0)
    assert len(back) == len(plain) == 100 and sorted(back) == sorted(plain)
    assert routing.edge_links(g, ug, bbox, [((100.0, 0.0), (100.0, 50.0), "left")], 30.0, pieces=ROW2) == []   # the joint
    left = routing.edge_links(g, ug, bbox, [((0.0, 0.0), (0.0, 50.0), "left")], 30.0, pieces=ROW2)
    assert len(left) == 25 and all(ug.centre(u)[0] < 2.0 for u, *_ in left)
    # an L: the right edge of the lower piece (x 150, y 100..200) is a border, the stretch of the top piece above it is not that segment
    lg = routing.build_grid(BBOX, [], 200.0, CFG, pieces=LPIECES)
    lug = routing.under_grid(lg, BBOX, [], CFG, LPIECES)
    seg = routing.edge_links(lg, lug, BBOX, [((150.0, 100.0), (150.0, 200.0), "right")], 30.0, pieces=LPIECES)
    assert len(seg) == 50 and all(148.0 <= lug.centre(u)[0] <= 150.0 and 100.0 <= lug.centre(u)[1] <= 200.0 for u, *_ in seg)
    assert all(lg.centre(t)[0] > 150.0 for _, t, *_ in seg)


def pieces_ctx(rects):
    """plug_ctx (board 0..300 x 0..200, A -> B) with the board made of pieces (the bounding box stays 0..300 x 0..200)."""
    ctx = plug_ctx({"type": "ra"})
    lay = ctx["layout"]
    lay["pieces"] = [mm_item(f"i-p{n}", "Board", r[0], r[1], r[2] - r[0], r[3] - r[1], "pedalboard") for n, r in enumerate(rects)]
    lay.update(board=lay["pieces"][0], board_rects=list(rects), board_rect=design.bounding_rect(rects), usable_rects=list(rects),
               usable=design.bounding_rect(rects))
    return ctx


def route(ctx):
    routing.route_project(ctx, {}, cable_types=RA_TYPES)
    (c,) = [x for x in ctx["cable_list"] if x["kind"] == "signal"]
    return c


def test_a_cable_runs_across_the_joint_like_on_one_board():
    whole = route(plug_ctx({"type": "ra"}))
    two = route(pieces_ctx([(0.0, 0.0, 150.0, 200.0), (150.0, 0.0, 300.0, 200.0)]))      # the joint between A and B
    assert two["status"] == "routed" and two["min_mm"] == pytest.approx(whole["min_mm"]) and two["path"] == whole["path"]
    assert two["under_board"] is False


def test_a_cable_cannot_cross_a_gap_wider_than_the_margins_but_can_a_narrow_one():
    whole = route(plug_ctx({"type": "ra"}))
    near = pieces_ctx([(0.0, 0.0, 148.0, 200.0), (152.0, 0.0, 300.0, 200.0)])         # a 4 mm gap: every cell is within the margin of a piece
    c = route(near)
    assert c["status"] == "routed" and c["min_mm"] == pytest.approx(whole["min_mm"])
    far = pieces_ctx([(0.0, 0.0, 100.0, 200.0), (200.0, 0.0, 300.0, 200.0)])          # a 100 mm gap: the cells in its middle are walls
    f = route(far)
    assert f["status"].startswith("unroutable")
    g = far["routing"]["grid"]
    assert g.cell_of(150.0, 100.0) in g.blocked and g.cell_of(103.0, 100.0) not in g.blocked
    assert not [x for x in far["cable_list"] if x.get("under_board")]


def test_the_drawing_shows_every_piece_and_every_usable_rect():
    rects = [(0.0, 0.0, 150.0, 200.0), (150.0, 0.0, 300.0, 200.0)]
    ctx = pieces_ctx(rects)
    route(ctx)
    ctx["layout"]["usable_rects"] = [(10.0, 0.0, 150.0, 200.0), (150.0, 0.0, 300.0, 190.0)]
    svg = svgdraw.render(ctx, {"a": "A", "b": "B"})
    assert svg.count('class="board"') == 2 and svg.count('class="usable-area"') == 2
    ctx["layout"]["usable_rects"] = rects
    assert svgdraw.render(ctx, {"a": "A", "b": "B"}).count('class="usable-area"') == 0


# --- scripts/boards.py: every piece gets its holes -----------------------------------------------------------
def test_boards_py_wants_the_image_of_every_piece(tmp_path, monkeypatch):
    # a layout with two pedalboard items: both board images are wanted, each with its own size (only the first piece before)
    (tmp_path / "project.json").write_text(json.dumps({"board": {"brand": "X", "model": "Y"}}))
    (tmp_path / "playground_design.json").write_text("{}")
    monkeypatch.setattr(boards_mod, "project_dirs", lambda names: [tmp_path])
    monkeypatch.setattr(design, "parse_design", lambda f: [{**mm_item("i1", "B1", 0, 0, 100, 50, "pedalboard"), "image": "one.png"},
                                                           {**mm_item("i2", "B2", 100, 0, 80, 50, "pedalboard"), "image": "two.png"}])
    assert boards_mod.wanted(None, [], {}) == {"one.png": (100, 50), "two.png": (80, 50)}


def test_the_board_editor_keeps_the_pieces_key_when_it_saves(tmp_path):
    import board_editor
    pieces = {"q.png": {"boxes": [], "bounds": {"right": 0.8}}}
    (tmp_path / "board.json").write_text(json.dumps({"boxes": [], "pieces": pieces}))
    board_editor.save_edits(tmp_path, [{"type": "hole", "x0": 0.1, "y0": 0.1, "x1": 0.2, "y1": 0.2}], {"left": 0.1})
    saved = json.loads((tmp_path / "board.json").read_text())
    assert saved["pieces"] == pieces and saved["bounds"] == {"left": 0.1} and len(saved["boxes"]) == 1
    board_editor.save_edits(tmp_path, [])
    assert json.loads((tmp_path / "board.json").read_text())["pieces"] == pieces
