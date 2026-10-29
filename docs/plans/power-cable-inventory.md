# Plan: `feat/power-cable-inventory`: plan the power wiring with the owner's own DC cables

Status: **PARKED (owner, 2026-10-29)**: not planned now. Kept for reference only; do not start it without the owner.
Owner: "Power cables are rather cheap and I can get them very easily. The most important focus of this project is to be
able to assemble the pedalboard and to guarantee that cables and pedals can fit on it." A 10 cm or a 30 cm DC cable is
almost the same (the longer one gets folded and tied). The owner wants PRECISE minimum required lengths per cable and
picks the cables from them; matching the owned cables is not the tool's job.

## How to run this (for the agent that picks this up)
1. Read `CLAUDE.md` (conventions, working agreements) and this plan. Do not read old handovers.
2. Ask the owner the questions in "Decisions to confirm" (one AskUserQuestion round, recommendations first) AND for the
   cable list itself (see "Data"); write the answers under "Owner decisions". The inventory is the owner's data:
   never invent cables; if the list is not ready, phases 1-2 can start with a test inventory and the gig left
   without one (the build must work without an inventory exactly as today).
3. Per phase: write a handover `docs/handovers/power-cable-inventory-<n>.md` (minimal, self-contained, as CLAUDE.md
   says), delegate it to a `general-purpose` agent on `model: sonnet`, verify (tests, build, the gig before/after),
   commit on the branch.
4. At the end: code review (`/code-review main...feat/power-cable-inventory`), fix the findings, update CLAUDE.md and
   `docs/TODO.md`, regenerate the gig proposals if the surrogate / `power.assign` changed, ask the owner before merging.

## Goal (owner, 2026-10-28, from docs/TODO.md 3.1)
Real DC cables are OFF-THE-SHELF: one input plug, several output plugs, fixed number of outputs, fixed lengths, no
modularity. The owner has a bunch of daisy-chain cables and uses them as needed, so whether an output is forked or
serial, and WHICH owned cable it uses, is part of the planning. Serial chains stay as wired today: leg by leg, above or
below the board, whichever is easier (owner, confirmed).

## Facts (main at 5b1f53f, 2026-10-28)
- Wiring: `project.json` `power.supplies[]` = {id, supply (catalog id), label, placement?, outputs: [{port, voltage_v,
  pedals [daisy order], note, style?}]}. `style` serial | forked (`routing.SERIAL` / `FORKED`), default
  `power_routing.daisy_style` (default serial; `routing.daisy_style(project, output)`).
- Every output is one or more physical DC cables: serial = ONE cable port -> pedal 1 -> pedal 2 ... (its legs are the
  hops P#, plugs = pedals + 1); forked = one cable per pedal from the port today (legs share the port plug); an output
  with one pedal is a plain single cable. Cable ids C# (`jacks.check` numbers them), `ctx["power_cable_summary"]`
  (`routing.power_cable_summary`): {id, style, output, legs, from, to, plugs, min_mm (sum of legs; None if a leg is
  unrouted), estimate_mm, status, plug_types {"port", "pedals": [per leg]}}. README "DC cables to buy".
- Lengths: each leg's `min_mm` = routed minimum (plug measures from half the head depth + polylines + hole / edge
  transits + down drops), no slack. A down plug (feat/plug-orientation) adds `jack_height_mm` + the deck transit.
- Plug types (feat/plug-orientation): `cables.power_type` (default `dc_ra_owner_baseline`), optional
  `cables.power_types`; per cable `type_a` (port end) / `type_b` (pedal end); one pedal-end type per serial cable;
  overrides `cables.overrides.<P#>.type_a / type_b / exit_b`. Straight DC plugs are owned but not used now (owner).
- Gig today: 10 outputs, all serial (6 single-pedal), 17 legs, DC 3355 mm; `power.assign` (layout proposals) chooses
  outputs and daisy order, measuring forked outputs as the sum of port -> pedal estimates.
- Owned quantities: supplies have `quantity` in `catalog/power_supplies.json`; the build errors "project uses n x
  <id> but you own q" and warns about shared items across projects ("shared:" lines).

## Design (to confirm)
### Data
- New `catalog/power_cables.json` (the owner's DC cable MODELS with `quantity` owned, like the supplies), one entry
  per model: `kind` single | serial | forked; `plugs`: the port plug type and the output plug type(s) (ids from
  `catalog/cables.json`, role power; e.g. right-angle / straight), `connector` 2.1 / 2.5 mm, `polarity_reversing`
  bool; lengths: single `length_mm`; serial `segments_mm` [port -> plug 1, plug 1 -> plug 2, ...]; forked
  `branches_mm` [one per output plug] (+ optional `trunk_mm` from the port plug to the split); `quantity`; `sources`
  / `notes`. How the owner measures (plug body to plug body vs plug tip to tip) is written in the file's `_doc` and
  compared with how `min_mm` is measured (from half the head depth: a cable of length L fits a leg of min_mm M when
  L >= M minus the two half head depths? -> decision 2).
### Fit model
- single: length >= the leg's min_mm. serial cable on a serial output: segment k >= leg k (in order; more segments
  than pedals -> decision 3). forked cable on a forked output: N branches >= pedals, each pedal's leg (port -> pedal,
  routed as forked) matched to a branch (sort both ascending and match: a pedal fits a branch at least as long).
