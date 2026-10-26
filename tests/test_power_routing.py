"""Power cable routing (routing.route_power) and the nearest-hole estimate (power.hop_estimate / chain_order / assign, the
layout surrogate's power term). Hand-computed cases on the small boards of test_routing; all lengths in mm.

Board 0..300 x 0..200; pedal A (20..70 x 60..160) has its power jack at (45, 60) facing top: the DC head is (40, 50, 50, 60),
the cable axis y = 55, the exit 8.5 mm to the left (36.5, 55) or right (53.5, 55), and the plug measures 8.5 mm (0 + 5 + 3.5).
The supply PSU (100..160 x 150..180) hangs under the board; F1 (x 112) and F2 (x 148) face top, so a cable starts under the
board at (112, 145) / (148, 145) (half a 10 mm plug head in front of the jack). The cells are 2 mm, centres at odd numbers."""
import math
import random
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import design  # noqa: E402
import layout  # noqa: E402
import power  # noqa: E402
import routing  # noqa: E402
import svgdraw  # noqa: E402
from test_layout import model as layout_model, ped, at  # noqa: E402
from test_routing import DC, TYPES, mm_item, power_ctx  # noqa: E402

TY = {**TYPES, **DC}
MEASURE = 8.5
HOLE_A = (28.5, 38.5, 40.5, 48.5)        # above A's power plug
HOLE_FAR = (98.5, 38.5, 110.5, 48.5)


def pw_ctx(holes=(HOLE_A,), hops=(("psu1.F1", "a.power"),), cables=None, power_routing=None, extra=(), d_pedal=False):
    ctx = power_ctx(list(extra))
    lay, project = ctx["layout"], ctx["project"]
    project["cables"].update(cables or {})
    if power_routing is not None:
        project["power_routing"] = power_routing
    psu = mm_item("i-psu", "PSU", 100, 150, 60, 30)
    lay.update(holes=list(holes), inst_item={"psu1": psu}, inst_placement={"psu1": "under"})
    lay["jacks"]["sup1"] = [{"id": "F1", "label": "F1", "function": "power_out", "x": 0.2, "y": 0.0, "facing": "top"},
                            {"id": "F2", "label": "F2", "function": "power_out", "x": 0.8, "y": 0.0, "facing": "top"}]
    if d_pedal:   # a second pedal with its power jack at (105, 60)
        d = mm_item("i-d", "D", 80, 60, 50, 100)
        lay["placed"]["d"] = d
        lay["obstacles"].append(d)
        lay["jacks"]["d"] = [{"id": "power", "label": "9V", "function": "power", "x": 0.5, "y": 0.0, "facing": "top"}]
    ctx["supplies"] = [{"inst": {"id": "psu1", "supply": "sup1"}, "sup": {"id": "sup1"}, "rows": []}]
    ctx["cables"] = {"power": [{"from": f, "to": t} for f, t in hops]}
    return ctx


def route(ctx):
    routing.route_project(ctx, {}, cable_types=TY)
    return {c["id"]: c for c in ctx["cable_list"] if c["kind"] == "power"}


def inside(pt, r):
    return r[0] <= pt[0] <= r[2] and r[1] <= pt[1] <= r[3]


def test_an_under_board_supply_goes_under_to_the_hole_by_the_jack_and_up_for_a_short_top_leg():
    ctx = pw_ctx()
    (c,) = route(ctx).values()
    assert c["status"] == "routed" and c["holes_used"] == 1 and c["edges_used"] == 0 and c["under_board"]
    assert [s["layer"] for s in c["stretches"]] == ["under", "top"] and ctx["errors"] == []
    (hp,) = c["hole_points"]
    assert inside(hp, HOLE_A)
    under = next(s["points"] for s in c["stretches"] if s["layer"] == "under")
    assert under[0] == pytest.approx((112.0, 145.0)) and under[-1] == hp and len(under) == 2     # one straight under leg
    assert c["under_mm"] == pytest.approx(math.hypot(hp[0] - 112.0, hp[1] - 145.0))
    assert 0 < c["top_mm"] < 25
    # min length = the plug at the pedal (8.5) + under + top + one hole pass (the fallback transit 15); none at the supply end
    assert c["min_mm"] == pytest.approx(MEASURE + c["under_mm"] + c["top_mm"] + 15.0)
    assert c["estimate_mm"] is None and ctx["routing"]["power"]["hole_transit_mm"] == 15.0


