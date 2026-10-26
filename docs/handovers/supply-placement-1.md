# Handover: supply-placement phase 1: board holes as data, drawn in routing.svg

Branch `feat/supply-placement` (already checked out). Do not commit; the reviewer commits.

## Goal
The pedalboard's holes (slots / cutouts in the deck, where cables can later pass under the board) become data:
derived from Pedal Playground's board image, optionally edited per project, available as canvas rectangles in the
build's layout, and drawn in `routing.svg`. **Routing, lengths and findings stay exactly as today** (holes are not
used by the router yet; that is a later phase).

## Context (what you need, nothing else)
- Python 3.12, run everything with `uv run` from the repo root (never pip). Tests: `uv run pytest tests -q` (~283 pass
  today). Build: `uv run scripts/build.py` (validates all projects, rewrites README.md / routing.svg per project).
- Units are mm everywhere we compute/store/show. Images are never committed: they are fetched on demand into the
  git-ignored `.cache/images/` with `common.fetch_image(name)` (urllib, server side).
- Pattern to copy: pedal outlines. `scripts/outlines.py` turns a pedal PNG's alpha channel into rects that COVER the
  opaque pixels (`outline_from_alpha`, `_cells`, `_runs`, `read_file`, `dumps`, `save`, `usable`, `load`, `coverage`,
  CLI `wanted`/`main`) and writes `catalog/outlines.json` (`_doc` + one entry per line, 4 decimals, fractions 0..1 of
  the UNROTATED image, origin top-left). `design.outline_rects(item, outlines)` maps fractions to canvas mm rects with
  `design.jack_point` (rotation-aware: 0/90/180/270). Read `scripts/outlines.py` and `tests/test_outlines.py` first.
- The board in a parsed layout is the item with `kind == "pedalboard"`, e.g. for guitar-gig:
  `{'kind': 'pedalboard', 'title': 'Fender Professional (Medium)', 'rot': 0, 'image': 'fender-pro-medium.png',
  'w_mm': 609.6, 'h_mm': 331.7, 'left_mm': 15.8, 'top_mm': 22.0, ...}`. `jacks.layout_from_items(...)` returns the
  layout dict with `"board"` (that item), `"placed"`, `"obstacles"`, `"shapes"`, ...; `build.validate` puts it in
  `ctx["layout"]`. `svgdraw.render(ctx, names, ...)` draws routing.svg (`board(bx)` then the routing area, pedals, ...).
- Board images live at `https://pedalplayground.com/public/images/pedalboards/<image>` (NOT the `.../pedals/` path
  `common.IMAGE_URLS` uses today). They are RGBA; the holes are transparent:
  - `fender-pro-medium.png` (2400 x 1306 px): 15 rounded slots in 4 rows, a handle cutout at the back centre, and
    transparent strips along the back and front edges (the frame profile).
  - `rockboard-duo-21.png` (1600 x 483 px): 17 rounded slots in 3 rows (6 + 5 + 6).
  Projects: guitar-gig uses the Fender (has a `playground_design.json`); guitar-practice and bass use the Duo 2.1 but
  have no layout file yet, so the CLI must also accept `--image NAME` (and know these two images via the projects'
  layouts or explicitly).

## Tasks
1. `common.fetch_image(image_name, refresh=False, kind="pedals")`: `kind="pedalboards"` uses the pedalboards URL(s)
   (`https://pedalplayground.com/public/images/pedalboards/{}`, also try `.../app/images/pedalboards/{}` like the
   pedals list). Same cache dir. Existing callers unchanged.
