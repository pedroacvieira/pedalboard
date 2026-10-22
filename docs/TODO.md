# To do

Hand-written backlog (not generated). Build-derived findings (warnings, data to verify, shopping list) live in the
generated `README.md`; this file holds the work and the questions for the owner. Tick items off or delete them when
done, and keep `CLAUDE.md` current when a decision changes.

## Branch `feat/cable-routing`
- [ ] Code review of the branch, apply the fixes, merge into `main`, push (owner asks for each step).

## Owner input needed
- [ ] Measure one **Ernie Ball flat patch plug**: depth from the jack face (catalog: 6.4 mm, maker) and the length
      from the jack axis to where the ribbon leaves (catalog: 19 mm, estimate). Update
      `catalog/cables.json` `ernie_ball_flat_patch_ra` and its `verified` list.
- [ ] Measure one **Ojai DC plug** (depth from the jack face, width, height) and its cable thickness. The current
      `dc_ra_2_1_low_profile` (RockBoard 20 x 11 x 10.5 mm, mapped by interpretation, ~11 mm deep) is deeper than the
      Ernie Ball plug, against the owner's expectation; RockBoard's own page also gives 5/16 in height.
- [ ] Confirm the power-jack fallback box `jacks.power_clearance` (default 5.5 x 5.5 mm, estimate).
- [ ] Power plug side: when neither side is blocked the tool reports "left". Does the side matter?

## Gig board layout
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
