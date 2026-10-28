"""Several DC plug types per project (`cables.power_types`, routing.power_plug_choices / route_power / validate_project_types, the
README). Synthetic cable types and hand-made layouts only (the boards of test_routing, test_power_routing and test_plug_collisions);
all lengths in mm, never catalog values.

Pedal A (20..70 x 60..160) has its power jack at (45, 60) facing top. `dc` (test_routing.DC): right-angle, head 10 x 10 (axis 5 mm
out), 3.5 mm cable: exit left (36.5, 55) / right (53.5, 55), cable runs (36.5, 53.25, 40, 56.75) / (50, 53.25, 53.5, 56.75), the
plug measures 8.5 mm. `dcs` (here): straight, head 30 deep x 6 wide, 3 mm cable: head (42, 30, 48, 60), cable run (43.5, 27, 46.5, 30),
exit (45, 27), measures 30 / 2 + 3 = 18 mm. `dcw` is a wide (5 mm) straight type for the grid width."""
import copy
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import build  # noqa: E402
import design  # noqa: E402
import routing  # noqa: E402
import test_plug_collisions as pc  # noqa: E402
from test_layout import gig_build  # noqa: E402
from test_power_routing import pw_ctx  # noqa: E402
from test_routing import DC, TYPES, mm_item, power_ctx  # noqa: E402

STRAIGHT = {"name": "test DC straight", "role": "power", "diameter_mm": 3.0, "tips": "DC 2.1 mm",
            "plug": {"style": "straight", "head_depth_mm": 30.0, "head_width_mm": 6.0}}
DCS = {"dcs": STRAIGHT, "dcw": {**STRAIGHT, "diameter_mm": 5.0}}
TY = {**TYPES, **DC, **DCS}
HOLE_PW = (35.0, 45.0, 55.0, 65.0)
HOLE_D = (95.0, 45.0, 115.0, 65.0)
LEFT_WALL = mm_item("i-l", "L", 30, 0, 9.9, 58)       # x 30..39.9: 3.4 mm into the left cable run of A's right-angle plug
RIGHT_WALL = mm_item("i-r", "R", 51, 0, 29, 58)       # x 51..80: 3.5 mm into its right cable run
BOTH = [LEFT_WALL, RIGHT_WALL]


def routed(ctx):
    routing.route_project(ctx, {}, cable_types=TY)
    return {c["id"]: c for c in ctx["cable_list"] if c["kind"] == "power"}


def one(extra=(), power_type="dc", power_types=None, overrides=None):
    ctx = power_ctx(list(extra), power_type=power_type, overrides=overrides)
    if power_types is not None:
        ctx["project"]["cables"]["power_types"] = power_types
    return ctx, routed(ctx)["P1"]


# --- settings and validation ------------------------------------------------------------------------
def test_the_type_list_is_the_default_type_first_then_the_others_without_duplicates():
    assert routing.power_type_list({}) == [] and routing.power_type_list({"power_type": "dc"}) == ["dc"]
    assert routing.power_type_list({"power_type": "dc", "power_types": ["dcs", "dc", "dcw", "dcs"]}) == ["dc", "dcs", "dcw"]
    assert routing.settings({"cables": {"power_type": "dc"}})["power_types"] == ["dc"]
    assert routing.settings({"cables": {"power_type": "dc", "power_types": ["dcs"]}})["power_types"] == ["dc", "dcs"]
    s = routing.settings({"cables": {"power_types": ["dcs", "dc"]}})   # no default type: the first one is it
    assert s["power_type"] == "dcs" and s["power_types"] == ["dcs", "dc"]
    assert routing.settings({"cables": {"power_types": "dcs"}})["power_types"] == []                # malformed: reported by validation


def test_power_types_are_validated_like_the_power_type():
    ok = routing.validate_project_types({"cables": {"power_type": "dc", "power_types": ["dc", "dcs"]}}, TY)
    assert ok == []
    errs = routing.validate_project_types({"cables": {"power_types": ["nope", "ra", "dcs"]}}, TY)
    assert len(errs) == 2
    assert any("power_types: nope is not in catalog/cables.json" in e for e in errs)
    assert any("power_types: ra is a patch cable, not a DC power cable" in e for e in errs)
    assert any("power_types must be a list" in e for e in routing.validate_project_types({"cables": {"power_types": "dc"}}, TY))
    assert any("power_types must be a list" in e for e in routing.validate_project_types({"cables": {"power_types": [3]}}, TY))


