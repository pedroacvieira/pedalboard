"""Right-angle plugs pointing DOWN into a board hole (design.plug_geometry side "down", routing.down_available / end_options /
route_project / route_power, the under goal of the search, the drawing and the README). Synthetic cable types and hand-made
layouts (the boards of test_routing and test_power_routing); all lengths in mm, never catalog values.

Signal (test_routing.plug_ctx): board 0..300 x 200; A (20..70 x 60..160) out at (70, 80) facing right, B (200..250 x 60..160) in at
(200, 140) facing left; the 20 x 16 head's cable axis is 10 mm out, so the bend points are (80, 80) and (190, 140). The 6 mm cable
needs a 6 x 6 square inside the holes there; a down plug's cable runs jack height 12 + the deck 15 (the fallback transit) = 27 mm
from the measure point to the bend point.
Power (test_power_routing.pw_ctx): pedal A's power jack at (45, 60) facing top, the DC head 10 x 10 (axis 5 mm out): bend (45, 55), the
3.5 mm cable needs a 3.5 square there; the under-board supply PSU (100..160 x 150..180) has F1 at (112, 150), its under cable
starts at (112, 145)."""
import math
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import build  # noqa: E402
import design  # noqa: E402
import routing  # noqa: E402
import svgdraw  # noqa: E402
from test_power_routing import pw_ctx  # noqa: E402
from test_routing import TYPES, DC, mm_item, plug_ctx  # noqa: E402

TY = {**TYPES, **DC}
DROP = 12.0 + 15.0                       # jack height + the deck (fallback hole transit)
HOLE_A = (70.0, 70.0, 90.0, 90.0)        # round A's bend point (80, 80)
HOLE_B = (180.0, 130.0, 200.0, 150.0)    # round B's bend point (190, 140)
HOLE_PW = (35.0, 45.0, 55.0, 65.0)       # round the power plug's bend point (45, 55)
HOLE_D = (95.0, 45.0, 115.0, 65.0)       # round the bend point (105, 55) of pedal D's power plug


def signal(holes=(), cables=None, extra=(), under_supply=None, validation=None):
    ctx = plug_ctx({"type": "ra", **(cables or {})}, extra_obstacles=extra)
    ctx["layout"]["holes"] = list(holes)
    if under_supply:
        ctx["layout"].update(inst_item={"psu1": mm_item("i-psu", "PSU", *under_supply)}, inst_placement={"psu1": "under"})
        ctx["supplies"] = [{"inst": {"id": "psu1", "supply": "sup1"}, "sup": {"id": "sup1"}, "rows": []}]
    if validation:
        ctx["project"]["validation"] = validation
    routing.route_project(ctx, {}, cable_types=TY)
    (c,) = [x for x in ctx["cable_list"] if x["kind"] == "signal"]
    return ctx, c


# --- availability ---------------------------------------------------------------------------------
def test_availability_at_a_hole_edge_inside_by_a_hair_and_out_by_a_hair():
    hole = [(70.0, 70.0, 90.0, 90.0)]
    ok = lambda x, holes=hole, under=(): routing.down_available(holes, under, (x, 80.0), 6.0)
    assert ok(80.0)
    assert ok(87.0)                       # the square 84..90 touches the hole's edge: still inside
    assert not ok(87.01)                  # out by a hair (0.01 mm)
    assert ok(73.0) and not ok(72.99)
    assert not routing.down_available(hole, [], (80.0, 87.01), 6.0) and routing.down_available(hole, [], (80.0, 87.0), 6.0)
    assert not routing.down_available([], [], (80.0, 80.0), 6.0)       # no hole at all


