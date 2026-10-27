"""Edge crossings: the segments of board.json (type "edge") along the board border where cables may go round the board edge.
Data (boards.load_edits), their canvas mapping (design.board_edges), the error for an under-board supply with no way up
(jacks.crossing_errors), the power estimate's crossing points (power.edge_sample / Crossings) and the board editor's helpers.
Hand-computed on small synthetic boards; all lengths in mm."""
import json
import math
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import board_editor as be  # noqa: E402
import boards  # noqa: E402
import design  # noqa: E402
import jacks  # noqa: E402
import power  # noqa: E402
import routing  # noqa: E402
import svgdraw  # noqa: E402
from test_boards import board  # noqa: E402
from test_check import A, PDATA, PEDALS, SUPPLIES, S, insts, project  # noqa: E402
from test_layout import BOARD, HOLE_BOARD, hole_model, ped  # noqa: E402

W, H = 200.0, 100.0   # an image of 200 x 100 mm for the editor helpers


def edge(side, f, t):
    return {"type": "edge", "side": side, "from": f, "to": t}


# --- board.json ------------------------------------------------------------------------------------
def test_load_edits_accepts_edge_segments_and_rejects_malformed_ones(tmp_path):
    good = edge("left", 0.2, 0.6)
    bad = [edge("top", 0.2, 0.6), edge("left", 0.6, 0.2), edge("left", 0.2, 0.2), edge("back", -0.1, 0.5), edge("front", 0.5, 1.2),
           {"type": "edge", "side": "left", "from": "a", "to": 1}, {"type": "edge", "side": "left", "from": 0.1},
           # an old-style box of the edge type (the removed design) and the hole boxes' own range rule
           {"type": "edge", "x0": -0.1, "y0": 0, "x1": 0.5, "y1": 0.2}, {"type": "hole", "x0": -0.1, "y0": 0, "x1": 0.5, "y1": 0.2}]
    hole = {"type": "hole", "x0": 0.1, "y0": 0.2, "x1": 0.3, "y1": 0.4}
    (tmp_path / "board.json").write_text(json.dumps({"boxes": [hole, good, *bad, edge("back", 0.0, 1.0)]}))
    w = []
    assert boards.load_edits(tmp_path, w) == [hole, good, edge("back", 0.0, 1.0)]
    assert len(w) == len(bad)
    assert boards.box_ok(good) and not boards.box_ok({**good, "extra": 1} | {"side": "x"})


# --- design.board_edges ----------------------------------------------------------------------------
def test_board_edges_map_to_canvas_segments_and_sides():
    # the 100 x 50 mm board at left 20, top 10 (footprint x 20..120, y 10..60)
    edits = [edge("left", 0.2, 0.6), edge("right", 0.0, 0.5), edge("back", 0.1, 0.5), edge("front", 0.5, 1.0),
             {"type": "hole", "x0": 0.1, "y0": 0.2, "x1": 0.3, "y1": 0.4}]
    got = design.board_edges(board(0), edits)
    assert got == [((20, 20), (20, 40), "left"), ((120, 10), (120, 35), "right"), ((30, 10), (70, 10), "back"), ((70, 60), (120, 60), "front")]
    assert design.board_edges(None, edits) == [] and design.board_edges(board(0), []) == []


def test_board_edges_rotate_with_the_board():
    # rotated 90 degrees about the centre (70, 35): footprint x 45..95, y -15..85; (u, v) -> (-v, u): the image's left edge is on top
    got = design.board_edges(board(90), [edge("left", 0.2, 0.6), edge("back", 0.0, 0.5), edge("right", 0.0, 1.0)])
    assert got[0] == (pytest.approx((65, -15)), pytest.approx((85, -15)), "back")        # left (x 0) -> the canvas back, y = -15
    assert got[1][2] == "right" and got[1][0] == pytest.approx((95, -15)) and got[1][1] == pytest.approx((95, 35))    # the image's back edge
    assert got[2][2] == "front" and got[2][0] == pytest.approx((45, 85)) and got[2][1] == pytest.approx((95, 85))
    # 180: the back edge is at the front, the left at the right
    flipped = design.board_edges(board(180), [edge("back", 0.1, 0.5), edge("left", 0.0, 1.0)])
    assert flipped[0][2] == "front" and flipped[0][0] == pytest.approx((70, 60)) and flipped[0][1] == pytest.approx((110, 60))
    assert flipped[1][2] == "right"