def test_an_unknown_or_non_power_override_type_is_an_error():
    for k in ("type_a", "type_b"):
        ctx, c = one(overrides={"P1": {k: "nope"}})
        assert any(f"P1 has unknown {k}=nope (not in catalog/cables.json)" in e for e in ctx["errors"])
        ctx, c = one(overrides={"P1": {k: "ra"}})
        assert any(f"{k}=ra (not a power cable (role power))" in e for e in ctx["errors"])
    ctx, c = one(overrides={"P1": {"type_b": "dcs"}})
    assert ctx["errors"] == [] and c["type_b"] == "dcs"


def test_the_router_ignores_an_override_type_that_is_not_a_power_cable():
    cfg = routing.settings({"cables": {"power_type": "dc", "power_types": ["dc", "dcs"]}}, TY)
    assert routing.power_candidates(TY, cfg, "ra") == ["dc", "dcs"] and routing.power_candidates(TY, cfg, "nope") == ["dc", "dcs"]
    assert routing.power_candidates(TY, cfg, "dcs") == ["dcs"] and not routing.is_power_type(TY, "ra") and routing.is_power_type(TY, "dc")
    for k in ("type_a", "type_b"):
        ctx, c = one(overrides={"P1": {k: "ra"}})
        assert any(f"{k}=ra (not a power cable (role power))" in e for e in ctx["errors"])   # reported ...
        assert (c["type_a"], c["type_b"], c["type"]) == ("dc", "dc", "dc")   # ... and not used
        (h,) = [v for v in ctx["routing"]["heads"] if v["cable"] == "P1"]
        assert dict(h["rects"])["head"] == pytest.approx((40, 50, 50, 60))            # the default DC plug's head (10 x 10), not the patch plug's


# --- one plug: the ranking ----------------------------------------------------------------------------
def test_without_power_types_nothing_changes():
    ctx, c = one(BOTH)                                    # the old test: blocked on both sides, the smaller overlap wins
    assert (c["type"], c["type_a"], c["type_b"], c["exit_b"]) == ("dc", "dc", "dc", "right")
    same, c2 = one(BOTH, power_types=["dc"])
    assert (c2["type_b"], c2["exit_b"]) == ("dc", "right") and [v["depth_mm"] for v in same["violations"]] == \
        [v["depth_mm"] for v in ctx["violations"]]
    ctx3, c3 = one([], power_types=["dc"])
    ctx4, c4 = one([])
    assert (c3["exit_b"], c3["type_b"]) == (c4["exit_b"], c4["type_b"]) == ("left", "dc")


def test_a_pedal_whose_right_angle_exits_are_both_blocked_takes_the_straight_plug():
    ctx, c = one(BOTH, power_types=["dcs"])
    assert (c["type"], c["type_b"], c["exit_b"]) == ("dcs", "dcs", None) and c["type_a"] == "dc"   # the port keeps the default
    assert not [v for v in ctx["violations"] if v["jack"] == "a.power"]
    (h,) = [h for h in ctx["routing"]["heads"] if h["cable"] == "P1"]
    assert dict(h["rects"])["head"] == pytest.approx((42, 30, 48, 60)) and dict(h["rects"])["cable"] == pytest.approx((43.5, 27, 46.5, 30))
    # and without the straight type the old violation stays
    ctx2, c2 = one(BOTH)
    assert [v["jack"] for v in ctx2["violations"]] == ["a.power"]


def test_a_pedal_whose_straight_head_is_blocked_keeps_the_right_angle_plug_whatever_the_order():
    shelf = mm_item("i-e", "E", 0, 0, 300, 40)            # y 0..40: 10 mm into the straight head and its cable run, clear of the dc plug
    for default, others in (("dc", ["dcs"]), ("dcs", ["dc"])):
        ctx, c = one([shelf], power_type=default, power_types=others)
        assert c["type_b"] == "dc" and c["exit_b"] in ("left", "right") and ctx["violations"] == [], default


