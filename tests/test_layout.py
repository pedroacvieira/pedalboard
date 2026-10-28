"""Layout model and surrogate score (scripts/layout.py) and the power assignment (scripts/power.py).
Hand-computed cases on small synthetic boards; all lengths in mm (45 px/in -> 1 px = 25.4/45 mm)."""
import copy
import functools
import json
import math
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import build  # noqa: E402
import design  # noqa: E402
import footswitches  # noqa: E402
import jacks  # noqa: E402
import layout  # noqa: E402
import power  # noqa: E402
import routing  # noqa: E402
from common import load_cable_types, load_catalog, load_json  # noqa: E402
from test_check import canvas, pedal_jacks  # noqa: E402

GIG = ROOT / "projects" / "guitar-gig"
PEDALS = {
    "a": {"brand": "T", "name": "A", "playground_title": "T A", "tags": ["gain", "overdrive"]},
    "b": {"brand": "T", "name": "B", "playground_title": "T B", "tags": ["modulation"]},
    "c": {"brand": "T", "name": "C", "playground_title": "T C", "tags": ["tuner"]},
}
JACKS = {k: pedal_jacks() for k in PEDALS}   # in: left edge middle, out: right edge middle, power: top middle
TYPES = {"t": {"role": "patch", "diameter_mm": 4.0, "plug": {"style": "straight", "head_depth_mm": 10.0, "head_width_mm": 8.0}}}
BOARD = ("Board", 0, 0, 10.0, 5.0, 0, "pedalboard")   # 254 x 127 mm


def ped(title, left_px, top_px=0, rot=0, w=2.0, h=4.0):
    return (title, left_px, top_px, w, h, rot, "pedal")


def model(specs, chain=("a", "b"), fs=None, project_extra=None, types=TYPES, outlines=None):
    proj = {"signal_chain": list(chain), "cables": {"type": "t"}, "jacks": {}, **(project_extra or {})}
    items = design.parse_canvas(canvas(BOARD, *specs))
    return layout.Model(proj, items, PEDALS, {}, JACKS, fs or {}, types, outlines=outlines)


def at(*centres):
    return [(x, y, r) for x, y, r in centres]


# --- feasibility ----------------------------------------------------------------------------------
def test_feasibility_board_overlap_touching_pins_rotation_and_max_move():
    m = model([ped("T A", 0), ped("T B", 135)])          # a: 50.8 x 101.6 at (25.4, 50.8)
    assert m.owner[0] == pytest.approx((25.4, 50.8, 0)) and m.allowed[0] == [0, 90, 270]
    assert m.feasible(at((25.4, 50.8, 0), (76.2, 50.8, 0)))          # touching: allowed
    assert not m.feasible(at((25.4, 50.8, 0), (75.0, 50.8, 0)))      # 1.2 mm overlap > TOL 0.6
    assert m.feasible(at((25.4, 50.8, 0), (75.7, 50.8, 0)))          # 0.5 mm overlap: within TOL
    assert not m.feasible(at((24.0, 50.8, 0), (150, 50.8, 0)))       # 1.4 mm off the left edge
    assert not m.feasible(at((25.4, 50.8, 180), (150, 50.8, 0)))     # 180 is never allowed
    assert m.feasible(at((50.8, 76.2, 90), (150, 50.8, 0)))          # rotated: 101.6 x 50.8 footprint inside
    m.pins = {"a"}
    assert not m.feasible(at((30.0, 50.8, 0), (150, 50.8, 0)))
    m.pins, m.max_move = set(), 10.0
    assert m.feasible(at((35.0, 50.8, 0), (101.6, 50.8, 0)))         # a moved 9.6 mm
    assert not m.feasible(at((40.0, 50.8, 0), (101.6, 50.8, 0)))     # 14.6 mm > 10 (+0.5 snapping slack)


# --- clearance ------------------------------------------------------------------------------------
def test_clearance_of_two_facing_straight_plugs():
    """Gap 5.6 mm between a.out and b.in: each 10 mm head (+4 mm cable run) reaches 4.4 mm into the other pedal."""
    m = model([ped("T A", 0), ped("T B", 135)])
    state = at((25.4, 50.8, 0), (25.4 + 50.8 + 5.6, 50.8, 0))
    total, det = m.score(state, margin=0, detail=True)
    hits = {(b["jack"], b["obstacle"], b["part"]): b["depth_mm"] for b in det["blocked"]}
    assert hits == pytest.approx({("a.out", "T B", "head"): 4.4, ("b.in", "T A", "head"): 4.4})
    # clearance = 2 x (50 x penetration 4.4 + 100 per hit); penetration = smaller overlap side (4.4 of 4.4 x 8)
    assert det["terms"]["clearance"] == pytest.approx((2 * 4.4, 2 * (50 * 4.4 + 100)))
    # with the 2 mm margin the cable run (4 x 4, grown to 8 x 8, all inside the other pedal) penetrates 8 mm:
    # 50 x 4.4 real + 10 x the extra 3.6 + 100 per end
    _, det2 = m.score(state, detail=True)
    assert det2["terms"]["clearance"] == pytest.approx((2 * 8.0, 2 * (50 * 4.4 + 10 * 3.6 + 100)))


