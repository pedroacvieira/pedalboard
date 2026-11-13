"""Per-pedal preference profiles (scripts/preferences.py, project.json `pedals.<id>`): lowering to the old keys, reading old
keys, validation messages, migration; equivalence on the frozen guitar-gig fixture (its project.json still uses the OLD keys)."""
import copy
import functools
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import build  # noqa: E402
import design  # noqa: E402
import footswitches  # noqa: E402
import jacks  # noqa: E402
import layout  # noqa: E402
import preferences as pref  # noqa: E402
from common import load_cable_types, load_catalog, load_json  # noqa: E402
from conftest import GIG_FIXTURE as GIG  # noqa: E402

CAT = {"a": {"power_consumption": {"min_voltage_v": 9, "max_voltage_v": 18}}, "b": {"power_consumption": {"min_voltage_v": 9, "max_voltage_v": 9}},
       "c": {}, "dormant": {}}
SUPS = {"ojai": {"id": "ojai", "outputs": [{"port": "F1", "options": [{"voltage_v": 9, "max_ma": 500}]},
                                           {"port": "SW_A", "options": [{"voltage_v": 9, "max_ma": 500}, {"voltage_v": 18, "max_ma": 500}]}]}}
FS = {"a": [{"id": "bypass"}, {"id": "switch_2"}], "b": []}
CHAIN = ["a", "b", "c"]


def proj(**kw):
    return {"signal_chain": CHAIN, "power": {"supplies": [{"id": "psu1", "supply": "ojai", "outputs": []}]}, **kw}


RULE = {"type": "after", "pedals": ["b"], "strength": "required", "reason": "x"}


def check(p, chain=CHAIN, fs=FS):
    return pref.validate(p, CAT, SUPS, fs, chain)


# --- 1: lower maps every field to its old key -----------------------------------------------------------------------------------
def test_lower_maps_each_field_to_its_old_key():
    p = proj(pedals={
        "a": {"position": {"depth": "back", "weight": 0.5}, "pin": True, "rotations": [0, 90], "toppers": ["bypass"],
              "order": {"after_b": {**RULE, "priority": 5}}},
        "b": {"rotations": "any", "position": {"depth": "any"}},
        "c": {"rotations": "current", "position": {"side": "left"}},
    })
    low = pref.lower(p)
    assert low["rules"] == [{"id": "a.after_b", "pedal": "a", **RULE, "priority": 5}]
    assert low["layout"]["pins"] == ["a"]
    assert low["layout"]["rotations"] == {"a": [0, 90], "b": "any", "c": "current"}
    assert low["layout"]["access"]["pedals"] == {"a": {"want": "back", "weight": 0.5}, "b": {"want": "none", "weight": 0.3}}   # any -> "none"; default weight
    assert low["footswitches"]["toppers"] == ["a.bypass"]
    assert "pedals" in low and "pedals" in p and "rules" not in p and "layout" not in p      # a copy; the input is untouched
    assert pref.lower(proj()) == proj()                                                       # no profiles: the project as is


def test_lower_is_idempotent_and_agrees_with_equal_old_keys():
    p = proj(pedals={"a": {"pin": True, "rotations": [0], "position": {"depth": "front", "weight": 0.2}, "toppers": ["bypass"], "order": {"x": RULE}},
                     "c": {"order": {"y": {**RULE, "priority": 0}}}},
             rules=[{"id": "c.y", "pedal": "c", **RULE}], layout={"pins": ["psu1", "a"], "rotations": {"default": [0], "a": [0], "psu1": [0]},
                                                                  "access": {"pedals": {"a": {"want": "front", "weight": 0.2}}}},
             footswitches={"toppers": ["a.bypass"], "comfort_mm": 90})
    low = pref.lower(p)
    assert pref.lower(low) == low
    assert [r["id"] for r in low["rules"]] == ["c.y", "a.x"]            # the equal rule (priority 0 = missing) is kept once
    assert low["layout"]["pins"] == ["psu1", "a"] and low["footswitches"]["toppers"] == ["a.bypass"] and low["footswitches"]["comfort_mm"] == 90
    assert check(p)[0] == []                                           # equal old + profile = no error
    differ = copy.deepcopy(p)
    differ["layout"]["rotations"]["a"] = [90]
    differ["layout"]["access"] = {"pedals": {"a": {"want": "back", "weight": 0.2}}}
    errs = check(differ)[0]
    assert "pedals.a.rotations and layout.rotations.a disagree: [0] vs [90]" in errs
    assert "pedals.a.position.depth and layout.access.pedals.a disagree: 'front' vs 'back'" in errs
    assert check({"signal_chain": CHAIN, "layout": {"pins": ["a"]}, "pedals": {"a": {"pin": False}}})[0] == ["pedals.a.pin and layout.pins disagree: False vs True"]


