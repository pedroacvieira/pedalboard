"""The migration of old keys into `pedals.<id>` (scripts/migrate_preferences.py, preferences.migrate) and the project.json formatter."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import common  # noqa: E402
import migrate_preferences as mp  # noqa: E402
import preferences as pref  # noqa: E402
from common import load_json  # noqa: E402
from conftest import GIG_FIXTURE, gig_copy  # noqa: E402
from test_preferences import RULE, proj  # noqa: E402


def test_dump_project_round_trips_the_live_files_and_keeps_the_style():
    for path in [*(ROOT / "projects").glob("*/project.json"), GIG_FIXTURE / "project.json"]:
        doc = load_json(path)
        text = common.dump_project(doc)
        assert json.loads(text) == doc and text.endswith("}\n")
        assert json.loads(common.dump_project(pref.migrate(doc))) == pref.migrate(doc)
    doc = {"a": {"b": [1, 2, 3], "c": {"d": 1}}, "pedals": {"x": {"order": {"n": {"type": "after", "pedals": ["y"]}}, "pin": True}}, "e": [], "f": {}}
    assert common.dump_project(doc) == (
        '{\n  "a": { "b": [1, 2, 3], "c": { "d": 1 } },\n  "pedals": {\n    "x": {\n      "order": {\n        "n": { "type": "after", "pedals": ["y"] }\n      },\n'
        '      "pin": true\n    }\n  },\n  "e": [],\n  "f": {}\n}\n')


def test_migrate_script_dry_run_writes_nothing_and_a_run_restamps_fresh_proposals_only(tmp_path, monkeypatch):
    pdir = gig_copy(tmp_path, monkeypatch, proposals=True)
    before = (pdir / "project.json").read_text()
    meta = pdir / "proposals" / "meta.json"
    doc = json.loads(meta.read_text())
    doc["inputs_sha1"] = common.proposal_inputs_sha1(pdir)           # fresh
    meta.write_text(json.dumps(doc, indent=1) + "\n")
    lines = []
    assert mp.migrate_dir(pdir, dry_run=True, out=lines.append) is True
    assert (pdir / "project.json").read_text() == before and json.loads(meta.read_text())["inputs_sha1"] == doc["inputs_sha1"]
    assert "proposals: fresh" in lines[0] and "migrated" in lines[1]
    assert mp.migrate_dir(pdir, out=lines.append) is True
    new = load_json(pdir / "project.json")
    assert new["rules"] == [] and new == pref.migrate(json.loads(before))
    assert json.loads(meta.read_text())["inputs_sha1"] == common.proposal_inputs_sha1(pdir) != doc["inputs_sha1"]      # stamped again
    assert not mp.migrate_dir(pdir, out=lines.append) and "nothing to migrate" in lines[-1]                            # idempotent
    # stale proposals stay stale
    (pdir / "project.json").write_text(before)
    doc["inputs_sha1"] = "0" * 40
    meta.write_text(json.dumps(doc, indent=1) + "\n")
    mp.migrate_dir(pdir, out=lines.append)
    assert json.loads(meta.read_text())["inputs_sha1"] == "0" * 40 and "stale already" in lines[-1]


def test_same_wishes_ignores_the_rule_order_only():
    old = proj(rules=[{"id": "b.x", "pedal": "b", **RULE}, {"id": "a.y", "pedal": "a", **RULE}], layout={"pins": ["b", "a"]},
               footswitches={"toppers": ["b.bypass", "a.bypass"]})
    new = pref.migrate(old)
    assert new["pedals"] and mp.same_wishes(old, new)
    new["pedals"]["a"]["order"]["y"]["strength"] = "preferred"
    assert not mp.same_wishes(old, new)


def test_migrated_project_keeps_unmappable_old_keys_and_instance_pins():
    old = proj(rules=[{"id": "free", "pedal": "a", **RULE}, {"id": "a.ok", "pedal": "a", **RULE}],
               layout={"pins": ["psu1", "a"], "rotations": {"default": [0], "psu1": [0], "b": "any"},
                       "access": {"tags": {}, "pedals": {"c": {"want": "back", "weight": 0.1}}}, "max_change": "fix"},
               footswitches={"toppers": ["a.bypass", "junk"], "comfort_mm": 90})
    new = pref.migrate(old)
    assert new["rules"] == [{"id": "free", "pedal": "a", **RULE}]
    assert new["layout"] == {"pins": ["psu1"], "rotations": {"default": [0], "psu1": [0]}, "access": {"tags": {}}, "max_change": "fix"}
    assert new["footswitches"] == {"toppers": ["junk"], "comfort_mm": 90}
    assert new["pedals"]["a"] == {"pin": True, "order": {"ok": RULE}, "toppers": ["bypass"]} and new["pedals"]["c"]["position"] == {"depth": "back", "weight": 0.1}
    assert new["pedals"]["b"] == {"rotations": "any"}
    assert list(new)[list(new).index("rules") + 1] == "pedals"