def test_clearance_is_measured_against_the_outline():
    """The facing-plugs case with a shape: a.out reaches 4.4 mm into b's box, b.in 4.4 mm into a's box."""
    state = at((25.4, 50.8, 0), (25.4 + 50.8 + 5.6, 50.8, 0))

    def hits(outline):
        m = model([ped("T A", 0), ped("T B", 135)], outlines={"x.png": [outline]})
        _, det = m.score(state, margin=0, detail=True)
        return {(b["jack"], b["obstacle"], b["part"]): b["depth_mm"] for b in det["blocked"]}
    assert hits([0, 0, 1, 1]) == pytest.approx({("a.out", "T B", "head"): 4.4, ("b.in", "T A", "head"): 4.4})
    assert hits([0.2, 0, 1, 1]) == pytest.approx({("b.in", "T A", "head"): 4.4})    # b starts 10 mm further in
    assert hits([0, 0, 0.8, 1]) == pytest.approx({("a.out", "T B", "head"): 4.4})   # a ends 10 mm earlier
    assert hits([0.2, 0, 0.8, 1]) == {}
    # the cost follows: no hit, no penetration
    m = model([ped("T A", 0), ped("T B", 135)], outlines={"x.png": [[0.2, 0, 0.8, 1]]})
    assert m.score(state, margin=0, detail=True)[1]["terms"]["clearance"] == (0.0, 0.0)
    # a rotated pedal: its outline turns with it (a band across the middle of the 50.8 x 101.6 box)
    rot = model([ped("T A", 0), ped("T B", 135)], outlines={"x.png": [[0, 0.4, 1, 0.6]]})
    assert rot._geom[(0, 0)]["shapes"] == [pytest.approx((-25.4, -10.16, 25.4, 10.16))]
    assert rot._geom[(0, 90)]["shapes"] == [pytest.approx((-10.16, -25.4, 10.16, 25.4))]


@functools.lru_cache(maxsize=1)
def _gig_build():
    pedals, supplies = load_catalog()
    return pedals, supplies, build.validate(GIG, pedals, supplies)


def gig_build():
    """(pedals, supplies, ctx): the build of the real guitar-gig, made once; every caller gets its own deep copy, so a test may
    change what it gets without touching the others."""
    return copy.deepcopy(_gig_build())


def test_surrogate_blocked_plugs_match_the_build_on_the_gig_layout():
    pedals, supplies, ctx = gig_build()
    m = layout.Model(load_json(GIG / "project.json"), design.parse_design(GIG / "playground_design.json"), pedals,
                     supplies, jacks.read_file()["jacks"], footswitches.read_file()["footswitches"], load_cable_types())
    _, det = m.score(m.owner, margin=0, detail=True)
    got = {(b["jack"], b["obstacle"], b["part"], round(b["depth_mm"], 1)) for b in det["blocked"]}
    want = {(v["jack"], v["obstacle"], v["part"], round(v["depth_mm"], 1)) for v in ctx["violations"]}
    assert got == want and len(got) == 4   # monk.out / monk.power by the Belle Epoch; red_muck.power / analog_chorus.power heads (1 mm)


# --- cable lengths --------------------------------------------------------------------------------
def test_signal_surrogate_is_measure_plus_octile_and_close_to_the_router():
    m = model([ped("T A", 0), ped("T B", 135)])
    state = at((25.4, 50.8, 0), (200.0, 70.0, 0))
    _, det = m.score(state, detail=True)
    # a.out exit: x 50.8 + 10 + 4 = 64.8, y 50.8; b.in exit: x 174.6 - 14 = 160.6, y 70; measure 5 + 4 per end
    want = 9 + 9 + layout.octile((64.8, 50.8), (160.6, 70.0))
    assert det["signal"]["S1"] == pytest.approx(want) and want == pytest.approx(18 + 95.8 + (math.sqrt(2) - 1) * 19.2)
    # the router on the same layout (open board): its path is smoothed to one straight segment, so it is exactly the
    # measure points plus hypot(95.8, 19.2) = 97.7 mm; the surrogate's octile estimate is up to ~8 % longer
    items = m.items_for(state, snap=False)
    proj = {**m.project, "validation": {}}
    ctx = {"project": proj, "dir": None, "errors": [], "warnings": [], "chain": ["a", "b"], "pedals": PEDALS, "supplies": []}
    jacks.check(ctx, PEDALS, {}, JACKS, cable_types=TYPES, defer=True, items=items)
    routing.route_project(ctx, PEDALS, cable_types=TYPES)
    (s1,) = [c for c in ctx["cable_list"] if c["id"] == "S1"]
    assert s1["status"] == "routed" and s1["min_mm"] == pytest.approx(18 + math.hypot(95.8, 19.2), abs=0.01) and 0 <= want - s1["min_mm"] < 8.0


def test_power_term_is_manhattan_between_measure_points_like_jacks_check():
    m = model([ped("T A", 0), ped("T B", 135)])
    m.set_wiring([((0.0, 0.0), ["a", "b"])])
    state = at((25.4, 50.8, 0), (200.0, 50.8, 0))
    _, det = m.score(state, detail=True)
    # power jacks at the top middle, facing top; no power type: half the 5.5 mm box -> measure 2.75 mm above
    assert det["terms"]["power"][0] == pytest.approx((25.4 + 2.75) + (200 - 25.4))
    assert det["terms"]["power"][1] == pytest.approx(0.1 * det["terms"]["power"][0])


# --- footswitches, io, flow, access, rotation, move ----------------------------------------------
def sw(t="bypass", x=0.5, y=0.8):
    return {"id": t, "label": t, "x": x, "y": y, "type": t}


