# Handover: supply-placement phase 3: per-supply placement (under / on_board)

Branch `feat/supply-placement` (checked out; phases 1-2 committed). Do not commit; the reviewer commits.

## Goal
Each supply instance gets its own `placement`, `under` (today, every supply) or `on_board`, instead of the single
global `jacks.supplies_layer`. An on-board supply is an obstacle like a pedal (its outline) and its used output ports
get the DC plug clearance like a pedal's power jack. **All three projects stay `under`: routes, lengths and findings
unchanged** (README gains only the placement in the power/supplies part).

## Context
- Python 3.12, `uv run` only. Tests `uv run pytest tests -q`; build `uv run scripts/build.py` (rewrites
  projects/*/README.md and routing.svg; diff them before/after).
- Project data: `projects/<name>/project.json` `power.supplies[]` = instances `{"id": "psu1", "supply": "ojai_r30",
  "label", "outputs": [{"port", "voltage_v", "pedals": [...]}]}`; `jacks.supplies_layer` = "under" | "on_board"
  (global, all three projects "under"). Supply catalog: `catalog/power_supplies.json`; supply ports are the supply's
  jacks with `function == "power_out"` in `catalog/jacks.json` (id = port name).
- `build.validate` builds `ctx["supplies"]` = [{"inst", "sup", "rows"}] (build.py ~line 215) and calls
  `jacks.check(...)`.
- `jacks.layout_from_items(items, chain, insts, ...)` (jacks.py ~181): maps each supply instance to a layout item by
  the supply's `playground_title` (`inst_item`), `jset["supply_items"]` can pin one; today
  `obstacles = [pedal items whose title is not a supply title, or all of them when supplies_layer == "on_board"]`.
- `jacks.check` (~line 313-345): the fixed clearance box per used jack; today `if supplies_layer == "on_board":` adds
  every instance's used ports (power_out jacks) with the small `power_clearance` box. With `defer=True` results go to
  `ctx["fixed_box"]` and `routing.route_project` reports the ones it did not check with a plug model
  (`report_fixed_box(ctx, checked)`).
- `routing.py`: `route_project` builds the cable list; power cables get `"under_board": under` from the global
  layer (~line 669) and a status "not routed (under the board)" / "not routed (power routing not implemented)".
  `power_plug_choices(ctx, cables, cable_types, cfg, obstacles)` picks the DC plug side for every placed pedal's
  power jack (`end_options` + `blocked_parts`), `power_plug_clearance(...)` reports blocked plug parts and returns
  the checked jack keys. A power cable's supply end is `c["from"]` = "<instance id>.<port>" (first hop of an
  output) or a pedal power jack (daisy-chain hops).
- `layout.py` `Model`: fixed obstacles = `lay["obstacles"]` minus the moving chain pedals, so an on-board supply is
  automatically a fixed obstacle for the search (moving it is a later phase; leave layout.py alone unless a test
  shows it breaks).
- `svgdraw.render` draws `layout["obstacles"]` as pedals; on-board supplies will then appear (fine); under-board
  supplies are not drawn today (keep it).
- Units mm. Unknown values null. Findings start as warnings (strict flags make errors).

## Tasks
1. Data: `power.supplies[].placement` "under" | "on_board"; missing = `jacks.supplies_layer` (default "under"),
   which stays readable. Unknown value = error ("power.supplies: psu1 has unknown placement ..."). Helper
   `power.placement(inst, project)` (or in jacks.py; one place) used everywhere below.
2. `layout_from_items`: obstacles = every pedal item that is not a supply item, plus the supply items of instances
   whose placement is on_board. Supply-titled items not matched to any instance: obstacles only when the global
   `supplies_layer` is "on_board" (today's behaviour). Return also `"inst_placement" {instance id: placement}`.
   Shapes for on-board supplies come from the outlines as for pedals (already, via `shown`).
3. `jacks.check`: the fixed-box owners for on-board instances only (per instance, not the global flag). The power
   cables in `ctx["cables"]["power"]` get `"under_board"` per hop: the placement of the hop's supply instance (every
   hop of an output belongs to that output's supply).
4. `routing.route_project`: power cable `under_board` from the hop (fallback: the instance's placement), status
   "not routed (under the board)" for under, "not routed (power routing not implemented)" for on-board.
   `power_plug_choices` / `power_plug_clearance`: also every USED port of an on-board supply (the DC plug of
   `cables.power_type` at a power_out jack: same `end_options` / `blocked_parts`, own item excluded; the cable at that
   port is the hop whose `from` is "<instance id>.<port>"; its side goes to that cable's `exit_a`). The checked keys
   are "<instance id>.<port>", matching the fixed-box keys of step 3, so each jack is checked exactly once. Plug
   heads drawn like the others.
5. README (`build.py`, the "Powering" section ~line 668): per supply instance one line/column with its placement
   ("under the board" / "on the board"), and the layout item found or "not in the layout". Keep wording short.
6. Tests (hand-computed, synthetic projects/layouts like the existing tests in tests/test_jacks.py,
   tests/test_routing.py, tests/test_check.py; reuse their fixtures/helpers):
   - default placement from supplies_layer; per-instance override both ways; unknown placement is an error;
   - an on-board supply is an obstacle (a pedal jack's clearance blocked by it; a signal cable routed around it);
     an under one is not;
   - an on-board supply's used port is checked with the DC plug (power_type) and reported once; without power_type
     with the fixed power box once; unused ports not checked;
   - power cables' `under_board` per supply (two instances, one under, one on-board);
   - the three real projects: `build.validate` results identical to before for guitar-gig (compare cable list
     lengths/status and warnings to the values on the current HEAD; e.g. a test that the gig has no on-board supply
     obstacle and every power cable is under_board).

## Acceptance
- `uv run pytest tests -q` all pass; `uv run scripts/build.py` runs; `git diff projects/` shows only the
  placement wording in the README power section (no route/length/finding change; routing.svg unchanged).
- Report: files changed, tests added, the README diff summary.

## Do not touch
- `projects/*/project.json` (do not add placement to the real projects; the default keeps them under),
  `playground_design.json`, `catalog/*`, `scripts/board_editor.py`, `scripts/boards.py`, the router's search
  (`astar`, `route_all`, `smooth`, `lanes`). No new dependencies. Do not edit CLAUDE.md / docs.
