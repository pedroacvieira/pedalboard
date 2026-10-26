"""Project-level jack checks (scripts/jacks.check) on small synthetic projects. All lengths in mm."""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import jacks  # noqa: E402
import routing  # noqa: E402

PEDALS = {
    "a": {"brand": "T", "name": "A", "playground_title": "T A"},
    "b": {"brand": "T", "name": "B", "playground_title": "T B"},
}
SUPPLIES = {"s1": {"id": "s1", "brand": "S", "model": "One", "playground_title": "S One"}}


def pedal_jacks():
    return [
        {"id": "in", "label": "Input", "function": "input", "x": 0.0, "y": 0.5, "facing": "left"},
        {"id": "out", "label": "Output", "function": "output", "x": 1.0, "y": 0.5, "facing": "right"},
        {"id": "power", "label": "9V", "function": "power", "x": 0.5, "y": 0.0, "facing": "top"},
    ]


def canvas(*specs):
    """specs: (title, left_px, top_px, w_in, h_in, rot, kind) -> Pedal Playground canvas html."""
    parts = []
    for n, (title, left, top, w, h, rot, kind) in enumerate(specs):
        cls = f"item {kind} undefined" + (f" rotate-{rot}" if rot else "")
        parts.append(f'<div id="item-{n}" class="{cls}" title="{title}" data-width="{w}" data-height="{h}" data-scale="45" '
                     f'style="touch-action: none; left: {left}px; top: {top}px;"><div class="artwork" style="width:{w * 45}px; '
                     f'background-image:url(public/images/pedals/x.png)"></div></div>')
    return "".join(parts)


def project(tmp_path, specs, validation=None, jacks_block=None, chain=("a", "b"), supplies=()):
    (tmp_path / "playground_design.json").write_text(json.dumps({"source": "pedalplayground.com", "version": "1.0", "canvas": canvas(*specs)}))
    proj = {"validation": validation or {}, "jacks": jacks_block or {}}
    ctx = {"project": proj, "dir": tmp_path, "errors": [], "warnings": [], "chain": list(chain),
           "pedals": {c: PEDALS[c] for c in chain}, "supplies": list(supplies)}
    return ctx


def A(left=0):
    return ("T A", left, 0, 2.0, 4.0, 0, "pedal")


def B(left):
    return ("T B", left, 0, 2.0, 4.0, 0, "pedal")


DATA = {"a": pedal_jacks(), "b": pedal_jacks()}


def test_clear_gap_has_no_violation_and_computes_the_signal_cable(tmp_path):
    ctx = project(tmp_path, [A(0), B(135)])           # B starts 1 in = 25.4 mm after A's right edge
    jacks.check(ctx, PEDALS, SUPPLIES, DATA)
    assert ctx["violations"] == [] and ctx["errors"] == []
    (hop,) = ctx["cables"]["signal"]
    assert hop["from"] == "a.out" and hop["to"] == "b.in"
    assert hop["direct_mm"] == pytest.approx(25.4)
    assert hop["min_mm"] == pytest.approx(25.4 - 6.3)  # from 3.15 mm in front of each jack (half the 6.3 mm box)


def test_zero_distance_side_by_side_is_blocked(tmp_path):
    ctx = project(tmp_path, [A(0), B(90)])            # B starts exactly where A ends
    jacks.check(ctx, PEDALS, SUPPLIES, DATA)
    assert [v["jack"] for v in ctx["violations"]] == ["a.out"] or "a.out" in [v["jack"] for v in ctx["violations"]]
    v = next(v for v in ctx["violations"] if v["jack"] == "a.out")
    assert v["obstacle"] == "T B" and v["depth_mm"] == pytest.approx(6.3)
    assert any("clearance: a.out" in w for w in ctx["warnings"]) and ctx["errors"] == []


def test_b_input_is_blocked_by_a_too(tmp_path):
    ctx = project(tmp_path, [A(0), B(90)])
    jacks.check(ctx, PEDALS, SUPPLIES, DATA)
    assert "b.in" in [v["jack"] for v in ctx["violations"]]


