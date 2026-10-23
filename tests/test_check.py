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
