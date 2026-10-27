"""Pedalboard holes: the slots and cutouts in the deck of each board, as a few rectangles (catalog/boards.json).

Pedal Playground draws every board as a PNG; the slots (where cables can pass under the board) are transparent.
`holes_from_alpha` finds the transparent regions that do NOT touch the image border (those that do are the outline /
frame profile; regions are made of 1 mm cells that are transparent in ALL their pixels, so a one-pixel hairline never
joins a slot to the outline) and covers each with a few rectangles. The rectangles are CONSERVATIVE: every one lies entirely inside
the transparent pixels of its hole (never bigger than the hole), the opposite of scripts/outlines.py. Only numbers are
stored, keyed by the board IMAGE file name, as fractions (0..1) of the unrotated image, origin top-left. No image is
ever committed.

    uv run scripts/boards.py [project ...] [--image NAME ...] [--refresh]

fetches the board images of the projects (their layout's board, else the board named in project.json) and of
`--image`, and writes catalog/boards.json; existing entries are kept unless --refresh (which recomputes only the
holes: `hole_transit_mm` and `notes` stay).

A project may correct the derived holes in projects/<name>/board.json (written later by a board editor):
{"boxes": [{"type": "hole" | "filled", "x0": .., "y0": .., "x1": .., "y1": ..},
{"type": "edge", "side": "left" | "right" | "back" | "front", "from": .., "to": ..}]}.
hole / filled boxes are fractions of the board image and correct the holes. An "edge" entry is a line segment along one
side of the (unrotated) image, `from` < `to` fractions 0..1 along that side (left / right: of the image height from the top;
back = the image's top edge / front = its bottom edge: of the image width from the left): where cables may go round the
board edge (under the board and back up). `load_edits` reads the file; `design.board_holes` applies the hole / filled
boxes, `design.board_edges` maps the edge segments.
"""
import argparse
import json
import math
import os
import sys
from pathlib import Path

import design
from common import CATALOG, IN_MM, database, fetch_image, load_json, project_dirs

BOARDS_FILE = CATALOG / "boards.json"
EDITS_FILE = "board.json"
DEFAULT_TRANSIT_MM = 15
TRANSIT_NOTE = "hole_transit_mm: unverified estimate (owner, 2026-10-26)"
DOC = ("Pedalboard holes per Pedal Playground board IMAGE file name (e.g. fender-pro-medium.png). holes: rectangles "
       "[x0, y0, x1, y1], fractions (0..1) of the UNROTATED image, origin top-left, 4 decimals; each lies entirely inside "
       "a transparent slot / cutout of the board image (conservative: never bigger than the hole). hole_transit_mm: extra "
       "cable length for one pass through the deck (down or up); NOT derived, an estimate until measured. Written ONLY by "
       "scripts/boards.py (holes); no image is stored.")
ALPHA_MAX = 128          # a pixel is transparent (hole or outside) when its alpha is at most this
MIN_HOLE_MM2 = 10.0      # smaller transparent regions are image noise, not holes
TARGET_COVER = 0.9       # a hole gets the fewest bands that cover at least this share of it ...
MAX_BANDS = 6            # ... at most this many (per hole)
EDGE_SIDES = ("left", "right", "back", "front")   # of the unrotated image: back = its top edge, front = its bottom edge


# --- decomposition (pure) ------------------------------------------------------------------------
def _as_image(alpha):
    """A Pillow 'L' image from an image or a 2D list of 0..255 values."""
    from PIL import Image
    if hasattr(alpha, "getextrema"):
        return alpha if alpha.mode == "L" else alpha.getchannel("A") if "A" in alpha.mode else alpha.convert("L")
    h, w = len(alpha), len(alpha[0]) if alpha else 0
    img = Image.new("L", (max(w, 1), max(h, 1)))
    img.putdata([v for row in alpha for v in row])
    return img


