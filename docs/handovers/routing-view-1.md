# Handover: routing-view phase 1: plug-head limit + path smoothing

Branch `feat/routing-view` (already checked out). Do not commit. Python 3.12, run everything with `uv run`
(`uv run pytest tests -q`, `uv run scripts/build.py`). Units: mm everywhere.

## Goal
1. Other cables may cross a plug (head/barrel) only up to a limit: new setting `cables.max_over_plug` (default 2).
2. Each routed signal path is reduced to its necessary corners (any-angle straight segments), and its minimum length
   follows the smoothed path.

## Context (scripts/routing.py, read it fully first)
- `settings()` merges `DEFAULTS` with project `cables`. `build_grid` blocks cells whose centre is inside a pedal
  grown by `grow = max(0, diameter/2 - grid/2 - 0.01)` (`Grid.block_rect`); `grid.body` = centre inside the body.
- `route_project`: chooses plug sides per signal cable (`chosen[id] = (oa, ob)`, options from `end_options` /
  `design.plug_geometry`: `o["rects"]` = [(part, rect)] with parts "head", "barrel" (right-angle only), "cable"
  (the straight lead, NOT part of the plug); `o["lead"]` jack -> bend -> exit; `o["exit"]`; `o["measure_mm"]`).
  Then `route_all(grid, nets, max_stack, iterations)` (negotiated congestion), then the path is
  `lead_a + cell centres + reversed(lead_b)` and `min_mm = measure_a + measure_b + |exit_a - first centre| +
  path_length + |last centre - exit_b|`.
- `power_plug_clearance` (called after routing) picks each power plug's side from pedal obstacles only and appends
  `{"cable": P#, "rects": ...}` to `ctx["routing"]["heads"]` (signal heads are appended there too).
- Findings go to `sink` (warnings, errors with `validation.strict_routing`), worded like the existing routing ones.

## Tasks
1. `DEFAULTS["max_over_plug"] = 2` (doc comment: other cables allowed across one plug, head + barrel).
2. Plug heads before routing: compute the power plug sides BEFORE `route_all` (split `power_plug_clearance` into a
   side choice + the clearance reporting, or compute the options early and reuse them: keep its findings and
   behaviour identical). Collect every plug of the layout: key `"<pedal id>.<jack id>"`, owner cable id (S#/P#,
   or None), cells = grid cells whose centre lies inside its head/barrel rects grown by the same `grow` as pedals.
3. `route_all(grid, nets, max_stack, iterations=40, plugs=None, max_over_plug=2)`: `plugs` = {key: (owner, cells)}.
   A net entering a cell of a plug it does not own, where that plug already has `max_over_plug` OTHER cables (owner
   excluded, this net excluded), pays the same over-limit penalty as an over-stacked cell; plugs still over the limit
   after the rounds get history cost like overflow cells. Return value: add a 4th item `plug_over` = {key: [cable
   names]} for plugs over the limit (update every caller and the existing tests' unpacking). A cable never counts
   against its own plugs. Default `plugs=None` keeps today's behaviour exactly.
4. In `route_project`, a routing finding per plug over the limit: `routing: S3, S5 and S7 cross the plug at
   monk.power (limit 2 other cables)`; the affected cables get status `routed, over the plug limit` (unless
   already worse).
5. Pure `smooth(points, obstacles, radius, plugs, own_plugs=())`: `points` = [exit_a, cell centres..., exit_b];
   `obstacles` = pedal rects (x0, y0, x1, y1); `plugs` = {key: [rects]} (head/barrel). String pulling: from anchor
   i, try j = i+2, i+3, ... and accept j while the segment (p_i, p_j) is valid; stop at the FIRST invalid j (do not
   skip ahead), the last valid j becomes the next corner. Valid segment (p_i, p_j): (a) for every obstacle,
   dist(segment, rect) >= min(radius, min over the replaced points p_i..p_j of dist(point, rect)) - 1e-6;
   (b) every plug the segment touches (segment within `radius` of a plug rect) is also touched by one of the
   replaced points' consecutive segments, or is in `own_plugs`. Return the corner list (first and last point kept).
   Write small helpers `seg_rect_distance` (exact: 0 if they intersect) and reuse them.
6. Use it in `route_project`: the grid part of each routed cable is smoothed (obstacles = every pedal footprint in
   `layout["obstacles"]`, radius = cfg diameter/2, plugs = all plugs, own plugs = the cable's two ends). `path` =
   `lead_a[:-1] + smoothed + reversed(lead_b)[1:]` (no duplicate exit points); `min_mm = measure_a + measure_b +
   polyline length of smoothed`. Stacking/overflow stays as computed on the grid paths.
7. Tests in `tests/test_routing.py` (style: small hand-made grids, `plug_ctx`, hand-computed numbers in comments):
   - `smooth` on an open field: a staircase becomes the single segment, length = hypot.
   - L around a pedal corner: one corner kept, near the grown corner; the result never passes closer than the
     radius to the pedal.
   - A squeezed sub-path (points closer than the radius) is not made closer.
   - The plug rule: a shortcut across a plug the grid path did not cross is refused; across an own plug allowed.
   - `route_all` with a plug: three nets forced across one plug with limit 2 -> one detours if it can; if it cannot,
     `plug_over` names the plug and the three cables; the owner never counts.
   - `route_project`: `min_mm` after smoothing <= the old formula (keep `test_router_picks_the_shorter_exit_sides`
     passing, adjust its numeric bounds only if needed with a comment giving the new hand-computed value).
8. Run `uv run pytest tests -q` (all pass) and `uv run scripts/build.py`; report how the guitar-gig signal lengths
   changed (before/after per S#, from the generated README table: run the build once BEFORE your changes and save
   the table to compare) and any new plug-limit findings.

## Constraints / do not touch
- Pure functions, stdlib only. Keep the code style of routing.py (compact, docstrings, comments where non-obvious).
- Do not change the SVG drawing, file names (`cables.svg` stays for now), layout.py, propose_layout.py logic, the
  catalog or project data. Generated files may change only by running the build.
- Do not commit. Do not edit CLAUDE.md or docs/TODO.md (the coordinator does).

## Acceptance
- All tests pass, new tests as above; build runs; lengths per cable equal or shorter than before; a short report:
  what changed, before/after lengths, new findings, anything you were unsure about.
