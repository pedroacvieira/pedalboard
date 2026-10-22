"""Power polarity checks in build.validate, on a copy of the bass project with edited catalog data."""
import copy
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import build  # noqa: E402
from common import load_catalog  # noqa: E402


def run(tmp_path, positive=(), outputs=None):
    """Validate the bass project with `positive` pedals made center-positive and optional output wiring."""
    pdir = tmp_path / "bass"
    pdir.mkdir()
    project = json.loads((ROOT / "projects" / "bass" / "project.json").read_text())
    project.pop("cables", None)      # no catalog/cables.json lookups needed here
    if outputs is not None:
        project["power"]["supplies"][0]["outputs"] = outputs
    (pdir / "project.json").write_text(json.dumps(project))
    pedals, supplies = load_catalog()
    pedals = copy.deepcopy(pedals)
    for pid in positive:
        pedals[pid]["power_consumption"]["polarity"] = "center_positive"
    ctx = build.validate(pdir, pedals, supplies, {})
    return ctx


def test_every_catalog_pedal_and_supply_has_a_polarity():
    pedals, supplies = load_catalog()
    assert {p["power_consumption"]["polarity"] for p in pedals.values()} == {"center_negative"}
    assert {s["polarity"] for s in supplies.values()} == {"center_negative"}


def test_matching_polarity_is_clean(tmp_path):
    ctx = run(tmp_path)
    assert not [m for m in ctx["errors"] + ctx["warnings"] if "polarity" in m or "center-" in m]


def test_center_positive_pedal_alone_needs_a_reversing_cable(tmp_path):
    ctx = run(tmp_path, positive=["ehx_bass_big_muff_2"])
    assert any("ehx_bass_big_muff_2 is center-positive" in w and "polarity-reversing cable" in w for w in ctx["warnings"])
    assert not [e for e in ctx["errors"] if "center-" in e]


def test_mixed_polarity_on_one_output_is_an_error(tmp_path):
    outputs = [{"port": "OUT1", "voltage_v": 9, "pedals": ["polytune_2_mini"]},
               {"port": "OUT2", "voltage_v": 9, "pedals": ["ehx_bass_big_muff_2", "tech21_vt_bass_di"]},
               {"port": "OUT4", "voltage_v": 9, "pedals": ["mxr_bass_synth"]},
               {"port": "OUT5", "voltage_v": 9, "pedals": ["darkglass_hyper_luminal"]}]
    ctx = run(tmp_path, positive=["ehx_bass_big_muff_2"], outputs=outputs)
    assert any("psu1_OUT2: center-negative and center-positive pedals share one output" in e for e in ctx["errors"])


def test_unknown_polarity_value_is_an_error(tmp_path):
    pedals, supplies = load_catalog()
    pedals = copy.deepcopy(pedals)
    pedals["tech21_vt_bass_di"]["power_consumption"]["polarity"] = "center_plus"
    pdir = tmp_path / "bass"
    shutil.copytree(ROOT / "projects" / "bass", pdir)
    ctx = build.validate(pdir, pedals, supplies, {})
    assert any("tech21_vt_bass_di: unknown polarity 'center_plus'" in e for e in ctx["errors"])


def test_unknown_supply_polarity_is_an_error_without_false_reversing_warnings(tmp_path):
    pedals, supplies = load_catalog()
    supplies = copy.deepcopy(supplies)
    supplies["harley_benton_iso5_pro"]["polarity"] = "center-negative"     # hyphen: not a known value
    pdir = tmp_path / "bass"
    shutil.copytree(ROOT / "projects" / "bass", pdir)
    ctx = build.validate(pdir, pedals, supplies, {})
    assert any("unknown polarity 'center-negative'" in e for e in ctx["errors"])
    assert not any("polarity-reversing" in w for w in ctx["warnings"])
