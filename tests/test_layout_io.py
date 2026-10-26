"""Layout injection and canvas editing (Phase 0 of feat/pedal-position): build.validate with injected items,
design.move and design.write_canvas. Hand-computed, all lengths in mm (45 px/in -> 1 px = 25.4/45 = 0.5644 mm)."""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import build  # noqa: E402
import design  # noqa: E402
import jacks  # noqa: E402
from common import load_catalog, load_json  # noqa: E402

GIG = ROOT / "projects" / "guitar-gig"

CANVAS = ('<div id="item-1" class="item pedalboard undefined" title="Board" data-width="10" data-height="5" data-scale="45" '
          'style="touch-action: none; left: 10px; top: 20px;"><div class="artwork" style="width: 450px;"></div></div>'
          '<input id="multiplier" type="hidden" value="45">'
          '<div id="item-2" class="item pedal undefined" title="P A" data-width="2" data-height="4" data-scale="45" '
          'style="touch-action: none; left: 45px; top: 90px;">\t<div class="artwork" style="left: 3px; top: 4px;"></div>'
          '\t<div class="actions">\t\t<a class="rotate"></a>\t</div></div>'
          '<div id="item-3" class="item pedal undefined rotate-90" title="P B" data-width="1" data-height="2" data-scale="45" '
          'style="touch-action: none; left: 200px; top: 50px;"><div class="artwork"></div></div>')


def strip(ctx):
    """The comparable part of a build context (drops the folder and the router's grid objects)."""
    out = {k: v for k, v in ctx.items() if k not in ("dir", "routing")}
    out["routing"] = {k: v for k, v in ctx["routing"].items() if k not in ("grid", "under")}
    out.pop("layout_source")
    return json.loads(json.dumps(out, default=repr, sort_keys=True))


def test_validate_with_injected_items_equals_the_file():
    pedals, supplies = load_catalog()
    from_file = build.validate(GIG, pedals, supplies)
    items = design.parse_design(GIG / "playground_design.json")
    injected = build.validate(GIG, pedals, supplies, items=items)
    assert from_file["layout_source"] == "file" and injected["layout_source"] == "injected"
    assert strip(from_file) == strip(injected)


def test_injected_items_are_checked_instead_of_the_file(tmp_path):
    """A project folder without a design file: injected items still give a layout and cables."""
    pedals, supplies = load_catalog()
    (tmp_path / "project.json").write_text((GIG / "project.json").read_text())
    none = build.validate(tmp_path, pedals, supplies)
    assert none["layout"] is None and none["cables"] is None
    items = design.parse_design(GIG / "playground_design.json")
    got = build.validate(tmp_path, pedals, supplies, items=items)
    assert got["layout"] is not None and len(got["layout"]["placed"]) == len(got["chain"])


def test_moving_a_pedal_changes_the_findings():
    """Moving the Belle Epoch 40 mm away from the Monk removes the Monk's blocked plugs."""
    pedals, supplies = load_catalog()
    items = design.parse_design(GIG / "playground_design.json")
    base = build.validate(GIG, pedals, supplies, items=items)
    before = {v["jack"] for v in base["violations"] if v["obstacle"] == pedals["belle_epoch"]["playground_title"]}
    belle = base["layout"]["placed"]["belle_epoch"]
    cx, cy = design.centre(belle)
    moved = [design.move(i, cx, cy + 300) if i["id"] == belle["id"] else i for i in items]   # far off the board
    after = build.validate(GIG, pedals, supplies, items=moved)
    assert before and not any(v["obstacle"] == pedals["belle_epoch"]["playground_title"] for v in after["violations"])


def test_layout_from_items_maps_pedals_board_and_obstacles():
    items = design.parse_canvas(CANVAS)
    cat = {"a": {"playground_title": "P A"}, "b": {"playground_title": "P B"}, "c": {"playground_title": "P C"}}
    warnings, clear = [], []
    lay = jacks.layout_from_items(items, ["a", "b", "c"], [], cat, {}, {}, warnings, clear)
    assert lay["board"]["id"] == "item-1" and set(lay["placed"]) == {"a", "b"}
    assert [o["id"] for o in lay["obstacles"]] == ["item-2", "item-3"]
    assert clear == ["layout: c is in the signal chain but not in playground_design.json"] and warnings == []


def test_real_projects_keep_every_supply_under_the_board():
    """Placement phase 3: no real project sets a placement, so the default (jacks.supplies_layer, "under") applies: no
    supply is an obstacle, every power cable is under the board, and an explicit "under" changes nothing."""
    pedals, supplies = load_catalog()
    for name in ("guitar-gig", "guitar-practice", "bass"):
        pdir = ROOT / "projects" / name
        base = build.validate(pdir, pedals, supplies)
        titles = {t for t in (supplies[s["sup"]["id"]].get("playground_title") for s in base["supplies"]) if t}
        assert all("placement" not in s["inst"] for s in base["supplies"])
        if base["layout"]:
            assert set(base["layout"]["inst_placement"].values()) <= {"under"}
            assert not [o for o in base["layout"]["obstacles"] if o["title"] in titles]
        assert base["cable_list"] and all(c["under_board"] for c in base["cable_list"] if c["kind"] == "power")
        assert all(c["status"] == "not routed (under the board)" for c in base["cable_list"] if c["kind"] == "power")
        proj = load_json(pdir / "project.json")
        for inst in proj["power"]["supplies"]:
            inst["placement"] = "under"
        explicit = build.validate(pdir, pedals, supplies, project=proj)
        a, b = strip(base), strip(explicit)
        for k in ("project", "supplies"):
            a.pop(k), b.pop(k)
        assert a == b