def test_edge_segments_are_not_holes():
    assert design.board_holes(board(), [[0.1, 0.2, 0.3, 0.6]], [edge("left", 0.0, 1.0)]) == [pytest.approx((30, 20, 50, 40))]


# --- the error: an under-board supply with no way up ------------------------------------------------
def check(tmp_path, supplies, edits=None, holes=(), cables=None, specs=None):
    ctx = project(tmp_path, specs or [BOARD, ped("T A", 0)], chain=("a",), supplies=supplies)
    ctx["project"]["cables"] = cables or {}
    if edits is not None:
        (tmp_path / "board.json").write_text(json.dumps({"boxes": edits}))
    jacks.check(ctx, PEDALS, SUPPLIES, PDATA, defer=True, board_data={"x.png": {"holes": [list(h) for h in holes]}})
    return [e for e in ctx["errors"] if "no power cable can come up" in e], ctx


def test_neither_holes_nor_edge_segments_is_an_error_per_under_board_instance(tmp_path):
    errs, ctx = check(tmp_path, insts(("psu1", "under", ["a"]), ("psu2", None, []), ("psu3", "on_board", [])))
    assert len(errs) == 2 and errs[0].startswith("power.supplies: psu1 is under the board, but the board has no holes and no edge segments")
    assert "psu2 is under" in errs[1] and "scripts/board_editor.py" in errs[0] and "set placement on_board" in errs[0]
    assert not any("psu3" in e for e in ctx["errors"])


def test_an_on_board_supply_never_needs_a_way_up(tmp_path):
    assert check(tmp_path, insts(("psu1", "on_board", ["a"])))[0] == []


def test_a_hole_or_an_edge_segment_is_enough(tmp_path):
    sup = insts(("psu1", "under", ["a"]))
    assert check(tmp_path, sup, holes=[[0.4, 0.4, 0.6, 0.6]])[0] == []
    assert check(tmp_path, sup, edits=[edge("left", 0.1, 0.5)])[0] == []
    assert check(tmp_path, sup, edits=[{"type": "hole", "x0": 0.4, "y0": 0.4, "x1": 0.6, "y1": 0.6}])[0] == []   # a hole box of board.json


def test_a_hole_every_pedal_covers_does_not_count(tmp_path):
    # the pedal A (0..90 x 0..180 px = 0..50.8 x 0..101.6 mm) covers the whole hole at x 0.05..0.15 (12.7..38.1 mm), y 0.1..0.5
    errs, _ = check(tmp_path, insts(("psu1", "under", ["a"])), holes=[[0.05, 0.1, 0.15, 0.5]])
    assert len(errs) == 1 and "covered by a pedal or a supply" in errs[0]


def test_a_front_segment_counts_only_with_route_in_front(tmp_path):
    sup = insts(("psu1", "under", ["a"]))
    assert len(check(tmp_path, sup, edits=[edge("front", 0.1, 0.5)])[0]) == 1
    assert check(tmp_path, sup, edits=[edge("front", 0.1, 0.5)], cables={"route_in_front": True})[0] == []
    assert check(tmp_path, sup, edits=[edge("front", 0.1, 0.5), edge("back", 0.1, 0.5)])[0] == []


def test_without_a_layout_the_data_decides(tmp_path, monkeypatch):
    import common
    monkeypatch.setattr(common, "database", lambda name: {"Rock Duo": {"Image": "duo.png"}})
    ctx = {"project": {"board": {"brand": "Rock", "model": "Duo"}, "cables": {}}, "dir": tmp_path, "supplies": insts(("psu1", "under", ["a"]), ("psu2", "on_board", []))}
    data = {"duo.png": {"holes": []}}
    got = jacks.data_crossing_errors(ctx, data, [])
    assert len(got) == 1 and "psu1" in got[0]                                          # on-board psu2: none
    assert jacks.data_crossing_errors(ctx, {"duo.png": {"holes": [[0, 0, 0.1, 0.1]]}}, []) == []
    assert jacks.data_crossing_errors(ctx, data, [{"type": "hole", "x0": 0.1, "y0": 0.1, "x1": 0.2, "y1": 0.2}]) == []
    assert jacks.data_crossing_errors(ctx, data, [edge("right", 0.1, 0.9)]) == []
    assert len(jacks.data_crossing_errors(ctx, data, [edge("front", 0.1, 0.9)])) == 1
    assert jacks.data_crossing_errors({**ctx, "project": {**ctx["project"], "cables": {"route_in_front": True}}}, data, [edge("front", 0.1, 0.9)]) == []
    assert jacks.data_crossing_errors(ctx, {}, []) == []                              # the board's holes are unknown: no error
    monkeypatch.setattr(common, "database", lambda name: {})
    assert jacks.data_crossing_errors(ctx, data, []) == []                             # the board is unknown too


