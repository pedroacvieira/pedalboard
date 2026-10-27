# Handover: feat/daisy-chains: forked vs serial power daisy chains

You work in your own git worktree on a new branch from `main`. Commit your work on that branch when done (message
ending with "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"). Python 3.12, `uv run` only (never pip); tests
`uv run pytest tests -q` (~30 s); build `uv run scripts/build.py`. No new dependencies. Do not edit CLAUDE.md /
docs/TODO.md / plans (the reviewer does), `playground_design.json`, `board.json`, catalog data. If `.cache/` is missing
in your worktree, copy it from /home/pvieira/projects/pedalboard/.cache (read-only source).

## Goal
A supply output's daisy chain is either SERIAL (one cable with several plugs that goes from the port to the first
pedal, then on to the next: today's geometry) or FORKED (one cable per pedal, each from the supply port; e.g. a
splitter at the port). Lengths, cable counts, drawing, README and the power assignment / layout search follow the style.

## Owner decisions (copy)
- Owner (2026-10-23): daisy chains are either FORKED (several cables from one source, each its own cable) or SERIAL
  (one long cable through every pedal, counted as ONE cable).
- Defaults chosen for the owner to confirm (list them in your report): the style is set per output
  (`power.supplies[].outputs[].style`: "serial" | "forked"), default from the project (`power_routing.daisy_style`,
  default "serial" = today's routes, so every existing project's routes and lengths stay unchanged). A serial cable
  is routed hop by hop exactly as today (each leg may run on top or dip under the board; the router decides by cost:
  `power_routing.top_cost`).
- Power cables are a minimum length to buy (no slack): a serial cable's length = the sum of its legs' `min_mm`; a forked
  output = one cable per pedal, each routed from the supply port (same plug model at the port; several plugs at one
  port share it: the port's DC plug clearance is checked once).

## Context (read first)
- `scripts/jacks.py` `check` step 4: power hops per output (`ctx["cables"]["power"]`: `output`, `from`, `to`, the
  right-angle estimate); `under_board` only on a supply's first hop.
- `scripts/routing.py`: `route_project` builds the power cable list (`P<n>` per hop, `estimate_mm`), `power_plug_choices`
  / `power_plug_clearance` (plug side per jack; an on-board port's side is the cable's `exit_a`), `route_power` (one net
  per hop; `stretches`, `min_mm`, `holes_used`, ...). `cables.overrides.<P#>` (exit_b etc.) are keyed by hop ids;
  `power.cable_ids` / `power.remap_overrides` map them for proposals.
- `scripts/power.py`: `chain_order(start, members, points, length=..., start_under=...)` (serial order, exact up to 7),
  `assign(...)` (slot_check uses chain_order), `hop_estimate`, `Crossings`.
- `scripts/layout.py` `Model.set_wiring` / the power term in `score` (sums the hop estimates along each chain).
- `scripts/build.py`: README "Powering" section (per supply: outputs table) and the routing section's power table
  (`power_text`, the cable table); `scripts/svgdraw.py` `power_cables`, `power_labels`, `render_power` (power.svg table).

## Tasks
1. Data + validation: `outputs[].style` and `power_routing.daisy_style` ("serial" | "forked"; anything else = error).
   `power.assign` keeps the style of the owner's output (or the project default) for the rows it writes.
2. Hops: forked -> every pedal of the output gets a hop from the supply port (`from` "<inst>.<port>"), serial -> as
   today. Each hop keeps its own P# leg id (so overrides keep working).
3. Cable grouping: every power leg gets `cable` = a cable id per physical cable (e.g. "C1", "C2", ... in order: a
   serial output = one cable with all its legs; a forked output = one cable per leg) and `style`. A summary list
   `ctx["power_cable_summary"]`: [{"id", "style", "output", "legs" [P#], "plugs" (number of DC plugs on it: serial =
   pedals + 1, forked = 2), "min_mm" (sum of legs; None if any leg is unrouted), "status"}].
4. README: the power cable table gains the physical cable (C#) per leg, plus a table "DC cables to buy" (one row per
   physical cable: style, output, from -> pedals, plugs, min length). Keep the existing per-leg table.
5. Drawing: power.svg table lists the physical cables (C#, style, legs, length); legs of one serial cable share a
   label; forked legs fan out from the port (as routed).
6. Estimate: `power.assign` and the layout surrogate: forked output length = sum of port -> pedal estimates (no order);
   serial = chain_order as today.
7. Tests (hand-computed, synthetic): style validation; forked hops all start at the port; serial unchanged (the gig's
   README power table / lengths byte-identical apart from the new columns/tables: show the diff); grouping and plug
   counts; summary length = sum of legs, None with an unrouted leg; assign with forked uses sums (and picks a
   different assignment than serial in a constructed case); surrogate power term for forked.

## Acceptance
- `uv run pytest tests -q` passes; `uv run scripts/build.py` runs; the gig's routes and lengths unchanged (default
  serial); report the README diff summary and the defaults chosen.
- Report: branch name, commit, files changed, tests, anything the owner must decide.