# --- design.move ---------------------------------------------------------------------------------
def test_move_sets_the_unrotated_box_around_the_new_centre():
    (_, a, _) = design.parse_canvas(CANVAS)          # 2 x 4 in = 50.8 x 101.6 mm, left 45 px = 25.4 mm
    m = design.move(a, 100.0, 200.0, snap=False)
    assert m["left_mm"] == pytest.approx(100 - 25.4) and m["top_mm"] == pytest.approx(200 - 50.8)
    assert m["left_px"] == pytest.approx(74.6 * 45 / 25.4) and design.centre(m) == pytest.approx((100.0, 200.0))
    r = design.move(a, 100.0, 200.0, rot=90, snap=False)   # rotation is about the centre: left/top unchanged
    assert r["rot"] == 90 and r["left_mm"] == pytest.approx(m["left_mm"]) and r["top_mm"] == pytest.approx(m["top_mm"])
    assert design.footprint(r) == pytest.approx((100 - 50.8, 200 - 25.4, 100 + 50.8, 200 + 25.4))
    assert a["left_px"] == 45 and a["rot"] == 0       # the original is not modified


def test_move_snaps_to_whole_px():
    (_, a, _) = design.parse_canvas(CANVAS)
    m = design.move(a, 100.0, 200.0)                  # left 74.6 mm = 132.17 px -> 132 px; top 149.2 mm = 264.33 -> 264
    assert (m["left_px"], m["top_px"]) == (132.0, 264.0)
    assert m["left_mm"] == pytest.approx(132 * 25.4 / 45) and m["top_mm"] == pytest.approx(264 * 25.4 / 45)
    assert abs(design.centre(m)[0] - 100.0) <= 0.29 and abs(design.centre(m)[1] - 200.0) <= 0.29   # half a px
    with pytest.raises(ValueError):
        design.move(a, 0, 0, rot=45)


# --- design.write_canvas -------------------------------------------------------------------------
def test_write_canvas_round_trip_is_identical():
    assert design.write_canvas(CANVAS, design.parse_canvas(CANVAS)) == CANVAS
    canvas = load_json(GIG / "playground_design.json")["canvas"]
    assert design.write_canvas(canvas, design.parse_canvas(canvas)) == canvas


def test_moving_one_item_changes_only_its_start_tag():
    items = design.parse_canvas(CANVAS)
    a = design.move(items[1], 100.0, 200.0, rot=270)
    out = design.write_canvas(CANVAS, [a])
    old_tag = CANVAS[CANVAS.index('<div id="item-2"'):].split(">", 1)[0]
    new_tag = out[out.index('<div id="item-2"'):].split(">", 1)[0]
    assert out.replace(new_tag, old_tag) == CANVAS
    assert 'class="item pedal undefined rotate-270"' in new_tag and "left: 132px; top: 264px;" in new_tag
    assert 'style="left: 3px; top: 4px;"' in out          # the artwork's own left/top is untouched
    again = design.parse_canvas(out)
    assert again[1]["rot"] == 270 and again[1]["left_px"] == 132 and again[2] == items[2] and again[0] == items[0]


def test_unrotating_removes_the_class_and_fractional_px_are_kept():
    items = design.parse_canvas(CANVAS)
    b = {**design.move(items[2], 50.0, 50.0, rot=0, snap=False)}
    out = design.write_canvas(CANVAS, [b])
    tag = out[out.index('<div id="item-3"'):].split(">", 1)[0]
    assert "rotate-" not in tag and 'class="item pedal undefined"' in tag
    assert f"left: {design._px(b['left_px'])}px" in tag and "." in design._px(b["left_px"])
    assert design.parse_canvas(out)[2]["left_px"] == pytest.approx(b["left_px"], abs=1e-3)


def test_write_canvas_rejects_unknown_ids():
    with pytest.raises(KeyError):
        design.write_canvas(CANVAS, [{**design.parse_canvas(CANVAS)[1], "id": "item-99"}])


def test_write_canvas_ignores_longer_names_containing_the_keys():
    """data-id= / data-class= and margin-left: / padding-top: must not be taken for id, class, left, top."""
    canvas = CANVAS.replace('<div id="item-2" class="item pedal undefined"',
                            '<div data-id="item-3" data-class="x" id="item-2" class="item pedal undefined"')
    canvas = canvas.replace("style=\"touch-action: none; left: 45px; top: 90px;\">\t",
                            "style=\"margin-left: 0px; padding-top: 1px; left: 45px; top: 90px;\">\t")
    items = design.parse_canvas(canvas)
    a = design.move(items[1], 100.0, 200.0)
    out = design.write_canvas(canvas, [a])
    tag = out[out.index('<div data-id="item-3"'):].split(">", 1)[0]
    assert "margin-left: 0px; padding-top: 1px; left: 132px; top: 264px;" in tag and 'data-class="x"' in tag
    assert out.count("left: 200px; top: 50px;") == 1                        # item-3 itself untouched
