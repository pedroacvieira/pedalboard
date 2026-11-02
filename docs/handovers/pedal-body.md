# Handover: the usable board area holds pedal BODIES, not their jacks (`feat/pedal-body`)

## Goal
Today a pedal must lie inside the usable board area (`layout["usable"]`, from board.json `bounds`) with its whole Pedal
Playground box, which includes the protruding jacks. The owner's rule: only the pedal's BODY (enclosure) must be inside; side
jacks may overhang the usable area and the board (that frees deck space). Derive each pedal's body from its image, use it for
every bounds test, and let plugs that overhang still be routed.

## Where you work
`/home/pvieira/projects/pedalboard`, branch `feat/pedal-body` (checked out, clean). Do NOT commit. `uv run pytest tests -q`
(~670 tests, ~95 s), `uv run scripts/build.py`, never `pip install`. Units: mm everywhere.

## Decisions (owner, 2026-11-02)
- Body from the image's alpha mask (alpha > 128, `outlines.ALPHA_MIN`): over the rows that have an opaque pixel, the MEDIAN
  first opaque x and the MEDIAN last opaque x; over the columns that have one, the MEDIAN first and last opaque y. Body =
  those four, as fractions (0..1) of the unrotated image, 4 decimals. (Jacks, screws, knobs cover few rows / columns: the
  median ignores them, e.g. the DD-8's bottom screw.)
- Pedal against pedal overlap (and `min_gap_mm`) keeps the Pedal Playground box: ONLY bounds tests use the body.
- `layout.board_margin_mm` (default 0) still shrinks the usable area; no other tolerance.
- Under-board supplies are still never bounds-checked. On-board supplies: body = their image's body like a pedal.
- No body data = the box (today's behaviour, so projects without outlines are unchanged).

## Do
1. **scripts/outlines.py**: `body_from_alpha(alpha)` (pure, works on an image or a 2D list like `outline_from_alpha`) ->
   [x0, y0, x1, y1] fractions. Store in catalog/outlines.json under a new top-level key `"bodies"` {image name: [x0, y0, x1, y1]}
   (one image per line, sorted, like "outlines"; keep `_doc` accurate). `main()` also computes the body of every wanted image
   that has none, without `--refresh` (the images are cached in `.cache/images/`); `--refresh` recomputes both. A loader for
   well-formed bodies (like `usable`/`load`). Run it so the catalog gets the bodies.
   Sanity values from a prototype (mm from the box edge, gig): DD-8 (boss-dd-8 image) L3.3 R3.1 B5.0; Sun Face L4.9 R4.9;
   Pico Pitch Fork L6.4 R6.4; 3699 top 3.6; Tumnus Deluxe R5.0 T3.5.
2. **scripts/design.py**: `body_rect(item, bodies)` -> canvas (x0, y0, x1, y1), corners through `jack_point` exactly like
   `outline_rects` (all rotations); without data = `footprint(item)`.
3. **scripts/jacks.py** `layout_from_items`: add `lay["bodies"]` {item id: canvas rect} for every obstacle / placed item /
   on-board supply (load the bodies where it loads outlines; callers that pass `outlines=` must be able to pass bodies too,
   follow how `outlines` / `outline_data` is threaded through `build.validate` and `propose_layout`). `outside_usable` tests
   the body instead of `design.footprint(it)` (message unchanged: "is outside the usable board area by N mm (side)").
4. **scripts/layout.py** (the model): keep `footprint(st, n)` (the box) for overlaps; add `body(st, n)` from per (pedal,
   rotation) offsets of the body relative to the centre (precompute in `_geom` like `half`; asymmetric!). Use the body in
   `inside_usable` callers: `feasible_one`, `repair_start` (its clamp `lo_x..hi_y` must use the body's offsets, not the box
   half sizes), `free_distance` (the board-edge term only; other items stay boxes), and anywhere else the usable area is tested
   against an item (grep `inside_usable`, `usable`, `board_margin_mm`). Keep docstrings honest.
5. **Routing area** (scripts/routing.py): the top grid blocks cells outside the usable area grown by `edge_margin_mm`
   (`area_limits`, `build_grid`). An edge pedal's plug can now reach past it, so its cable would have nowhere to start. Make
   every used plug's footprint (head + barrel + cable run, every option the router may pick, grown by the cable radius) part
   of the routing area: those cells are not area walls (pedals still block as usual). Do the same in the layout surrogate,
   which tests a plug's exit against `routing.area_box` (layout.py ~line 819 and the plug option feasibility): an exit inside
   its own plug's footprint zone counts as inside. Signal and power plugs alike. Keep the edge-segment strips as they are.
6. **Tests** (new `tests/test_pedal_body.py` + adapt): the median ignores a jack bump and a screw (hand-made masks); a body
   rect for 0/90/270; a pedal whose box is past the bound but whose body is inside: no build warning, feasible in the model,
   not moved by `repair_start`; one whose body is past: warned, pushed the least distance (body-based) inside; an overhanging
   side jack still gets its cable routed (no unrouted cable, no new routing finding). Tests that depend on the gig use the
   frozen fixture `tests/fixtures/guitar-gig` (`conftest.gig_copy` / `GIG_FIXTURE`). If an existing expected value changes
   BECAUSE the body replaced the box, update it and list it in the report; never loosen an assertion for another reason.
7. **Docs**: CLAUDE.md: the `catalog/outlines.json` line (bodies), the `bounds` line in `board.json` and the layout-proposal
   paragraph ("never outside the usable board area" -> by the body), the "Pedal outlines" convention (bounds use the body,
   overlap the box). docs/TODO.md: tick the item if one exists, add "Tumnus Deluxe body: 5 mm right inset unexplained (check
   the image)".

## Acceptance
- `uv run pytest tests -q` green; `uv run scripts/build.py` exits 0.
- On the live gig: the Sun Face and the DD-8 are no longer reported outside; Belle Epoch, Tumnus (front 0.5 mm) and the Beano
  (right 0.2 mm) still are; no new routing / unrouted-cable findings versus before your change (diff the build output).
- `uv run scripts/propose_layout.py guitar-gig --max-change fix --seed 1` runs (report its result table briefly).
- **Re-check the fix-mode collision** (docs/TODO.md section 2, "Fix-mode proposals keep one plug collision"): before the
  bodies, all `--max-change fix` proposals kept the owner's collision belle_epoch.in vs the Reticon's plugs. With the bodies,
  run fix mode with seeds 1, 2, 3 and `--max-change rearrange --seed 42`; per run report the collisions, blocked plugs, signal /
  DC mm and crowding of each proposal. Update that TODO item with the result (gone: tick it; still there: say which plugs and
  the numbers). Do NOT change the search to fix it: report only. Note: the live gig layout still contains the parked MXR
  Carbon Copy far outside the board (the owner removes it later); if it makes `propose_layout.py` stop, say so and do not
  edit the layout.

## Do not touch
`projects/*/playground_design.json`, `projects/*/board.json`, `catalog/jacks.json`, `catalog/footswitches.json`, the
fixture's files (unless a test genuinely needs a body there: say so). No new dependencies.

## Report back
Files changed, where the body is used, expected values you changed and why, the gig build diff (bounds + routing lines), the
proposal run's table, anything you were unsure about.
