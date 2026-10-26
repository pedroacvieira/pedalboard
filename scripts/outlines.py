"""Pedal outlines: the real top-view shape of each pedal as a few rectangles (catalog/outlines.json).

Pedal Playground draws every pedal as a PNG with a transparent background; the box it lays out (Width x Height)
includes the protruding jacks, so the pedal's true shape is smaller and not a rectangle (jack bumps, rounded
corners). `outline_from_alpha` turns the alpha channel into at most `max_rects` rectangles that COVER every opaque
pixel (conservative: never smaller than the pedal). Only the numbers are stored, keyed by the IMAGE file name, as
fractions (0..1) of the unrotated image, origin top-left. No image is ever committed.

    uv run scripts/outlines.py [project ...] [--image NAME ...] [--refresh]

fetches the images of the projects' layouts and of every catalog pedal / supply (into the git-ignored .cache/images/)
and writes catalog/outlines.json; existing entries are kept unless --refresh.
"""
import argparse
import json
import math
import os
import sys
from pathlib import Path

import design
from common import CATALOG, IN_MM, database, fetch_image, load_catalog, project_dirs

OUTLINES_FILE = CATALOG / "outlines.json"
DOC = ("Pedal outlines per Pedal Playground IMAGE file name (e.g. mxr-m290.png): a list of rectangles [x0, y0, x1, y1], "
       "fractions (0..1) of the UNROTATED image, origin top-left, 4 decimals, that together cover every opaque pixel "
       "(alpha > 128) of the pedal image: the pedal's real top-view shape, smaller than Pedal Playground's box (which "
       "includes the protruding jacks). Written ONLY by scripts/outlines.py. No image is stored.")
ALPHA_MIN = 128   # a pixel is part of the pedal when its alpha is above this


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
    """Occupancy grid [ny][nx]: a cell is occupied if ANY pixel inside it has alpha > ALPHA_MIN."""
    pw, ph = img.size
    binary = img.point(lambda a: 255 if a > ALPHA_MIN else 0)
    grid = []
    for r in range(ny):
        y0, y1 = r * ph // ny, -(-(r + 1) * ph // ny)
        strip = binary.crop((0, y0, pw, max(y1, y0 + 1)))
        row = []
        for c in range(nx):
            x0, x1 = c * pw // nx, -(-(c + 1) * pw // nx)
            row.append(strip.crop((x0, 0, max(x1, x0 + 1), strip.size[1])).getextrema()[1] > 0)
        grid.append(row)
    return grid


def _runs(row, gap_cells):
    """Occupied runs [(start, end exclusive)] of a cell row; runs separated by fewer than `gap_cells` empty cells join."""
    runs, c, n = [], 0, len(row)
    while c < n:
        if row[c]:
            s = c
            while c < n and row[c]:
                c += 1
            if runs and s - runs[-1][1] < gap_cells:
                runs[-1] = (runs[-1][0], c)
            else:
                runs.append((s, c))
        else:
            c += 1
    return runs


def _bands(rows, tol):
    """Consecutive rows with the same number of runs, all of whose run ends stay within `tol` cells of each other
    (compared over the whole band, so a slow drift cannot add up). Returns [(row start, row end exclusive, runs)] where
    each run is the union span of its rows."""
    bands, cur = [], None   # cur: [r0, r1, [[smin, smax, emin, emax] per run]]
    for r, runs in enumerate(rows):
        if not runs:
            cur = None
            continue
        if cur is not None and cur[1] == r and len(cur[2]) == len(runs):
            spans = [[min(a[0], s), max(a[1], s), min(a[2], e), max(a[3], e)] for a, (s, e) in zip(cur[2], runs)]
            if all(a[1] - a[0] <= tol and a[3] - a[2] <= tol for a in spans):
                cur[1], cur[2] = r + 1, spans
                continue
        cur = [r, r + 1, [[s, s, e, e] for s, e in runs]]
        bands.append(cur)
    return [(b[0], b[1], [(a[0], a[3]) for a in b[2]]) for b in bands]


def _area(band):
    return sum(e - s for s, e in band[2]) * (band[1] - band[0])


