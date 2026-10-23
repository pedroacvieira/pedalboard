"""Pure helpers of the pedal editor (scripts/pedal_editor.py); the Tkinter window itself is not run here."""
import sys
from pathlib import Path

import pytest
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import footswitches  # noqa: E402
import jacks  # noqa: E402
import pedal_editor as pe  # noqa: E402
from common import JACKS_FILE, load_catalog  # noqa: E402


def test_command_names_the_editor():
    assert jacks.COMMAND == footswitches.COMMAND == pe.COMMAND == "uv run scripts/pedal_editor.py"
    assert not (ROOT / "scripts" / "jack_setter.py").exists()


def test_jacks_file_doc_is_current_and_the_file_is_unchanged_by_a_rewrite():
    data = jacks.read_file()
    assert data["_doc"] == jacks.DOC and "pedal_editor.py" in data["_doc"]
    assert jacks.dumps(data) == JACKS_FILE.read_text()     # saving another id would not move any stored jack


# --- new items ----------------------------------------------------------------------------------
def test_new_jack_fills_input_output_power_then_other():
    got = []
    for fx, fy in ((0.0, 0.5), (1.0, 0.5), (0.5, 0.0), (0.5, 1.0)):
        got.append(pe.new_jack(got, fx, fy, "pedal"))
    assert [(j["id"], j["function"], j["facing"]) for j in got] == [
        ("in", "input", "left"), ("out", "output", "right"), ("power", "power", "top"), ("jack_4", "other", "down")]


def test_new_jack_on_a_supply_takes_the_next_free_port():
    first = pe.new_jack([], 0.2, 1.0, "supply", ["F1", "F2"])
    assert (first["id"], first["function"]) == ("F1", "power_out")
    assert pe.new_jack([first], 0.4, 1.0, "supply", ["F1", "F2"])["id"] == "F2"


def test_new_footswitch_first_is_bypass_then_other_switches():
    a = pe.new_footswitch([], 0.5, 0.8)
    b = pe.new_footswitch([a], 0.2, 0.8)
    c = pe.new_footswitch([a, b], 0.8, 0.8)
    assert (a["id"], a["label"], a["type"]) == ("bypass", "Bypass", "bypass")
    assert (b["id"], b["label"], b["type"]) == ("switch_2", "Switch 2", "function") and c["id"] == "switch_3"
    assert c["type"] == "function"
    assert footswitches.validate_file({"footswitches": {"beano": [a, b, c]}}, {"beano": {}}, {}) == {}


# --- save checks --------------------------------------------------------------------------------
def test_jack_problems():
    j = {"id": "in", "function": "input"}
    assert pe.jack_problems([j, {"id": "out", "function": "output"}]) == []
    assert pe.jack_problems([j, dict(j)]) == ["two jacks share the id 'in'"]
    assert pe.jack_problems([{**j, "default": True}, {"id": "in2", "function": "input", "default": True}]) == \
        ["more than one default input jack"]


def test_footswitch_problems_and_payload():
    a = {"id": "bypass", "label": "Bypass", "bypass": True}
    assert pe.footswitch_problems([a]) == []
    assert pe.footswitch_problems([a, dict(a)]) == ["two footswitches share the id 'bypass'"]
    assert pe.footswitch_problems([{**a, "label": " "}]) == ["footswitch 'bypass' has no label"]
    assert pe.footswitch_problems([a], no_footswitch=True)
    assert pe.footswitch_payload([a], False) == [a]
    assert pe.footswitch_payload([], True) == []         # verified: no footswitch
    assert pe.footswitch_payload([], False) is None      # unknown: the id is removed


# --- on-body checks with Pillow -----------------------------------------------------------------
def pedal_image():
    """100 x 50 px RGBA: transparent, with an opaque block over the left half (x < 50)."""
    img = Image.new("RGBA", (100, 50), (0, 0, 0, 0))
    img.paste((10, 10, 10, 255), (0, 0, 50, 50))
    return img


def test_alpha_mask_keeps_the_pedal_aspect_ratio():
    mask = pe.alpha_mask(pedal_image(), w_mm=100.0, h_mm=50.0, width=40)
    assert mask.mode == "L" and mask.size == (40, 20)


