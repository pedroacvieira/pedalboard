"""Usable board area (board.json `bounds`): the canvas rectangle (design.board_bounds), the build warning (jacks.check), the routing
area of the signal / power grids (routing.build_grid, area_limits, edge strips), the layout search (feasible_one, free_distance,
repair_start), the proposal table row and the drawing. Hand-computed on small synthetic boards; all lengths in mm."""
import json
import shutil
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import build  # noqa: E402
import design  # noqa: E402
import jacks  # noqa: E402
import layout  # noqa: E402
import routing  # noqa: E402
import svgdraw  # noqa: E402
from test_boards import board  # noqa: E402
from test_check import PDATA, PEDALS, SUPPLIES, insts, project  # noqa: E402
from test_layout import BOARD, JACKS, TYPES, canvas, ped  # noqa: E402

PX = 25.4 / 45   # one Pedal Playground px in mm


# --- design.board_bounds -----------------------------------------------------------------------------
BOUNDS = {"back": 0.1, "front": 0.8, "left": 0.2, "right": 0.9}


def test_board_bounds_rotations():
    # the 100 x 50 mm image at left 20, top 10 (centre (70, 35)); (u, v) = offset of the corner from the centre
    assert design.board_bounds(board(0), BOUNDS) == pytest.approx((40, 15, 110, 50))       # x 20 + 100 * (0.2, 0.9), y 10 + 50 * (0.1, 0.8)
    # 90: (u, v) -> (-v, u): corners (0.2, 0.1) -> u -30, v -20 -> (90, 5); (0.9, 0.8) -> u 40, v 15 -> (55, 75)
    assert design.board_bounds(board(90), BOUNDS) == pytest.approx((55, 5, 90, 75))
    # 270: (u, v) -> (v, -u): (0.2, 0.1) -> (50, 65); (0.9, 0.8) -> (85, -5)
    assert design.board_bounds(board(270), BOUNDS) == pytest.approx((50, -5, 85, 65))


def test_board_bounds_default_to_the_footprint_and_need_a_board():
    for rot in (0, 90, 270):
        b = board(rot)
        assert design.board_bounds(b, None) == pytest.approx(design.footprint(b))
        assert design.board_bounds(b, {}) == pytest.approx(design.footprint(b))
        assert design.board_bounds(b, {"back": 0.0, "front": 1.0, "left": 0.0, "right": 1.0}) == pytest.approx(design.footprint(b))
    assert design.board_bounds(None, BOUNDS) is None
    assert design.board_bounds(board(0), {"back": 0.5}) == pytest.approx((20, 35, 120, 60))   # one side only: the others stay at the edges


def test_has_bounds_compares_with_the_board_footprint():
    b = board(0)
    assert not design.has_bounds(None) and not design.has_bounds({"board": None, "usable": None})
    assert not design.has_bounds({"board": b, "usable": design.footprint(b)})
    assert design.has_bounds({"board": b, "usable": design.board_bounds(b, {"back": 0.1})})


# --- the build warning -------------------------------------------------------------------------------
# board 254 x 127 mm at (0, 0); a pedal "T A" (50.8 x 101.6) with its top at 9 px = 5.08 mm. back = (5.08 + 5) / 127: the line is 5 mm below its top
BACK_5 = (9 * PX + 5.0) / 127.0


def check(tmp_path, specs, bounds=None, validation=None, supplies=(), chain=("a",)):
    ctx = project(tmp_path, specs, validation=validation, chain=chain, supplies=supplies)
    if bounds is not None:
        (tmp_path / "board.json").write_text(json.dumps({"bounds": bounds}))
    jacks.check(ctx, PEDALS, SUPPLIES, PDATA, defer=True, board_data={})
    return ctx


def outside(ctx, errors=False):
    return [m for m in ctx["errors" if errors else "warnings"] if "outside the usable board area" in m]


def test_a_pedal_past_the_back_line_is_a_warning_with_side_and_depth(tmp_path):
    ctx = check(tmp_path, [BOARD, ped("T A", 0, 9)], {"back": BACK_5})
    assert outside(ctx) == ["layout: T A is outside the usable board area by 5.0 mm (back)"]
    assert not outside(ctx, errors=True) and ctx["outside_usable"] == ["item-1"]


def test_strict_bounds_makes_it_an_error(tmp_path):
    ctx = check(tmp_path, [BOARD, ped("T A", 0, 9)], {"back": BACK_5}, validation={"strict_bounds": True})
    assert outside(ctx, errors=True) == ["layout: T A is outside the usable board area by 5.0 mm (back)"] and not outside(ctx)


