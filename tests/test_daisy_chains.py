"""Forked and serial power daisy chains (`outputs[].style`, `power_routing.daisy_style`): validation, the hops and the
physical cables (C#), the DC cable summary, the power assignment and the layout surrogate. Hand-computed synthetic cases plus
the real guitar-gig (all outputs serial by default: its routes and lengths are the ones from before the feature)."""
import copy
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import build  # noqa: E402
import power  # noqa: E402
import routing  # noqa: E402
import svgdraw  # noqa: E402
from common import load_catalog  # noqa: E402
from test_layout import GIG, gig_build, model, ped, at  # noqa: E402
from test_power_routing import pw_ctx, route  # noqa: E402


# --- validation -------------------------------------------------------------------------------------
def test_daisy_style_is_the_outputs_own_else_the_projects_default_else_serial():
    assert routing.daisy_style({}) == "serial" and routing.daisy_style({}, {"port": "F1"}) == "serial"
    forked = {"power_routing": {"daisy_style": "forked"}}
    assert routing.daisy_style(forked, {"port": "F1"}) == "forked"
    assert routing.daisy_style(forked, {"port": "F1", "style": "serial"}) == "serial"
    assert routing.daisy_style({}, {"style": "forked"}) == "forked"
    assert routing.power_settings(forked)["daisy_style"] == "forked" and routing.power_settings({})["daisy_style"] == "serial"


def test_the_project_default_style_is_validated():
    ok = {"power_routing": {"daisy_style": "forked"}}
    assert routing.validate_power_routing(ok) == [] and routing.validate_power_routing({"power_routing": {"daisy_style": "serial"}}) == []
    (err,) = routing.validate_power_routing({"power_routing": {"daisy_style": "star"}})
    assert "power_routing.daisy_style" in err and "serial, forked" in err and "'star'" in err
    assert any("daisy_style" in e for e in routing.validate_power_routing({"power_routing": {"nope": 1}}))   # listed among the settings


def bass_project(output_style=None, default=None):
    project = json.loads((ROOT / "projects" / "bass" / "project.json").read_text())
    project.pop("cables", None)
    if output_style is not None:
        project["power"]["supplies"][0]["outputs"][0]["style"] = output_style
    if default is not None:
        project["power_routing"] = {"daisy_style": default}
    return project


def validate_bass(project):
    pedals, supplies = load_catalog()
    return build.validate(ROOT / "projects" / "bass", pedals, supplies, {}, project=project)


def test_an_unknown_output_style_is_an_error_and_known_ones_are_clean():
    ctx = validate_bass(bass_project("star"))
    assert any("psu1_OUT1: style 'star' is unknown (serial, forked)" in e for e in ctx["errors"])
    for style in ("serial", "forked", None):
        assert not [e for e in validate_bass(bass_project(style)).get("errors", []) if "style" in e]
    ctx = validate_bass(bass_project(default="star"))
    assert any("power_routing.daisy_style" in e for e in ctx["errors"])
    assert [r["style"] for r in validate_bass(bass_project("forked"))["supplies"][0]["rows"]][:2] == ["forked", "serial"]
    assert {r["style"] for r in validate_bass(bass_project(default="forked"))["supplies"][0]["rows"]} == {"forked"}


# --- hops and cables on the real guitar-gig ---------------------------------------------------------
def gig_with(**edit):
    """The guitar-gig build with the project edited by edit(project)."""
    pedals, supplies, ctx = gig_build()
    proj = copy.deepcopy(ctx["project"])
    edit["edit"](proj)
    return pedals, build.validate(GIG, pedals, supplies, project=proj)


def power_hops(ctx):
    return ctx["cables"]["power"]


