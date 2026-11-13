# Handover: code review of feat/pedal-preferences

## Goal
Review branch `feat/pedal-preferences` (worktree /home/pvieira/projects/pedalboard/.claude/worktrees/agent-af1a76db1f4133b36;
`git diff f38d901..HEAD` there) for correctness bugs. Report findings only; do not edit or commit.

## What it must do
One preference profile per pedal in `project.json` `pedals.<id>` (position side / depth + strength, pin, rotations, order wishes
-> ordering rules, power wishes, topper, access override). `scripts/preferences.py` `lower(project)` fills the OLD keys
(`rules`, `layout.pins`, `layout.rotations`, `layout.access.pedals`, `footswitches.toppers`) in memory, so the rule engine, the
layout model and the toppers stay unchanged; the old keys stay readable (a conflict = error). New: a `position` term in the
layout surrogate (penalty only), required position / power wishes = build warnings (errors with
`validation.strict_preferences`), `power.assign(wishes=)` (required = feasibility, preferred = 300 mm), a proposal gate on
unmet required wishes, README "Preferences" table, migration script `pb migrate-preferences` (+ `common.dump_project`).
The live projects must build exactly as before (identical errors / warnings / cable lengths).

## Check
- `lower` idempotent; every reader of the old keys gets the lowered project (build, layout.settings, propose_layout,
  proposal_inputs_sha1); no double-lowering side effects.
- Rule ids / rule_overrides survive; priorities; conflicts detected.
- power.assign with wishes: feasibility, cost, no crash when no wishes; agreement of build and proposal paths.
- Migration: lossless (old -> profiles -> lower == old semantics), dry-run vs write, formatter round trip.
- Tests (tests/test_preferences*.py) test what they claim.

## Deliverable
A short list of real bugs (file:line, concrete failure scenario), most severe first. No style nits.
