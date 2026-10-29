"""scripts/boards.py: board holes from a board image's alpha channel, the data file, the project's edits,
design.board_holes (rotation, filled / hole boxes) and their drawing in routing.svg."""
import json
import sys
from pathlib import Path

import pytest
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import boards  # noqa: E402
import build  # noqa: E402
import design  # noqa: E402
import svgdraw  # noqa: E402
from common import load_catalog  # noqa: E402

W_MM, H_MM = 50.0, 100.0     # 1 mm cells -> 50 x 100 cells; masks are drawn at 4 px per mm
PX = 4


def board_mask(draw):
    """A 200 x 400 'L' image, opaque (255) everywhere; `draw(ImageDraw)` paints transparent (0) regions (mm)."""
    img = Image.new("L", (int(W_MM * PX), int(H_MM * PX)), 255)
    draw(ImageDraw.Draw(img))
    return img


def clear(d, x0, y0, x1, y1):
    d.rectangle([x0 * PX, y0 * PX, x1 * PX - 1, y1 * PX - 1], fill=0)


def inside_transparent(rects, img):
    """True if every pixel under every rectangle (fractions of the image) is transparent (alpha <= 128)."""
    pw, ph = img.size
    px = img.load()
    for x0, y0, x1, y1 in rects:
        for y in range(round(y0 * ph), round(y1 * ph)):
            for x in range(round(x0 * pw), round(x1 * pw)):
                if px[x, y] > 128:
                    return False
    return True


def test_inner_rectangle_is_one_hole():
    img = board_mask(lambda d: clear(d, 10, 20, 30, 40))
    assert boards.holes_from_alpha(img, W_MM, H_MM) == [[0.2, 0.2, 0.6, 0.4]]
    (reg,) = boards.hole_regions(img, W_MM, H_MM)
    assert reg["cells"] == reg["covered"] == 400


def test_strip_touching_the_border_is_not_a_hole():
    def draw(d):
        clear(d, 0, 0, 50, 10)       # along the top edge
        clear(d, 0, 50, 20, 60)      # from the left edge inwards
    assert boards.holes_from_alpha(board_mask(draw), W_MM, H_MM) == []


def test_two_holes():
    def draw(d):
        clear(d, 5, 10, 20, 20)
        clear(d, 25, 60, 45, 90)
    img = board_mask(draw)
    assert boards.holes_from_alpha(img, W_MM, H_MM) == [[0.1, 0.1, 0.4, 0.2], [0.5, 0.6, 0.9, 0.9]]
    assert len(boards.hole_regions(img, W_MM, H_MM)) == 2


def test_circular_hole_is_covered_by_rects_inside_it():
    img = board_mask(lambda d: d.ellipse([15 * PX, 40 * PX, 35 * PX - 1, 60 * PX - 1], fill=0))   # 20 mm circle
    (reg,) = boards.hole_regions(img, W_MM, H_MM)
    assert 1 < len(reg["rects"]) <= boards.MAX_BANDS
    assert inside_transparent(reg["rects"], img)
    assert reg["covered"] / reg["cells"] >= 0.8
    area = sum((r[2] - r[0]) * W_MM * (r[3] - r[1]) * H_MM for r in reg["rects"])
    assert area <= 3.1416 * 100          # never more than the circle (r = 10 mm)


def test_rounded_slot_with_few_rects_is_inside_and_well_covered():
    img = board_mask(lambda d: d.rounded_rectangle([5 * PX, 30 * PX, 45 * PX - 1, 42 * PX - 1], radius=5 * PX, fill=0))
    (reg,) = boards.hole_regions(img, W_MM, H_MM)
    assert len(reg["rects"]) <= boards.MAX_BANDS and reg["covered"] / reg["cells"] >= 0.9
    assert inside_transparent(reg["rects"], img)


