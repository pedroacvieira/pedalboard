# Handover: code review of feat/floor-devices

## Goal
Review the uncommitted diff on branch `feat/floor-devices` (`git diff`, scripts/ and tests/ only) for correctness bugs.
Report findings only; do not edit files.

## What it must do (owner, 2026-11-13)
Floor devices (catalog `floor_device: true`: an expression pedal, a wah) sit on the floor, not on any board, and can be
used with any board and with several pedals per board. A project lists the ones it uses in `floor`
[{"device", "controls": ["<pedal>.<jack>"], "note"}]. The jacks a device drives count as used extra jacks:
`jacks.with_floor` merges them into `jacks.extra_used` (applied in `build.validate` and `propose_layout.py`);
`jacks.floor_findings` validates (device exists and is a floor device, controls name chain pedals' existing jacks, a floor
device in signal_chain is an error). README sections: project "Floor devices", root "Floor devices"; floor devices are
excluded from "Catalog pedals not in any project" and never shared gear.

## Check
- Every reader of `extra_used` sees the merged jacks (build path, routing, drawings, layout model, proposal finalists,
  `common.proposal_inputs_sha1`).
- No crash on malformed `floor`; README rendering with malformed entries.
- Tests: tests/test_floor.py.

## Deliverable
A short list of real bugs (file:line, concrete failure scenario). No style nits.