def test_a_hole_a_pedal_covers_is_skipped_for_the_next_one():
    cover = mm_item("i-c", "C", 26, 30, 28, 17)          # over the whole usable part of HOLE_A (y 30..47), clear of the plug
    ctx = pw_ctx(holes=(HOLE_A, HOLE_FAR), extra=[cover])
    (c,) = route(ctx).values()
    assert c["status"] == "routed" and c["holes_used"] == 1
    assert inside(c["hole_points"][0], HOLE_FAR) and not inside(c["hole_points"][0], HOLE_A)
    assert not any(inside(ctx["routing"]["grid"].centre(h), HOLE_A) for h in ctx["routing"]["power"]["hole_cells"])
    assert c["top_mm"] > 40                              # the longer way up: about 50 mm on top
    free = pw_ctx(holes=(HOLE_A, HOLE_FAR))
    (f,) = route(free).values()
    assert inside(f["hole_points"][0], HOLE_A) and f["min_mm"] < c["min_mm"]


def test_no_hole_uses_the_allowed_back_edge_not_the_nearer_avoided_left_edge():
    ctx = pw_ctx(holes=())
    (c,) = route(ctx).values()
    et = ctx["routing"]["power"]["edge_transit_mm"]
    assert et == 30.0 and ctx["routing"]["power"]["edge_transit_source"] == "twice the hole transit"
    # the left edge is the shorter way under (about 143 against 160 mm) but "avoid" costs 100 mm more in the search
    assert c["status"] == "routed" and c["edge_sides"] == ["back"] and c["holes_used"] == 0 and c["edges_used"] == 1
    assert c["under_board"] and len(c["edge_points"]) == 1 and c["edge_points"][0][1] < 3
    assert c["min_mm"] == pytest.approx(MEASURE + c["under_mm"] + c["top_mm"] + 30.0)
    assert 50 < c["top_mm"] < 62                         # from the back margin down to the plug exit (y 55)


def test_an_edge_mode_allowed_avoided_or_forbidden_decides():
    left = pw_ctx(holes=(), power_routing={"edges": {"left": "allowed"}})
    (c,) = route(left).values()
    assert c["edge_sides"] == ["left"]                   # now the shorter way wins
    avoided = pw_ctx(holes=(), power_routing={"edges": {"back": "forbidden"}})
    (c,) = route(avoided).values()
    assert c["status"] == "routed" and c["edge_sides"] == ["left"]    # an avoided edge is used when nothing better exists
    none = pw_ctx(holes=(), power_routing={"edges": {"back": "forbidden", "left": "forbidden", "right": "forbidden"}})
    (c,) = route(none).values()
    assert c["status"].startswith("unroutable") and c["min_mm"] is None    # the front is forbidden by default: never used
    assert any("P1" in w and "no free path" in w for w in none["warnings"])


def test_edge_transit_comes_from_the_project_then_the_board_data_then_twice_the_hole_transit():
    base = pw_ctx(holes=())
    (b,) = route(base).values()
    board = pw_ctx(holes=())
    board["layout"]["edge_transit_mm"] = 20.0
    (c,) = route(board).values()
    assert board["routing"]["power"]["edge_transit_source"] == "the board data"
    assert c["min_mm"] == pytest.approx(b["min_mm"] - 10.0)
    both = pw_ctx(holes=(), power_routing={"edge_transit_mm": 45.0})
    both["layout"]["edge_transit_mm"] = 20.0
    (d,) = route(both).values()
    assert both["routing"]["power"]["edge_transit_source"] == "power_routing.edge_transit_mm"
    assert d["min_mm"] == pytest.approx(b["min_mm"] + 15.0)


def test_a_daisy_chain_hop_between_close_pedals_stays_on_top():
    ctx = pw_ctx(holes=(HOLE_A,), hops=(("a.power", "d.power"),), d_pedal=True)   # no hole by D: down and up again costs more
    (c,) = route(ctx).values()
    assert c["status"] == "routed" and not c["under_board"] and c["holes_used"] == 0 and c["edges_used"] == 0
    (top,) = c["stretches"]
    assert top["layer"] == "top" and c["under_mm"] == 0
    # both plugs measure 8.5; the rest is the smoothed polyline between the two plug exits (y 55; 43 .. 60 mm apart)
    assert c["min_mm"] == pytest.approx(2 * MEASURE + c["top_mm"]) and 40 < c["top_mm"] < 62
    assert c["top_mm"] == pytest.approx(routing.polyline_length(c["path"][2:-2]), abs=1e-6)


