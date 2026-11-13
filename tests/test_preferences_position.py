"""Position wishes of the profiles (`pedals.<id>.position`): the met test, the search's `position` term, `access_rule` "none", the build's
findings and `ctx["preferences"]`."""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import build  # noqa: E402
import layout  # noqa: E402
import preferences as pref  # noqa: E402
from common import load_catalog, load_json  # noqa: E402
from conftest import GIG_FIXTURE  # noqa: E402
from test_layout import model, ped, sw  # noqa: E402


# --- 7: met -----------------------------------------------------------------------------------------------------------------------
def test_met_half_left_right_front_back_on_a_200_mm_board():
    assert pref.met_half("left", 90, 0, 200) == (True, -10)         # 10 mm left of the middle
    assert pref.met_half("left", 110, 0, 200) == (False, 10)        # 10 mm right of it: 10 mm past
    assert pref.met_half("right", 110, 0, 200) == (True, -10) and pref.met_half("right", 90, 0, 200) == (False, 10)
    assert pref.met_half("left", 100, 0, 200)[0] is True            # the middle line itself is met
    # y grows to the FRONT: back = the low half, front = the high half, avoid_front = not the front half
    assert pref.met_half("back", 90, 0, 200) == (True, -10) and pref.met_half("front", 90, 0, 200) == (False, 10)
    assert pref.met_half("avoid_front", 110, 0, 200) == (False, 10) and pref.met_half("avoid_front", 100, 0, 200)[0] is True
    assert pref.met_position({"side": "left", "depth": None}, (110, 5), (0, 0, 200, 200)) == {"side": (False, 10), "depth": None}


def check_ctx(wish, switch_ys=None, project_extra=None):
    """ctx of one chain pedal 'a' (box x 40..90, y 60..160 on a 200 x 200 board) for `preferences.check`."""
    item = {"id": "item-a", "left_mm": 40.0, "top_mm": 60.0, "w_mm": 50.0, "h_mm": 100.0, "rot": 0}
    ctx = {"project": {"signal_chain": ["a"], "pedals": {"a": wish}, **(project_extra or {})}, "chain": ["a"], "errors": [], "warnings": [],
           "layout": {"placed": {"a": item}, "bodies": {}, "board_rect": (0.0, 0.0, 200.0, 200.0)},
           "footswitch_points": [{"cid": "a", "y": y} for y in switch_ys or []]}
    pref.check(ctx, {})
    return ctx


def test_depth_reference_is_the_footswitch_mean_and_side_the_body_centre():
    ctx = check_ctx({"position": {"depth": "back", "strength": "required"}}, switch_ys=[80, 100])   # mean 90: back half
    (row,) = ctx["preferences"]
    assert (row["kind"], row["met"], row["detail"], row["wish"]) == ("position.depth", True, "10 mm inside", "back half") and ctx["warnings"] == []
    ctx = check_ctx({"position": {"depth": "front", "strength": "required"}}, switch_ys=[80, 100])
    assert ctx["preferences"][0]["met"] is False and ctx["warnings"] == [
        "preferences: a: wants the front half (required); its footswitches' mean is 10 mm past the middle"]
    ctx = check_ctx({"position": {"side": "right", "depth": "avoid_front"}})   # no switches: the centre (65, 110); preferred: never a finding
    assert [(r["kind"], r["met"], r["detail"]) for r in ctx["preferences"]] == [("position.side", False, "35 mm past the middle"),
                                                                              ("position.depth", False, "10 mm past the middle")]
    assert ctx["warnings"] == [] and ctx["errors"] == []
    ctx = check_ctx({"position": {"side": "left", "strength": "required"}}, project_extra={"validation": {"strict_preferences": True}})
    assert ctx["errors"] == [] and ctx["preferences"][0]["met"] is True                   # centre 65 < 100: inside
    ctx = check_ctx({"position": {"side": "right", "strength": "required"}}, project_extra={"validation": {"strict_preferences": True}})
    assert ctx["errors"] == ["preferences: a: wants the right half (required); its body centre is 35 mm past the middle"] and ctx["warnings"] == []