def test_footswitch_crowding_weighs_the_pair_by_type_priority():
    """Switches 80 mm apart, comfort 100: crowding = priority x 20^2 / 100 = 4, weighted x 2. An optional minimum
    of 100 mm adds 20 / mm below it + 100 per pair (times the priority) and reports the pair."""
    pair = {"a": [sw()], "b": [sw()]}
    state = at((25.4, 50.8, 0), (105.4, 50.8, 0))
    m = model([ped("T A", 0), ped("T B", 180)], fs=pair)
    _, det = m.score(state, detail=True)
    assert det["terms"]["footswitch"] == pytest.approx((4.0, 8.0)) and det["fs_close"] == []
    assert m.score(at((25.4, 50.8, 0), (130.0, 50.8, 0)), detail=True)[1]["terms"]["footswitch"][0] < 4.0   # further: less
    m1 = model([ped("T A", 0), ped("T B", 180)], fs=pair, project_extra={"footswitches": {"min_distance_mm": 100}})
    _, det1 = m1.score(state, detail=True)
    assert det1["terms"]["footswitch"] == pytest.approx((4.0, 8.0 + 1.0 * (20 * 20 + 100))) and len(det1["fs_close"]) == 1
    m2 = model([ped("T A", 0), ped("T B", 180)], fs={"a": [sw("function")], "b": [sw("tap")]})
    assert m2.score(state, detail=True)[1]["terms"]["footswitch"] == pytest.approx((3.2, 6.4))   # max(0.5, 0.8)
    m3 = model([ped("T A", 0), ped("T B", 180)])                      # no footswitch data: term 0
    assert m3.score(state, detail=True)[1]["terms"]["footswitch"] == (0.0, 0.0) and not m3.fs_known


def test_io_and_flow():
    m = model([ped("T A", 0), ped("T B", 135)])
    state = at((25.4, 50.8, 0), (150.0, 50.8, 0))
    _, det = m.score(state, detail=True)
    # first input (a.in at x 0) to the right edge 254; last output (b.out at x 175.4): nearest of left 175.4,
    # right 78.6, back 50.8 -> 50.8
    assert det["terms"]["io"][0] == pytest.approx(254 + 50.8)
    assert det["terms"]["flow"] == pytest.approx((150 - 25.4, 0.1 * (150 - 25.4)))   # b is right of a


def test_access_rules():
    acc = layout.settings({})["access"]
    assert layout.access_rule({"id": "x", "tags": ["tuner"]}, [], acc) == {"want": "back", "weight": 0.5}
    assert layout.access_rule({"id": "x", "tags": ["gain", "overdrive", "master", "eq"]}, [], acc)["weight"] == 0.3
    assert layout.access_rule({"id": "x", "tags": ["modulation"]}, [], acc)["want"] == "avoid_front"
    assert layout.access_rule({"id": "x", "tags": ["modulation"]}, ["bypass", "tap"], acc) == {"want": "front", "weight": 0.1}
    assert layout.access_rule({"id": "x", "tags": []}, ["boost"], acc) == {"want": "front", "weight": 0.05}
    assert layout.access_rule({"id": "x", "tags": ["modulation"]}, ["boost"], acc)["want"] == "avoid_front"
    acc2 = layout.settings({"layout": {"access": {"pedals": {"x": {"want": "back", "weight": 2}}}}})["access"]
    assert layout.access_rule({"id": "x", "tags": ["gain"]}, [], acc2) == {"want": "back", "weight": 2}
    assert layout.access_rule({"id": "y", "tags": ["fuzz"]}, [], acc) is None


def test_access_term_uses_footswitch_depth_else_the_centre():
    m = model([ped("T A", 0), ped("T B", 135), ped("T C", 300)], chain=("a", "b", "c"), fs={"a": [sw()]})
    state = at((25.4, 50.8, 0), (100.0, 50.8, 0), (200.0, 50.8, 0))
    _, det = m.score(state, detail=True)
    # a (drive, front 0.1): switch at y 0.8 * 101.6 = 81.28 -> 127 - 81.28 from the front edge
    # b (modulation, avoid_front 0.1): centre 50.8, not in the front half (mid 63.5) -> 0
    # c (tuner, back 0.5): centre 50.8 from the back edge
    assert det["terms"]["access"][0] == pytest.approx(0.1 * (127 - 81.28) + 0.5 * 50.8)


def test_rotation_preference_and_move_cost():
    m = model([ped("T A", 0), ped("T B", 135)])
    one = at((25.4, 50.8, 0), (150.0, 76.2, 90))
    _, det = m.score(one, detail=True)
    assert det["terms"]["rotation"] == (1, 40.0)                      # a new angle on the board
    two = at((50.8, 25.4, 90), (150.0, 76.2, 90))
    assert m.score(two, detail=True)[1]["terms"]["rotation"] == (2, 20.0)   # each uses an angle the other has
    # move: b from (101.6, 50.8) to (150, 76.2) rotated: 0.2 / mm + 25 per moved pedal + 20 per rotation change
    d = math.hypot(150 - 101.6, 76.2 - 50.8)
    assert det["terms"]["move"] == pytest.approx((d, 0.2 * d + 25 + 20))
    assert m.score(one, detail=True, move_factor=0.0)[1]["terms"]["move"][1] == 0.0


def test_touching_bonus():
    m = model([ped("T A", 0), ped("T B", 135)], types={})     # no plug model: only fixed boxes
    _, det = m.score(at((25.4, 50.8, 0), (76.2, 50.8, 0)), detail=True)
    assert det["terms"]["touch"] == pytest.approx((101.6, -0.02 * 101.6))


