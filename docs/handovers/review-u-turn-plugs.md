# Handover: code review of feat/u-turn-plugs

## Goal
Review branch `feat/u-turn-plugs` (worktree /home/pvieira/projects/pedalboard/.claude/worktrees/agent-af7da533b5a689f31;
`git diff f38d901..HEAD -- scripts tests` there) for correctness bugs. Report findings only; do not edit or commit.

## What it must do (owner, 2026-11-13)
A cable may pass UNDER its own plug (the plug sits high enough that one thin cable fits under it); no keep-out, no extra
length: `min_mm` stays the routed deck path. Only its own cable passes under a plug; other cables cross over as before.
The feature only DETECTS and REPORTS it (info, no warning): `routing.plug_body_rects`, `inside_length`,
`passes_under_own_plug`, flags `under_own_a` / `under_own_b` set in `route_project` (signal) and `route_power` (DC; a
pedal-start daisy leg's end a = the previous pedal's plug), README Exits cell "(passes under its own plug)", a sentence under
the cable table, a build log line. Routing, sides, lengths must be identical to before.

## Check
- Detection geometry: a segment that only touches / runs along an edge is not flagged; down plugs, fixed boxes, straight
  plugs; under-board segments ignored; the right plug for each end (a / b; daisy legs; forked legs sharing a port).
- No change to routing results (compare against main if needed).
- Tests in tests/test_u_turn.py test what they claim (hand-computed values).

## Deliverable
A short list of real bugs (file:line, concrete failure scenario). No style nits.