def _cells(img, nx, ny):
    """Grid [ny][nx]: a cell is transparent only if ALL pixels inside it (partly covered edge pixels included) have
    alpha <= 128. A one-pixel hairline or a rim of semi-opaque pixels therefore never makes a cell, and never joins
    two regions."""
    pw, ph = img.size
    opaque = img.point(lambda a: 255 if a > ALPHA_MAX else 0)
    grid = []
    for r in range(ny):
        y0, y1 = r * ph // ny, -(-(r + 1) * ph // ny)
        strip = opaque.crop((0, y0, pw, max(y1, y0 + 1)))
        if strip.getextrema()[1] == 0:
            grid.append([True] * nx)
            continue
        row = []
        for c in range(nx):
            x0, x1 = c * pw // nx, -(-(c + 1) * pw // nx)
            row.append(strip.crop((x0, 0, max(x1, x0 + 1), strip.size[1])).getextrema()[1] == 0)
        grid.append(row)
    return grid


def _components(grid):
    """4-connected components of the True cells: lists of (row, col)."""
    ny, nx = len(grid), len(grid[0]) if grid else 0
    seen, comps = set(), []
    for r in range(ny):
        for c in range(nx):
            if grid[r][c] and (r, c) not in seen:
                seen.add((r, c))
                stack, comp = [(r, c)], []
                while stack:
                    y, x = stack.pop()
                    comp.append((y, x))
                    for yy, xx in ((y - 1, x), (y + 1, x), (y, x - 1), (y, x + 1)):
                        if 0 <= yy < ny and 0 <= xx < nx and grid[yy][xx] and (yy, xx) not in seen:
                            seen.add((yy, xx))
                            stack.append((yy, xx))
                comps.append(comp)
    return comps


def _mask_runs(mask):
    """Maximal runs [(start, end exclusive)] of set bits of an int bit mask."""
    runs, c = [], 0
    while mask:
        low = (mask & -mask).bit_length() - 1
        mask >>= low
        c += low
        n = (~mask & (mask + 1)).bit_length() - 1   # length of the run of ones from bit 0
        runs.append((c, c + n))
        mask >>= n
        c += n
    return runs


def _bands(rows, target=TARGET_COVER, max_bands=MAX_BANDS):
    """Rectangles (r0, r1, c0, c1; end exclusive) inside the cells set in `rows` (int bit masks, one per row).

    A band is consecutive rows; its rectangles are the maximal runs of the columns set in ALL its rows, so each lies
    inside the region. Dynamic programming picks, for the fewest bands that cover `target` of the region (at most
    `max_bands`), the bands covering the most cells."""
    n = len(rows)
    total = sum(bin(m).count("1") for m in rows)
    if not total:
        return []
    area = [[0] * (n + 1) for _ in range(n + 1)]      # area[a][b]: cells covered by one band of rows a..b-1
    for a in range(n):
        m = -1
        for b in range(a + 1, n + 1):
            m &= rows[b - 1]
            area[a][b] = bin(m).count("1") * (b - a)
    best = [[0] * (n + 1) for _ in range(max_bands + 1)]   # best[k][i]: most cells with k bands over rows 0..i-1
    cut = [[0] * (n + 1) for _ in range(max_bands + 1)]
    for k in range(1, max_bands + 1):
        for i in range(1, n + 1):
            best[k][i], cut[k][i] = max((best[k - 1][a] + area[a][i], a) for a in range(i))
    k = next((k for k in range(1, max_bands + 1) if best[k][n] >= target * total), max_bands)
    bands, i = [], n
    while k and i:
        a = cut[k][i]
        bands.append((a, i))
        i, k = a, k - 1
    out = []
    for a, b in sorted(bands):
        m = -1
        for r in range(a, b):
            m &= rows[r]
        out += [(a, b, c0, c1) for c0, c1 in _mask_runs(m)]
    return out