def test_a_free_pedal_takes_the_first_type_of_the_list_and_the_exit_of_that_type():
    ctx, c = one([], power_type="dc", power_types=["dcs"])
    assert c["type_b"] == "dc" and c["exit_b"] == "left"
    ctx, c = one([], power_type="dcs", power_types=["dc"])
    assert c["type_b"] == "dcs" and c["exit_b"] is None and c["type"] == "dcs"


def test_a_down_plug_beats_a_straight_one_that_is_free_and_listed_first():
    ctx = pw_ctx(holes=(HOLE_PW,), cables={"power_type": "dcs", "power_types": ["dc"]})
    (c,) = routed(ctx).values()
    assert (c["type_b"], c["exit_b"]) == ("dc", "down") and c["status"] == "routed" and c["under_board"]
    # no hole: the straight plug (listed first) takes it
    ctx = pw_ctx(holes=(), cables={"power_type": "dcs", "power_types": ["dc"]})
    (c,) = routed(ctx).values()
    assert (c["type_b"], c["exit_b"]) == ("dcs", None)
    # an exit fixed to down where no hole allows it: only the right-angle plug could, so the fall-back is the usual ranking
    ctx = pw_ctx(holes=(), cables={"power_type": "dcs", "power_types": ["dc"], "overrides": {"P1": {"exit_b": "down"}}})
    (c,) = routed(ctx).values()
    assert any("P1 exit_b is down, but the plug at a.power cannot point down" in w for w in ctx["warnings"])


# --- feasibility: the exit must be usable --------------------------------------------------------------
HEAD_HITTERS = [mm_item("i-hl", "HL", 38, 0, 4, 58), mm_item("i-hr", "HR", 48, 0, 5, 58)]   # each right-angle exit: its head and cable run (and the head the other wall) are hit, the exit free
ABOVE = mm_item("i-up", "UP", 30, 0, 30, 28)          # y 0..28 holds the straight plug's exit (45, 27) and 1 mm of its cable run


def test_a_straight_plug_whose_exit_is_inside_a_pedal_loses_to_a_right_angle_plug_with_more_hits():
    ctx, c = one(HEAD_HITTERS + [ABOVE], power_types=["dcs"])
    assert c["type_b"] == "dc" and c["exit_b"] in ("left", "right")
    # without the pedal over its exit the straight plug (0 hits against 2) is the better one
    ctx2, c2 = one(HEAD_HITTERS, power_types=["dcs"])
    assert c2["type_b"] == "dcs"
    # the count: with the pedal the straight plug has 1 hit, each right-angle one more (the head touches both walls)
    pool = routing.power_plug_pool(ctx["layout"]["placed"]["a"], ctx["layout"]["jacks"]["a"][1], "a.power", ["dc", "dcs"], TY, None,
                                   routing.settings(ctx["project"], TY), ctx["layout"], ctx["layout"]["obstacles"], None)[1]
    st = [o for o in pool if o["type"] == "dcs"][0]
    ra = [o for o in pool if o["type"] == "dc"]
    assert len(st["hits"]) == 1 and not st["ok"] and all(len(o["hits"]) > 1 and o["ok"] for o in ra)


def test_an_exit_outside_the_routing_area_is_infeasible():
    ctx = power_ctx([], power_type="dc")
    ctx["project"]["cables"]["power_types"] = ["dcs"]
    cfg = routing.settings(ctx["project"], TY)
    cables = lambda: [{"kind": "power", "from": "psu1.1", "to": "a.power"}]     # fresh ones: a chosen exit_b would be read as an override
    area = lambda pt: pt[1] > 30                       # the straight exit (45, 27) lies beyond the area, the right-angle ones (y 55) do not
    (cid, jk, c, f, o), = routing.power_plug_choices(ctx, cables(), TY, cfg, ctx["layout"]["obstacles"], inside=area)
    assert o["type"] == "dc"
    (cid, jk, c, f, o), = routing.power_plug_choices(ctx, cables(), TY, cfg, ctx["layout"]["obstacles"])     # no area: the list order decides
    assert o["type"] == "dc"
    ctx = power_ctx([], power_type="dcs")
    ctx["project"]["cables"]["power_types"] = ["dc"]
    cfg = routing.settings(ctx["project"], TY)
    (cid, jk, c, f, o), = routing.power_plug_choices(ctx, cables(), TY, cfg, ctx["layout"]["obstacles"])
    assert o["type"] == "dcs"                          # straight listed first and feasible
    (cid, jk, c, f, o), = routing.power_plug_choices(ctx, cables(), TY, cfg, ctx["layout"]["obstacles"], inside=area)
    assert o["type"] == "dc"


