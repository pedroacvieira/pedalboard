# Handover: plug-orientation phase 4, the layout surrogate learns down plugs, plug collisions and DC plug types

Branch `feat/plug-orientation` (checked out; do not commit, the coordinator commits). Python 3.12, `uv run` only
(`uv run pytest tests -q`, ~60 s; `PEDALBOARD_SLOW=1` adds the full gig search). Never `pip install`.

## Goal
The build (`scripts/routing.py`) now has three plug features the layout search's surrogate (`scripts/layout.py`,
class `Model`, `score`) does not know yet. Bring the surrogate in line, cheaply, so the search sees what the build
will report. Finalists are still checked with the full build (`propose_layout.py`), so the surrogate may approximate.

## What the build does (the reference; read these functions in `scripts/routing.py`)
1. **Plug collisions**: every used plug's footprint (chosen option's rects: head, barrel, cable run; the fixed
   audio / power box of jacks without a plug model: first input, last output, extra jacks) must not overlap another
   jack's footprint (`design.overlap`, TOL). Side choice counts a collision like a blocked part. Findings in
   `ctx["plug_collisions"]`; `propose_layout.py` metrics already have `collisions` and gate on it.
   (`collision_count`, `fixed_footprints`, `plug_collision_findings`.)
2. **Down exit** for right-angle plugs (signal and power): available when `routing.down_available(holes,
   under_rects, bend point, cable diameter)` (holes = `layout["holes"]`, under_rects = the under-board supplies'
   outline rects; both FIXED during the search: under-board supplies do not move). Footprint = the head only.
   `measure_mm` = |exit_offset - depth/2| + `cables.jack_height_mm` (12) + hole transit; the cable then starts / ends
   UNDER the board at the bend point. Owner rule: **always down when available**, even if longer. `end_options(...,
   down=callable)` adds the option (see how `route_project` builds the callable).
3. **DC plug types**: `cfg["power_types"]` (`routing.settings`, default [power_type]); per power plug the type and exit
   are ranked by `routing.plug_rank`: feasible (exit not inside another pedal, inside the area), down, blocked +
   collisions, overlap, list order; a serial cable shares one pedal-end type (the surrogate may ignore that rule:
   per plug best type is fine, say so in the docstring).

## What to change in `scripts/layout.py`
- `_geometry` / `_supply_geometry`: build the plug options with the down option too (its availability depends on the
  candidate position: keep the option with its bend point relative to the centre, test availability per candidate in
  `score` with `down_available` on the shifted point; memoise per (rounded point, diameter) if it is slow) and with
  every power type in `power_types` (per power jack: options of each type, each tagged with its type and list index).
- Choice per end in `score`: down first when available (as the build), else today's choice (lowest clearance + cable
  cost for signal ends, lowest clearance for power plugs; with several types, ties by list order). The routing-area
  check: a down end is never "outside the routing area".
- Signal length with a down end: measure_mm (already includes jack height + transit) + an under-board estimate: from
  the bend point under the board to the other end: if the other end is also down, the straight / octile distance under
  the board (no pedals in the way: no detour term); else the nearest usable crossing near the other end's exit
  (`power.hop_estimate`-style: under distance + a pass + the top distance; reuse `power.Crossings` / the model's
  `power_setup` if suitable, the signal cable's hole transit) — keep it simple and document it.
- Power estimate (`power` term, `power.hop_estimate`): a down plug at the target ends under the board (no pass up);
  a down plug at a serial hop's source starts under (`src_under`).
- Collisions: after the per-end choice, add a collision cost for overlapping footprints of DIFFERENT jacks (the
  chosen options + the fixed boxes the model already has in `g["extra"]`): the same weights as clearance (real
  penetration `w["clearance"]` / mm, `w["clearance_hit"]` per colliding pair; margin as `_opt_clearance` does if easy).
  Prefilter by bounding boxes (most pairs are far apart); the gig search must not get much slower (measure:
  `time uv run scripts/propose_layout.py guitar-gig --seed 1` before/after, today ~15 s; tell me both numbers). With
  `detail=True` return `det["collisions"]` [{"jack", "with", "depth_mm"}] like `det["blocked"]`.
- `--score` output (`propose_layout.py`): print the collision count next to "Blocked plugs".
- Module docstring: the clearance term mentions down, collisions and types.

## Tests
- Extend `tests/test_layout.py` (synthetic types / hand-made models where possible; look at the existing helpers):
  down chosen in the surrogate when a hole is under the bend point and not when the pedal moves off it; a collision
  between two plugs on one pedal costs and is listed; two power types: the surrogate takes the type the build takes
  in a simple case.
- The gig check `test_surrogate_blocked_plugs_match_the_build_on_the_gig_layout` (surrogate blocked == build
  violations, margin 0) must keep passing; add the same check for collisions (surrogate collisions vs build
  `plug_collisions`, as sets of jack pairs). If they cannot match exactly (the build chooses signal sides in chain
  order with collisions; the surrogate per end), make them match where you can and explain the residual in the test.

## Acceptance
- `uv run pytest tests -q` passes, and `PEDALBOARD_SLOW=1 uv run pytest tests -q -k gig` too.
- `uv run scripts/propose_layout.py guitar-gig --score` prints the new figures; timing before/after reported.
- Do NOT regenerate `projects/*/proposals/` (the coordinator does it); if a test run writes there in a tmp copy, fine.
- Short report: changes per file, decisions, the gig surrogate vs build match, timing, open points.

## Do not touch
`scripts/routing.py` except tiny helpers you need to share (say which), `catalog/`, `projects/*/project.json`,
`playground_design.json`, `projects/*/proposals/`, CLAUDE.md, docs/TODO.md, the plan.