def _round_in(v, up):
    """4 decimals, rounded INWARD (a rectangle never grows); a tiny epsilon keeps exact values exact."""
    return (math.floor(v * 1e4 + 1e-6) if up else math.ceil(v * 1e4 - 1e-6)) / 1e4


def hole_regions(alpha, w_mm, h_mm, cell_mm=1.0, min_area_mm2=MIN_HOLE_MM2, target=TARGET_COVER, max_bands=MAX_BANDS):
    """The holes of a board image: a list of {"cells": hole cell count, "covered": cells covered, "rects": [[x0, y0, x1,
    y1] fractions of the image, 4 decimals, rounded inward]}, one per transparent region that does not touch the image
    border and is at least `min_area_mm2` large.

    `alpha`: a Pillow 'L' image (or a 2D list) of the board's alpha channel, `w_mm` x `h_mm` its size. Cells of about
    `cell_mm` count as hole only if ALL their pixels are transparent; regions are 4-connected cells; every rectangle
    lies inside the transparent pixels of its hole."""
    img = _as_image(alpha)
    nx, ny = max(1, round(w_mm / cell_mm)), max(1, round(h_mm / cell_mm))
    cell_area = (w_mm / nx) * (h_mm / ny)
    grid = _cells(img, nx, ny)
    out = []
    for comp in sorted(_components(grid), key=lambda c: min(c)):
        if len(comp) * cell_area < min_area_mm2 or any(r in (0, ny - 1) or c in (0, nx - 1) for r, c in comp):
            continue    # a speck, or a region touching the image border (the board's outline / frame profile)
        r0, r1 = min(r for r, _ in comp), max(r for r, _ in comp) + 1
        rows = [0] * (r1 - r0)
        for r, c in comp:
            rows[r - r0] |= 1 << c
        found = [(a + r0, b + r0, c0, c1) for a, b, c0, c1 in _bands(rows, target, max_bands)]
        rects = []
        for a, b, c0, c1 in found:
            x0, y0, x1, y1 = _round_in(c0 / nx, False), _round_in(a / ny, False), _round_in(c1 / nx, True), _round_in(b / ny, True)
            if x1 > x0 and y1 > y0:
                rects.append([x0, y0, x1, y1])
        out.append({"cells": len(comp), "covered": sum((b - a) * (c1 - c0) for a, b, c0, c1 in found), "rects": rects})
    return out


def holes_from_alpha(alpha, w_mm, h_mm, **kwargs):
    """All hole rectangles [x0, y0, x1, y1] (fractions of the image, inside the holes) of a board image; see
    `hole_regions`. No holes gives []."""
    return [r for reg in hole_regions(alpha, w_mm, h_mm, **kwargs) for r in reg["rects"]]


# --- the file ------------------------------------------------------------------------------------
def read_file(path=BOARDS_FILE):
    """The whole file as a dict {"_doc", "boards"}; a fresh one if it does not exist."""
    p = Path(path)
    if not p.exists():
        return {"_doc": DOC, "boards": {}}
    data = json.loads(p.read_text())
    data.setdefault("_doc", DOC)
    data.setdefault("boards", {})
    return data


def dumps(data):
    """Compact, diff-friendly JSON: one board per block, one hole rectangle per line, board names sorted."""
    names = sorted(data["boards"])
    head = "{\n" + f'  "_doc": {json.dumps(data.get("_doc", DOC), ensure_ascii=False)},\n  "boards": {{'
    if not names:
        return head + "}\n}\n"
    blocks = []
    for n in names:
        entry = data["boards"][n]
        holes = entry.get("holes") or []
        parts = ['      "holes": []' if not holes else
                 '      "holes": [\n' + ",\n".join(f"        {json.dumps(r)}" for r in holes) + "\n      ]"]
        for k, v in entry.items():
            if k != "holes":
                parts.append(f"      {json.dumps(k)}: {json.dumps(v, ensure_ascii=False)}")
        blocks.append(f"    {json.dumps(n)}: {{\n" + ",\n".join(parts) + "\n    }")
    return head + "\n" + ",\n".join(blocks) + "\n  }\n}\n"


