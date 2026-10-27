# Plan: `feat/supply-placement`: supplies on or under the board, board holes, cables through the holes

Status: implemented (2026-10-26, phases 1-6 + code review); owner decisions in two rounds. Branch
`feat/supply-placement` from `main` (routing-view and pedal-outlines are merged and pushed). It also absorbs the
TODO item "Later: patch cables under the board" and part of feature 2 (power cables stay under the board).

## Goal
1. The board's **holes** as data: derived from the Pedal Playground board image, editable per project in a new
   **board editor**.
2. Per supply instance `placement`: `under` (today, every supply) or `on_board`, instead of the single global
   `jacks.supplies_layer`.
3. **Cables through the holes**: signal cables may go down a hole, run under the board and come up through another
   hole (fewer cables on top, shorter paths); power cables stay under the board as much as possible and come up
   through the hole nearest the pedal's power jack.

## Owner decisions (2026-10-26)
1. **Holes are derived from the board image** (transparent areas inside the board) and kept as a mask per board image.
2. **Board editor**, similar to the pedal editor and kept simple: the owner adds boxes of type `hole` or `filled` on
   the board image. The saved boxes override the derived mask **for that project** (a `filled` box closes a derived
   hole, a `hole` box opens one).
3. **No under-board fit check** (supply height, space under the deck): assume the supply fits. Possibly a later branch.
4. ~~The entire hole counts as usable~~ (replaced by round-2 decision 9): no minimum size, but the parts of a hole a
   pedal (or an on-board supply) covers are not usable.
5. **Holes are used to reduce the cables on top of the board and to give signal cables shorter paths.**
6. **Power cables try to always stay under the board** and come up only where they must (at their pedal).
7. **A supply on top of the board is an obstacle like a pedal** (its outline; its output ports get the DC plug
   clearance). Holes stay usable for routing next to it.

## Owner decisions, round 2 (2026-10-26)
8. **Hole costs**: `hole_transit_mm` 15 per pass (down or up) and `hole_penalty` 15 per pass (search cost, mm
   equivalent); both unverified estimates. The transit depends on the board: default per board image in
   `catalog/boards.json` (`hole_transit_mm`, Fender Pro Medium thin deck: 15; Duo 2.1: 15, unverified), project
   override `cables.hole_transit_mm`. The under layer costs 0.9x per mm (equal routes prefer under, decision 5).
