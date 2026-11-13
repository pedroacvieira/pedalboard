# Handover: code review of feat/board-editor-pieces

## Goal
Review branch `feat/board-editor-pieces` (worktree /home/pvieira/projects/pedalboard/.claude/worktrees/agent-ab51399eb3076a13c;
`git diff 09c8e73..HEAD -- scripts tests` there) for correctness bugs. Report findings only; do not edit or commit.

## What it must do
The board editor (`scripts/board_editor.py`, Tkinter; pure helpers at module level) edits every piece of a composed board
(several pedalboard items in the layout). `board.json`: a composed board is saved entirely under `pieces` {image: {boxes,
bounds}} sorted by image, top level `boxes: []` and no bounds; hand-written top-level edits move into `pieces[<first image>]`
on the first save (dropped with a note if that image already has an entry); a single-piece board keeps today's file byte for
byte; a `pieces` entry on a single-piece board moves to the top level; entries for images no longer in the layout are kept.
One rule for which edits belong to which piece, shared by the editor and the build: `boards.piece_edits` /
`load_piece_edits` (a `pieces` entry wins, also for the first image; else the top level = the first image; else none), used
by `jacks.layout_from_items` and `jacks.data_crossing_errors`. Fractions are of each piece's UNROTATED image.

## Check
- Save round trips (single piece byte-identical; composed: nothing lost, unsaved edits of every piece saved once).
- The shared edit rule gives the build the same edits as before for the live projects.
- Geometry helpers (`canvas_to_piece_frac`, `rects_to_piece_fracs`, `composed_effective`, `piece_effective`, `joint_sides`,
  `edge_on_joint`, `piece_at`) incl. rotated pieces.
- Tests in tests/test_board_editor.py test what they claim.

## Deliverable
A short list of real bugs (file:line, concrete failure scenario), most severe first. No style nits.
