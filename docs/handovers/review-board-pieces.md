# Handover: code review of feat/board-pieces

## Goal
Review commit ce10d10 on branch `feat/board-pieces` (`git diff 9942b02 ce10d10`) for correctness bugs. Report
findings only; do not edit files.

## What the change must do (owner, 2026-11-09)
A Pedal Playground layout may contain several `pedalboard` items (D'Addario XPND 1 + its extension, which slide on each
other). They are SUMMED and evaluated as ONE board: the deck = union of the piece footprints (pieces may overlap; a pedal
body may straddle a joint and must lie inside the union of the per-piece usable rects); under the deck cables pass freely
between pieces; top routing area = cells within `edge_margin_mm` of any piece; holes / edge segments per piece from
`catalog/boards.json` + `board.json` (`pieces` {image: {boxes, bounds}}, top-level keys = first piece). With ONE piece
everything must be exactly as before (generated files unchanged).

## Check
- One-piece paths really unchanged (grid extents, `outside_usable` numbers, layout model feasibility, drawings).
- `design.inside_union` / `outside_union` / `slide_room` geometry: correct for overlapping, abutting, L-shaped unions;
  the "least shift" claim; tolerance handling at joints (a body exactly across two abutting rects must be inside).
- Build vs layout surrogate agreement (`jacks.outside_usable` vs `layout.Model.inside_usable` / `feasible_one` /
  `repair_start` / `free_distance`).
- Under grid and edge links: a joint between pieces must not count as a board edge; under cells outside every piece walls.
- `board_editor` save keeps `pieces`.
- Tests in `tests/test_board_pieces.py`: do they test what they claim (hand-computed values)?

## Deliverable
A short list of real bugs (file:line, concrete failure scenario), most severe first. No style nits.