9. **A pedal above a hole blocks that part of the hole**: a cable changes layer only in a hole cell that is free on the
   top layer (outside every pedal / on-board supply outline grown by the cable radius, as the router's walls). The
   nearest-hole power estimate uses the same usable hole cells.
10. **Power estimate**: `power.assign` and the layout surrogate use a nearest-hole estimate (supply port -> under
    the board -> the usable hole nearest the pedal's power jack -> up -> the jack on top), not the right-angle one.
    The surrogate's power term (weight `layout.weights.power`) is the DC-length term.
11. **On-board supplies are movable in the layout search** (like a chain pedal: moves, swaps with pedals of similar
    size, rotations; never overhanging, no overlap); under-board supplies are not moved.
12. **Execution**: one Sonnet agent per phase (handover each), commit per phase on `feat/supply-placement`, code
    review at the end, merge after the owner's OK.

## Owner decisions, round 3 (2026-10-26)
13. **No edge modes**: `power_routing.edges` (front/left/right/back) and `avoid_penalty` are removed. Power cables go
    from under to over the board ONLY through the holes and through **edge boxes** the owner draws in the board editor
    (type `edge` in board.json, may lie outside the board image): a cable may come round the board edge only where the
    border is inside an edge box. No edge boxes = holes only. Neither holes nor edge boxes = an under-board supply is an
    error (no power cable could come up). Handover `docs/handovers/supply-placement-edges.md`.
    Edge crossings are LINES, not boxes (owner): board.json `{"type": "edge", "side": left|right|back|front, "from", "to"}`
    (fractions along that side); the editor projects a hand-drawn line onto the nearest board side.
    Signal cables may use edge boxes too (round the edge under the board and back up), not only power cables.
    Front of the board: project toggle `cables.route_in_front` (default false: nothing in front of the lowest pedals;
    true: the routing area reaches the board front and front edge boxes work). guitar-gig: false.
14. The Reticon and the MXR Analog Chorus swapped in the gig chain (chorus first): signal 2401 -> 2322 mm.

## Starting point (code, 2026-10-26)
- `jacks.layout_from_items(...)` maps supply instances (`project.power.supplies[]`, ids `psu1`, ...) to Pedal
  Playground items by `playground_title` (`inst_item` {instance id: item}; `jacks.supply_items` can pin one). The
  owner draws the supplies in the Pedal Playground layout where they hang under the board (guitar-gig: two Ojai R30
  items, 130 x 58 mm, at about (172, 58) and (311, 59) mm). With `jacks.supplies_layer: "under"` (all three
  projects) supplies are not obstacles; `"on_board"` makes every supply an obstacle (`jacks.check` ~line 326).
- Signal routing (`routing.py`): one layer on top of the board. 2 mm grid; pedals (their outlines, `layout["shapes"]`)
  are obstacles grown by the cable radius; negotiated congestion (`route_all`: `max_stack` 2 per cell,
  `max_over_plug` 2); then smoothing (`smooth`) and drawing lanes (`lanes`). `min_mm` = plug measure lengths +
  smoothed polyline.
- Power cables: modelled (tips, polarity, `under_board` = the global layer), not routed. Min length = a right-angle
  estimate from the supply port point to the pedal's power-jack point (`power.measure_points`). `power.assign`
  (layout proposals) picks outputs and daisy chains by those estimates. Supply ports = the supply's `power_out` jacks
  in `catalog/jacks.json`.
- The board item: `layout["board"]` (e.g. "Fender Professional (Medium)", image `fender-pro-medium.png`,
  610 x 332 mm). `project.json` `board` has brand, model, size and price only.
- Pattern to copy: pedal outlines (`catalog/outlines.json` written only by `scripts/outlines.py` from the image alpha;
  `design.outline_rects`; `layout["shapes"]`). The pedal editor (`scripts/pedal_editor.py`, Tkinter, pure helpers at
  module level, tests in `tests/test_pedal_editor.py`) is the pattern for the board editor.
- Board images: `https://pedalplayground.com/public/images/pedalboards/<image>` (not `.../pedals/`);
  `common.fetch_image` only knows the pedals path today.

## Finding: the board images show the holes (2026-10-26)
Pedal Playground's board PNGs are RGBA and the holes are transparent:
- `fender-pro-medium.png` (2400 x 1306 px): 15 rounded slots in 4 rows (2 + 4 + 3 + 4 plus short end slots), a
  handle cutout at the back centre, transparent strips along the back and front edges (the frame's profile).
- `rockboard-duo-21.png` (1600 x 483 px): 17 rounded slots in 3 rows (6 + 5 + 6).
Holes = transparent regions INSIDE the board (not connected to the image border); regions touching the border are
the outline / profile, not holes. Not yet verified against the real boards (maker pictures): the board editor is the
owner's tool to correct them.

## Data model
- `catalog/boards.json` (derived, committed, written only by `scripts/boards.py`): per board IMAGE name
  `{"holes": [[x0, y0, x1, y1], ...]}`, rects in fractions of the unrotated image that lie INSIDE the transparent
  hole (conservative: never bigger than the hole). Same file style as outlines.json (`_doc`, one entry per line).
- `projects/<name>/board.json` (new, written only by `scripts/board_editor.py`): `{"boxes": [{"type": "hole" |
  "filled", "x0", "y0", "x1", "y1"}]}` in fractions of the board image. Effective holes of a project = derived holes
  minus `filled` boxes plus `hole` boxes (in the editor's order: a later box wins where boxes overlap). Missing
  file = derived holes only.
- `project.json`: `power.supplies[].placement` `under` | `on_board` (default from `jacks.supplies_layer`, which
  stays readable). Routing settings in `cables`: `under_board` (default true: signal cables may use holes),
  `hole_transit_mm` (extra length per pass through the deck, down or up: the deck thickness plus a bend; default
  from the board data or an estimate, marked unverified), `hole_penalty` (search cost per pass, so a cable only goes
  under when it saves enough), `max_stack_under` (cables per cell under the board, default like `max_stack`).
- No per-supply height, no `under_clearance_mm` (decision 3).

## Routing model (phases 3-4)
- Two layers on the same 2 mm grid: **top** (today's grid: pedal outlines and on-board supplies are obstacles) and
  **under** (the board's underside: area = the board footprint; under-board supplies are obstacles there, since a
  cable runs around them; nothing else is known about rails/frame).
- A cable changes layer only in a **hole cell** (a cell whose centre lies inside an effective hole AND that is free on
  the top layer: decision 9), at a cost (`hole_penalty` in the search, `hole_transit_mm` in the length).
- Signal cables: start and end on top (plug exits); A* over (cell, layer) states may go down and up through holes when
  that is cheaper (shorter, and fewer cables on top: the top layer's congestion cost counts, the under layer is
  cheaper per mm by a small factor, so equal routes prefer under). Smoothing per layer stretch (the hole points stay
  corners). Stacking limits per layer. Lanes on top only.
- Power cables (decision 6): start at the supply port. Under-board supply: the cable starts under the board; on-board
  supply: on top. They end at the pedal's power jack on top. Under the board they are cheap, on top expensive, so
  they come up through the hole nearest the jack and run the shortest way on top. If no hole is reachable they go
  over an allowed board edge (`board_edges`: front forbidden, sides avoid, back allowed, the owner's rule from
  feature 2) or, last resort, run on top (finding). Daisy chains: each hop (supply -> first pedal, pedal -> next) is
  one routed cable for now; forked vs serial chains stay in feature 2.
- Power and patch cables do not count against each other's stacking (owner, 2026-10-23); power cables have their own
  `max_stack` on each layer.
- `min_mm` = plug measures + the polyline on top + the polyline under + `hole_transit_mm` per pass. For power cables
  this replaces the right-angle estimate (also in `power.assign`? see "Open").

## Phases (a handover each, `docs/handovers/supply-placement-<n>.md`, Sonnet agents)
1. **Board holes**: `scripts/boards.py` (decomposition of the transparent, border-disconnected regions into rects:
   reuse the ideas of `outlines.outline_from_alpha`, but conservative INSIDE the hole; CLI like outlines.py:
   `uv run scripts/boards.py [project...] [--image NAME] [--refresh]`; `common.fetch_image` learns the pedalboards
   path), `catalog/boards.json` for both boards, `design.board_holes(board_item, boards, edits)` (effective holes
   as canvas rects, rotation-aware), holes drawn in routing.svg, tests on synthetic masks. Results unchanged.
2. **Board editor**: `scripts/board_editor.py <project>` (Tkinter, like pedal_editor: the board image with the
   derived holes overlaid; drag to add a box, a key toggles hole / filled, select + Delete, Ctrl+S saves
   `projects/<name>/board.json`; pure helpers at module level and tested; `--list`?). Build reads the edits.
3. **Supply placement**: per-instance `placement` (default from `supplies_layer`); on-board supplies = obstacles with
   outlines + DC plug clearance on their ports (like a pedal's power jack); `under_board` per power cable from its
   supply; README supplies section; today's projects unchanged.
4. **Two-layer router for signal cables**: under layer, hole transitions, costs and settings above, smoothing and
   lengths, README / routing.svg (under-board stretches dashed, hole passes marked), findings. Report the guitar-gig
   before/after (lengths, cables on top, stacked corridors).
5. **Power cables routed**: under first, up at the nearest usable hole, edges as fallback (`power_routing.edges`,
   default front forbidden, sides avoid, back allowed); lengths replace the estimate in the README; drawn in
   routing.svg (power legs distinct); `power.assign` and the layout surrogate use the nearest-hole estimate
   (decision 10).
6. **Layout search with on-board supplies** (decision 11): on-board supplies are movable candidates in `layout.py`
   (moves, swaps, rotations, overlap and board limits like pedals; their DC plug clearance in the surrogate); the
   power term follows them. Tested on a synthetic project (no real project has an on-board supply yet).

## Open (to confirm before the phase that needs it)
- (Answered, round 2) Phase 4: values of `hole_transit_mm` (Fender deck thickness, Duo 2.1 rail profile) and `hole_penalty`; whether the
  under layer should prefer under-board routes (decision 5 suggests yes).
- (Answered, round 2: nearest-hole estimate in both) Phase 5: does the layout search (surrogate) and `power.assign` use the hole-aware power lengths (needs a cheap
  estimate: nearest hole to each jack), or keep the estimate? Recommendation: nearest-hole estimate in both.
- Feature 2 after this: what remains is forked vs serial daisy chains, power.svg, edge settings refinements.
- The TODO's "plug pointing down into a hole" and "U-turn plugs" stay later.

## Acceptance
- `uv run pytest tests -q` passes (+ new tests); `uv run scripts/build.py` runs. Phases 1-3 leave today's routes,
  lengths and findings unchanged (only holes drawn, supplies section). Phases 4-5 change them on purpose: report
  before/after per cable for guitar-gig.
- CLAUDE.md (layout: boards.json, board.json, board_editor.py; conventions: holes, placement, two-layer routing) and
  docs/TODO.md updated. Code review, then merge into main.