def test_strict_clearance_makes_it_an_error(tmp_path):
    ctx = project(tmp_path, [A(0), B(90)], validation={"strict_clearance": True})
    jacks.check(ctx, PEDALS, SUPPLIES, DATA)
    assert any("clearance:" in e for e in ctx["errors"])


def test_gap_just_wide_enough_passes(tmp_path):
    ctx = project(tmp_path, [A(0), B(102)])           # 12 px = 6.77 mm > 6.3 mm
    jacks.check(ctx, PEDALS, SUPPLIES, DATA)
    assert ctx["violations"] == []


def test_clearance_parameters_come_from_the_project(tmp_path):
    ctx = project(tmp_path, [A(0), B(102)], jacks_block={"clearance": {"outward_mm": 10, "side_mm": 7}})
    jacks.check(ctx, PEDALS, SUPPLIES, DATA)
    assert ctx["violations"] and ctx["violations"][0]["depth_mm"] == pytest.approx(10 - 6.77, abs=0.05)


def test_missing_jacks_warn_with_the_fix_command(tmp_path):
    ctx = project(tmp_path, [A(0), B(135)])
    jacks.check(ctx, PEDALS, SUPPLIES, {"a": pedal_jacks()})
    assert any("unknown jack setup for b" in w and "scripts/pedal_editor.py b" in w for w in ctx["warnings"])
    assert ("b", "uv run scripts/pedal_editor.py b") in ctx["jack_fixes"] and ctx["errors"] == []
    assert ctx["cables"]["signal"][0]["direct_mm"] is None


def test_require_jacks_makes_missing_setup_an_error(tmp_path):
    ctx = project(tmp_path, [A(0), B(135)], validation={"require_jacks": True})
    jacks.check(ctx, PEDALS, SUPPLIES, {})
    assert any("unknown jack setup" in e for e in ctx["errors"])


def test_incomplete_setup_names_the_missing_function(tmp_path):
    ctx = project(tmp_path, [A(0), B(135)])
    data = {"a": pedal_jacks(), "b": [j for j in pedal_jacks() if j["function"] != "power"]}
    jacks.check(ctx, PEDALS, SUPPLIES, data)
    assert any("incomplete jack setup for b" in w and "missing power" in w for w in ctx["warnings"])


def test_unknown_extra_jack_is_always_an_error(tmp_path):
    ctx = project(tmp_path, [A(0), B(135)], jacks_block={"extra_used": {"a": ["tap"]}})
    jacks.check(ctx, PEDALS, SUPPLIES, DATA)
    assert any("a has no jack 'tap'" in e for e in ctx["errors"])


def test_extra_used_jack_is_clearance_checked(tmp_path):
    data = {"a": pedal_jacks() + [{"id": "tap", "label": "Tap", "function": "other", "x": 1.0, "y": 0.2, "facing": "right"}], "b": pedal_jacks()}
    ctx = project(tmp_path, [A(0), B(102)], jacks_block={"extra_used": {"a": ["tap"]}}, validation={})
    jacks.check(ctx, PEDALS, SUPPLIES, data)
    assert ctx["violations"] == []                      # 6.77 mm gap is fine for the tap jack too
    ctx = project(tmp_path, [A(0), B(90)], jacks_block={"extra_used": {"a": ["tap"]}})
    jacks.check(ctx, PEDALS, SUPPLIES, data)
    assert "a.tap" in [v["jack"] for v in ctx["violations"]]


def test_no_design_file_is_only_a_note(tmp_path):
    ctx = {"project": {}, "dir": tmp_path, "errors": [], "warnings": [], "chain": ["a", "b"], "supplies": [],
           "pedals": PEDALS}
    jacks.check(ctx, PEDALS, SUPPLIES, DATA)
    assert ctx["cables"] is None and ctx["violations"] == []
    assert ctx["warnings"] == [] and any("no playground_design.json" in n for n in ctx["jack_notes"])


def test_pedal_missing_from_the_design_is_reported(tmp_path):
    ctx = project(tmp_path, [A(0)])
    jacks.check(ctx, PEDALS, SUPPLIES, DATA)
    assert any("layout: b is in the signal chain but not in playground_design.json" in w for w in ctx["warnings"])


