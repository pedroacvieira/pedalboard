# Handover: write the plan for `feat/switch-height` (planning only, no code)

## Goal
Write `docs/plans/switch-height.md`: an implementation plan, then stop. Do not change code, data or git state.

## The feature (owner's backlog, 2026-10-27)
"Toppers and pedal height: a low pedal at the back of the board is harder to reach, a tall pedal is naturally easier to
reach and may not need a topper at all. Needs a height per pedal (enclosure height, and the switch height above the board)
and a reach / position model (back vs front row); then the spacing model (`topper_bonus_mm`) and the suggestions weigh a
switch by its height and position."

## What exists
- `catalog/pedals.json` `height_mm` per pedal (every pedal has one; null = unknown) = the footswitch top above the pedal's
  base (owner rule: the footswitch is the pedal's tallest point), `height_info` with source / confidence. No board deck
  height or rubber feet are modelled.
- Footswitch spacing (`scripts/footswitches.py`): crowding of a pair on different pedals = priority x max(0, comfort - d)^2 /
  comfort (`crowding`, comfort `footswitches.comfort_mm` 100); toppers per project `footswitches.toppers`
  ["<pedal>.<switch>"]: a pair's effective distance = d + `topper_bonus_mm` (4.5) per topper (`effective_distance`);
  post-layout suggestions on bypass switches only (`suggest_toppers`, greedy, `max_toppers` 5, `topper_min_gain`).
  The layout search (scripts/layout.py, footswitch term) and the proposals ignore toppers.
- Accessibility in the layout search (scripts/layout.py `access_rule`, `ACCESS`): front / back preferences per tag.
- Footswitch positions: `catalog/footswitches.json` (fractions of the pedal image), the board depth from the layout.

## Constraints
Units mm; never invent data (estimates are marked); Python 3.12 via `uv run`; pytest with hand-computed cases; gig-dependent
tests use `tests/fixtures/guitar-gig/`. The model is an approximation, not a 3D simulation. Findings start as warnings.

## The plan must contain
The model (how height and depth position change the effective distance / crowding of a pair and a switch's reach; formulas
with a worked example on two real gig pedals), whether and how a topper's benefit depends on the switch's height, how the
suggestions and the build report change (README), whether the layout search uses it, config keys with defaults, test list,
implementation steps (each a self-contained handover for a Sonnet agent), risks, and "Decisions for the owner" each with a
recommended default (implementation will start with the defaults).

Read the code you need (scripts/footswitches.py, scripts/layout.py, scripts/build.py footswitch section, a few
catalog/pedals.json entries, projects/guitar-gig/project.json); do not read other plans or handovers.

## Deliverable
The plan file written, and a 10-line summary with the decisions and your recommended defaults.
