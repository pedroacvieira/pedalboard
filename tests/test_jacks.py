"""Checks for the jack data layer (scripts/jacks.py)."""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import jacks  # noqa: E402

PEDALS = {"p1": {}, "p2": {}}
SUPPLIES = {"s1": {"outputs": [{"port": "F1"}, {"port": "F2"}]}}


def jack(**kw):
    base = {"id": "in", "label": "Input", "function": "input", "x": 0.0, "y": 0.5, "facing": "left"}
    base.update(kw)
    return base


@pytest.mark.parametrize("label,expected", [("Input", "input"), ("Tap tempo", "tap_tempo"), ("  9V DC!! ", "9v_dc"), ("", "jack")])
def test_slugify(label, expected):
    assert jacks.slugify(label) == expected


def test_unique_id():
    assert jacks.unique_id([], "Out") == "out"
    assert jacks.unique_id(["out"], "Out") == "out_2"
    assert jacks.unique_id(["out", "out_2"], "Out") == "out_3"


@pytest.mark.parametrize("fx,fy,expected", [(0.0, 0.5, "left"), (1.0, 0.4, "right"), (0.5, 0.0, "top"), (0.5, 1.0, "down"), (0.1, 0.8, "left"), (0.9, 0.95, "down")])
def test_guess_facing(fx, fy, expected):
    assert jacks.guess_facing(fx, fy) == expected


def test_default_jack_rule():
    a, b = jack(id="out_l", function="output"), jack(id="out_r", function="output")
    assert jacks.default_jack([jack()], "input")["id"] == "in"
    assert jacks.default_jack([a, b], "output") is None and jacks.ambiguous([a, b], "output")
    b["default"] = True
    assert jacks.default_jack([a, b], "output")["id"] == "out_r" and not jacks.ambiguous([a, b], "output")
    assert jacks.default_jack([a, b], "power") is None and not jacks.ambiguous([a, b], "power")


def test_validate_accepts_good_data():
    data = {"jacks": {"p1": [jack(), jack(id="out", function="output", x=1.0, facing="right")],
                      "s1": [jack(id="F1", function="power_out", facing="down")]}}
    assert jacks.validate_jacks_file(data, PEDALS, SUPPLIES) == {}


@pytest.mark.parametrize("bad,fragment", [
    (jack(function="wah"), "function"), (jack(facing="up"), "facing"), (jack(x=1.2), "0..1"),
    (jack(function="power_out"), "only for power supplies"), ({"id": "q"}, "missing"),
])
def test_validate_flags_bad_jacks(bad, fragment):
    problems = jacks.validate_jacks_file({"jacks": {"p1": [bad]}}, PEDALS, SUPPLIES)
    assert any(fragment in m for m in problems["p1"])


def test_validate_flags_duplicates_unknown_ids_and_ports():
    data = {"jacks": {"p1": [jack(), jack()], "nope": [jack()], "s1": [jack(id="F9", function="power_out")]}}
    problems = jacks.validate_jacks_file(data, PEDALS, SUPPLIES)
    assert any("duplicate" in m for m in problems["p1"])
    assert any("not a pedal or supply" in m for m in problems["nope"])
    assert any("not a port" in m for m in problems["s1"])
    two_defaults = {"jacks": {"p1": [jack(default=True), jack(id="in2", default=True)]}}
    assert any("more than one default" in m for m in jacks.validate_jacks_file(two_defaults, PEDALS, SUPPLIES)["p1"])


def test_save_merges_rounds_and_removes(tmp_path):
    path = tmp_path / "jacks.json"
    jacks.save_jacks("p1", [jack(x=0.123456789)], path)
    jacks.save_jacks("p2", [jack(id="out", function="output")], path)
    data = json.loads(path.read_text())
    assert set(data["jacks"]) == {"p1", "p2"} and data["jacks"]["p1"][0]["x"] == 0.1235
    jacks.save_jacks("p1", [jack(id="power", function="power", y=0.0, facing="top")], path)   # replace only p1
    data = json.loads(path.read_text())
    assert [j["id"] for j in data["jacks"]["p1"]] == ["power"] and "p2" in data["jacks"]
    jacks.save_jacks("p2", [], path)                                                          # removes the key
    assert "p2" not in json.loads(path.read_text())["jacks"]
    assert "p1" in jacks.read_file(path)["jacks"] and not list(tmp_path.glob("*.tmp"))


def test_dump_is_one_jack_per_line_and_stable(tmp_path):
    path = tmp_path / "jacks.json"
    jacks.save_jacks("p1", [jack(), jack(id="out", function="output", x=1.0, facing="right")], path)
    text = path.read_text()
    assert text.count('"label"') == 2 and len([l for l in text.splitlines() if l.strip().startswith('{"id"')]) == 2
    jacks.save_jacks("p1", jacks.read_file(path)["jacks"]["p1"], path)
    assert path.read_text() == text


def test_real_file_is_valid():
    data = jacks.read_file()
    from common import load_catalog
    pedals, supplies = load_catalog()
    assert jacks.validate_jacks_file(data, pedals, supplies) == {}
