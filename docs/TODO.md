# To do

Hand-written backlog (not generated). Build-derived findings (warnings, data to verify, shopping list) live in the
generated `README.md`; this file holds the work and the questions for the owner. Tick items off or delete them when
done, and keep `CLAUDE.md` current when a decision changes.

## Branch `feat/pedal-position` (current)
- [ ] Plan: `docs/plans/pedal-position.md` (handover `docs/handovers/pedal-position.md`); answer its open questions.
- [x] Phases 0-2 (2026-10-22): layout injection, `design.move` / `write_canvas`, footswitch data + spacing check,
      `scripts/pedal_editor.py` (renamed from jack_setter, footswitch mode, Pillow instead of numpy).
- [ ] Manual GUI check of the pedal editor (footswitch mode, J/F, no-footswitch box, the four-way switch type) by the owner.
- [x] Phases 3-5 (2026-10-22): `scripts/layout.py` (surrogate score, search), `scripts/power.py` (policy checks
      shared with the build, power assignment per layout), `scripts/propose_layout.py`, README "Layout proposals".
- [ ] Owner: look at the guitar-gig proposals (`projects/guitar-gig/proposals/1.json`, Load from File) and say whether
      the moves are acceptable; tune `layout.weights` / `max_move_mm` if not.
- [ ] Owner: try `--max-change rearrange` (bigger moves, swaps, rotations) once and judge the result.
- [ ] Footswitch term is 0 until the footswitches are placed; rerun the proposals after placing them.
- [ ] Surrogate vs router: the signal estimate (octile + detour around crossed pedals) still misjudges some routes
      (finalists are checked with the router, so proposals are safe, but the search may miss better ones).
- [ ] `feat/cable-routing` is merged into `main` locally (2026-10-22); push `main` when the owner asks.
- [ ] Code-review leftover (not fixed, efficiency only): the router runs A* to pick exit sides and then again in
      `route_all`; reuse the first path if the build ever gets slow (today ~0.2 s).

## Owner input needed
- [ ] Place the footswitches of the 17 gig pedals (`python3 scripts/pedal_editor.py --list-missing guitar-gig --only
      footswitches`), picking the type (bypass / tap / boost / function) per switch; then read the auto minimum in the gig README and calibrate
      `footswitches.min_distance_mm` if wanted.
- [ ] Measure one **Ernie Ball flat patch plug**: depth from the jack face (catalog: 6.4 mm, maker) and the length
      from the jack axis to where the ribbon leaves (catalog: 19 mm, estimate). Update
      `catalog/cables.json` `ernie_ball_flat_patch_ra` and its `verified` list.
- [ ] Measure one **Ojai DC plug** (depth from the jack face, width, height) and its cable thickness. The current
      `dc_ra_2_1_low_profile` (RockBoard 20 x 11 x 10.5 mm, mapped by interpretation, ~11 mm deep) is deeper than the
      Ernie Ball plug, against the owner's expectation; RockBoard's own page also gives 5/16 in height.
- [ ] Confirm the power-jack fallback box `jacks.power_clearance` (default 5.5 x 5.5 mm, estimate).
- [ ] Power plug side: when neither side is blocked the tool reports "left". Does the side matter?
- [ ] Polarity: every pedal and supply is recorded center-negative (owner); add the real value when a
      center-positive pedal arrives.

## Gig board layout
- [ ] Both findings below are fixed by the fix-level proposals (`projects/guitar-gig/README.md`, Layout proposals).
- [ ] Monk / Belle Epoch are too close: `monk.out` (1.0 mm) and `monk.power` (5.1 mm) plug heads are blocked by the
      Belle Epoch. Move one apart in Pedal Playground and re-save `projects/guitar-gig/playground_design.json`
      (or confirm with measurements that the plugs fit).
- [ ] `red_muck.power` DC head blocked 3.0 mm by the MXR Analog Chorus.

## Features
- [ ] Model the guitar -> board and board -> amp cables (`fender_pro_instrument_ra`, role instrument): needs guitar
      and amp positions (or board-edge exit points) in the project.
- [ ] Under-board routing (cables already carry `under_board`): route power cables from the supply ports under the
      board, then optionally signal cables.
- [ ] Layouts for `guitar-practice` and `bass` (`playground_design.json`), so their cables and clearance are checked.
- [ ] Practice board: out of scope for now (owner, 2026-10-22); the third Ojai R30 is still to buy.

## Data
- [ ] Items in the generated README's "Data to verify" (power specs, Reticon, Protein, version assumptions).
