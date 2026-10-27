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
import svgdraw  # noqa: E402
from test_check import DATA, PEDALS, canvas  # noqa: E402


def sw(fid="bypass", x=0.5, y=0.8, type="bypass", **kw):
    return {"id": fid, "label": fid.title(), "x": x, "y": y, "type": type, **kw}


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


def test_distance_and_crowding_without_a_minimum(tmp_path):
    """76.2 mm apart, comfort 100 mm, bypass pair (priority 1): crowding = 23.8^2 / 100 = 5.6644; no minimum."""
    ctx = run(tmp_path, [A(), B()], ONE_EACH)
    (pair,) = ctx["footswitch_pairs"]
    assert (pair["a"], pair["b"]) == ("a.bypass", "b.bypass") and pair["distance_mm"] == pytest.approx(76.2)
    st = ctx["footswitch_settings"]
    assert st["min_distance_mm"] is None and st["comfort_mm"] == 100.0
    assert pair["crowding"] == pytest.approx(23.8 ** 2 / 100) and st["crowding"] == pytest.approx(pair["crowding"])
    assert not pair["too_close"] and foot(ctx) == []
    far = run(tmp_path, [A(), B()], ONE_EACH, project={"footswitches": {"comfort_mm": 70}})
    assert far["footswitch_settings"]["crowding"] == 0.0                             # beyond the comfort distance
    fn = run(tmp_path, [A(), B()], {"a": [sw(type="function")], "b": [sw(type="tap")]})
    assert fn["footswitch_pairs"][0]["crowding"] == pytest.approx(0.8 * 23.8 ** 2 / 100)   # max(0.5, 0.8)


def test_rotated_pedal(tmp_path):
    """B rotated 90: centre (101.6, 50.8); the switch is 30.48 mm below the centre, rotated to 30.48 mm left of it
    -> (71.12, 50.8). From (25.4, 81.28): hypot(45.72, 30.48) = 54.95 mm."""
    ctx = run(tmp_path, [A(), B(rot=90)], ONE_EACH)
    p = {q["key"]: q for q in ctx["footswitch_points"]}
    assert (p["b.bypass"]["x"], p["b.bypass"]["y"]) == pytest.approx((71.12, 50.8))
    assert ctx["footswitch_pairs"][0]["distance_mm"] == pytest.approx(math.hypot(45.72, 30.48))


def test_same_pedal_pairs_are_ignored_and_pairs_are_sorted(tmp_path):
    data = {"a": [sw("left", x=0.2), sw("right", x=0.8, type="function")], "b": [sw()]}
    ctx = run(tmp_path, [A(), B()], data)
    got = [(r["a"], r["b"], round(r["distance_mm"], 2), r["a_type"], r["b_type"]) for r in ctx["footswitch_pairs"]]
    # a.right at x 40.64 -> 60.96 mm to b; a.left at 10.16 -> 91.44 mm
    assert got == [("a.right", "b.bypass", 60.96, "function", "bypass"), ("a.left", "b.bypass", 91.44, "bypass", "bypass")]


def test_fixed_minimum_gives_warnings_or_strict_errors(tmp_path):
    proj = {"footswitches": {"min_distance_mm": 80}}
    ctx = run(tmp_path, [A(), B()], ONE_EACH, project=proj)
    assert ctx["footswitch_pairs"][0]["too_close"] and ctx["errors"] == []
    assert foot(ctx) == ["footswitch: a.bypass and b.bypass are 76.2 mm apart (min 80 mm)"]
    proj["validation"] = {"strict_footswitches": True}
    ctx = run(tmp_path, [A(), B()], ONE_EACH, project=proj)
    assert ctx["errors"] == ["footswitch: a.bypass and b.bypass are 76.2 mm apart (min 80 mm)"]
    ok = run(tmp_path, [A(), B()], ONE_EACH, project={"footswitches": {"min_distance_mm": 76.2}})
    assert not ok["footswitch_pairs"][0]["too_close"]                                   # equal is fine


def test_bad_spacing_settings_are_errors(tmp_path):
    for bad in ({"min_distance_mm": "big"}, {"comfort_mm": 0}):
        ctx = run(tmp_path, [A(), B()], ONE_EACH, project={"footswitches": bad})
        assert any(next(iter(bad)) in e for e in ctx["errors"])
    old = run(tmp_path, [A(), B()], ONE_EACH, project={"footswitches": {"min_distance_mm": "auto"}})   # the old default
    assert old["errors"] == [] and old["footswitch_settings"]["min_distance_mm"] is None
    assert any("\"auto\" is no longer used" in w for w in old["warnings"])


