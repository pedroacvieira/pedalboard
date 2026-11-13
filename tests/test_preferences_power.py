"""Power wishes of the profiles (`pedals.<id>.power`): `power.assign(wishes=)`, `wish_findings`, the build's findings and table rows."""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import build  # noqa: E402
import power  # noqa: E402
import preferences as pref  # noqa: E402
from common import load_catalog, load_json  # noqa: E402
from conftest import GIG_FIXTURE  # noqa: E402


def quiet(vmax=9):
    return {"power_consumption": {"current_ma": 50, "min_voltage_v": 9, "max_voltage_v": vmax, "polarity": "center_negative"},
            "digital": False, "clocked_noise": False, "tags": []}


def supply(*ports):
    return {"id": "s", "polarity": "center_negative",
            "outputs": [{"port": p, "options": [{"voltage_v": 9, "max_ma": 1000}, {"voltage_v": 18, "max_ma": 1000}]} for p in ports]}


def wish(**kw):
    return {"own_output": False, "supply": None, "port": None, "voltage_v": None, "required": False, **kw}


# the plugs of a (100,0) b (110,0) c (100,40) d (110,40); the ports O1 (0,0), O2 (0,40): Manhattan, no holes (as test_daisy_chains)
PEDALS4 = {p: quiet() for p in "abcd"}
INSTS = [{"id": "psu", "supply": "s", "sup": supply("O1", "O2"), "under": False}]
POINTS = {"a": (100, 0), "b": (110, 0), "c": (100, 40), "d": (110, 40)}
PORTS = {("psu", "O1"): (0, 0), ("psu", "O2"): (0, 40)}


def assign(wishes, pedals=PEDALS4, insts=INSTS, points=POINTS, ports=PORTS, chain="abcd", **kw):
    res = power.assign(list(chain), pedals, insts, {}, points, ports, wishes=wishes, **kw)
    return {o["port"]: o["pedals"] for s in res["supplies"] for o in s["outputs"]}, res


def test_no_wishes_change_nothing():
    plain, res = assign(None)
    assert plain == {"O1": ["a", "b", "d", "c"]} and res["length_mm"] == pytest.approx(160.0) and res["preferences"] == []
    assert assign({})[0] == plain and assign({"zzz": wish(own_output=True, required=True)})[0] == plain      # a wish of a pedal not in the chain is ignored


def test_required_port_is_honoured_even_when_longer():
    out, res = assign({"a": wish(supply="psu", port="O2", required=True)})
    assert out == {"O2": ["c", "d", "b", "a"]} and res["length_mm"] == pytest.approx(160.0)       # 100 + 10 + 40 + 10 from (0, 40)
    assert res["preferences"] == [("a", "supply psu, port psu.O2", True)]
    # a alone on O1 would cost 100 + 150 = 250 mm; a required own output has to take that
    out, res = assign({"a": wish(own_output=True, required=True)})
    assert out == {"O1": ["a"], "O2": ["c", "d", "b"]} and res["length_mm"] == pytest.approx(250.0)
    # two pedals that both require the same port and each want it alone: no wiring
    with pytest.raises(ValueError, match="no power wiring"):
        assign({"a": wish(port="O1", own_output=True, required=True), "b": wish(port="O1", own_output=True, required=True)})
    with pytest.raises(ValueError, match="no power wiring"):
        assign({"a": wish(supply="psu", port="O9", required=True)})
    with pytest.raises(ValueError, match="no power wiring"):
        assign({"a": wish(supply="other", required=True)})


def test_preferred_wish_yields_above_300_mm_of_cable_and_is_kept_below():
    pedals = {"a": quiet(), "b": quiet()}
    points = {"a": (10, 0), "b": (20, 0)}
    far = {("psu", "O1"): (0, 0), ("psu", "O2"): (1000, 0)}
    # both on O1 = 20 mm; a alone on O1 and b on O2 = 10 + 980: the 300 mm penalty of a broken wish is the lesser cost, so the wish yields
    out, res = assign({"a": wish(own_output=True)}, pedals, INSTS, points, far, "ab")
    assert out == {"O1": ["a", "b"]} and res["preferences"] == [("a", "own output", False)] and res["length_mm"] == pytest.approx(20.0)
    near = {("psu", "O1"): (0, 0), ("psu", "O2"): (40, 0)}
    # port O2 for a: both there from (40, 0) = 20 + 10 = 30 mm; both on O1 = 20 mm + 300 for the broken wish: the wish is kept (10 mm dearer)
    out, res = assign({"a": wish(supply="psu", port="O2")}, pedals, INSTS, points, near, "ab")
    assert out == {"O2": ["b", "a"]} and res["preferences"][0][2] is True
    # (own output, near ports: a alone on O1 10 + b on O2 20 = 30 mm: also kept)
    out, _ = assign({"a": wish(own_output=True)}, pedals, INSTS, points, near, "ab")
    assert out == {"O1": ["a"], "O2": ["b"]}
    # the same wish, required: kept at any price (a alone on O1 and b on O2 = 990 mm here)
    out, res = assign({"a": wish(own_output=True, required=True)}, pedals, INSTS, points, far, "ab")
    assert out == {"O1": ["a"], "O2": ["b"]} and res["length_mm"] == pytest.approx(10 + 980)