def test_serial_is_the_default_and_the_hops_are_as_before():
    pedals, supplies, ctx = gig_build()
    hops = power_hops(ctx)
    assert len(hops) == 17 and {h["style"] for h in hops} == {"serial"}
    by = {i + 1: h for i, h in enumerate(hops)}
    assert (by[6]["from"], by[6]["to"]) == ("psu2.F1", "red_muck.power")                     # port -> first pedal
    assert (by[7]["from"], by[7]["to"]) == ("red_muck.power", "beano.power")                 # then pedal -> next pedal
    assert (by[9]["from"], by[9]["to"]) == ("danelectro_3699.power", "sun_face.power")
    assert [h["under_board"] for h in hops[5:9]] == [True, False, False, False]              # only the first hop starts under the board
    assert [h["cable"] for h in hops[5:9]] == ["C6"] * 4 and by[10]["cable"] == "C7"       # one cable per serial output
    assert [c["id"] for c in ctx["power_cable_summary"]] == [f"C{n}" for n in range(1, 11)]


def test_forked_hops_all_start_at_the_port_with_one_cable_each():
    pedals, ctx = gig_with(edit=lambda p: p["power_routing"].update(daisy_style="forked") if "power_routing" in p
                           else p.update(power_routing={"daisy_style": "forked"}))
    hops = power_hops(ctx)
    assert len(hops) == 17 and {h["style"] for h in hops} == {"forked"}
    outs = {}
    for h in hops:
        outs.setdefault(h["output"], []).append(h)
    assert [h["from"] for h in outs["psu2_F1"]] == ["psu2.F1"] * 4                          # red_muck, beano, 3699, sun_face
    assert [h["to"] for h in outs["psu2_F1"]] == ["red_muck.power", "beano.power", "danelectro_3699.power", "sun_face.power"]
    assert all(h["under_board"] for h in hops)                                               # every cable leaves an under-board port
    assert [h["cable"] for h in hops] == [f"C{n}" for n in range(1, 18)]                    # one physical cable per leg
    assert ctx["errors"] == []


def test_per_output_style_overrides_the_project_default():
    def edit(p):
        p["power_routing"] = {"daisy_style": "forked"}
        p["power"]["supplies"][1]["outputs"][0]["style"] = "serial"        # psu2 F1 stays serial
    pedals, ctx = gig_with(edit=edit)
    hops = power_hops(ctx)
    f1 = [h for h in hops if h["output"] == "psu2_F1"]
    assert [h["style"] for h in f1] == ["serial"] * 4 and [h["from"] for h in f1][1] == "red_muck.power"
    assert {h["style"] for h in hops if h["output"] != "psu2_F1"} == {"forked"}
    summary = {c["id"]: c for c in ctx["power_cable_summary"]}
    assert summary["C6"]["style"] == "serial" and summary["C6"]["legs"] == ["P6", "P7", "P8", "P9"] and summary["C6"]["plugs"] == 5
    assert summary["C7"]["style"] == "forked" and summary["C7"]["plugs"] == 2


def test_serial_summary_on_the_gig_is_the_sum_of_the_legs():
    pedals, supplies, ctx = gig_build()
    legs = {c["id"]: c for c in ctx["cable_list"] if c["kind"] == "power"}
    summary = {c["id"]: c for c in ctx["power_cable_summary"]}
    c6 = summary["C6"]
    assert (c6["style"], c6["output"], c6["from"], c6["plugs"], c6["status"]) == ("serial", "psu2_F1", "psu2.F1", 5, "routed")
    assert c6["legs"] == ["P6", "P7", "P8", "P9"]
    assert c6["min_mm"] == pytest.approx(sum(legs[p]["min_mm"] for p in c6["legs"]))
    assert c6["to"] == ["red_muck.power", "beano.power", "danelectro_3699.power", "sun_face.power"]
    assert all(legs[p]["cable"] == "C6" and legs[p]["style"] == "serial" for p in c6["legs"])
    # the legs themselves are the routes and lengths of the owner's wiring (measured DC plug, dc_ra_owner_baseline)
    assert [round(legs[p]["min_mm"]) for p in ("P6", "P7", "P8", "P9")] == [125, 430, 223, 311]   # P9 left -> right: the plug at sun_face.power avoids danelectro_3699.out (plug-orientation phase 1); P6 / P7 right / left: red_muck.power takes the right side once the signal plugs saw the DC plugs (review fix, rounds)
    assert round(c6["min_mm"]) == 1090


