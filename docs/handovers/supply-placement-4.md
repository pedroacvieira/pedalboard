# Handover: supply-placement phase 4: two-layer router for signal cables (under the board through holes)

Branch `feat/supply-placement` (checked out; phases 1-3 committed). Do not commit; the reviewer commits.

## Goal
Signal (patch) cables may go DOWN through a board hole, run under the board and come UP through another hole, when
that is cheaper: shorter, or out of a crowded corridor on top. Lengths, findings, routing.svg and the README follow.
This changes routes on purpose; report the guitar-gig before/after per cable.

## Owner decisions (copy, do not change)
- Holes come from `layout["holes"]` (phase 1: effective holes as canvas mm rects; `design.board_holes`).
- A cable changes layer only in a **hole cell**: a grid cell whose centre lies inside an effective hole AND that is
  free on the top layer (not a top-layer wall: pedals / on-board supplies grown by the cable radius) AND free on the
  under layer. So the part of a hole a pedal covers is NOT usable (owner, 2026-10-26).
- Costs: `hole_transit_mm` = extra cable length per pass through the deck (down or up); default from the board data
  (`catalog/boards.json` entry of the board image: `hole_transit_mm`, 15 for both boards, unverified), project
  override `cables.hole_transit_mm`, fallback 15. `hole_penalty` = search-only cost per pass, default 15 (mm
  equivalent), `cables.hole_penalty`. The under layer costs `under_cost` 0.9 x per mm (default; equal routes prefer
  under). Both values are unverified estimates.
