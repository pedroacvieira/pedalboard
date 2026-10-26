# Handover: pedal-outlines phase 1: outline data, layout shapes, drawing

Branch `feat/pedal-outlines` (checked out). Do not commit. Python 3.12, run everything with `uv run`
(`uv run pytest tests -q`, `uv run scripts/build.py`). Units: mm. Stdlib + Pillow only.

## Goal
Every pedal's real top-view shape (from the alpha channel of its Pedal Playground image) as a few rectangles,
committed as data, available on the parsed layout, and drawn in routing.svg. This phase does NOT change routing or
clearance yet (phase 2): routes, lengths and findings must stay identical.

## Decisions
- `catalog/outlines.json`, written ONLY by the new `scripts/outlines.py`; keyed by the Pedal Playground IMAGE file
  name (e.g. "mxr-m290.png"); value = list of rects [x0, y0, x1, y1] in fractions (0..1) of the UNROTATED image,
  origin top-left, 4 decimals. Format like `catalog/jacks.json` (a `_doc` string, then one entry per line, keys
  sorted: see `jacks.dumps` for the one-item-per-line style). No images are ever committed.
- The rects COVER every opaque pixel (alpha > 128): conservative, never smaller than the pedal.
- Missing outline: the item's bounding box is used (`design.footprint`).
- Pedal Playground's Width/Height include the protruding jacks; the image is not squeezed (verified 2026-10-23).

## Context
- `scripts/common.py`: `database("pedals.json")` -> {title: {Brand, Name, Width (in), Height (in), Image}};
  `fetch_image(name)` -> cached PNG path in `.cache/images/` (downloads if missing, raises RuntimeError);
  `load_catalog()`; `project_dirs()`; `IN_MM`.
- `scripts/design.py`: `parse_design` items have `image` (file name), `left_mm, top_mm, w_mm, h_mm` (unrotated box),
  `rot`; `footprint(item)`; `jack_point(item, fx, fy)` (fraction of the unrotated image -> canvas mm, rotation-aware).
- `scripts/jacks.py` `layout_from_items(...)` returns {"board", "placed", "obstacles", "inst_item"}; it is used by
  the build (`jacks.check`) and by `layout.Model`.
- `scripts/svgdraw.py` `pedal(item, name, ...)` draws the box; `render` draws `layout["obstacles"]`.
- `scripts/pedal_editor.py` has `alpha_mask(image, w_mm, h_mm, ...)`: look at it, reuse what fits (move shared pure
  code to a place both can import if needed; keep the editor working).

## Tasks
1. Pure decomposition `outline_from_alpha(alpha, w_mm, h_mm, cell_mm=1.0, gap_mm=2.0, tol_mm=1.0, max_rects=16)`
   (in `scripts/outlines.py`, importable): `alpha` = a Pillow "L" image (or 2D list). Cells of ~cell_mm (a cell is
   occupied if ANY of its pixels has alpha > 128). Per cell row: occupied runs; runs closer than gap_mm are joined.
   Consecutive rows with the same number of runs whose ends differ by <= tol_mm form a band; each band gives one rect
   per run = the union span of its rows. While more than `max_rects` rects: merge the two adjacent bands whose merge
   adds the least area (same run count, else union into one run). Return rects in fractions (4 decimals), rounded
   OUTWARD so coverage stays conservative. Empty image -> [[0, 0, 1, 1]].
2. CLI `uv run scripts/outlines.py [project ...] [--image NAME ...] [--refresh]`: collects the image names of every
   item in the given projects' `playground_design.json` (default: all projects that have one) plus, for each catalog
   pedal/supply with a `playground_title`, its DB image; fetches each image (`common.fetch_image`), computes the
   outline with the DB Width/Height (inches -> mm), and writes `catalog/outlines.json` (re-read first; only the
   computed keys change; `--refresh` recomputes existing ones, default skips them). Prints one line per image (rect
   count, covered area % of the box). Images that fail are reported and skipped.
3. `outlines.read_file()` / `usable()` like jacks.py (missing file -> {}), and `design.outline_rects(item, outlines)`:
   canvas rects (x0, y0, x1, y1) of the item's outline via `jack_point` for two opposite corners (min/max: correct
   for 0/90/180/270), fallback `[footprint(item)]` when the item has no image or no outline.
4. `jacks.layout_from_items(..., outlines=None)`: adds `"shapes"`: {item id: [canvas rects]} for every obstacle and
   placed item (fallback box). The build passes the outlines (read once in `build.main`, passed down like
   `jacks_data` / `footswitch_data`, default: read the file); `layout.Model` passes them too (it calls
   `layout_from_items`). Nothing uses "shapes" yet except the drawing.
5. svgdraw: draw each pedal as its outline (filled, same style as today's box) with the bounding box as a faint
   dashed rectangle; labels and everything else unchanged. Key line: "dashed: Pedal Playground box".
6. Run the CLI for all projects and commit-ready data: `catalog/outlines.json` must cover every image used in the
   three projects' layouts and every catalog pedal with a DB image.
7. Tests (new `tests/test_outlines.py`): synthetic masks made with Pillow: a full rectangle -> one rect [0,0,1,1];
   a body with a jack bump on one side -> 2-3 rects covering both; rounded corners -> covered (every opaque pixel
   inside some rect); two separate top jacks -> two runs in that band; max_rects respected; coverage is conservative
   for random blobs (check every opaque pixel). `outline_rects` for rot 0/90/180/270 on a hand-computed item, and the
   fallback. `outlines.json` format round-trip (one entry per line, sorted).
8. Run all tests and the build: `routes, lengths and findings unchanged` (diff the generated READMEs: only the
   routing.svg may change). Render `projects/guitar-gig/routing.svg` with headless Chrome
   (`google-chrome --headless=new --screenshot=OUT.png --window-size=2412,1480 file://...`) and check the outlines
   sit on the pedals. Report: rect counts per image, the box vs outline area for the gig pedals, file size.

## Constraints / do not touch
- No routing/clearance/layout-score changes (phase 2). Do not change layout.py logic beyond passing outlines through.
- Keep the code style of the repo (compact, docstrings). Do not commit. Do not edit CLAUDE.md or docs/TODO.md.

## Acceptance
- All tests pass (+ new ones); `catalog/outlines.json` complete for the projects; build output identical except
  routing.svg; short report as in task 8, plus doubts.
