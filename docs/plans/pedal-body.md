# Plan: pedal bodies for the usable board area (`feat/pedal-body`)

## Owner decisions (2026-11-02)
- The usable board area (board.json `bounds`) must hold the pedal's BODY (its enclosure bottom), not its jacks. Side jacks
  overhanging the usable area, or even the board, are fine and part of the optimisation (more deck space). The DD-8 and the
  Sun Face are on the edge on purpose with overhanging jacks.
- The body comes from the pedal image (owner's method): per row of the alpha mask (alpha > 128) the first and last opaque
  x, per column the first and last opaque y; the body = the MEDIANS of these four. Jacks, screws (DD-8 bottom screw),
  knobs only cover a few rows / columns, so the median ignores them.
- Pedal against pedal keeps the Pedal Playground box (as today): only the bounds use the body.
- No extra tolerance: the existing `layout.board_margin_mm` (default 0) still shrinks the area.

## Measured (gig, cached images; mm from the box edge to the body)
Sun Face L4.9 R4.9; 3699 T3.6; Beano L5.2 R4.8 T1.4; PolyTune 3 L4.5 R4.3; Mini Ego / Ratsbane L3.7 R3.6; Pico Pitch Fork
L6.4 R6.4; Fulldrive 2 T1.9; Phase 95 L3.2 R3.1; Retrovibe L4.4 R5.7 T0.4; Red Muck / Monk L4.7 R4.7; Protein T3.1;
Analog Chorus L3.2 R3.0; Reticon L3.3 R3.6; Belle Epoch T3.0; DD-8 L3.3 R3.1 B5.0 (screw); Tumnus Deluxe R5.0 (unexplained:
check) T3.5. Every inset matches the jack sides.
Expected effect on the current gig layout: the Sun Face and the DD-8 are no longer outside; Belle Epoch, Tumnus (front 0.5) and
the Beano (right 0.2) still are.

## Design
1. **Data**: `scripts/outlines.py` computes `body` per image (fractions of the unrotated image) next to the outline rects,
   stored in catalog/outlines.json under a new top-level key `bodies` {image: [x0, y0, x1, y1]}. Missing = the box
   [0, 0, 1, 1] (today's behaviour). Entries without a body are filled on the next run without `--refresh`.
2. **Geometry**: `design.body_rect(item, bodies)` (canvas mm, all rotations like `outline_rects`); `lay["bodies"]` {item id: rect}.
3. **Bounds**: `jacks.outside_usable` (the build warning / `strict_bounds`), the layout model (`inside_usable`, `feasible_one`,
   `repair_start`, `free_distance`'s board term) test the body. Overlap between items keeps the box.
4. **Routing area**: a plug of a pedal at the edge may now reach past the grown usable area. Every plug footprint (head,
   barrel, cable run) counts as routing area, in the build's grid (`routing.build_grid`) and in the surrogate's area test, so
   its cable can start where the plug ends and come back onto the board.
5. **Search**: nothing extra: with the body as the limit, the search can already push edge pedals out to their bodies.
6. Tests, CLAUDE.md, then rebuild, run outlines, re-run the gig proposals.