def test_availability_counts_the_union_of_adjacent_hole_rects_but_not_a_gap():
    pair = [(70.0, 70.0, 80.0, 90.0), (80.0, 70.0, 90.0, 90.0)]
    assert routing.down_available(pair, [], (80.0, 80.0), 6.0)          # the square straddles the shared edge
    gap = [(70.0, 70.0, 79.9, 90.0), (80.1, 70.0, 90.0, 90.0)]
    assert not routing.down_available(gap, [], (80.0, 80.0), 6.0)       # a 0.2 mm slit between them: the square is not inside
    corner = [(70.0, 70.0, 80.0, 90.0), (80.0, 80.0, 90.0, 90.0)]       # an L: the square's upper right quarter is missing
    assert not routing.down_available(corner, [], (80.0, 80.0), 6.0)


def test_an_under_board_obstacle_blocks_a_down_plug_within_the_cable_radius():
    hole = [(70.0, 70.0, 90.0, 90.0)]
    supply = [(86.0, 70.0, 100.0, 90.0)]          # grown by the 3 mm radius: from x 83; the square at (80, 80) reaches 83
    assert routing.down_available(hole, supply, (80.0, 80.0), 6.0)      # touching is fine
    assert not routing.down_available(hole, supply, (80.01, 80.0), 6.0)
    assert routing.down_available(hole, [(86.0, 100.0, 100.0, 120.0)], (80.0, 80.0), 6.0)   # elsewhere under the board


# --- geometry and options -------------------------------------------------------------------------
def test_down_geometry_is_the_head_alone_with_the_bend_point_as_exit():
    g = design.plug_geometry((70.0, 80.0), "right", TYPES["ra"]["plug"], 6.0, 6.0, "down", 27.0)
    assert g["down"] and [p for p, _ in g["rects"]] == ["head"] and g["rects"][0][1] == (70.0, 72.0, 90.0, 88.0)
    assert g["exit"] == (80.0, 80.0) and g["lead"] == [(70.0, 80.0), (80.0, 80.0)] and g["lead_mm"] == 10.0
    assert g["measure"] == (80.0, 80.0) and g["measure_mm"] == pytest.approx(27.0)   # |10 - 20/2| + the drop
    off = {**TYPES["ra"]["plug"], "exit_offset_mm": 13.0}
    g = design.plug_geometry((70.0, 80.0), "right", off, 6.0, 6.0, "down", 27.0)
    assert g["exit"] == (83.0, 80.0) and g["measure_mm"] == pytest.approx(3.0 + 27.0)
    with pytest.raises(ValueError):
        design.plug_geometry((70.0, 80.0), "right", TYPES["ra"]["plug"], 6.0, 6.0, "up")
    assert design.EXITS == ("left", "right", "down") and design.SIDES == ("left", "right")


def test_end_options_offer_down_after_the_sides_only_where_available_and_never_for_straight_plugs():
    ctx = plug_ctx({"type": "ra"})
    it, jk = ctx["layout"]["placed"]["a"], ctx["layout"]["jacks"]["a"][0]
    cfg = routing.settings({"cables": {}}, TY)
    cfg["hole_transit_mm"] = 15.0
    yes = lambda pt, d: routing.down_available([HOLE_A], [], pt, d)
    _, opts = routing.end_options(it, jk, TY["ra"], None, cfg, 6.3, down=yes)
    assert [o["side"] for o in opts] == ["left", "right", "down"] and opts[2]["measure_mm"] == pytest.approx(DROP)
    assert [o["side"] for o in routing.end_options(it, jk, TY["ra"], None, cfg, 6.3)[1]] == ["left", "right"]   # no callable: as before
    assert [o["side"] for o in routing.end_options(it, jk, TY["ra"], "left", cfg, 6.3, down=yes)[1]] == ["left"]   # a fixed side wins
    assert [o["side"] for o in routing.end_options(it, jk, TY["ra"], "down", cfg, 6.3, down=yes)[1]] == ["down"]
    no = lambda pt, d: False
    assert [o["side"] for o in routing.end_options(it, jk, TY["ra"], "down", cfg, 6.3, down=no)[1]] == ["left", "right"]
    (st,) = routing.end_options(it, jk, TY["st"], None, cfg, 6.3, down=yes)[1]
    assert st["side"] is None and not st.get("down")                      # straight plugs never go down
    cfg["jack_height_mm"] = 20.0
    assert routing.end_options(it, jk, TY["ra"], None, cfg, 6.3, down=yes)[1][2]["measure_mm"] == pytest.approx(35.0)