def test_forked_cables_of_the_gig_route_from_the_port_and_each_has_its_own_length():
    pedals, ctx = gig_with(edit=lambda p: p.update(power_routing={"daisy_style": "forked"}))
    legs = {c["id"]: c for c in ctx["cable_list"] if c["kind"] == "power"}
    summary = {c["id"]: c for c in ctx["power_cable_summary"]}
    assert len(summary) == 17 and all(c["plugs"] == 2 and len(c["legs"]) == 1 for c in summary.values())
    assert all(c["status"] == "routed" for c in summary.values())
    assert summary["C7"]["min_mm"] == pytest.approx(legs["P7"]["min_mm"])
    # beano is fed from the port now, not from red_muck's plug: that cable is a port -> beano route (304 mm in the gig layout)
    assert legs["P7"]["from"] == "psu2.F1" and round(legs["P7"]["min_mm"]) == 304
    assert round(sum(c["min_mm"] for c in summary.values())) > 3231 - 1500                 # sanity: a real total, not zero


# --- the summary (pure) -----------------------------------------------------------------------------
def leg(pid, cable, style, min_mm, est=None, status="routed", frm="psu1.F1", to="x.power"):
    return {"id": pid, "kind": "power", "cable": cable, "style": style, "output": "psu1_F1", "from": frm, "to": to, "min_mm": min_mm,
            "estimate_mm": est, "status": status}


def test_power_cable_summary_groups_legs_into_cables_and_counts_plugs():
    cables = [{"id": "S1", "kind": "signal"},
              leg("P1", "C1", "serial", 100.0, to="a.power"), leg("P2", "C1", "serial", 50.0, frm="a.power", to="b.power"),
              leg("P3", "C1", "serial", 25.0, frm="b.power", to="c.power"),
              leg("P4", "C2", "forked", 70.0, to="d.power"), leg("P5", "C3", "forked", 80.0, to="e.power")]
    summary = routing.power_cable_summary(cables)
    assert [c["id"] for c in summary] == ["C1", "C2", "C3"]
    c1, c2, c3 = summary
    assert (c1["style"], c1["legs"], c1["plugs"], c1["min_mm"], c1["from"], c1["to"]) == \
        ("serial", ["P1", "P2", "P3"], 4, 175.0, "psu1.F1", ["a.power", "b.power", "c.power"])      # pedals + 1 plugs
    assert (c2["legs"], c2["plugs"], c2["min_mm"]) == (["P4"], 2, 70.0) and (c3["legs"], c3["plugs"], c3["min_mm"]) == (["P5"], 2, 80.0)
    assert c1["status"] == "routed"


def test_summary_length_is_none_when_a_leg_is_not_routed_and_falls_back_to_the_estimate():
    cables = [leg("P1", "C1", "serial", 100.0, est=90.0), leg("P2", "C1", "serial", None, est=40.0, status="unroutable: no free path")]
    (c,) = routing.power_cable_summary(cables)
    assert c["min_mm"] is None and c["estimate_mm"] == 130.0 and c["status"] == "unroutable: no free path"
    (c,) = routing.power_cable_summary([leg("P1", "C1", "serial", 100.0, est=None), leg("P2", "C1", "serial", 5.0, est=3.0)])
    assert c["min_mm"] == 105.0 and c["estimate_mm"] is None