2. `scripts/boards.py` (new, like outlines.py):
   - Pure `holes_from_alpha(alpha, w_mm, h_mm, ...)` -> list of rects (fractions). Holes = transparent regions
     (alpha <= 128) that do NOT touch the image border (regions connected to the border are the outline/profile).
     **Conservative INSIDE the hole**: every rect lies entirely in transparent pixels of one hole (never bigger than
     the hole). Work on a ~1 mm cell grid (a cell counts as hole only if ALL its pixels are transparent and it belongs
     to a border-disconnected region); merge cells into few rects (row runs merged vertically where they match, like
     outlines' approach). Ignore specks smaller than a small area (image noise, e.g. < 10 mm^2; a named constant).
     Each hole should end up covered well (aim >= 80 % of its area for rounded slots) with a handful of rects.
   - `catalog/boards.json`: `{"_doc": "...", "boards": {"<image name>": {"holes": [[x0, y0, x1, y1], ...],
     "hole_transit_mm": 15, "notes": "..."}}}`, one hole rect per line style like outlines.json (write a `dumps`).
     `hole_transit_mm` (extra cable length per pass through the deck, down or up) is NOT derived: the CLI writes 15
     for a new entry with a note "hole_transit_mm: unverified estimate (owner, 2026-10-26)" and KEEPS existing
     non-hole keys when it recomputes holes. `read_file`, `save`, `usable` (range-checked like outlines.usable),
     `load` (usable entries; {} if the file is missing).
   - CLI: `uv run scripts/boards.py [project...] [--image NAME ...] [--refresh]`: the board images of the projects'
     layouts plus `--image`; existing entries kept unless `--refresh`. Board size in mm: from the layout item when
     there is one, else Pedal Playground's database `common.database("pedalboards.json")` (cached in `.cache/`,
     keyed "Brand Name", entries with Width/Height in inches and Image; look up by Image). Print per image: number of holes, rects, coverage.
   - Run it for both images and commit-ready `catalog/boards.json` (fender-pro-medium.png and rockboard-duo-21.png).
     Sanity check the counts against the finding above (Fender: 15 slots + handle cutout = 16 holes; Duo: 17).
     If the counts differ, look at why (e.g. a slot touching the border) and report it; do not hand-edit the file.
3. Per-project edits: `projects/<name>/board.json` (optional; written later by a board editor, not by you):
   `{"boxes": [{"type": "hole" | "filled", "x0": .., "y0": .., "x1": .., "y1": ..}]}` in fractions of the board
   image. `boards.load_edits(project_dir)` -> list of valid boxes ([] if missing; invalid boxes ignored with a
   warning returned/collected, not a crash).
4. `design.board_holes(board_item, holes, edits)` (pure): the effective holes as canvas mm rects, rotation-aware
   (same fraction -> canvas mapping as `outline_rects`). Effective = derived holes, then each edit box in order:
   `filled` subtracts its area (rect difference: split the remaining rects), `hole` adds it (a later box wins where
   boxes overlap). Returns a list of axis-aligned rects (may be non-overlapping pieces).
5. Build: `layout["holes"]` = `design.board_holes(...)` for the layout's board (empty without a board or without data);
   loaded once per build like outlines (pass through as `jacks.layout_from_items` / `build.validate` already do for
   `outlines`; keep the existing signatures working with defaults). Nothing else reads it yet.
6. `svgdraw`: draw the holes right after the board (before the routing area and pedals): a darker fill (e.g. the
   board stroke colour at low opacity, class `hole`), plus a "Board hole" entry in the key (`key_entries` /
   `key_sample`). Keep the committed SVG outline-only style.
7. Tests (new `tests/test_boards.py`, hand-computed): synthetic alpha masks (a frame with an inner transparent
   rectangle = 1 hole; a transparent strip touching the border = no hole; two holes; a rounded/circular hole: every
   rect inside it, coverage reasonable; a speck ignored); `usable` rejects malformed data; `board_holes` with
   rotation 0 and 90, `filled` subtracting part of a hole, `hole` adding a box, order (hole then filled on the same
   area = closed); `load_edits` with a missing file and an invalid box; svgdraw draws a hole rect.

## Acceptance
- `uv run pytest tests -q` all pass (old + new).
- `uv run scripts/build.py` runs; `git diff projects/*/README.md` shows no change in routes, lengths or findings
  (README text may mention holes only if you add one sentence; keep it minimal). `projects/guitar-gig/routing.svg`
  changes only by the drawn holes and the key entry.
- `catalog/boards.json` has both boards. Report: hole counts, rects per board, coverage, anything odd.

## Do not touch
- `projects/*/playground_design.json`, `projects/*/project.json`, `catalog/jacks.json`, `catalog/footswitches.json`,
  `catalog/outlines.json`; the router (`routing.py` behaviour), `layout.py`, `power.py`.
- No new dependencies. Do not edit generated files by hand (README.md, *.svg, *.mmd, playground.json).
- Do not update CLAUDE.md / docs (the reviewer does).