def test_a_serial_cable_counts_its_infeasible_plugs_first():
    ctx, ps = chain("serial", extra=HEAD_HITTERS)    # A's right-angle plug has 2 hits either side: the whole cable goes straight
    assert {c["type_b"] for c in ps.values()} == {"dcs"}
    ctx, ps = chain("serial", extra=HEAD_HITTERS + [ABOVE])    # ... but a pedal over A's straight exit makes the straight type infeasible there
    assert {c["type_b"] for c in ps.values()} == {"dc"}


# --- overrides ----------------------------------------------------------------------------------------
def test_type_b_fixes_the_pedal_plug_type_even_where_the_other_type_ranks_better():
    ctx, c = one(BOTH, power_types=["dcs"], overrides={"P1": {"type_b": "dc"}})
    assert c["type_b"] == "dc" and c["exit_b"] == "right"
    ctx, c = one([], power_types=[], overrides={"P1": {"type_b": "dcs"}})               # not in the project's list: still honoured
    assert c["type_b"] == "dcs" and c["type_a"] == "dc"


def test_an_exit_the_chosen_type_cannot_do_falls_back_with_a_warning_and_the_other_type_keeps_its_side():
    ctx, c = one([], power_types=["dcs"], overrides={"P1": {"type_b": "dcs", "exit_b": "left"}})
    assert c["type_b"] == "dcs" and c["exit_b"] is None
    assert any("P1 exit_b is left, but the plug at a.power (dcs) has no side exit" in w for w in ctx["warnings"]) and ctx["errors"] == []
    # a fixed side with several types: the types that cannot do it drop out
    ctx, c = one([], power_type="dcs", power_types=["dc"], overrides={"P1": {"exit_b": "right"}})
    assert (c["type_b"], c["exit_b"]) == ("dc", "right") and ctx["warnings"] == []
    strict = power_ctx([], power_type="dcs", overrides={"P1": {"type_b": "dcs", "exit_b": "left"}})
    strict["project"]["validation"] = {"strict_routing": True}
    routed(strict)
    assert any("P1 exit_b is left" in e for e in strict["errors"])


def test_type_a_fixes_the_port_plug_and_an_under_board_port_start_uses_its_head_depth():
    ctx = pw_ctx(holes=(HOLE_PW,), cables={"overrides": {"P1": {"type_a": "dcs"}}})
    (c,) = routed(ctx).values()
    assert (c["type_a"], c["type_b"]) == ("dcs", "dc")
    under = next(s["points"] for s in c["stretches"] if s["layer"] == "under")
    assert under[0] == pytest.approx((112.0, 135.0))        # F1 (112, 150) facing top, half the 30 mm straight head in front
    ctx = pw_ctx(holes=(HOLE_PW,))
    (c,) = routed(ctx).values()
    assert (c["type_a"], c["type_b"]) == ("dc", "dc")
    assert next(s["points"] for s in c["stretches"] if s["layer"] == "under")[0] == pytest.approx((112.0, 145.0))


# --- serial and forked cables -------------------------------------------------------------------------
def chain(style, hops=None, cables=None, extra=BOTH, holes=()):
    hops = hops or ((("psu1.F1", "d.power"), ("d.power", "a.power")) if style == "serial" else (("psu1.F1", "d.power"), ("psu1.F1", "a.power")))
    ctx = pw_ctx(holes=holes, hops=hops, d_pedal=True, extra=list(extra),
                 cables={"power_types": ["dcs"], **(cables or {})})
    ctx["cables"]["power"] = [{"from": f, "to": t, "cable": f"C{1 if style == 'serial' else n}", "style": style}
                              for n, (f, t) in enumerate(hops, 1)]
    return ctx, routed(ctx)