def test_the_summary_is_set_for_a_project_without_routing_too():
    ctx = pw_ctx(hops=(("psu1.F1", "a.power"),), cables={"power_type": None})          # no power cable type: listed, not routed
    ctx["cables"]["power"][0].update(min_mm=33.0)
    route(ctx)
    (c,) = ctx["power_cable_summary"]
    assert c["id"] == "C1" and c["min_mm"] is None and c["estimate_mm"] == 33.0 and c["status"].startswith("not routed")


# --- routing of forked cables ------------------------------------------------------------------------
def forked_ctx():
    hops = [{"from": "psu1.F1", "to": "a.power", "style": "forked", "cable": "C1", "under_board": True},
            {"from": "psu1.F1", "to": "d.power", "style": "forked", "cable": "C2", "under_board": True}]
    ctx = pw_ctx(holes=((28.5, 38.5, 40.5, 48.5), (98.5, 38.5, 110.5, 48.5)), d_pedal=True)
    ctx["cables"] = {"power": hops}
    return ctx


def test_forked_cables_each_start_under_the_board_at_the_port_with_their_own_route():
    ctx = forked_ctx()
    legs = route(ctx)
    assert set(legs) == {"P1", "P2"} and all(c["status"] == "routed" for c in legs.values())
    starts = {n: next(s["points"][0] for s in c["stretches"] if s["layer"] == "under") for n, c in legs.items()}
    assert starts["P1"] == pytest.approx((112.0, 145.0)) and starts["P2"] == pytest.approx((112.0, 145.0))
    assert legs["P1"]["end_point"] != legs["P2"]["end_point"]
    assert [(c["cable"], c["style"]) for c in legs.values()] == [("C1", "forked"), ("C2", "forked")]
    summary = {c["id"]: c for c in ctx["power_cable_summary"]}
    assert summary["C1"]["min_mm"] == pytest.approx(legs["P1"]["min_mm"]) and summary["C2"]["min_mm"] == pytest.approx(legs["P2"]["min_mm"])


def test_a_serial_pair_from_the_same_port_is_one_cable_summed_over_two_legs():
    ctx = forked_ctx()
    ctx["cables"]["power"] = [{"from": "psu1.F1", "to": "a.power", "style": "serial", "cable": "C1", "under_board": True},
                              {"from": "a.power", "to": "d.power", "style": "serial", "cable": "C1", "under_board": False}]
    legs = route(ctx)
    (c,) = ctx["power_cable_summary"]
    assert c["legs"] == ["P1", "P2"] and c["plugs"] == 3 and c["min_mm"] == pytest.approx(legs["P1"]["min_mm"] + legs["P2"]["min_mm"])


def test_cables_of_a_forked_port_share_its_start_cell_beyond_the_stacking_limit():
    g = routing.Grid(0, 0, 60, 60, 6.0)
    s = (5, 5)
    nets = [("a", s, (9, 5)), ("b", s, (5, 9)), ("c", s, (1, 5)), ("d", s, (5, 1))]
    _, users, overflow, _ = routing.route_all(g, nets, max_stack=2, iterations=20)
    assert s in overflow and len(users[s]) == 4                                       # four cables in one cell: over the limit of 2
    paths, users, overflow, _ = routing.route_all(g, nets, max_stack=2, iterations=20, shared=frozenset({s}))
    assert overflow == set() and len(users[s]) == 4 and all(p[0] == s for p in paths.values())


def captured_shared(ctx, monkeypatch):
    seen = []
    real = routing.route_all

    def spy(*args, **kw):
        if kw.get("quick"):   # the power cables' call (the signal cables' is not quick)
            seen.append(kw.get("shared"))
        return real(*args, **kw)
    monkeypatch.setattr(routing, "route_all", spy)
    route(ctx)
    return seen


