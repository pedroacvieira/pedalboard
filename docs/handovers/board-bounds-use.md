# Handover: use the board bounds in the build, the router and the layout search (`feat/board-bounds`, steps 1-2)

## Goal
Each project's `board.json` may now hold `bounds` (four lines: where pedals may sit; drawn by the owner in the board
editor). Make the build, the cable router (signal and power), the drawings and the layout search use them. The
guitar-gig board has them (back 12.0 mm and front 8.5 mm in from the image edges; left / right at the edges); bass and
guitar-practice have none and must come out exactly as today.

## Where you work
- Git worktree `/home/pvieira/projects/pedalboard-board-bounds`, branch `feat/board-bounds` (checked out). Work ONLY
  here; never touch any other checkout.
- `.cache/` is a copy (git-ignored) of the Pedal Playground cache; keep it.
- Python 3.12 via uv: `uv sync` once, then `uv run ...`; never `pip install`. Tests: `uv run pytest tests -q`
  (~600 tests, ~100 s; must stay green). Build: `uv run scripts/build.py`.
- Do NOT commit. Leave the changes uncommitted and report; the owner reviews first.
- Background (only if a detail is unclear): `docs/plans/board-bounds.md`.

## What exists
- `boards.load_bounds(project_dir, warnings=None)` -> `{"back", "front", "left", "right"}`: fractions of the UNROTATED
  board image; back / front measured from the image's TOP edge, left / right from its LEFT edge; defaults = the image
  edges (0, 1, 0, 1); invalid -> a warning and the defaults.
- `design.board_holes(board_item, holes, edits)` / `design.board_edges` map image fractions to canvas mm with the
  board's rotation (`design.jack_point`); `design.footprint(item)` = the item's canvas box.
- `jacks.layout_from_items(..., board_data=, board_edits=)` builds `layout` (board, placed, obstacles, shapes, holes,
  edge_segments, inst_item, inst_placement...). Callers: `jacks.check` (~line 401-404, reads `boards_mod.load_edits`),
  `layout.Model.__init__` (~line 200-215), `propose_layout.evaluate` / `main` (~line 106-112, 218-230).
- Router: `routing.front_limit(board_rect, foot_bottoms, cfg)` and `routing.build_grid(board_rect, obstacles, front_y,
  cfg)` (routing area = board footprint + `edge_margin_mm` at back and sides, cut at `front_y`); signal routing in
  `route_project` (~line 1672-1688: `board = design.footprint(layout["board"])`, `build_grid`, `build_under`); power
  in `route_power` (~line 2071: `build_grid(board, ...)`, `under_grid`, `edge_links`). `edge_links(top, ug, board_rect,
  segments, ...)` joins an under-board border cell to the top cell just OUTSIDE the board border.
- Layout search: `layout.Model.board` (footprint) used by `feasible_one` (~line 480: inside the board shrunk by
  `board_margin_mm`) and `free_distance` (~line 1236); the surrogate's routing area in `Model.score` (~line 805-812:
  `front_limit(b, ...)`, `area = (b[0] - em, b[1] - em, b[2] + em, front_y)`).
- Drawing: `svgdraw.py` ~line 574 (`routing.svg`: `bx = design.footprint(layout["board"])`, `routing_area(...)`) and
  ~line 646 (`power.svg`); proposal SVGs use the same renderer.

## Required behaviour (owner decisions, 2026-10-29)
1. **Geometry**: `design.board_bounds(board_item, bounds)` -> usable rect (x0, y0, x1, y1) in canvas mm, rotation-aware
   like `board_holes` (test 0 / 90 / 270). `layout_from_items` takes `board_bounds=None` and returns
   `layout["usable"]` (= the board footprint when None or at the edges). Every caller passes
   `boards.load_bounds(project dir)` (the build, `layout.Model`, `propose_layout`; read once per run like
   `board_edits`).
