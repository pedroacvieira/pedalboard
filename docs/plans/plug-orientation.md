# Plan: `feat/plug-orientation`: plugs pointing down into a hole, straight DC plugs, plug-to-plug collisions

Status: in progress (2026-10-28), branch `feat/plug-orientation` (created from `main` at the commit that adds this file).
This file is the entry point for a new conversation: read it, then `CLAUDE.md`, then follow "How to run this".

## How to run this (for the agent that picks this up)
1. Read `CLAUDE.md` (conventions, working agreements) and this plan. Do not read old handovers.
2. Ask the owner the questions in "Decisions to confirm" (one AskUserQuestion round, recommendations first); write the
   answers into this file under "Owner decisions, round 2".
3. Per phase: write a handover `docs/handovers/plug-orientation-<n>.md` (minimal and self-contained, as CLAUDE.md
   says), delegate it to a `general-purpose` agent on `model: sonnet`, verify (tests, build, the gig before/after),
   commit on `feat/plug-orientation`. Phases 1-2 are the core; 3-4 follow.
4. At the end: code review of the branch (`/code-review main...feat/plug-orientation`), fix the findings, update
   CLAUDE.md and `docs/TODO.md`, regenerate the gig proposals, then ask the owner before merging into `main`.

## Goal (owner, 2026-10-28)
Cables (power and signal) whose jack sits above a board hole may go **straight down into the hole**, whether they then
stay under the board or come back up somewhere else. A cable going down frees space next to the pedal. Example on the
gig: the Tumnus Deluxe's three jacks (input, output, power) all face the back of the board and sit right over a slot.
Today its power cable P13 (leg of the serial DC cable C8) leaves its right-angle plug to the left and lies along the
pedal, where it actually blocks the Tumnus's output jack.

The owner's two ways of solving it:
- **Straight DC plug**: no right angle, so the plug is slimmer, but it takes more room outwards from the jack.
- **Right-angle plug pointing down**: the cable leaves the head downwards into the hole; this uses the least 2D space on
  the board.

## Facts (checked on main, 2026-10-28)
- Tumnus Deluxe (gig): footprint x 23.1..94.3, y 216.2..343.2 mm, rotation 0. Jacks: `out` (output) at (40.5, 216.6),
  `power` at (55.5, 219.9), `in` (input) at (70.2, 216.6), all facing `top` (the back). The effective hole
  x 38.5..186.6, y 201.3..219.8 lies right under the space in front of all three jacks (3-10 mm out is inside it).
- The Tumnus is the LAST pedal: its output is the board's last output (guitar/amp cable, not modelled, fixed audio box
  `jacks.clearance` 6.3 x 7 mm). P13: protein.power -> tumnus_deluxe.power, 278 mm, 2 holes, 66 mm on top, exit left.
- **Plugs do not collide with each other in today's model**: clearance checks each plug (head + barrel + cable run, on
  the chosen exit side) against pedal OUTLINES only (`routing.blocked_parts`, `jacks.check` fixed boxes,
  `routing.power_plug_clearance`); `cables.max_over_plug` only limits cables CROSSING a plug. So "the power plug blocks
  the output jack" is not reported today. This must be modelled first (phase 1), else the router has no reason to pick
  another orientation.
- Plug model: `design.plug_geometry(point, facing, plug, diameter_mm, run_mm, side)`: right-angle plugs exit `left` or
  `right` of the facing (`design.SIDES`), parts head / barrel / cable (straight run `cables.exit_run_mm`), `exit`
  point where the router starts, `measure` point and `measure_mm` for lengths; straight plugs exit along the facing at
  head depth. `routing.end_options` gives the options per end; `route_project` picks the signal sides (feasible, fewest
  blocked parts, shortest route; `cables.overrides.<S#>.exit_a / exit_b` fix them); `routing.power_plug_choices` picks
  each power plug's side (fewest blocked parts, then least overlap; `overrides.<P#>.exit_b`, on-board ports `exit_a`).
- Two-layer router (`routing.Under`): search states (i, j) on top and (i, j, 1) under the board; layer changes only at
  hole cells (inside an effective hole, free on top AND under) or owner-drawn edge segments, at `hole_transit_mm`
  (board data, 15, unverified) + `hole_penalty` 15 (signal search only). Power legs from an under-board supply start
  under the board. Lengths: `min_mm` = plug measures + polylines per layer + transits.