def test_route_power_exempts_only_the_start_cell_of_a_forked_port(monkeypatch):
    ctx = forked_ctx()
    (shared,) = captured_shared(ctx, monkeypatch)
    cell = ctx["routing"]["grid"].cell_of(112.0, 145.0)
    assert shared == {(cell[0], cell[1], 1)}                                           # the under-board start state of the port
    serial = forked_ctx()
    serial["cables"]["power"] = [{"from": "psu1.F1", "to": "a.power", "style": "serial", "cable": "C1", "under_board": True},
                                 {"from": "a.power", "to": "d.power", "style": "serial", "cable": "C1", "under_board": False}]
    (none,) = captured_shared(serial, monkeypatch)
    assert not none                                                                      # serial: stacking counts everywhere as before


# --- the power assignment ------------------------------------------------------------------------
def quiet(i):
    return {"power_consumption": {"current_ma": 50, "min_voltage_v": 9, "max_voltage_v": 9, "polarity": "center_negative"},
            "digital": False, "clocked_noise": False, "tags": []}


PEDALS4 = {p: quiet(p) for p in "abcd"}
SUPPLY = {"id": "s", "polarity": "center_negative",
          "outputs": [{"port": "O1", "options": [{"voltage_v": 9, "max_ma": 1000}]},
                      {"port": "O2", "options": [{"voltage_v": 9, "max_ma": 1000}]}]}
INSTS = [{"id": "psu", "supply": "s", "sup": SUPPLY, "under": False}]
# the plugs of a (100,0) b (110,0) c (100,40) d (110,40); the ports O1 (0,0), O2 (0,40): Manhattan, no holes
POINTS = {"a": (100, 0), "b": (110, 0), "c": (100, 40), "d": (110, 40)}
PORTS = {("psu", "O1"): (0, 0), ("psu", "O2"): (0, 40)}


def assigned(project, start=None, chain=("a", "b", "c", "d")):
    res = power.assign(list(chain), PEDALS4, INSTS, project, POINTS, PORTS, start=start)
    return {o["port"]: o for s in res["supplies"] for o in s["outputs"]}, res


def test_serial_assignment_chains_everything_on_one_output_forked_splits_them():
    serial, res = assigned({})
    assert list(serial) == ["O1"] and serial["O1"]["pedals"] == ["a", "b", "d", "c"]   # 100 + 10 + 40 + 10 = 160 mm of one cable
    assert res["length_mm"] == pytest.approx(160.0) and "style" not in serial["O1"]
    forked, res = assigned({"power_routing": {"daisy_style": "forked"}})
    # every cable runs from the port: a, b on O1 (100 + 110), c, d on O2 (100 + 110) = 420; all four on O1 would be 500 mm
    assert {k: v["pedals"] for k, v in forked.items()} == {"O1": ["a", "b"], "O2": ["c", "d"]}
    assert res["length_mm"] == pytest.approx(420.0)


def test_forked_listing_follows_the_signal_chain_order_not_the_cable_length():
    forked, _ = assigned({"power_routing": {"daisy_style": "forked"}}, chain=("b", "a", "d", "c"))
    assert forked["O1"]["pedals"] == ["b", "a"] and forked["O2"]["pedals"] == ["d", "c"]


def test_assignment_keeps_the_style_of_the_owners_output():
    one = [{"id": "psu", "supply": "s", "sup": {**SUPPLY, "outputs": SUPPLY["outputs"][:1]}, "under": False}]   # a single output O1
    start = {"psu": [{"port": "O1", "voltage_v": 9, "pedals": ["a", "b", "c", "d"], "style": "forked"}]}
    res = power.assign(list("abcd"), PEDALS4, one, {}, POINTS, PORTS, start=start)
    (out,) = res["supplies"][0]["outputs"]
    assert out["style"] == "forked" and out["pedals"] == ["a", "b", "c", "d"]
    assert res["length_mm"] == pytest.approx(100 + 110 + 140 + 150)                       # forked: every plug from the port
    res = power.assign(list("abcd"), PEDALS4, one, {}, POINTS, PORTS, start={"psu": [{**start["psu"][0], "style": "serial"}]})
    assert res["supplies"][0]["outputs"][0]["style"] == "serial" and res["length_mm"] == pytest.approx(160.0)
    res = power.assign(list("abcd"), PEDALS4, one, {}, POINTS, PORTS)                       # no style given: the project default, no key written
    assert "style" not in res["supplies"][0]["outputs"][0] and res["length_mm"] == pytest.approx(160.0)