def supply_inst():
    rows = [{"port": "F1", "id": "psu1_F1", "pedals": ["a"]}]
    return [{"inst": {"id": "psu1"}, "sup": SUPPLIES["s1"], "rows": rows}]


def test_supply_under_the_board_is_not_an_obstacle_but_feeds_the_power_cable(tmp_path):
    supply = ("S One", 0, 100, 3.0, 1.0, 0, "pedal")   # overlaps pedal A's body in the 2D view
    data = dict(DATA, s1=[{"id": "F1", "label": "F1", "function": "power_out", "x": 1.0, "y": 0.5, "facing": "right"}])
    ctx = project(tmp_path, [A(0), supply], chain=("a",), supplies=supply_inst())
    jacks.check(ctx, PEDALS, SUPPLIES, data)
    assert ctx["violations"] == []
    (hop,) = ctx["cables"]["power"]
    assert hop["from"] == "psu1.F1" and hop["to"] == "a.power" and hop["direct_mm"] is not None
    # supply jack: x = 3 in = 76.2 mm, y = 100 px = 56.4 mm + 0.5 in = 69.1; pedal power jack: (50.8/2... 25.4, 0)
    assert hop["direct_mm"] == pytest.approx(((76.2 - 25.4) ** 2 + (100 * 25.4 / 45 + 12.7 - 0) ** 2) ** 0.5, abs=0.05)


def test_supply_on_board_layer_is_checked_like_a_pedal(tmp_path):
    supply = ("S One", 0, 100, 3.0, 1.0, 0, "pedal")
    data = dict(DATA, s1=[{"id": "F1", "label": "F1", "function": "power_out", "x": 0.5, "y": 0.5, "facing": "right"}])  # jack inside pedal A's body area
    ctx = project(tmp_path, [A(0), supply], chain=("a",), supplies=supply_inst(), jacks_block={"supplies_layer": "on_board"})
    jacks.check(ctx, PEDALS, SUPPLIES, data)
    assert any(v["obstacle"] == "T A" for v in ctx["violations"])


# --- regressions from the code review ----------------------------------------------------------
def test_untitled_catalog_item_never_matches_untitled_design_items(tmp_path):
    pedals = dict(PEDALS, b={"brand": "T", "name": "B", "playground_title": None})
    ctx = project(tmp_path, [A(0), ("", 135, 0, 2.0, 4.0, 0, "pedal")])
    ctx["pedals"] = {c: pedals[c] for c in ("a", "b")}
    jacks.check(ctx, pedals, SUPPLIES, DATA)
    assert any("layout: b is in the signal chain but not in playground_design.json" in w for w in ctx["warnings"])
    assert ctx["cables"]["signal"][0]["direct_mm"] is None


def test_malformed_jacks_do_not_crash_the_check(tmp_path):
    broken = [{"id": "in", "label": "Input", "function": "input", "x": 0.0, "y": 0.5},          # no facing
              {"label": "Output", "function": "output", "x": 1.0, "y": 0.5, "facing": "right"},  # no id
              {"id": "power", "label": "9V", "function": "power", "x": "?", "y": 0.0, "facing": "top"}]
    ctx = project(tmp_path, [A(0), B(135)])
    jacks.check(ctx, PEDALS, SUPPLIES, {"a": broken, "b": pedal_jacks()})
    assert any("unknown jack setup for a" in w for w in ctx["warnings"])


def test_cable_rows_name_the_jacks_actually_used(tmp_path):
    a = [dict(j, id="out_l") if j["function"] == "output" else j for j in pedal_jacks()]
    ctx = project(tmp_path, [A(0), B(135)])
    jacks.check(ctx, PEDALS, SUPPLIES, {"a": a, "b": pedal_jacks()})
    assert ctx["cables"]["signal"][0]["from"] == "a.out_l"