def test_the_committed_projects_have_a_way_up_for_their_under_board_supplies():
    import build
    from common import load_catalog
    pedals, supplies = load_catalog()
    for name in ("guitar-gig", "guitar-practice", "bass"):
        ctx = build.validate(ROOT / "projects" / name, pedals, supplies, route=False)
        assert not [e for e in ctx["errors"] if "no power cable can come up" in e], name


# --- the estimate: edge points with their own transit -------------------------------------------------
def test_edge_sample_is_a_centred_row_of_points_along_each_segment():
    pts = power.edge_sample([((0.0, 0.0), (30.0, 0.0), "back"), ((0.0, 10.0), (0.0, 13.0), "left")], spacing=6.0)
    assert pts == [pytest.approx(p) for p in [(3.0, 0.0), (9.0, 0.0), (15.0, 0.0), (21.0, 0.0), (27.0, 0.0), (0.0, 11.5)]]
    assert power.edge_sample(None) == [] and power.edge_sample([]) == []


def test_crossings_choose_the_cheapest_point_including_its_transit():
    cfg = {"top_cost": 3.0, "transit_mm": 15.0, "edge_transit_mm": 30.0}
    holes, edges = power.HoleIndex([(100.0, 50.0)]), power.HoleIndex([(40.0, 0.0)])
    cross = power.Crossings(holes, edges, cfg)
    # from (100, 40): the hole is 10 mm away (15 + 30 = 45), the edge point 60 mm away (30 + 180)
    assert cross.nearest((100.0, 40.0)) == (100.0, 50.0)
    # from (40, 4): the edge point 4 mm away (30 + 12 = 42), the hole 60+ mm away
    assert cross.nearest((40.0, 4.0)) == (40.0, 0.0) and cross.transit_of((40.0, 0.0), 15.0) == 30.0
    # from (60, 20): the hole is 50 mm away (15 + 150 = 165), the edge point 28.3 mm away (30 + 85 = 115): the edge wins by its distance
    assert cross.nearest((60.0, 20.0)) == (40.0, 0.0)
    assert power.Crossings(holes, None, cfg).nearest((40.0, 4.0)) == (100.0, 50.0) and len(cross) == 2 and len(power.Crossings(holes, None, cfg)) == 1


def test_hop_estimate_pays_the_edge_transit_for_an_edge_point():
    cfg = {"top_cost": 3.0, "transit_mm": 15.0, "edge_transit_mm": 30.0}
    cross = power.Crossings(power.HoleIndex([]), power.HoleIndex([(50.0, 0.0)]), cfg)
    # source under at (0, 0), target (50, 10): under Manhattan to (50, 0) = 50, the edge transit 30, 3 x 10 on top
    assert power.hop_estimate((0, 0), (50, 10), True, cross, cfg) == pytest.approx(50 + 30 + 30)
    # the same with a hole point there: the hole transit (15)
    holes = power.Crossings(power.HoleIndex([(50.0, 0.0)]), None, cfg)
    assert power.hop_estimate((0, 0), (50, 10), True, holes, cfg) == pytest.approx(50 + 15 + 30)
    # a plain HoleIndex keeps the old behaviour
    assert power.hop_estimate((0, 0), (50, 10), True, power.HoleIndex([(50.0, 0.0)]), cfg) == pytest.approx(95)


def test_the_model_samples_the_edge_segments_with_the_edge_transit():
    edits = [edge("back", 0.4, 0.6)]                          # x 101.6..152.4 on the back edge (y 0) of the 254 x 127 mm board
    setup = hole_model([ped("T A", 0)], {}, edits).power_setup
    assert setup is not None and len(setup["index"]) == 0 and len(setup["edges"]) > 0
    assert all(y == 0 and 101.6 <= x <= 152.4 for x, y in setup["edges"].points)
    assert setup["cfg"]["edge_transit_mm"] == 30.0 and len(setup["crossings"]) == len(setup["edges"])
    both = hole_model([ped("T A", 0)], HOLE_BOARD, edits).power_setup
    assert len(both["index"]) > 0 and len(both["crossings"]) == len(both["index"]) + len(both["edges"])
    # a front segment only counts with cables.route_in_front
    front = [edge("front", 0.4, 0.6)]
    assert hole_model([ped("T A", 0)], {}, front).power_setup is None