def test_forked_estimate_uses_each_hop_from_the_port_with_the_under_board_flag():
    # a supply under the board: every forked cable starts under it, the hole estimate applies to each leg (not chained through a pedal)
    holes = power.HoleIndex([(100.0, 20.0)])
    cfg = {"top_cost": 3.0, "transit_mm": 15.0}
    length, order = power.fork_length((0, 0), ["a", "c"], POINTS, lambda a, b, u: power.hop_estimate(a, b, u, holes, cfg), True,
                                      {"a": 0, "c": 1})
    # each: under Manhattan to the hole (120) + the pass (15) + 3 x the straight distance from the hole (20 and 20)
    assert order == ["a", "c"] and length == pytest.approx(2 * (100 + 20 + 15 + 3 * 20))


# --- the layout surrogate --------------------------------------------------------------------------
def test_surrogate_power_term_of_a_forked_output_is_the_sum_of_the_port_to_pedal_distances():
    m = model([ped("T A", 0), ped("T B", 135)])
    state = at((25.4, 50.8, 0), (200.0, 50.8, 0))
    m.set_wiring([((0.0, 0.0), ["a", "b"])])                                              # serial (the default): port -> a -> b
    serial = m.score(state, detail=True)[1]["terms"]["power"][0]
    assert serial == pytest.approx((25.4 + 2.75) + (200 - 25.4))
    m.set_wiring([((0.0, 0.0), ["a", "b"], True, None, "forked")])                        # forked: port -> a and port -> b
    forked = m.score(state, detail=True)[1]["terms"]["power"][0]
    assert forked == pytest.approx((25.4 + 2.75) + (200.0 + 2.75))
    assert m.wiring[0][3] == "forked"
    m.set_wiring([((0.0, 0.0), ["a", "b"], True, None, None)])
    assert m.wiring[0][3] == "serial"


def test_the_model_reads_the_style_of_the_projects_own_wiring():
    m = model([ped("T A", 0), ped("T B", 135)])
    m.insts = [{"inst": {"id": "psu1", "supply": "s", "outputs": [{"port": "F1", "pedals": ["a", "b"], "style": "forked"},
                                                                 {"port": "F2", "pedals": ["c"]}]}, "sup": {"id": "s"}}]
    m.set_wiring(None)
    assert [w[3] for w in m.wiring] == ["forked", "serial"]
    m.project = {**m.project, "power_routing": {"daisy_style": "forked"}}
    m.set_wiring(None)
    assert [w[3] for w in m.wiring] == ["forked", "forked"]


# --- README and pictures -------------------------------------------------------------------------------
def test_readme_lists_the_physical_dc_cables_and_keeps_the_per_leg_table():
    pedals, supplies, ctx = gig_build()
    md = build.project_readme(ctx, pedals)
    assert "### DC cables to buy" in md
    assert "| C6 | serial | psu2_F1 | psu2.F1 -> red_muck -> beano -> danelectro_3699 -> sun_face | 5 | P6, P7, P8, P9 | 1090 | routed |" in md
    assert "| P7 | power | C6 | red_muck.power | beano.power |" in md                    # the per-leg table keeps every leg, with its cable
    assert "DC cable, minimum: 3355 mm over 10 cables (10 serial, 0 forked)." in md
    assert "| S1 | signal | - | sun_face.out |" in md


def test_forked_readme_and_diagram():
    pedals, ctx = gig_with(edit=lambda p: p.update(power_routing={"daisy_style": "forked"}))
    md = build.project_readme(ctx, pedals)
    assert "| C7 | forked | psu2_F1 | psu2.F1 -> beano | 2 | P7 |" in md and "(0 serial, 17 forked)" in md
    assert "**F1** (fixed, forked)" in md
    mmd = build.mermaid_power(ctx)
    assert "    psu2_F1 --> beano" in mmd and "    red_muck --> beano" not in mmd


