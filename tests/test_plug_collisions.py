"""Plug-to-plug collisions (routing.route_project, power_plug_choices, plug_collision_findings) on small hand-made layouts.
Synthetic cable types only, so the catalog's plug sizes can change. All lengths in mm."""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import design  # noqa: E402
import routing  # noqa: E402

# signal: head 20 deep x 16 wide, cable axis 10 mm out, ribbon leaves 8 mm from the jack axis, 6 mm run
# DC: head 10 x 10 (axis 5 mm out); barrel 4 mm wide from 5 to 15 mm beside the jack axis, then a 3.5 mm run
TYPES = {"ra": {"name": "test right angle", "role": "patch", "diameter_mm": 6.0, "tips": "TS",
                "plug": {"style": "right_angle", "head_depth_mm": 20.0, "head_width_mm": 16.0}},
         "dc": {"name": "test DC right angle", "role": "power", "diameter_mm": 3.5, "tips": "DC 2.1 mm",
                "plug": {"style": "right_angle", "head_depth_mm": 10.0, "head_width_mm": 10.0,
                         "body_reach_mm": 15.0, "barrel_width_mm": 4.0}}}


def item(iid, title, left, top, w, h, kind="pedal"):
    return {"id": iid, "kind": kind, "title": title, "rot": 0, "w_mm": w, "h_mm": h, "left_mm": left, "top_mm": top}


def jack(jid, fn, fx, label=None, facing="top", fy=0.0):
    return {"id": jid, "label": label or jid.capitalize(), "function": fn, "x": fx, "y": fy, "facing": facing}


def make_ctx(pedals, jd, chain, cables=None, power=(), zones=None, validation=None):
    """Board 0..300 x 0..200; `pedals` {id: (left, top, w, h)}; every jack on the pedals' top edge facing the back."""
    placed = {pid: item(f"i-{pid}", pid.upper(), *geo) for pid, geo in pedals.items()}
    layout = {"board": item("i-board", "Board", 0, 0, 300, 200, "pedalboard"), "placed": placed,
              "obstacles": list(placed.values()), "inst_item": {}, "jacks": jd, "outward_mm": 6.3}
    return {"project": {"cables": cables or {}, "validation": validation or {}}, "chain": list(chain), "layout": layout,
            "errors": [], "warnings": [], "violations": [], "cables": {"power": list(power)}, "fixed_zones": zones or {}}


def zone(layout, pid, jk, out=6.3, side=7.0, kind="audio"):
    pt = design.jack_point(layout["placed"][pid], jk["x"], jk["y"])
    facing = design.jack_facing(layout["placed"][pid], jk["facing"])
    return {"rect": design.clearance_rect(pt, facing, out, side), "facing": facing, "zone": kind, "label": jk["label"]}


def route(ctx):
    routing.route_project(ctx, {}, cable_types=TYPES)
    return ctx


def one_pedal(power_override=None, with_zone=True, validation=None):
    """Pedal A (20..120 x 60..160), `out` at (50, 60) and `power` at (70, 60), both facing the back. The `out` fixed box is
    (43, 53.7, 57, 60). The DC plug's left barrel (55..65 x 53..57) reaches 2 mm into it and its left cable run
    (51.5..55 x 53.25..56.75) reaches 3.5 mm in x and 3.05 mm in y; the right side (barrel 75..85) is clear."""
    jd = {"a": [jack("out", "output", 0.3, "Output"), jack("power", "power", 0.5, "Power")]}
    cables = {"power_type": "dc", "overrides": {"P1": {"exit_b": power_override}} if power_override else {}}
    ctx = make_ctx({"a": (20, 60, 100, 100)}, jd, ["a"], cables, [{"from": "psu1.1", "to": "a.power"}], validation=validation)
    if with_zone:
        ctx["fixed_zones"] = {"a.out": zone(ctx["layout"], "a", jd["a"][0])}
    return ctx


def test_a_right_angle_dc_plug_over_a_fixed_box_passes_under_it_and_is_no_collision():
    """The DC plug's left cable run reaches 3.5 mm in x and 3.05 mm in y into the `out` fixed box (the barrel only 2.0): the deepest
    overlap, 3.05 mm, is the pass (owner 2026-11-03: a right-angle DC plug is plugged diagonally and goes under the patch cables)."""
    ctx = route(one_pedal(power_override="left"))
    assert ctx["plug_collisions"] == [] and ctx["violations"] == []
    (u,) = ctx["plug_under"]
    assert (u["dc"], u["signal"], u["cable"], u["signal_cable"]) == ("a.power", "a.out", "P1", None)
    assert u["depth_mm"] == pytest.approx(3.05)
    assert not any("collides" in w for w in ctx["warnings"])
    assert routing.under_text(u) == "P1 (a.power) passes under the plug at a.out: plug it diagonally"


