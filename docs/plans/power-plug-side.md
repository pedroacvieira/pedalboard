# Plan: DC plug side by route length (`feat/power-plug-side`)

## Owner decision (2026-10-29)
A DC plug's exit side only matters for the cable length. When the sides are equally good on everything that matters for the
fit (feasible, down, blocked parts + plug collisions), take the side with the SHORTER power cable, as the signal plugs
already do, instead of today's tie-break (least overlap, then the type's list position, then the first option = "left").
The layout surrogate's power estimate should follow.

## Today
- Build: `routing.power_plug_choices` picks every DC plug BEFORE the power cables are routed, by `routing.plug_rank`:
  `(failed, infeasible, not down, blocked + collisions, overlap sum, type index)`. Length is not in the key.
  `route_power_choosing` then routes (`route_power`, own power grids) and retries with `avoid` only for unroutable legs.
- Signal plugs (`choose_signal`, for comparison): among the combinations tied on the fit key, A* (`plain_search`) on the
  grid tells them apart by length.
- Surrogate (`layout.py`, phase A "power plugs ... clearance only"): per DC plug the option with the lowest clearance cost
  (`_clearance`); the power term (`power.hop_estimate`, nearest crossing) does not depend on the side picked.
- A DC plug can end two legs (serial daisy chain: the cable in and the cable out share the pedal's plug position) or one
  (forked, last in a chain, under-board port hop).

## Design
1. **Fit key unchanged, length before overlap.** New rank:
   `(failed, infeasible, not down, blocked + collisions, length, overlap sum, type index)`.
   Length = the sum, over the legs that touch this plug, of the measure (plug geometry, `measure_mm`) + the leg's span.
   Only options tied on the first four fields compete on length, so length never beats a fit criterion.
2. **Two stages (like the signal plugs).**
   - *Estimate* (in `power_plug_choices`, no grid yet): span = `power.hop_estimate` from the option's exit to the leg's
     other end (an under-board port: its measure point, under; a neighbour pedal: its jack's measure point, as
     `power.measure_points` gives it; nearest-crossing estimate with `power.Crossings`). Cheap, same function as the surrogate.
   - *Routed refinement* (in `route_power_choosing`, after the first `route_power`): for every plug whose estimate-ties
     (options within `TIE_MM` of the best estimate on the same fit key) remain, A* on the power grid (plain costs, no
     congestion, as `plain_search`) for its legs with each option, the other ends as chosen; switch when the routed sum is
     shorter by more than `SWITCH_MM`; route once more and keep the result only if no leg became unroutable and the total
     power min length did not grow (else the first routing stands, as the `avoid` retry does today).
3. **Serial cables**: one type per serial cable stays (`decide_group`); length joins its summed ranking the same way.
4. **Overrides**: `cables.overrides.<P#>.exit_b` still fixes the side (no length choice for that plug).
5. **Rounds with the signal plugs**: the DC choice keeps running inside the existing `SIDE_ROUNDS` loop; the estimate stage
   is part of `choose_dc`, so the signal plugs see the new DC footprints. The routed refinement runs after the loop and
   only between options that are tied on collisions with the signal plugs already chosen, so no signal side has to change.
6. **Surrogate**: the DC plug option per pedal is picked by the same key (clearance cost, then the estimated span of its
   legs); the power term then uses the chosen option's exit instead of the jack point, so moving a pedal to give its plug
   the shorter side shows in the score.
7. **Report**: README "DC cables to buy" unchanged in form (lengths shrink); the build log gets one line per project:
   `power: N DC plugs took the shorter side (saved X mm)` (vs the old tie-break), so the owner sees the effect.

## Tests
Hand-made cases: a pedal whose power jack faces back with the supply port to its right -> the right exit wins (estimate
and routed); a tie broken against today's "left"; an override keeps its side; a down option still wins even when longer;
a blocked / colliding side never wins on length; a serial chain where the middle plug's side changes both legs; the
surrogate picks the same side as the build on a small layout. Gig fixture: total DC min length not longer than before,
no new findings (list the plugs whose side changed).

## Open questions (owner)
1. `SWITCH_MM`: switch sides only when it saves more than ~5 mm? (Avoids flapping between near-equal routes; a few mm do
   not change which cable you buy.) Default proposal: 5 mm.
2. Is the routed refinement wanted, or is the estimate enough? (The estimate misjudges routes around pedals; the refinement
   costs one A* per tied plug and option, ~20 plugs on the gig: cheap.) Proposal: both.
3. When one side gives a shorter cable but a slightly bigger overlap with a neighbour that is still no blocked part (e.g.
   both within the clearance), length wins (as above). OK?
