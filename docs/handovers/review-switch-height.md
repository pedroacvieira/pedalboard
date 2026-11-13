# Handover: code review of feat/switch-height

## Goal
Review branch `feat/switch-height` (worktree /home/pvieira/projects/pedalboard/.claude/worktrees/agent-ac1c5f4575ce4c8cb;
`git diff 09c8e73..HEAD -- scripts tests` there) for correctness bugs. Report findings only; do not edit or commit.

## What it must do (plan docs/plans/switch-height.md, recommended defaults)
- Height step: a pair of footswitches on different pedals gets effective distance d + 0.5 x min(|h1 - h2|, 10 mm) (heights =
  catalog `height_mm`, the switch top), plus `topper_bonus_mm` 4.5 per topper (toppers NOT inside the step).
- Shadow (reach): a switch is shadowed when a taller switch on another pedal stands in the strip in front of it where the
  foot passes (foot 80 mm wide, 190 mm long, 5 deg pitch, flat deck `deck_rise_mm` 0); a topper's 4.5 mm counts in the reach
  model. Shadow sum = reach cost.
- Topper suggestions minimise crowding + 1.0 x shadow sum; the layout search uses the step always and a `reach` term
  (weight 1.0); `max_shadow_mm` opt-in finding; `footswitches.heights: false` = exactly today's output.
- README: Step column, Reach table, "Shadow removed" column, proposals row "Footswitch shadow (sum, mm)".

## Check
- Formulas and geometry (`step_mm`, `pair_distance`, `switch_heights`, `shadow_map`, `shadows`, `reach_cost`): rotated pedals,
  unknown heights (null), pairs on the same pedal excluded, front direction of the board.
- Build and layout surrogate agree (crowding and reach); `heights: false` gives the old numbers exactly.
- `suggest_toppers` objective and stop rules (max_toppers, min_gain) still sound.
- Tests test what they claim (hand-computed).

## Deliverable
A short list of real bugs (file:line, concrete failure scenario), most severe first. No style nits.
