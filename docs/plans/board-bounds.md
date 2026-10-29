# Plan: usable board area (`feat/board-bounds`)

Status: plan with the owner's decisions (2026-10-29, section "Decisions"); handovers next. Start the code after
`feat/cable-ids` is merged (both touch `build.py`, `svgdraw.py`, `routing.py`).

## Problem (owner, 2026-10-29)
The Fender Professional Medium has rounded edges at the back and at the front where pedals cannot sit. The layout
search only keeps pedals inside the board image box shrunk by `layout.board_margin_mm` (`layout.py`
`feasible_one` ~line 480, `free_distance` ~line 1236), so the proposals (e.g. `--max-change rearrange --seed 42`) put
pedals on the rounded parts, and the build does not notice it in the owner's layout either.

## Goal
Four boundary lines per project (back, front, left, right) that define where pedals may sit. Set them in the board
editor; each line moves on its own, along its own axis only, so the owner can adjust one without touching the others.

## Decisions (owner, 2026-10-29)
1. Cables may still run over the edges (sides and back) as before: the routing area is the usable area plus a small
   margin on the sides and the back (`edge_margin_mm`), computed from the usable area.
2. The bounds do NOT apply under the board: some boards (the Fender) have their own supply placement, which may lie
   outside the usable area; the owner's placement of under-board supplies is kept and never checked against the bounds.
3. Warn when a pedal of the owner's layout is outside the usable area.
4. Board editor: drag a line with the mouse, arrow keys too: exactly the intended idea.
5. (Plan default, not objected) The Pedal Playground box is checked, not the outline (as for overlaps); edge segments
   stay on the image edge.

## Data
`projects/<name>/board.json` gets a top-level `bounds` next to `boxes`:
```json
"bounds": {"back": 0.06, "front": 0.95, "left": 0.0, "right": 1.0}
```
- Fractions of the UNROTATED Pedal Playground board image, as the boxes: back / front = distance of the line from the
  image's top edge (fraction of the height, back < front), left / right = from the left edge (fraction of the width,
  left < right). 4 decimals.
- A missing side (or no `bounds`) = that image edge: today's behaviour, every existing project unchanged.
- Written ONLY by `scripts/board_editor.py` (the `_doc` string explains it). `boards.load_edits` stays as is; a new
  `boards.load_bounds(project_dir, warnings)` returns the four fractions (invalid -> warning, ignored, as the boxes).
- `board.json` is already part of `common.proposal_inputs_sha1`: changing the bounds makes the proposals stale.

## Geometry
- `design.board_bounds(board_item, bounds)` -> the usable rectangle in canvas mm (x0, y0, x1, y1), mapped like
  `design.board_holes` (rotation-aware via `jack_point`); None without a board.
- `jacks.layout_from_items` returns it as `layout["usable"]` (the board footprint when there are no bounds).

## Use
1. **Layout search** (`layout.py`): `feasible_one` and `free_distance` use `layout["usable"]` instead of the board
   footprint (`board_margin_mm` still shrinks it), for the pedals AND the movable on-board supplies. Under-board
   supplies are never limited (decision 2).
2. **Routing area** (decision 1): the top routing area of the signal AND power grids is the usable area grown by
   `cables.edge_margin_mm` (default one cable diameter) at the back and the sides, instead of the board footprint grown
   by it (`routing.build_grid`, `routing.front_limit`, `routing.route_power` ~line 2026, and the surrogate's copy in
   `layout.py` ~line 810). Front: nothing in front of the lowest pedals as today; with `cables.route_in_front` the
   usable front + the margin. Without bounds the area is exactly today's (usable = footprint).
   - Edge segments (`board.json` type edge, cables round the board edge) stay on the IMAGE edge. A cable crossing there
     has to reach the board border, which may now lie outside the routing area: the top grid keeps today's extent but
     blocks the cells outside the grown usable area, except a strip along each edge segment from the usable area to
     the border + margin (`routing.edge_links` keeps working unchanged). The under layer stays the whole board footprint.
3. **Build check** (decision 3): every chain pedal and on-board item of the owner's layout whose box lies outside the
   usable area -> warning `layout: <pedal> is outside the usable board area by N mm (back)` (README findings).
   `validation.strict_bounds` (default false) promotes it to an error, as the other strict flags. Under-board supplies
   are not checked.
4. **Proposals** (`propose_layout.py`): the search starts from the owner's state, which may now be infeasible. Pedals
   that start outside the usable area are first moved to the nearest feasible spot inside (counted as moves); if none
   is found the search reports it and starts with the check relaxed for those pedals until they move inside. A
   proposal never has a pedal outside (hard constraint); the README proposal table gets a row "Outside the usable
   area" (owner's layout vs proposals).
5. **Drawing** (`svgdraw.py`): the usable area as a dashed outline in `routing.svg`, `power.svg` and the proposal SVGs,
   with a legend entry; only drawn when `bounds` exist. The routing area outline follows the new area.
6. **Board editor** (`board_editor.py`, decision 4):
   - A "bounds" mode (key `B`, and a radio button next to hole / filled / edge) shows the four lines across the whole
     image (distinct colour, dashed, labelled back / front / left / right), the area outside shaded.
   - Click near a line selects it (nearest line within a few px); dragging moves ONLY that line, only along its axis
     (back / front move vertically, left / right horizontally). Arrow keys nudge the selected line 0.5 mm (Shift 2 mm),
     only along its axis; the other arrows do nothing. Delete resets the selected line to the image edge. Esc deselects.
   - A line cannot cross its opposite (at least 10 mm between them) and stays inside the image.
   - The list panel / status bar shows each line's distance from its image edge in mm. Saved with Ctrl+S together
     with the boxes (same file, same dirty flag).
   - Pure helpers at module level (hit test, move, nudge, clamp, to/from fractions) with tests, as the existing ones.
   - Outside bounds mode the lines are drawn but not editable.
7. **Docs**: `CLAUDE.md` (board.json line, routing area, layout proposals line), the README texts that describe the
   routing area and the layout rules, `docs/TODO.md` (tick "Usable board area").

## Phases (one handover each)
1. Data + geometry + build check + routing area + drawing (`boards.load_bounds`, `design.board_bounds`,
   `layout["usable"]`, warning, `strict_bounds`, grown-usable routing area with the edge-segment strips, SVG outline),
   tests with hand-computed cases (rotated board too).
2. Layout search and proposals (feasibility, `free_distance`, the surrogate's routing area, start from an infeasible
   owner layout, the README row), tests.
3. Board editor bounds mode (pure helpers + GUI), tests for the helpers. Independent of 1-2 apart from the data
   format: can run in parallel with them.
4. Owner: draw the gig bounds, build, re-run the proposals (fix and rearrange), judge them.

## Not in scope
Non-rectangular usable areas (a rounded corner as a curve), per-pedal exceptions, under-board fit.