def test_speck_is_ignored_but_a_larger_hole_is_kept():
    def draw(d):
        clear(d, 10, 10, 12, 12)     # 4 mm^2 < 10
        clear(d, 20, 50, 24, 54)     # 16 mm^2
    assert boards.holes_from_alpha(board_mask(draw), W_MM, H_MM) == [[0.4, 0.5, 0.48, 0.54]]


def test_single_semi_transparent_rim_pixels_do_not_join_or_enlarge():
    """A hole next to a one-pixel hairline reaching the border stays a hole (the hairline makes no whole cell)."""
    def draw(d):
        clear(d, 10, 20, 30, 40)
        d.line([30 * PX, 30 * PX, 50 * PX - 1, 30 * PX], fill=0)    # 1 px wide, out to the right border
    img = board_mask(draw)
    (r,) = boards.holes_from_alpha(img, W_MM, H_MM)
    assert r == [0.2, 0.2, 0.6, 0.4]


def test_semi_opaque_pixels_above_128_block_a_cell():
    img = board_mask(lambda d: clear(d, 10, 20, 30, 40))
    img.putpixel((10 * PX + 2, 30 * PX), 200)          # one opaque-ish pixel inside the column x = 10 mm
    (r,) = boards.holes_from_alpha(img, W_MM, H_MM)
    assert r[0] >= 0.22 and inside_transparent([r], img)


def test_two_dimensional_list_is_accepted_and_no_hole_gives_empty():
    rows = [[255] * 20 for _ in range(20)]
    assert boards.holes_from_alpha(rows, 20.0, 20.0) == []
    for y in range(5, 15):
        for x in range(5, 15):
            rows[y][x] = 0
    assert boards.holes_from_alpha(rows, 20.0, 20.0) == [[0.25, 0.25, 0.75, 0.75]]


def test_rects_are_rounded_inward():
    # 3 x 3 mm hole at 0.3333 mm... a hole from cell 1 to 4 of 3 cells wide image: x0 = 1/3 -> 0.3334, x1 = 2/3 -> 0.6666
    img = Image.new("L", (30, 30), 255)
    ImageDraw.Draw(img).rectangle([10, 10, 19, 19], fill=0)
    (r,) = boards.holes_from_alpha(img, 3.0, 3.0, cell_mm=1.0, min_area_mm2=0.5)
    assert r == [0.3334, 0.3334, 0.6666, 0.6666]


# --- the file ---------------------------------------------------------------------------------
ENTRY = {"holes": [[0.1, 0.2, 0.5, 0.25], [0.6, 0.6, 0.9, 0.9]], "hole_transit_mm": 15, "notes": "n"}


def test_dumps_one_hole_per_line_sorted_and_round_trips(tmp_path):
    data = {"_doc": "doc", "boards": {"b.png": {"holes": [], "hole_transit_mm": 10}, "a.png": ENTRY}}
    text = boards.dumps(data)
    lines = text.splitlines()
    assert lines[1] == '  "_doc": "doc",' and lines[2] == '  "boards": {'
    assert lines[3] == '    "a.png": {' and lines[4] == '      "holes": [' and lines[5] == "        [0.1, 0.2, 0.5, 0.25],"
    assert lines[6] == "        [0.6, 0.6, 0.9, 0.9]" and lines[7] == "      ]," and lines[8] == '      "hole_transit_mm": 15,'
    assert '"b.png": {' in text and '"holes": [],' in text
    path = tmp_path / "boards.json"
    path.write_text(text)
    assert boards.read_file(path) == data


def test_missing_file_is_empty_and_save_keeps_other_entries(tmp_path):
    path = tmp_path / "boards.json"
    assert boards.read_file(path)["boards"] == {}
    boards.save({"a.png": ENTRY}, path)
    boards.save({"b.png": {"holes": []}}, path)
    assert sorted(boards.read_file(path)["boards"]) == ["a.png", "b.png"]