def test_signal_jacks_with_a_cable_type_are_left_to_the_plug_model(tmp_path):
    # touching pedals and no pedalboard item in the layout: nothing is routed, but every plug is still checked
    ctx = project(tmp_path, [A(0), B(90)])
    ctx["project"]["cables"] = {"type": "ernie_ball_flat_patch_ra"}
    jacks.check(ctx, PEDALS, SUPPLIES, DATA, defer=True)
    assert ctx["violations"] == [] and {k for k, _, _ in ctx["fixed_box"]} >= {"a.out", "b.in"}
    routing.route_project(ctx, PEDALS)
    blocked = {v["jack"]: v for v in ctx["violations"]}
    assert blocked["a.out"]["cable_type"] == "ernie_ball_flat_patch_ra"            # the plug model, not the box
    assert blocked["b.in"]["cable_type"] == "ernie_ball_flat_patch_ra"
    assert not any("audio zone" in w for w in ctx["warnings"]) and ctx["fixed_box"] == []
    data = {"a": pedal_jacks(), "b": [dict(j, x=0.0, y=0.1, facing="left") if j["function"] == "power" else j for j in pedal_jacks()]}
    ctx = project(tmp_path, [A(0), B(90)])
    ctx["project"]["cables"] = {"type": "ernie_ball_flat_patch_ra"}
    jacks.check(ctx, PEDALS, SUPPLIES, data, defer=True)
    routing.route_project(ctx, PEDALS)
    assert next(v for v in ctx["violations"] if v["jack"] == "b.power")["zone"] == "power"   # no power type: the box


def test_power_jacks_use_the_smaller_power_box_or_the_dc_plug_type(tmp_path):
    # b.power at (50.8, 10.16) facing left, against A's right edge (A spans x 0..50.8)
    data = {"a": pedal_jacks(), "b": [dict(j, x=0.0, y=0.1, facing="left") if j["function"] == "power" else j for j in pedal_jacks()]}
    ctx = project(tmp_path, [A(0), B(90)], jacks_block={"power_clearance": {"outward_mm": 3.0, "side_mm": 4.0}})
    jacks.check(ctx, PEDALS, SUPPLIES, data)
    v = next(v for v in ctx["violations"] if v["jack"] == "b.power")
    assert v["depth_mm"] == pytest.approx(3.0) and v["zone"] == "power"
    assert any("into the 3 mm power zone" in w for w in ctx["warnings"])
    ctx = project(tmp_path, [A(0), B(135)], jacks_block={"power_clearance": {"outward_mm": 3.0, "side_mm": 4.0}})
    jacks.check(ctx, PEDALS, SUPPLIES, data)                        # 25.4 mm gap: the power box is clear
    assert not [v for v in ctx["violations"] if v["jack"] == "b.power"]
    ctx = project(tmp_path, [A(0), B(90)])
    ctx["project"]["cables"] = {"type": "ernie_ball_flat_patch_ra", "power_type": "dc_ra_2_1_low_profile"}
    jacks.check(ctx, PEDALS, SUPPLIES, data, defer=True)
    routing.route_project(ctx, PEDALS)
    v = next(v for v in ctx["violations"] if v["jack"] == "b.power")
    assert v["cable_type"] == "dc_ra_2_1_low_profile" and "zone" not in v       # the DC plug, not the power box


def test_fixed_box_is_blocked_by_the_outline_not_the_box(tmp_path):
    # touching pedals (A 0..50.8, B 50.8..101.6): every pedal image x.png is drawn as its outline [0, 0.9] of the width
    ctx = project(tmp_path, [A(0), B(90)])
    jacks.check(ctx, PEDALS, SUPPLIES, DATA)
    assert {v["jack"]: v["depth_mm"] for v in ctx["violations"]} == pytest.approx({"a.out": 6.3, "b.in": 6.3})
    ctx = project(tmp_path, [A(0), B(90)])
    jacks.check(ctx, PEDALS, SUPPLIES, DATA, outlines={"x.png": [[0, 0, 0.9, 1]]})
    # A's outline ends 5.08 mm short of its box: b.in (zone 44.5..50.8) reaches 1.22 mm into it; a.out still touches B's box edge
    assert {v["jack"]: v["depth_mm"] for v in ctx["violations"]} == pytest.approx({"a.out": 6.3, "b.in": 1.22}, abs=0.01)
    ctx = project(tmp_path, [A(0), B(90)])
    jacks.check(ctx, PEDALS, SUPPLIES, DATA, outlines={"x.png": [[0.2, 0, 0.8, 1]]})
    assert ctx["violations"] == [] and ctx["layout"]["no_outline"] == []
    ctx = project(tmp_path, [A(0), B(90)])
    jacks.check(ctx, PEDALS, SUPPLIES, DATA, outlines={})
    assert ctx["layout"]["no_outline"] == ["T A", "T B"]


