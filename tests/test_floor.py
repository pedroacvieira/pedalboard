"""Floor devices (catalog `floor_device`, project `floor`): pedals that sit on the floor and go with any board; the jacks they drive count as
used extra jacks."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import jacks  # noqa: E402

CAT = {"exp": {"floor_device": True}, "a": {}, "b": {}}
JD = {"a": [{"id": "in", "function": "input"}, {"id": "exp", "function": "other"}], "b": [{"id": "in", "function": "input"}]}


def test_controls_become_used_extra_jacks_once_and_the_project_is_not_changed():
    proj = {"jacks": {"extra_used": {"a": ["exp"]}}, "floor": [{"device": "exp", "controls": ["a.exp", "b.tap"]}]}
    out = jacks.with_floor(proj)
    assert out["jacks"]["extra_used"] == {"a": ["exp"], "b": ["tap"]}
    assert proj["jacks"]["extra_used"] == {"a": ["exp"]}               # a copy
    assert jacks.with_floor(out) == out                                # idempotent
    plain = {"jacks": {}}
    assert jacks.with_floor(plain) is plain                            # no floor devices: the project itself


def test_floor_findings():
    ok = {"floor": [{"device": "exp", "controls": ["a.exp"], "note": "x"}]}
    assert jacks.floor_findings(ok, CAT, JD, ["a", "b"]) == []
    bad = {"floor": [{"device": "nope"}, {"device": "a"}, {"device": "exp", "controls": ["c.exp", "a.zzz"]}, {"device": "exp", "controls": "a.exp"}]}
    errs = jacks.floor_findings(bad, CAT, JD, ["a", "b"])
    assert "floor[0]: device 'nope' is not in catalog/pedals.json" in errs
    assert any(e.startswith("floor[1]: a is no floor device") for e in errs)
    assert "floor[2].controls: c.exp: c is not in the signal chain" in errs
    assert "floor[2].controls: a.zzz: a has no jack 'zzz'" in errs
    assert any(e.startswith("floor[3].controls must be a list") for e in errs)
    assert any("exp is a floor device" in e for e in jacks.floor_findings({}, CAT, JD, ["exp", "a"]))
    assert jacks.floor_findings({"floor": "x"}, CAT, JD, []) and jacks.with_floor({"floor": "x"}) == {"floor": "x"}


def test_malformed_devices_and_controls_never_crash():
    bad = {"floor": [{"device": ["x"]}, {"device": {"a": 1}}, {"device": "exp", "controls": None}, {"device": "exp", "controls": 5}]}
    errs = jacks.floor_findings(bad, CAT, JD, ["a"])
    assert any(e.startswith("floor[0]: device") for e in errs) and any(e.startswith("floor[1]: device") for e in errs)
    assert not any(e.startswith("floor[2]") for e in errs)              # null = drives nothing
    assert any(e.startswith("floor[3].controls must be a list") for e in errs)
    assert jacks.with_floor(bad) is bad