def save(updates, path=BOARDS_FILE):
    """Merge {image name: entry} into the file (re-read first, so other entries are never lost)."""
    data = read_file(path)
    data["boards"].update(updates)
    tmp = Path(str(path) + ".tmp")
    tmp.write_text(dumps(data))
    os.replace(tmp, path)


def _rect_ok(r):   # fractions of the image: 0 <= x0 < x1 <= 1 (bools are not numbers here)
    return (isinstance(r, (list, tuple)) and len(r) == 4
            and all(isinstance(v, (int, float)) and not isinstance(v, bool) and 0 <= v <= 1 for v in r)
            and r[2] > r[0] and r[3] > r[1])


def _edge_ok(b):   # an edge segment: a side and 0 <= from < to <= 1 (fractions along that side)
    f, t = b.get("from"), b.get("to")
    return (b.get("side") in EDGE_SIDES
            and all(isinstance(v, (int, float)) and not isinstance(v, bool) and 0 <= v <= 1 for v in (f, t)) and t > f)


def box_ok(box):
    """Whether `box` is well-formed: hole / filled {"type", "x0".."y1"} inside the image (0..1), edge {"type", "side", "from",
    "to"} (see the module docstring)."""
    if not isinstance(box, dict):
        return False
    t = box.get("type")
    if t in ("hole", "filled"):
        return _rect_ok([box.get("x0"), box.get("y0"), box.get("x1"), box.get("y1")])
    return t == "edge" and _edge_ok(box)


def usable(boards):
    """Only well-formed board entries {image name: {"holes": [[x0, y0, x1, y1], ...], "hole_transit_mm": n, ...}}:
    every hole a fraction rectangle (0 <= x0 < x1 <= 1, same for y); `holes` may be empty (a board without holes);
    `hole_transit_mm` and `edge_transit_mm` are dropped when not a number >= 0. A malformed entry is dropped as a whole, so a
    hand-edited file cannot crash a build. Accepts the whole file dict or just its "boards" part."""
    if isinstance(boards, dict) and isinstance(boards.get("boards"), dict):
        boards = boards["boards"]
    out = {}
    for name, entry in (boards or {}).items():
        holes = entry.get("holes") if isinstance(entry, dict) else None
        if not isinstance(holes, list) or not all(_rect_ok(r) for r in holes):
            continue
        e = {**entry, "holes": [list(r) for r in holes]}
        for key in ("hole_transit_mm", "edge_transit_mm"):
            t = e.get(key)
            if key in e and (not isinstance(t, (int, float)) or isinstance(t, bool) or t < 0):
                del e[key]
        out[name] = e
    return out


def load():
    """The usable boards of catalog/boards.json ({} if the file is missing)."""
    return usable(read_file()["boards"])


def load_edits(project_dir, warnings=None):
    """The valid edit boxes {"type": "hole" | "filled", "x0", "y0", "x1", "y1"} (fractions of the board image) and edge segments
    {"type": "edge", "side", "from", "to"} of
    projects/<name>/board.json, in file order; [] if the file is missing (or there is no project folder). Invalid boxes (or an unreadable file) are
    ignored and described in `warnings` (a list, if given) instead of crashing the build."""
    if project_dir is None:
        return []
    path = Path(project_dir) / EDITS_FILE
    if not path.exists():
        return []

    def warn(msg):
        if warnings is not None:
            warnings.append(f"{path.parent.name}/{EDITS_FILE}: {msg}")
    try:
        raw = load_json(path).get("boxes", [])
    except (ValueError, AttributeError, OSError) as e:
        warn(f"unreadable, ignored ({e})")
        return []
    if not isinstance(raw, list):
        warn("'boxes' is not a list, ignored")
        return []
    boxes = []
    for i, b in enumerate(raw):
        if box_ok(b):
            boxes.append({"type": "edge", "side": b["side"], "from": b["from"], "to": b["to"]} if b["type"] == "edge" else
                         {"type": b["type"], "x0": b["x0"], "y0": b["y0"], "x1": b["x1"], "y1": b["y1"]})
        else:
            warn(f"box {i} ignored (needs type hole|filled with fractions 0 <= x0 < x1 <= 1, 0 <= y0 < y1 <= 1, or type edge with "
                 f"side left|right|back|front and 0 <= from < to <= 1)")
    return boxes