# --- per-supply placement (under | on_board) -----------------------------------------------------
SUP_JACKS = [{"id": "F1", "label": "F1", "function": "power_out", "x": 1.0, "y": 0.5, "facing": "right"},
             {"id": "F2", "label": "F2", "function": "power_out", "x": 1.0, "y": 0.9, "facing": "right"}]
PDATA = dict(DATA, s1=SUP_JACKS)
DC_TYPES = {"dc": {"name": "test DC right angle", "role": "power", "diameter_mm": 3.5, "tips": "DC 2.1 mm",
                   "plug": {"style": "right_angle", "head_depth_mm": 10.0, "head_width_mm": 10.0}}}


def insts(*specs):
    """specs: (instance id, placement or None, pedals fed by F1) -> supply instances with F1 used and F2 spare."""
    out = []
    for iid, pl, fed in specs:
        inst = {"id": iid, **({"placement": pl} if pl else {})}
        rows = [{"port": "F1", "id": f"{iid}_F1", "pedals": list(fed)}, {"port": "F2", "id": f"{iid}_F2", "pedals": []}]
        out.append({"inst": inst, "sup": SUPPLIES["s1"], "rows": rows})
    return out


def S(left=0, top=0, w=2.0, h=1.0):
    return ("S One", left, top, w, h, 0, "pedal")


def test_placement_is_the_instances_own_else_the_global_layer_else_under():
    assert jacks.placement({"id": "p"}, {}) == "under"
    assert jacks.placement({"id": "p"}, {"jacks": {"supplies_layer": "on_board"}}) == "on_board"
    assert jacks.placement({"id": "p", "placement": "under"}, {"jacks": {"supplies_layer": "on_board"}}) == "under"
    assert jacks.placement({"id": "p", "placement": "on_board"}, {"jacks": {"supplies_layer": "under"}}) == "on_board"
    assert jacks.placement({"id": "p", "placement": "on_board"}, {}) == "on_board"


def layout_of(tmp_path, specs, supplies, jacks_block=None, chain=("a",)):
    ctx = project(tmp_path, specs, jacks_block=jacks_block, chain=chain, supplies=supplies)
    jacks.check(ctx, PEDALS, SUPPLIES, PDATA)
    return ctx["layout"]


def test_layout_obstacles_follow_each_instances_placement(tmp_path):
    specs = [A(0), S(300, 0), S(500, 0)]          # two supply items: the left one is psu1's, the right one psu2's
    lay = layout_of(tmp_path, specs, insts(("psu1", None, ["a"]), ("psu2", "on_board", [])))
    assert lay["inst_placement"] == {"psu1": "under", "psu2": "on_board"}
    assert [o["id"] for o in lay["obstacles"]] == ["item-0", lay["inst_item"]["psu2"]["id"]]    # A and psu2's item
    assert lay["inst_item"]["psu1"]["left_mm"] < lay["inst_item"]["psu2"]["left_mm"]
    # the other way round: the global layer is the default, an instance overrides it
    lay = layout_of(tmp_path, specs, insts(("psu1", "under", ["a"]), ("psu2", None, [])), jacks_block={"supplies_layer": "on_board"})
    assert lay["inst_placement"] == {"psu1": "under", "psu2": "on_board"}
    assert lay["inst_item"]["psu1"]["id"] not in [o["id"] for o in lay["obstacles"]]
    assert lay["inst_item"]["psu2"]["id"] in [o["id"] for o in lay["obstacles"]]


def test_a_supply_item_without_an_instance_is_an_obstacle_only_with_the_global_on_board_layer(tmp_path):
    specs = [A(0), S(300, 0), S(500, 0)]          # one instance, two items: the second is matched to nothing
    under = layout_of(tmp_path, specs, insts(("psu1", "on_board", ["a"])))
    assert [o["id"] for o in under["obstacles"]] == ["item-0", under["inst_item"]["psu1"]["id"]]
    on = layout_of(tmp_path, specs, insts(("psu1", "under", ["a"])), jacks_block={"supplies_layer": "on_board"})
    assert [o["id"] for o in on["obstacles"]] == ["item-0", "item-2"]        # the unmatched item, not psu1's


