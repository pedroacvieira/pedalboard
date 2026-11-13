# Plan: `feat/board-editor-pieces`: the board editor edits every piece of a composed board

Status: plan (2026-11-13). Handover: `docs/handovers/plan-board-editor-pieces.md`. Implementation starts with the defaults of
"Decisions for the owner" below.

## 1. Where we are

- `scripts/board_editor.py` (Tkinter, `uv run pb board-editor <project>`) edits ONE board image: `board_image_for(project_dir, project,
  db)` returns the FIRST `pedalboard` item of `playground_design.json` (else Pedal Playground's DB entry for `project.json` `board`).
  All its pure helpers (boxes, edge segments, bounds, `effective_holes`, `list_rows`, `bound_rows`) work in fractions of that one
  unrotated image and its `w_mm` x `h_mm`; the App holds `self.boxes` / `self.bounds` for that image.
- `board.json`: top-level `boxes` / `bounds` = the first piece's; optional `pieces` {"<image>.png": {"boxes", "bounds"}} for the others.
  `save_edits` re-reads the file and writes `pieces` back unchanged; `dumps_edits` writes it as ONE `json.dumps` line (not the
  one-entry-per-line style).
- The build (`jacks.layout_from_items`) picks a piece's edits as: its `pieces` entry if there is one (also for the first piece), else
  the top-level for piece 0, else none. `boards.unknown_pieces` warns about `pieces` keys that are no piece of the layout.
- The bass board today (`projects/bass/playground_design.json`): two pieces, both rotation 0, in this LAYOUT ORDER:
  1. `daddario-xpnd-1-extension.png` 10.75 x 5.5 in (273.1 x 139.7 mm), x 21.60 in;
  2. `daddario-xpnd-1.png` 14 x 6.03 in (355.6 x 153.2 mm), x 32.36 in (abuts the extension's right edge, gap ~0.19 mm).
  So the "first piece" (top-level) is the EXTENSION, and the order is whatever the owner's last Pedal Playground save had. bass has no
  `board.json` yet; guitar-gig has a single-piece one (must stay byte-identical); guitar-practice has none.
- `catalog/boards.json` has derived holes for both XPND images.

Consequence: "top-level = first piece" is fragile for composed boards (a re-fetched layout can swap the order, silently moving the
top-level edits to the other image). The plan therefore writes composed boards' edits under `pieces` only (keyed by image, order-free).

## 2. UI design

### 2.1 Piece view (the editing view; default)
The editor shows ONE piece at a time, exactly as today: its own unrotated image, its derived holes, its boxes / edge segments /
bounds, all in fractions of that image. Every existing pure helper is reused unchanged (they take `w_mm`, `h_mm` of the piece).

Choosing the piece:
- `--piece IMAGE|N` on the command line (image file name with or without `.png`, or the 1-based layout index); default piece 1.
  An unknown value exits with the list of pieces.
- In the window: a "Board piece" combobox at the top of the panel (`1  daddario-xpnd-1-extension.png  273 x 140 mm`), shown only
  when there is more than one piece; keys `Tab` / `Shift+Tab` = next / previous piece (bound with `return "break"` so Tk's focus
  traversal does not eat them; through `_guard`).
- Switching keeps every piece's unsaved edits in memory (per-piece state), deselects, resets the mode-specific selection (`sel`,
  `bsel`), keeps the zoom factor (px per mm, so the two images are at the same scale), loads (fetches) the next image lazily.
- Title: `bass: piece 1/2 daddario-xpnd-1-extension.png - 273.1 x 139.7 mm`; status bar adds `piece 1/2` and `UNSAVED` when ANY
  piece is dirty (the listbox and bounds label show the current piece).
- Ctrl+S saves ALL pieces in one write; close asks once if any piece is dirty.

Context drawn in the piece view (composed boards only, read-only):
- The area where another piece's footprint covers this one (a stacked joint): grey hatch + the other piece's name. There, a hole
  of this piece is a way through only if the other piece has a hole too (`design.composed_holes`); the owner sees why.
- A thin grey tick along each side of this image that touches another piece (a joint, not a board edge: an edge segment there is
  useless because `routing.edge_links(..., pieces=)` takes border cells of the UNION). Drawing an edge segment that lies entirely on a
  joint is still allowed (it is data) but the status bar says "this side is a joint with <piece>: no cable crossing there".

### 2.2 Effective view (E)
- Piece view: E draws the holes the BUILD will use on this piece: the composed effective holes (all pieces, `design.composed_holes`)
  clipped to this piece's footprint and mapped back to its image fractions (orange dashed). For a single-piece board this equals
  today's `effective_holes` (same result, tested).
- Whole-board overview (below): E toggles the same composed holes on the whole board.

### 2.3 Whole-board overview (W, read-only)
`W` (or a "Whole board" button, composed boards only) switches the canvas to all pieces in their layout positions (canvas mm of
the layout, origin = the bounding box of the pieces, `design.layout_board_rect`): each piece's image rotated by its `rot`
(Pillow `rotate(-rot, expand=True)`; Pedal Playground rotates clockwise), its edge segments (purple, `design.board_edges`), its usable
rect (`design.board_bounds`, dashed teal; the area outside the UNION of the usable rects shaded), a label per piece, and with E the
composed effective holes. Nothing is editable there: a click on a piece (`piece_at`) selects it and returns to the piece view
(overlapping pieces: the later in the layout order, which Pedal Playground draws on top; repeated clicks cycle). Esc or W returns to
the piece view without changing the piece.

Why not edit in the overview (option B of the handover): rotated pieces swap the axes of bounds lines, nudges and edge snapping;
overlapping pieces make "the piece under the cursor" ambiguous; every helper would need a canvas<->image mapping. The overview
gives the composed picture; editing stays in image fractions where all helpers and tests already are. (Decision D2.)

## 3. Data written

Model in the editor: `edits = {image: {"boxes": [...], "bounds": {...}}}` for every piece image of the layout, read with the build's
own rule (`boards.piece_edits`, below), so the editor shows exactly what the build uses.

On save (`split_for_save`):
- ONE piece (guitar-gig, guitar-practice, a board without a layout): top-level `boxes` / `bounds`, no `pieces` key for it (today's file,
  byte-identical). An existing `pieces` entry for that same image (hand-written) is moved to the top level (D3) and the entry dropped.
- SEVERAL pieces (bass): every piece goes under `pieces[<image>]`; the top-level `boxes` is `[]` and has no `bounds`. Existing
  top-level edits of a composed board (hand-written for "the first piece") are MIGRATED on the first save into
  `pieces[<first piece's image>]` unless that image already has a `pieces` entry (then the top level was dead data: it is dropped and
  the status bar says so). (D1.)
- A piece with no boxes and bounds on the image edges gets no `pieces` entry.
- `pieces` entries for images that are no piece of the current layout (a removed board, a renamed image) are KEPT unchanged (D4);
  `--list` and a one-time status message name them; the build already warns (`boards.unknown_pieces`).
- Two pieces with the SAME image share one entry (the file is keyed by image): editing one edits both; the combobox marks them
  `(same image as piece N)` (D5).
- Format (one item per line, like the top level), pieces sorted by image name (stable diffs when the layout order changes, D6):

```json
{
  "_doc": "...",
  "boxes": [],
  "pieces": {
    "daddario-xpnd-1-extension.png": {
      "bounds": {"right": 0.98},
      "boxes": [
        {"type": "edge", "side": "back", "from": 0.1, "to": 0.9}
      ]
    },
    "daddario-xpnd-1.png": {
      "boxes": [
        {"type": "hole", "x0": 0.1, "y0": 0.2, "x1": 0.3, "y1": 0.6}
      ]
    }
  }
}
```

  `_doc` gets one sentence about `pieces` (the doc line is ignored by the byte-identity test already).
- Old files keep working: the loaders do not change behaviour (`pieces` wins, else top-level for piece 0); a file whose `pieces` is
  written as one line still loads; the editor rewrites it in the new style on the next save.

## 4. Pure helpers to add (module level, unit-tested)

`scripts/boards.py`
- `piece_edits(top_boxes, top_bounds, pieces, images) -> dict[str, dict]`: {image: {"boxes", "bounds"}} for every image in `images`
  (layout order), by the build's rule: `pieces[image]` if present, else (`top_boxes`, `top_bounds`) for `images[0]`, else
  ([], `BOUNDS_EDGE`). Duplicate images: the first occurrence decides (same as the build). `jacks.layout_from_items` is changed to use
  it (no behaviour change; the existing `tests/test_board_pieces.py` cases must stay green), so editor and build cannot drift.
- `load_piece_edits(project_dir, images, warnings=None)`: `piece_edits(load_edits, load_bounds, load_pieces, images)`.

`scripts/board_editor.py`
- `board_pieces_for(project_dir, project, db) -> list[dict]`: every `pedalboard` item with an image, layout order, as
  {"image", "w_mm", "h_mm", "item"} (`item` = the parsed layout item, for the overview); without a layout: one piece from the DB with
  `item = None` (overview unavailable). Raises ValueError like today. `board_image_for` stays (= the first piece's tuple) for callers
  and tests.
- `resolve_piece(pieces, arg) -> int`: index for `--piece` (image with / without `.png`, or 1-based number); ValueError naming the
  choices.
- `piece_label(pieces, i) -> str`: the combobox text, with `(same image as piece N)` for a repeated image.
- `split_for_save(edits, images, file_pieces, top_boxes, top_bounds) -> (boxes, bounds, pieces, notes)`: the rules of section 3
  (`file_pieces` = the raw `pieces` already in the file, for the unknown-image entries to keep; `notes` = human-readable lines for the
  status bar: "moved the top-level edits into pieces.<image>", "dropped top-level edits shadowed by pieces.<image>").
- `dumps_edits(boxes, bounds=None, pieces=None)`: `pieces` written one box per line (section 3), sorted by image; a piece entry with
  bounds on the edges has no `bounds` key. Signature unchanged.
- `save_edits(project_dir, boxes, bounds=None, pieces=KEEP)`: `pieces=KEEP` (a module sentinel, the default) = today's behaviour
  (re-read and keep the file's `pieces`); a dict = write that (None / {} = no key). Existing callers and tests unchanged.
- `canvas_to_piece_frac(item, x_mm, y_mm) -> (fx, fy)`: inverse of `design.jack_point` (rotations 0 / 90 / 180 / 270).
- `rects_to_piece_fracs(item, rects) -> list`: canvas rects -> fraction rects of the piece image, clipped to 0..1, empty ones dropped.
- `composed_effective(pieces, derived, edits) -> list`: canvas rects = `design.composed_holes([footprint], [design.board_holes(item,
  derived.get(image), edits[image]["boxes"])])`; `derived` = `boards.load()` ({} entry = no derived holes).
- `piece_effective(pieces, i, derived, edits) -> list`: `rects_to_piece_fracs(pieces[i]["item"], clip to footprint(composed_effective))`;
  for one piece without a layout item: `effective_holes` mapped to fractions (today's result).
- `overlap_ghosts(pieces, i) -> list[(fraction rect, other image)]`: the other pieces' footprints clipped to piece `i`'s, in its fractions.
- `joint_sides(pieces, i, tol_mm=0.5) -> list[(side, from, to, other image)]`: the parts of each side of piece `i`'s unrotated image that
  lie on (within `tol_mm` of) another piece's footprint, as fractions along that side (for the ticks and the edge-segment warning).
- `piece_at(pieces, x_mm, y_mm, after=None) -> int | None`: the piece whose footprint contains the canvas point, topmost (latest in the
  layout) first; `after` = the index picked last, to cycle through overlapping pieces.
- `overview_rows(pieces)` is NOT needed (the overview reuses the helpers above).

## 5. `--list` output

Single-piece projects: the row is unchanged (existing test). A composed board gets a header row and one indented row per piece:

```
bass             composed board, 2 pieces (edits in board.json pieces)
  1 daddario-xpnd-1-extension.png  hole rects  2   edit boxes 0   edge segments 1   bounds set: right   [pieces]
  2 daddario-xpnd-1.png            hole rects  3   edit boxes 1   edge segments 0   no bounds           [none]
  ! pieces.old-board.png: no piece of the layout (kept)
  ! top-level boxes / bounds are shadowed by pieces.daddario-xpnd-1-extension.png
```

`[pieces]` / `[top-level]` / `[none]` = where the piece's edits come from (`piece_edits` rule). Implemented by extending
`project_rows` with a helper `piece_rows(pieces, edits, sources, boards_data, file_pieces, top_level_set)` (pure).

## 6. Tests (`tests/test_board_editor.py`, `tests/test_board_pieces.py`)

Pure, no display:
1. `piece_edits`: pieces entry wins, also for the first image; top-level for the first image only; others empty; duplicate image.
2. `layout_from_items` gives the same usable rects / holes as before for the existing pieces tests (no change; they stay green).
3. `board_pieces_for`: two `pedalboard` items in layout order with mm sizes; no layout -> one piece from the DB with `item` None;
   `board_image_for` still returns the first.
4. `resolve_piece`: `daddario-xpnd-1`, `daddario-xpnd-1.png`, `2`; unknown -> ValueError listing the pieces.
5. `split_for_save` one piece: top level, no `pieces`; an existing hand-written entry for that image moves to the top level.
6. `split_for_save` two pieces: all under `pieces`, top-level `[]` / no bounds; empty piece omitted; unknown-image entry kept;
   top-level migrated into the first image; shadowed top-level dropped with a note.
7. `dumps_edits` with pieces: one box per line, sorted images, no `bounds` key for edge bounds; `json.loads` round trip.
8. save -> `boards.load_piece_edits` round trip for two pieces (the build reads what the editor wrote).
9. guitar-gig byte-identical (the existing parametrised test, now via `split_for_save` too).
10. A file with a one-line `pieces` loads, and the editor re-dumps it in the new style with the same content.
11. `canvas_to_piece_frac` inverts `design.jack_point` for rot 0 / 90 / 180 / 270 (hand-computed points).
12. `rects_to_piece_fracs` clips and drops empty rects; rotated piece maps a canvas rect to the right image corner.
13. `composed_effective` / `piece_effective`: abutting pieces = each piece's own holes; a piece stacked over another's hole closes it
    unless both have one (hand-computed, like `test_a_hole_is_a_way_through_only_where_every_covering_piece_has_one`); one piece ==
    today's `effective_holes` in fractions.
14. `overlap_ghosts` / `joint_sides`: abutting (a joint side, no ghost), overlapping (ghost rect), apart (nothing); the bass geometry
    (0.19 mm gap counts as a joint with the 0.5 mm tolerance).
15. `piece_at`: point in one piece, in the overlap (topmost, then cycles with `after`), outside -> None.
16. `project_rows` for a composed board: header + one row per piece + `!` lines; single-piece row unchanged.
17. `main(["bass", "--piece", "nope"])` exits with the list (no display needed: the check runs before the window).

With a display (skipped otherwise, like today's app tests):
18. App with two pieces (two small PNGs passed in): switch with `_set_piece(1)`, edit, switch back, edits of both kept, `dirty`;
    `_save` writes both under `pieces`; reopen shows them.
19. Overview toggles on and off; a click maps to the right piece (`_overview_click` with a synthetic point).

## 7. Implementation steps (each a self-contained handover for a Sonnet agent)

Each step: branch `feat/board-editor-pieces`, `uv run pytest tests -q` green, no change to `catalog/`, `projects/` data or other
scripts than listed. A code review (Sonnet) after step 3, then the owner merges.

### Step 1: data layer (no GUI change)
- Goal: the editor's file side handles every piece; the build and the editor share one rule for "which edits belong to which piece".
- Files: `scripts/boards.py` (`piece_edits`, `load_piece_edits`), `scripts/jacks.py` (`layout_from_items` uses `piece_edits`;
  `data_crossing_errors` uses `piece_edits` for the project.json board image so a `pieces` entry for it counts), `scripts/board_editor.py`
  (`board_pieces_for`, `resolve_piece`, `piece_label`, `split_for_save`, `dumps_edits` pieces format, `save_edits(pieces=KEEP)`).
- Rules to copy into the handover: section 3 entirely; "pieces wins, also for the first piece; else top-level for piece 0"; fractions
  of each piece's UNROTATED image; one entry per line, 4 decimals; written only by the editor; guitar-gig byte-identical.
- Tests: 1-10 of section 6.
- Not to touch: the App class, `--list`, the routing / layout code beyond the one call in `layout_from_items`.

### Step 2: piece selection in the window, `--piece`, `--list`
- Goal: the owner edits every piece in the piece view.
- Files: `scripts/board_editor.py` only (+ `CLAUDE.md` line about `board.json` `pieces`: "Written by the board editor (every piece;
  composed boards under `pieces` keyed by image)", and the module docstring / `--help`).
- Content: `main` builds `pieces = board_pieces_for(...)`, `--piece`, `--image FILE` applies to the chosen piece; `make_app(project_dir,
  pieces, derived_by_image, start=0, image_paths=None)` (keep a thin compatibility path for the existing `make_app(dir, img, name, w,
  h, derived)` calls in the tests, or update those tests); per-piece state dict `{image: {"boxes", "bounds", "saved", "saved_bounds"}}`;
  `self.w_mm` / `self.h_mm` / `self.derived` / `self.img` of the current piece replace the closure variables; combobox; Tab /
  Shift+Tab; title and status; save all via `split_for_save` + `save_edits(pieces=...)`, notes to the status bar; `project_rows`
  per section 5.
- Tests: 16, 17, 18.
- Not to touch: the pure box / bounds helpers (their signatures), `boards.py`.

### Step 3: composed view: E, ghosts, joints, overview
- Goal: the owner sees the composed result.
- Files: `scripts/board_editor.py` only.
- Content: `canvas_to_piece_frac`, `rects_to_piece_fracs`, `composed_effective`, `piece_effective`, `overlap_ghosts`, `joint_sides`,
  `piece_at`; piece view draws ghosts and joint ticks, E uses `piece_effective`; edge-segment-on-a-joint status message; W overview
  (section 2.3), click selects a piece.
- Tests: 11-15, 19.
- Not to touch: data format, `boards.py`, `jacks.py`.

## 8. Risks

- Layout order: the first piece changes when the owner re-saves in Pedal Playground. Writing composed boards under `pieces` removes the
  dependency; a hand-written top level on a composed board is migrated on the first save (D1).
- Same image twice (two identical boards): one shared edit set, by the file format; flagged in the combobox (D5). A real need for
  different edits per instance would need a format change (key by layout item id), not planned.
- A piece removed from the layout keeps its `pieces` entry (D4): dead data the owner must delete by hand (or a later "prune" key).
- `--image FILE` (local PNG) now means one piece only; the others are fetched (network on first use, cached).
- Rotations other than multiples of 90 (Pedal Playground allows them) break `design._rotate`; out of scope (the build fails the same way).
- Per-piece dirty state across switches: easy to lose an edit if the save path writes only the current piece; test 18 covers it.
- Tk: `Tab` focus traversal, combobox stealing keys (`_guard` must include `ttk.Combobox`).
- The 0.19 mm gap between the bass pieces: a joint for `joint_sides` (0.5 mm tolerance) and for `design.inside_union` (its own `tol`);
  not an editor concern, just drawn.
- The GUI is only smoke-tested (display tests are skipped headless); keep logic in the pure helpers.

## 9. Decisions for the owner (implementation starts with the recommended defaults)

- D1. Where a composed board's edits are written. Default: ALL pieces under `pieces` (keyed by image, independent of the layout order);
  top-level `boxes` `[]`, no `bounds`. Existing top-level edits of a composed board move into `pieces[<first image>]` on the first save
  (dropped with a status note when that image already has an entry). Alternative: keep the first piece at the top level (today's split;
  breaks when the layout order changes).
- D2. Editing view. Default: one piece at a time in its own unrotated image (selector, Tab, `--piece`) plus a read-only whole-board
  overview (W) for the composed picture; click in the overview picks the piece. Alternative: edit directly on the composed canvas
  (rotations swap axes, overlapping pieces are ambiguous: much more code).
- D3. A single-piece board with a hand-written `pieces` entry for its own image. Default: moved to the top level on save (today's file
  shape). Alternative: leave it where it is.
- D4. `pieces` entries for images that are no piece of the layout. Default: kept unchanged and listed (`--list`, status bar).
  Alternative: dropped on save (the board might come back).
- D5. Two pieces with the same image. Default: one shared edit set, marked in the selector. Alternative: key `pieces` by layout item id
  (format change; item ids change when the owner re-creates an item).
- D6. Order of `pieces` in the file. Default: sorted by image name (stable diffs). Alternative: layout order.
- D7. E in the piece view. Default: the composed effective holes (what the build uses) clipped to this piece; for one piece identical to
  today. Alternative: this piece's holes alone (ignores a stacked piece's solid deck).