# --- the CLI -------------------------------------------------------------------------------------
def wanted(project_names, extra_images, db):
    """{image name: (w_mm, h_mm)}: the board of each project (its layout's pedalboard item, else the board of
    project.json looked up in Pedal Playground's pedalboards database as "Brand Model") and `extra_images` (looked up
    by their Image)."""
    by_image = {e["Image"]: e for e in db.values() if e.get("Image")}
    out = {}

    def add(name, entry=None, item=None):
        if name in out:
            return
        if item is not None:
            out[name] = (item["w_mm"], item["h_mm"])
        elif entry is not None or name in by_image:
            e = entry or by_image[name]
            out[name] = (e["Width"] * IN_MM, e["Height"] * IN_MM)
        else:
            print(f"  {name}: not in Pedal Playground's pedalboards database, skipped", file=sys.stderr)

    for pdir in project_dirs(project_names or None):
        f = pdir / "playground_design.json"
        item = next((it for it in design.parse_design(f) if it["kind"] == "pedalboard" and it.get("image")), None) if f.exists() else None
        if item is not None:
            add(item["image"], item=item)
            continue
        b = load_json(pdir / "project.json").get("board") or {}
        entry = db.get(f"{b.get('brand')} {b.get('model')}")
        if entry and entry.get("Image"):
            add(entry["Image"], entry=entry)
        else:
            print(f"  {pdir.name}: board {b.get('brand')} {b.get('model')} not in Pedal Playground's database, skipped", file=sys.stderr)
    for name in extra_images:
        add(name)
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("projects", nargs="*", help="project folder names (default: all)")
    ap.add_argument("--image", action="append", default=[], metavar="NAME", help="also compute this board image (file name)")
    ap.add_argument("--refresh", action="store_true", help="recompute the holes of entries that already exist")
    args = ap.parse_args()

    from PIL import Image
    have_all = read_file()["boards"]
    have = usable(have_all)
    every = wanted(args.projects, args.image, database("pedalboards.json"))
    todo = {n: s for n, s in every.items() if args.refresh or n not in have}   # malformed entries: recomputed
    new, failed = {}, []
    for name, (w, h) in sorted(todo.items()):
        try:
            with Image.open(fetch_image(name, kind="pedalboards")) as im:
                alpha = im.convert("RGBA").getchannel("A")
        except (RuntimeError, OSError) as e:
            failed.append(name)
            print(f"  {name}: FAILED ({str(e).splitlines()[0]})")
            continue
        regions = hole_regions(alpha, w, h)
        holes = [r for reg in regions for r in reg["rects"]]
        old = have.get(name) or (have_all.get(name) if isinstance(have_all.get(name), dict) else {})
        entry = {**old, "holes": holes}
        if "hole_transit_mm" not in entry:
            entry["hole_transit_mm"] = DEFAULT_TRANSIT_MM
            entry["notes"] = TRANSIT_NOTE
        new[name] = entry
        cells, covered = sum(r["cells"] for r in regions), sum(r["covered"] for r in regions)
        print(f"  {name}: {len(regions)} holes, {len(holes)} rects, covers {covered / cells * 100 if cells else 0:.0f}% of the hole area")
    if new:
        save(new)
    print(f"{len(new)} board(s) written, {len(every) - len(todo)} kept, {len(failed)} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
