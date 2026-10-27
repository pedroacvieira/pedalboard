"""Pure helpers of the board editor (scripts/board_editor.py); the Tkinter window itself is only constructed when a
display exists."""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import board_editor as be  # noqa: E402
import boards  # noqa: E402
import design  # noqa: E402
from common import IN_MM  # noqa: E402

W, H = 200.0, 100.0   # board image of 200 x 100 mm: 1 mm = 0.005 x, 0.01 y


def box(type_="hole", x0=0.1, y0=0.2, x1=0.3, y1=0.6):
    return be.make_box(type_, x0, y0, x1, y1)


def test_importing_does_not_import_tkinter():
    code = "import sys; sys.path.insert(0, %r); import board_editor; print('tkinter' in sys.modules)" % str(ROOT / "scripts")
    out = subprocess.run([sys.executable, "-I", "-c", code], capture_output=True, text=True, check=True)
    assert out.stdout.strip() == "False"


# --- which board ---------------------------------------------------------------------------------
CANVAS = ('<div class="item pedalboard" id="b1" data-scale="45" data-width="10" data-height="4" '
          'style="left: 90px; top: 45px;"><div class="artwork" style="background-image: url(img/my-board.png)"></div></div>')


def test_board_image_for_a_project_with_a_layout_item(tmp_path):
    (tmp_path / "playground_design.json").write_text(json.dumps({"canvas": CANVAS}))
    # the database says something else: the layout item wins
    db = {"A B": {"Image": "other.png", "Width": 1, "Height": 1}}
    name, w, h = be.board_image_for(tmp_path, {"board": {"brand": "A", "model": "B"}}, db)
    assert name == "my-board.png"
    assert (w, h) == pytest.approx((10 * IN_MM, 4 * IN_MM))


def test_board_image_for_resolved_through_the_database(tmp_path):
    db = {"Rock Duo": {"Image": "rock-duo.png", "Width": 18.0, "Height": 5.0}}
    name, w, h = be.board_image_for(tmp_path, {"board": {"brand": "Rock", "model": "Duo"}}, db)
    assert name == "rock-duo.png"
    assert (w, h) == pytest.approx((457.2, 127.0))


def test_board_image_for_a_layout_without_a_board_image_falls_back(tmp_path):
    (tmp_path / "playground_design.json").write_text(json.dumps({"canvas": '<div class="item" id="p" data-scale="45"></div>'}))
    db = {"Rock Duo": {"Image": "rock-duo.png", "Width": 2.0, "Height": 1.0}}
    assert be.board_image_for(tmp_path, {"board": {"brand": "Rock", "model": "Duo"}}, db)[0] == "rock-duo.png"


def test_board_image_for_unknown_board_raises(tmp_path):
    with pytest.raises(ValueError, match="not in Pedal Playground"):
        be.board_image_for(tmp_path, {"board": {"brand": "No", "model": "Such"}}, {})


# --- coordinates ---------------------------------------------------------------------------------
def test_px_to_frac_and_back_with_zoom_and_margin():
    # zoom 2 px/mm, margin 30 px: the image spans px 30..430 in x and 30..230 in y
    assert be.px_to_frac(130, 80, 2.0, W, H, 30) == pytest.approx((0.25, 0.25))
    assert be.frac_to_px(0.25, 0.25, 2.0, W, H, 30) == pytest.approx((130, 80))
    assert be.px_to_frac(10, 500, 2.0, W, H, 30) == (0.0, 1.0)      # outside: clamped


# --- boxes ---------------------------------------------------------------------------------------
def test_normalize_swaps_corners_and_clamps():
    b = be.normalize_box(0.5, 0.9, -0.2, 0.3, "filled", W, H)
    assert b == {"type": "filled", "x0": 0.0, "y0": 0.3, "x1": 0.5, "y1": 0.9}
    assert be.normalize_box(0.2, 0.2, 1.7, 2.0, "hole", W, H) == box("hole", 0.2, 0.2, 1.0, 1.0)


