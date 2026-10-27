# Handover: fix the code review of feat/supply-placement

Branch `feat/supply-placement` (checked out, everything committed). Do not commit; the reviewer commits.
Python 3.12, `uv run` only; tests `uv run pytest tests -q`; build `uv run scripts/build.py`. Never edit
`projects/*/board.json`, `projects/*/project.json`, `playground_design.json`, catalog data. Do not regenerate
proposals. No new dependencies. Do not edit CLAUDE.md / docs.

Fix each finding below (line numbers are approximate), with a test per behavioural fix (hand-computed, small
synthetic cases like the existing tests). Report per finding: fixed / not changed, and why.

1. **Hole edits missing in the search** (`scripts/layout.py` ~187 `Model`, `scripts/propose_layout.py` ~105
   `evaluate`): `jacks.layout_from_items` is called without `board_edits`, so the power estimate (Model.power_setup,
   `power.estimate_setup` / `usable_points`) uses catalog/boards.json without the project's `board.json`
   (`boards.load_edits(project_dir)`); only `jacks.check` passes them. Pass the edits everywhere a layout is built for a
   project (Model gets them from its caller: propose_layout knows the project dir; keep a default of none).
2. **`boards.usable` does not check `edge_transit_mm`** (`scripts/boards.py` ~236; `routing.route_power` ~1356 does
   `float(edge_t)`): validate it like `hole_transit_mm` (number, not bool, >= 0) and drop invalid values, so a
   hand-edited file cannot crash a build or shorten cables.
3. **`under_board` per hop** (`scripts/jacks.py` ~435): every hop of a daisy chain gets the supply's placement, but
   pedal-to-pedal hops start on top. Set it only for the first hop (supply port -> first pedal); daisy hops False
   until routed. With power routing the router's value wins as now.
4. **Supply port outside the board** (`scripts/routing.py` ~1390): the check uses `ug.inside(cell)` (grid bounds,
   includes the left/back margin). Use the board footprint (the under layer's area) so a port off the board gives
   the "unroutable: outside the board footprint" finding.
5. **Tight power heuristic not admissible across edge links** (`routing.py` ~418 `Under.tight`): make it admissible
   (e.g. subtract one cell x the layer's cost factor where an edge link can also move a cell, or use min(pass_cost,
   edge cost) and drop the step), and fix the comment. Keep power routing time about as now (report gig time).
6. **Estimate ignores the under layer** (`scripts/power.py` ~173 `usable_points`, `layout.py` Model `pw_blocked`):
   hole points must also be free UNDER the board (not inside an under-board supply's outline grown by the power cable
   radius), as `routing.hole_cells` requires. Under-board supplies do not move in the search, so precompute that once.
7. **`metrics.power_mm` mixes routed and estimated** (`propose_layout.py` ~61): sum routed `min_mm` only and count
   the unrouted power cables separately (e.g. `power_unrouted`), shown in the README proposals table (a column or a
   note) so a proposal cannot look shorter by falling back to the estimate.
8. **boards.json re-read per finalist** (`propose_layout.py` ~105 and ~128): load `boards.load()` and the project's
   edits once in main and pass `board_data` (and edits) to `layout_from_items` and `build.validate` (it already has
   `board_data=`; add what is missing for edits only if needed).
9. **Two nearest-hole implementations** (`power.py` ~229 `nearest_usable` vs `HoleIndex`): `assign` / `hop_estimate`
   should use the `HoleIndex` (wrap the filtered points) instead of a linear scan; keep one implementation if
   possible (tests that compare them may then go).
10. **Duplicated post-processing** (`routing.py` ~1324 `route_power` vs `route_project`): extract the shared part
    (state path -> per-layer stretches, smoothing, path/draw_path, min_mm, per-layer over-limit messages) into one
    helper used by both. Signal and power results must stay identical (diff the README tables before/after).

## Acceptance
- `uv run pytest tests -q` all pass; `uv run scripts/build.py` runs. Report the README diff for guitar-gig (expected:
  none from 1-5, 7-10 for the routed results; 3 may change the "Under board" column only where power is not routed).
- Report the `uv run scripts/propose_layout.py guitar-gig --score` total before/after (6 and 1 may change it) and
  the timing of `--score`.