def test_a_side_whose_only_overlap_is_one_signal_plug_ties_with_a_free_side_and_the_length_decides():
    ctx = route(one_pedal())
    (p,) = [c for c in ctx["cable_list"] if c["kind"] == "power"]
    assert p["exit_b"] == "left" and ctx["plug_collisions"] == []       # as without the fixed box: both sides are collision free, left is the first
    assert [u["signal"] for u in ctx["plug_under"]] == ["a.out"]        # and the left side passes under a.out
    blind = one_pedal(with_zone=False)
    route(blind)
    (q,) = [c for c in blind["cable_list"] if c["kind"] == "power"]
    assert q["exit_b"] == "left" and blind["plug_collisions"] == [] and blind["plug_under"] == []
    assert q["min_mm"] == pytest.approx(p["min_mm"])                    # the same cable: the fixed box does not change the choice


def test_an_override_keeps_the_side_and_the_pass_is_reported():
    ctx = route(one_pedal(power_override="right"))
    (p,) = [c for c in ctx["cable_list"] if c["kind"] == "power"]
    assert p["exit_b"] == "right" and ctx["plug_collisions"] == [] and ctx["plug_under"] == []   # the right side is clear of the box
    ctx = route(one_pedal(power_override="left"))
    (p,) = [c for c in ctx["cable_list"] if c["kind"] == "power"]
    assert p["exit_b"] == "left" and ctx["plug_collisions"] == [] and len(ctx["plug_under"]) == 1


STRAIGHT = {"name": "test DC straight", "role": "power", "diameter_mm": 3.5, "tips": "DC 2.1 mm",
            "plug": {"style": "straight", "head_depth_mm": 10.0, "head_width_mm": 10.0}}


def straight_pedal(validation=None):
    """Pedal A as in `one_pedal`, with `out` at x 60 (fixed box 53..67 x 53.7..60) and a STRAIGHT DC plug at the power jack (x 70, head
    65..75 x 50..60): the head reaches 2 mm in x (and 6.3 in y) into the box. A straight plug never passes under anything."""
    jd = {"a": [jack("out", "output", 0.4, "Output"), jack("power", "power", 0.5, "Power")]}
    ctx = make_ctx({"a": (20, 60, 100, 100)}, jd, ["a"], {"power_type": "dcs"}, [{"from": "psu1.1", "to": "a.power"}], validation=validation)
    ctx["fixed_zones"] = {"a.out": zone(ctx["layout"], "a", jd["a"][0])}
    routing.route_project(ctx, {}, cable_types={**TYPES, "dcs": STRAIGHT})
    return ctx


def test_a_straight_dc_plug_over_a_fixed_box_is_a_collision():
    ctx = straight_pedal()
    (col,) = ctx["plug_collisions"]
    assert (col["jack"], col["with"], col["part"], col["with_part"]) == ("a.out", "a.power", "box", "head")
    assert col["depth_mm"] == pytest.approx(2.0) and ctx["plug_under"] == []
    assert any(w.startswith("clearance: a.out (Output, last output, fixed box) collides with the plug at a.power (DC plug)") for w in ctx["warnings"])


def test_strict_clearance_makes_collisions_errors():
    ctx = straight_pedal(validation={"strict_clearance": True})
    assert any("collides with the plug at a.power" in e for e in ctx["errors"])
    assert not any("collides" in w for w in ctx["warnings"])
    loose = straight_pedal()
    assert not any("collides" in e for e in loose["errors"])


