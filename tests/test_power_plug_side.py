"""DC plug side by cable length (`routing.plug_rank` / `rank_pool` / `dc_estimator` / `refine_dc_sides`, the layout surrogate's `_dc_length`).
Hand-made cases on the board of test_power_routing: pedal A (20..70 x 60..160) with its power jack at (45, 60) facing top (exits left
(36.5, 55) / right (53.5, 55), the plug measures 8.5 mm), the supply PSU under the board (F1 starts the cable at (112, 145)), holes by
the cases. Lengths in mm."""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import routing  # noqa: E402
from test_power_routing import HOLE_A, HOLE_FAR, TY, pw_ctx  # noqa: E402
from test_power_types import RIGHT_WALL, routed  # noqa: E402

HOLE_LEFT = (4.5, 38.5, 16.5, 48.5)   # left of A's left edge (x 20)


def one(holes, **kw):
    ctx = pw_ctx(holes=holes, **kw)
    (c,) = routed(ctx).values()
    return ctx, c


def test_a_free_plug_takes_the_side_towards_the_hole():
    ctx, c = one((HOLE_FAR,))                       # the hole is right of the pedal: the old tie-break took "left" (the first option)
    assert c["status"] == "routed" and c["exit_b"] == "right"
    other = one((HOLE_FAR,), cables={"overrides": {"P1": {"exit_b": "left"}}})[1]
    assert other["exit_b"] == "left" and c["min_mm"] < other["min_mm"] - 5
    assert ctx["routing"]["power"]["side_savings"]["plugs"] == 1 and ctx["routing"]["power"]["side_savings"]["saved_mm"] > 5


def test_the_old_side_stays_when_it_is_also_the_shorter_one():
    ctx, c = one((HOLE_LEFT,))
    assert c["exit_b"] == "left" and ctx["routing"]["power"]["side_savings"] == {"plugs": 0, "saved_mm": 0.0}


def test_an_override_keeps_its_side_whatever_the_length():
    ctx, c = one((HOLE_FAR,), cables={"overrides": {"P1": {"exit_b": "left"}}})
    assert c["exit_b"] == "left" and ctx["routing"]["power"]["side_savings"]["plugs"] == 0


def test_a_blocked_side_never_wins_on_length():
    ctx, c = one((HOLE_FAR,), extra=[RIGHT_WALL])   # the wall blocks the right side (and the hole is on that side)
    assert c["exit_b"] == "left"
    assert [v["side"] for v in ctx["violations"] if v["jack"] == "a.power"] == []


def test_length_only_tells_sides_apart_never_the_types_of_the_list():
    # no hole: the straight type (listed first) measures 18 mm, the right-angle one 8.5 mm; the list still decides
    ctx = pw_ctx(holes=(), cables={"power_type": "dcs", "power_types": ["dc"]})
    (c,) = routed(ctx).values()
    assert c["type_b"] == "dcs"


def test_the_rank_compares_the_length_before_the_overlap_and_after_the_fit():
    mk = lambda **k: {"hits": [], "tidx": 0, "type": "dc", **k}
    short, long_ = mk(length=10.0, hits=[("head", None, (3.0, 3.0))]), mk(length=40.0, hits=[("head", None, (1.0, 1.0))])
    ranked = routing.rank_pool([long_, short], "x", None)
    assert min(ranked, key=lambda x: x[0])[1] is short            # one blocked part each, more overlap, but the shorter cable
    blocked = mk(length=0.0, hits=[("head", None, (1.0, 1.0))] * 2)
    assert routing.best_option([blocked, long_], "x", None) is long_   # the fit (blocked parts) comes first
    down = mk(length=90.0, down=True)
    assert routing.best_option([short, down], "x", None) is down        # down wins even when longer
    assert routing.best_option([long_, short], "x", None, length=False) is long_   # the old ranking: the first of the equals


def test_both_legs_of_a_serial_plug_decide_its_side():
    # a -> d in a serial chain: a's plug ends the leg from the port and starts the leg to d (to the right of it)
    ctx = pw_ctx(holes=(HOLE_FAR,), hops=(("psu1.F1", "a.power"), ("a.power", "d.power")), d_pedal=True)
    legs = routed(ctx)
    side = {c["id"]: c["exit_b"] for c in legs.values()}
    assert side["P1"] == "right"
    forced = pw_ctx(holes=(HOLE_FAR,), hops=(("psu1.F1", "a.power"), ("a.power", "d.power")), d_pedal=True,
                    cables={"overrides": {"P1": {"exit_b": "left"}}})
    worse = routed(forced)
    assert sum(c["min_mm"] for c in legs.values()) < sum(c["min_mm"] for c in worse.values())


def test_the_surrogate_takes_the_side_towards_the_hole_like_the_build():
    import power
    from test_layout import TYPES as LT, model as layout_model, ped, at
    from test_power_routing import CFG
    from test_routing import DC
    m = layout_model([ped("T A", 0)], chain=("a",), project_extra={"cables": {"type": "t", "power_type": "dc"}}, types={**LT, **DC})

    def side(hole):
        m._near_memo.clear()   # (the answers are kept per query point and covered set, not per index)
        index = power.HoleIndex([hole])
        m.power_setup = {"index": index, "edges": power.HoleIndex([]), "cfg": CFG, "radius": 1.6, "crossings": power.Crossings(index, None, CFG)}
        m.set_wiring([((100.0, 100.0), ["a"], True)])
        _, det = m.score(at((25.4, 50.8, 0)), detail=True)
        return det["plugs"]["a.power"]["side"], det["terms"]["power"][0]
    right, left = side((120.0, 10.0)), side((-30.0, 10.0))
    assert right[0] == "right" and left[0] == "left"       # (the old tie-break took "left" in both)
    # the power term follows the chosen exit: the cable ends at the plug's exit and pays its measure, not the jack's measure point
    assert right[1] > 0 and left[1] > 0


def test_the_gig_fixture_needs_less_dc_cable_than_with_the_old_tie_break_and_no_new_findings():
    from test_layout import gig_build
    _, _, ctx = gig_build()
    total = sum(c["min_mm"] for c in ctx["power_cable_summary"])
    assert total < 3355 - 100            # the old tie-break (left first) needed 3355 mm; belle_epoch / analog_chorus / danelectro_3699 went right
    sides = {c["to"]: c["exit_b"] for c in ctx["cable_list"] if c["kind"] == "power"}
    assert [sides[k] for k in ("belle_epoch.power", "analog_chorus.power", "danelectro_3699.power")] == ["right"] * 3
    assert len([w for w in ctx["warnings"] if w.startswith("clearance")]) == 12 and ctx["errors"] == []   # as many findings as before
    saving = ctx["routing"]["power"]["side_savings"]
    assert saving["plugs"] == 3 and saving["saved_mm"] > 100