2. **Build warning**: every item on top of the board (`layout["obstacles"]`: chain pedals, other pedals, ON-BOARD
   supplies) whose Pedal Playground box (`design.footprint`) lies outside `layout["usable"]` ->
   `layout: <pedal name or title> is outside the usable board area by N mm (back)` (worst side and depth, 1 decimal;
   one finding per item). A warning; `validation.strict_bounds: true` makes it an error (add the flag where the other
   validation flags are documented / scaffolded: `build.py` text ~line 987, `new_project.py`). UNDER-board supplies are
   never checked (decision: the owner's under-board supply placement is kept even outside the bounds).
3. **Routing area** (signal and power grids, decision: cables may go over the edges as before, with a small margin
   computed from the usable area): the top area = `layout["usable"]` grown by `edge_margin_mm` at the back and the
   sides; front: `front_limit` with the usable rect (nothing in front of the lowest pedals; with
   `cables.route_in_front` the usable front + margin). Implementation: keep the top grid's extent as today (board
   footprint + margin, so the cell indices of the top and under grids keep matching) and BLOCK the top cells outside
   the grown usable area, except a strip along each usable edge segment (`routing.usable_edge_segments`): the
   rectangle spanning the segment along its side, from the grown usable area out to the board border + margin, so
   `edge_links` still finds a free top cell just outside the border. The under-board grid stays the whole board
   footprint (unchanged). Hole cells outside the grown area are only usable where their top cell is free (existing
   rule). Without bounds the grid must be cell-for-cell identical to today.
4. **Layout search** (`layout.py`): `feasible_one` and `free_distance` use the usable rect (shrunk by
   `board_margin_mm`) instead of the board footprint, for pedals AND movable on-board supplies; the surrogate's
   routing area (`Model.score`) follows point 3 (the grown usable area; the edge strips may be ignored there, it is an
   estimate: say so in a comment).
5. **Owner's layout outside the bounds** (`propose_layout.py` / `layout.py`): the search starts from the owner's
   state. If a pedal of it is outside the usable area, the start is infeasible: first move each such pedal to the
   nearest feasible position inside (same rotation; try growing distances; counted as a move by the move cost). If a
   pedal cannot be placed, print a clear message and stop (`sys.exit` with the pedal names), do not crash. Find out how
   today's code treats an infeasible owner state (overlaps) and stay consistent with it.
6. **Proposal metrics** (`propose_layout.py` meta + `build.py` README "Layout proposals" table): a row "Outside the
   usable area" = the number of items of point 2 for the owner's layout and each proposal (proposals: always 0).
   Old `meta.json` files without the field must still render (show "?").
7. **Drawing** (`svgdraw.py`): when the project has bounds that differ from the board edges, draw the usable rect as a
   dashed outline (own colour, e.g. teal `#00897b` as in the board editor) in `routing.svg`, `power.svg` and the
   proposal SVGs, with a legend entry "usable board area (pedals stay inside)". The routing area drawing follows the
   new area (draw the grown usable area instead of the full grid extent).
8. **README text** (`build.py`): the sentence that describes the routing area ("Signal cables are routed on the board
   surface ... at most N mm beyond the back and sides") says "beyond the usable board area" when bounds exist; the
   layout proposal intro mentions that pedals stay inside the usable area.
9. **Docs**: `CLAUDE.md` (the `board.json` bullet's last sentence: now used; the "Cable routing" routing-area sentence;
   the "Layout proposals" bullet: never outside the usable area, `strict_bounds`), `docs/TODO.md` section 2: tick
   "Usable board area" with a one-line done note (keep the open owner step "re-run the gig proposals").

## Tests (hand-computed, small boards; follow the style of the existing tests)
- `design.board_bounds`: rotations 0 / 90 / 270, defaults = footprint.
- Build warning: a pedal 5 mm past the back line -> warning with "back" and 5.0 mm; `strict_bounds` -> error; an
  under-board supply outside -> nothing; no bounds -> nothing.
- Routing: no bounds -> the grid's blocked set identical to today's; with bounds a cell outside the grown usable area is
  blocked, a cell in an edge segment strip is free and `edge_links` still returns links there.
- Layout: `feasible_one` rejects a pedal outside the usable rect; `free_distance` stops at the bound; an owner state
  with a pedal outside is moved inside before the search.
- README: the proposal table row (with and without the field in meta).

## Acceptance
- `uv run pytest tests -q` green.
- `uv run scripts/build.py` exits 0. `bass` and `guitar-practice` generated files unchanged (`git diff --stat`).
  guitar-gig: report which of the owner's pedals are outside its bounds (warnings) and how signal / DC totals change
  (README "Signal cables, routed minimum" and "DC cable, minimum") versus before.
- `uv run scripts/propose_layout.py guitar-gig --dry-run` and `--max-change rearrange --seed 42 --dry-run` run and
  print proposals with 0 items outside (do NOT run without `--dry-run`: the owner regenerates proposals after review).

## Do not touch
`scripts/board_editor.py` and `boards.load_bounds` (done), catalog data, `projects/*/board.json`,
`projects/*/playground_design.json`, `projects/*/project.json` (no `strict_bounds` in any project), the proposals'
files.

## Report back
Files changed, design decisions you made (especially points 3 and 5), test results, the gig numbers before / after and
its warnings, the dry-run results, anything open.