def test_usable_drops_malformed_boards():
    bad = {"ok.png": ENTRY, "none.png": {"holes": []}, "flip.png": {"holes": [[0.5, 0, 0.2, 1]]}, "short.png": {"holes": [[0, 0, 1]]},
           "str.png": "x", "nolist.png": {"holes": "x"}, "text.png": {"holes": [["a", 0, 1, 1]]}, "pct.png": {"holes": [[0, 0, 100, 100]]},
           "neg.png": {"holes": [[-0.1, 0, 0.5, 1]]}, "bool.png": {"holes": [[False, 0, True, 1]]}, "missing.png": {"notes": "x"}}
    assert boards.usable(bad) == {"ok.png": ENTRY, "none.png": {"holes": []}}
    assert boards.usable({"boards": bad}) == boards.usable(bad)
    assert boards.usable(None) == {}


def test_usable_drops_a_bad_transit_but_keeps_the_holes():
    got = boards.usable({"a.png": {"holes": [[0, 0, 1, 1]], "hole_transit_mm": -3}, "b.png": {"holes": [], "hole_transit_mm": "x"}})
    assert got == {"a.png": {"holes": [[0, 0, 1, 1]]}, "b.png": {"holes": []}}


def test_usable_drops_a_bad_edge_transit():
    h = [[0, 0, 1, 1]]
    got = boards.usable({"a.png": {"holes": h, "edge_transit_mm": "x"}, "b.png": {"holes": h, "edge_transit_mm": True},
                         "c.png": {"holes": h, "edge_transit_mm": -1}, "d.png": {"holes": h, "edge_transit_mm": 0},
                         "e.png": {"holes": h, "edge_transit_mm": 7.5}})
    assert got == {"a.png": {"holes": h}, "b.png": {"holes": h}, "c.png": {"holes": h},
                   "d.png": {"holes": h, "edge_transit_mm": 0}, "e.png": {"holes": h, "edge_transit_mm": 7.5}}


def test_committed_file_is_well_formed():
    data = boards.read_file()
    assert {"fender-pro-medium.png", "rockboard-duo-21.png"} <= set(data["boards"])
    assert set(boards.usable(data["boards"])) == set(data["boards"])
    assert boards.dumps(data) == (ROOT / "catalog" / "boards.json").read_text()
    assert all(e["hole_transit_mm"] >= 0 for e in data["boards"].values())


# --- the project's edits -------------------------------------------------------------------------
def test_load_edits_missing_file_is_empty(tmp_path):
    w = []
    assert boards.load_edits(tmp_path, w) == [] and w == []


def test_load_edits_ignores_invalid_boxes_with_a_warning(tmp_path):
    good = {"type": "hole", "x0": 0.1, "y0": 0.2, "x1": 0.3, "y1": 0.4}
    boxes = [good, {**good, "type": "weird"}, {**good, "x1": 0.05}, {**good, "x0": "a"}, {"type": "filled"}, "x",
             {"type": "filled", "x0": 0, "y0": 0, "x1": 1, "y1": 1, "extra": 1}]
    (tmp_path / "board.json").write_text(json.dumps({"boxes": boxes}))
    w = []
    got = boards.load_edits(tmp_path, w)
    assert got == [good, {"type": "filled", "x0": 0, "y0": 0, "x1": 1, "y1": 1}]
    assert len(w) == 5 and "box 1" in w[0]
    assert boards.load_edits(tmp_path) == got      # no warnings list: no crash


def test_load_edits_survives_a_broken_file(tmp_path):
    (tmp_path / "board.json").write_text("{not json")
    w = []
    assert boards.load_edits(tmp_path, w) == [] and len(w) == 1
    (tmp_path / "board.json").write_text('{"boxes": 3}')
    assert boards.load_edits(tmp_path, w) == [] and len(w) == 2


# --- design.board_holes ---------------------------------------------------------------------------
def board(rot=0):
    # 100 x 50 mm image at left 20, top 10 mm: centre (70, 35)
    return {"id": "b", "kind": "pedalboard", "rot": rot, "scale": 45, "image": "x.png", "w_mm": 100.0, "h_mm": 50.0,
            "left_mm": 20.0, "top_mm": 10.0}