# --- the search ends under the board ----------------------------------------------------------------
def small_under(holes, tight=False):
    top = routing.Grid(0.0, 0.0, 20.0, 20.0, 2.0)
    ug = routing.Grid(0.0, 0.0, 20.0, 20.0, 2.0)
    under = routing.Under(ug, holes, 15.0, 15.0, 0.9, 2, top_cost=3.0)
    under.tight = tight
    return top, under


@pytest.mark.parametrize("tight", [False, True])
def test_a_search_can_end_under_the_board_and_passes_a_hole_to_get_there(tight):
    top, under = small_under({(2, 2)}, tight)
    path = routing.astar(top, (0, 0), (8, 8, 1), lambda c: 1.0, under=under)
    assert path[0] == (0, 0) and path[-1] == (8, 8, 1)
    assert (2, 2) in path and (2, 2, 1) in path and path.index((2, 2)) + 1 == path.index((2, 2, 1))   # down through the hole cell
    assert all(len(c) == 3 for c in path[path.index((2, 2, 1)):])
    both = routing.astar(top, (8, 0, 1), (1, 7, 1), lambda c: 1.0, under=under)   # under to under: no pass at all
    assert all(len(c) == 3 for c in both) and both[0] == (8, 0, 1) and both[-1] == (1, 7, 1)


def test_connected_takes_under_states_and_an_isolated_under_goal_is_unreachable_from_the_top():
    top, under = small_under(set())                                    # no way through the deck
    assert not under.connected(top, (0, 0), (8, 8, 1))
    assert under.connected(top, (3, 3, 1), (8, 8, 1))
    assert under.connected(top, (3, 3, 1), (3, 4, 1)) and not under.connected(top, (3, 3), (3, 3, 1))
    top, under = small_under({(2, 2)})
    assert under.connected(top, (0, 0), (8, 8, 1)) and under.connected(top, (8, 8, 1), (0, 0))
    top.blocked = {(i, j) for i in range(top.nx) for j in range(top.ny)} - {(0, 0)}
    assert not under.connected(top, (0, 0), (8, 8, 1))                 # the top is closed round the start: the hole is out of reach


def test_the_under_goal_heuristic_is_admissible_so_the_tight_search_finds_the_same_cost():
    for tight in (False, True):
        top, under = small_under({(2, 2), (7, 1)}, tight)
        path = routing.astar(top, (0, 0), (9, 9, 1), lambda c: 1.0, under=under)
        costs = routing.path_cost(top, path, under)
        if tight:
            assert costs == pytest.approx(ref)
        else:
            ref = costs
    top, under = small_under({(2, 2)}, True)
    assert routing.tight_heuristic(under, (8, 8, 1), 2.0)((8, 8, 1)) == 0.0
    h = routing.tight_heuristic(under, (8, 8, 1), 2.0)
    assert h((0, 0)) >= under.pass_floor(0) and h((0, 0)) > h((0, 0, 1))


# --- signal cables ----------------------------------------------------------------------------------
def test_both_ends_down_run_under_the_board_with_a_hand_computed_length():
    ctx, c = signal([HOLE_A, HOLE_B])
    assert (c["exit_a"], c["exit_b"], c["status"]) == ("down", "down", "routed") and ctx["errors"] == []
    assert c["under_board"] and c["holes_used"] == 0 and c["edges_used"] == 0   # the plug ends are no hole passes
    under = math.hypot(110.0, 60.0)                                             # bend (80, 80) -> bend (190, 140), a straight run
    assert c["under_mm"] == pytest.approx(under, abs=0.01)
    assert c["min_mm"] == pytest.approx(2 * DROP + under, abs=0.01)
    assert [s["layer"] for s in c["stretches"]] == ["under"]
    assert c["path"] == [(70.0, 80.0), (80.0, 80.0), (190.0, 140.0), (200.0, 140.0)]
    assert ctx["routing"]["heads"] == [{"cable": "S1", "rects": [("head", (70.0, 72.0, 90.0, 88.0))], "down": (80.0, 80.0)},
                                       {"cable": "S1", "rects": [("head", (180.0, 132.0, 200.0, 148.0))], "down": (190.0, 140.0)}]