def test_a_dc_plug_that_passes_under_a_signal_plug_is_still_blocked_by_a_pedal_body():
    """a.power faces right at the pedal's right edge (x 120): the 10 mm head (120..130) reaches 6 mm into pedal B (124..): blocked, whatever it
    also passes under."""
    jd = {"a": [jack("power", "power", 1.0, "Power", facing="right", fy=0.5), jack("out", "output", 1.0, "Output", facing="right", fy=0.8)],
          "b": [jack("in", "input", 0.5)]}
    ctx = make_ctx({"a": (20, 60, 100, 100), "b": (124, 60, 100, 100)}, jd, ["a"], {"power_type": "dc"}, [{"from": "psu1.1", "to": "a.power"}])
    ctx["fixed_zones"] = {"a.out": zone(ctx["layout"], "a", jd["a"][1])}
    route(ctx)
    assert any(v["jack"] == "a.power" and v["obstacle"] == "B" for v in ctx["violations"])


# --- the pass-under rule on bare footprints ----------------------------------------------------------
# a right-angle DC plug passes under a signal footprint only when both jacks face the same way (owner 2026-11-03)
def dcf(parts, right_angle=True, facing="top"):
    return routing.DcRects(parts, right_angle, facing)


def sigf(parts, facing="top"):
    return routing.SigRects(parts, facing)


def under_of(fp, meta=None):
    ctx = {"plug_collisions": []}
    sink = []
    routing.plug_collision_findings(ctx, fp, meta or {}, sink)
    return ctx, sink


def test_a_right_angle_dc_plug_over_one_signal_plug_is_one_pass_and_no_collision():
    ctx, sink = under_of({"a.power": dcf([("head", (0, 0, 10, 10))]), "b.out": sigf([("head", (7, 0, 20, 10))])})
    assert ctx["plug_collisions"] == [] and sink == []
    assert [(u["dc"], u["signal"], u["depth_mm"]) for u in ctx["plug_under"]] == [("a.power", "b.out", pytest.approx(3.0))]


@pytest.mark.parametrize("dc_facing,sig_facing,passes", [
    ("top", "top", True), ("left", "left", True),                  # the same facing: a pass
    ("top", "left", False), ("right", "top", False),               # perpendicular: an ordinary collision
    ("top", "down", False), ("left", "right", False),              # opposite: an ordinary collision
])
def test_a_dc_plug_passes_under_a_signal_plug_only_with_the_same_facing(dc_facing, sig_facing, passes):
    ctx, sink = under_of({"a.power": dcf([("head", (0, 0, 10, 10))], True, dc_facing), "b.out": sigf([("head", (7, 0, 20, 10))], sig_facing)})
    assert [(u["dc"], u["signal"]) for u in ctx["plug_under"]] == ([("a.power", "b.out")] if passes else [])
    assert [(c["jack"], c["with"], c["depth_mm"]) for c in ctx["plug_collisions"]] == ([] if passes else [("a.power", "b.out", pytest.approx(3.0))])
    assert len(sink) == (0 if passes else 1)
    assert routing.pass_eligible(dcf([], True, dc_facing), sigf([], sig_facing)) == passes
    assert routing.pass_eligible(sigf([], sig_facing), dcf([], True, dc_facing)) == passes


def test_a_footprint_without_a_facing_never_passes():
    assert not routing.pass_eligible(dcf([], True, None), sigf([], None)) and not routing.pass_eligible(dcf([], True), [])


def test_a_dc_plug_over_two_signal_plugs_passes_under_the_deeper_one_and_collides_with_the_other():
    fp = {"a.power": dcf([("head", (0, 0, 10, 10))]), "b.out": sigf([("head", (8, 0, 20, 10))]), "c.out": sigf([("head", (-9, 0, 4, 10))])}   # 2 mm and 4 mm deep
    ctx, _ = under_of(fp)
    assert [(u["dc"], u["signal"]) for u in ctx["plug_under"]] == [("a.power", "c.out")]
    assert [(c["jack"], c["with"], c["depth_mm"]) for c in ctx["plug_collisions"]] == [("a.power", "b.out", pytest.approx(2.0))]
    fp["c.out"] = sigf([("head", (-9, 0, 4, 10))], "left")           # the deeper one faces another way: the pass goes to the other
    ctx, _ = under_of(fp)
    assert [(u["dc"], u["signal"]) for u in ctx["plug_under"]] == [("a.power", "b.out")]
    assert [(c["jack"], c["with"]) for c in ctx["plug_collisions"]] == [("a.power", "c.out")]