def _merge(a, b):
    """The band covering both: run by run when the run counts match, else one run over everything."""
    if len(a[2]) == len(b[2]):
        runs = [(min(x[0], y[0]), max(x[1], y[1])) for x, y in zip(a[2], b[2])]
    else:
        runs = [(min(s for s, _ in a[2] + b[2]), max(e for _, e in a[2] + b[2]))]
    return (a[0], b[1], runs)


def _round_out(v, up):
    """4 decimals, rounded outward (so the rectangle never shrinks); a tiny epsilon keeps exact values exact."""
    return (math.ceil(v * 1e4 - 1e-6) if up else math.floor(v * 1e4 + 1e-6)) / 1e4


def outline_from_alpha(alpha, w_mm, h_mm, cell_mm=1.0, gap_mm=2.0, tol_mm=1.0, max_rects=16):
    """Rectangles [x0, y0, x1, y1] (fractions of the image, 4 decimals, rounded outward) covering every opaque pixel.

    `alpha`: a Pillow 'L' image (or a 2D list) of the pedal's alpha channel, `w_mm` x `h_mm` its size. Cells of about
    `cell_mm` are occupied if any pixel has alpha > 128; per cell row the occupied runs closer than `gap_mm` join;
    consecutive rows with the same run count and run ends within `tol_mm` form a band (one rectangle per run, the
    union span of its rows); while there are more than `max_rects` rectangles the two adjacent bands whose merge adds
    the least area are merged. An empty image gives [[0, 0, 1, 1]]."""
    img = _as_image(alpha)
    nx, ny = max(1, round(w_mm / cell_mm)), max(1, round(h_mm / cell_mm))
    cw, ch = w_mm / nx, h_mm / ny
    grid = _cells(img, nx, ny)
    if not any(any(row) for row in grid):
        return [[0, 0, 1, 1]]
    gap_cells = gap_mm / cw - 1e-9
    bands = _bands([_runs(row, gap_cells) for row in grid], tol_mm / cw)
    while sum(len(b[2]) for b in bands) > max_rects and len(bands) > 1:
        i = min(range(len(bands) - 1), key=lambda k: _area(_merge(bands[k], bands[k + 1])) - _area(bands[k]) - _area(bands[k + 1]))
        bands[i:i + 2] = [_merge(bands[i], bands[i + 1])]
    if len(bands) == 1 and len(bands[0][2]) > max_rects:
        r0, r1, runs = bands[0]
        bands = [(r0, r1, [(runs[0][0], runs[-1][1])])]
    return [[_round_out(s / nx, False), _round_out(r0 / ny, False), _round_out(e / nx, True), _round_out(r1 / ny, True)]
            for r0, r1, runs in bands for s, e in runs]


# --- the file ------------------------------------------------------------------------------------
def read_file(path=OUTLINES_FILE):
    """The whole file as a dict {"_doc", "outlines"}; a fresh one if it does not exist."""
    p = Path(path)
    if not p.exists():
        return {"_doc": DOC, "outlines": {}}
    data = json.loads(p.read_text())
    data.setdefault("_doc", DOC)
    data.setdefault("outlines", {})
    return data


def dumps(data):
    """Compact, diff-friendly JSON: one image per line, image names sorted."""
    names = sorted(data["outlines"])
    head = "{\n" + f'  "_doc": {json.dumps(data.get("_doc", DOC), ensure_ascii=False)},\n  "outlines": {{'
    if not names:
        return head + "}\n}\n"
    lines = [f"    {json.dumps(n)}: {json.dumps(data['outlines'][n])}{',' if i < len(names) - 1 else ''}" for i, n in enumerate(names)]
    return head + "\n" + "\n".join(lines) + "\n  }\n}\n"


def save(updates, path=OUTLINES_FILE):
    """Merge {image name: rects} into the file (re-read first, so other entries are never lost)."""
    data = read_file(path)
    data["outlines"].update(updates)
    tmp = Path(str(path) + ".tmp")
    tmp.write_text(dumps(data))
    os.replace(tmp, path)