def test_old_keys_are_read_as_profiles_and_dormant_pedals_are_not_lowered():
    p = proj(rules=[{"id": "a.after_b", "pedal": "a", **RULE}, {"id": "free_form", "pedal": "a", **RULE}],
             layout={"pins": ["a", "psu1"], "rotations": {"default": [0], "b": "any", "psu1": [0]}, "access": {"pedals": {"c": {"want": "front", "weight": 0.1}}}},
             footswitches={"toppers": ["a.switch_2"]})
    prof = pref.profiles(p)
    assert prof["a"]["order"] == {"after_b": RULE} and prof["a"]["pin"] is True and prof["a"]["toppers"] == ["switch_2"]    # "free_form" is no <pedal>.<name>
    assert prof["b"]["rotations"] == "any" and prof["c"]["position"] == {"depth": "front", "weight": 0.1, "strength": "preferred"}
    assert "psu1" not in prof and "default" not in prof                                                           # supply instances are no pedals
    q = proj(signal_chain=["a"], pedals={"dormant": {"pin": True, "rotations": [0], "toppers": ["bypass"], "position": {"depth": "back"},
                                                     "order": {"x": RULE}}})
    low = pref.lower(q)
    assert low["rules"] == [{"id": "dormant.x", "pedal": "dormant", **RULE}]       # the build skips it (skipped_rules), as today
    assert not low.get("layout") and not low.get("footswitches")                    # no pin / rotation / depth / topper of a pedal that is not placed


# --- 3: rule order ---------------------------------------------------------------------------------------------------------
def test_lowered_rule_order_old_first_then_chain_order_then_dormant_alphabetically():
    r = lambda n: {**RULE, "reason": n}
    p = proj(signal_chain=["a", "b", "c"], rules=[{"id": "b.old", "pedal": "b", **RULE}],
             pedals={"zed": {"order": {"z1": r("z1")}}, "c": {"order": {"c1": r("c1"), "c2": r("c2")}}, "dormant": {"order": {"d": r("d")}},
                     "a": {"order": {"a1": r("a1")}}, "b": {"order": {"b2": r("b2")}}})
    assert [x["id"] for x in pref.lower(p)["rules"]] == ["b.old", "a.a1", "b.b2", "c.c1", "c.c2", "dormant.d", "zed.z1"]
    clash = proj(rules=[{"id": "a.x", "pedal": "a", **RULE}], pedals={"a": {"order": {"x": {**RULE, "pedals": ["c"]}}}})
    assert [x["id"] for x in pref.lower(clash)["rules"]] == ["a.x", "a.x"]          # differs: both stay, the build says "duplicate rule id"


# --- 4: validation messages --------------------------------------------------------------------------------------------------
def errors_of(profile, pid="a", **kw):
    return check(proj(pedals={pid: profile}, **kw))