def test_a_hop_goes_under_when_the_top_way_is_dearer_than_two_passes():
    # a wall between the pedals' exits on top (a tall pedal), holes either side: top x 3 round it costs more than 2 passes
    wall = mm_item("i-w", "W", 70, 0, 8, 200)
    ctx = pw_ctx(holes=(HOLE_A, HOLE_FAR), hops=(("a.power", "d.power"),), d_pedal=True, extra=[wall])
    (c,) = route(ctx).values()
    assert c["status"] == "routed" and c["under_board"] and c["holes_used"] == 2
    assert [s["layer"] for s in c["stretches"]] == ["top", "under", "top"] and c["min_mm"] == pytest.approx(
        2 * MEASURE + c["top_mm"] + c["under_mm"] + 2 * 15.0)


NO_EDGES = {"edges": {"back": "forbidden", "left": "forbidden", "right": "forbidden"}}


def test_power_stacking_is_its_own_limit_per_layer():
    cell = (28.5, 18.5, 29.5, 19.5)                      # a one-cell hole (centre (29, 19)): both cables must pass through it
    hops = (("psu1.F1", "a.power"), ("psu1.F2", "d.power"))
    ok = pw_ctx(holes=(cell,), hops=hops, d_pedal=True, power_routing=NO_EDGES)
    routed = route(ok)
    assert all(c["status"] == "routed" and c["holes_used"] == 1 for c in routed.values())   # default: 2 cables per cell
    tight = pw_ctx(holes=(cell,), hops=hops, d_pedal=True, power_routing={**NO_EDGES, "max_stack": 1})
    r = route(tight)
    assert any("over the stacking limit" in c["status"] for c in r.values())
    assert any("beyond the limit of 1 stacked power cables" in w for w in tight["warnings"])
    # the patch cables' limit (cables.max_stack) does not count power cables: 1 for them, 2 for the power cables
    sep = pw_ctx(holes=(cell,), hops=hops, d_pedal=True, cables={"max_stack": 1}, power_routing={**NO_EDGES, "max_stack": 2})
    r = route(sep)
    assert all(c["status"] == "routed" for c in r.values()) and not any("stacking" in w for w in sep["warnings"])
    assert sep["routing"]["power"]["settings"]["max_stack"] == 2 and not sep["routing"]["overflow"]


def test_a_long_top_run_is_reported_and_unrouted_without_a_power_type():
    ctx = pw_ctx(holes=((240.5, 38.5, 250.5, 48.5),), power_routing=NO_EDGES)
    ctx["layout"]["placed"]["a"] = mm_item("i-a", "A", 20, 140, 50, 100)   # the only hole is 200 mm from the jack
    ctx["layout"]["obstacles"][0] = ctx["layout"]["placed"]["a"]
    (c,) = route(ctx).values()
    assert c["top_mm"] > routing.POWER_TOP_WARN_MM
    assert any("P1" in w and "mm on top of the board" in w for w in ctx["warnings"])
    plain = pw_ctx()
    plain["project"]["cables"].pop("power_type")
    (p,) = route(plain).values()
    assert p["status"].startswith("not routed (no power cable type") and p["min_mm"] is None


def test_power_routing_settings_and_validation():
    s = routing.power_settings({"cables": {"max_stack": 3}, "power_routing": {"edges": {"front": "allowed"}, "top_cost": 2}})
    assert s["edges"] == {"front": "allowed", "left": "avoid", "right": "avoid", "back": "allowed"}
    assert s["top_cost"] == 2 and s["avoid_penalty"] == 100.0 and s["max_stack"] == 3 and s["edge_transit_mm"] is None
    assert routing.power_settings({})["edges"]["front"] == "forbidden"
    assert routing.validate_power_routing({}) == []
    bad = routing.validate_power_routing({"power_routing": {"edges": {"front": "sometimes", "top": "allowed"}, "top_cost": 0,
                                                           "max_stack": 0, "colour": 1}})
    assert len(bad) == 5 and any("unknown mode 'sometimes'" in e for e in bad) and any("unknown side 'top'" in e for e in bad)
    ctx = pw_ctx(power_routing={"edges": {"back": "never"}})
    route(ctx)
    assert any("unknown mode 'never'" in e for e in ctx["errors"])