HOLES = [[0.1, 0.2, 0.3, 0.6]]


def area(rects):
    return sum((x1 - x0) * (y1 - y0) for x0, y0, x1, y1 in rects)


def box(kind, x0, y0, x1, y1):
    return {"type": kind, "x0": x0, "y0": y0, "x1": x1, "y1": y1}


@pytest.mark.parametrize("rot, expected", [(0, (30, 20, 50, 40)), (90, (65, -5, 85, 15))])
def test_board_holes_rotate_with_the_board(rot, expected):
    (r,) = design.board_holes(board(rot), HOLES)
    assert r == pytest.approx(expected)


def test_board_holes_without_board_or_data_are_empty():
    assert design.board_holes(None, HOLES) == []
    assert design.board_holes(board(), None) == []
    assert design.board_holes(board(), []) == []


def test_filled_subtracts_part_of_a_hole():
    got = design.board_holes(board(), HOLES, [box("filled", 0.2, 0.0, 0.4, 0.4)])
    assert sorted(got) == pytest.approx(sorted([(30, 30, 50, 40), (30, 20, 40, 30)]))
    assert area(got) == pytest.approx(300)     # 20 x 20 minus the 10 x 10 cut


def test_filled_over_the_whole_hole_removes_it():
    assert design.board_holes(board(), HOLES, [box("filled", 0, 0, 1, 1)]) == []


def test_filled_that_misses_the_hole_changes_nothing():
    assert design.board_holes(board(), HOLES, [box("filled", 0.5, 0.5, 0.9, 0.9)]) == [pytest.approx((30, 20, 50, 40))]


def test_hole_box_adds_a_hole():
    got = design.board_holes(board(), HOLES, [box("hole", 0.5, 0.5, 0.7, 0.9)])
    assert (70, 35, 90, 55) in [tuple(round(v, 6) for v in r) for r in got]
    assert len(got) == 2


def test_overlapping_hole_box_is_not_counted_twice():
    got = design.board_holes(board(), HOLES, [box("hole", 0.2, 0.3, 0.4, 0.5)])
    assert area(got) == pytest.approx(500)     # 400 + 200 - 100 overlap, pieces do not overlap


def test_edit_order_later_box_wins():
    b = box("hole", 0.5, 0.5, 0.7, 0.9)
    closed = design.board_holes(board(), [], [b, {**b, "type": "filled"}])
    opened = design.board_holes(board(), [], [{**b, "type": "filled"}, b])
    assert closed == []
    assert opened == [pytest.approx((70, 35, 90, 55))]
    over = design.board_holes(board(), HOLES, [box("filled", 0.1, 0.2, 0.3, 0.6), box("hole", 0.1, 0.2, 0.2, 0.4)])
    assert area(over) == pytest.approx(10 * 10)


# --- layout and drawing ---------------------------------------------------------------------------
def test_gig_layout_has_the_board_holes_inside_the_board():
    pedals, supplies = load_catalog()
    gig = ROOT / "projects" / "guitar-gig"
    ctx = build.validate(gig, pedals, supplies, route=False)
    holes = ctx["layout"]["holes"]
    x0, y0, x1, y1 = design.footprint(ctx["layout"]["board"])
    assert holes and all(x0 <= r[0] < r[2] <= x1 and y0 <= r[1] < r[3] <= y1 for r in holes)
    none = build.validate(gig, pedals, supplies, route=False, board_data={})   # no derived holes: only the project's edits
    assert none["layout"]["holes"] == design.board_holes(none["layout"]["board"], [], boards.load_edits(gig))