def test_one_down_end_adds_its_measure_to_the_top_and_under_runs_and_one_hole_pass():
    ctx, c = signal([HOLE_A, HOLE_B], cables={"overrides": {"S1": {"exit_b": "right"}}})
    assert (c["exit_a"], c["exit_b"]) == ("down", "right") and c["status"] == "routed"
    assert c["under_board"] and c["holes_used"] == 1 and [s["layer"] for s in c["stretches"]] == ["under", "top"]
    (hp,) = c["hole_points"]
    assert HOLE_B[0] <= hp[0] <= HOLE_B[2] and HOLE_B[1] <= hp[1] <= HOLE_B[3]
    assert c["under_mm"] == pytest.approx(math.hypot(hp[0] - 80.0, hp[1] - 80.0), abs=0.01)     # from the bend point under the board
    top = c["stretches"][1]["points"][:-2]                                       # (the last two points are the plug's lead)
    top_mm = sum(math.hypot(q[0] - p[0], q[1] - p[1]) for p, q in zip(top, top[1:]))
    assert top[0] == hp and top[-1] == (190.0, 126.0)                            # the hole cell up to B's right exit
    # the side end measures 8 + 6 = 14 (reach + run); the down end 27; one pass through the deck 15 (the top polyline starts at the hole cell)
    assert c["min_mm"] == pytest.approx(DROP + 14.0 + c["under_mm"] + top_mm + 15.0, abs=0.01)


def test_the_choice_prefers_down_even_when_the_side_route_is_shorter_and_takes_a_side_without_a_hole():
    ctx, plain = signal([])
    assert (plain["exit_a"], plain["exit_b"]) == ("right", "right")           # no hole: sides, as before
    ctx, down = signal([HOLE_A, HOLE_B], cables={"overrides": {"S1": {"exit_b": "right"}}})
    assert down["exit_a"] == "down" and down["min_mm"] > plain["min_mm"]      # always down where available, even if longer
    ctx, far = signal([HOLE_B], cables={"overrides": {"S1": {"exit_b": "right"}}})   # no hole at A: that end keeps a side
    assert far["exit_a"] in ("left", "right") and far["exit_b"] == "right"


def test_an_override_down_is_honoured_a_fixed_side_beats_down_and_an_unavailable_down_is_reported():
    ctx, fixed = signal([HOLE_A, HOLE_B], cables={"overrides": {"S1": {"exit_a": "left", "exit_b": "right"}}})
    assert (fixed["exit_a"], fixed["exit_b"]) == ("left", "right")
    ctx, c = signal([HOLE_A, HOLE_B], cables={"overrides": {"S1": {"exit_a": "down"}}})
    assert c["exit_a"] == "down" and ctx["errors"] == [] and not any("S1" in w for w in ctx["warnings"])
    ctx, c = signal([], cables={"overrides": {"S1": {"exit_a": "down"}}})     # no hole anywhere
    assert c["exit_a"] in ("left", "right") and c["status"] == "routed"       # the automatic choice
    assert any("S1 exit_a is down, but the plug at a.out cannot point down" in w for w in ctx["warnings"]) and ctx["errors"] == []
    ctx, c = signal([], cables={"overrides": {"S1": {"exit_b": "down"}}}, validation={"strict_routing": True})
    assert any("S1 exit_b is down, but the plug at b.in cannot point down" in e for e in ctx["errors"])
    assert not any("unknown" in e for e in ctx["errors"])                      # `down` is a known exit