@pytest.mark.parametrize("profile, message", [
    ({"zzz": 1}, "pedals.a: unknown key 'zzz' (known: position, pin, rotations, order, power, toppers, note)"),
    ({"position": {"side": "up"}}, "pedals.a.position.side must be left, right or any, got 'up'"),
    ({"position": {"depth": "mid"}}, "pedals.a.position.depth must be front, back, avoid_front or any, got 'mid'"),
    ({"position": {"strength": "maybe"}}, "pedals.a.position.strength must be required or preferred, got 'maybe'"),
    ({"position": {"weight": -1}}, "pedals.a.position.weight must be a number >= 0, got -1"),
    ({"position": {"weight": "x"}}, "pedals.a.position.weight must be a number >= 0, got 'x'"),
    ({"pin": "yes"}, "pedals.a.pin must be true or false, got 'yes'"),
    ({"rotations": [0, 45]}, "pedals.a.rotations must be a list of 0, 90, 270, or \"any\" / \"current\", got [0, 45]"),
    ({"rotations": "sometimes"}, "pedals.a.rotations must be a list of 0, 90, 270, or \"any\" / \"current\", got 'sometimes'"),
    ({"rotations": [0, 180]}, "pedals.a.rotations: 180 is never allowed"),
    ({"order": {"Bad-Name": RULE}}, "pedals.a.order: 'Bad-Name' is not a valid name ([a-z0-9_]+)"),
    ({"order": {"x": {**RULE, "id": "a.x"}}}, "rules: a.x: must not have 'id' (the rule id is <pedal>.<name>)"),
    ({"order": {"x": {"type": "after", "strength": "required"}}}, "rules: a.x: after needs 'pedals' (a list of pedal ids)"),
    ({"order": {"x": {"type": "position", "value": "mid", "strength": "required"}}}, "rules: a.x: position needs 'value' first or last, got 'mid'"),
    ({"order": {"x": {"type": "before_group", "strength": "required"}}}, "rules: a.x: before_group needs 'group' (a tag)"),
    ({"order": {"x": {"type": "after", "pedals": ["b"]}}}, "rules: a.x: strength must be required or preferred, got None"),
    ({"power": {"supply": "psu9"}}, "pedals.a.power.supply 'psu9' is not a supply instance of power.supplies (psu1)"),
    ({"power": {"supply": "psu1", "port": "F9"}}, "pedals.a.power.port 'F9' is not a port of ojai (F1, SW_A)"),
    ({"power": {"port": "F1"}}, "pedals.a.power.port 'F1' needs power.supply"),
    ({"power": {"voltage_v": 24}}, "pedals.a.power.voltage_v 24 is outside the pedal's range 9-18 V"),
    ({"power": {"voltage_v": 12}}, "pedals.a.power.voltage_v: no output of the project's supplies offers 12 V"),
    ({"power": {"supply": "psu1", "port": "F1", "voltage_v": 18}}, "pedals.a.power.voltage_v: no output of the project's supplies offers 18 V"),
    ({"power": {"strength": "x"}}, "pedals.a.power.strength must be required or preferred, got 'x'"),
    ({"power": {"own_output": 1}}, "pedals.a.power.own_output must be true or false, got 1"),
    ({"toppers": ["nope"]}, "pedals.a.toppers: 'nope' is not a footswitch of a (bypass, switch_2)"),
    ({"note": 3}, "pedals.a.note must be a string, got 3"),
])
def test_validation_errors(profile, message):
    assert message in errors_of(profile)[0]