- `cables.under_board` (default true): false disables the under layer for signal cables (today's behaviour).
- `cables.max_stack_under` (default = `max_stack`): cables per cell under the board.
- Under layer area = the board footprint (`design.footprint(layout["board"])`), the WHOLE board (also in front of the
  lowest pedals; the "nothing in front" rule is about the top). Obstacles under the board: the under-board supplies'
  outlines (supply items of instances with placement "under", phase 3), grown like pedals. Nothing else is known
  under the deck (no rails/frame model). Plug limits (`max_over_plug`) apply on top only.
- Signal cables start and end on top (the plug exits). Lanes (drawing) on top only. Lengths are a MINIMUM to buy:
  `min_mm` = both plug measures + the smoothed polyline on top + the smoothed polyline under + `hole_transit_mm` per
  pass. No slack, no rounding. Power cables are NOT routed in this phase (next phase), keep them as today.

## Context (code you will touch; read these functions first)
- `scripts/routing.py`: module docstring (keep it current); `DEFAULTS`, `settings(project, types)`; `Grid`
  (`blocked` = grown cells, `body` = pedal cells, `walls(squeeze)`, `inside`, `cell_of`, `centre`, `connected`),
  `rect_cells`, `grow_of`, `build_grid(board_rect, obstacle_rects, front_y, cfg)`; `astar(grid, start, goal,
  cell_cost, squeeze=False)` (8-connected, no corner cutting, octile steps); `route_all(grid, nets, max_stack,
  iterations, plugs, max_over_plug)` (negotiated congestion: usage per cell, present/history costs, plug crossings);
  `path_length`; `smooth(points, obstacles, radius, plugs, own_plugs=())` (string pulling); `lanes(routes,
  pedal_rects, plug_rects, area, width)` (drawing only); `route_project(ctx, cat_pedals, cable_types)` (side choice per
  cable end via `combos` + a single-layer `astar`, then `route_all`, smoothing, findings, lanes, plug clearance).
- `layout["holes"]` (canvas rects), `layout["board"]`, `layout["obstacles"]`, `layout["shapes"]`,
  `layout["inst_item"]` and the per-instance placement from phase 3 (see how phase 3 exposed it, e.g.
  `layout["inst_placement"]`).
- `scripts/svgdraw.py`: `cables(cable_list, colours, diameter, ends)` draws `c["draw_path"]` (else `c["path"]`),
  `holes(rects)`, `key_entries` / `key_sample`, `legend_table`.
- `scripts/build.py`: the routing section of the README (~line 437-470: text + the cable table with an "Under board"
  column) and `common.proposal_inputs_sha1` (common.py ~33).
- Tests: `tests/test_routing.py` (hand-computed grid cases; read its helpers), `tests/test_svgdraw.py`.

## Tasks
1. Settings: add `under_board` (True), `hole_penalty` (15.0), `under_cost` (0.9), `max_stack_under` (None ->
   max_stack) to DEFAULTS / `settings`; `hole_transit_mm` resolved in route_project (project > board data > 15).
2. Under-layer grid: same origin / cell size as the top grid so cell (i, j) is the same place on both layers; its own
   blocked set (under supplies grown) and its own extent (the board footprint, which may reach below the top grid's
   `front_y`). Hole cells as defined above. Store on `ctx["routing"]`: `under` (the under grid or None), `hole_cells`.
3. Search over states (cell, layer): extend `astar` (or add `astar2`; keep the old call working for single-layer
   use) with an optional under grid: moving within a layer as today (under steps x `under_cost`, with the under
   layer's own cell_cost), switching layer only at a hole cell at cost `hole_transit_mm + hole_penalty`.
   Heuristic must stay admissible (e.g. `under_cost` x euclid). Start and goal on top.
4. `route_all`: usage, history and the stacking limit per (cell, layer) (`max_stack` on top, `max_stack_under`
   under); plug crossings on top only. Overflow reported per layer.
5. Side choice in route_project: feasibility (`mode`) and the length estimate of each combination use the two-layer
   graph (a pair unreachable on top may be reachable through the holes). Keep the old ranking order otherwise.
6. Per routed cable: split the path into stretches by layer; smooth each stretch separately (top: as today with
   pedal rects and plugs; under: against the under obstacles, no plugs; the hole cells where the cable changes layer
   stay fixed corners); `min_mm` as above. Cable fields: `under_board` true when any stretch is under (keep the key),
   `under_mm` (polyline under), `holes_used` (number of passes), `stretches` [{"layer": "top"|"under", "points":
   [...]}] (drawing), `path` (all points in order, as today, for compatibility). Findings: over-stacking under
   reported like on top ("... beyond the limit of N stacked cables under the board").
7. Lanes: only top stretches take part (feed each top stretch to `lanes` as its own entry and reassemble
   `draw_path` per stretch); under stretches drawn as their smoothed polyline.
8. routing.svg: under stretches dashed (and lighter), a small marker (e.g. ring) at each hole pass; key entries
   "under the board" and "hole pass". README: the routing text says cables may pass under the board through holes
   (with the transit/penalty values), the table's "Under board" column shows e.g. "yes (2 holes, 180 mm)" / "no".
9. `common.proposal_inputs_sha1`: include the board image's `catalog/boards.json` entry and the project's
   `board.json` (if present), so proposals go stale when holes change.
10. Tests (hand-computed, small synthetic boards): a wall of pedals between two jacks with one hole on each side ->
    the cable goes under (length = measures + top + under + 2 x transit); the same with `under_board: false` -> on
    top / around; a hole covered by a pedal is not used; a cable does not go under when the detour saving is smaller
    than 2 x (transit + penalty); `max_stack_under` respected; under-board supply blocks the under layer; side-choice
    finds a combo only reachable through holes; svg draws dashed under stretches and hole markers;
    `proposal_inputs_sha1` changes when board.json changes.

## Acceptance
- `uv run pytest tests -q` all pass (`PEDALBOARD_SLOW=1` too, if feasible in time; report).
- `uv run scripts/build.py` runs; build time per project stays reasonable (report gig time before/after; today ~0.2 s
  for routing).
- Report for guitar-gig a before/after table per signal cable (min length, under yes/no, holes): the "before" values
  are in the README table on the last commit (`git show HEAD:projects/guitar-gig/README.md`). Also the total, the
  stacked corridors and any new findings. Do not tune the costs to make the result look good; report what happens.

## Do not touch
- Power cable routing (next phase), `layout.py` / `propose_layout.py` / `power.py` (beyond nothing), project.json,
  playground_design.json, catalog data, board_editor.py. Do not regenerate proposals. No new dependencies. Do not
  edit CLAUDE.md / docs.