def test_an_under_board_supply_under_the_hole_takes_the_down_option_away():
    ctx, c = signal([HOLE_A, HOLE_B], under_supply=(60, 60, 30, 40))          # the supply (60..90 x 60..100) hangs under bend A
    assert c["exit_a"] in ("left", "right") and c["exit_b"] == "down"
    ctx, c = signal([HOLE_A, HOLE_B], under_supply=(60, 100, 30, 40))         # clear of both bends
    assert (c["exit_a"], c["exit_b"]) == ("down", "down")


def test_jack_height_is_a_setting_with_a_default_of_12_and_changes_the_length():
    assert routing.settings({"cables": {}})["jack_height_mm"] == 12.0
    assert routing.settings({"cables": {"jack_height_mm": 20}})["jack_height_mm"] == 20
    assert routing.settings({"cables": {"jack_height_mm": "tall"}})["jack_height_mm"] == 12.0      # reported, never used
    for bad in (-1, "tall", True):
        assert routing.validate_project_types({"cables": {"jack_height_mm": bad}}, TY)
    assert routing.validate_project_types({"cables": {"jack_height_mm": 0}}, TY) == []
    _, base = signal([HOLE_A, HOLE_B])
    _, tall = signal([HOLE_A, HOLE_B], cables={"jack_height_mm": 20})
    assert tall["min_mm"] == pytest.approx(base["min_mm"] + 2 * 8.0, abs=0.01)
    ctx, _ = signal([HOLE_A, HOLE_B], cables={"jack_height_mm": -3})
    assert any("jack_height_mm" in e for e in ctx["errors"])


def test_cables_stay_on_top_when_under_board_is_off_and_no_down_option_exists():
    ctx, c = signal([HOLE_A, HOLE_B], cables={"under_board": False})
    assert (c["exit_a"], c["exit_b"]) == ("right", "right") and not c["under_board"]


# --- power cables -----------------------------------------------------------------------------------
def power(holes=(HOLE_PW,), hops=(("psu1.F1", "a.power"),), cables=None, **kw):
    ctx = pw_ctx(holes=holes, hops=hops, cables=cables, **kw)
    routing.route_project(ctx, {}, cable_types=TY)
    return ctx, {c["id"]: c for c in ctx["cable_list"] if c["kind"] == "power"}


def test_a_power_plug_over_a_hole_points_down_and_its_cable_stays_under_the_board():
    ctx, ps = power()
    (c,) = ps.values()
    assert c["exit_b"] == "down" and c["status"] == "routed" and c["under_board"] and c["holes_used"] == 0 and c["top_mm"] == 0
    # from the port's under start (112, 145) straight to the bend point (45, 55); the plug measures |5 - 10/2| + 12 + 15
    run = math.hypot(112 - 45, 145 - 55)
    assert c["under_mm"] == pytest.approx(run, abs=0.01) and c["min_mm"] == pytest.approx(DROP + run, abs=0.01)
    assert [s["layer"] for s in c["stretches"]] == ["under"] and c["stretches"][0]["points"][-2:] == [(45.0, 55.0), (45.0, 60.0)]   # + the lead to the jack
    ctx2, ps2 = power(holes=())
    assert list(ps2.values())[0]["exit_b"] in ("left", "right")               # no hole: the sides, as before
    ctx3, ps3 = power(holes=(HOLE_PW,), cables={"overrides": {"P1": {"exit_b": "right"}}})
    assert list(ps3.values())[0]["exit_b"] == "right"                         # the owner's side beats down


def test_a_power_override_down_that_no_hole_allows_is_reported_and_falls_back():
    ctx, ps = power(holes=(), cables={"overrides": {"P1": {"exit_b": "down"}}})
    assert list(ps.values())[0]["exit_b"] in ("left", "right")
    assert any("P1 exit_b is down, but the plug at a.power cannot point down" in w for w in ctx["warnings"]) and ctx["errors"] == []
    strict = pw_ctx(holes=(), cables={"overrides": {"P1": {"exit_b": "down"}}})
    strict["project"]["validation"] = {"strict_routing": True}
    routing.route_project(strict, {}, cable_types=TY)
    assert any("P1 exit_b is down" in e for e in strict["errors"])