def test_validation_accepts_good_profiles_and_reports_the_rest():
    good = {"position": {"side": "left", "depth": "front", "weight": 0.3, "strength": "required"}, "pin": False, "rotations": [0, 90, 270],
            "order": {"x": RULE}, "power": {"own_output": True, "supply": "psu1", "port": "SW_A", "voltage_v": 18, "strength": "preferred"},
            "toppers": ["bypass"], "note": "hello"}
    assert errors_of(good) == ([], [], [])
    assert errors_of({"power": {"voltage_v": 18}})[0] == []                      # some output offers 18 V
    assert check(proj())[0] == [] and check({"signal_chain": CHAIN})[0] == []    # no profiles: nothing
    assert check(proj(pedals=["a"]))[0] == ["pedals must be an object {pedal id: profile}, got ['a']"]
    assert errors_of({}, pid="nope")[0] == ["pedals: 'nope' is not in catalog/pedals.json"]
    assert errors_of("x")[0] == ["pedals.a must be an object, got 'x'"]
    errs, warns, notes = errors_of({"pin": True, "rotations": [0]}, pid="dormant")
    assert errs == [] and notes == ["dormant: dormant"] and warns == ["pedals.dormant: pinned, so its rotations wish has no effect"]
    assert errors_of({"toppers": ["bypass"]}, pid="c")[1] == ["pedals.c.toppers: ignored, the footswitch data of c is missing"]   # no data: a warning
    assert errors_of({"toppers": ["x"]}, pid="b")[0] == ["pedals.b.toppers: 'x' is not a footswitch of b ()"]                      # verified none: an error
    # a topper that validate reports is not lowered (the owner sees one message, about the key he wrote)
    low = pref.lower(proj(pedals={"a": {"toppers": ["bypass", "nope"]}, "c": {"toppers": ["x"]}}), FS)
    assert low["footswitches"]["toppers"] == ["a.bypass"]


# --- 5: equivalence on the frozen gig (old keys vs migrated) ------------------------------------------------------------------
@functools.lru_cache(maxsize=1)
def gig():
    pedals, supplies = load_catalog()
    old = load_json(GIG / "project.json")
    new = pref.migrate(old)
    return pedals, supplies, old, new, build.validate(GIG, pedals, supplies, project=old), build.validate(GIG, pedals, supplies, project=new)


def test_migrated_gig_validates_like_the_old_keys():
    _, _, old, new, a, b = gig()
    assert new["rules"] == [] and len(new["pedals"]) > 5
    assert len(old["rules"]) == sum(len(v.get("order", {})) for v in new["pedals"].values())
    assert sorted(a["errors"]) == sorted(b["errors"]) and sorted(a["warnings"]) == sorted(b["warnings"])
    assert {r["id"] for r in a["active_rules"]} == {r["id"] for r in b["active_rules"]}
    assert {r["id"] for r in a["skipped_rules"]} == {r["id"] for r in b["skipped_rules"]} == {"double_dragon.after_sun_face_beano"}
    assert sorted(map(repr, a["overrides"])) == sorted(map(repr, b["overrides"]))
    ca = {c["id"]: c["min_mm"] for c in a["cable_list"]}
    cb = {c["id"]: c["min_mm"] for c in b["cable_list"]}
    assert ca == cb and len(ca) > 20                        # signal and power cables


def test_migrated_gig_gives_the_same_surrogate_model():
    pedals, supplies, old, _, _, _ = gig()
    old = {**old, "layout": {**(old.get("layout") or {}), "pins": ["polytune_3"], "rotations": {"default": [0, 90, 270], "monk": "current"},
                             "access": {"pedals": {"reticon": {"want": "back", "weight": 0.4}}}}}
    old["footswitches"] = {**(old.get("footswitches") or {}), "toppers": ["monk.bypass"]}
    new = pref.migrate(old)
    assert new["pedals"]["polytune_3"]["pin"] is True and new["pedals"]["reticon"]["position"] == {"depth": "back", "weight": 0.4}
    items = design.parse_design(GIG / "playground_design.json")
    args = (items, pedals, supplies, jacks.read_file()["jacks"], footswitches.read_file()["footswitches"], load_cable_types())
    ma, mb = layout.Model(old, *args), layout.Model(new, *args)
    assert ma.pins == mb.pins == {"polytune_3"} and ma.allowed == mb.allowed and ma.access == mb.access
    assert ma.score(ma.owner)[0] == pytest.approx(mb.score(mb.owner)[0])
    assert pref.lower(new)["footswitches"]["toppers"] == ["monk.bypass"]