def test_the_svg_draws_power_cables_thin_with_under_stretches_dashed_and_marks_the_passes():
    ctx = pw_ctx(holes=())
    (c,) = route(ctx).values()
    out = "\n".join(svgdraw.power_cables(ctx["cable_list"]))
    assert out.count('class="power-under"') == 1 and out.count('class="power-cable"') == 1 and out.count('class="power-edge"') == 1
    assert 'stroke-dasharray="3 2"' in out and svgdraw.POWER_WIDTH < 2.0
    assert [x for x in svgdraw.power_labels(ctx["cable_list"]) if ">P1<" in x]
    kinds = [k for k, _ in svgdraw.key_entries(ctx, ctx["cable_list"], 2)]
    assert {"power", "power_under", "power_edge"} <= set(kinds) and "power_hole" not in kinds


# --- the estimate --------------------------------------------------------------------------------------
CFG = {"top_cost": 3.0, "transit_mm": 15.0}


def test_hop_estimate_cases():
    assert power.hop_estimate((0, 0), (30, 40), True, [], CFG) == 70 and power.hop_estimate((0, 0), (30, 40), False, None, CFG) == 70
    # source under: Manhattan to the hole by the target (80) + the pass (15) + 3 x the 10 mm straight leg
    assert power.hop_estimate((0, 0), (50, 40), True, [(40, 40)], CFG) == pytest.approx(80 + 15 + 30)
    # on top, close together: the top way (3 x 10) beats going down and up
    assert power.hop_estimate((0, 0), (10, 0), False, [(500, 500)], CFG) == pytest.approx(30)
    # on top, far apart with a hole by each end: 3 x 5 + 15 + 190 under + 15 + 3 x 5 = 250 against 3 x 200 on top
    holes = [(5, 0), (195, 0)]
    assert power.hop_estimate((0, 0), (200, 0), False, holes, CFG) == pytest.approx(250)
    # no usable hole near the target: Manhattan
    assert power.hop_estimate((0, 0), (200, 0), True, holes, CFG, near=lambda p: None) == 200


def test_nearest_usable_skips_the_points_a_pedal_covers_and_the_index_agrees():
    sample = [(10.0, 0.0), (20.0, 0.0), (90.0, 0.0)]
    assert power.nearest_usable((12, 0), sample) == (10.0, 0.0)
    assert power.nearest_usable((12, 0), sample, [(5, -5, 15, 5)]) == (20.0, 0.0)
    assert power.nearest_usable((12, 0), sample, [(5, -5, 25, 5)]) == (90.0, 0.0)
    assert power.nearest_usable((12, 0), sample, [(0, -5, 100, 5)]) is None
    rnd = random.Random(3)
    big = power.hole_sample([(0, 0, 80, 40), (120, 10, 200, 60)])
    index = power.HoleIndex(big)
    for _ in range(60):
        blocked = [(a, b, a + rnd.uniform(5, 50), b + rnd.uniform(5, 50)) for a, b in ((rnd.uniform(0, 200), rnd.uniform(0, 60)) for _ in range(4))]
        pt = (rnd.uniform(-20, 220), rnd.uniform(-20, 80))
        want, got = power.nearest_usable(pt, big, blocked), index.nearest(pt, blocked)
        assert (got is None) == (want is None)
        if want:
            assert math.hypot(got[0] - pt[0], got[1] - pt[1]) == pytest.approx(math.hypot(want[0] - pt[0], want[1] - pt[1]))


def test_hole_sample_is_a_centred_grid_in_each_rectangle():
    pts = power.hole_sample([(0, 0, 13, 5)], spacing=6.0)       # 2 columns (13 // 6), 1 row: centred in 13 x 5
    assert pts == [(3.5, 2.5), (9.5, 2.5)]
    assert power.hole_sample([(10, 10, 11, 11)]) == [(10.5, 10.5)] and power.hole_sample(None) == []