def test_items_for_and_snapping_keep_unmoved_pedals_exact():
    m = model([ped("T A", 0), ped("T B", 135)])
    st = m.snapped(at((25.4, 50.8, 0), (150.13, 60.07, 0)))
    assert st[0] == m.owner[0]
    assert abs(st[1][0] - 150.13) < 0.57 and abs(st[1][1] - 60.07) < 0.57      # within one px (0.56 mm)
    raw = m.items_for(st, snap=False)[2]
    assert raw["left_px"] == round(raw["left_px"]) or abs(raw["left_px"] - round(raw["left_px"])) < 1e-6
    items = m.items_for(st)
    assert items[1] == m.placed["a"] and design.centre(items[2]) == pytest.approx(st[1][:2])


# --- power assignment -----------------------------------------------------------------------------
def test_chain_order_is_the_shortest_daisy_chain():
    pts = {"x": (10, 0), "y": (5, 0), "z": (20, 0)}
    length, order = power.chain_order((0, 0), ["x", "y", "z"], pts)
    assert order == ["y", "x", "z"] and length == 20


def gig_assignment():
    pedals, supplies, ctx = gig_build()   # (read only by every caller)
    lay, project = ctx["layout"], ctx["project"]
    insts = [{**i, "sup": supplies[i["supply"]]} for i in project["power"]["supplies"]]
    pts, ports = power.measure_points(lay["placed"], lay["inst_item"], insts, lay["jacks"],
                                     load_cable_types()[project["cables"]["power_type"]]["plug"]["head_depth_mm"])
    return pedals, supplies, ctx, project, insts, pts, ports


def test_power_assignment_passes_the_build_and_is_not_longer_than_the_owners():
    pedals, supplies, ctx, project, insts, pts, ports = gig_assignment()
    start = {i["id"]: i["outputs"] for i in project["power"]["supplies"]}
    for kw in ({"start": start}, {}):                                 # from the owner's wiring, and greedy alone
        res = power.assign(ctx["chain"], ctx["pedals"], insts, project, pts, ports, run_v=ctx["run_v"], **kw)
        proj = {**copy.deepcopy(project), "power": {"supplies": res["supplies"]}}
        got = build.validate(GIG, pedals, supplies, project=proj)
        assert got["errors"] == [] and res["warnings"] == []
        assert sorted(p for s in res["supplies"] for o in s["outputs"] for p in o["pedals"]) == sorted(ctx["chain"])
        assert got["run_v"] == ctx["run_v"]                               # operating voltages kept
        new = sum(h["min_mm"] for h in got["cables"]["power"])
        assert new == pytest.approx(res["length_mm"])                     # = the build's DC length estimate
        assert new <= sum(h["min_mm"] for h in ctx["cables"]["power"]) + 1e-6


def test_power_assignment_respects_the_policy():
    pedals, supplies, ctx, project, insts, pts, ports = gig_assignment()
    res = power.assign(ctx["chain"], ctx["pedals"], insts, project, pts, ports, run_v=ctx["run_v"])
    rows = {p: o["pedals"] for s in res["supplies"] for o in s["outputs"] for p in o["pedals"]}
    for pid in ("polytune_3", "monk", "belle_epoch", "flight_delay", "reticon"):   # digital or isolated: alone
        assert rows[pid] == [pid]
    chorus = rows["analog_chorus"]                                    # clocked: never with gain / compressor
    assert not any({"gain", "overdrive", "compressor"} & set(pedals[p]["tags"]) for p in chorus)


def test_power_assignment_fails_cleanly_without_enough_outputs():
    pedals, supplies, ctx, project, insts, pts, ports = gig_assignment()
    with pytest.raises(ValueError, match="no power wiring"):
        power.assign(ctx["chain"], ctx["pedals"], insts[:1], project, pts, ports, run_v=ctx["run_v"])


def test_output_findings_match_the_build_messages():
    pedals = {"d": {"digital": True, "clocked_noise": True, "tags": [], "power_consumption": {"current_ma": 300, "min_voltage_v": 9,
                                                                                           "max_voltage_v": 9, "polarity": "center_negative"}},
              "g": {"digital": False, "clocked_noise": False, "tags": ["gain"], "power_consumption": {"current_ma": 300, "min_voltage_v": 9,
                                                                                                  "max_voltage_v": 18, "polarity": "center_negative"}}}
    errs, warns, load = power.output_findings("p_F1", ["d", "g"], 9, 500, "center_negative", pedals, {"gain"}, "required")
    assert load == 600 and warns == []
    assert errs == ["p_F1: time-based/clocked ['d'] share an output with noise-sensitive ['g']",
                    "p_F1: digital pedal 'd' shares an output with ['g']", "p_F1: 600 mA exceeds 500 mA limit"]


def test_detour_around_a_crossed_pedal():
    rect = (40.0, -10.0, 60.0, 30.0)                  # the line y = 0 from x 0 to 100 crosses it
    assert layout.detour((0, 0), (100, 0), [rect]) == pytest.approx(2 * 10)   # clear it 10 mm upwards, out and back
    assert layout.detour((0, 40), (100, 40), [rect]) == 0.0                     # passes behind it
    assert layout.detour((0, 30), (100, 30), [rect]) == 0.0                     # grazing the edge is not crossing