def test_serial_diagram_still_chains_the_pedals():
    pedals, supplies, ctx = gig_build()
    mmd = build.mermaid_power(ctx)
    assert "    red_muck --> beano" in mmd and "    psu2_F1 --> beano" not in mmd


def test_power_picture_labels_physical_cables_and_tables_one_row_per_cable():
    pedals, supplies, ctx = gig_build()
    labels = svgdraw.power_labels(ctx["cable_list"])
    assert len([x for x in labels if ">C6<" in x]) == 4 and not [x for x in labels if ">P6<" in x]   # the legs of a serial cable share its label
    names = {pid: pedals[pid]["name"] for pid in ctx["chain"]}
    svg = svgdraw.render_power(ctx, names)
    assert svg.count('class="legend-row"') == 10 and 'data-id="C6"' in svg and 'data-id="P6"' not in svg.split("legend-row")[-1]
    assert "serial: " in svg and "1090 mm" in svg


# --- review fixes -------------------------------------------------------------------------------------------
@pytest.mark.parametrize("bad", [["forked"], "forked"])
def test_a_malformed_power_routing_is_reported_not_a_crash(bad):
    project = bass_project()
    project["power_routing"] = bad
    ctx = validate_bass(project)
    assert [e for e in ctx["errors"] if e.startswith("power_routing")] == ["power_routing must be an object"]
    assert routing.daisy_style(project, {"port": "OUT1"}) == "serial" and routing.power_settings(project)["daisy_style"] == "serial"
    m = model([ped("T A", 0), ped("T B", 135)], project_extra={"power_routing": bad})
    m.set_wiring([((0.0, 0.0), ["a"])])
    assert m.wiring[0][3] == "serial"
    res = power.assign(list("abcd"), PEDALS4, INSTS, project, POINTS, PORTS)
    assert res["length_mm"] == pytest.approx(160.0)


def test_a_bad_project_default_is_reported_once_and_a_bad_output_style_by_its_output():
    ctx = validate_bass(bass_project(default="star"))
    assert len([e for e in ctx["errors"] if "daisy_style" in e or "'star'" in e]) == 1
    assert {r["style"] for r in ctx["supplies"][0]["rows"]} == {"serial"}                 # the rows fall back to serial
    ctx = validate_bass(bass_project(output_style="star", default="forked"))
    assert len([e for e in ctx["errors"] if "style" in e]) == 1 and ctx["supplies"][0]["rows"][0]["style"] == "forked"
    ctx = validate_bass(bass_project(default="star", output_style="serial"))
    assert len([e for e in ctx["errors"] if "daisy_style" in e]) == 1 and not [e for e in ctx["errors"] if "OUT1: style" in e]


def test_power_routing_problems_are_reported_once_by_the_build():
    project = bass_project()
    project["power_routing"] = {"edges": {"back": "allowed"}}
    errs = [e for e in validate_bass(project)["errors"] if "power_routing.edges was removed" in e]
    assert len(errs) == 1


def test_a_shared_cell_does_not_make_its_whole_layer_unlimited():
    g = routing.Grid(0, 0, 60, 6.0, 6.0)                       # a corridor of 10 cells: two cables must share all of them
    nets = [("a", (0, 0), (9, 0)), ("b", (0, 0), (9, 0))]
    _, users, overflow, _ = routing.route_all(g, nets, max_stack=1, iterations=5, shared=frozenset({(0, 0)}))
    assert (0, 0) not in overflow and (5, 0) in overflow and (9, 0) in overflow             # only the start cell is exempt
    _, _, overflow, _ = routing.route_all(g, nets, max_stack=1, iterations=5)
    assert (0, 0) in overflow


