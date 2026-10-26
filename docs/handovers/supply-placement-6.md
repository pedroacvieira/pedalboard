# Handover: supply-placement phase 6: on-board supplies movable in the layout search

Branch `feat/supply-placement` (checked out; phases 1-5 committed). Do not commit; the reviewer commits.

## Goal
In the layout search (`scripts/layout.py`, `scripts/propose_layout.py`), a supply instance placed ON the board
(`power.supplies[].placement: "on_board"`) is a movable item like a chain pedal: moves, swaps (with pedals or other
on-board supplies), rotations; never overhanging the board, no overlap. Its used ports' DC plug clearance counts in the
surrogate, and the power term (nearest-hole estimate, phase 5) follows its ports. Under-board supplies stay fixed and
are not obstacles (as today). No real project has an on-board supply: test on synthetic projects. Real projects'
results must stay identical.

## Owner decisions (copy)
- On-board supplies are movable in the layout search (like a chain pedal: moves, swaps with pedals of similar size,
  rotations; never overhanging, no overlap beyond TOL; touching allowed). Rotations 0/90/270 (never 180, as pedals).
- A supply on top is an obstacle by its outline; its used output ports get the DC plug clearance (`cables.power_type`)
  like a pedal's power jack; the build already does this (phase 3: `routing.power_plug_choices` adds on-board ports,
  key "<instance id>.<port>").
- `layout.pins` may list instance ids too (pin an on-board supply). `layout.rotations.<instance id>` as for pedals.

## Context
- `layout.py` `Model.__init__`: `lay = jacks.layout_from_items(...)` returns `placed` (chain pedals), `inst_item`
  {instance id: item}, `inst_placement` {instance id: "under" | "on_board"}, `obstacles` (on-board supply items
  included); `self.ids` = movable chain pedals; `self.fixed` = obstacles not moving; `self.owner`, `self.allowed`,
  `self.pins`, `self.access`, `self.names`, `self.titles`, `_geometry(n, rot)` (per-item: half sizes, outline shapes,
  signal ends, power plug, extra jacks, footswitches; uses `self.project["signal_chain"].index(pid)`), `set_wiring`
  (power daisy chains: port point + member indices + under flag; the port points come from
  `power.measure_points({}, self.inst_item, ...)` for the owner's supply positions), `score` (terms incl. power,
  io / flow / access that only make sense for chain pedals), `items_for(state)` (moves items by `self.placed[p]["id"]`),
  `snapped`, `feasible_one`, `problems`; `propose`, `polish`, `shuffle_start` (moves / swaps), `free_distance`.
- `propose_layout.py`: `evaluate` (candidate items -> `jacks.layout_from_items` -> `power.measure_points` ->
  `power.assign` -> `build.validate(items=...)`), `metrics`, the moved-items report (`moves`: per pedal dx/dy/rot),
  `overlay` (SVG of moves), README section via `proposals/meta.json`.
- Tests: `tests/test_layout.py`, `tests/test_propose.py` (synthetic projects / layouts helpers there; reuse them).

## Tasks
1. Model: movable items = chain pedals + on-board supply instances (keep chain pedals first, so pedal indices are
   unchanged when there is no on-board supply). For a supply: geometry with outline shapes, no signal ends, no
   footswitches, no access rule, no io/flow; its used ports (rows with pedals) as plug-clearance ends (the DC plug
   with `end_options` like a pedal power jack, else the fixed `jacks.power_clearance` box) and as moving power-term
   start points (the port measure points relative to the item centre, as `_geometry` stores a pedal's power measure).
   Names/titles from the supply label / catalog. `items_for` moves supply items too.
2. Power term and `set_wiring`: a wiring row's start point follows its supply when that supply moves (store the
   port as (instance index, port offset) rather than a fixed point for on-board supplies).
3. Moves/swaps/rotations/pins/max-move/move cost apply to supplies like pedals (`propose`, `shuffle_start`,
   `polish`, `free_distance`, `snapped`); swaps between a supply and a pedal only when sizes are similar (reuse the
   existing similar-size rule if there is one, else allow any swap that stays feasible).
4. `propose_layout.py`: `evaluate` passes the moved supply items (they are in `items_for`); moves report and overlay
   name the supply; nothing else changes.
5. Tests: a synthetic project with one on-board supply: the Model lists it as movable; it never overlaps a pedal or
   overhangs; a pin keeps it fixed; moving it changes the power term (its ports move); its port plug clearance is in
   the score (a pedal blocking its port costs); a search run (small iteration budget, fixed seed) returns a feasible
   state; `items_for` moves the supply item; the real guitar-gig `--score` breakdown is identical to before (compare
   `Model.score(owner state, detail=True)` terms to values computed on the last commit; e.g. assert equality
   against a fresh Model built with the same inputs before/after is not possible, so record the gig numbers in the
   test from the current HEAD before your change).

## Acceptance
- `uv run pytest tests -q` all pass; `uv run scripts/build.py` runs and changes nothing in `projects/`;
  `uv run scripts/propose_layout.py guitar-gig --score` prints the same numbers as before your change.
- Report: files changed, tests, timings of `--score` and of one `--dry-run --seed 1` search before/after.

## Do not touch
- Router (`routing.py`), `power.py` beyond what the wiring start points need, `project.json`, `playground_design.json`,
  `board.json`, catalog data. Do not regenerate proposals. No new dependencies. Do not edit CLAUDE.md / docs.