def test_chain_order_with_holes_goes_to_the_pedal_by_the_hole_first():
    pts = {"x": (10, 0), "y": (20, 0), "z": (95, 0)}
    holes = [(100, 0)]
    hop = lambda a, b, under: power.hop_estimate(a, b, under, holes, CFG)
    # plain Manhattan: x, y, z (95). From an under-board port at the origin the one hole is at x = 100: z first
    # (100 + 15 + 3 x 5 = 130), then z -> y on top (3 x 75 = 225), y -> x (3 x 10 = 30)
    assert power.chain_order((0, 0), ["x", "y", "z"], pts) == (95, ["x", "y", "z"])
    length, order = power.chain_order((0, 0), ["x", "y", "z"], pts, hop, True)
    assert order == ["z", "y", "x"] and length == pytest.approx(130 + 225 + 30)
    # a chain that starts on top (an on-board supply): x 30, x -> y 30, y -> z 225 on top (down and up costs 285)
    assert power.chain_order((0, 0), ["x", "y", "z"], pts, hop, False) == (pytest.approx(285), ["x", "y", "z"])


def test_assign_orders_the_daisy_chain_for_the_estimate_with_holes():
    pedals = {p: {"digital": False, "clocked_noise": False, "tags": [],
                  "power_consumption": {"current_ma": 10, "min_voltage_v": 9, "max_voltage_v": 9, "polarity": "center_negative"}}
              for p in "xyz"}
    sup = {"polarity": "center_negative", "outputs": [{"port": "O", "options": [{"voltage_v": 9, "max_ma": 500}]}]}
    insts = [{"id": "s", "supply": "sup", "sup": sup}]
    pts, ports = {"x": (10, 0), "y": (20, 0), "z": (95, 0)}, {("s", "O"): (0, 0)}
    plain = power.assign(["x", "y", "z"], pedals, insts, {}, pts, ports)
    assert plain["supplies"][0]["outputs"][0]["pedals"] == ["x", "y", "z"] and plain["length_mm"] == 95
    holed = power.assign(["x", "y", "z"], pedals, insts, {}, pts, ports, holes=[(100, 0)], cfg=CFG)
    assert holed["supplies"][0]["outputs"][0]["pedals"] == ["z", "y", "x"] and holed["length_mm"] == pytest.approx(385)
    on_top = power.assign(["x", "y", "z"], pedals, [{**insts[0], "under": False}], {}, pts, ports, holes=[(100, 0)], cfg=CFG)
    assert on_top["supplies"][0]["outputs"][0]["pedals"] == ["x", "y", "z"] and on_top["length_mm"] == pytest.approx(285)


def test_the_surrogate_power_term_skips_hole_points_a_candidate_pedal_covers():
    m = layout_model([ped("T A", 0), ped("T B", 135)])          # a: 50.8 x 101.6, b the same
    sample = [(30.0, 10.0), (120.0, 10.0)]
    m.power_setup = {"sample": sample, "index": power.HoleIndex(sample), "cfg": CFG, "radius": 1.6}
    port = (100.0, 100.0)
    m.set_wiring([(port, ["a"], True)])

    def raw(state):
        return m.score(state, detail=True)[1]["terms"]["power"][0]

    def expect(state, hole):
        ms = m._geom[(0, state[0][2])]["power"]["measure"]
        here = (ms[0] + state[0][0], ms[1] + state[0][1])
        return abs(port[0] - hole[0]) + abs(port[1] - hole[1]) + 15 + 3 * math.hypot(hole[0] - here[0], hole[1] - here[1])

    over = at((25.4, 50.8, 0), (150, 50.8, 0))                    # a (0..50.8 x 0..101.6) covers (30, 10): the far point is used
    assert raw(over) == pytest.approx(expect(over, (120.0, 10.0)))
    clear = at((60.0, 50.8, 0), (200, 50.8, 0))                   # a (34.6..85.4) leaves (30, 10) free and nearest
    assert raw(clear) == pytest.approx(expect(clear, (30.0, 10.0)))
    m.power_setup = None                                          # no holes known: Manhattan between the measure points
    ms = m._geom[(0, 0)]["power"]["measure"]
    assert raw(clear) == pytest.approx(abs(port[0] - ms[0] - 60.0) + abs(port[1] - ms[1] - 50.8))
