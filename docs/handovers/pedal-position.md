# Handover: plan `feat/pedal-position` (layout proposals)

Read `CLAUDE.md` first (repo briefing, conventions, working agreements). This handover is for the PLANNING
step: produce an implementation plan, do not write code.

## Goal (owner, 2026-10-22)
Propose new x/y positions for the pedals on a board, scored on:
1. **Cable clearance**: plug heads and cable exits at every used jack must not be blocked (today's
   `routing.route_project` / `routing.power_plug_clearance` / `jacks.check` produce `ctx["violations"]`).
2. **Distance to the power supply**: power cable length from the supply port to each pedal's power jack (supplies
   sit under the board; today a right-angle estimate between half-clearance measuring points, see `jacks.check`).
3. **Distance to the previous / next pedal** in the signal chain: signal cable minimum length (`min_mm` from the
   router; a cheap right-angle estimate exists in `jacks.check`).
4. **Footswitch distance**: footswitches of different pedals need clearance between them so the owner does not
   press the wrong one by accident. This needs NEW data: the x/y position of each pedal's footswitch(es).

Footswitch data: set with the existing Tkinter app `scripts/jack_setter.py`, which must be **renamed to a pedal
editor** (e.g. `scripts/pedal_editor.py`) and extended to place footswitches as well as jacks. Positions are
stored like jacks (fractions 0..1 of the unrotated Pedal Playground image; catalog file written only by the editor).

## Context you need
- Layout input: `projects/<name>/playground_design.json` (the owner's Pedal Playground save; only guitar-gig has
  one). Parsed by `scripts/design.py` (inches/px -> mm, rotation 0/90/180/270 about the centre).
- Output today: `projects/<name>/playground.json` written by `scripts/to_playground.py` (Pedal Playground
  "Load from File"); a proposal should produce a loadable layout the owner can open and tweak.
- Jack data: `catalog/jacks.json` (owner-placed; never change positions). Cable/plug types: `catalog/cables.json`.
- Router: `scripts/routing.py` (2 mm grid A*, negotiated congestion; ~0.2 s per board). Fine to call it to score a
  final candidate, probably too slow to call inside a large search loop: plan a cheap surrogate + final check.
- Board area, front limit, edge margin: see `routing.settings` / `build_grid`.
- Tests: pytest with hand-computed geometry (`tests/`). Build: `python3 scripts/build.py`.

## Owner preferences (keep)
- Approximation, not simulation: all cables bend alike, no 3D, simple models.
- mm everywhere; no pedal images in the repo (fetch into `.cache/images/`).
- Findings are warnings first; strict flags promote them.
- Never invent specs; unknown = null.
- Don't handle guitar-practice now; guitar-gig is the main target (bass has no layout yet).
- Commit/push only when asked; work on `feat/pedal-position`.

## What the plan must cover
- Data model for footswitches (catalog file and fields, e.g. id, label, x, y, maybe a footprint/diameter) and the
  footswitch-clearance rule (parameter per project, default to propose with reasoning, e.g. a minimum
  centre-to-centre distance in mm).
- Pedal editor: rename (keep a compatibility shim or not?), UI changes to place footswitches, file format,
  `--list-missing` for footswitches.
- Objective: how the four criteria combine (weights / hard constraints vs soft costs; which are hard: no overlap
  of pedals, inside the board, clearance?), configurable per project.
- Search: algorithm (e.g. greedy + local search / simulated annealing on positions and 0/90/180/270 rotations,
  keeping rows? keeping the owner's layout as the start and moving as little as possible?), constraints (board
  bounds, no overlaps, supplies under the board, pedals that must stay fixed, e.g. owner pins), runtime budget.
- Outputs: proposed `playground_design` / `playground.json` variant (don't overwrite the owner's file), a README
  section with before/after scores and moved pedals, maybe an SVG diff.
- Phasing into small reviewable steps, tests per step, and open questions for the owner.

Return the plan as Markdown (it will be saved as `docs/plans/pedal-position.md`).
