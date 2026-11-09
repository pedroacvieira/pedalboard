# Handover: code review of feat/extra-plug-types

## Goal
Review the uncommitted diff on branch `feat/extra-plug-types` (`git diff`) for correctness bugs. Report findings only;
do not edit files.

## What the change does (owner decisions, 2026-11-06)
- A used extra jack (`project.jacks.extra_used`, e.g. an Exp jack) gets a STRAIGHT plug box instead of the fixed audio
  clearance box when `cables.extra_type` (or per jack `cables.extra_types {"<pedal>.<jack>": type}`) names a straight
  cable type with role expression|patch: box = head depth + one cable diameter along the facing, half the head width to
  each side (`jacks.extra_plug_box`). Built in `jacks.check` (ctx["fixed_zones"], with "plug_type"), labelled in
  `routing.fixed_footprints`, validated in `routing.validate_project_types`, mirrored in the layout surrogate
  (`layout.py`, extra jacks) so the search and the build agree.
- New cable role `expression`, new type `exp_trs_straight_baseline` (catalog/cables.json, placeholder sizes).
- `scripts/pedal_editor.py new_jack`: a pedal tagged "controller" (BOSS EV-30: passive, only two Exp outs) gets
  Exp 1, Exp 2 ('other') jacks instead of Input/Output/Power.
- Catalog data updates (pedals.json): owner's versions; test_power polarity test skips passive pedals (current_ma 0).

## Check
- Same box in the build (jacks.check) and the surrogate (layout.py) for the same project.
- Jacks that are both a default in/out/power AND listed in extra_used (duplicates) behave sensibly.
- Validation messages; no crash when `cables` / `extra_types` is missing or malformed.
- Tests: tests/test_check.py, tests/test_layout.py, tests/test_pedal_editor.py (new tests at the end of each).

## Deliverable
A short list of real bugs (file:line, failure scenario). No style nits.
