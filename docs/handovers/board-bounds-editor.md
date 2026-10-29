# Handover: board editor "bounds" mode (`feat/board-bounds-editor`, step 3 of `feat/board-bounds`)

## Goal
Let the owner set four boundary lines (back, front, left, right) of the usable board area in
`scripts/board_editor.py`, saved in `projects/<name>/board.json` as `bounds`. Pedals will later be kept inside them
(another step; NOT this task). This task: the data format, its loader, the editor mode, tests.

## Where you work
- Git worktree `/home/pvieira/projects/pedalboard-board-bounds-editor`, branch `feat/board-bounds-editor` (checked
  out, based on main). Work ONLY here; never touch any other checkout (`/home/pvieira/projects/pedalboard`,
  `pedalboard-cable-ids`, ...).
- `.cache/` is a copy (git-ignored) of the owner's Pedal Playground cache (board images included); keep it.
- Python 3.12 via uv: `uv sync` once, then `uv run ...`; never `pip install`. Tests: `uv run pytest tests -q`
  (~590 tests, ~90 s). The GUI needs a display; test the pure helpers, not Tkinter.
- Do NOT commit. Leave the changes uncommitted and report; the owner reviews first.

## Why (owner, 2026-10-29)
The Fender Professional Medium has rounded edges at the back and the front where pedals cannot sit; the layout search
uses them today. The owner wants four lines, each moved independently: "I want these 4 lines to be movable
independently, so I can focus on one without worrying about the others." Drag with the mouse (the owner's idea) and
arrow keys too.

## Data format (decided)
`projects/<name>/board.json` gets a top-level `bounds` next to `boxes` and `_doc`:
```json
{
  "_doc": "...",
  "bounds": {"back": 0.06, "front": 0.95, "left": 0.0, "right": 1.0},
  "boxes": [ ... ]
}
```
- Fractions of the UNROTATED board image, origin top-left, 4 decimals: back / front = distance of the line from the
  image's TOP edge as a fraction of the height (back < front); left / right = from the LEFT edge as a fraction of the
  width (left < right). Same convention as the boxes (back = the image's top edge, front = its bottom edge).
- A missing side, or no `bounds` key = that image edge (back 0, front 1, left 0, right 1). Write only the sides that
  differ from the image edge; write no `bounds` key when all four are at the edges (existing files stay byte-identical
  when nothing changed). Keep the key order `_doc`, `bounds`, `boxes`.
- Extend the `DOC` string in `board_editor.py` with one sentence on `bounds` (where pedals may sit; cables and
  under-board supplies are not limited by it).

## Code
1. `scripts/boards.py`: `load_bounds(project_dir, warnings=None)` -> dict with all four keys (fractions; defaults
   for missing sides). Invalid values (not numbers, outside 0..1, back >= front, left >= right) -> a warning in the
   style of `load_edits` (`"<project>/board.json: bounds ignored (...)"`) and the defaults. Missing file / project dir
   None -> defaults. `load_edits` stays unchanged (it reads only `boxes`).
2. `scripts/board_editor.py` file helpers: `dumps_edits(boxes, bounds=None)` and `save_edits(project_dir, boxes,
   bounds=None)` write `bounds` as above. The App loads them with `boards.load_bounds` and keeps them in the dirty
   check (`dirty` compares boxes AND bounds with the saved state); Ctrl+S saves both.
3. Pure helpers at module level (like the existing `hit_box`, `nudge_box`, ...), each with tests:
   - `bound_lines(bounds, w_mm, h_mm)` -> per side the line in mm on the unrotated image (back/front horizontal,
     left/right vertical).
   - `hit_bound(bounds, fx, fy, w_mm, h_mm, tol_mm=HIT_MM)` -> the side whose line is nearest to the click within
     `tol_mm` (back/front: vertical distance; left/right: horizontal distance), else None.
   - `move_bound(bounds, side, f, w_mm, h_mm)` -> new bounds with ONLY `side` set to fraction `f` (clamped to 0..1 and
     to at least `MIN_BOUNDS_GAP_MM` = 10 mm from the opposite line). Other sides untouched.
   - `nudge_bound(bounds, side, d_mm, w_mm, h_mm)` -> move along the side's own axis by `d_mm` (same clamping).
   - `reset_bound(bounds, side)` -> that side back to the image edge.
   - `bound_rows(bounds, w_mm, h_mm)` -> list lines like `back   12.5 mm from the top edge`.
4. Editor mode (`make_app`):
   - A fourth radio button "Bounds (B)" in the type panel and key `B` / `b`. In bounds mode: click near a line selects
     it (`hit_bound`); dragging moves ONLY that line, only along its axis (back / front follow the mouse's y, left /
     right its x; the other coordinate is ignored); Arrow keys nudge the selected line 0.5 mm (Shift 2 mm) only along
     its axis (Up/Down for back/front, Left/Right for left/right; the other arrows do nothing); Delete resets the
     selected line (`reset_bound`); Esc deselects. Dragging on empty space draws nothing in bounds mode.
   - In the other modes the lines are drawn but not selectable; the existing box / edge behaviour is unchanged
     (the keys 1 / 2 / 3, T, [ ], E keep working exactly as before; switching to bounds mode deselects any box).
   - Drawing: the four lines across the whole image (dashed, one distinct colour, e.g. "#00897b"; the selected one
     thicker), a short label at each (back / front / left / right), the area of the image outside the bounds lightly
     shaded (stipple or semi-transparent overlay drawn with PIL as the existing overlays are). Add a legend row.
   - The panel shows `bound_rows` (a small label block under the list) and the status bar the selected line and its
     distance in mm.
   - Update the module docstring and the help text in the panel (bounds mode: B, click a line, drag or arrows along
     its axis, Delete resets, Esc).
   - `--list` (`project_rows`): add "bounds set: back, front" (the sides that differ from the edge) or "no bounds".
5. Docs: `CLAUDE.md`, the `projects/<name>/board.json` bullet in "Layout": add the `bounds` key in one sentence
   (fractions of the image, back/front from the top, left/right from the left; written by the board editor; pedals
   must stay inside: used by the build / layout search in a later step).

## Acceptance
- `uv run pytest tests -q` green, new tests for `load_bounds` (defaults, valid, each invalid case -> warning),
  `dumps_edits` round trip with and without bounds (an existing file without bounds stays identical:
  `projects/guitar-gig/board.json` re-dumped unchanged), and every helper of point 3 (independence: moving / nudging /
  resetting one side never changes another; clamping at the image edges and at the 10 mm gap).
- `uv run scripts/build.py` exits 0 with no change to generated files (the build does not read `bounds` yet).
- `uv run scripts/board_editor.py --list` works.
- Do NOT open the GUI for the owner and do not write a `bounds` into any project's board.json: the owner draws them.

## Do not touch
`layout.py`, `routing.py`, `jacks.py`, `design.py`, `build.py`, `svgdraw.py`, `propose_layout.py` (later steps),
catalog data, `projects/` (except reading), generated files.

## Report back
Files changed, the helpers' signatures, test results, how the mode works (keys / mouse) in 5 lines, anything open.
