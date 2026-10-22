"""Footswitch data (scripts/footswitches.py) and the spacing check, on hand-made layouts. All lengths in mm.

Pedals are 2 x 4 in = 50.8 x 101.6 mm at 45 px/in. A switch at (0.5, 0.8) of pedal A (left 0, top 0) sits at
(25.4, 81.28); the same switch of pedal B at left 135 px = 76.2 mm sits at (101.6, 81.28): 76.2 mm apart.
"""
import json
import math
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import design  # noqa: E402
import footswitches as fsw  # noqa: E402
import jacks  # noqa: E402
from test_check import DATA, PEDALS, canvas  # noqa: E402


def sw(fid="bypass", x=0.5, y=0.8, bypass=True, **kw):
    return {"id": fid, "label": fid.title(), "x": x, "y": y, "bypass": bypass, **kw}


def run(tmp_path, specs, fs_data, project=None, items=None):
    """jacks.check (for the layout) then footswitches.check on a two-pedal chain a -> b."""
    (tmp_path / "playground_design.json").write_text(json.dumps({"canvas": canvas(*specs)}))
    ctx = {"project": project or {}, "dir": tmp_path, "key": "t", "errors": [], "warnings": [], "chain": ["a", "b"],
           "pedals": PEDALS, "supplies": []}
    jacks.check(ctx, PEDALS, {}, DATA, cable_types={}, items=items)
    fsw.check(ctx, PEDALS, fs_data)
    return ctx


def A(left=0, rot=0):
    return ("T A", left, 0, 2.0, 4.0, rot, "pedal")


def B(left=135, rot=0):
    return ("T B", left, 0, 2.0, 4.0, rot, "pedal")


ONE_EACH = {"a": [sw()], "b": [sw()]}


def foot(ctx):
    return [m for m in ctx["warnings"] + ctx["errors"] if m.startswith("footswitch")]


def test_distance_between_two_pedals_and_auto_minimum(tmp_path):
    ctx = run(tmp_path, [A(), B()], ONE_EACH)
    (pair,) = ctx["footswitch_pairs"]
    assert (pair["a"], pair["b"]) == ("a.bypass", "b.bypass") and pair["distance_mm"] == pytest.approx(76.2)
    st = ctx["footswitch_settings"]
    assert st["mode"] == "auto" and st["auto_mm"] == pytest.approx(76.2) and st["min_distance_mm"] == pytest.approx(76.2)
    assert not pair["too_close"] and foot(ctx) == []      # the owner's layout has no findings by construction


def test_rotated_pedal(tmp_path):
    """B rotated 90: centre (101.6, 50.8); the switch is 30.48 mm below the centre, rotated to 30.48 mm left of it
    -> (71.12, 50.8). From (25.4, 81.28): hypot(45.72, 30.48) = 54.95 mm."""
    ctx = run(tmp_path, [A(), B(rot=90)], ONE_EACH)
    p = {q["key"]: q for q in ctx["footswitch_points"]}
    assert (p["b.bypass"]["x"], p["b.bypass"]["y"]) == pytest.approx((71.12, 50.8))
    assert ctx["footswitch_pairs"][0]["distance_mm"] == pytest.approx(math.hypot(45.72, 30.48))


def test_same_pedal_pairs_are_ignored_and_pairs_are_sorted(tmp_path):
    data = {"a": [sw("left", x=0.2, bypass=True), sw("right", x=0.8, bypass=False)], "b": [sw()]}
    ctx = run(tmp_path, [A(), B()], data)
    got = [(r["a"], r["b"], round(r["distance_mm"], 2), r["a_bypass"], r["b_bypass"]) for r in ctx["footswitch_pairs"]]
    # a.right at x 40.64 -> 60.96 mm to b; a.left at 10.16 -> 91.44 mm
    assert got == [("a.right", "b.bypass", 60.96, False, True), ("a.left", "b.bypass", 91.44, True, True)]


