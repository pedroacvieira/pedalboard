# Handover: feat/routing-speed: faster router, search and tests with IDENTICAL results

Branch `feat/routing-speed` (checked out from main). Do not commit; the reviewer commits.
Python 3.12, `uv run` only (never pip); tests `uv run pytest tests -q`; build `uv run scripts/build.py`.
No new dependencies without asking (numpy would need the owner's OK: do not add it). Do not edit CLAUDE.md / docs,
project data, catalog data, board.json files.

## Goal
Make the build, the layout search and the test suite faster WITHOUT changing any result: every generated file
(`projects/*/README.md`, `routing.svg`, `power.svg`, `*.mmd`, `playground.json`) byte-identical, and
`uv run scripts/propose_layout.py guitar-gig --dry-run --seed 1` printing the same proposals / scores / moves.

## Measured today (this machine)
- `build.validate` of guitar-gig: ~1.2 s, of which ~80 % is A* (`routing.astar_layers`: 111 calls; `route_all` signal
  + power ~1.8 s under the profiler, `route_power` ~1.2 s). Hot spots under cProfile: `astar_layers` own time 1.3 s,
  `route_all.cost` closure 0.6 s (506k calls), `dict.get` 3.7M calls, `under_ok` / `top_ok` lambdas (1.7M / 1.1M
  calls), `Under.components` called 64 times (side choice `connected`).
- The side choice in `route_project` runs a full A* per best-ranked plug-side combination (cost 1) and `route_all`
  then routes again from scratch (known leftover in docs/TODO.md: "the router runs A* to pick exit sides and then again
  in route_all").
- `uv run scripts/propose_layout.py guitar-gig` (default search) ~30-40 s.
- Test suite ~70 s; slowest: test_propose.py::test_propose_writes_loadable_proposals_and_the_readme_section 15 s,
  ::test_readme_section_lists_proposals_and_detects_stale_ones 9 s, test_power_routing.py::
  test_power_stacking_is_its_own_limit_per_layer 7.5 s (a tiny synthetic board: suspicious; find out why),
  test_layout.py::test_power_assignment_passes_the_build_and_is_not_longer_than_the_owners 3.7 s, several 2-2.7 s
  tests that run build.validate on the real gig.

## Tasks (measure first: record before/after numbers for each; keep a change only when the outputs stay identical)
1. Baseline: before touching code, save copies of every generated file and the `--dry-run --seed 1` output in your
   scratch space; after each change, rebuild and compare (byte-identical) and rerun the dry run (identical text apart
   from the runtime line).
2. A* inner loop (`astar_layers`, `astar`): precompute per grid/layer what does not change between calls (neighbour
   offsets with step lengths, passable sets, hole cells / edge links as dicts), avoid per-step lambda / closure calls
   (`top_ok`, `under_ok`), use local variables, plain tuples; same tie-breaking (the heap order must stay identical:
   keep the (f, g, state) keys and the push order) so paths do not change.
3. `route_all.cost`: cheaper per-cell cost (precomputed plug membership, local lookups); same values.
4. Side choice: cache `Under.components` / `connected` per (grid, squeeze) (check it is not already) and reuse any A*
   result that can be reused without changing results (e.g. memoise identical (start, goal, squeeze) searches with the
   plain cost within one route_project call). Do NOT seed route_all with the side-choice paths if that changes the
   negotiation (results must stay identical).
5. The 7.5 s power-stacking test: find the cause (an unroutable search exploring everything? a squeeze retry?) and fix
   the code if it is a real inefficiency (e.g. an early exit when start and goal are not connected) — results identical.
6. Tests: the propose tests may use smaller search budgets (iterations / restarts / time limit) where the test does not
   depend on the full search; tests that run `build.validate` on the real gig repeatedly can share one module-level
   result (pytest fixture with scope="module") where they only read it. Never weaken an assertion.
7. Optional, only if 2-4 are done and results stay identical: in `layout.py` the surrogate (`Model.score`, ~1.9 ms per
   call, ~10k calls per search) — profile and speed up the hottest part.

## Acceptance
- `uv run pytest tests -q` all pass (and `PEDALBOARD_SLOW=1` if it finishes in reasonable time; report).
- Generated files byte-identical to the baseline; dry-run output identical (except runtime).
- Report a before/after table: gig `build.validate` time, `uv run scripts/build.py` time, `--score` time, default
  search time, test suite time, and the slowest 5 tests after.
