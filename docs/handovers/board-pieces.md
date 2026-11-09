# Handover: `feat/board-pieces` (a pedalboard composed of several pieces)

Work on branch `feat/board-pieces` (create it from `main`). Commit there when done (message ends with the line
`Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`); do NOT merge or push.

## Goal
A Pedal Playground layout may contain several `pedalboard` items (the owner's bass board: a D'Addario XPND 1 and its
extension, which slide on each other). Owner decision: the pieces are SUMMED and evaluated as ONE pedalboard: the deck is
the union of the piece footprints (pieces may overlap; a pedal may straddle a joint), and under the deck the cables pass
freely between pieces. With ONE piece everything must behave exactly as today (the whole test suite unchanged).

Today `jacks.layout_from_items` (scripts/jacks.py ~280-295) takes `boards[0]` and ignores the other pieces.

## Required behaviour
1. `jacks.layout_from_items` returns, besides today's keys: `pieces` (all pedalboard items, layout order), `board_rects`
   (their `design.footprint`), `board_rect` (bounding box of `board_rects`), `usable_rects` (per piece its usable rect:
   `design.board_bounds(piece, bounds_of_that_piece)`). `board` stays the first piece; `usable` becomes the bounding box of
   `usable_rects` (for drawings). `holes` = concatenation of each piece's holes (`design.board_holes(piece,
   board_data[piece image].holes, edits_of_that_piece)`), `edge_segments` likewise. `hole_transit_mm` / `edge_transit_mm`:
   the first piece's entry that has one.
2. Owner edits per piece: `projects/<p>/board.json` may have `"pieces": {"<image name>": {"boxes": [...], "bounds": {...}}}`
   (same item formats as the top-level keys, edge items inside `boxes` as today); the top-level `boxes` / `bounds` keep
   meaning the FIRST piece. Read it in `boards.load_edits` / `boards.load_bounds` (or a new loader) without breaking callers;
   find the callers with `grep -n "load_edits\|load_bounds" scripts/*.py`. Validation of unknown image names: a build warning.
3. Bounds test (pedal BODY inside the usable area) against the UNION of `usable_rects`: `jacks.outside_usable` (report the
   least distance that brings the body inside the union; with one rect identical to today) and the layout model
   (`scripts/layout.py`: `Model.body` / `feasible_one` / `repair_start` / `free_distance` board term, wherever `usable` or
   `self.board` is used as the allowed area). Write the geometry once (e.g. `design.inside_union(rect, rects)` and
   `design.outside_union(rect, rects)` -> (side, mm)) with hand-computed unit tests.
4. Every place that uses `design.footprint(layout["board"])` as "the board area" uses `layout["board_rect"]` instead:
   `grep -n 'footprint(layout\["board"\])\|footprint(lay\["board"\])\|lay\["board"\]\|layout\["board"\]' scripts/*.py`
   (routing.py route_project ~1917, svgdraw.py ~591 / ~665, design.has_bounds ~233, layout.py ~237-239). `has_bounds`:
   true when any piece's usable rect differs from its footprint.
5. Top routing grid (`routing.build_grid`, `area_rect`): extent from `board_rect`; cells that are farther than
   `edge_margin_mm` from EVERY piece are walls (pass `board_rects` in; with one piece the grid must be identical to
   today's). The plug zones keep opening cells as today. `front_limit` uses `board_rect`.
6. Under layer (`routing.Under` / wherever the under grid is built from the board footprint): cells outside every piece are
   walls (one piece = today).
7. Power routing uses the same grids/rects (check `route_power` and `power.Crossings` / `power.estimate_setup` for the
   board footprint).
8. `scripts/boards.py` (`~380`): derive holes for EVERY pedalboard image of a project's layout, not only the first.
9. Drawings (`svgdraw.render` / `render_power`): draw every piece (outline; the image too in `--images` mode where the
   board image is drawn today) and the usable rect of every piece.
10. `scripts/board_editor.py`: out of scope (it keeps editing the first piece). Mention the limitation in its --help text.

## Tests (pytest; `uv run pytest tests -q`, ~250 s; run the touched test files first)
- Whole suite passes unchanged (one-piece layouts).
- New: two abutting pieces (hand-computed): a body across the joint is inside; a body in the notch of an L-shaped union is
  outside by the right mm and side; the top grid has no free cell beyond margin of the union; holes of both pieces are
  present; under-layer walls outside the pieces; the layout model's feasibility agrees with `jacks.outside_usable`.
- Build all: `uv run pb build` must not crash (the bass project will still have data warnings).

## Docs
Update `CLAUDE.md` (Layout: board.json `pieces`; conventions: composed boards) in the same terse style.

## Do not touch
`catalog/pedals.json`, `catalog/jacks.json`, `catalog/footswitches.json`, any `projects/*/playground_design.json`,
`projects/*/project.json`. Do not run `fetch_playground.py`.

## Deliverable
Branch with one or more commits, test results (pass counts), a list of the touched functions, and anything left open.