def test_normalize_rejects_a_box_smaller_than_one_mm():
    assert be.normalize_box(0.1, 0.1, 0.104, 0.5, "hole", W, H) is None      # 0.004 * 200 = 0.8 mm wide
    assert be.normalize_box(0.1, 0.1, 0.5, 0.109, "hole", W, H) is None      # 0.009 * 100 = 0.9 mm high
    assert be.normalize_box(0.1, 0.1, 0.5, 0.5, "weird", W, H) is None
    assert be.normalize_box(0.1, 0.1, 0.11, 0.12, "hole", W, H) is not None  # 2 mm x 2 mm


def test_hit_box_last_box_wins_on_overlap():
    boxes = [box("hole", 0.0, 0.0, 0.5, 0.5), box("filled", 0.25, 0.25, 0.75, 0.75)]
    assert be.hit_box(boxes, 0.4, 0.4) == 1       # both contain it: the later one
    assert be.hit_box(boxes, 0.1, 0.1) == 0
    assert be.hit_box(boxes, 0.9, 0.9) is None
    assert be.hit_box([], 0.5, 0.5) is None


def test_move_box_keeps_size_and_stays_inside():
    b = be.move_box(box(x0=0.1, y0=0.2, x1=0.3, y1=0.6), 0.1, -0.1)
    assert (b["x0"], b["y0"], b["x1"], b["y1"]) == pytest.approx((0.2, 0.1, 0.4, 0.5))
    b = be.move_box(box(x0=0.1, y0=0.2, x1=0.3, y1=0.6), 5, 5)
    assert (b["x0"], b["y0"], b["x1"], b["y1"]) == pytest.approx((0.8, 0.6, 1.0, 1.0))


def test_nudge_in_mm_and_clamped_at_the_edge():
    b = be.nudge_box(box(x0=0.1, y0=0.2, x1=0.3, y1=0.6), 2.0, -1.0, W, H)     # +2 mm = 0.01 x, -1 mm = -0.01 y
    assert (b["x0"], b["y0"], b["x1"], b["y1"]) == pytest.approx((0.11, 0.19, 0.31, 0.59))
    left = be.nudge_box(box(x0=0.001, y0=0.2, x1=0.101, y1=0.6), -2.0, 0, W, H)
    assert (left["x0"], left["x1"]) == pytest.approx((0.0, 0.1))               # stops at the edge, size kept


def test_toggle_type_is_pure():
    b = box("hole")
    assert be.toggle_type(b)["type"] == "filled" and b["type"] == "hole"
    assert be.toggle_type(be.toggle_type(b)) == b


def test_reorder_moves_one_place_and_clamps():
    a, b, c = box("hole"), box("filled"), box("hole", 0.5, 0.5, 0.6, 0.6)
    assert be.reorder([a, b, c], 1, 1) == ([a, c, b], 2)
    assert be.reorder([a, b, c], 1, -1) == ([b, a, c], 0)
    assert be.reorder([a, b, c], 0, -1) == ([a, b, c], 0)
    assert be.reorder([a, b, c], 2, 1) == ([a, b, c], 2)
    assert be.reorder([a, b, c], 0, 5) == ([b, c, a], 2)


def test_list_rows_show_index_type_and_size_in_mm():
    rows = be.list_rows([box("hole", 0.1, 0.2, 0.3, 0.6), box("filled", 0.0, 0.0, 0.05, 0.1)], W, H)
    assert rows == [" 1  hole    40.0 x 40.0 mm", " 2  filled  10.0 x 10.0 mm"]
    assert be.list_rows([], W, H) == []


def test_effective_holes_apply_the_boxes_in_mm():
    derived = [[0.0, 0.0, 0.5, 0.5]]                       # 100 x 50 mm at the top-left
    assert be.effective_holes(derived, [], W, H) == pytest.approx([(0, 0, 100, 50)])
    got = be.effective_holes(derived, [box("filled", 0.25, 0.0, 0.5, 0.5), box("hole", 0.75, 0.5, 1.0, 1.0)], W, H)
    assert sorted(got) == pytest.approx(sorted([(0, 0, 50, 50), (150, 50, 200, 100)]))
    assert design.board_holes(None, derived) == []          # a board item is required: the helper builds its own