# --- the board editor ------------------------------------------------------------------------------
def test_project_edge_snaps_a_line_to_the_nearest_side():
    # 200 x 100 mm: a line near the left border (x 0.01), from y 0.2 to y 0.6, is the left segment 0.2..0.6
    assert be.project_edge(0.01, 0.6, 0.015, 0.2, W, H) == edge("left", 0.2, 0.6)           # drawn upwards: from < to
    assert be.project_edge(0.99, 0.1, 1.02, 0.9, W, H) == edge("right", 0.1, 0.9)           # a line just outside the right border
    assert be.project_edge(0.3, 0.02, 0.7, -0.04, W, H) == edge("back", 0.3, 0.7)           # beyond the top border: back
    assert be.project_edge(0.2, 0.97, 0.5, 1.05, W, H) == edge("front", 0.2, 0.5)


def test_project_edge_diagonal_and_clamped_lines():
    # a diagonal across the lower-left corner: the middle (0.1, 0.9) is 20 mm from the left and 10 mm from the front side
    assert be.project_edge(0.0, 0.7, 0.2, 1.1, W, H) == edge("front", 0.0, 0.2)
    # the same lines on a tall image (100 x 200 mm): the left side is nearer (10 mm against 20 mm)
    assert be.project_edge(0.0, 0.7, 0.2, 1.1, 100.0, 200.0) == edge("left", 0.7, 1.0)
    # beyond the corner: clamped to the side
    assert be.project_edge(0.02, 0.8, 0.0, 1.4, W, H) == edge("left", 0.8, 1.0)
    # a line in the middle of the image snaps to the side nearest its middle: here the front (0.1 away in y, 0.4 in x)
    assert be.project_edge(0.4, 0.92, 0.6, 0.9, W, H) == edge("front", 0.4, 0.6)


def test_project_edge_rejects_a_line_shorter_than_one_mm_along_the_side():
    assert be.project_edge(0.01, 0.50, 0.01, 0.505, W, H) is None          # 0.5 mm along the left side
    assert be.project_edge(0.01, 0.50, 0.01, 0.51, W, H) == edge("left", 0.5, 0.51)    # exactly 1 mm
    assert be.project_edge(0.5, 0.01, 0.503, 0.01, W, H) is None           # 0.6 mm along the back side
    assert be.project_edge(0.3, 0.5, 0.3, 0.5, W, H) is None
    assert be.normalize_box(0.01, 0.2, 0.01, 0.6, "edge", W, H) == edge("left", 0.2, 0.6)
    assert be.normalize_box(0.01, 0.5, 0.01, 0.5, "edge", W, H) is None


def test_the_type_cycles_hole_filled_edge_and_a_selected_box_toggles_hole_filled():
    assert [be.next_type(t) for t in ("hole", "filled", "edge")] == ["filled", "edge", "hole"]
    assert be.next_type("weird") == "hole" and be.TYPES == ("hole", "filled", "edge")
    e = edge("left", 0.1, 0.2)
    assert be.toggle_type(e) is e and be.toggle_type(be.make_box("hole", 0, 0, 1, 1))["type"] == "filled"


def test_hole_and_filled_boxes_still_clamp_to_the_image_and_edge_lines_clamp_along_the_side():
    assert be.normalize_box(-0.3, 0.2, 0.5, 1.7, "hole", W, H) == be.make_box("hole", 0.0, 0.2, 0.5, 1.0)
    assert be.px_to_frac(10, 500, 2.0, W, H, 30) == (0.0, 1.0)                                # clamped by default
    # unclamped (the margin round the image: an edge line is drawn just outside the border)
    assert be.px_to_frac(10, 500, 2.0, W, H, 30, clamp=False) == pytest.approx((-0.05, 2.35))
    assert be.px_to_frac(130, 80, 2.0, W, H, 30, clamp=False) == pytest.approx((0.25, 0.25))