def test_two_dc_plugs_over_the_same_signal_plug_one_passes_and_one_collides():
    fp = {"p2.power": dcf([("head", (10, 0, 20, 10))]), "p1.power": dcf([("head", (0, 0, 10, 10))]), "s.out": sigf([("head", (5, 0, 15, 10))])}
    ctx, _ = under_of(fp)
    assert [(u["dc"], u["signal"]) for u in ctx["plug_under"]] == [("p1.power", "s.out")]       # the first in natural key order
    assert [(c["jack"], c["with"]) for c in ctx["plug_collisions"]] == [("p2.power", "s.out")]


def test_a_straight_dc_plug_and_two_dc_plugs_never_pass():
    ctx, _ = under_of({"a.power": dcf([("head", (0, 0, 10, 10))], False), "b.out": sigf([("head", (7, 0, 20, 10))])})
    assert ctx["plug_under"] == [] and len(ctx["plug_collisions"]) == 1
    ctx, _ = under_of({"a.power": dcf([("head", (0, 0, 10, 10))]), "b.power": dcf([("head", (7, 0, 20, 10))])})
    assert ctx["plug_under"] == [] and [(c["jack"], c["with"]) for c in ctx["plug_collisions"]] == [("a.power", "b.power")]


def test_collision_count_ranks_a_one_signal_overlap_like_a_free_side():
    """An option of a right-angle DC plug that overlaps one signal plug of the same facing is as good as a free one; with a second signal plug,
    or when that signal plug already passes under another DC plug, for a straight DC plug or another facing, the overlap counts."""
    head = [("head", (0, 0, 10, 10))]
    near = {"s1": sigf([("head", (7, 0, 20, 10))])}
    assert routing.collision_count({"rects": dcf(head)}, "d.power", near) == 0
    assert routing.collision_count({"rects": dcf(head, True, "left")}, "d.power", near) == 1   # perpendicular: counts
    assert routing.collision_count({"rects": sigf(head)}, "d.power", near) == 1                 # a signal plug against a signal plug
    assert routing.collision_count({"rects": dcf(head, False)}, "d.power", near) == 1
    assert routing.collision_count({"rects": dcf(head)}, "d.power", {**near, "s2": sigf([("head", (-9, 0, 4, 10))])}) == 1    # the second one counts
    taken = {**near, "c.power": dcf([("head", (7, 0, 20, 10))])}                               # c.power comes first (natural order) and takes s1
    assert routing.collision_count({"rects": dcf(head)}, "d.power", taken) == 2                # s1 (already paired) and c.power itself (DC against DC)
    taken = {"s1": near["s1"], "a.power": dcf([("head", (15, 0, 30, 10))])}                    # a.power (not in the way) sorts before d.power
    assert routing.collision_count({"rects": dcf(head)}, "d.power", taken) == 1                  # and has taken s1 already
    assert routing.collision_count({"rects": dcf(head)}, "z.power", taken) == 1
    assert routing.collision_count({"rects": dcf(head)}, "A.power", taken) == 0                  # "A" sorts first: it takes s1 itself
    taken = {"s1": near["s1"], "a.power": dcf([("head", (15, 0, 30, 10))], True, "left")}      # a.power faces another way: it cannot take s1
    assert routing.collision_count({"rects": dcf(head)}, "d.power", taken) == 0
    # a signal option overlapping one DC plug: free too
    assert routing.collision_count({"rects": sigf([("head", (7, 0, 20, 10))])}, "s1", {"d.power": dcf(head)}) == 0
    assert routing.collision_count({"rects": sigf([("head", (7, 0, 20, 10))])}, "s1", {"d.power": dcf(head, False)}) == 1
    assert routing.collision_count({"rects": sigf([("head", (7, 0, 20, 10))], "down")}, "s1", {"d.power": dcf(head)}) == 1


def facing_pedal(out_facing, power_facing):
    """Pedal A (20..120 x 60..160) with `out` on its top edge at x 65 and `power` at x 70, each facing as given. The `out` fixed box reaches 6.3 mm
    out of the jack and 7 mm to each side; the DC plug's 10 mm head too, whatever side its cable leaves by."""
    jd = {"a": [jack("out", "output", 0.45, "Output", out_facing), jack("power", "power", 0.5, "Power", power_facing)]}
    ctx = make_ctx({"a": (20, 60, 100, 100)}, jd, ["a"], {"power_type": "dc"}, [{"from": "psu1.1", "to": "a.power"}])
    ctx["fixed_zones"] = {"a.out": zone(ctx["layout"], "a", jd["a"][0])}
    return route(ctx)