def test_unknown_placement_is_an_error():
    import build
    from common import load_catalog, load_json
    pedals, supplies = load_catalog()
    gig = ROOT / "projects" / "guitar-gig"
    proj = load_json(gig / "project.json")
    proj["power"]["supplies"][0]["placement"] = "sideways"
    ctx = build.validate(gig, pedals, supplies, project=proj)
    assert any(e.startswith(f"power.supplies: {proj['power']['supplies'][0]['id']} has unknown placement 'sideways'") for e in ctx["errors"])
    proj["power"]["supplies"][0]["placement"] = "on_board"
    assert not any("unknown placement" in e for e in build.validate(gig, pedals, supplies, project=proj)["errors"])


def test_an_on_board_supply_blocks_a_pedal_jack_an_under_one_does_not(tmp_path):
    # A (0..50.8 mm) has its output at (50.8, 50.8); the supply starts 5 px = 2.82 mm further right: 6.3 - 2.82 = 3.48 mm deep
    specs = [A(0), S(95, 0, 2.0, 4.0)]
    ctx = project(tmp_path, specs, chain=("a",), supplies=insts(("psu1", "on_board", ["a"])))
    jacks.check(ctx, PEDALS, SUPPLIES, PDATA)
    v = next(v for v in ctx["violations"] if v["jack"] == "a.out")
    assert v["obstacle"] == "S One" and v["depth_mm"] == pytest.approx(6.3 - 5 * 25.4 / 45)
    ctx = project(tmp_path, specs, chain=("a",), supplies=insts(("psu1", "under", ["a"])))
    jacks.check(ctx, PEDALS, SUPPLIES, PDATA)
    assert not [v for v in ctx["violations"] if v["jack"] == "a.out"]


def test_an_on_board_supply_is_routed_around(tmp_path):
    # board 12 x 6 in; A (x 50.8..101.6, y 25.4..127), B (x 228.6..279.4); the supply (x 152.4..165.1, y 0..101.6) is a wall
    # between them that ends 25 mm above the front of the pedals: a cable has to pass below it
    board = ("Board", 0, 0, 12.0, 6.0, 0, "pedalboard")
    specs = [board, ("T A", 90, 45, 2.0, 4.0, 0, "pedal"), ("T B", 405, 45, 2.0, 4.0, 0, "pedal"), S(270, 0, 0.5, 4.0)]
    lengths = {}
    for pl in ("under", "on_board"):
        ctx = project(tmp_path, specs, supplies=insts(("psu1", pl, ["a"])))
        jacks.check(ctx, PEDALS, SUPPLIES, PDATA, defer=True)
        routing.route_project(ctx, {}, cable_types={})
        (c,) = [x for x in ctx["cable_list"] if x["kind"] == "signal"]
        assert c["status"] == "routed" and ctx["errors"] == []
        lengths[pl] = c["min_mm"]
    assert lengths["under"] == pytest.approx(228.6 - 101.6 - 6.3, abs=0.01)     # straight, between the 3.15 mm points
    assert lengths["on_board"] > lengths["under"] + 10                           # down past y 101.6 and up again


def test_power_cables_are_under_the_board_per_supply(tmp_path):
    specs = [A(0), ("T B", 100, 0, 2.0, 4.0, 0, "pedal"), S(300, 0), S(500, 0)]
    ctx = project(tmp_path, specs, chain=("a", "b"), supplies=insts(("psu1", "under", ["a"]), ("psu2", "on_board", ["b"])))
    jacks.check(ctx, PEDALS, SUPPLIES, PDATA, defer=True)
    assert [(h["from"], h["under_board"]) for h in ctx["cables"]["power"]] == [("psu1.F1", True), ("psu2.F1", False)]
    routing.route_project(ctx, {}, cable_types={})
    p = [c for c in ctx["cable_list"] if c["kind"] == "power"]
    assert [(c["under_board"], c["status"]) for c in p] == [(True, "not routed (under the board)"),
                                                            (False, "not routed (power routing not implemented)")]


