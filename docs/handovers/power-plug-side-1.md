# Handover: DC plug side by route length (`feat/power-plug-side`), implementation

You run in your own git worktree (created from `fix/cable-area`, which is being reviewed and merged into main in parallel).
First: `git switch -c feat/power-plug-side`. Do not commit; the coordinator reviews and commits. Python 3.12, `uv run` only
(`uv sync` once in the worktree; `uv run pytest tests -q`, ~100 s; `PEDALBOARD_SLOW=1 uv run pytest tests -q -k gig`;
`uv run scripts/build.py`, exit 0). No new dependencies.

## Goal
The plan is `docs/plans/power-plug-side.md` (short; read it, it is the spec). Owner defaults for its open questions
(proposals accepted for this first pass): `SWITCH_MM` = 5, both stages (estimate AND routed refinement), length wins over
overlap (overlap only breaks length ties). `TIE_MM`: pick a small constant (e.g. 5 mm) and name it next to `SIDE_ROUNDS`.

## Code you need (scripts/routing.py unless noted)
- `plug_rank(o, key, taken)` (~2374): today `(failed, infeasible, not down, blocked + collisions, overlap, type index)`;
  insert length before overlap.
- `power_plug_choices(...)` (~2426) with `decide_group` (~2484, one pedal-end type per serial cable: add length to its summed
  ranking): picks every DC plug before routing. Estimate stage goes here.
- `choose_dc(report)` (~1908, inside the `SIDE_ROUNDS` loop with `choose_signal` ~1865): the estimate stage is part of it.
- `route_power_choosing(...)` (~2088): routes, retries with `avoid` for unroutable legs; add the routed refinement after the
  first `route_power` (A* with plain costs like `plain_search` ~819 on the power grid; only between options tied on the fit
  key, including collisions with the already chosen signal plugs; keep the new routing only if no leg became unroutable and the
  total power min length did not grow).
- `scripts/power.py`: `Crossings` (~321), `hop_estimate(src, dst, src_under, holes, cfg, near=None, dst_under=False)` (~355),
  `measure_points(...)` (~644). Use these for the estimate (same function as the surrogate).
- `scripts/layout.py`: surrogate phase A "power plugs ... clearance only" picks a DC option by `_clearance`; add the estimated
  span of its legs as the tie-break, and let the power term use the chosen option's exit.
- Overrides: `cables.overrides.<P#>.exit_b` still fixes the side (no length choice for that plug).
- Cable ids: power cables P#, legs P#.1, P#.2... in daisy order; a serial cable's middle pedal plug ends two legs.

## Conventions
Units mm. Comments / docstrings in the surrounding terse style. Down plugs always win when available, even if longer; a
blocked / colliding side never wins on length. Tests that use the gig use the frozen fixture (`conftest.gig_copy` /
`GIG_FIXTURE`), never `projects/guitar-gig`. Generated files (READMEs, .svg, .mmd) only via the build. Update CLAUDE.md
(the "Plug orientation" / "DC plug types" bullet: the new rank and the two stages) and `docs/TODO.md`.

## Acceptance
- Tests from the plan's "Tests" section (hand-made cases + surrogate agreement + gig fixture: total DC min length not longer,
  no new findings).
- Build log line per project: `power: N DC plugs took the shorter side (saved X mm)`.
- All tests pass (normal + slow gig), build exit 0, generated files regenerated.

## Report
What changed (files, functions), per project the build log line, the gig plugs whose side changed with before/after lengths,
test counts and time, anything you could not do or decided yourself.

## Do not touch
`projects/*/playground_design.json`, `projects/*/project.json` power wiring, `catalog/*.json`, the test fixture's data.