def test_voltage_wish_beats_the_owners_voltage():
    pedals = {"a": quiet(18), "b": quiet(18)}
    points = {"a": (10, 0), "b": (20, 0)}
    res = power.assign(["a", "b"], pedals, INSTS, {}, points, PORTS, run_v={"a": 9, "b": 9}, wishes={"a": wish(voltage_v=18)})
    by_v = {o["voltage_v"]: o["pedals"] for o in res["supplies"][0]["outputs"]}
    assert by_v == {18: ["a"], 9: ["b"]} and res["preferences"] == [("a", "18 V", True)]      # a on its own 18 V output, b keeps the owner's 9 V
    # a preferred voltage no output offers falls back to the owner's; a required one has no wiring
    res = power.assign(["a", "b"], pedals, INSTS, {}, points, PORTS, run_v={"a": 9, "b": 9}, wishes={"a": wish(voltage_v=12)})
    assert {o["voltage_v"] for o in res["supplies"][0]["outputs"]} == {9} and res["preferences"] == [("a", "12 V", False)]
    with pytest.raises(ValueError, match="no power wiring"):
        power.assign(["a", "b"], pedals, INSTS, {}, points, PORTS, wishes={"a": wish(voltage_v=12, required=True)})


def test_start_wiring_that_breaks_a_required_wish_is_dropped():
    start = {"psu": [{"port": "O1", "voltage_v": 9, "pedals": ["a", "b", "c", "d"]}]}
    out, _ = assign({"a": wish(supply="psu", port="O2", required=True)}, start=start)
    assert list(out) == ["O2"]
    out, _ = assign(None, start=start)
    assert list(out) == ["O1"]


# --- findings and the table ---------------------------------------------------------------------------------------------------
def rows(*outs):
    return [{"inst": {"id": "psu1"}, "rows": [{"port": p, "voltage_v": v, "pedals": ps} for p, v, ps in outs]}]


def test_wish_misses_text_and_findings():
    w = wish(own_output=True, supply="psu1", port="F1", voltage_v=18)
    assert power.wish_text(w) == "own output, supply psu1, port psu1.F1, 18 V"
    assert power.wish_misses(w, ["a"], "psu1", "F1", 18) == [] and power.wish_misses(w, ["a", "b"], "psu2", "F2", 9) == [
        "own output", "supply psu1", "port psu1.F1", "18 V"]
    assert power.wish_misses(w, ["a"], "psu1", "F1") == []                                  # no voltage given: not judged
    got = power.wish_findings({"a": wish(own_output=True, required=True), "z": wish(port="F1")}, rows(("F1", 9, ["a", "b"]), ("F2", 18, ["c"])))
    assert got == [{"pedal": "a", "wish": "own output", "wants": "own output", "required": True, "met": False, "got": "psu1.F1 with b"}]
    (g,) = power.wish_findings({"c": wish(voltage_v=9, supply="psu1")}, rows(("F2", 18, ["c"])))
    assert g["got"] == "psu1.F2 at 18 V alone" and g["wants"] == "9 V" and not g["met"]


def test_power_wishes_view():
    p = {"signal_chain": ["a", "b", "c"], "pedals": {"a": {"power": {"own_output": True, "strength": "required"}}, "b": {"power": {"supply": "psu1", "port": "F1", "voltage_v": 18}},
                                                  "c": {"power": {"own_output": False}}, "z": {"power": {"voltage_v": 9}}}}
    assert pref.power_wishes(p, {"a", "b", "c"}) == {
        "a": {"own_output": True, "supply": None, "port": None, "voltage_v": None, "required": True},
        "b": {"own_output": False, "supply": "psu1", "port": "F1", "voltage_v": 18, "required": False}}
    assert set(pref.power_wishes(p)) == {"a", "b", "z"}


def gig_ctx(profiles, **extra):
    pedals, supplies = load_catalog()
    project = {**load_json(GIG_FIXTURE / "project.json"), "pedals": profiles, **extra}
    return build.validate(GIG_FIXTURE, pedals, supplies, project=project, route=False)


def test_build_finds_a_required_power_wish_the_hand_wiring_breaks():
    # fixture wiring: monk alone on psu1.F3 (9 V); reticon alone on psu1.SW_A (18 V)
    ctx = gig_ctx({"monk": {"power": {"own_output": True, "supply": "psu2", "strength": "required"}}, "reticon": {"power": {"voltage_v": 18, "port": "SW_A", "supply": "psu1"}}})
    assert [w for w in ctx["warnings"] if w.startswith("preferences:")] == [
        "preferences: monk: wants supply psu2 (required); the wiring puts it on psu1.F3 alone"]
    by = {r["pedal"]: r for r in ctx["preferences"] if r["kind"] == "power"}
    assert (by["monk"]["met"], by["monk"]["strength"], by["monk"]["detail"]) == (False, "required", "on psu1.F3 alone")
    assert (by["reticon"]["met"], by["reticon"]["strength"], by["reticon"]["wish"]) == (True, "preferred", "supply psu1, port psu1.SW_A, 18 V")
    strict = gig_ctx({"monk": {"power": {"supply": "psu2", "strength": "required"}}}, validation={"no_unknown": True, "strict_preferences": True})
    assert any(e.startswith("preferences: monk: wants supply psu2 (required)") for e in strict["errors"])
    pref_only = gig_ctx({"monk": {"power": {"supply": "psu2"}}})                              # preferred: the table only
    assert not any(w.startswith("preferences:") for w in pref_only["warnings"] + pref_only["errors"])
    assert [r["met"] for r in pref_only["preferences"] if r["kind"] == "power"] == [False]