def test_holes_are_drawn_after_the_board_with_a_key_entry():
    svg = "".join(svgdraw.holes([(1.0, 2.0, 11.0, 7.0)]))
    assert '<rect x="1.0" y="2.0" width="10.0" height="5.0"' in svg and 'class="hole"' in svg
    assert svgdraw.holes([]) == []
    ctx = {"layout": {"holes": [(1, 2, 3, 4)]}}
    assert ("hole", "Board hole") in svgdraw.key_entries(ctx, [], 2)
    assert ("hole", "Board hole") not in svgdraw.key_entries({"layout": {"holes": []}}, [], 2)
    assert "<rect" in svgdraw.key_sample("hole", 0, 0)


# --- the bounds ----------------------------------------------------------------------------------
EDGE = {"back": 0.0, "front": 1.0, "left": 0.0, "right": 1.0}


def write_bounds(tmp_path, bounds):
    (tmp_path / "board.json").write_text(json.dumps({"bounds": bounds, "boxes": []}))


def test_load_bounds_defaults_are_the_image_edges(tmp_path):
    w = []
    assert boards.load_bounds(None, w) == EDGE                       # no project folder
    assert boards.load_bounds(tmp_path, w) == EDGE                   # no file
    (tmp_path / "board.json").write_text(json.dumps({"boxes": []}))
    assert boards.load_bounds(tmp_path, w) == EDGE                   # no bounds key
    write_bounds(tmp_path, {})
    assert boards.load_bounds(tmp_path, w) == EDGE and w == []


def test_load_bounds_valid_full_and_partial(tmp_path):
    write_bounds(tmp_path, {"back": 0.06, "front": 0.95, "left": 0.01, "right": 0.99})
    w = []
    assert boards.load_bounds(tmp_path, w) == {"back": 0.06, "front": 0.95, "left": 0.01, "right": 0.99} and w == []
    write_bounds(tmp_path, {"front": 0.9})                             # missing sides = the image edge
    assert boards.load_bounds(tmp_path, w) == {**EDGE, "front": 0.9} and w == []
    write_bounds(tmp_path, {"back": 0, "right": 1})                    # integers are numbers
    assert boards.load_bounds(tmp_path, w) == EDGE and w == []


@pytest.mark.parametrize("bounds", [
    {"back": "a"}, {"back": None}, {"left": True}, {"front": 1.5}, {"right": -0.1}, {"back": float("nan")},
    {"back": 0.5, "front": 0.5}, {"back": 0.7, "front": 0.3}, {"back": 1.0},          # back >= front
    {"left": 0.5, "right": 0.5}, {"left": 0.9, "right": 0.1}, {"right": 0.0},         # left >= right
    {"top": 0.1}, [0.1, 0.9], "x", 3])
def test_load_bounds_invalid_values_warn_and_give_the_defaults(tmp_path, bounds):
    # a half-valid set is not trusted: every side comes back as the image edge
    (tmp_path / "board.json").write_text(json.dumps({"bounds": bounds, "boxes": []}).replace("NaN", "NaN"))
    w = []
    assert boards.load_bounds(tmp_path, w) == EDGE
    assert len(w) == 1 and w[0].startswith(f"{tmp_path.name}/board.json: bounds ignored (")
    assert boards.load_bounds(tmp_path) == EDGE                      # no warnings list: no crash


def test_load_bounds_valid_sides_are_not_kept_next_to_an_invalid_one(tmp_path):
    write_bounds(tmp_path, {"back": 0.1, "front": "x"})
    w = []
    assert boards.load_bounds(tmp_path, w) == EDGE and len(w) == 1


def test_load_bounds_survives_a_broken_file_and_load_edits_ignores_bounds(tmp_path):
    (tmp_path / "board.json").write_text("{not json")
    w = []
    assert boards.load_bounds(tmp_path, w) == EDGE and len(w) == 1 and "unreadable" in w[0]
    box = {"type": "hole", "x0": 0.1, "y0": 0.2, "x1": 0.3, "y1": 0.4}
    (tmp_path / "board.json").write_text(json.dumps({"bounds": {"back": 0.1}, "boxes": [box]}))
    w = []
    assert boards.load_edits(tmp_path, w) == [box] and w == []