def test_the_worst_side_is_reported_once_per_item(tmp_path):
    # left line at 25.4 mm (0.1): the pedal's left edge is at 0 -> 25.4 mm; the back line is only 5 mm below its top
    ctx = check(tmp_path, [BOARD, ped("T A", 0, 9)], {"back": BACK_5, "left": 0.1})
    assert outside(ctx) == ["layout: T A is outside the usable board area by 25.4 mm (left)"]


def test_a_pedal_inside_and_no_bounds_give_nothing(tmp_path):
    assert not outside(check(tmp_path, [BOARD, ped("T A", 0, 20)], {"back": BACK_5}))      # top 11.29 mm > 10.08
    other = tmp_path / "none"
    other.mkdir()
    ctx = check(other, [BOARD, ped("T A", 0, 0)])                                          # no board.json: the board edges
    assert not outside(ctx) and ctx["outside_usable"] == [] and ctx["layout"]["usable"] == pytest.approx(design.footprint(ctx["layout"]["board"]))


def test_an_under_board_supply_outside_is_never_checked_but_an_on_board_one_is(tmp_path):
    specs = [BOARD, ped("T A", 0, 30), ("S One", 200, 0, 2.0, 1.0, 0, "pedal")]            # the supply sits at the very back (top 0)
    under = check(tmp_path, specs, {"back": BACK_5}, supplies=insts(("psu1", "under", ["a"])))
    assert not outside(under)
    on = tmp_path / "on"
    on.mkdir()
    ctx = check(on, specs, {"back": BACK_5}, supplies=insts(("psu1", "on_board", ["a"])))
    assert outside(ctx) == ["layout: S One is outside the usable board area by 10.1 mm (back)"]   # top 0, the line at 10.08


def test_a_box_within_the_rounding_is_not_reported(tmp_path):
    # the line 0.04 mm below the pedal's top: under the 0.05 mm that would print as 0.0
    ctx = check(tmp_path, [BOARD, ped("T A", 0, 9)], {"back": (9 * PX + 0.04) / 127.0})
    assert not outside(ctx)


# --- the routing area --------------------------------------------------------------------------------
CFG = {**routing.DEFAULTS, "grid_mm": 2.0, "edge_margin_mm": 4.0, "diameter_mm": 2.0}
BRD = (0.0, 0.0, 60.0, 30.0)      # the grid: x -4..64, y -4..30 (cells 2 mm, centres at odd numbers)


def centre_cell(g, x, y):
    return g.cell_of(x, y)


def test_without_bounds_the_grid_is_cell_for_cell_the_plain_one():
    pedal = [(20.0, 10.0, 30.0, 20.0)]
    plain = routing.build_grid(BRD, pedal, 30.0, CFG)
    for usable in (BRD, (0.0, 0.0, 60.0, 30.0)):
        g = routing.build_grid(BRD, pedal, 30.0, CFG, usable, [((20, 0), (40, 0), "back")])
        assert (g.x0, g.y0, g.nx, g.ny) == (plain.x0, plain.y0, plain.nx, plain.ny)
        assert g.blocked == plain.blocked and g.body == plain.body
    assert routing.area_limits(BRD, None, 30.0, CFG) == (None, None, None, None)
    assert routing.area_limits(BRD, BRD, 30.0, CFG) == (None, None, None, None)
    assert routing.area_rect(plain, BRD, None, 30.0, CFG) == (plain.x0, plain.y0, plain.x0 + plain.nx * plain.cell, 30.0)
    assert routing.area_rect(plain, BRD, BRD, 30.0, CFG) == routing.area_rect(plain, BRD, None, 30.0, CFG)


def test_cells_outside_the_grown_usable_area_are_walls():
    usable = (10.0, 8.0, 50.0, 30.0)      # back 8 mm and sides 10 mm in; the grown area: x 6..54, y 4..
    assert routing.area_limits(BRD, usable, 30.0, CFG) == (6.0, 4.0, 54.0, None)
    g = routing.build_grid(BRD, [], 30.0, CFG, usable)
    plain = routing.build_grid(BRD, [], 30.0, CFG)
    assert (g.nx, g.ny) == (plain.nx, plain.ny)                      # the extent (and so the cell indices) stay today's
    for x, y, free in ((7, 5, True), (5, 5, False), (7, 3, False), (53, 29, True), (55, 29, False), (64 - 1, 29, False)):
        c = g.cell_of(x, y)
        assert (c not in g.blocked) is free and (c not in g.body) is free
    assert routing.area_rect(g, BRD, usable, 30.0, CFG) == (6.0, 4.0, 54.0, 30.0)
    assert g.blocked > plain.blocked


