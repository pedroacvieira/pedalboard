# Handover: edge boxes instead of edge modes (power cables cross only through holes or owner-drawn edge boxes)

Branch `feat/supply-placement` (checked out, all committed). Do not commit; the reviewer commits.
Python 3.12, `uv run` only; tests `uv run pytest tests -q`; build `uv run scripts/build.py`. No new dependencies.
Never edit `projects/*/playground_design.json` or catalog data. Do not edit CLAUDE.md / docs. Do not regenerate
proposals.

## Owner decisions (2026-10-26, copy, do not change)
- Remove the per-side board-edge routing for power cables (`power_routing.edges` front/left/right/back modes and
  `power_routing.avoid_penalty`). Power cables go from under to over the board EXCLUSIVELY through:
  1. the board's holes (effective holes, as today), and
  2. **edge boxes** the owner draws in the board editor: a box of the new type `"edge"` in `projects/<name>/board.json`
     placed over (and usually outside) a section of the board's border. A cable may come round the board edge only
     where the border lies inside an edge box.
- No edge boxes -> only the holes. Neither usable holes nor edge boxes on the board -> a supply can NOT be under the
  board: every under-board supply instance of that project is an **error** ("power.supplies: psu1 is under the board,
  but the board has no holes and no edge boxes, so no power cable can come up; draw them with uv run
  scripts/board_editor.py <project> or set placement on_board").
- `edge_transit_mm` (extra length round the edge) stays as it is (board data > power_routing.edge_transit_mm > 2 x hole
  transit).

## Context (read these first)
- `scripts/boards.py`: `load_edits(project_dir, warnings)` validates boxes `{"type": "hole"|"filled", "x0".."y1"}` in
  fractions 0..1 of the board image; `usable` for catalog/boards.json.
- `scripts/design.py`: `board_holes(board_item, holes, edits)` (applies hole/filled boxes in order, maps fractions to
  canvas mm rotation-aware via `jack_point`).
- `scripts/jacks.py` `layout_from_items(..., board_data, board_edits)` -> `layout["holes"]`.
- `scripts/routing.py`: `power_settings` / `validate_power_routing` (`POWER_ROUTING` defaults incl. `edges`,
  `avoid_penalty`), `edge_links(top, ug, board_rect, modes, transit_mm, penalty)` (under cells on a board side ->
  the top margin cell just outside), `Under` (edge links, `edge_cost`, `pass_floor`), `tight_heuristic`,
  `route_power` (edges_used / edge_sides / edge_points), README text `build.power_text`.
- `scripts/power.py`: the nearest-hole estimate (`estimate_setup`, `HoleIndex`, `usable_holes`, `hop_estimate`) used by
  `power.assign` and `layout.Model`; today it knows holes only (check how edges enter it, if at all).
- `scripts/board_editor.py` (Tkinter; pure helpers at module level, tested in `tests/test_board_editor.py`): `TYPES =
  ("hole", "filled")`, `normalize_box` clamps to 0..1, `toggle_type`, drawing colours per type, the canvas shows the
  image only; `save_edits` / `dumps_edits`.
- `svgdraw.py` (`routing.svg`, `power.svg` via `render_power`): edge passes are drawn as squares.
- The guitar-gig `project.json` has `"power_routing": { "edges": {...} }` (owner, earlier today): REMOVE that key from
  `projects/guitar-gig/project.json` (owner's instruction; touch nothing else in that file). guitar-gig's board.json has
  16 hole boxes and no edge boxes, so after this change its P10 (today over the back edge) must come up through a hole.

## Tasks
1. Data: box type `"edge"` in board.json. Fractions of the board image, allowed outside 0..1 (down to -EDGE_MARGIN and
   up to 1 + EDGE_MARGIN, a named constant, e.g. 0.25 of the image size). Hole/filled boxes keep 0..1. `load_edits`
   validates per type. `design.board_holes` ignores edge boxes; new `design.board_edges(board_item, edits)` -> the edge
   boxes as canvas mm rects (rotation-aware like board_holes). `layout["edge_boxes"]` from `layout_from_items`.
2. Router: `power_settings` drops `edges` / `avoid_penalty` (an old `power_routing.edges` or `avoid_penalty` key is an
   error telling the owner to draw edge boxes instead). `edge_links` takes the edge boxes: a link from an under cell on
   the board border to the top cell just outside it exists only where that top cell's centre (or the border point
   between them) lies inside an edge box, on any side. Cost = `edge_transit_mm` (at least one cell). An edge box that
   reaches no border cell gives a warning ("board.json: edge box N does not touch the board edge"); one only on the
   front, where the top routing area ends at the lowest pedals, gives a warning that it cannot be used (the top grid has
   no cells there) — do not change the front rule.
3. The "neither" error (decision above): in the build, after the layout is known: project has under-board supply
   instances, and the layout has no hole cell usable by power cables (or no holes at all) and no edge box touching the
   board -> error per under-board instance. Without a layout (practice / bass today) check the data instead: no
   effective holes for the project's board image (boards.json + board.json) and no edge boxes -> the same error.
   guitar-practice / bass use the Duo 2.1 which has 17 derived holes, so they stay OK.
4. Estimate (`power.py`, `layout.py`): edge boxes are crossing points too: sample points along the board border inside
   each edge box (same spacing as the hole sample) with their own transit (`edge_transit_mm`) instead of the hole
   transit; `hop_estimate` / `HoleIndex` (or a sibling) pick the cheapest crossing including that transit. Edge points
   are never covered by pedals (they are outside the board). Keep the search speed (report `--score` time).
5. Board editor:
   - The canvas shows a margin round the image (EDGE_MARGIN of the image size on each side, a neutral background, the
     board image in the middle) so boxes can be drawn outside the board.
   - Types cycle with `T`: hole -> filled -> edge -> hole. Edge boxes drawn in a distinct colour (e.g. purple) with
     their own legend line; the status bar shows the current default type.
   - `normalize_box`: hole/filled clamp to 0..1 (as today), edge clamps to [-EDGE_MARGIN, 1 + EDGE_MARGIN] and must
     overlap the image border band (else rejected with a status message "an edge box must cover part of the board
     edge"). `nudge_box` / `move_box` clamp per type. `effective_holes` unchanged (edge boxes are not holes); `E` view
     also shows the edge boxes.
   - `--list` gains an "edge boxes" count. Update the module docstring and the board.json `_doc` (DOC) text.
6. Drawing: routing.svg and power.svg draw the edge boxes (light purple, translucent, dashed outline) with a key entry
   "edge box: power cables may come round the board edge here"; the edge-pass squares stay.
7. README (`build.power_text`): describe the crossing model (holes + owner-drawn edge boxes, none drawn = holes only;
   neither = an under-board supply is an error); remove the edge-mode wording.
8. Tests (hand-computed, small synthetic boards; update the existing edge-mode tests in `tests/test_power_routing.py`
   and `tests/test_routing.py` to edge boxes): an edge box on the left lets a cable cross there and nowhere else on the
   left; no edge box -> through a hole; neither holes nor edge boxes -> the error per under-board instance (and no
   error for an on-board supply); old `power_routing.edges` key -> error; edge box not touching the edge -> warning;
   load_edits accepts out-of-range fractions for edge only; design.board_edges with rotation 0 and 90; estimate uses an
   edge point with the edge transit; editor helpers (type cycle, clamp per type, rejection of an edge box off the border,
   margin mapping px <-> fractions with the margin).

## Acceptance
- `uv run pytest tests -q` all pass; `uv run scripts/build.py` runs with 0 errors for all three projects.
- Report the guitar-gig power cables that changed (expected: P10 no longer over the back edge) with old / new min
  length and crossing; the README / svg diff summary; `--score` time.
- Report what you could not verify (the editor GUI by eye).