# --- the file ------------------------------------------------------------------------------------
def test_dumps_one_box_per_line_with_4_decimals():
    text = be.dumps_edits([box("hole", 0.123456, 0.2, 0.3, 0.6), box("filled", 0, 0, 1, 1)])
    lines = text.splitlines()
    assert lines[0] == "{" and lines[1].startswith('  "_doc": ') and lines[2] == '  "boxes": ['
    assert lines[3] == '    {"type": "hole", "x0": 0.1235, "y0": 0.2, "x1": 0.3, "y1": 0.6},'
    assert lines[4] == '    {"type": "filled", "x0": 0, "y0": 0, "x1": 1, "y1": 1}'
    assert lines[-2:] == ["  ]", "}"]
    assert json.loads(text)["boxes"][0]["x0"] == 0.1235


def test_save_then_load_edits_round_trips(tmp_path):
    boxes = [box("hole", 0.1, 0.2, 0.3, 0.6), box("filled", 0.25, 0.25, 0.5, 0.5)]
    path = be.save_edits(tmp_path, boxes)
    assert path == tmp_path / "board.json" and not (tmp_path / "board.json.tmp").exists()
    warnings = []
    assert boards.load_edits(tmp_path, warnings) == boxes and warnings == []


def test_saving_no_boxes_keeps_the_file(tmp_path):
    be.save_edits(tmp_path, [box()])
    be.save_edits(tmp_path, [])
    data = json.loads((tmp_path / "board.json").read_text())
    assert data["boxes"] == [] and "_doc" in data
    assert boards.load_edits(tmp_path) == []


def test_project_rows_count_holes_and_edits(tmp_path, monkeypatch):
    p = tmp_path / "demo"
    p.mkdir()
    (p / "project.json").write_text(json.dumps({"board": {"brand": "Rock", "model": "Duo"}}))
    be.save_edits(p, [box()])
    monkeypatch.setattr(be, "project_dirs", lambda names: [p])
    db = {"Rock Duo": {"Image": "rock-duo.png", "Width": 1, "Height": 1}}
    (row,) = be.project_rows(None, db, {"rock-duo.png": {"holes": [[0, 0, 1, 1]] * 3}})
    assert "demo" in row and "rock-duo.png" in row and "hole rects  3" in row and "edit boxes 1" in row
    (row,) = be.project_rows(None, db, {})
    assert "hole rects  ?" in row


# --- the window ----------------------------------------------------------------------------------
@pytest.mark.skipif(not os.environ.get("DISPLAY"), reason="needs a display")
def test_the_app_can_be_constructed_and_destroyed(tmp_path):
    from PIL import Image
    img = tmp_path / "board.png"
    Image.new("RGBA", (200, 100), (10, 10, 10, 255)).save(img)
    try:
        app = be.make_app(tmp_path, img, "board.png", W, H, [[0.1, 0.1, 0.2, 0.2]])
    except Exception as e:  # noqa: BLE001  (a DISPLAY that does not work is not a failure of the editor)
        pytest.skip(f"no usable display: {e}")
    try:
        app.update()
        app.boxes.append(box())
        app._toggle_effective()
        app._save()
        assert boards.load_edits(tmp_path) == [box()]
    finally:
        app.destroy()


def test_hit_box_can_skip_the_boxes_so_edge_mode_draws_over_them():
    boxes = [be.make_box("hole", 0.0, 0.0, 0.5, 0.5), be.make_edge("left", 0.0, 0.4)]
    assert be.hit_box(boxes, 0.1, 0.1, 100.0, 50.0) == 0                       # a click in the hole box
    assert be.hit_box(boxes, 0.1, 0.1, 100.0, 50.0, types=("edge",)) is None  # edge mode: free to draw
    assert be.hit_box(boxes, 0.01, 0.2, 100.0, 50.0, types=("edge",)) == 1    # 1 mm from the left segment