def test_an_edge_segment_strip_stays_open_up_to_the_border_and_edge_links_find_it():
    usable = (10.0, 8.0, 50.0, 30.0)
    seg = ((20.0, 0.0), (40.0, 0.0), "back")
    g = routing.build_grid(BRD, [], 30.0, CFG, usable, [seg])
    assert g.cell_of(25, 1) not in g.blocked and g.cell_of(25, -3) not in g.blocked           # in the strip: from the border + margin
    assert g.cell_of(15, 1) in g.blocked and g.cell_of(45, -3) in g.blocked                  # beside it: cut
    assert g.cell_of(25, -3) not in g.blocked and g.cell_of(5, 25) in g.blocked              # (the left cut still holds in the strip's row range)
    ug = routing.under_grid(g, BRD, [], CFG)
    links = routing.edge_links(g, ug, BRD, [seg], 30.0)
    assert len(links) == 10 and all(sd == "back" and 20 <= ug.centre(u)[0] <= 40 and t == (u[0], u[1] - 1) for u, t, _, sd in links)
    no_strip = routing.build_grid(BRD, [], 30.0, CFG, usable)
    assert routing.edge_links(no_strip, routing.under_grid(no_strip, BRD, [], CFG), BRD, [seg], 30.0) == []   # without the strip: no free cell


def test_the_strip_of_a_side_segment_and_the_corner_with_another_cut():
    usable = (10.0, 8.0, 50.0, 30.0)
    seg = ((0.0, 14.0), (0.0, 20.0), "left")
    g = routing.build_grid(BRD, [], 30.0, CFG, usable, [seg])
    assert g.cell_of(1, 15) not in g.blocked and g.cell_of(-3, 17) not in g.blocked           # left strip
    assert g.cell_of(1, 11) in g.blocked                                                     # above the span
    plain_back = routing.build_grid(BRD, [], 30.0, CFG, usable, [((0.0, 0.0), (60.0, 0.0), "back")])
    assert plain_back.cell_of(1, 1) in plain_back.blocked                                    # a back strip does not open the left cut (corner)


def test_front_limit_and_the_front_cut_with_route_in_front():
    usable = (0.0, 0.0, 60.0, 20.0)
    assert routing.front_limit(BRD, [], CFG) == 30.0 and routing.front_limit(BRD, [], CFG, usable) == 20.0
    assert routing.front_limit(BRD, [14.0, 18.0], CFG, usable) == 18.0 and routing.front_limit(BRD, [25.0], CFG, usable) == 20.0
    on = {**CFG, "route_in_front": True}
    assert routing.front_limit(BRD, [], on) == 34.0 and routing.front_limit(BRD, [], on, usable) == 24.0   # the usable front + the margin
    y = routing.front_limit(BRD, [], on, usable)
    plain = routing.build_grid(BRD, [], routing.front_limit(BRD, [], on), on)
    g = routing.build_grid(BRD, [], y, on, usable, [((20.0, 30.0), (40.0, 30.0), "front")])
    assert g.ny == plain.ny and g.cell_of(10, 26) in g.blocked and g.cell_of(10, 23) not in g.blocked
    assert g.cell_of(25, 26) not in g.blocked and g.cell_of(25, 33) not in g.blocked          # the strip of a front segment to the border + margin
    assert routing.area_rect(g, BRD, usable, y, on)[3] == 24.0


def test_area_box_follows_the_grown_usable_area():
    usable = (10.0, 8.0, 50.0, 30.0)
    assert routing.area_box(BRD, None, 30.0, CFG) == (-4.0, -4.0, 64.0, 30.0)
    assert routing.area_box(BRD, usable, 30.0, CFG) == (6.0, 4.0, 54.0, 30.0)
    assert routing.area_box(BRD, (0.0, 8.0, 60.0, 30.0), 30.0, CFG) == (-4.0, 4.0, 64.0, 30.0)


# --- the layout search -------------------------------------------------------------------------------
# the 254 x 127 board; lines 0.1 / 0.9 of both axes: usable x 25.4..228.6, y 12.7..114.3
LINES = {"back": 0.1, "front": 0.9, "left": 0.1, "right": 0.9}