def test_every_cable_of_a_set_owns_a_plug_and_crosses_it_for_free():
    g = routing.Grid(0, 0, 60, 6.0, 6.0)
    nets = [("a", (0, 0), (9, 0)), ("b", (0, 0), (9, 0)), ("c", (0, 0), (9, 0))]
    cells = {(4, 0), (5, 0)}
    got = {}
    for label, owner in (("one", "a"), ("two", {"a", "b"}), ("all", frozenset({"a", "b", "c"}))):
        *_, plug_over = routing.route_all(g, nets, max_stack=5, iterations=5, plugs={"p": (owner, cells)}, max_over_plug=0)
        got[label] = plug_over.get("p")
    assert got == {"one": ["b", "c"], "two": ["c"], "all": None}


def onboard_forked_ctx(overrides=None):
    ctx = forked_ctx()
    ctx["layout"]["inst_placement"] = {"psu1": "on_board"}
    ctx["supplies"] = [{"inst": {"id": "psu1", "supply": "sup1", "placement": "on_board"}, "sup": {"id": "sup1"},
                        "rows": [{"port": "F1", "pedals": ["a", "d"]}]}]
    ctx["project"]["cables"]["overrides"] = overrides or {}
    return ctx


def test_the_legs_of_a_forked_on_board_port_all_own_its_plug(monkeypatch):
    seen = []
    real = routing.route_all

    def spy(*args, **kw):
        if kw.get("quick"):
            seen.append(args[4])
        return real(*args, **kw)
    monkeypatch.setattr(routing, "route_all", spy)
    route(onboard_forked_ctx())
    assert seen[0]["psu1.F1"][0] == {"P1", "P2"}                  # both legs of the forked output own the port's plug


def test_conflicting_exit_a_overrides_on_one_forked_port_are_reported():
    ctx = onboard_forked_ctx({"P1": {"exit_a": "left"}, "P2": {"exit_a": "right"}})
    legs = route(ctx)
    assert {c["exit_a"] for c in legs.values()} == {"left"}
    (w,) = [w for w in ctx["warnings"] if "same port psu1.F1" in w]
    assert "P1 (exit_a left)" in w and "P2 (exit_a right)" in w and "left is used for both" in w
    agree = onboard_forked_ctx({"P1": {"exit_a": "left"}, "P2": {"exit_a": "left"}})
    route(agree)
    assert not [w for w in agree["warnings"] if "same port" in w]


def test_a_hop_without_a_cable_id_never_takes_a_real_cable_id():
    ctx = pw_ctx(hops=(("psu1.F1", "a.power"), ("a.power", "d.power")), d_pedal=True)
    ctx["cables"]["power"][1]["cable"] = "C1"
    legs = route(ctx)
    assert legs["P2"]["cable"] == "C1" and legs["P1"]["cable"] == "C2"
    assert [c["id"] for c in ctx["power_cable_summary"]] == ["C2", "C1"]


def test_power_picture_shows_the_routed_part_of_a_cable_with_unrouted_legs_and_plural_edges():
    pedals, supplies, ctx = gig_build()
    legs = {c["id"]: c for c in ctx["cable_list"] if c["kind"] == "power"}
    legs["P9"]["min_mm"], legs["P9"]["status"] = None, "unroutable: no free path"
    legs["P3"]["edges_used"], legs["P4"]["edges_used"] = 2, 1
    ctx["power_cable_summary"] = routing.power_cable_summary(ctx["cable_list"])
    svg = svgdraw.render_power(ctx, {pid: pedals[pid]["name"] for pid in ctx["chain"]})
    part = sum(legs[p]["min_mm"] for p in ("P6", "P7", "P8"))
    assert f"&gt;= {part:.0f} mm, 1 leg unrouted" in svg   # (escaped in the SVG text)
    assert "2 edges<" in svg and "1 edge<" in svg and "1 edges" not in svg