def test_fixed_minimum_gives_warnings_or_strict_errors(tmp_path):
    proj = {"footswitches": {"min_distance_mm": 80}}
    ctx = run(tmp_path, [A(), B()], ONE_EACH, project=proj)
    assert ctx["footswitch_pairs"][0]["too_close"] and ctx["errors"] == []
    assert foot(ctx) == ["footswitch: a.bypass and b.bypass are 76.2 mm apart (min 80.0 mm)"]
    proj["validation"] = {"strict_footswitches": True}
    ctx = run(tmp_path, [A(), B()], ONE_EACH, project=proj)
    assert ctx["errors"] == ["footswitch: a.bypass and b.bypass are 76.2 mm apart (min 80.0 mm)"]
    ok = run(tmp_path, [A(), B()], ONE_EACH, project={"footswitches": {"min_distance_mm": 76.2}})
    assert not ok["footswitch_pairs"][0]["too_close"]                                   # equal is fine


def test_bad_minimum_setting_is_an_error(tmp_path):
    ctx = run(tmp_path, [A(), B()], ONE_EACH, project={"footswitches": {"min_distance_mm": "big"}})
    assert any("min_distance_mm" in e for e in ctx["errors"])


def test_auto_comes_from_the_owner_file_not_the_injected_layout(tmp_path):
    """The owner's file has 76.2 mm; a candidate with B 22.5 px (12.7 mm) closer is 63.5 mm -> too close."""
    items = design.parse_canvas(canvas(A(), B(112.5)))
    ctx = run(tmp_path, [A(), B()], ONE_EACH, items=items)
    assert ctx["layout_source"] == "injected" and ctx["footswitch_settings"]["auto_mm"] == pytest.approx(76.2)
    assert ctx["footswitch_pairs"][0]["distance_mm"] == pytest.approx(63.5)
    assert foot(ctx) == ["footswitch: a.bypass and b.bypass are 63.5 mm apart (min 76.2 mm, auto)"]


def test_empty_list_is_not_missing_and_missing_is_reported(tmp_path):
    ctx = run(tmp_path, [A(), B()], {"a": []})
    assert ctx["footswitch_setup"] == {"a": "none", "b": "missing"}
    assert ctx["footswitch_fixes"] == [("b", "python3 scripts/pedal_editor.py b --footswitches")]
    assert foot(ctx) == ["footswitches: no footswitch data for 1 of 2 pedals (b) -> run: "
                         "python3 scripts/pedal_editor.py --list-missing t --only footswitches"]
    assert ctx["footswitch_pairs"] == [] and ctx["footswitch_settings"]["min_distance_mm"] is None
    strict = run(tmp_path, [A(), B()], {"a": []}, project={"validation": {"require_footswitches": True}})
    assert len(strict["errors"]) == 1 and strict["errors"][0].startswith("footswitches: no footswitch data")


def test_no_design_file_checks_only_the_data(tmp_path):
    ctx = {"project": {}, "dir": tmp_path, "key": "t", "errors": [], "warnings": [], "chain": ["a", "b"],
           "pedals": PEDALS, "supplies": []}
    jacks.check(ctx, PEDALS, {}, DATA, cable_types={})
    fsw.check(ctx, PEDALS, ONE_EACH)
    assert ctx["footswitch_setup"] == {"a": "ok", "b": "ok"} and ctx["footswitch_pairs"] == []
    assert not ctx["footswitch_settings"]["layout"] and foot(ctx) == []


# --- file layer ---------------------------------------------------------------------------------
def test_save_keeps_empty_lists_and_none_removes(tmp_path):
    path = tmp_path / "footswitches.json"
    fsw.save_footswitches("p1", [sw(x=0.123456)], path)
    fsw.save_footswitches("p2", [], path)
    data = json.loads(path.read_text())
    assert data["footswitches"] == {"p1": [{"id": "bypass", "label": "Bypass", "x": 0.1235, "y": 0.8, "bypass": True}], "p2": []}
    assert '"p2": []' in path.read_text() and data["_doc"] == fsw.DOC
    fsw.save_footswitches("p1", None, path)
    assert fsw.read_file(path)["footswitches"] == {"p2": []} and not list(tmp_path.glob("*.tmp"))


def test_dump_is_one_switch_per_line_and_stable(tmp_path):
    path = tmp_path / "footswitches.json"
    fsw.save_footswitches("p1", [sw("left", bypass=False, diameter_mm=None), sw("right")], path)
    text = path.read_text()
    assert len([l for l in text.splitlines() if l.strip().startswith('{"id"')]) == 2
    assert '{"id": "left", "label": "Left", "x": 0.5, "y": 0.8, "bypass": false, "diameter_mm": null}' in text
    fsw.save_footswitches("p1", fsw.read_file(path)["footswitches"]["p1"], path)
    assert path.read_text() == text


