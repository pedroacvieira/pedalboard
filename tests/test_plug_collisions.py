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


def test_collision_depth_of_a_dc_plug_into_a_fixed_box_is_hand_computed():
    ctx = route(one_pedal(power_override="left"))
    (col,) = ctx["plug_collisions"]
    assert (col["jack"], col["with"], col["part"], col["with_part"]) == ("a.out", "a.power", "box", "cable")
    assert col["depth_mm"] == pytest.approx(3.05)                       # min(3.5, 3.05): the cable run, deeper than the barrel (2.0)
    assert col["with_kind"] == "DC plug" and col["kind"] == "last output, fixed box" and col["side"] is None
    assert ctx["violations"] == []                                      # not a blocked plug
    assert any(w.startswith("clearance: a.out (Output, last output, fixed box) collides with the plug at a.power (DC plug): 3.")
               and w.endswith(" mm (its box into the cable run)") for w in ctx["warnings"])
    assert "(its box into the cable run)" in routing.collision_text(col)


def test_power_side_flips_to_the_side_without_a_collision():
    ctx = route(one_pedal())
    (p,) = [c for c in ctx["cable_list"] if c["kind"] == "power"]
    assert p["exit_b"] == "right" and ctx["plug_collisions"] == []
    blind = one_pedal(with_zone=False)                                  # without the fixed box the first side (left) wins
    route(blind)
    (q,) = [c for c in blind["cable_list"] if c["kind"] == "power"]
    assert q["exit_b"] == "left" and blind["plug_collisions"] == []


def test_an_override_keeps_the_side_and_the_collision_is_reported():
    ctx = route(one_pedal(power_override="left"))
    (p,) = [c for c in ctx["cable_list"] if c["kind"] == "power"]
    assert p["exit_b"] == "left" and len(ctx["plug_collisions"]) == 1
    assert ctx["plug_collisions"][0]["with"] == "a.power"


def test_strict_clearance_makes_collisions_errors():
    ctx = route(one_pedal(power_override="left", validation={"strict_clearance": True}))
    assert any("collides with the plug at a.power" in e for e in ctx["errors"])
    assert not any("collides" in w for w in ctx["warnings"])
    loose = route(one_pedal(power_override="left"))
    assert not any("collides" in e for e in loose["errors"])


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


def test_a_signal_plug_moves_away_from_a_dc_plug_that_was_chosen_after_it(monkeypatch):
    """a.out (x 50, head 42..58, a right cable at 58..64 x 47..53) sends S1 to b on the right. a.power (x 77) has a long DC head (20 deep:
    cable axis y 50, left run 58.5..62, left barrel 62..72) and its exit is fixed to the left by an override: it clears a.out's head but its
    run and barrel reach into a.out's RIGHT cable. The first pass chooses the signal sides before the DC plugs exist, so a.out takes the
    shorter right side; the next round sees the DC plug and moves a.out to the left (35..42 is free). With one round it would collide."""
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
    ctx, s1, p1 = build(1)
    assert (s1["exit_a"], p1["exit_b"]) == ("right", "left") and [(c["jack"], c["with"]) for c in ctx["plug_collisions"]] == [("a.out", "a.power")]
    ctx, s1, p1 = build(3)
    assert (s1["exit_a"], p1["exit_b"]) == ("left", "left") and ctx["plug_collisions"] == []