def test_a_serial_chain_goes_through_a_down_plug_under_the_board_at_both_ends_of_a_hop():
    hops = (("psu1.F1", "d.power"), ("d.power", "a.power"))
    ctx = pw_ctx(holes=(HOLE_PW, HOLE_D), hops=hops, d_pedal=True)
    ctx["cables"]["power"] = [{"from": f, "to": t, "cable": "C1", "style": "serial"} for f, t in hops]
    routing.route_project(ctx, {}, cable_types=TY)
    p1, p2 = (c for c in ctx["cable_list"] if c["kind"] == "power")
    assert (p1["exit_b"], p2["exit_b"]) == ("down", "down") and p1["status"] == p2["status"] == "routed"
    # P1 ends down at D (bend (105, 55)), P2 starts there (under) and ends down at A (bend (45, 55)): no pass, nothing on top
    assert p1["holes_used"] == p2["holes_used"] == 0 and p1["top_mm"] == p2["top_mm"] == 0
    assert p2["under_mm"] == pytest.approx(60.0, abs=0.01) and p2["min_mm"] == pytest.approx(2 * DROP + 60.0, abs=0.01)
    assert p1["min_mm"] == pytest.approx(DROP + math.hypot(112 - 105, 145 - 55), abs=0.01)
    (cab,) = ctx["power_cable_summary"]
    assert cab["min_mm"] == pytest.approx(p1["min_mm"] + p2["min_mm"]) and cab["status"] == "routed" and cab["plugs"] == 3


def test_a_down_plug_at_a_pedal_source_comes_up_through_a_hole_for_a_top_target():
    hops = (("psu1.F1", "d.power"), ("d.power", "a.power"))
    ctx = pw_ctx(holes=(HOLE_D, (28.5, 38.5, 40.5, 48.5)), hops=hops, d_pedal=True)
    routing.route_project(ctx, {}, cable_types=TY)
    p1, p2 = (c for c in ctx["cable_list"] if c["kind"] == "power")
    assert p1["exit_b"] == "down" and p2["exit_b"] in ("left", "right") and p2["status"] == "routed"
    assert p2["holes_used"] == 1 and [s["layer"] for s in p2["stretches"]] == ["under", "top"]   # starts under at D's bend, up at A's hole
    assert p2["stretches"][0]["points"][:2] == [(105.0, 60.0), (105.0, 55.0)]       # the lead from the jack, then D's bend point


# --- drawing and README -----------------------------------------------------------------------------
def test_the_pictures_mark_a_down_plug_and_the_key_says_so():
    ctx, c = signal([HOLE_A, HOLE_B])
    svg = svgdraw.render(ctx, {})
    assert svg.count('class="plug-down"') == 2 and svg.count('class="key-down"') == 1 and "plug points down into a hole" in svg
    plain_ctx, _ = signal([])
    plain = svgdraw.render(plain_ctx, {})
    assert 'class="plug-down"' not in plain and "plug points down into a hole" not in plain
    pctx, ps = power()
    pic = svgdraw.render_power(pctx, {})
    assert pic.count('class="plug-down"') == 1 and pic.count('class="key-down"') == 1 and "plug points down into a hole" in pic


def test_the_readme_shows_down_in_the_exits_column_and_explains_it():
    ctx, c = signal([HOLE_A, HOLE_B])
    md = "\n".join(build.routing_section(ctx))
    assert "| S1 | signal | - | a.out | b.in | ra | down / down |" in md
    assert "point straight down into a board hole" in md and "cables.jack_height_mm" in md and "12 mm" in md
    ctx, _ = signal([])
    assert "point straight down" not in "\n".join(build.routing_section(ctx))
    ctx, ps = power()
    assert "| P1 | power |" in "\n".join(build.routing_section(ctx)) and "| - / down |" in "\n".join(build.routing_section(ctx))