@pytest.mark.parametrize("bad,fragment", [
    ({"id": "x"}, "missing"), (sw(x=1.5), "0..1"), (sw(bypass="yes"), "bypass must be"),
    (sw(diameter_mm=-3), "diameter_mm"),
])
def test_validate_flags_bad_switches(bad, fragment):
    problems = fsw.validate_file({"footswitches": {"p1": [bad]}}, {"p1": {}}, {})
    assert any(fragment in m for m in problems["p1"])


def test_validate_flags_duplicates_supplies_and_unknown_ids():
    data = {"footswitches": {"p1": [sw(), sw()], "s1": [], "nope": [], "p2": "none"}}
    problems = fsw.validate_file(data, {"p1": {}, "p2": {}}, {"s1": {}})
    assert any("duplicate" in m for m in problems["p1"])
    assert problems["s1"] == ["power supplies have no footswitches"] and problems["nope"] == ["not a pedal id in the catalog"]
    assert any("must be a list" in m for m in problems["p2"])
    assert fsw.validate_file({"footswitches": {"p1": [sw()], "p2": []}}, {"p1": {}, "p2": {}}, {}) == {}


def test_usable_drops_malformed_switches_and_keeps_empty_lists():
    assert fsw.usable({"p1": [sw(), {"id": "x"}, sw(bypass=1)], "p2": [], "p3": "bad"}) == {"p1": [sw()], "p2": []}


def test_real_file_is_valid():
    from common import load_catalog
    pedals, supplies = load_catalog()
    assert fsw.validate_file(fsw.read_file(), pedals, supplies) == {}


def test_gig_build_with_switch_data_has_no_findings_under_auto():
    """One centre switch per gig pedal (invented positions, test only): auto = the closest pair, so no findings;
    the README lists the closest pairs and the SVG draws the switches."""
    import build
    import routing
    from common import load_catalog
    pedals, supplies = load_catalog()
    gig = ROOT / "projects" / "guitar-gig"
    chain = json.loads((gig / "project.json").read_text())["signal_chain"]
    ctx = build.validate(gig, pedals, supplies, footswitch_data={c: [sw()] for c in chain})
    prs = ctx["footswitch_pairs"]
    assert len(prs) == len(chain) * (len(chain) - 1) // 2 and not any(r["too_close"] for r in prs)
    assert ctx["footswitch_settings"]["min_distance_mm"] == pytest.approx(prs[0]["distance_mm"])
    assert foot(ctx) == []
    md = "\n".join(build.footswitch_section(ctx, pedals))
    assert f"Closest pairs ({fsw.TOP_PAIRS} of {len(prs)})" in md and "No pair is closer than the minimum." in md
    picture = routing.svg(ctx, {})
    assert picture.count("<circle") == len(chain) and "stroke-dasharray=\"3 2\"" not in picture


def test_tap_flag_is_optional_stored_only_when_true_and_validated(tmp_path):
    path = tmp_path / "footswitches.json"
    fsw.save_footswitches("p1", [sw("bypass"), sw("tap", bypass=False, tap=True), sw("preset", bypass=False, tap=False)], path)
    stored = fsw.read_file(path)["footswitches"]["p1"]
    assert [f.get("tap") for f in stored] == [None, True, None]
    assert '{"id": "tap", "label": "Tap", "x": 0.5, "y": 0.8, "bypass": false, "tap": true}' in path.read_text()
    problems = fsw.validate_file({"footswitches": {"p1": [sw(tap="yes")]}}, {"p1": {}}, {})
    assert problems == {"p1": ["footswitch bypass: tap must be true or false"]}
    assert fsw.validate_file({"footswitches": {"p1": stored}}, {"p1": {}}, {}) == {}


def test_pairs_carry_the_tap_flags(tmp_path):
    ctx = run(tmp_path, [A(), B()], {"a": [sw("tap", bypass=False, tap=True)], "b": [sw()]})
    (pair,) = ctx["footswitch_pairs"]
    assert (pair["a_bypass"], pair["a_tap"], pair["b_bypass"], pair["b_tap"]) == (False, True, True, False)
