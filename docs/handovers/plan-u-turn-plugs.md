# Handover: write the plan for `feat/u-turn-plugs` (planning only, no code)

## Goal
Write `docs/plans/u-turn-plugs.md`: an implementation plan, then stop. Do not change any code or data.

## The feature (owner's backlog)
When a right-angle plug cannot point to the side its cable has to go, point it the other way and turn the cable back (a
U-turn): longer minimum length, the turned cable occupies both sides of the plug; the router considers it when the direct
side is blocked or worse (signal AND DC plugs); the layout surrogate (scripts/layout.py) mirrors it.

## How plugs work today (keep)
- `design.plug_geometry`: head = depth x width rect centred on the jack along the facing. Right-angle: the cable leaves to
  the LEFT or RIGHT of the facing (seen from above looking out along the facing), `exit_offset_mm` out (default depth/2),
  body to `body_reach_mm` from the jack axis, then `cables.exit_run_mm` (default one diameter) straight; the router starts
  there. "down" = the plug points into a board hole (`routing.down_available`).
- The router picks each end's side: feasible first (free path), then fewest blocked plug parts + plug collisions, then
  shortest route; overrides (`cables.overrides.<S#>.exit_a/exit_b` = left|right|down|auto) fix a side. Signal:
  `routing.choose_signal` / end options; DC: `routing.plug_rank`, `power_plug_choices`, `refine_dc_sides`.
- Footprints and collisions: `routing.SigRects` / `DcRects`, `routing.plug_collision_findings`, `collision_count`;
  a right-angle DC plug may pass under one signal plug facing the same way.
- Lengths: `min_mm` = measured from half the plug head depth in front of the jack, along the exit and the routed path; no
  bend radius (all cables bend alike; an approximation, not a 3D simulation).
- The layout surrogate mirrors the plug choice (`layout.Model`, `_pool`, `in_area`); build and surrogate must agree
  (tests in tests/test_layout.py).
- Focus (owner): guarantee that pedals, plugs and cables FIT; a precise minimum cable length per cable.

## Constraints
Units mm; Python 3.12 via `uv run`; pytest with hand-computed geometry; gig-dependent tests use `tests/fixtures/guitar-gig/`.

## The plan must contain
Geometry of a U-turn option (footprint parts, where the cable starts, the extra length and how it is measured), when it is
offered and how it ranks against left / right / down, override syntax, signal and DC paths, surrogate mirroring, README /
drawing changes, test list, implementation steps (each a self-contained handover for a Sonnet agent), risks, and a short
"Decisions for the owner" list with a recommended default for each.

Read the code you need (scripts/design.py, scripts/routing.py, scripts/layout.py, scripts/svgdraw.py, catalog/cables.json);
do not read other plans or handovers.

## Deliverable
The plan file written, and a 10-line summary with the owner decisions and your recommended defaults.