def test_a_serial_cable_has_one_pedal_plug_type_the_one_with_the_best_summed_ranking():
    ctx, ps = chain("serial")                      # A's right-angle exits are blocked, D's are free: the whole cable goes straight
    assert [(c["type_b"], c["exit_b"]) for c in ps.values()] == [("dcs", None), ("dcs", None)]
    # the plug at D is the one on both legs it touches: P2 starts with it, the port plug keeps the default type
    assert [c["type_a"] for c in ps.values()] == ["dc", "dcs"]
    (cab,) = ctx["power_cable_summary"]
    assert cab["plug_types"] == {"port": "dc", "pedals": ["dcs", "dcs"]} and cab["plugs"] == 3
    # nothing blocked: the default type of the list wins every plug, and so the cable
    ctx, ps = chain("serial", extra=())
    assert {c["type_b"] for c in ps.values()} == {"dc"}


def test_a_serial_cable_prefers_the_type_that_blocks_fewer_plugs_in_total():
    shelf = mm_item("i-e", "E", 90, 0, 30, 40)      # D's straight head (102..108, y 30..60) and run: 10 mm into it; D's right-angle plug is free
    ctx, ps = chain("serial", extra=[shelf, LEFT_WALL, RIGHT_WALL])
    # right-angle: A blocked on both sides (1 hit either way) + D free = 1; straight: A free + D blocked (head and run) = 2
    assert {c["type_b"] for c in ps.values()} == {"dc"}
    assert not [w for w in ctx["warnings"] if "exit_b" in w or "type_b" in w]


def test_a_forked_output_lets_each_leg_pick_its_own_type():
    ctx, ps = chain("forked")
    assert [(c["type_b"], c["exit_b"]) for c in ps.values()] == [("dc", "left"), ("dcs", None)]
    assert [c["type_a"] for c in ps.values()] == ["dc", "dc"]                    # the port plug is shared: one type
    summary = {c["id"]: c for c in ctx["power_cable_summary"]}
    assert summary["C1"]["plug_types"] == {"port": "dc", "pedals": ["dc"]} and summary["C2"]["plug_types"] == {"port": "dc", "pedals": ["dcs"]}


def test_conflicting_type_b_overrides_on_one_serial_cable_warn_and_the_first_leg_wins():
    ctx, ps = chain("serial", extra=(), cables={"overrides": {"P1": {"type_b": "dc"}, "P2": {"type_b": "dcs"}}})
    assert {c["type_b"] for c in ps.values()} == {"dc"}
    assert any("P1 type_b (dc) and P2 type_b (dcs) are on the same serial DC cable C1" in w and "dc is used for all" in w
               for w in ctx["warnings"])
    ctx, ps = chain("serial", extra=(), cables={"overrides": {"P2": {"type_b": "dcs"}}})   # one leg fixing it is enough for the cable
    assert {c["type_b"] for c in ps.values()} == {"dcs"} and not [w for w in ctx["warnings"] if "type_b" in w]
    ctx, ps = chain("forked", extra=(), cables={"overrides": {"P1": {"type_b": "dc"}, "P2": {"type_b": "dcs"}}})
    assert [c["type_b"] for c in ps.values()] == ["dc", "dcs"] and not [w for w in ctx["warnings"] if "type_b" in w]


