# Handover: supply-placement phase 5: power cables routed (under the board, up through the nearest hole)

Branch `feat/supply-placement` (checked out; phases 1-4 committed). Do not commit; the reviewer commits.

## Goal
Power (DC) cables get real routes and minimum lengths instead of today's right-angle estimate: they stay UNDER the
board as much as possible and come up through the usable hole nearest the pedal's power jack (or over an allowed
board edge), then run the short way on top to the jack. `power.assign` (power wiring for layout proposals) and the
layout search's power term use a cheap **nearest-hole estimate** of the same model.

## Owner decisions (copy, do not change)
- Power cables try to always stay under the board and come up only where they must (at their pedal). If there is no
  easy way up, a cable comes up once and routes on top (a finding).
- Board edges per project, setting `power_routing.edges` {front, left, right, back}: "forbidden" | "avoid" |
  "allowed"; default {front: forbidden, left: avoid, right: avoid, back: allowed}. Holes are preferred, then allowed
  edges; "avoid" edges cost extra (`power_routing.avoid_penalty`, default 100 mm equivalent); forbidden never.
- Usable hole cells = phase 4's definition (inside an effective hole, free on top and under). A pedal over part of a
  hole blocks that part.
- Power and patch cables do not count against each other's stacking; power cables have their own stacking limit
  (`power_routing.max_stack`, default = `cables.max_stack`) on each layer. Signal routes do NOT change in this phase.
- Each daisy-chain hop (supply port -> first pedal, pedal -> next pedal) is one routed cable for now (forked vs serial
  chains: later). A hop starts under the board when its source is an under-board supply port; a hop from a pedal's
  power jack (daisy chain) or from an on-board supply port starts on top.
- Lengths are a MINIMUM to buy (no slack): plug measures (as the signal cables: half the plug head depth in front of
  the jack + the plug's exit lead) + the smoothed polylines on each layer + `hole_transit_mm` per hole pass (phase 4's
  value) + `edge_transit_mm` per edge crossing.
- `edge_transit_mm`: the extra length to go round the board edge from under to over. Default from the board data
  (`catalog/boards.json` optional key `edge_transit_mm`), else `power_routing.edge_transit_mm`, else 2 x
  `hole_transit_mm`; mark it "unverified" in the README. Do NOT invent board heights in boards.json (leave the key out).
- Estimate (`power.assign`, layout surrogate): per hop, from the source point to the target pedal's power-jack measure
  point: source under -> Manhattan under to the nearest usable hole point of the target -> transit -> straight
  distance on top to the jack; source on top -> min(on-top Manhattan x `top_cost`, down through the nearest usable
  hole of the source + under Manhattan + up through the nearest usable hole of the target). Same costs as the router
  (`top_cost` below) so the estimate ranks wirings like the router would. Fallback without holes: today's Manhattan.

## Context
- Phase 4 (read first, in `scripts/routing.py`): the two-layer grid (top grid + under grid, same cells), hole cells,
  the two-layer A*, `route_all` per layer, per-layer smoothing, `stretches`, `under_mm`, `holes_used`, drawing of under
  stretches and hole passes in `svgdraw.py`, the README routing table in `build.py`.
- Power cables today: `route_project` appends `{"id": "P<n>", "kind": "power", "from", "to", "type":
  cfg["power_type"], "exit_b", "under_board", "estimate_mm", "status": "not routed (...)"}` from
  `ctx["cables"]["power"]` (built in `jacks.check` step 4: hops with `from` "<inst>.<port>" or "<pedal>.<jack>",
  measure points via `endpoint(item, jack, depth)`). `power_plug_choices` already picks each power plug's exit side
  (pedal jacks: `exit_b`; on-board supply ports: `exit_a`) with `end_options` (which gives each option's `exit`,
  `lead`, `measure_mm`, `rects`). Power cable type `cables.power_type` = `dc_ra_2_1_low_profile` (catalog/cables.json:
  `diameter_mm` = its routing width).
- `power.py`: `measure_points(placed, inst_item, insts, jacks_data, depth_mm)`, `chain_order(start, members, points)`
  (Manhattan), `assign(chain, pedals, insts, project, points, port_points, run_v, start)` (slot_check uses
  chain_order). `layout.py` `Model.set_wiring` and the power term in the score (~line 488: Manhattan between measure
  points along each chain, weight `layout.weights.power` 0.1/mm). `propose_layout.evaluate` calls
  `power.measure_points` + `power.assign`.