def test_the_build_lets_a_dc_plug_pass_under_a_signal_plug_only_with_the_same_facing():
    """Both facing right: the head (70..80 x 55..65) reaches 1.3 mm into the box (65..71.3 x 53..67) whichever side the cable takes: a pass.
    The DC jack facing the back (head 65..75 x 50..60) overlaps the box 6.3 mm deep: perpendicular, a collision, and no pass."""
    ctx = facing_pedal("right", "right")
    assert ctx["plug_collisions"] == [] and [(u["dc"], u["signal"]) for u in ctx["plug_under"]] == [("a.power", "a.out")]
    assert ctx["plug_under"][0]["depth_mm"] == pytest.approx(1.3)
    ctx = facing_pedal("right", "top")
    assert ctx["plug_under"] == [] and [(c["jack"], c["with"], c["depth_mm"]) for c in ctx["plug_collisions"]] == [("a.out", "a.power", pytest.approx(6.3))]
    ctx = facing_pedal("top", "top")                                   # the same facing again (box 58..72 x 53.7..60): a pass
    assert ctx["plug_collisions"] == [] and len(ctx["plug_under"]) == 1


def three_pedals():
    """B (100..200 x 60..160) has `in` at (130, 60) and `out` at (154, 60) facing the back (heads 122..138 and 146..162). A
    (230..280) sends S1 into b.in from the right, C (20..70) takes S2 on the left. b.in's right cable (138..144 x 47..53)
    and b.out's left cable (140..146) overlap by 4 mm; b.out's right option clears everything."""
    jd = {"a": [jack("out", "output", 0.5)], "b": [jack("in", "input", 0.3), jack("out", "output", 0.54)],
          "c": [jack("in", "input", 0.5)]}
    return make_ctx({"a": (230, 60, 50, 100), "b": (100, 60, 100, 100), "c": (20, 60, 50, 100)}, jd, ["a", "b", "c"], {"type": "ra"})


def test_a_collision_with_an_earlier_cables_plug_changes_the_side_choice(monkeypatch):
    ctx = route(three_pedals())
    s1, s2 = [c for c in ctx["cable_list"] if c["kind"] == "signal"]
    assert s1["exit_b"] == "right"                                      # nearest side towards A
    assert s2["exit_a"] == "right" and ctx["plug_collisions"] == []     # away from C, to stay clear of b.in's plug
    monkeypatch.setattr(routing, "collision_count", lambda *a, **k: 0)   # the old ranking: shortest route only
    old = route(three_pedals())
    assert [c["exit_a"] for c in old["cable_list"] if c["kind"] == "signal"][1] == "left"
    assert len(old["plug_collisions"]) == 1                              # which the check then reports
    col = old["plug_collisions"][0]
    assert (col["jack"], col["with"], col["depth_mm"]) == ("b.in", "b.out", pytest.approx(4.0))
    assert (col["part"], col["with_part"]) == ("cable", "cable")


def test_a_signal_override_is_kept_and_the_other_plugs_move_away_from_it():
    ctx = three_pedals()
    ctx["project"]["cables"]["overrides"] = {"S2": {"exit_a": "left"}}
    route(ctx)
    s1, s2 = [c for c in ctx["cable_list"] if c["kind"] == "signal"]
    # b.in was chosen (right) before b.out's fixed left side was known; the second round re-chooses it away from that plug
    assert s2["exit_a"] == "left" and s1["exit_b"] == "left" and ctx["plug_collisions"] == []


def test_two_overrides_that_collide_are_both_kept_and_the_collision_is_reported():
    ctx = three_pedals()
    ctx["project"]["cables"]["overrides"] = {"S2": {"exit_a": "left"}, "S1": {"exit_b": "right"}}
    route(ctx)
    s1, s2 = [c for c in ctx["cable_list"] if c["kind"] == "signal"]
    assert (s1["exit_b"], s2["exit_a"]) == ("right", "left") and [(c["jack"], c["with"]) for c in ctx["plug_collisions"]] == [("b.in", "b.out")]