def test_the_port_plug_of_an_on_board_supply_is_ranked_apart_from_the_pedal_plugs():
    jd = {"a": [pc.jack("power", "power", 0.5)], "d": [pc.jack("power", "power", 0.5)], "s1": [pc.jack("F1", "power_out", 0.5)]}
    ctx = pc.make_ctx({"a": (20, 60, 100, 100), "d": (150, 60, 100, 100)}, jd, ["a", "d"], {"power_type": "dc", "power_types": ["dcs"]})
    ctx["layout"]["inst_item"] = {"psu1": pc.item("i-psu1", "S", 20, 10, 60, 30)}
    ctx["layout"]["obstacles"] += [pc.item("i-wl", "WL", 38, 0, 5, 20), pc.item("i-wr", "WR", 57, 0, 10, 20)]   # into the port's two cable runs (41.5..45, 55..58.5)
    ctx["supplies"] = [{"inst": {"id": "psu1", "placement": "on_board"}, "sup": {"id": "s1"},
                        "rows": [{"port": "F1", "pedals": ["a", "d"]}]}]
    cables = [{"kind": "power", "from": "psu1.F1", "to": "a.power"}, {"kind": "power", "from": "psu1.F1", "to": "d.power"}]
    cfg = routing.settings(ctx["project"], TY)
    out = routing.power_plug_choices(ctx, cables, TY, cfg, ctx["layout"]["obstacles"], {})
    by = {cid: o for cid, jk, c, f, o in out}
    assert by["psu1"]["type"] == "dcs" and by["a"]["type"] == "dc" and by["d"]["type"] == "dc"
    assert [(c["type_a"], c["type_b"]) for c in cables] == [("dcs", "dc"), ("dcs", "dc")]          # one port plug for both legs


# --- lengths and the grid -----------------------------------------------------------------------------
def test_each_end_uses_its_own_plug_measure_in_the_minimum_length():
    ctx, ps = chain("forked", extra=(), cables={"overrides": {"P1": {"type_b": "dc"}, "P2": {"type_b": "dcs"}}}, holes=(HOLE_PW, HOLE_D))
    p1, p2 = ps["P1"], ps["P2"]
    assert p1["status"] == p2["status"] == "routed" and (p1["type_b"], p2["type_b"]) == ("dc", "dcs")
    assert p2["min_mm"] == pytest.approx(18.0 + p2["under_mm"] + p2["top_mm"] + p2["holes_used"] * 15.0, abs=0.01)
    if p1["exit_b"] != "down":
        assert p1["min_mm"] == pytest.approx(8.5 + p1["under_mm"] + p1["top_mm"] + p1["holes_used"] * 15.0, abs=0.01)
    else:   # a right-angle plug pointing down: |5 - 10 / 2| + jack height 12 + the deck 15
        assert p1["min_mm"] == pytest.approx(27.0 + p1["under_mm"] + p1["top_mm"], abs=0.01)


def test_the_power_grid_is_as_wide_as_the_widest_type_in_use():
    ctx = power_ctx(BOTH, power_type="dc")
    ctx["project"]["cables"]["power_types"] = ["dcw"]
    ctx["layout"].update(holes=[(28.5, 38.5, 40.5, 48.5)], inst_item={"psu1": mm_item("i-psu", "PSU", 100, 150, 60, 30)}, inst_placement={"psu1": "under"},
                         edge_segments=[])
    ctx["layout"]["jacks"]["sup1"] = [{"id": "F1", "label": "F1", "function": "power_out", "x": 0.2, "y": 0.0, "facing": "top"}]
    ctx["supplies"] = [{"inst": {"id": "psu1", "supply": "sup1"}, "sup": {"id": "sup1"}, "rows": []}]
    ctx["cables"] = {"power": [{"from": "psu1.F1", "to": "a.power"}]}
    (c,) = routed(ctx).values()
    assert c["type_b"] == "dcw" and ctx["routing"]["power"]["diameter_mm"] == 5.0           # both right-angle exits blocked: the 5 mm straight plug
    ctx2 = copy.deepcopy(ctx)
    ctx2["layout"]["obstacles"] = [o for o in ctx2["layout"]["obstacles"] if o["id"] not in ("i-l", "i-r")]
    (c2,) = routed(ctx2).values()
    assert c2["type_b"] == "dc" and ctx2["routing"]["power"]["diameter_mm"] == 3.5           # dcw not in use: the default's width