- Cable types (`catalog/cables.json`): `ernie_ball_flat_patch_ra` (patch, right-angle, 3.5 mm ribbon, head 6.4 x
  12.7, exit offset 3.2, body reach 19.0), `dc_ra_2_1_low_profile` (power, right-angle, 3.2 mm, head 11 x 11, exit
  offset 5.5, body reach 14.5). There is **no straight DC type** (only `generic_straight` / `neutrik_np2x`, role
  reference). Owner rule: every PATCH plug is angled (no straight patch plugs).

## Design
### A. Plug-to-plug collisions (phase 1)
- Every used plug's footprint (head, barrel, straight cable run on its chosen side; the fixed boxes of jacks without a
  plug model: first input / last output / extra jacks; power boxes without a power type) must not overlap another
  plug's footprint (TOL like pedals). A collision is a clearance finding ("clearance: tumnus_deluxe.power (DC plug,
  exits left) collides with the plug at tumnus_deluxe.out (last output, fixed box): 4.2 mm"), warnings unless
  `validation.strict_clearance`.
- Side choice takes collisions into account: signal sides are chosen first (as today); power plug sides then avoid the
  signal plugs and fixed boxes; a collision counts like a blocked part in the ranking. (Joint choice per pedal is
  optional; say if it is needed.)
- Expected on the gig: P13's left exit collides with the Tumnus output box -> the right exit or (phase 2) down.

### B. Right-angle plug pointing DOWN (phase 2)
- New exit `down` for right-angle plugs (signal and power): the cable leaves the head downwards at the bend point
  (jack point + facing x `exit_offset_mm`). Available only when a disc of the cable's radius around the bend point lies
  inside an effective hole and the under-board cell there is free (under-board supplies are obstacles under the board).
  The top-layer "free" rule for hole cells does NOT apply here: the plug sits right next to its own pedal.
