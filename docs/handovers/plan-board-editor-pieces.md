# Handover: write the plan for `feat/board-editor-pieces` (planning only, no code)

## Goal
Write `docs/plans/board-editor-pieces.md`: an implementation plan, then stop. Do not change code, data or git state.

## The feature
`scripts/board_editor.py` (Tkinter GUI, `uv run pb board-editor <project>`) edits a project's `projects/<p>/board.json`:
hole / filled boxes, edge segments (type `edge`), and `bounds` (usable area, mode B), drawn on the board image. A layout may
now hold several pedalboard items (a composed board, e.g. the bass board: D'Addario XPND 1 + its extension, evaluated as one
board). `board.json` has an optional `pieces` {"<board image file name>": {"boxes": [...], "bounds": {...}}}: the same keys
for the OTHER pieces (the top-level `boxes` / `bounds` are the FIRST piece's; a `pieces` entry for an image wins, also for
the first piece; `boards.load_pieces`, `boards.load_edits`, `boards.load_bounds`). Today the editor edits only the first piece
(its --help says so) and keeps `pieces` when it saves; edits for other pieces are written by hand.
Goal: the editor edits every piece: choose the piece (selector / key / --piece IMAGE), or show all pieces on one canvas in
their layout positions and edit the one under the cursor; the effective view (E key) shows the composed result.

## Constraints
Pure helpers at module level are unit-tested (the GUI itself is not); fractions are of each piece's UNROTATED image; written
only by the editor (one-item-per-line JSON style, `save_edits` / `dumps_edits`); old files keep working. Python 3.12 via
`uv run`; tests with pytest.

## The plan must contain
UI design (how a piece is chosen, what is drawn), data written (top-level vs `pieces`, how the first piece is identified and
whether its edits move into `pieces`), the pure helpers to add with signatures, --list output, test list, implementation steps
(each a self-contained handover for a Sonnet agent), risks, and "Decisions for the owner" each with a recommended default
(implementation will start with the defaults).

Read the code you need (scripts/board_editor.py, scripts/boards.py, scripts/design.py board helpers, scripts/jacks.py
`layout_from_items`, projects/bass/playground_design.json); do not read other plans or handovers.

## Deliverable
The plan file written, and a 10-line summary with the decisions and your recommended defaults.