def test_detour_around_touching_pedals_goes_around_both():
    left, right = (0.0, 0.0, 50.0, 100.0), (50.0, 0.0, 120.0, 100.0)   # touching along x = 50
    # a line along the contact edge (direction (2, 120)): clear both on the cheaper (left) side: the farthest left
    # corner (0, 100) lies (49 x 120 + 110 x 2) / |(2, 120)| = 50.83 mm off the line -> out and back
    want = 2 * (49 * 120 + 110 * 2) / (2 ** 2 + 120 ** 2) ** 0.5
    assert layout.detour((49.0, -10.0), (51.0, 110.0), [left, right]) == pytest.approx(want) and want == pytest.approx(101.65, abs=0.01)
    assert layout.detour((49.0, -10.0), (51.0, 110.0), [left]) < 2.0     # alone: a small step to the right clears it


def test_first_input_and_last_output_get_the_fixed_box_as_in_jacks_check():
    """The guitar input of the first pedal has no patch cable: the fixed 6.3 mm audio box, as jacks.check."""
    pedals = {**PEDALS, "z": {"brand": "T", "name": "Z", "playground_title": "T Z", "tags": []}}
    proj = {"signal_chain": ["a", "b"], "cables": {"type": "t"}, "jacks": {}}
    items = design.parse_canvas(canvas(BOARD, ped("T Z", 0), ped("T A", 92), ped("T B", 300)))   # 2 px = 1.13 mm gap
    m = layout.Model(proj, items, pedals, {}, JACKS, {}, TYPES)
    _, det = m.score(m.owner, margin=0, detail=True)
    hits = {(b["jack"], b["obstacle"], b["part"]): b["depth_mm"] for b in det["blocked"]}
    assert hits[("a.in", "T Z", "box")] == pytest.approx(6.3 - 2 * 25.4 / 45, abs=1e-3)
    assert ("b.out", "T Z", "box") not in hits


def test_power_plug_side_override_follows_its_pedal():
    pedals, supplies = load_catalog()
    project = load_json(GIG / "project.json")
    ids = power.cable_ids(project["power"]["supplies"])
    pid = next(p for p, c in ids.items() if c == "P1")
    project["cables"].setdefault("overrides", {})["P1"] = {"exit_b": "right"}
    m = layout.Model(project, design.parse_design(GIG / "playground_design.json"), pedals, supplies,
                     jacks.read_file()["jacks"], footswitches.read_file()["footswitches"], load_cable_types())
    n = m.index[pid]
    assert m.p_exit[pid] == "right" and {o["side"] for o in m._geom[(n, m.owner[n][2])]["power"]["opts"]} == {"right"}


def test_power_cable_ids_and_override_remap():
    old = [{"outputs": [{"pedals": ["x", "y"]}, {"pedals": []}, {"pedals": ["z"]}]}]
    new = [{"outputs": [{"pedals": ["z"]}, {"pedals": ["y", "x"]}]}]
    assert power.cable_ids(old) == {"x": "P1", "y": "P2", "z": "P3"}
    over = {"P1": {"exit_b": "left"}, "P3": {"exit_b": "right"}, "S2": {"exit_a": "left"}}
    assert power.remap_overrides(over, old, new) == {"P3": {"exit_b": "left"}, "P1": {"exit_b": "right"},
                                                     "S2": {"exit_a": "left"}}
    assert power.remap_overrides({"P4": {"exit_b": "left"}}, old, new + [{"outputs": [{"pedals": ["w"]}]}]) == {}   # stale


def test_isolated_need_and_unknown_max_ma_are_one_policy_for_build_and_assign():
    pc = {"current_ma": 50, "min_voltage_v": 9, "max_voltage_v": 9, "needs_isolated_output": True, "polarity": "center_negative"}
    pedals = {"i": {"digital": False, "clocked_noise": False, "tags": [], "power_consumption": pc}}
    errs, _, _ = power.output_findings("p_F1", ["i"], 9, 500, "center_negative", pedals, set(), "required", isolated=False)
    assert errs == ["p_F1: i needs an isolated output but this port is not isolated"]
    assert power.output_findings("p_F1", ["i"], 9, 500, "center_negative", pedals, set(), "required", isolated=True)[0] == []
    # assign never uses a voltage option whose max_ma is unknown (the build reports that output as an error)
    _, _, ctx, project, insts, pts, ports = gig_assignment()
    insts = copy.deepcopy(insts)
    port = insts[0]["sup"]["outputs"][0]
    for op in port["options"]:
        op["max_ma"] = None
    res = power.assign(ctx["chain"], ctx["pedals"], insts, project, pts, ports, run_v=ctx["run_v"])
    used = {(s["id"], o["port"]) for s in res["supplies"] for o in s["outputs"]}
    assert (insts[0]["id"], port["port"]) not in used


def test_surrogate_crowding_equals_the_builds_on_the_gig_layout():
    pedals, supplies = load_catalog()
    fs_data = footswitches.read_file()["footswitches"]
    ctx = build.validate(GIG, pedals, supplies, footswitch_data=fs_data)
    m = layout.Model(load_json(GIG / "project.json"), design.parse_design(GIG / "playground_design.json"), pedals,
                     supplies, jacks.read_file()["jacks"], fs_data, load_cable_types())
    raw = m.score(m.owner, detail=True)[1]["terms"]["footswitch"][0]
    assert ctx["footswitch_settings"]["crowding"] > 0 and raw == pytest.approx(ctx["footswitch_settings"]["crowding"])