def test_applied_settings_and_order_rows():
    ctx = check_ctx({"pin": True, "rotations": [0, 90], "toppers": ["bypass"], "position": {"depth": "any"},
                     "order": {"x": {"type": "after", "pedals": ["b"], "strength": "required"}, "y": {"type": "position", "value": "last", "strength": "preferred"},
                               "z": {"type": "before_group", "group": "gain", "strength": "required"}, "w": {"type": "after", "pedals": ["b"], "strength": "required"}}},
                    project_extra={"rule_status": None})
    assert ctx["preferences"][0]["wish"] == "no depth wish"
    ctx["rule_status"] = {"a.x": "met", "a.y": "broken", "a.z": "overridden"}
    pref.check(ctx, {})
    rows = {(r["kind"], r.get("name")): r for r in ctx["preferences"]}
    assert rows[("order", "x")]["met"] is True and rows[("order", "y")]["met"] is False and rows[("order", "z")]["met"] is False
    assert rows[("order", "z")]["detail"] == "overridden by a higher priority" and ("order", "w") not in rows          # no status (not built): no row
    assert rows[("order", "y")]["wish"] == "last in the chain" and rows[("order", "x")]["wish"] == "after b"
    assert [rows[k]["detail"] for k in (("pin", None), ("rotations", None), ("toppers", None))] == ["applied"] * 3
    assert rows[("rotations", None)]["wish"] == "rotations 0, 90" and rows[("toppers", None)]["wish"] == "topper on bypass"


# --- 8: the search's `position` term -----------------------------------------------------------------------------------------------
def term(m, state=None):
    return m.score(state or m.owner, detail=True)[1]["terms"]["position"]


def test_position_term_pulls_by_weight_and_penalises_a_required_miss():
    wish = {"a": {"position": {"side": "left", "weight": 0.3}}}
    m = model([ped("T A", 0), ped("T B", 135)], project_extra={"pedals": wish})
    assert m.position[0] == {"side": "left", "depth": None, "weight": 0.3, "required": False} and m.position[1] is None
    raw, weighted = term(m)
    assert raw == pytest.approx(0.3 * 25.4) and weighted == pytest.approx(7.62)                      # centre 25.4 mm from the left edge
    assert term(m, [(76.2, 50.8, 0), m.owner[1]])[1] == pytest.approx(0.3 * 76.2)
    # a required wish on a 254 mm wide board: the middle line is x = 127; the body centre at 152.4 is 25.4 mm past it
    req = {"a": {"position": {"side": "left", "weight": 0.3, "strength": "required"}}}
    m = model([ped("T A", 225), ped("T B", 135)], project_extra={"pedals": req})
    st = [(152.4, 50.8, 0), (101.6, 50.8, 0)]
    raw, weighted = term(m, st)
    assert raw == pytest.approx(0.3 * 152.4) and weighted == pytest.approx(0.3 * 152.4 + 100 + 20 * 25.4)
    assert m.score(st, detail=True)[1]["preferences"] == [{"pedal": "a", "kind": "position.side", "mm": pytest.approx(25.4)}]
    assert m.score([(100.0, 50.8, 0), (101.6, 50.8, 0)], detail=True)[1]["preferences"] == []        # inside the left half: no penalty
    assert m.score(m.owner, detail=True)[1]["preferences"]                                          # the owner's layout breaks it (the search starts there)
    # the weights are the project's
    m2 = model([ped("T A", 225), ped("T B", 135)], project_extra={"pedals": req, "layout": {"weights": {"position": 2.0, "preference_miss": 0, "preference_miss_mm": 0}}})
    assert term(m2, st)[1] == pytest.approx(2 * 0.3 * 152.4)