def test_an_injected_layout_is_measured_itself(tmp_path):
    """A candidate with B 22.5 px (12.7 mm) closer: 63.5 mm, crowding 36.5^2 / 100; no minimum -> no finding."""
    items = design.parse_canvas(canvas(A(), B(112.5)))
    ctx = run(tmp_path, [A(), B()], ONE_EACH, items=items)
    assert ctx["layout_source"] == "injected" and ctx["footswitch_pairs"][0]["distance_mm"] == pytest.approx(63.5)
    assert ctx["footswitch_settings"]["crowding"] == pytest.approx(36.5 ** 2 / 100) and foot(ctx) == []


def test_empty_list_is_not_missing_and_missing_is_reported(tmp_path):
    ctx = run(tmp_path, [A(), B()], {"a": []})
    assert ctx["footswitch_setup"] == {"a": "none", "b": "missing"}
    assert ctx["footswitch_fixes"] == [("b", "uv run scripts/pedal_editor.py b --footswitches")]
    assert foot(ctx) == ["footswitches: no footswitch data for 1 of 2 pedals (b) -> run: "
                         "uv run scripts/pedal_editor.py --list-missing t --only footswitches"]
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
    assert data["footswitches"] == {"p1": [{"id": "bypass", "label": "Bypass", "x": 0.1235, "y": 0.8, "type": "bypass"}], "p2": []}
    assert '"p2": []' in path.read_text() and data["_doc"] == fsw.DOC
    fsw.save_footswitches("p1", None, path)
    assert fsw.read_file(path)["footswitches"] == {"p2": []} and not list(tmp_path.glob("*.tmp"))


def test_dump_is_one_switch_per_line_and_stable(tmp_path):
    path = tmp_path / "footswitches.json"
    fsw.save_footswitches("p1", [sw("left", type="function", diameter_mm=None), sw("right")], path)
    text = path.read_text()
    assert len([l for l in text.splitlines() if l.strip().startswith('{"id"')]) == 2
    assert '{"id": "left", "label": "Left", "x": 0.5, "y": 0.8, "type": "function", "diameter_mm": null}' in text
    fsw.save_footswitches("p1", fsw.read_file(path)["footswitches"]["p1"], path)
    assert path.read_text() == text


