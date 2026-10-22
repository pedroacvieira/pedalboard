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