# --- README ---------------------------------------------------------------------------------------------
def test_the_readme_shows_the_types_per_plug_and_describes_the_plugs_of_each_dc_cable():
    ctx, ps = chain("serial")
    md = "\n".join(build.routing_section(ctx))
    assert "| P1 | power | C1 | psu1.F1 | d.power | dc / dcs |" in md and "| P2 | power | C1 | d.power | a.power | dcs |" in md
    assert "| DC cable | Style | Output | Route | Plugs | Plug types | Legs |" in md
    assert "| 3 | 1 x dc (port) + 2 x dcs | P1, P2 |" in md
    assert "plug types `dc`, `dcs`, picked per plug" in md and "type_b" in md
    ctx, ps = chain("forked")
    md = "\n".join(build.routing_section(ctx))
    assert "| 2 | 1 x dc (port) + 1 x dcs | P2 |" in md and "| 2 | 2 x dc | P1 |" in md
    plain = pw_ctx(holes=(HOLE_PW,))
    routed(plain)
    md = "\n".join(build.routing_section(plain))
    assert "Plug types" not in md and "plug `dc`" in md and "plug types" not in md


# --- the real gig -----------------------------------------------------------------------------------------
def test_one_listed_type_is_the_gig_as_before():
    pedals, supplies, ctx = gig_build()
    proj = copy.deepcopy(ctx["project"])
    assert "power_types" not in proj["cables"]
    proj["cables"]["power_types"] = [proj["cables"]["power_type"]]
    other = build.validate(ROOT / "projects" / "guitar-gig", pedals, supplies, project=proj)
    keys = ("from", "to", "exit_a", "exit_b", "min_mm", "status", "type", "type_a", "type_b")
    pick = lambda c: [{k: x.get(k) for k in keys} for x in c["cable_list"]]
    assert pick(other) == pick(ctx) and other["warnings"] == ctx["warnings"] and other["errors"] == ctx["errors"]


# --- jacks.py and layout.py read the default type like the router ---------------------------------------------
def test_a_project_with_only_power_types_has_its_first_type_as_the_default_everywhere(tmp_path):
    import jacks
    from test_check import A, B, PEDALS, SUPPLIES, pedal_jacks, project
    assert jacks.default_power_type({}) is None and jacks.default_power_type({"cables": {"power_type": "dc"}}) == "dc"
    assert jacks.default_power_type({"cables": {"power_types": ["dcs", "dc"]}}) == "dcs"
    assert jacks.default_power_type({"cables": {"power_type": "dc", "power_types": ["dcs"]}}) == "dc"
    data = {"a": pedal_jacks(), "b": [dict(j, x=0.0, y=0.1, facing="left") if j["function"] == "power" else j for j in pedal_jacks()]}
    for cables in ({"type": "ernie_ball_flat_patch_ra", "power_type": "dc_ra_2_1_low_profile"},
                   {"type": "ernie_ball_flat_patch_ra", "power_types": ["dc_ra_2_1_low_profile"]}):
        ctx = project(tmp_path, [A(0), B(90)])
        ctx["project"]["cables"] = cables
        jacks.check(ctx, PEDALS, SUPPLIES, data, defer=True)
        routing.route_project(ctx, PEDALS)
        v = next(v for v in ctx["violations"] if v["jack"] == "b.power")
        assert v["cable_type"] == "dc_ra_2_1_low_profile" and "zone" not in v, cables       # the DC plug, not the power box
        assert ctx["jack_settings"]["power_modelled"], cables


def test_the_layout_model_reads_the_default_power_type_from_power_types():
    import layout
    from test_layout import BOARD, JACKS, PEDALS as LP, SUPPLIES as LS, SUP_JACKS, TYPES as LT, canvas, ped, sup
    dc = {"dc": {"role": "power", "diameter_mm": 3.5, "plug": {"style": "right_angle", "head_depth_mm": 10.0, "head_width_mm": 10.0}}}
    inst = {"id": "psu1", "supply": "s1", "placement": "on_board", "outputs": [{"port": "F1", "pedals": ["a"]}]}
    items = design.parse_canvas(canvas(BOARD, ped("T A", 0), sup(200)))
    pts = []
    for cables in ({"type": "t", "power_type": "dc"}, {"type": "t", "power_types": ["dc"]}):
        proj = {"signal_chain": ["a"], "cables": cables, "jacks": {}, "power": {"supplies": [inst]}}
        m = layout.Model(proj, items, LP, LS, {**JACKS, "s1": SUP_JACKS}, {}, {**LT, **dc}, outlines={})
        pts.append((m.ptype is not None, m.p_depth, m._geom[(1, 0)]["port_pt"]["F1"]))
    assert pts[0] == pts[1] and pts[0][0] and pts[0][1] == 10.0


