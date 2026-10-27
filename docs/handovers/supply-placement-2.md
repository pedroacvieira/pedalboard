# Handover: supply-placement phase 2: board editor (hole / filled boxes per project)

Branch `feat/supply-placement` (checked out; phase 1 is committed). Do not commit; the reviewer commits.

## Goal
A small Tkinter editor, `scripts/board_editor.py <project>`, where the owner corrects the board holes derived from
the Pedal Playground board image: draw boxes of type `hole` (opens a hole) or `filled` (closes one) on the image and
save them to `projects/<name>/board.json`. The build already reads that file (phase 1). Keep it simple.

## Context
- Python 3.12, `uv run` only (never pip). Tests `uv run pytest tests -q`; build `uv run scripts/build.py`.
- Phase 1 (read these first): `scripts/boards.py` (`load`, `load_edits(project_dir)`, the `catalog/boards.json`
  format: per board IMAGE name `{"holes": [[x0, y0, x1, y1], ...], "hole_transit_mm": .., "notes": ..}` in fractions of
  the unrotated image), `design.board_holes(board_item, holes, edits)` (effective holes = derived holes, then each
  edit box in order: `filled` subtracts, `hole` adds; a later box wins), `common.fetch_image(name, kind="pedalboards")`.
- `projects/<name>/board.json` format (fixed by phase 1): `{"boxes": [{"type": "hole" | "filled", "x0", "y0", "x1",
  "y1"}]}`, fractions 0..1 of the board image, x0 < x1, y0 < y1. Box order matters (later wins). Written ONLY by the
  board editor: one box per line, 4 decimals, like `catalog/outlines.json` style (add a `_doc` key explaining it).
- Which board image: the project's `playground_design.json` board item (`kind == "pedalboard"`, field `image`, sizes
  `w_mm`/`h_mm`) when it exists, else Pedal Playground's database: `common.database("pedalboards.json")` keyed
  `f"{project['board']['brand']} {project['board']['model']}"` (e.g. "Rockboard by Warwick Duo 2.1" ->
  `rockboard-duo-21.png`, Width/Height in inches, `common.IN_MM`). Projects: guitar-gig (Fender, has a layout),
  guitar-practice and bass (Duo 2.1, no layout). Optional `--image FILE` to use a local PNG.
- Pattern to copy: `scripts/pedal_editor.py` (Tkinter + Pillow; pure helpers at module level, tested in
  `tests/test_pedal_editor.py`; the GUI class built inside `make_app`; `run_app`; `main(argv)`; zoom with +/- and the
  wheel; Ctrl+S saves only when changed; it asks before closing with unsaved changes). Reuse its image/zoom/canvas
  handling ideas; do not refactor pedal_editor.py.

## Tasks
1. `scripts/board_editor.py`:
   - Shows the board image scaled to fit (zoomable), the DERIVED holes as one overlay style (e.g. blue outline), the
     project's boxes on top (hole = green, filled = red, semi-transparent stipple/outline; the selected box
     highlighted), and optionally the EFFECTIVE holes (toggle key `E`) computed with `design.board_holes` on an
     unrotated item of the image's mm size.
   - Mouse: drag on empty space draws a new box (type = the current default type, shown in the status bar); click
     a box selects it; drag a selected box moves it; `T` toggles the selected box's type (or the default type when
     none is selected); Delete removes the selected box; arrow keys nudge the selected box 0.5 mm (Shift 2 mm);
     `[` / `]` move the selected box earlier / later in the order (order matters). A list panel shows the boxes in
     order (index, type, size in mm) and selects on click. Status bar: cursor position in mm.
   - Ctrl+S saves `projects/<name>/board.json` (atomic write via a .tmp + os.replace); saving with no boxes writes
     `{"boxes": []}` (keep the file, the owner may want "no edits" explicitly) . Quit asks when unsaved.
   - CLI: `uv run scripts/board_editor.py <project> [--image FILE]`; `--list` prints every project with its board
     image, derived hole count (from boards.json, `?` when the image has no entry) and edit box count. If the board
     image has no boards.json entry, still open the editor (no derived overlay) and print a hint to run
     `uv run scripts/boards.py <project>`.
   - Pure helpers at module level (no Tk import at module import time; import tkinter inside `make_app`/`run_app`):
     e.g. `board_image_for(project_dir, project, db)` -> (image name, w_mm, h_mm); `px_to_frac` / `frac_to_px` with a
     zoom; `normalize_box(x0, y0, x1, y1, type)` (orders corners, clamps to 0..1, rejects boxes smaller than ~1 mm
     on a side -> None); `hit_box(boxes, fx, fy)` (topmost = last in order wins); `move_box`, `nudge_box` (clamped to
     the image); `toggle_type`; `reorder(boxes, i, delta)`; `dumps_edits(boxes)` and `save_edits(project_dir, boxes)`
     (round-trips with `boards.load_edits`); `list_rows(...)`.
2. Tests `tests/test_board_editor.py` (no display needed): every pure helper above with hand-computed values
   (normalize swaps corners and clamps; a too-small box is rejected; hit_box returns the last box on overlap;
   nudge clamps at the edge; reorder; save -> load_edits round trip in a tmp dir; `board_image_for` for a project
   with a layout item and for one resolved via a fake database dict; list rows). Also a test that importing
   `board_editor` does not import tkinter.
3. Manual check: you cannot see the GUI. At least construct the app once if a display is available
   (`DISPLAY` set) and destroy it immediately in a guarded test (`pytest.mark.skipif` without DISPLAY), like any
   existing GUI test in the repo if one exists; otherwise skip this.

## Acceptance
- `uv run pytest tests -q` all pass. `uv run scripts/build.py` runs and changes nothing (no board.json exists).
- `uv run scripts/board_editor.py --list` prints the three projects.
- Report: files changed, test counts, what you could not verify (the GUI itself).

## Do not touch
- `scripts/pedal_editor.py`, `routing.py`, `layout.py`, `power.py`, `catalog/*` data, `projects/*/project.json`,
  `projects/*/playground_design.json`. Do not create any `projects/*/board.json` in the repo (tests use tmp dirs).
- No new dependencies. Do not edit CLAUDE.md / docs.