# --- on-board supplies are movable items ------------------------------------------------------------
PX = 25.4 / 45
SUPPLIES = {"s1": {"id": "s1", "brand": "S", "model": "One", "playground_title": "S One"}}
SUP_JACKS = [{"id": "F1", "label": "F1", "function": "power_out", "x": 1.0, "y": 0.5, "facing": "right"},
             {"id": "F2", "label": "F2", "function": "power_out", "x": 1.0, "y": 0.9, "facing": "right"}]


def sup(left_px, top_px=0, w=2.0, h=1.0):
    return ("S One", left_px, top_px, w, h, 0, "pedal")


def smodel(specs, chain=("a",), placement="on_board", extra=None, pedals=PEDALS):
    """A project with one supply instance psu1 (F1 feeds pedal a, F2 spare); its item is the one titled "S One"."""
    inst = {"id": "psu1", "supply": "s1", "outputs": [{"port": "F1", "pedals": ["a"]}]}
    if placement:
        inst["placement"] = placement
    proj = {"signal_chain": list(chain), "cables": {"type": "t"}, "jacks": {}, "power": {"supplies": [inst]}, **(extra or {})}
    items = design.parse_canvas(canvas(BOARD, *specs))
    return layout.Model(proj, items, pedals, SUPPLIES, {**JACKS, "s1": SUP_JACKS}, {}, TYPES, outlines={})


QUIET_W = {"layout": {"weights": {"io": 0, "flow": 0, "access": 0}}}


def test_an_on_board_supply_is_a_movable_item_after_the_chain_pedals():
    m = smodel([sup(200), ped("T A", 0), ped("T B", 100)], chain=("a", "b"))
    assert m.ids == ["a", "b", "psu1"] and m.n_ped == 2 and m.index["psu1"] == 2
    assert m.titles == ["T A", "T B", "S One"] and m.names["psu1"] == "S One" and m.access[2] is None
    assert m.owner[2] == pytest.approx((200 * PX + 25.4, 12.7, 0)) and m.allowed[2] == [0, 90, 270]
    assert m.fixed == [] and m._geom[(2, 0)]["ends"] == {} and m._geom[(2, 0)]["fs"] == []
    # an under-board supply is neither movable nor an obstacle; the chain pedals alone are the state
    u = smodel([sup(200), ped("T A", 0)], placement="under")
    assert u.ids == ["a"] and u.n_ped == 1 and u.fixed == [] and len(u.owner) == 1
    assert smodel([sup(200), ped("T A", 0)], placement=None).ids == ["a"]


def test_the_supply_never_overlaps_a_pedal_or_overhangs_and_pins_hold():
    m = smodel([ped("T A", 0), sup(200)])
    ok = [m.owner[0], (150.0, 20.0, 0)]
    assert m.feasible(ok) and m.feasible_one(ok, 1)
    assert not m.feasible([m.owner[0], (40.0, 60.0, 0)])          # on top of pedal a
    assert not m.feasible([m.owner[0], (240.0, 20.0, 0)])         # 11 mm over the right edge
    assert not m.feasible_one([m.owner[0], (150.0, 20.0, 180)], 1)   # never 180
    assert m.feasible([m.owner[0], (150.0, 40.0, 90)])            # rotated: 25.4 x 50.8
    assert not m.feasible([(120.0, 50.8, 0), (138.0, 12.7, 0)])   # a pedal moved onto the supply
    for seed in range(12):
        for _, st in layout.search(m, "rearrange", seed=seed, iterations=80, restarts=1):
            assert m.feasible(st)
    pin = smodel([ped("T A", 0), sup(200)], extra={"layout": {"pins": ["psu1"]}})
    assert not pin.feasible([pin.owner[0], (150.0, 20.0, 0)]) and pin.feasible(pin.owner)
    for _, st in layout.search(pin, "rearrange", seed=2, iterations=100, restarts=2):
        assert st[1] == pin.owner[1]
    with pytest.raises(ValueError, match="layout.pins"):
        smodel([ped("T A", 0), sup(200)], placement="under", extra={"layout": {"pins": ["psu1"]}})


def test_moving_the_supply_moves_its_ports_and_the_power_term():
    m = smodel([ped("T A", 0), sup(200)])
    # a: power jack top middle (25.4, 0), measure 2.75 above; psu1.F1 at its right edge middle facing right: measure 2.75 right
    for (cx, cy), want in (((138.289, 100.0), (138.289 + 25.4 + 2.75 - 25.4) + (100.0 + 2.75)),
                           ((100.0, 30.0), (100.0 + 25.4 + 2.75 - 25.4) + (30.0 + 2.75))):
        _, det = m.score([m.owner[0], (cx, cy, 0)], detail=True)
        assert det["terms"]["power"][0] == pytest.approx(want, abs=1e-6)
        assert det["terms"]["power"][1] == pytest.approx(0.1 * want, abs=1e-6)
    # rotated 90 deg: the port faces down, at the bottom edge middle: 25.4 + 2.75 below the centre; 270 deg: up
    assert m._geom[(1, 90)]["port_pt"]["F1"] == pytest.approx((0.0, 28.15)) and m._geom[(1, 270)]["port_pt"]["F1"] == pytest.approx((0.0, -28.15))
    _, det = m.score([m.owner[0], (100.0, 40.0, 90)], detail=True)
    assert det["terms"]["power"][0] == pytest.approx(abs(100.0 - 25.4) + abs(40.0 + 28.15 + 2.75), abs=1e-6)
    # an under-board supply keeps its owner position: the power term does not follow the state
    u = smodel([ped("T A", 0), sup(200)], placement="under")
    assert u.score(u.owner, detail=True)[1]["terms"]["power"][0] > 0 and len(u.owner) == 1


