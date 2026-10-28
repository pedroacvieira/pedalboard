# Handover: plug-orientation phase 1, plug-to-plug collisions

Branch `feat/plug-orientation` (already checked out; do not commit, the coordinator commits). Python 3.12, run
everything with `uv run` (`uv run pytest tests -q`, ~60 s; `uv run scripts/build.py`). Never `pip install`.

## Goal
Today every plug footprint is checked against pedal OUTLINES only, so two plugs may overlap each other unnoticed.
On the gig the Tumnus Deluxe has three jacks side by side facing the back (`out` at x 40.5, `power` at 55.5, `in`
at 70.2 mm); the power plug (DC right-angle, cable exits left, body reaching 19 mm from the jack axis) lies over
the space of the output jack, which is the board's LAST output (guitar/amp cable, not modelled: it keeps the fixed
audio box `jacks.clearance`). Model plug-to-plug collisions, report them, and let the side choice avoid them.

## What to build
1. **Fixed boxes as footprints** (`scripts/jacks.py`, `check`, step 3): it already builds `zone =
   design.clearance_rect(pt, facing, out_mm, side_mm)` for every used jack (`owners`: input/output/power of every
   placed pedal, `jacks.extra_used` jacks, used ports of on-board supplies). Keep every zone (overlapping or not) in
   `ctx["fixed_zones"]` = {"<id>.<jack id>": {"rect", "facing", "zone": "audio"|"power", "label": jack label}} so
   routing can use the ones that get no plug model.
2. **Footprints** (`scripts/routing.py`, `route_project`): a footprint per used jack key "<id>.<jack id>":
   - signal ends with a cable type: the chosen option's rects (`o["rects"]`: head, barrel, cable run);
   - power plugs (`power_plug_choices` result, pedal power jacks and on-board supply ports): the chosen option's rects;
   - every other used jack: its fixed zone from `ctx["fixed_zones"]` (part name "box"): first input, last output,
     extra jacks, signal jacks without a cable type, power jacks when the project has no `cables.power_type`.
   "Modelled" keys are known before any choice (signal ends with a type and a placed pedal; power jacks of placed
   pedals and used on-board ports when there is a power type), so the fixed set = zones minus modelled keys.
