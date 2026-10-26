# Handover: pedal-outlines phase 2: route and check clearance against the outlines

Branch `feat/pedal-outlines` (checked out; phase 1 is in the working tree, uncommitted: keep it). Do not commit.
Python 3.12, `uv run` everything (`uv run pytest tests -q`, `uv run scripts/build.py`). Units: mm. Stdlib + Pillow.

## Goal
Pedals are obstacles by their real outline (a few rects per item, phase 1: `layout["shapes"]` {item id: [canvas
rects]}, fallback = the bounding box) instead of their Pedal Playground box, for cable routing AND plug clearance,
in the build and in the layout surrogate. Pedal-pedal overlap stays box-based.

## Decisions (owner)
- Outlines for routing AND plug clearance (build and layout surrogate agree).
- Layout feasibility (`layout.Model.feasible_one`, `free_distance`, swaps, board edges) keeps the bounding box.
- Missing outline = box (conservative), mentioned once in the README (not a warning).

## Context
- `scripts/design.py`: `footprint(item)`, `outline_rects(item, outlines)`, `overlap(a, b)` -> (dx, dy) or None,
  `part_depth(part, facing, side, ov)`.
- `scripts/jacks.py`: `layout_from_items` returns "shapes"; `check(...)` computes the fixed clearance box per used
  jack against `design.footprint(ob)` for every obstacle (~line 330).
- `scripts/routing.py` `route_project`: `build_grid(board, [design.footprint(o) for o in obstacles], front_y, cfg)`;
  `front_y` = max footprint bottom of the placed pedals (capped at the board); `pedal_rects = [design.footprint(o)
  ...]` for `smooth` / `lanes`; `blocked_parts(opt, own_id, obstacles)` overlaps plug part rects with each obstacle
  footprint -> [(part, obstacle item, ov)]; `deepest_hits` keeps the deepest part per obstacle;
  `power_plug_choices` ranks options by hits and overlap.
- `scripts/layout.py` `Model`: `_geom[(n, rot)]` holds per-pedal geometry relative to the centre ("half", plug
  options...); `fixed_feet` [(title, rect)]; `_opt_clearance` measures plug parts (grown by a margin) against
  `feet` / `fixed_feet` (penetration per obstacle = max over parts of min(ov)); `score` also uses `feet` for the
  routing area / signal detour estimate.
- `scripts/common.py` `proposal_inputs_sha1(pdir)`: hash of what proposals depend on (design file, project.json,
  cables, the project's catalog entries incl. jacks and footswitches).
- `scripts/svgdraw.py`: pedals drawn as outline rects (phase 1) + dashed box; touching rects show faint seams.
- `scripts/build.py` ~line 697: README sentence "Pedal footprints are the image bounding boxes, so rounded corners
  count as occupied ..."

## Tasks
1. routing.py: grid obstacles, `front_y` and `pedal_rects` (smooth, lanes) from the shapes (flattened);
   `blocked_parts(opt, own_id, obstacles, shapes=None)`: overlaps against each of the obstacle's shape rects
   (fallback footprint), one hit per (part, obstacle) with the largest overlap (by min(ov)); `deepest_hits` and the
   power side ranking unchanged otherwise. Pass shapes everywhere `route_project` calls it.
2. jacks.check: the fixed box against the obstacle's shape rects (deepest over its rects), same messages.
3. layout.py: per pedal and rotation, the shape rects relative to the centre in `_geom` (like "half"), fixed items'
   shapes alongside `fixed_feet`; `_opt_clearance` measures against the shapes (per obstacle: max over its rects
   and the plug parts, as today per footprint); keep a cheap bounding-box reject first (the footprint) so the search
   does not slow down. Feasibility, `free_distance`, swaps, routing area and the detour estimate stay box-based.
   The surrogate must keep reporting the same blocked plugs as the build for the owner's layout (an existing test
   checks the surrogate against the build: keep it passing).
4. `common.proposal_inputs_sha1`: include the outline entries of the images used in the project's design file.
5. svgdraw: draw each outline as ONE path along the union boundary of its rects (no seams): e.g. collect the rects'
   distinct x and y coordinates, mark covered grid cells, emit the boundary edges between covered and uncovered
   cells, chain them into closed loops, merge collinear edges. A pure helper `union_outline(rects) -> [loops]` with
   tests (two touching rects -> one loop of 6 or 8 points; L-shape; separate rects -> two loops).
6. build.py README: replace the footprint sentence: pedals are their outlines from the images
   (`catalog/outlines.json`, `uv run scripts/outlines.py` to add or refresh), the Pedal Playground box only where
   an outline is missing (list those items once: "no outline: <titles>"); the layout keeps the boxes for overlaps.
7. Tests: routing around a shape with a notch (a corridor that only exists in the outline), plug clearance against
   a shape (a plug that overlaps the box but not the outline -> no hit; overlapping the outline -> hit with the
   depth into the outline), jacks.check fixed box likewise, layout surrogate clearance with a shape, the hash
   changes when an outline entry changes, `union_outline`.
8. Run all tests (incl. `PEDALBOARD_SLOW=1 uv run pytest tests -q -k slow` once if it finishes in a few minutes)
   and the build. Before your changes, save the guitar-gig README; after, report per cable the min length
   before/after, which cables are no longer stacked (`stacked_with`), clearance findings before/after (the three
   known: monk.out / monk.power blocked by the Belle Epoch, red_muck.power by the Analog Chorus), build time.
   Render routing.svg with headless Chrome and check it.

## Constraints / do not touch
- Feasibility stays box-based; do not change weights, the search, the power policy, catalog data (other than nothing)
  or project data. Do not rerun propose_layout. Generated files change only by running the build.
- Keep the repo's compact style. Do not commit. Do not edit CLAUDE.md or docs/TODO.md.

## Acceptance
- All tests pass (+ new ones); the build runs; the report of task 8 and doubts.