- Slack = cable length - leg length (the extra cable lying on / under the board; less is cleaner).
### Planning (build)
- Per output: the owner may fix `cable` (a model id from the inventory) and / or `style`; otherwise the build picks.
- Choice over all outputs of a project: each owned cable used at most `quantity` times; minimise (outputs without a
  fitting owned cable, then total slack); styles follow the chosen cable (a forked model -> forked output, a serial
  model or single -> serial). Small problem (10 outputs, tens of cables): exhaustive per output with a matching /
  greedy-with-repair is enough; document the method.
- Lengths depend on the style (forked legs start at the port), so route both styles: one all-serial and one all-forked
  power routing pass give the per-output leg lengths for each style (outputs only interact through stacking), choose,
  then the final routing with the chosen styles, and re-check the fit (report a cable that no longer fits).
- The chosen cable fixes its plug types (port / pedal ends): pass them as the cable's types (as `type_a` / `type_b`
  overrides do); a model whose plug style the jack cannot take (e.g. straight blocked) ranks lower (decision 5).
- Shortfall: per output without a fitting owned cable, say what to buy: "needs a serial cable with segments >= 250,
  310, 120 mm" / "a 3-way forked cable with branches >= ..." (rounded up to 10 mm? decision 4).
### Output
- README: "DC cables" table: output, chosen model (or "buy: ..."), style, per-leg length vs cable length (slack),
  status; "Owned DC cables not used" (spares); `power.svg` legend names the model.
- Validation: unknown model ids, wrong plug roles, segment / branch counts, `quantity` exceeded across projects
  (shared warning, like supplies).
### Layout search
- v1: `power.assign` and the layout surrogate stay as they are (cable fit is checked on the finalists by the build).
  Open: whether the search should consider cable fit (decision 6).

## Phases
1. Data + validation: `catalog/power_cables.json` (schema, `_doc`, the owner's cables or an empty list), loader in
   `common.py`, `build.validate` checks; README lists the inventory. No behaviour change without an inventory.
2. Fit check of the owner's fixed choice: `power.supplies[].outputs[].cable` = model id; the build checks fit with the
   routed legs, reports slack / shortfall, fixes the plug types from the model.
3. Automatic choice: style + cable per output (both-style routing, assignment with quantities), README, power.svg,
   shopping suggestions for the shortfall.
4. (If the owner wants it) `power.assign` / surrogate prefer wirings that fit the owned cables.

## Decisions to confirm (ask the owner; recommendation first)
1. Where the inventory lives: `catalog/power_cables.json` with `quantity` (recommended: like the supplies, shared by
   all projects), or per project.
2. How the owner measures a cable's length / segments (recommend: plug body to plug body, the visible cable), and so
   how it compares with `min_mm` (from half the head depth in front of each jack): recommend "fits when cable length
   >= min_mm - head depth" (each end's half depth is already inside min_mm), written down in the `_doc`.
3. A serial cable with MORE plugs than the output's pedals (a spare plug at the end) or a forked cable with more
   branches than pedals: allowed (recommend yes, the spare plug is reported) or not.
4. Slack: minimise total slack (recommended), or prefer the fewest cables / keep the owner's current styles; a maximum
   slack per leg (e.g. 150 mm) above which it warns "too long, coil it"?
5. Plug style per model: a model's plugs fix the plug types; may a jack whose right-angle exits are all blocked take a
   straight-plug model (owner: owns straight cables but does not use them now: recommend only when `power_types`
   allows straight).
6. Layout search: consider cable fit in proposals (later phase 4) or not (recommended: not in v1).
7. The cable list: per model kind, plug types (angled / straight, 2.1 / 2.5 mm, polarity), lengths (segments /
   branches), how many. Owner to provide (a table in the chat is fine).

## Owner decisions
(to be filled in by the agent that runs this plan)

## Acceptance
- `uv run pytest tests -q` passes (+ hand-computed fit tests: single / serial / forked fit and slack, assignment with
  quantities, shortfall text, both-style routing, plug types from the model).
- `uv run scripts/build.py` runs; projects without an inventory unchanged (gig before/after identical until the
  owner's cables are entered); with the owner's list: report the gig choice per output (model, style, slack) and the
  shortfall.
- CLAUDE.md and docs/TODO.md updated; code review fixed; merge after the owner's OK.