3. **Side choice avoids collisions** (owner: "signal sides are chosen first, power sides then avoid the signal plugs
   and fixed boxes; a collision counts like a blocked part"):
   - signal cables in chain order (S1, S2, ...): per end option, `collides` = parts of that option overlapping a
     fixed footprint or a footprint of an end ALREADY chosen (earlier cables). In the `combos` ranking key replace
     `len(oa["hits"]) + len(ob["hits"])` by blocked parts + collisions of both ends. Same in the no-grid branch
     (`min(... len(o["hits"]))`). Overrides (`exit_a` / `exit_b`) still fix a side.
   - `power_plug_choices(ctx, cables, cable_types, cfg, obstacles, taken=None)`: `taken` = {key: [(part, rect)]} of
     the signal plugs and the fixed footprints; rank `(len(hits) + collisions, overlap sum)`; every chosen power plug
     joins `taken` for the next ones. Keep it working when `taken` is None (other callers, e.g. tests and
     `power_plug_clearance(..., choices=None)`).
4. **Collision check and findings** after all choices: every pair of footprints of DIFFERENT keys, all part pairs,
   `design.overlap(r1, r2)` (TOL like pedals). One finding per pair of jacks: the deepest part pair, depth =
   `min(dx, dy)` of the overlap. Keep them in a new list `ctx["plug_collisions"]` (NOT `ctx["violations"]`: the layout
   surrogate does not model collisions yet, and a test checks that its blocked plugs equal the build's violations):
   {"jack", "part", "with", "with_part", "depth_mm", "cable", "cable_type", "side", "with_kind"}; `with_kind` says
   what the other footprint is ("DC plug", "<type> plug", "first input, fixed box", "last output, fixed box", "extra
   jack, fixed box", "power box"...). Message to the clearance sink (warnings, errors with `validation.strict_clearance`),
   e.g. `clearance: tumnus_deluxe.power (Power, dc_ra_owner_baseline right-angle plug, cable exits left) collides with
   the plug at tumnus_deluxe.out (last output, fixed box): 4.2 mm (its barrel into the box)`. Order the pair so that
   the message is stable (natural key order of the jack keys is fine). No finding without a layout / when a footprint
   is missing.
5. **README / proposals** (`scripts/build.py`, `scripts/propose_layout.py`): the clearance section and "Open issues"
   list the collisions next to the blocked plugs (one line each, same style). In `propose_layout.py` the metrics get
   `"collisions": len(ctx["plug_collisions"])`, and the finalist gate treats it like `blocked` (a proposal must not
   have more collisions than the owner's layout); the README proposals table shows a "Plug collisions" row. Look at
   how `blocked` flows through `metrics`, the gate and `build.proposals_section`, and mirror it.

## Context (facts you need)
- `design.plug_geometry` returns `{"rects": [(part, rect)], "lead", "exit", "lead_mm", "measure", "measure_mm"}`;
  parts "head", "barrel", "cable". Rects are (x0, y0, x1, y1) mm on the canvas.
- `routing.end_options(item, jack, ctype, exit_fixed, cfg, outward)` -> (facing, [options with "side"]).
- `routing.blocked_parts(opt, own_id, obstacles, shapes)` -> [(part, obstacle item, overlap)] (outlines only).
- `route_project`: signal ends in `c["_sides"]` ({"cid", "jack", "facing", "opts"}), chosen options in
  `chosen[c["id"]] = (oa, ob)`; `power_choices` = [(item id, jack, power cable or None, facing, option)];
  `checked` = keys checked with a plug model; `report_fixed_box(ctx, checked)` reports the rest's fixed boxes
  against pedals (keep that).
- A forked output's legs share one port plug (same key), a serial chain's legs share each pedal's plug (same key):
  one footprint per key, never a self-collision.
- Units mm everywhere. Generated files (READMEs, SVGs) only via `uv run scripts/build.py`.

## Tests (new file `tests/test_plug_collisions.py`; synthetic cable types and small hand-made layouts, never the
catalog's values, so the owner can change plug sizes)
Look at `tests/test_routing.py` / `tests/test_check.py` for how they build a ctx with a hand-made layout and types.
- hand-computed collision depth of two plugs on one pedal (e.g. a right-angle plug whose barrel reaches the
  neighbour jack's fixed box by a known number of mm);
- the power side choice flips to the other side when the first one collides (and stays when an override fixes it,
  the collision is then reported);
- a signal plug collision with an earlier cable's plug influences the side choice;
- no collision finding for touching footprints (within TOL) and for the shared plug of a serial / forked chain;
- strict_clearance makes them errors.

## Acceptance
- `uv run pytest tests -q` passes; `uv run scripts/build.py` exit 0.
- Gig before/after: run `uv run python /tmp/claude-1000/-home-pvieira-projects-pedalboard/08007042-4064-4da5-be57-4d44a51608ea/scratchpad/snap.py guitar-gig <out.json>` before and after
  your change (it dumps every cable's exits, min_mm, status and the warnings) and report the differences: which
  power / signal exits changed, P13's exit and length, the new collision findings (expected: the Tumnus power plug
  vs its last-output box, unless the right side avoids it). If a gig-pinned test changes value only because a
  side flipped, update it and say so.
- Short report: what changed per file, decisions you had to make, anything left open.

## Do not touch
`scripts/layout.py` (the surrogate gets collisions in a later phase), `catalog/`, `projects/*/project.json`,
`playground_design.json`, CLAUDE.md, docs/TODO.md, the plan. Do not add the "down" exit (phase 2).