def usable(outlines):
    """Only well-formed outlines {image name: [[x0, y0, x1, y1], ...]} (fractions, x1 > x0, y1 > y0), so a hand-edited
    file cannot crash a build. Accepts the whole file dict or just its "outlines" part."""
    if isinstance(outlines, dict) and isinstance(outlines.get("outlines"), dict):
        outlines = outlines["outlines"]

    def ok(r):   # fractions of the image: 0 <= x0 < x1 <= 1 (bools are not numbers here)
        return (isinstance(r, (list, tuple)) and len(r) == 4
                and all(isinstance(v, (int, float)) and not isinstance(v, bool) and 0 <= v <= 1 for v in r)
                and r[2] > r[0] and r[3] > r[1])
    return {n: [list(r) for r in rs] for n, rs in (outlines or {}).items() if isinstance(rs, list) and rs and all(ok(r) for r in rs)}


def load():
    """The usable outlines of catalog/outlines.json ({} if missing)."""
    return usable(read_file()["outlines"])


def coverage(rects):
    """Share (0..1) of the image box the rectangles cover (they may overlap each other: counted once)."""
    xs = sorted({v for r in rects for v in (r[0], r[2])})
    ys = sorted({v for r in rects for v in (r[1], r[3])})
    area = 0.0
    for x0, x1 in zip(xs, xs[1:]):
        for y0, y1 in zip(ys, ys[1:]):
            if any(r[0] <= x0 and r[2] >= x1 and r[1] <= y0 and r[3] >= y1 for r in rects):
                area += (x1 - x0) * (y1 - y0)
    return area


# --- the CLI -------------------------------------------------------------------------------------
def wanted(project_names, extra_images, db):
    """{image name: (w_mm, h_mm)}: the images of the projects' layouts, of every catalog pedal / supply with a
    playground_title, and of `extra_images`; sizes from Pedal Playground's database (else the layout item's)."""
    by_image = {e["Image"]: e for e in db.values() if e.get("Image")}
    out = {}

    def add(name, entry=None, item=None):
        if name in out:
            return
        if entry is None:
            entry = by_image.get(name)
        if entry is not None:
            out[name] = (entry["Width"] * IN_MM, entry["Height"] * IN_MM)
        elif item is not None:
            out[name] = (item["w_mm"], item["h_mm"])
        else:
            print(f"  {name}: not in Pedal Playground's database, skipped", file=sys.stderr)

    for pdir in project_dirs(project_names or None):
        f = pdir / "playground_design.json"
        if f.exists():
            for it in design.parse_design(f):
                if it["kind"] == "pedal" and it.get("image"):
                    add(it["image"], item=it)
    pedals, supplies = load_catalog()
    for p in list(pedals.values()) + list(supplies.values()):
        entry = db.get(p.get("playground_title") or "")
        if entry and entry.get("Image"):
            add(entry["Image"], entry=entry)
    for name in extra_images:
        add(name)
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("projects", nargs="*", help="project folder names (default: all with a playground_design.json)")
    ap.add_argument("--image", action="append", default=[], metavar="NAME", help="also compute this image (file name)")
    ap.add_argument("--refresh", action="store_true", help="recompute entries that already exist")
    args = ap.parse_args()

    from PIL import Image
    have = read_file()["outlines"]
    every = wanted(args.projects, args.image, database("pedals.json"))
    todo = {n: s for n, s in every.items() if args.refresh or n not in usable(have)}   # malformed entries: recomputed
    new, failed = {}, []
    for name, (w, h) in sorted(todo.items()):
        try:
            with Image.open(fetch_image(name)) as im:
                alpha = im.convert("RGBA").getchannel("A")
        except (RuntimeError, OSError) as e:
            failed.append(name)
            print(f"  {name}: FAILED ({str(e).splitlines()[0]})")
            continue
        new[name] = outline_from_alpha(alpha, w, h)
        print(f"  {name}: {len(new[name])} rects, covers {coverage(new[name]) * 100:.0f}% of the box")
    if new:
        save(new)
    print(f"{len(new)} outline(s) written, {len(every) - len(todo)} kept, {len(failed)} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
