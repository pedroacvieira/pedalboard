# Handover: DC plug may pass under one signal plug; DC exit offset (`feat/dc-under-signal`)

Repo `/home/pvieira/projects/pedalboard`, on `main` (clean). First: `git switch -c feat/dc-under-signal`. Python 3.12, `uv run`
only (`uv run pytest tests -q`, ~150 s; `PEDALBOARD_SLOW=1 uv run pytest tests -q -k gig`, ~55 s; `uv run scripts/build.py`, exit 0).
No new dependencies. Commit on the branch when everything is green (message ends with
`Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`); do not merge into main, do not push.

## Owner decisions (2026-11-03)
1. **Exit offset.** `catalog/cables.json` `dc_ra_owner_baseline.plug.exit_offset_mm` = 8.4 (owner's rule of thumb: 70% of the
   12 mm outwards clearance; today null -> depth/2 = 6). Not measured: do not add it to `verified`; say "owner rule of thumb, 70%
   of head_depth, 2026-11-03" in its notes / sources. Only this type.
2. **A DC plug may pass under ONE signal plug.** Real angled DC plugs get plugged diagonally (between a side and down) and pass
   under a neighbouring signal plug; a power cable always goes under the signal cables. Model (no 3D, no diagonal orientation):
   - An overlap between a **right-angle** DC plug's footprint (any option: left / right / down; DC plugs of pedals and of
     on-board supply ports) and a **signal** footprint (a modelled patch plug, or the fixed audio box of a first input / last
     output / extra jack: anything that is not a DC plug) is **not a collision** ("passes under").
   - At most one such pass per DC plug and per signal plug (a one-to-one pairing). Further overlaps are collisions as today.
     Pairing must be deterministic: e.g. per DC plug its deepest signal overlap, DC plugs in natural key order, a signal plug
     already paired is not available again.
   - Unchanged: straight DC plugs; DC vs DC; any plug vs a pedal body / outline (blocked parts, `hits`); feasibility; the
     `down` preference; `max_over_plug` and stacking (power cables are already on their own grids and not counted there).
   - Same pedal or neighbour does not matter.

## Code (scripts/routing.py unless noted)
- `collision_count(opt, own_key, taken)` (~1497): counts overlapping (part, footprint) pairs; used by the plug ranking
  (`plug_rank` ~2498, `choose_signal` ~1847, `refine_dc_sides`) and by the surrogate (`layout.py` `_count` ~765). The rule
  must apply in the ranking of BOTH ends: a DC option whose only overlap is one signal plug is collision-free, and a signal
  option overlapping one DC plug is too (subject to the pairing). Needs to know which keys are DC plugs and which plug type
  style they have: `dc_plug_jacks` (~1510) / `power_plug_keys` list them; the option carries its type.
- `plug_collision_findings` (~1625): pairs that pass under are not findings and not in `ctx["plug_collisions"]`; record them in a
  new `ctx["plug_under"]` [{"dc": key, "signal": key, "depth_mm"}] instead.
- README (`scripts/build.py`): one short line per pass, e.g. `P5 (analog_chorus.power) passes under the plug at
  analog_chorus.out: plug it diagonally`, near the clearance / collision section. `routing.svg` (`scripts/svgdraw.py`): draw power
  cables below signal cables if they are not already; optional: mark a pass (no new legend clutter).
- `scripts/layout.py` surrogate: `_collisions` (~673), `_count` (~765), `_resolve` (~779): same rule so the search stops penalising
  a one-plug pass; the proposal gate on `collisions` then follows automatically. Keep surrogate and build agreeing
  (`tests/test_layout.py` gig agreement tests: collision pairs must still match the build exactly; do not loosen them).

## Tests
Hand-made: DC right-angle plug overlapping one signal plug -> no collision, one `plug_under`; overlapping two signal plugs -> one
pass + one collision; two DC plugs over the same signal plug -> one pass + one collision; straight DC plug -> collision; DC vs DC ->
collision; DC plug into a pedal body -> still blocked; ranking: a side whose only overlap is one signal plug ties with a free side
(then length decides); surrogate agrees on a small layout. Exit offset: a hand-computed `design.plug_geometry` measure with 8.4.
Update exact-number tests that change because of the offset or the rule (say which and why). Gig fixture: report collisions
before/after and the `plug_under` list.

## Docs
CLAUDE.md: the plug-orientation bullet (collisions: the pass-under rule, `ctx["plug_under"]`) and the cable-types bullet
(exit offset 8.4, rule of thumb). `docs/TODO.md`: note the decision and that diagonal / height modelling stays out.

## Report
Files and functions changed, gig fixture and live gig: collisions before/after, passes, DC total min length before/after, test
counts, anything you decided yourself.

## Do not touch
`projects/*/playground_design.json`, project.json power wiring, other catalog entries, the test fixture's data.