def bounded(specs, chain=("a",), bounds=LINES, pins=()):
    proj = {"signal_chain": list(chain), "cables": {"type": "t"}, "jacks": {}, "layout": {"pins": list(pins)}}
    items = design.parse_canvas(canvas(BOARD, *specs))
    return layout.Model(proj, items, PEDALS, {}, JACKS, {}, TYPES, outlines={}, board_bounds=bounds)


def test_the_model_uses_the_usable_area_for_feasibility_and_sliding():
    m = bounded([ped("T A", 100, 40, w=2.0, h=2.0)])         # 50.8 x 50.8 at (63.5 + 25.4 ... ) -> centre (x 100 px = 56.4 mm + 25.4)
    assert m.usable == pytest.approx((25.4, 12.7, 228.6, 114.3)) and m.board == pytest.approx((0, 0, 254, 127))
    assert m.feasible_one([(60.0, 50.0, 0)], 0)               # left edge 34.6 >= 25.4, back edge 24.6 >= 12.7
    assert not m.feasible_one([(40.0, 50.0, 0)], 0)           # left edge 14.6 < the line (the board itself would allow it)
    assert not m.feasible_one([(60.0, 30.0, 0)], 0)           # back edge 4.6 < 12.7
    assert not m.feasible_one([(215.0, 50.0, 0)], 0) and m.feasible_one([(203.2, 50.0, 0)], 0)   # right edge 240.4 > 228.6 / exactly on the line
    assert not m.feasible_one([(60.0, 100.0, 0)], 0)          # front edge 125.4 > 114.3
    m.max_move = None
    assert layout.free_distance(m, [(60.0, 50.0, 0)], 0, (-1, 0)) == pytest.approx(34.6 - 25.4)
    assert layout.free_distance(m, [(60.0, 50.0, 0)], 0, (0, -1)) == pytest.approx(24.6 - 12.7)
    assert layout.free_distance(m, [(60.0, 50.0, 0)], 0, (1, 0)) == pytest.approx(228.6 - 85.4)
    assert layout.free_distance(m, [(60.0, 50.0, 0)], 0, (0, 1)) == pytest.approx(114.3 - 75.4)


def test_the_margin_still_shrinks_the_usable_area_and_no_bounds_keep_the_board():
    m = bounded([ped("T A", 100, 40, w=2.0, h=2.0)])
    m.cfg["board_margin_mm"] = 2.0
    assert not m.feasible_one([(52.0, 50.0, 0)], 0) and m.feasible_one([(54.0, 50.0, 0)], 0)    # left edge 26.6 / 28.6 vs 25.4 + 2
    plain = bounded([ped("T A", 100, 40, w=2.0, h=2.0)], bounds=None)
    assert plain.usable == pytest.approx(plain.board) and plain.feasible_one([(40.0, 30.0, 0)], 0)


def test_a_pedal_of_the_owners_layout_outside_is_moved_inside_before_the_search():
    m = bounded([ped("T A", 0, 0, w=2.0, h=2.0)])             # centre (25.4, 25.4): left edge 0, back edge 0
    m.max_move = 40.0
    start = layout.repair_start(m, m.owner)
    f = m.footprint(start[0], 0)
    assert m.inside_usable(f) and m.feasible_one(start, 0)
    assert f[0] == pytest.approx(25.4, abs=PX + 1e-6) and f[1] == pytest.approx(12.7, abs=PX + 1e-6)      # the nearest spot: against both lines (whole px)
    assert start[0][2] == 0                                                                   # the same rotation
    assert m.score(start, detail=True)[1]["terms"]["move"][0] > 25                          # about 28 mm from the owner's position
    found = layout.search(m, "fix", seed=1, iterations=30, restarts=1)
    assert found and all(m.inside_usable(m.footprint(st[0], 0)) for _, st in found)


def test_a_pedal_that_cannot_be_placed_is_named_and_a_pinned_one_is_pushed_in_and_stays_pinned_there():
    big = [ped("T A", 0, 0, w=2.0, h=5.0)]                    # 127 mm tall > the 101.6 mm between the lines
    m = bounded(big)
    m.max_move = 40.0
    with pytest.raises(layout.CannotPlace) as e:
        layout.repair_start(m, m.owner)
    assert e.value.names == ["A (a)"]
    pinned = bounded([ped("T A", 0, 0, w=2.0, h=2.0)], pins=["a"])
    pinned.max_move = 40.0
    start = layout.repair_start(pinned, pinned.owner)
    assert pinned.inside_usable(pinned.footprint(start[0], 0))                # the pin is pushed inside too (owner, 2026-10-29)
    assert pinned.pin_at[0] == tuple(start[0]) and pinned.feasible_one(start, 0)
    assert not pinned.feasible_one(list(pinned.owner), 0)                      # ... and stays pinned at the new spot