def test_touching_footprints_are_no_collision_but_a_real_overlap_is():
    ctx = {"plug_collisions": []}
    sink = []
    fp = {"a.x": [("head", (0, 0, 10, 10))], "b.y": [("box", (9.5, 0, 20, 10))]}        # 0.5 mm <= TOL (0.6)
    routing.plug_collision_findings(ctx, fp, {}, sink)
    assert ctx["plug_collisions"] == [] and sink == []
    fp["b.y"] = [("box", (9.0, 2, 20, 10))]                                              # 1.0 x 8 mm
    meta = {"a.x": {"kind": "k", "label": "X", "how": "k"}, "b.y": {"kind": "other kind", "label": "Y", "how": "o"}}
    routing.plug_collision_findings(ctx, fp, meta, sink)
    (col,) = ctx["plug_collisions"]
    assert col["depth_mm"] == pytest.approx(1.0) and col["with_kind"] == "other kind" and len(sink) == 1
    assert sink[0].startswith("clearance: a.x (X, k) collides with the plug at b.y (other kind): 1.0 mm")


def test_one_finding_per_pair_with_the_deepest_part_pair():
    ctx = {"plug_collisions": []}
    fp = {"a.x": [("head", (0, 0, 10, 10)), ("barrel", (10, 0, 30, 4))], "b.y": [("head", (8, 0, 20, 10)), ("cable", (28, 2, 40, 4))]}
    routing.plug_collision_findings(ctx, fp, {}, [])
    (col,) = ctx["plug_collisions"]
    # head/head 2 x 10, barrel/head 10 x 4 (min 4), barrel/cable 2 x 2: the barrel into b.y's head is deepest
    assert (col["part"], col["with_part"], col["depth_mm"]) == ("barrel", "head", pytest.approx(4.0))


def test_the_shared_plug_of_a_serial_chain_does_not_collide_with_itself():
    jd = {"a": [jack("power", "power", 0.5)], "b": [jack("power", "power", 0.5)]}
    power = [{"from": "psu1.1", "to": "a.power"}, {"from": "a.power", "to": "b.power"}]    # one cable through both pedals
    ctx = route(make_ctx({"a": (20, 60, 100, 100), "b": (150, 60, 100, 100)}, jd, ["a", "b"], {"power_type": "dc"}, power))
    assert ctx["plug_collisions"] == []
    taken = {}
    cables = [{"kind": "power", "from": h["from"], "to": h["to"]} for h in power]
    ctx = make_ctx({"a": (20, 60, 100, 100), "b": (150, 60, 100, 100)}, jd, ["a", "b"], {"power_type": "dc"}, power)
    cfg = routing.settings(ctx["project"], TYPES)
    out = routing.power_plug_choices(ctx, cables, TYPES, cfg, ctx["layout"]["obstacles"], taken)
    assert [f"{cid}.{jk['id']}" for cid, jk, *_ in out] == ["a.power", "b.power"] and set(taken) == {"a.power", "b.power"}


def test_the_shared_plug_of_a_forked_port_is_one_footprint():
    jd = {"a": [jack("power", "power", 0.5)], "d": [jack("power", "power", 0.5)],
          "s1": [jack("F1", "power_out", 0.5)]}
    ctx = make_ctx({"a": (20, 60, 100, 100), "d": (150, 60, 100, 100)}, jd, ["a", "d"], {"power_type": "dc"})
    ctx["layout"]["inst_item"] = {"psu1": item("i-psu1", "S", 20, 10, 60, 30)}
    ctx["supplies"] = [{"inst": {"id": "psu1", "placement": "on_board"}, "sup": {"id": "s1"},
                        "rows": [{"port": "F1", "pedals": ["a", "d"]}]}]
    cables = [{"kind": "power", "from": "psu1.F1", "to": "a.power"}, {"kind": "power", "from": "psu1.F1", "to": "d.power"}]
    taken = {}
    cfg = routing.settings(ctx["project"], TYPES)
    out = routing.power_plug_choices(ctx, cables, TYPES, cfg, ctx["layout"]["obstacles"], taken)
    assert [f"{cid}.{jk['id']}" for cid, jk, *_ in out] == ["a.power", "d.power", "psu1.F1"] and set(taken) == {"a.power", "d.power", "psu1.F1"}
    assert routing.power_plug_keys(ctx, TYPES, cfg) == {"a.power", "d.power", "psu1.F1"}
    ctx["plug_collisions"] = []
    routing.plug_collision_findings(ctx, taken, {}, [])
    assert ctx["plug_collisions"] == []