def test_a_supply_port_with_a_blocking_pedal_costs_clearance_and_moving_the_supply_clears_it():
    # obstacle b (not in the chain) 2.82 mm right of the supply's right edge: F1's 5.5 mm power box reaches 2.68 mm into it
    m = smodel([ped("T A", 0), sup(200), ped("T B", 295)], extra=QUIET_W)
    gap = 295 * PX - (200 + 90) * PX
    assert gap == pytest.approx(2.822, abs=1e-3)
    _, det = m.score(m.owner, margin=0, detail=True)
    (hit,) = [b for b in det["blocked"] if b["jack"] == "psu1.F1"]
    assert hit["obstacle"] == "T B" and hit["part"] == "box" and hit["depth_mm"] == pytest.approx(5.5 - gap, abs=1e-3)
    assert det["terms"]["clearance"][1] >= 50 * hit["depth_mm"] + 100
    moved = [m.owner[0], (m.owner[1][0] - 10.0, m.owner[1][1], 0)]
    _, det2 = m.score(moved, margin=0, detail=True)
    assert not [b for b in det2["blocked"] if b["jack"] == "psu1.F1"]
    assert det2["terms"]["clearance"][1] < det["terms"]["clearance"][1]
    # the supply as an obstacle: a plug of pedal a's output (box 6.3 mm) next to the supply is blocked by it
    near = smodel([ped("T A", 0), sup(95, 0, 2.0, 4.0)], extra=QUIET_W)        # supply starts 2.82 mm right of a's right edge
    _, d3 = near.score(near.owner, margin=0, detail=True)
    assert [b for b in d3["blocked"] if b["jack"] == "a.out" and b["obstacle"] == "S One"]
    # the search clears the port by moving the supply (b is a fixed obstacle; a is far from everything)
    best = layout.search(m, "fix", seed=1, iterations=400, restarts=1)[0][1]
    assert m.feasible(best) and blocked_of(m, best) == [] and best[1] != m.owner[1]


def blocked_of(m, state):
    return m.score(state, margin=0, detail=True)[1]["blocked"]


def test_with_a_power_type_the_port_gets_the_dc_plug_on_the_better_side():
    dc = {"dc": {"role": "power", "diameter_mm": 3.5, "plug": {"style": "right_angle", "head_depth_mm": 10.0, "head_width_mm": 10.0}}}
    inst_types = {**TYPES, **dc}
    inst = {"id": "psu1", "supply": "s1", "placement": "on_board", "outputs": [{"port": "F1", "pedals": ["a"]}]}
    proj = {"signal_chain": ["a"], "cables": {"type": "t", "power_type": "dc", "overrides": {"P1": {"exit_a": "left"}}}, "jacks": {},
            "power": {"supplies": [inst]}}
    items = design.parse_canvas(canvas(BOARD, ped("T A", 0), sup(200)))
    m = layout.Model(proj, items, PEDALS, SUPPLIES, {**JACKS, "s1": SUP_JACKS}, {}, inst_types, outlines={})
    (port,) = m._geom[(1, 0)]["ports"]
    assert port["jack"] == "psu1.F1" and {o["side"] for o in port["opts"]} == {"left"}        # the override fixes the side
    assert m._geom[(1, 0)]["port_pt"]["F1"] == pytest.approx((25.4 + 5.0, 0.0))                # half the 10 mm head in front
    free = layout.Model({**proj, "cables": {"type": "t", "power_type": "dc"}}, items, PEDALS, SUPPLIES,
                        {**JACKS, "s1": SUP_JACKS}, {}, inst_types, outlines={})
    assert {o["side"] for o in free._geom[(1, 0)]["ports"][0]["opts"]} == {"left", "right"}


def test_items_for_moves_the_supply_item_and_leaves_the_rest():
    m = smodel([ped("T A", 0), sup(200), ped("T B", 295)])
    state = [m.owner[0], (100.0, 30.0, 90)]
    out = {it["id"]: it for it in m.items_for(state, snap=False)}
    sid = m.inst_item["psu1"]["id"]
    cx, cy = design.centre(out[sid])
    assert (cx, cy) == pytest.approx((100.0, 30.0)) and out[sid]["rot"] == 90
    assert out[m.placed["a"]["id"]] == m.placed["a"]
    assert [it for it in m.items if it["title"] == "T B"][0] in m.items_for(state)
    assert m.items_for(m.owner, snap=True)[1:] and design.centre(m.items_for(m.owner)[0]) == pytest.approx(design.centre(m.items[0]))


def test_wiring_given_by_the_search_follows_an_on_board_supply():
    """propose_layout.evaluate passes (port point, pedals, under, (instance, port)): the on-board port follows the state."""
    m = smodel([ped("T A", 0), sup(200)])
    m.set_wiring([((0.0, 0.0), ["a"], False, ("psu1", "F1"))])
    _, det = m.score([m.owner[0], (100.0, 30.0, 0)], detail=True)
    assert det["terms"]["power"][0] == pytest.approx((100.0 + 2.75 + 25.4 - 25.4) + (30.0 + 2.75) - 0.0, abs=1e-6)
    m.set_wiring([((0.0, 0.0), ["a"], True, ("other", "F1"))])    # not a movable supply: the fixed point stays
    _, det = m.score([m.owner[0], (100.0, 30.0, 0)], detail=True)
    assert det["terms"]["power"][0] == pytest.approx((25.4 - 0.0) + (0.0 + 2.75), abs=1e-6)