def test_the_pre_processing_pushes_a_pedal_the_least_distance_inside():
    m = bounded([ped("T A", 100, 40, w=2.0, h=2.0)])
    m.max_move = 40.0
    cx, cy, rot = m.owner[0]
    back = m.footprint(m.owner[0], 0)[1]
    m.usable = (m.usable[0], back + 0.7, m.usable[2], m.usable[3])              # the pedal is 0.7 mm past the back line
    start = layout.repair_start(m, m.owner)
    assert start[0][0] == pytest.approx(cx, abs=PX) and 0.7 - 1e-6 <= start[0][1] - cy <= 0.7 + PX   # forward only, about 0.7 mm (whole px)
    assert m.inside_usable(m.footprint(start[0], 0))


def test_a_state_inside_is_returned_unchanged():
    m = bounded([ped("T A", 100, 40, w=2.0, h=2.0)])
    m.max_move = 40.0
    assert layout.repair_start(m, m.owner) == list(m.owner)


# --- proposals ---------------------------------------------------------------------------------------
def test_the_proposal_metrics_count_items_outside_and_gate_on_them():
    import propose_layout as pl
    base = {"errors": 0, "blocked": 1, "blocked_mm": 2.0, "collisions": 0, "unroutable": 0, "squeezed": 0, "overflow": 0, "fs_close": 0, "score": 10.0}
    owner = {**base, "outside": 1, "score": 20.0}
    mine = {**base, "outside": 0, "blocked": 1, "score": 19.0}
    assert pl.acceptable(mine, owner) and pl.rank_key(mine) < pl.rank_key(owner)
    assert not pl.acceptable({**mine, "outside": 2}, owner)
    assert not pl.acceptable({**mine, "outside": 1}, owner)                  # never outside (pinned pedals are pushed in as well)
    assert not pl.acceptable({**mine, "outside": 1, "score": 25.0}, {**owner, "outside": 0})
    old = {k: v for k, v in owner.items() if k != "outside"}                # a meta.json without the field
    assert pl.rank_key(old)[1] == 0


def test_the_readme_table_has_the_row_and_old_meta_shows_a_question_mark(tmp_path, monkeypatch):
    import common
    from test_propose import gig_copy
    pdir = gig_copy(tmp_path, monkeypatch)
    shutil.copytree(ROOT / "projects" / "guitar-gig" / "proposals", pdir / "proposals")   # the committed one: made before the field existed
    pedals, supplies = common.load_catalog()
    ctx = build.validate(pdir, pedals, supplies)
    meta_path = pdir / "proposals" / "meta.json"
    meta = json.loads(meta_path.read_text())
    meta["owner"].pop("outside", None)                                       # a meta.json made before the field existed
    for p in meta["proposals"]:
        p["metrics"].pop("outside", None)
    meta_path.write_text(json.dumps(meta))
    md = "\n".join(build.proposals_section(ctx, pedals))
    assert "| Outside the usable area | ? | ? | ? | ? |" in md
    meta["owner"]["outside"] = 2
    for p in meta["proposals"]:
        p["metrics"]["outside"] = 0
    meta_path.write_text(json.dumps(meta))
    md = "\n".join(build.proposals_section(ctx, pedals))
    assert "| Outside the usable area | 2 | 0 | 0 | 0 |" in md and "stay inside the usable board area" in md


# --- the drawing -------------------------------------------------------------------------------------
def test_the_usable_area_is_drawn_dashed_with_a_key_entry_only_with_bounds(tmp_path):
    ctx = check(tmp_path, [BOARD, ped("T A", 0, 20)], {"back": BACK_5})
    lay = ctx["layout"]
    svg = "".join(svgdraw.usable_area(lay))
    assert 'class="usable-area"' in svg and 'stroke="#00897b"' in svg and "stroke-dasharray" in svg
    assert 'y="10.1"' in svg and 'height="116.9"' in svg                                    # y 10.08 .. 127
    assert ("usable", svgdraw.USABLE_KEY) in svgdraw.key_entries({"layout": lay}, [], 2)
    assert "usable board area (pedals stay inside)" == svgdraw.USABLE_KEY
    flat = tmp_path / "flat"
    flat.mkdir()
    plain = check(flat, [BOARD, ped("T A", 0, 20)])["layout"]
    assert svgdraw.usable_area(plain) == [] and not any(k == "usable" for k, _ in svgdraw.key_entries({"layout": plain}, [], 2))