# --- a plug option that leaves its cable without a path --------------------------------------------------
CUP = [mm_item("i-t", "T", 38.5, 15, 13, 9), mm_item("i-l", "L", 38.5, 15, 3.4, 44.9), mm_item("i-r", "R", 48.1, 15, 3.4, 44.9)]
HOLE_D2 = (95.0, 45.0, 115.0, 65.0)


def cup_ctx(power_types):
    """A's power plug (45, 60) with an upside-down U of walls round the straight plug's exit (45, 27): the walls (x 38.5..41.9 / 48.1..51.5 down
    to y 59.9 and a roof 15..24) touch neither its head (42..48) nor its cable run, so the straight plug has no hit and ranks first, but its
    cable cannot get out. The right-angle plug's heads (40..50) reach 1.9 mm into both side walls (2 hits each side), its exits are outside."""
    return pw_ctx(holes=(HOLE_D2,), extra=CUP, cables={"power_type": "dcs", "power_types": power_types})


def test_a_plug_option_that_leaves_its_cable_without_a_path_is_replaced_by_one_that_routes(monkeypatch):
    calls = []
    real = routing.route_power
    monkeypatch.setattr(routing, "route_power", lambda *a, **k: (calls.append(1), real(*a, **k))[1])
    ctx = cup_ctx(["dc"])
    (c,) = routed(ctx).values()
    assert (c["type_b"], c["exit_b"], c["status"]) == ("dc", "left", "routed") and len(calls) == 2
    assert not any("no free path" in w for w in ctx["warnings"])                      # the first try's finding is dropped with it
    assert [v["jack"] for v in ctx["violations"]] == ["a.power", "a.power"]            # the price: the head is blocked by both walls
    assert [h["rects"][0][0] for h in ctx["routing"]["heads"] if h["cable"] == "P1"] == ["head"]


def test_nothing_is_routed_again_when_the_plug_has_no_other_option_or_the_second_try_is_no_better(monkeypatch):
    calls = []
    real = routing.route_power
    monkeypatch.setattr(routing, "route_power", lambda *a, **k: (calls.append(1), real(*a, **k))[1])
    ctx = cup_ctx([])                                                                    # only the straight type: no other option
    (c,) = routed(ctx).values()
    assert (c["type_b"], c["status"].startswith("unroutable"), len(calls)) == ("dcs", True, 1)
    assert any("P1 (psu1.F1 -> a.power) has no free path" in w for w in ctx["warnings"])
    calls.clear()
    def nothing_routes(*a, **k):
        real(*a, **k)
        for c in a[1]:
            if c["kind"] == "power":
                c["status"] = "unroutable: test"
        calls.append(1)
    monkeypatch.setattr(routing, "route_power", nothing_routes)
    ctx = cup_ctx(["dc"])
    (c,) = routed(ctx).values()
    assert len(calls) == 2 and (c["type_b"], c["status"]) == ("dcs", "unroutable: test")   # not better: the first choice stays


def test_a_failed_option_loses_even_to_an_infeasible_one_that_was_not_tried():
    mk = lambda **k: {"hits": [], "tidx": 0, **k}
    tried, other = mk(ok=False, failed=True), mk(ok=False, hits=[("head", None, (1.0, 2.0))] * 3)   # (the gig's monk.power: every exit lies inside the Belle Epoch)
    assert routing.plug_rank(other, "x", None) > routing.plug_rank(mk(ok=False), "x", None)
    assert routing.plug_rank(tried, "x", None) > routing.plug_rank(other, "x", None)
    assert routing.plug_rank(mk(ok=True, down=False), "x", None) < routing.plug_rank(other, "x", None)