def test_opaque_fraction_hand_computed():
    """1 px = 1 mm; the pixel range of a rectangle includes its end pixel (int(x1) + 1, conservative), as before."""
    mask = pe.alpha_mask(pedal_image(), 100.0, 50.0, width=100)
    assert pe.opaque_fraction(mask, (10, 10, 30, 20), 100.0, 50.0) == 1.0                    # 21 x 11 px, capped at 1
    assert pe.opaque_fraction(mask, (60, 10, 80, 20), 100.0, 50.0) == 0.0
    assert pe.opaque_fraction(mask, (40, 10, 60, 20), 100.0, 50.0) == pytest.approx(110 / 200)   # columns 40-49 opaque
    assert pe.opaque_fraction(mask, (-20, -20, -10, -10), 100.0, 50.0) == 0.0               # beyond the image: free
    assert pe.opaque_fraction(mask, (-10, 10, 10, 20), 100.0, 50.0) == pytest.approx(121 / 200)  # columns 0-10, rows 10-20


def test_on_body():
    mask = pe.alpha_mask(pedal_image(), 100.0, 50.0, width=100)
    assert pe.on_body(mask, 0.2, 0.5) and not pe.on_body(mask, 0.8, 0.5)
    assert not pe.on_body(mask, 1.2, 0.5)


# --- listings -----------------------------------------------------------------------------------
def test_list_rows_show_unknown_and_verified_none():
    rows = pe.list_rows({"a": {}, "b": {}, "c": {}}, {"s": {}}, {"a": [{}] * 3}, {"a": [{}], "b": []})
    assert [r.split() for r in rows] == [
        ["a", "pedal", "3", "jack(s)", "1", "footswitch(es)"], ["b", "pedal", "0", "jack(s)", "0", "footswitch(es)"],
        ["c", "pedal", "0", "jack(s)", "?", "footswitch(es)"], ["s", "supply", "0", "jack(s)", "-", "footswitch(es)"]]


def test_list_missing_footswitches_for_the_gig_board():
    pedals, supplies = load_catalog()
    import json
    chain = json.loads((ROOT / "projects" / "guitar-gig" / "project.json").read_text())["signal_chain"]
    lines = pe.missing_lines(["guitar-gig"], pedals, supplies, "footswitches", fs_data={})
    assert lines == [f"uv run scripts/pedal_editor.py {c} --footswitches    # guitar-gig" for c in chain]
    some = pe.missing_lines(["guitar-gig"], pedals, supplies, "footswitches", fs_data={c: [] for c in chain[1:]})
    assert some == [f"uv run scripts/pedal_editor.py {chain[0]} --footswitches    # guitar-gig"]
    both = pe.missing_lines(["guitar-gig"], pedals, supplies, None, fs_data={c: [] for c in chain})
    assert both[0] == "# jacks" and "# footswitches" in both
    assert "Every pedal used by these projects has footswitch data." in both


def test_cli_rejects_only_without_list_missing_and_footswitches_on_a_supply():
    with pytest.raises(SystemExit):
        pe.main(["--only", "jacks"])
    _, supplies = load_catalog()
    with pytest.raises(SystemExit, match="supplies have no footswitches"):
        pe.main([next(iter(supplies)), "--footswitches"])


def test_switch_kind():
    assert [pe.switch_kind({"type": t}) for t in ("bypass", "tap", "boost", "function")] == ["bypass", "tap", "boost", "function"]
    assert pe.switch_kind({}) == "?" and pe.switch_kind({"type": "preset"}) == "?"
    assert set(pe.FOOTSWITCH_COLOURS) == set(footswitches.TYPES)


def test_switch_drawing_is_a_10_mm_cap_in_an_18_mm_ring():
    assert pe.switch_diameters_mm({"type": "bypass"}) == (10.0, 18.0)
    assert pe.switch_diameters_mm({"type": "tap", "diameter_mm": None}) == (10.0, 18.0)
    assert pe.switch_diameters_mm({"type": "tap", "diameter_mm": 12}) == (10.0, 18.0)


def test_list_missing_does_not_run_the_router(monkeypatch):
    import routing
    monkeypatch.setattr(routing, "route_project", lambda *a, **k: (_ for _ in ()).throw(AssertionError("routed")))
    pedals, supplies = load_catalog()
    assert pe.missing_lines(["guitar-gig"], pedals, supplies, only="footswitches")
