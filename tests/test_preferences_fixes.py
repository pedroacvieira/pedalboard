"""Review fixes of feat/pedal-preferences: lowering round trip, a preferred voltage wish, migration refusals."""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import build  # noqa: E402
import migrate_preferences as mp  # noqa: E402
import power  # noqa: E402
import preferences as pref  # noqa: E402
from common import load_catalog, load_json  # noqa: E402
from conftest import GIG_FIXTURE, gig_copy  # noqa: E402
from test_preferences_power import wish  # noqa: E402


def test_lowered_profiles_validate_cleanly_a_second_time():
    """propose_layout lowers the project and build.validate lowers and validates it again: depth `any` (lowered to want "none") must read back."""
    pedals, supplies = load_catalog()
    base = load_json(GIG_FIXTURE / "project.json")
    profiles = {"polytune_3": {"position": {"depth": "any", "weight": 0.2}, "pin": True, "rotations": [0, 90], "toppers": []},
                "monk": {"position": {"depth": "front", "weight": 0.5}}}
    raw = {**base, "pedals": profiles}
    low = pref.lower(raw)
    assert low["layout"]["access"]["pedals"]["polytune_3"] == {"want": "none", "weight": 0.2}
    once = build.validate(GIG_FIXTURE, pedals, supplies, project=raw, route=False)
    twice = build.validate(GIG_FIXTURE, pedals, supplies, project=low, route=False)
    assert not any("disagree" in e for e in once["errors"] + twice["errors"])
    assert sorted(once["errors"]) == sorted(twice["errors"]) and pref.lower(low) == low
    assert pref.profiles(low)["polytune_3"]["position"]["depth"] == "any"
    assert pref.position_wishes(low, {"polytune_3"}) == {}                      # depth any is no wish


def test_a_preferred_voltage_wish_that_cannot_be_wired_only_costs_its_penalty():
    sup = {"id": "s", "polarity": "center_negative",
           "outputs": [{"port": "O1", "options": [{"voltage_v": 9, "max_ma": 1000}, {"voltage_v": 18, "max_ma": 20}]}]}
    insts = [{"id": "psu", "supply": "s", "sup": sup, "under": False}]
    ped = {"power_consumption": {"current_ma": 50, "min_voltage_v": 9, "max_voltage_v": 18, "polarity": "center_negative"},
           "digital": False, "clocked_noise": False, "tags": []}
    args = (["a"], {"a": ped}, insts, {}, {"a": (10, 0)}, {("psu", "O1"): (0, 0)})
    res = power.assign(*args, wishes={"a": wish(voltage_v=18)})                    # the only 18 V output gives 20 mA: 50 mA does not fit
    assert res["supplies"][0]["outputs"][0]["voltage_v"] == 9 and res["preferences"] == [("a", "18 V", False)]
    with pytest.raises(ValueError, match="no power wiring"):                       # required: no fallback
        power.assign(*args, wishes={"a": wish(voltage_v=18, required=True)})
    ped["power_consumption"]["current_ma"] = 10                                    # now it fits: the wish is kept
    res = power.assign(*args, wishes={"a": wish(voltage_v=18)})
    assert res["supplies"][0]["outputs"][0]["voltage_v"] == 18 and res["preferences"] == [("a", "18 V", True)]


def test_an_already_migrated_file_is_left_alone_whatever_its_formatting(tmp_path, monkeypatch):
    pdir = gig_copy(tmp_path, monkeypatch)
    lines = []
    assert mp.migrate_dir(pdir, out=lines.append) is True
    migrated = load_json(pdir / "project.json")
    (pdir / "project.json").write_text(json.dumps(migrated, indent=1))            # another formatting of the same data
    before = (pdir / "project.json").read_text()
    assert mp.migrate_dir(pdir, out=lines.append) is False and lines[-1] == "guitar-gig: nothing to migrate"
    assert (pdir / "project.json").read_text() == before


def test_migration_refuses_old_keys_and_profiles_that_disagree(tmp_path, monkeypatch):
    pdir = gig_copy(tmp_path, monkeypatch)
    project = load_json(pdir / "project.json")
    project["layout"] = {"rotations": {"default": [0, 90, 270], "monk": [0]}}
    project["pedals"] = {"monk": {"rotations": [90]}}
    (pdir / "project.json").write_text(json.dumps(project))
    before = (pdir / "project.json").read_text()
    lines = []
    assert mp.migrate_dir(pdir, out=lines.append) is False
    assert "nothing migrated" in lines[0] and "pedals.monk.rotations and layout.rotations.monk disagree" in lines[0]
    assert (pdir / "project.json").read_text() == before


def test_migration_refuses_malformed_profiles_and_never_drops_them(tmp_path, monkeypatch):
    pdir = gig_copy(tmp_path, monkeypatch)
    project = load_json(pdir / "project.json")
    project["pedals"] = {"no_such_pedal": {}, "monk": "x"}
    (pdir / "project.json").write_text(json.dumps(project))
    before = (pdir / "project.json").read_text()
    lines = []
    assert mp.migrate_dir(pdir, out=lines.append) is False
    assert "pedals: 'no_such_pedal' is not in catalog/pedals.json" in lines[0] and "pedals.monk must be an object, got 'x'" in lines[0]
    assert (pdir / "project.json").read_text() == before
    kept = pref.migrate(project)["pedals"]                                          # (and `migrate` itself keeps what it cannot read)
    assert kept["monk"] == "x" and kept["no_such_pedal"] == {}