# recorded from the commit before on-board supplies became movable (uv run scripts/propose_layout.py guitar-gig --score)


def test_the_gig_score_is_unchanged_by_movable_supplies():
    """No on-board supply: only chain pedals move, and an explicit "under" on every supply scores exactly as the
    default (compared within the current data, so owner edits of the gig never break this test)."""
    pedals, supplies = load_catalog()
    proj = load_json(GIG / "project.json")
    args = (design.parse_design(GIG / "playground_design.json"), pedals, supplies, jacks.read_file()["jacks"],
            footswitches.read_file()["footswitches"], load_cable_types())
    m = layout.Model(proj, *args)
    assert m.ids == m.ids[:m.n_ped] and m.n_ped == len(m.owner)       # no on-board supply: only chain pedals move
    under = copy.deepcopy(proj)
    for inst in under["power"]["supplies"]:
        inst["placement"] = "under"
    u = layout.Model(under, *args)
    assert u.ids == m.ids
    (total, det), (total_u, det_u) = m.score(m.owner, detail=True), u.score(u.owner, detail=True)
    assert total == pytest.approx(total_u) and det["terms"] == det_u["terms"]


# --- the power estimate's hole points: the project's hole edits, free under the board -----------------------
DC_TYPES = {**TYPES, "dc": {"role": "power", "diameter_mm": 3.5, "plug": {"style": "right_angle", "head_depth_mm": 10.0, "head_width_mm": 10.0}}}
HOLE_BOARD = {"x.png": {"holes": [[0.4, 0.4, 0.6, 0.6]]}}         # x 101.6..152.4, y 50.8..76.2 on the 254 x 127 mm board


def hole_model(specs, board_data, board_edits=None, placement="under"):
    inst = {"id": "psu1", "supply": "s1", "placement": placement, "outputs": [{"port": "F1", "pedals": ["a"]}]}
    proj = {"signal_chain": ["a"], "cables": {"type": "t", "power_type": "dc"}, "jacks": {}, "power": {"supplies": [inst]}}
    items = design.parse_canvas(canvas(BOARD, *specs))
    return layout.Model(proj, items, PEDALS, SUPPLIES, {**JACKS, "s1": SUP_JACKS}, {}, DC_TYPES, outlines={},
                        board_data=board_data, board_edits=board_edits)


def test_the_model_uses_the_projects_hole_edits_for_the_power_estimate():
    specs = [ped("T A", 0)]
    assert hole_model(specs, {}).power_setup is None                                    # no holes known
    edit = {"type": "hole", "x0": 0.4, "y0": 0.4, "x1": 0.6, "y1": 0.6}
    opened = hole_model(specs, {}, [edit]).power_setup                                  # the project's box opens a hole
    assert opened is not None and len(opened["index"]) > 0
    assert all(101.6 <= x <= 152.4 and 50.8 <= y <= 76.2 for x, y in opened["index"].points)
    closed = hole_model(specs, HOLE_BOARD, [{"type": "filled", "x0": 0, "y0": 0, "x1": 1, "y1": 1}])
    assert closed.power_setup is None                                                   # the board data's hole filled by an edit
    assert len(hole_model(specs, HOLE_BOARD).power_setup["index"]) == len(opened["index"])


def test_hole_points_under_an_under_board_supply_are_not_usable_for_the_estimate():
    free = hole_model([ped("T A", 0)], HOLE_BOARD).power_setup["index"]
    # the supply item (x 112.9..163.7, y 50.8..76.2) hangs under the board over the hole's right part; grown by the cable radius 1.75
    under = hole_model([ped("T A", 0), sup(200, 90)], HOLE_BOARD).power_setup["index"]
    assert 0 < len(under) < len(free)
    assert all(not (112.9 - 1.75 <= x <= 163.7 + 1.75 and 50.8 - 1.75 <= y <= 76.2 + 1.75) for x, y in under.points)
    assert set(under.points) < set(free.points)
    # an on-board supply is a pedal on top, not an under-board obstacle: the model moves it instead and keeps all the points
    on = hole_model([ped("T A", 0), sup(200, 90)], HOLE_BOARD, placement="on_board").power_setup["index"]
    assert len(on) == len(free)


def test_surrogate_ignores_toppers():
    """Toppers are a finishing step after the layout: the surrogate's footswitch term (and the total score) is the
    same with and without `footswitches.toppers` / `topper_bonus_mm`."""
    pair = {"a": [sw()], "b": [sw()]}
    state = at((25.4, 50.8, 0), (105.4, 50.8, 0))
    plain = model([ped("T A", 0), ped("T B", 180)], fs=pair)
    topped = model([ped("T A", 0), ped("T B", 180)], fs=pair,
                   project_extra={"footswitches": {"toppers": ["a.bypass", "b.bypass"], "topper_bonus_mm": 30}})
    t0, d0 = plain.score(state, detail=True)
    t1, d1 = topped.score(state, detail=True)
    assert t0 == t1 and d0["terms"] == d1["terms"] and d1["terms"]["footswitch"] == pytest.approx((4.0, 8.0))