def test_hit_move_and_nudge_an_edge_segment_along_its_side():
    boxes = [be.make_box("hole", 0.0, 0.0, 0.5, 0.5), edge("left", 0.2, 0.6)]
    # within 2 mm of the left side (0.005 x 200 = 1 mm), in y between 0.2 and 0.6 (the edge segment is above the hole box)
    assert be.hit_box(boxes, 0.005, 0.4, W, H) == 1
    assert be.hit_box(boxes, 0.02, 0.4, W, H) == 0                   # 4 mm from the side: only the hole box
    assert be.hit_box(boxes, 0.005, 0.7, W, H) is None               # beyond the end of the segment (by 10 mm)
    assert be.hit_box(boxes, 0.005, 0.4) == 0                        # no image size: edge segments are ignored
    m = be.move_box(edge("left", 0.2, 0.6), 0.3, 0.1)                # the x part is ignored on a left side
    assert (m["from"], m["to"], m["side"]) == pytest.approx((0.3, 0.7, "left"))
    assert be.move_box(edge("left", 0.2, 0.6), 0, 5)["to"] == 1.0 and be.move_box(edge("left", 0.2, 0.6), 0, 5)["from"] == pytest.approx(0.6)
    n = be.nudge_box(edge("back", 0.2, 0.6), 2.0, 50.0, W, H)        # back side: x only, 2 mm = 0.01
    assert (n["from"], n["to"]) == pytest.approx((0.21, 0.61))
    n = be.nudge_box(edge("right", 0.2, 0.6), 50.0, -5.0, W, H)      # right side: y only, -5 mm = -0.05
    assert (n["from"], n["to"]) == pytest.approx((0.15, 0.55))


def test_list_rows_and_the_file_round_trip_with_edge_segments(tmp_path):
    boxes = [be.make_box("hole", 0.1, 0.2, 0.3, 0.6), edge("left", 0.2, 0.45), edge("back", 0.0, 1.0)]
    assert be.list_rows(boxes, W, H) == [" 1  hole    40.0 x 40.0 mm", " 2  edge    left 0.20-0.45 (25.0 mm)", " 3  edge    back 0.00-1.00 (200.0 mm)"]
    text = be.dumps_edits(boxes)
    assert text.splitlines()[4] == '    {"type": "edge", "side": "left", "from": 0.2, "to": 0.45},'
    assert json.loads(text)["boxes"][2] == edge("back", 0.0, 1.0)
    be.save_edits(tmp_path, boxes)
    w = []
    assert boards.load_edits(tmp_path, w) == boxes and w == []
    assert be.effective_holes([[0.0, 0.0, 0.5, 0.5]], boxes[1:], W, H) == pytest.approx([(0, 0, 100, 50)])     # edge: not a hole


def test_project_rows_count_edge_segments_separately(tmp_path, monkeypatch):
    p = tmp_path / "demo"
    p.mkdir()
    (p / "project.json").write_text(json.dumps({"board": {"brand": "Rock", "model": "Duo"}}))
    be.save_edits(p, [be.make_box("hole", 0.1, 0.1, 0.2, 0.2), edge("left", 0.1, 0.5), edge("back", 0.1, 0.5)])
    monkeypatch.setattr(be, "project_dirs", lambda names: [p])
    (row,) = be.project_rows(None, {"Rock Duo": {"Image": "d.png", "Width": 1, "Height": 1}}, {"d.png": {"holes": []}})
    assert "edit boxes 1" in row and "edge segments 2" in row


# --- drawing ---------------------------------------------------------------------------------------
def test_edge_segments_are_drawn_as_thick_translucent_lines_with_a_key_entry():
    segs = [((0.0, 10.0), (0.0, 40.0), "left")]
    svg = "".join(svgdraw.edge_segments(segs))
    assert 'x1="0.0" y1="10.0" x2="0.0" y2="40.0"' in svg and 'class="edge-segment"' in svg and 'stroke-opacity="0.6"' in svg
    assert svgdraw.edge_segments([]) == [] and svgdraw.edge_segments(None) == []
    ctx = {"layout": {"edge_segments": segs}}
    assert ("edge", "edge crossing: cables may go round the board edge here") in svgdraw.key_entries(ctx, [], 2)
    assert ("edge", svgdraw.EDGE_KEY) not in svgdraw.key_entries({"layout": {"edge_segments": []}}, [], 2)
    assert "<line" in svgdraw.key_sample("edge", 0, 0)