def blocked_port_ctx(tmp_path, power_type):
    """The supply (x 0..50.8, y 0..25.4) has F1 (used) at (50.8, 12.7) and F2 (spare) at (50.8, 22.9), both facing right; a
    non-chain pedal C starts at x 95 px = 53.67 mm over y 0..101.6: 2.63 mm into F1's and F2's 5.5 mm power box."""
    specs = [("T A", 400, 0, 2.0, 4.0, 0, "pedal"), S(0, 0, 2.0, 1.0), ("T C", 95, 0, 2.0, 4.0, 0, "pedal")]
    ctx = project(tmp_path, specs, chain=("a",), supplies=insts(("psu1", "on_board", ["a"])))
    if power_type:
        ctx["project"]["cables"] = {"power_type": "dc"}
    jacks.check(ctx, PEDALS, SUPPLIES, PDATA, defer=True)
    routing.route_project(ctx, {}, cable_types=DC_TYPES)
    return ctx


def test_on_board_supply_port_without_a_power_type_gets_the_fixed_power_box_once(tmp_path):
    ctx = blocked_port_ctx(tmp_path, power_type=False)
    hits = [v for v in ctx["violations"] if v["jack"].startswith("psu1.")]
    assert [(v["jack"], v["obstacle"], v["zone"]) for v in hits] == [("psu1.F1", "T C", "power")]    # F2 is spare
    assert hits[0]["depth_mm"] == pytest.approx(5.5 - (95 * 25.4 / 45 - 50.8))
    assert sum("psu1.F1" in w for w in ctx["warnings"]) == 1


def test_on_board_supply_port_with_a_power_type_gets_the_dc_plug_once(tmp_path):
    ctx = blocked_port_ctx(tmp_path, power_type=True)
    hits = [v for v in ctx["violations"] if v["jack"].startswith("psu1.")]
    # DC head 10 x 10 at the jack (50.8, 12.7) facing right: x 50.8..60.8; C starts at 53.67: 7.13 mm into the head
    assert [(v["jack"], v["part"], v["cable_type"], v["cable"]) for v in hits] == [("psu1.F1", "head", "dc", "P1")]
    assert hits[0]["depth_mm"] == pytest.approx(60.8 - 95 * 25.4 / 45)
    assert sum("psu1.F1" in w for w in ctx["warnings"]) == 1
    (p,) = [c for c in ctx["cable_list"] if c["kind"] == "power"]
    assert p["exit_a"] in ("left", "right") and p["under_board"] is False
    assert [h for h in ctx["routing"]["heads"] if h["cable"] == "P1"]


def test_on_board_port_takes_the_free_exit_side_and_an_override_fixes_it(tmp_path):
    # C only reaches the up side's cable run (y 4.2..7.7, x 54.05..57.55): C y 0..6.35 from x 56.44 -> the down side is free
    specs = [("T A", 400, 0, 2.0, 4.0, 0, "pedal"), S(0, 0, 2.0, 1.0), ("T C", 100, 0, 2.0, 0.25, 0, "pedal")]
    ctx = project(tmp_path, specs, chain=("a",), supplies=insts(("psu1", "on_board", ["a"])))
    ctx["project"]["cables"] = {"power_type": "dc"}
    jacks.check(ctx, PEDALS, SUPPLIES, PDATA, defer=True)
    routing.route_project(ctx, {}, cable_types=DC_TYPES)
    (p,) = [c for c in ctx["cable_list"] if c["kind"] == "power"]
    assert p["exit_a"] == "right" and not [v for v in ctx["violations"] if v["jack"] == "psu1.F1"]   # right = down (facing right)
    ctx = project(tmp_path, specs, chain=("a",), supplies=insts(("psu1", "on_board", ["a"])))
    ctx["project"]["cables"] = {"power_type": "dc", "overrides": {"P1": {"exit_a": "left"}}}
    jacks.check(ctx, PEDALS, SUPPLIES, PDATA, defer=True)
    routing.route_project(ctx, {}, cable_types=DC_TYPES)
    (v,) = [v for v in ctx["violations"] if v["jack"] == "psu1.F1"]
    assert v["side"] == "left" and v["part"] == "cable" and v["obstacle"] == "T C"