- Footprint on the board: the head only (no barrel, no cable run): the smallest 2D footprint.
- Routing: that end of the cable is the UNDER state of the cell below the bend point; from there the router continues
  under the board, or comes back up through a hole / edge segment as usual (no special case: "go down and come up
  immediately" is a normal layer change in the same slot, further from the pedal where the top is free).
- Length: `measure_mm` = |exit_offset - head_depth/2| + `jack_height_mm` (jack axis above the deck; new setting, see
  decisions) + `hole_transit_mm` (the deck). Then the under polyline etc.
- Choice: `down` joins `left` / `right` in the option set per end (`end_options`); ranking as today (feasible,
  blocked parts + collisions, then length) unless the owner prefers down whenever possible (decision). Overrides:
  `exit_a / exit_b: "down"` allowed (error if no hole under the plug).
- Drawing: routing.svg / power.svg draw the head and a down marker (e.g. a filled circle with a cross) at the bend
  point; the README "Exits" column shows `down`.

### C. Straight DC plug (phase 3)
- A straight DC type in `catalog/cables.json` (role power, style straight: head depth, width, cable diameter; research
  with sources, "unverified" otherwise, or the owner's measured plug).
- Projects may list several power plug types: `cables.power_types` [ids] (default [`cables.power_type`]); per power
  jack the router picks the type and exit (right-angle left/right/down, straight) by the same ranking; overrides
  `overrides.<P#>.type_b` / `exit_b`. The README / "DC cables to buy" say which plug each end needs.
- Note for the plan: a serial daisy chain cable has its plugs fixed by the cable; mixed plug styles on one serial
  cable may be unrealistic -> decision.

### D. Layout search and estimate (phase 4)
- `layout.py` surrogate: plug options include `down` where the candidate position puts the bend point over a usable
  hole (the hole sample of `power.Crossings` / an inside-hole test per candidate; keep the search fast), collisions in
  the clearance term; the power estimate counts a down exit as an under-board start.

## Decisions to confirm (ask the owner; recommendation first)
1. `jack_height_mm` (jack axis above the deck, for the down length): one project default (recommend 12 mm, unverified:
   typical jack centre ~8-10 mm above the enclosure bottom + feet / velcro), optional per pedal later.
2. Down preference: (a) rank `down` like any other exit (blocked parts + collisions, then length) — recommended, it
   wins exactly when the side exits collide or block; or (b) always prefer down when available (least 2D space) even
   if longer; or (c) a project toggle `cables.prefer_down`.
3. Straight DC plug: does the owner have a straight DC plug (measure head depth / width / cable diameter), or should the
   plan research a typical one? May a serial daisy-chain cable mix plug styles?
4. Collisions with the fixed boxes of first input / last output (guitar / amp cables, not modelled): count them as
   plugs (recommended: yes, the Tumnus output is the gig's example).
5. Signal plugs down too (recommended: yes, same model; patch plugs are right-angle).

## Owner decisions, round 2
### Measurements (owner, 2026-10-28: one random power cable, one end straight, the other angled)
Clearance needed around each plug, measured from the jack (mm):
- **Right-angle DC plug**: 12 outwards (along the facing); on the side it bends to 19 (from the jack axis, where the
  cable leaves the body); on the opposite side 4 (= the head's radius). Pointing DOWN it needs only 4 to each side
  and the same 12 outwards.
- **Straight DC plug**: 34 outwards; radius 5 (10 wide in all: 5 to each side).
Owner (2026-10-28): this cable is probably bigger than most of the owner's own; the straight plugs (and maybe the
right-angle ones) are likely smaller. Use these values as the BASELINE; the owner updates them later. So: keep every
plug dimension in `catalog/cables.json` (data, never hard-coded), mark them "owner baseline, may be smaller", and keep
the code and tests independent of the exact values (tests use their own synthetic plug types).
How to use them (for the phase handovers):
- Update `catalog/cables.json` `dc_ra_2_1_low_profile` (or add a new measured type and make it the gig's
  `cables.power_type`; say which and why): `head_depth_mm` 12, `head_width_mm` 8 (2 x 4), `body_reach_mm` 19;
  `exit_offset_mm` stays the default (depth / 2) unless the owner gives it; `verified`: "owner measured a random DC
  cable, 2026-10-28". Keep the RockBoard figures in the notes.
- The down exit's footprint = the head only: 12 deep x 8 wide (4 to each side of the jack axis), exactly as measured.
- Phase 3 straight DC type (role power, style straight): `head_depth_mm` 34, `head_width_mm` 10; cable diameter
  unknown: keep the right-angle type's diameter and mark it unverified.
- The measured cable has one straight and one angled end: a power cable may need a DIFFERENT plug type per end
  (the plug at the supply port vs at the pedal). Phase 3 must allow a type per end (e.g. `type_a` / `type_b` in
  `cables.overrides.<P#>`, or `power_types` per end), not one type per cable.
- Effect to report: today's `dc_ra_2_1_low_profile` is 11 deep x 11 wide with the body reaching 14.5; the measured
  plug is deeper (12), narrower (8) and reaches further on its bend side (19), so the gig's power clearance findings
  will change once the catalog is updated: list them before / after.

### Answers to "Decisions to confirm"
Owner, 2026-10-28:
1. `jack_height_mm`: one project default `cables.jack_height_mm` = 12 (unverified estimate; per pedal later).
2. Down preference: **always down when available**, even if longer (least 2D space). Ranking per end: feasible
   first (inside the area, free path), then down before left/right, then blocked parts + collisions, then length.
   (Down's footprint is the head only, a subset of a side exit's, so it never has more blocked parts.)
3. Plug styles on one cable: **one style per serial cable**: all the pedal-end plugs of a serial daisy-chain cable
   share one plug type; only the port plug (the supply end) may differ. A forked cable (one per pedal today) picks
   its pedal-end type per cable. The straight DC size = the owner baseline above.
4. Collisions with the fixed boxes of first input / last output (guitar / amp cables): **yes**, they count as plugs.
5. Signal plugs down too: **yes** (same model as the power plugs).

### Catalog step (done before phase 1, commit "plug-orientation: owner-measured DC plugs")
New types `dc_ra_owner_baseline` (right-angle 12 x 8, body reach 19) and `dc_straight_owner_baseline` (straight
34 x 10), both "owner baseline, may be smaller"; gig and practice `cables.power_type` = `dc_ra_owner_baseline` (a new
type rather than editing `dc_ra_2_1_low_profile`, so the RockBoard reference data stays as published). Gig effect:
every power cable a bit longer (P13 278 -> 287 mm, DC total 3231 -> 3344 mm), exits unchanged (all left); clearance
findings 2 -> 4: monk.power 9.0 -> 15.0 mm (barrel), new red_muck.power / analog_chorus.power heads 1.0 / 1.3 mm
(their 12 mm deep heads now reach each other's pedal).

## Acceptance
- `uv run pytest tests -q` passes (+ hand-computed tests per phase: collision depth, down availability at a hole edge,
  down length, straight plug option, overrides, surrogate).
- `uv run scripts/build.py` runs. Report the gig before/after per changed cable (P13 at least: exit, length, findings)
  and the Tumnus findings; routing.svg / power.svg show the down plugs.
- CLAUDE.md (plug model, collisions, down exit, power types, jack height) and docs/TODO.md updated; proposals
  regenerated; code review fixed; merge after the owner's OK.