- Under-board supply ports: their `power_out` jack points on the supply item (the item is drawn where the supply
  hangs under the board), so the cable starts under the board at that point.

## Tasks
1. Settings `power_routing` (project.json, all optional): `edges` (defaults above), `avoid_penalty` 100, `top_cost`
   3.0 (cost factor per mm on top for power cables; under = 1.0), `max_stack` (default cables.max_stack),
   `edge_transit_mm`. Validate values (unknown edge mode -> error).
2. Router: power grids built with the power cable's diameter (own grown walls, same cell size/origin); a separate
   negotiated-congestion run (`route_all` per layer limits) for the power nets; endpoints: source under (under-board
   supply port point) or on top (plug exit of the source jack), target on top (the plug exit chosen by
   `power_plug_choices`). Edge crossing: an allowed/avoid edge cell of the under grid connects to the top grid's cell
   just outside/at the board edge (top grid margin) at `edge_transit_mm` (+ `avoid_penalty` for avoid edges, search
   only). If unroutable even on top: status "unroutable" + finding. A power cable that had to come up somewhere other
   than the hole nearest its jack is fine (no finding); a cable that runs on top for more than e.g. 150 mm gets a
   warning "runs N mm on top of the board" (a named constant).
3. Cable fields as phase 4 (`stretches`, `under_mm`, `holes_used`, `edges_used`, `min_mm`, `path`, status "routed");
   keep `estimate_mm` (the old Manhattan) in the dict for comparison. The power cable's `under_board` stays true when
   any stretch is under.
4. Plug clearance of power plugs unchanged (`power_plug_clearance`). Power cables on top respect the plug limit
   among power cables only (or ignore plugs: say which you did and why).
5. Estimate: `power.hop_estimate(src, dst, src_under, hole_points, cfg)` (pure) and `chain_order(start, members,
   points, length=None, start_under=...)` using it; `assign(..., holes=None, cfg=None)` passes it through (no holes:
   Manhattan as today). `hole_points`: a cheap sample of usable hole points (e.g. hole-cell centres every ~6 mm) for the
   layout; usable = not under any pedal outline grown by the cable radius. `propose_layout.evaluate` passes the
   candidate's holes. Layout surrogate (`layout.py` power term): the same estimate, with hole points blocked by the
   CANDIDATE's pedal footprints (precompute the sample once per Model; per evaluation only the coverage test; keep
   the search fast: report the time of `uv run scripts/propose_layout.py guitar-gig --score` and of one default
   search run before/after).
6. Drawing: power cables in routing.svg (one neutral colour family, thinner than patch cables, under stretches
   dashed, hole/edge passes marked; P# labels near the pedal end); key entries. Signal drawing unchanged.
7. README: the power cable table shows the routed min length (and holes / edges used, mm on top); the text explains
   the model (under first, nearest usable hole, edges per `power_routing.edges`, transit values unverified). The
   "Powering" daisy-chain lengths, if shown elsewhere, use the routed values. `common.proposal_inputs_sha1` already
   covers project.json.
8. Tests (hand-computed): an under-board supply and one pedal next to a hole -> under to the hole, up, short top
   leg, length = measures + under + transit + top; hole covered by a pedal -> next hole; no hole -> back edge
   (allowed) with edge_transit; front forbidden never used; avoid edge used only when no hole/allowed edge; a
   daisy-chain hop pedal -> pedal near each other stays on top when that is cheaper by `top_cost`; power stacking
   separate from signal stacking; `hop_estimate` cases; `assign` picks a different (cheaper) output order with holes;
   the surrogate power term with a pedal covering the nearest hole point.

## Acceptance
- `uv run pytest tests -q` all pass; `uv run scripts/build.py` runs. Report for guitar-gig a table per power cable:
  estimate (old) vs routed min length, holes/edges used, mm on top; and the timing numbers from task 5.
- Signal cable routes and lengths identical to phase 4 (diff the README signal table).

## Do not touch
- The signal routing results; `project.json`, `playground_design.json`, catalog data (except none);
  `board_editor.py`. Do not regenerate proposals (the reviewer does). No new dependencies. Do not edit CLAUDE.md / docs.
