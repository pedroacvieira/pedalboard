# Plan: `feat/board-pieces`: a board made of several pieces

Owner (2026-11-09): the bass layout uses a D'Addario XPND 1 and its extension, two `pedalboard` items side by side
(XPND 1 355.6 x 153.2 mm, extension 273.1 x 139.7 mm; in the owner's layout they overlap ~22 mm in x and their backs
differ by ~3 mm). Today `jacks.layout_from_items` takes the FIRST pedalboard item as the board and ignores the rest, so
the pedals on the other piece are "outside the usable area" and cables cannot reach them.

## Model
- `layout["pieces"]`: every pedalboard item of the layout, in layout order. A layout with one piece behaves exactly as
  today (tests must not change).
- Footprint: `layout["board"]` stays (the first piece, for code that needs an item); new `layout["board_rect"]` = the
  bounding box of all pieces and `layout["board_rects"]` = the pieces' footprints. Every `design.footprint(layout["board"])`
  that means "the board area" (routing.py ~1917, svgdraw.py 591 / 665, design.has_bounds, layout.py 239) uses these.
- Usable area (where pedal BODIES must lie): `layout["usable_rects"]` = per piece its usable rect (its bounds, else its
  footprint); a body is inside when it lies inside the UNION of these rects (it may straddle the joint between two pieces:
  decision D1). `layout["usable"]` keeps the bounding box for drawings. `jacks.outside_usable` and the layout model
  (`Model.body` feasibility, `repair_start`, `free_distance`'s board term) test the union (rect minus union of rects =
  empty; distance outside = the least move that brings it inside one piece or the union).
- Routing area (top grid): the cells within `edge_margin_mm` of ANY piece (not the bounding box), plus the plug zones;
  nothing in front of the lowest pedals as today (`front_limit` on the bounding box). Surrogate `area_box`: the bounding box
  (an estimate; finalists are checked by the build).
- Under layer: the union of the piece footprints (cells outside every piece are walls); cables may cross between pieces
  under the deck (D2).
- Holes: per piece from `catalog/boards.json` (by that piece's image) mapped with that piece's item, concatenated.
  `scripts/boards.py` derives the holes of EVERY pedalboard image of a project (not only the first).
- Owner edits (`board.json`): today one set of boxes / edges / bounds for the board image. New optional key `pieces`
  {image name: {boxes, edges, bounds}}; the existing top-level keys keep meaning the FIRST piece (D3). The board editor
  gets a piece selector (or `--piece IMAGE`); until then edits for other pieces by hand.
- Edge segments: per piece (its own sides); a segment on a side that touches another piece is pointless and allowed.
- Pictures: every piece drawn; bounds per piece.
- `boards.json` entries for the XPND images: `uv run pb boards bass` after the change.

## Decisions
Owner (2026-11-09): "the two parts slide on each other: sum them and consider them ONE pedalboard for the evaluation"
(composed boards in general, not only the XPND). So:
- D1: the deck is the union of the pieces: pedals may straddle a joint; overlapping pieces simply overlap. Decided.
- D2: under the board, cables pass freely between pieces (one under layer = the union). Decided.
- D3: `board.json`: `pieces` per image; the old top-level keys = the first piece. Default (not asked).

## Tests
One-piece layouts unchanged (whole suite). New hand-computed cases: two abutting pieces: a body across the joint is
inside; a body in the notch of an L-shape is outside by the right mm; the grid has no cells beyond margin + pieces;
holes of both pieces present; under layer walls outside the pieces; surrogate and build agree on outside / feasibility.

## Not in scope
Pieces at different heights (no 3D), a gap between pieces that cables must bridge (treated as routing area only within
the margin), rotation of single pieces beyond 0/90/180/270.
