"""scripts/outlines.py: decomposition of a pedal's alpha channel into rectangles, the data file, design.outline_rects."""
import random
import sys
from pathlib import Path

import pytest
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import design  # noqa: E402
import outlines  # noqa: E402

W_MM, H_MM = 50.0, 100.0     # 1 mm cells -> 50 x 100 cells; masks are drawn at 4 px per mm
PX = 4


def mask(draw):
    """A 200 x 400 'L' image; `draw(ImageDraw)` paints opaque regions (coordinates in mm, scaled by PX)."""
    img = Image.new("L", (int(W_MM * PX), int(H_MM * PX)), 0)
    draw(ImageDraw.Draw(img))
    return img


def box(d, x0, y0, x1, y1):
    d.rectangle([x0 * PX, y0 * PX, x1 * PX - 1, y1 * PX - 1], fill=255)


def covered(rects, img):
    """True if every opaque pixel (alpha > 128) lies inside the union of the rectangles (fractions of the image):
    its centre and its four corners, pulled in a hair, are inside some rectangle (a pixel may straddle two of them)."""
    pw, ph = img.size
    px = img.load()
    e = 1e-3

    def inside(x, y):
        return any(r[0] * pw <= x + 1e-6 and x <= r[2] * pw + 1e-6 and r[1] * ph <= y + 1e-6 and y <= r[3] * ph + 1e-6 for r in rects)
    return all(inside(x + dx, y + dy) for y in range(ph) for x in range(pw) if px[x, y] > 128
               for dx, dy in ((0.5, 0.5), (e, e), (1 - e, e), (e, 1 - e), (1 - e, 1 - e)))


def test_full_rectangle_is_one_rect():
    assert outlines.outline_from_alpha(mask(lambda d: box(d, 0, 0, 50, 100)), W_MM, H_MM) == [[0, 0, 1, 1]]


def test_empty_image_is_the_whole_box():
    assert outlines.outline_from_alpha(mask(lambda d: None), W_MM, H_MM) == [[0, 0, 1, 1]]


def test_two_dimensional_list_is_accepted():
    rows = [[255] * 10 for _ in range(20)]
    assert outlines.outline_from_alpha(rows, 10.0, 20.0) == [[0, 0, 1, 1]]


def test_body_with_a_jack_bump_gives_body_and_bump():
    def draw(d):
        box(d, 5, 10, 45, 100)      # body
        box(d, 20, 0, 30, 10)       # bump on top
    img = mask(draw)
    rects = outlines.outline_from_alpha(img, W_MM, H_MM)
    assert rects == [[0.4, 0.0, 0.6, 0.1], [0.1, 0.1, 0.9, 1.0]]
    assert covered(rects, img)


def test_two_separate_top_jacks_are_two_runs_in_that_band():
    def draw(d):
        box(d, 0, 10, 50, 100)
        box(d, 5, 0, 12, 10)
        box(d, 30, 0, 40, 10)
    img = mask(draw)
    rects = outlines.outline_from_alpha(img, W_MM, H_MM)
    top = [r for r in rects if r[3] <= 0.1]
    assert sorted(top) == [[0.1, 0.0, 0.24, 0.1], [0.6, 0.0, 0.8, 0.1]]
    assert covered(rects, img)


def test_close_runs_join_and_far_runs_do_not():
    near = mask(lambda d: (box(d, 0, 0, 10, 100), box(d, 11, 0, 50, 100)))     # 1 mm gap < 2 mm
    far = mask(lambda d: (box(d, 0, 0, 10, 100), box(d, 13, 0, 50, 100)))      # 3 mm gap
    assert outlines.outline_from_alpha(near, W_MM, H_MM) == [[0, 0, 1, 1]]
    assert outlines.outline_from_alpha(far, W_MM, H_MM) == [[0, 0, 0.2, 1], [0.26, 0, 1, 1]]


def test_rounded_corners_stay_covered():
    img = mask(lambda d: d.rounded_rectangle([0, 0, 50 * PX - 1, 100 * PX - 1], radius=8 * PX, fill=255))
    rects = outlines.outline_from_alpha(img, W_MM, H_MM)
    assert 1 < len(rects) <= 16 and covered(rects, img)


@pytest.mark.parametrize("limit", [2, 3, 5])
def test_max_rects_is_respected_and_coverage_kept(limit):
    def draw(d):   # a staircase: every step is its own band
        for n in range(10):
            box(d, 0, n * 10, 5 + n * 4, n * 10 + 10)
    img = mask(draw)
    rects = outlines.outline_from_alpha(img, W_MM, H_MM, max_rects=limit)
    assert len(rects) <= limit and covered(rects, img)


@pytest.mark.parametrize("seed", range(5))
def test_random_blobs_are_covered(seed):
    rnd = random.Random(seed)

    def draw(d):
        for _ in range(6):
            x0, y0 = rnd.uniform(0, 40), rnd.uniform(0, 90)
            box(d, x0, y0, x0 + rnd.uniform(2, 25), y0 + rnd.uniform(2, 40))
            ex, ey = rnd.uniform(0, 160), rnd.uniform(0, 340)
            d.ellipse([ex, ey, ex + rnd.uniform(5, 40), ey + rnd.uniform(5, 60)], fill=255)
    img = mask(draw)
    rects = outlines.outline_from_alpha(img, W_MM, H_MM)
    assert len(rects) <= 16 and covered(rects, img)
    assert all(0 <= r[0] < r[2] <= 1 and 0 <= r[1] < r[3] <= 1 for r in rects)