def test_required_depth_uses_the_footswitch_mean_and_no_wish_costs_nothing():
    fs = {"a": [sw("bypass", 0.5, 0.8)]}                         # 30.5 mm in front of the centre (101.6 mm tall)
    back = {"a": {"position": {"depth": "back", "strength": "required"}}}
    m = model([ped("T A", 0), ped("T B", 135)], fs=fs, project_extra={"pedals": back})
    # board y 0..127, middle 63.5; the switch is at 50.8 + 30.48 = 81.28: 17.78 mm into the front half
    assert m.score(m.owner, detail=True)[1]["preferences"] == [{"pedal": "a", "kind": "position.depth", "mm": pytest.approx(17.78)}]
    raw, weighted = term(m)
    assert raw == 0 and weighted == pytest.approx(100 + 20 * 17.78)                  # the pull of a depth wish is the access term, not this one
    acc = m.score(m.owner, detail=True)[1]["terms"]["access"]
    assert acc[0] == pytest.approx(81.28 * 0.3)                                      # lowered layout.access: back, weight 0.3
    front = model([ped("T A", 0), ped("T B", 135)], fs=fs, project_extra={"pedals": {"a": {"position": {"depth": "front", "strength": "required"}}}})
    assert front.score(front.owner, detail=True)[1]["preferences"] == []
    none = model([ped("T A", 0), ped("T B", 135)])
    assert term(none) == (0.0, 0.0) and none.score(none.owner, detail=True)[1]["preferences"] == []


# --- 9: access_rule "none" -------------------------------------------------------------------------------------------------------
def test_depth_any_cancels_the_tag_rule():
    acc = layout.settings({"signal_chain": ["c"], "pedals": {"c": {"position": {"depth": "any"}}}})["access"]
    assert acc["pedals"]["c"] == {"want": "none", "weight": 0.3}
    tuner = {"id": "c", "tags": ["tuner"]}
    assert layout.access_rule(tuner, [], acc) is None                                          # the tuner tag (back) no longer applies
    assert layout.access_rule(tuner, [], layout.settings({})["access"]) == {"want": "back", "weight": 0.5}
    assert layout.access_rule(tuner, [], layout.settings({"signal_chain": ["c"], "pedals": {"c": {"position": {"depth": "front", "weight": 0.2}}}})["access"]) == {"want": "front", "weight": 0.2}


# --- 11: the build -------------------------------------------------------------------------------------------------------------------
def gig_build(profile_for, **extra):
    """build.validate of the frozen gig (no router) with a profile on the pedal whose body centre is farthest right."""
    pedals, supplies = load_catalog()
    base = {**load_json(GIG_FIXTURE / "project.json"), **extra}
    ctx = build.validate(GIG_FIXTURE, pedals, supplies, project=base, route=False)
    lay = ctx["layout"]
    right = max(lay["placed"], key=lambda p: lay["placed"][p]["left_mm"] + lay["placed"][p]["w_mm"] / 2)
    base["pedals"] = {right: profile_for}
    return right, build.validate(GIG_FIXTURE, pedals, supplies, project=base, route=False)


def test_required_side_not_met_is_a_warning_and_an_error_when_strict():
    right, ctx = gig_build({"position": {"side": "left", "strength": "required"}})
    mine = [w for w in ctx["warnings"] if w.startswith("preferences:")]
    assert len(mine) == 1 and mine[0].startswith(f"preferences: {right}: wants the left half (required); its body centre is ") and mine[0].endswith(" mm past the middle")
    (row,) = [r for r in ctx["preferences"] if r["kind"] == "position.side"]
    assert row["met"] is False and row["pedal"] == right and row["strength"] == "required"
    _, strict = gig_build({"position": {"side": "left", "strength": "required"}}, validation={"no_unknown": True, "strict_preferences": True})
    assert any(e.startswith(f"preferences: {right}: wants the left half") for e in strict["errors"])
    assert not any(w.startswith("preferences:") for w in strict["warnings"])


def test_preferred_side_not_met_is_only_in_the_table_and_rule_status_is_recorded():
    right, ctx = gig_build({"position": {"side": "left"}})                                       # preferred (the default): no finding
    assert not any(m.startswith("preferences:") for m in ctx["warnings"] + ctx["errors"])
    assert [(r["kind"], r["met"], r["strength"]) for r in ctx["preferences"] if r["pedal"] == right and r["kind"].startswith("position")] == [("position.side", False, "preferred")]
    status = ctx["rule_status"]
    assert status["double_dragon.after_sun_face_beano"] == "skipped" and status["beano.after_sun_face"] == "met"
    assert set(status.values()) <= {"met", "broken", "overridden", "skipped", "disabled"}
    _, right_ok = gig_build({"position": {"side": "right", "strength": "required"}})
    assert [r["met"] for r in right_ok["preferences"] if r["kind"] == "position.side"] == [True]
