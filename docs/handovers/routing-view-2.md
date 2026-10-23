# Handover: routing-view phase 2: parallel lanes (drawing geometry)

Branch `feat/routing-view` (checked out, phase 1 committed). Do not commit. Python 3.12, run everything with
`uv run` (`uv run pytest tests -q`, `uv run scripts/build.py`). Units: mm everywhere. Stdlib only.

## Goal
Cables that run along the same corridor are drawn side by side in lanes one cable width apart, ordered so they do not
cross inside the corridor, instead of on top of each other. Where a lane does not fit, they are drawn stacked (marked).
This is drawing geometry only: `min_mm`, `path`, statuses and findings do not change (owner: lane offsets do not
count towards the minimum length).

## Context (scripts/routing.py)
- `route_project` routes each signal cable on a grid, then `smooth(...)` reduces it to corners. Each routed cable has
  `c["path"] = lead_a[:-1] + corners + reversed(lead_b)[1:]`: the plug leads (jack -> bend -> exit, from
  `design.plug_geometry`) are fixed geometry, the `corners` part (exit_a ... exit_b) is the routed centreline.
  Keep the corners separately (e.g. `c["_corners"]` while routing, plus the lead lengths) so lanes can work on them.
- Helpers already there: `seg_rect_distance`, `point_rect_distance`, `point_seg_distance`, `polyline_length`.
  Smoothing rules to reuse: a segment stays at least min(cable radius, how close the original was) from every pedal
  rect (`pedal_rects`), and touches (within the radius) no plug the original did not touch (`plug_rects`
  {key: [rects]}, own plugs excluded).
- Routing area: `ctx["routing"]["grid"]` (x0, y0, nx * cell, ...) cut at `ctx["routing"]["front_y"]`.
- Routing width = `cfg["diameter_mm"]` (lane spacing, centre to centre).
- `routing.svg()` draws `c["path"]` for each signal cable.

## Tasks
1. Pure `lanes(routes, pedal_rects, plug_rects, area, width)`: `routes` = {cable id: (corners, own plug keys)};
   `area` = (x0, y0, x1, y1). Returns {cable id: {"corners": offset corners, "stacked": sorted ids it is drawn
   stacked with}}.
   - Segments of different cables form a pair when they are nearly parallel (angle <= 10 deg), their projections
     onto each other overlap by at least one `width`, and their centrelines are closer than `width` over that
     overlap. Pairs join into bundles (union-find over segments).
   - Per bundle: reference direction = its longest segment; each cable in it gets ONE lane index (also when several
     of its segments are in the bundle). Order the cables by the side they come from / go to: the signed
     perpendicular position (relative to the bundle line) of the cable's corner before entering and after leaving
     the bundle (sum of both; a cable that starts/ends inside uses its end point); ties by cable id (S2 < S10:
     natural order). Offsets (i - (k-1)/2) x width, i = 0..k-1, perpendicular to the reference direction.
   - Rebuild each offset polyline: a shifted segment's line is intersected with its neighbours' (shifted or not)
     lines to get the new corners (miter); nearly parallel neighbours (< 5 deg): the midpoint of the two shifted
     end points. The first and last corner (the plug exits) never move: the first/last segment, if shifted, gets
     an extra corner so the cable still starts/ends at the exit.
   - Validity per bundle: every changed segment satisfies the smoothing rules (pedals, plugs) and stays inside
     `area`. If a bundle is invalid, try once with half the spacing reduced so all lanes fit (spacing >= width / 2
     is still a lane); if still invalid, the bundle stays on the original centrelines and its cables get `stacked`.
2. In `route_project`, after all routing: `c["draw_path"] = lead_a[:-1] + lane corners + reversed(lead_b)[1:]` and
   `c["stacked_with"]` for every routed signal cable (no lanes: draw_path == path, stacked_with []). Remove the
   temporary keys at the end as the existing `_ends` / `_sides` are removed.
3. `routing.svg()`: draw `draw_path` instead of `path` (fallback `path`); a cable with `stacked_with` gets a dashed
   white line on top (stroke-dasharray) so stacked stretches are visible; add "white dashes: cables stacked on top
   of each other" to the legend sentence. Nothing else in the picture changes (phase 3 redoes the drawing).
4. Tests in `tests/test_routing.py` (style: hand-computed numbers in comments):
   - Two cables along the same straight line in open space -> offsets +-width/2, parallel, centre distance = width,
     the exits unchanged.
   - Ordering: the cable entering from above gets the upper lane, and the lanes do not cross inside the bundle
     (check the offset segments do not intersect).
   - A bundle squeezed between two pedals with no room for lanes -> stacked, centrelines unchanged.
   - Three cables -> offsets -width, 0, +width.
   - Crossing (non-parallel) cables are not bundled.
   - `route_project`: `min_mm` and `path` identical with and without lanes (lanes only fill `draw_path`).
5. Run all tests and the build; report for guitar-gig: how many bundles, lanes and stacked bundles, and which
   cables are stacked where. Look at `projects/guitar-gig/cables.svg` (rasterise it with Pillow? not needed: read
   the coordinates) and say whether any lane looks wrong (lanes crossing, a lane through a pedal).

## Constraints / do not touch
- Keep routing.py's compact style (docstrings, comments where non-obvious). Pure functions, stdlib only.
- Do not change `min_mm`, `path`, statuses, findings, the router, smoothing, layout.py, propose_layout.py, the
  catalog or project data. Do not rename `cables.svg` (phase 4). Generated files change only by running the build.
- Do not commit. Do not edit CLAUDE.md or docs/TODO.md.

## Acceptance
- All tests pass with the new ones; build runs; guitar-gig README lengths unchanged (compare before/after);
  short report: what changed, the guitar-gig bundle summary, doubts.