def test_two_fixed_boxes_of_the_same_pedal_are_no_collision_but_those_of_different_pedals_are():
    """A (20..120) has `out` at x 120 (audio box 113..127) and `power` at x 113 (power box 106..120): they overlap by 7 mm, but nothing can
    move two fixed boxes of one pedal apart. B (124..224), `in` at x 124 (box 117..131), overlaps both of them (a.out by 10 mm in x but only 6.3 in y, the depth; a.power by 3)."""
    jd = {"a": [jack("out", "output", 1.0), jack("power", "power", 0.93)], "b": [jack("in", "input", 0.0)]}
    ctx = make_ctx({"a": (20, 60, 100, 100), "b": (124, 60, 100, 100)}, jd, ["a", "b"])
    lay = ctx["layout"]
    ctx["fixed_zones"] = {"a.out": zone(lay, "a", jd["a"][0]), "a.power": zone(lay, "a", jd["a"][1], 6.3, 7.0, "power"),
                          "b.in": zone(lay, "b", jd["b"][0])}
    route(ctx)
    pairs = {(c["jack"], c["with"]): c["depth_mm"] for c in ctx["plug_collisions"]}
    assert pairs == {("a.out", "b.in"): pytest.approx(6.3), ("a.power", "b.in"): pytest.approx(3.0)}
    assert not any("a.out" in w and "a.power" in w for w in ctx["warnings"])
    assert routing.same_item_boxes("a.out", [("box", (0, 0, 1, 1))], "a.power", [("box", (0, 0, 1, 1))])
    assert not routing.same_item_boxes("a.out", [("box", (0, 0, 1, 1))], "b.in", [("box", (0, 0, 1, 1))])
    assert not routing.same_item_boxes("a.out", [("box", (0, 0, 1, 1))], "a.power", [("head", (0, 0, 1, 1))])   # a plug of that pedal is movable


def test_a_signal_plug_does_not_move_away_from_a_dc_plug_that_passes_under_it(monkeypatch):
    """a.out (x 50, head 42..58, a right cable at 58..64 x 47..53) sends S1 to b on the right. a.power (x 77) has a long DC head (20 deep:
    cable axis y 50, left run 58.5..62, left barrel 62..72) and its exit is fixed to the left by an override: it clears a.out's head but its
    run and barrel reach into a.out's RIGHT cable. That used to be a collision that moved a.out to the left in the next round; a right-angle
    DC plug passes under one signal plug now, so a.out keeps its shorter right side (one round or three)."""
    types = {**TYPES, "dcl": {**TYPES["dc"], "plug": {**TYPES["dc"]["plug"], "head_depth_mm": 20.0}}}
    jd = {"a": [jack("out", "output", 0.3), jack("power", "power", 0.57)], "b": [jack("in", "input", 0.5)]}

    def build(rounds):
        monkeypatch.setattr(routing, "SIDE_ROUNDS", rounds)
        ctx = make_ctx({"a": (20, 60, 100, 100), "b": (230, 60, 50, 100)}, jd, ["a", "b"],
                       {"type": "ra", "power_type": "dcl", "overrides": {"P1": {"exit_b": "left"}}}, [{"from": "psu1.1", "to": "a.power"}])
        routing.route_project(ctx, {}, cable_types=types)
        (s1,) = [c for c in ctx["cable_list"] if c["kind"] == "signal"]
        (p1,) = [c for c in ctx["cable_list"] if c["kind"] == "power"]
        return ctx, s1, p1
    for rounds in (1, 3):
        ctx, s1, p1 = build(rounds)
        assert (s1["exit_a"], p1["exit_b"]) == ("right", "left") and ctx["plug_collisions"] == []
        assert [(u["dc"], u["signal"]) for u in ctx["plug_under"]] == [("a.power", "a.out")]


def test_gig_fixture_readme_lists_the_passes_and_the_picture_draws_power_below_the_patch_cables():
    from test_layout import gig_build
    import build
    import svgdraw
    pedals, supplies, ctx = gig_build()
    assert len(ctx["plug_under"]) == 7 and len(ctx["plug_collisions"]) == 4          # (7 collisions before the rule and the DC exit offset 8.4)
    md = build.project_readme(ctx, pedals)
    assert "- P6.3 (danelectro_3699.power) passes under the plug at danelectro_3699.out: plug it diagonally" in md
    assert md.count("passes under the plug at") == 7
    names = {pid: pedals[pid]["name"] for pid in ctx["chain"]}
    svg = svgdraw.render(ctx, names)
    assert 0 < svg.index('class="power-cable"') < svg.index('class="cable"')