@pytest.mark.parametrize("bad,fragment", [
    ({"id": "x"}, "missing"), (sw(x=1.5), "0..1"), (sw(type="stomp"), "type must be one of"),
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
    assert fsw.usable({"p1": [sw(), {"id": "x"}, sw(type=True)], "p2": [], "p3": "bad"}) == {"p1": [sw()], "p2": []}


def test_real_file_is_valid():
    from common import load_catalog
    pedals, supplies = load_catalog()
    assert fsw.validate_file(fsw.read_file(), pedals, supplies) == {}


def test_gig_build_with_switch_data_has_no_findings_without_a_minimum():
    """One centre switch per gig pedal (invented positions, test only): no minimum, so no findings; the README
    lists the crowding and the closest pairs, the SVG draws the switches."""
    import build
    import routing
    from common import load_catalog
    pedals, supplies = load_catalog()
    gig = ROOT / "projects" / "guitar-gig"
    chain = json.loads((gig / "project.json").read_text())["signal_chain"]
    ctx = build.validate(gig, pedals, supplies, footswitch_data={c: [sw()] for c in chain})
    prs = ctx["footswitch_pairs"]
    assert len(prs) == len(chain) * (len(chain) - 1) // 2 and not any(r["too_close"] for r in prs)
    assert ctx["footswitch_settings"]["min_distance_mm"] is None and foot(ctx) == []
    md = "\n".join(build.footswitch_section(ctx, pedals))
    assert f"Closest pairs ({fsw.TOP_PAIRS} of {len(prs)})" in md and "No minimum distance is set." in md
    assert f"Crowding: {ctx['footswitch_settings']['crowding']:.1f}" in md
    picture = svgdraw.render(ctx, {})
    assert picture.count('class="footswitch"') == len(chain) and 'class="too-close"' not in picture


def test_types_are_stored_and_validated(tmp_path):
    path = tmp_path / "footswitches.json"
    fsw.save_footswitches("p1", [sw("bypass"), sw("tap", type="tap"), sw("boost", type="boost"), sw("oct", type="function")], path)
    stored = fsw.read_file(path)["footswitches"]["p1"]
    assert [f["type"] for f in stored] == ["bypass", "tap", "boost", "function"]
    assert '{"id": "tap", "label": "Tap", "x": 0.5, "y": 0.8, "type": "tap"}' in path.read_text()
    assert fsw.validate_file({"footswitches": {"p1": stored}}, {"p1": {}}, {}) == {}
    problems = fsw.validate_file({"footswitches": {"p1": [{**sw(), "type": "preset"}]}}, {"p1": {}}, {})
    assert problems == {"p1": ["footswitch bypass: type must be one of bypass, tap, boost, function, got 'preset'"]}


def test_priorities_and_pair_priority():
    prio = fsw.priorities({})
    assert prio == {"bypass": 1.0, "boost": 0.8, "tap": 0.8, "function": 0.5}
    assert fsw.pair_priority(prio, "function", "bypass") == 1.0 and fsw.pair_priority(prio, "function", "tap") == 0.8
    assert fsw.pair_priority(prio, "function", "function") == 0.5
    assert fsw.priorities({"footswitches": {"priority": {"function": 0.2}}})["function"] == 0.2


def test_pairs_carry_the_types(tmp_path):
    ctx = run(tmp_path, [A(), B()], {"a": [sw("tap", type="tap")], "b": [sw()]})
    (pair,) = ctx["footswitch_pairs"]
    assert (pair["a_type"], pair["b_type"]) == ("tap", "bypass")


def test_svg_has_a_marker_style_per_type():
    assert set(svgdraw.FOOTSWITCH_STYLE) == set(fsw.TYPES)


# --- toppers ---------------------------------------------------------------------------------------
TOP = {"footswitches": {"toppers": ["a.bypass"]}}


def test_effective_distance_and_crowding_with_zero_one_two_toppers(tmp_path):
    """76.2 mm bypass pair, comfort 100, bonus 10: d_eff 76.2 / 86.2 / 96.2 -> crowding 23.8^2/100 = 5.6644,
    13.8^2/100 = 1.9044, 3.8^2/100 = 0.1444."""
    assert fsw.effective_distance(76.2, 0, 10) == 76.2 and fsw.effective_distance(76.2, 2, 10) == pytest.approx(96.2)
    for toppers, d_eff, crowd in ((None, 76.2, 5.6644), (["a.bypass"], 86.2, 1.9044),
                                  (["a.bypass", "b.bypass"], 96.2, 0.1444)):
        proj = {"footswitches": {"toppers": toppers}} if toppers else {}
        ctx = run(tmp_path, [A(), B()], ONE_EACH, project=proj)
        (pair,) = ctx["footswitch_pairs"]
        assert pair["distance_mm"] == pytest.approx(76.2) and pair["effective_mm"] == pytest.approx(d_eff)
        assert pair["crowding"] == pytest.approx(crowd) and ctx["footswitch_settings"]["crowding"] == pytest.approx(crowd)
        assert ctx["footswitch_settings"]["crowding_plain"] == pytest.approx(5.6644) and ctx["errors"] == []
    ctx = run(tmp_path, [A(), B()], ONE_EACH, project={"footswitches": {"toppers": ["a.bypass"], "topper_bonus_mm": 20}})
    assert ctx["footswitch_pairs"][0]["effective_mm"] == pytest.approx(96.2)


def test_minimum_distance_uses_the_effective_distance(tmp_path):
    proj = {"footswitches": {"min_distance_mm": 80, "toppers": ["a.bypass"]}}
    assert foot(run(tmp_path, [A(), B()], ONE_EACH, project={"footswitches": {"min_distance_mm": 80}}))   # 76.2 < 80
    ctx = run(tmp_path, [A(), B()], ONE_EACH, project=proj)                                            # 86.2 >= 80
    assert foot(ctx) == [] and not ctx["footswitch_pairs"][0]["too_close"]
    ctx = run(tmp_path, [A(), B()], ONE_EACH, project={"footswitches": {"min_distance_mm": 90, "toppers": ["a.bypass"]}})
    assert "86.2 mm apart (effective with toppers, 76.2 mm plain) (min 90 mm)" in foot(ctx)[0]


@pytest.mark.parametrize("cfg,fragment", [
    ({"toppers": ["a.nope"]}, "a.nope is not a footswitch of a pedal in the signal chain"),
    ({"toppers": ["zzz.bypass"]}, "zzz.bypass is not a footswitch"),
    ({"toppers": ["a.bypass", "a.bypass"]}, "a.bypass is listed twice"),
    ({"toppers": "a.bypass"}, "footswitches.toppers must be a list"),
    ({"topper_bonus_mm": -1}, "topper_bonus_mm must be a number >= 0"),
    ({"topper_bonus_mm": "x"}, "topper_bonus_mm must be a number >= 0"),
    ({"max_toppers": -1}, "max_toppers must be an integer >= 0"),
    ({"max_toppers": 1.5}, "max_toppers must be an integer >= 0"),
    ({"topper_min_gain": 1.5}, "topper_min_gain must be a number in 0..1"),
])
def test_topper_settings_errors(tmp_path, cfg, fragment):
    ctx = run(tmp_path, [A(), B()], ONE_EACH, project={"footswitches": cfg})
    assert any(fragment in e for e in ctx["errors"]), ctx["errors"]


def test_valid_zero_values_and_cap_warning(tmp_path):
    cfg = {"toppers": ["a.bypass", "b.bypass"], "topper_bonus_mm": 0, "max_toppers": 1, "topper_min_gain": 0}
    ctx = run(tmp_path, [A(), B()], ONE_EACH, project={"footswitches": cfg})
    assert ctx["errors"] == [] and any("2 toppers are listed, more than max_toppers (1)" in w for w in ctx["warnings"])
    assert ctx["footswitch_pairs"][0]["effective_mm"] == pytest.approx(76.2)     # bonus 0: no change
    ctx = run(tmp_path, [A(), B()], ONE_EACH, project={"footswitches": {"max_toppers": 0}})
    assert ctx["errors"] == [] and ctx["footswitch_suggestions"]["suggestions"] == []


def _synthetic(*switches):
    """Points and pairs (as footswitches.points / pairs make them) from (key, type, x, y)."""
    pts = [{"key": k, "cid": k.split(".")[0], "id": "s", "label": k, "type": t, "x": x, "y": y} for k, t, x, y in switches]
    return pts, fsw.pairs(pts)


PRIO = fsw.PRIORITY


def test_greedy_order_picks_the_switch_shared_by_two_close_pairs_first():
    """a, b, c in a row 60 mm apart (a-c 120 mm): crowding 16 + 16 = 32. A topper on b: both pairs 70 -> 9 + 9, gain 14
    (on a: 16 - 9 = 7). Then a and c tie at gain 5 (a-b 70 -> 80: 9 -> 4; one pair each) -> c is nearer the front
    (larger y), then a."""
    pts, prs = _synthetic(("a.s", "bypass", 0, 0), ("b.s", "bypass", 60, 0), ("c.s", "bypass", 120, 0))
    pts[2]["y"] = 0.001   # nearer the front, distances unchanged within rounding
    out = fsw.suggest_toppers(pts, prs, PRIO, 100.0, 10.0)
    assert out["before"] == pytest.approx(32.0)
    got = [(s["key"], round(s["gain"], 3), round(s["crowding_after"], 3)) for s in out["suggestions"]]
    assert got == [("b.s", 14.0, 18.0), ("c.s", 5.0, 13.0), ("a.s", 5.0, 8.0)]
    assert out["after"] == pytest.approx(8.0)


def test_tie_goes_to_the_higher_type_priority_then_the_front():
    """x (function) and y (bypass) 60 mm apart: either topper gains the same (the pair weighs the larger priority);
    the bypass switch wins although it is further back; with equal types the larger y wins."""
    pts, prs = _synthetic(("p.s", "function", 0, 0), ("q.s", "bypass", 60, 0))
    pts[0]["y"] = 0.001
    out = fsw.suggest_toppers(pts, prs, PRIO, 100.0, 10.0)
    assert out["suggestions"][0]["key"] == "q.s" and out["suggestions"][0]["gain"] == pytest.approx(7.0)
    pts, prs = _synthetic(("p.s", "bypass", 0, 0), ("q.s", "bypass", 60, 0))
    pts[1]["y"] = 0.001
    assert fsw.suggest_toppers(pts, prs, PRIO, 100.0, 10.0)["suggestions"][0]["key"] == "q.s"
    pts[0]["y"] = 0.002
    assert fsw.suggest_toppers(pts, prs, PRIO, 100.0, 10.0)["suggestions"][0]["key"] == "p.s"


def test_cap_threshold_existing_and_none_needed():
    pts, prs = _synthetic(("a.s", "bypass", 0, 0), ("b.s", "bypass", 60, 0), ("c.s", "bypass", 120, 0))
    cap1 = fsw.suggest_toppers(pts, prs, PRIO, 100.0, 10.0, max_toppers=1)
    assert [s["key"] for s in cap1["suggestions"]] == ["b.s"]
    # a topper already on b counts towards the cap: nothing left to suggest
    assert fsw.suggest_toppers(pts, prs, PRIO, 100.0, 10.0, existing=["b.s"], max_toppers=1)["suggestions"] == []
    # with b toppered the crowding is 18 and every further gain is 5 (a: 9 -> 4; then c: 9 -> 4 ... 13 -> 8)
    assert len(fsw.suggest_toppers(pts, prs, PRIO, 100.0, 10.0, existing=["b.s"], min_gain=0.2)["suggestions"]) == 2
    assert fsw.suggest_toppers(pts, prs, PRIO, 100.0, 10.0, existing=["b.s"], min_gain=0.3)["suggestions"] == []
    # threshold 0.5 x 32 = 16: even the first gain (14) is below it
    assert fsw.suggest_toppers(pts, prs, PRIO, 100.0, 10.0, min_gain=0.5)["suggestions"] == []
    # nothing crowded: none needed
    far = fsw.suggest_toppers(*_synthetic(("a.s", "bypass", 0, 0), ("b.s", "bypass", 150, 0)), PRIO, 100.0, 10.0)
    assert far["before"] == 0 and far["suggestions"] == []


def test_readme_section_with_toppers_and_suggestions(tmp_path):
    import build
    ctx = run(tmp_path, [A(), B()], ONE_EACH, project=TOP)
    md = "\n".join(build.footswitch_section(ctx, PEDALS))
    assert "Crowding: 1.9 with 1 topper(s) (5.7 without toppers)" in md
    assert "Toppers set (`footswitches.toppers`): a.bypass." in md and "checked on the effective distance" not in md
    assert "| Switch | Type | Switch | Type | Distance (mm) | Effective (mm) | Crowding |" in md
    assert "| a.bypass (topper) | bypass | b.bypass | bypass | 76.2 | 86.2 | 1.9 |" in md
    assert "### Suggested toppers" in md
    # b's topper takes the pair to 96.2 mm: crowding 1.9 -> 0.1, gain 1.8 >= 5 % of 1.9
    assert "| 1 | b.bypass (Bypass) | T B | bypass | 1.8 | 0.1 |" in md
    md = "\n".join(build.footswitch_section(run(tmp_path, [A(), B()], ONE_EACH), PEDALS))
    assert "No toppers are set." in md and "without toppers" not in md and "Effective (mm)" not in md
    assert "| 1 | a.bypass (Bypass) | T A | bypass | 3.8 | 1.9 |" in md   # tie (same gain, type, y): first key
    far = "\n".join(build.footswitch_section(run(tmp_path, [A(), B(left=400)], ONE_EACH), PEDALS))
    assert "None needed." in far
    md = "\n".join(build.footswitch_section(run(tmp_path, [A(), B()], ONE_EACH, project={"footswitches": {
        "min_distance_mm": 80}}), PEDALS))
    assert "checked on the effective distance" in md


def test_svg_draws_rings_for_toppers_and_suggestions(tmp_path):
    import build
    from common import load_catalog
    pedals, supplies = load_catalog()
    gig = ROOT / "projects" / "guitar-gig"
    project = json.loads((gig / "project.json").read_text())
    chain = project["signal_chain"]
    project["footswitches"] = {"toppers": [f"{chain[0]}.bypass"]}
    ctx = build.validate(gig, pedals, supplies, footswitch_data={c: [sw()] for c in chain}, project=project)
    sug = ctx["footswitch_suggestions"]["suggestions"]
    picture = svgdraw.render(ctx, {})
    assert picture.count('class="topper"') == 1 and picture.count('class="topper-suggested"') == len(sug) > 0
    assert "solid ring: topper on the footswitch" in picture and "dashed orange ring: suggested topper" in picture
    plain = svgdraw.render(build.validate(gig, pedals, supplies, footswitch_data={c: [sw()] for c in chain}), {})
    assert 'class="topper"' not in plain and "solid ring" not in plain