def test_single_pixel_is_found_and_rounding_is_outward():
    img = Image.new("L", (150, 300), 0)
    img.putpixel((77, 151), 255)
    (r,) = outlines.outline_from_alpha(img, 3.0, 6.0, cell_mm=1.0)
    assert r[0] <= 77 / 150 and r[2] >= 78 / 150 and r[1] <= 151 / 300 and r[3] >= 152 / 300
    assert r == [round(r[0], 4), round(r[1], 4), round(r[2], 4), round(r[3], 4)]


# --- design.outline_rects ---------------------------------------------------------------------
def pedal(rot):
    # 50.8 x 101.6 mm at left 25.4, top 50.8 mm: centre (50.8, 101.6)
    return {"id": "p", "kind": "pedal", "rot": rot, "scale": 45, "image": "a.png", "w_mm": 50.8, "h_mm": 101.6,
            "left_mm": 25.4, "top_mm": 50.8}


OUT = {"a.png": [[0.1, 0.2, 0.6, 0.5]]}


@pytest.mark.parametrize("rot, expected", [
    (0, (30.48, 71.12, 55.88, 101.6)),
    (90, (50.8, 81.28, 81.28, 106.68)),
    (180, (45.72, 101.6, 71.12, 132.08)),
    (270, (20.32, 96.52, 50.8, 121.92)),
])
def test_outline_rects_rotate_with_the_pedal(rot, expected):
    (r,) = design.outline_rects(pedal(rot), OUT)
    assert r == pytest.approx(expected)


def test_outline_rects_fall_back_to_the_box():
    it = pedal(90)
    box_ = design.footprint(it)
    assert design.outline_rects(it, {}) == [box_]
    assert design.outline_rects(it, None) == [box_]
    assert design.outline_rects({**it, "image": None}, OUT) == [box_]
    assert design.outline_rects({**it, "image": "other.png"}, OUT) == [box_]


# --- the file ---------------------------------------------------------------------------------
def test_dumps_one_entry_per_line_sorted_and_round_trips(tmp_path):
    data = {"_doc": "doc", "outlines": {"b.png": [[0, 0, 1, 1]], "a.png": [[0.1, 0.0, 0.5, 0.25], [0.0, 0.25, 1.0, 1.0]]}}
    text = outlines.dumps(data)
    lines = text.splitlines()
    assert lines[1] == '  "_doc": "doc",' and lines[2] == '  "outlines": {'
    assert lines[3].startswith('    "a.png": [[0.1, 0.0, 0.5, 0.25], [0.0, 0.25, 1.0, 1.0]],')
    assert lines[4] == '    "b.png": [[0, 0, 1, 1]]' and lines[5:] == ["  }", "}"]
    path = tmp_path / "outlines.json"
    path.write_text(text)
    assert outlines.read_file(path) == data


def test_missing_file_is_empty_and_save_keeps_other_entries(tmp_path):
    path = tmp_path / "outlines.json"
    assert outlines.read_file(path)["outlines"] == {}
    outlines.save({"a.png": [[0, 0, 1, 1]]}, path)
    outlines.save({"b.png": [[0, 0, 0.5, 1]]}, path)
    assert sorted(outlines.read_file(path)["outlines"]) == ["a.png", "b.png"]


def test_usable_drops_malformed_outlines():
    bad = {"ok.png": [[0, 0, 1, 1]], "empty.png": [], "flip.png": [[0.5, 0, 0.2, 1]], "short.png": [[0, 0, 1]],
           "str.png": "x", "text.png": [["a", 0, 1, 1]]}
    assert outlines.usable(bad) == {"ok.png": [[0, 0, 1, 1]]}
    assert outlines.usable({"outlines": bad}) == {"ok.png": [[0, 0, 1, 1]]}
    assert outlines.usable(None) == {}


def test_coverage_counts_overlaps_once():
    assert outlines.coverage([[0, 0, 0.5, 1], [0.25, 0, 1, 1]]) == pytest.approx(1.0)
    assert outlines.coverage([[0, 0, 0.5, 0.5]]) == pytest.approx(0.25)


def test_committed_file_is_well_formed():
    data = outlines.read_file()
    assert set(outlines.usable(data["outlines"])) == set(data["outlines"])
    assert outlines.dumps(data) == (ROOT / "catalog" / "outlines.json").read_text()


def test_usable_drops_entries_outside_the_image_fractions():
    good = [[0.0, 0.0, 1.0, 1.0]]
    data = {"ok.png": good, "pct.png": [[0, 0, 100, 100]], "neg.png": [[-0.1, 0, 0.5, 1]], "bool.png": [[False, 0, True, 1]]}
    assert outlines.usable(data) == {"ok.png": good}
