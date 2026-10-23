# Handover: implement `feat/pedal-position`, part 1 (phases 0-2)

Branch `feat/pedal-position` (from `main` 40f60c7, already checked out). Read `CLAUDE.md`, then the plan
`docs/plans/pedal-position.md` INCLUDING its final section "Owner decisions, 2026-10-22", which overrides the plan.

## Scope of this part
- **Phase 0** (refactors, no behaviour change): items injection (`build.validate(..., items=None)` /
  `jacks.check` layout from injected items), `design.move`, `design.write_canvas`, with the plan's tests.
- **Phase 1** (footswitch data + rule in the build): `catalog/footswitches.json` (only `_doc` + empty map: the owner
  places the data), `scripts/footswitches.py`, build call, README "Footswitches" section, SVG dots, scaffold block,
  validation flags `require_footswitches` / `strict_footswitches`. Per the owner: every switch is recorded with
  `bypass: true|false`; `min_distance_mm` defaults to `"auto"` = the smallest distance between switches of different
  pedals in the owner's `playground_design.json` (report it; while that is the limit, the owner's own layout has no
  findings by construction); a number overrides it. Bypass priority matters for the optimizer later; in the build,
  list the closest pairs with their bypass flags.
- **Phase 2** (pedal editor): `git mv scripts/jack_setter.py scripts/pedal_editor.py` (clean break, no shim), all
  references (incl. the `_doc` line of `catalog/jacks.json`, nothing else in that file), footswitch mode (J/F keys,
  `--footswitches`), "no footswitch" checkbox (`[]`), bypass checkbox per switch, on-body check, numpy -> Pillow,
  `--list` / `--list-missing [--only jacks|footswitches]`, pure helpers with tests.

Not in this part: the optimizer (layout.py, propose_layout.py), power re-assignment, proposals.

## Constraints
- Never change jack positions in `catalog/jacks.json`; never write `playground_design.json`.
- mm everywhere; no images in the repo; findings are warnings unless strict flags; unknown = null.
- Keep the build fast and green and all tests passing; add hand-computed tests.
- GUI code can't be run headless: keep logic in pure functions and test those; say what was not run.
- Commit each phase on `feat/pedal-position` with a clear message ending with
  `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`; do NOT push or merge.
- Update `CLAUDE.md` (layout, commands, conventions) and `docs/TODO.md`; add a "Current state" note at the end of
  this handover when done.

## Acceptance
- Build green; tests pass; `uv run scripts/pedal_editor.py --list-missing guitar-gig --only footswitches` prints the
  17 gig pedals' commands; README of guitar-gig shows the Footswitches section (data missing for now).
- Report: what changed per phase, commits, test count, what could not be verified (GUI), open questions.

## Current state (2026-10-22, end of part 1)
Phases 0-2 done on `feat/pedal-position` (not pushed, not merged), plus the owner's later `tap` flag:
- Phase 0: `build.validate(..., items=None)` / `jacks.check(..., items=None)` with `jacks.load_items`, `place_chain`,
  `layout_from_items`; `ctx["layout_source"]`; `design.move` (snaps to whole px) and `design.write_canvas`.
- Phase 1: `catalog/footswitches.json` (empty map), `scripts/footswitches.py`, build call, README "Footswitches",
  open issues line, SVG dots, scaffold, `require_footswitches` / `strict_footswitches`, `min_distance_mm` "auto".
- Phase 2: `scripts/pedal_editor.py` (renamed, footswitch mode, no-footswitch box, bypass + tap boxes, on-body check,
  Pillow only, `--footswitches`, `--list`, `--list-missing ... --only`); `catalog/jacks.json` `_doc` line only.
- Not run: the Tkinter main loop (a scripted smoke test built the window withdrawn and drove its methods; the owner
  should click through it once). Footswitch data and the auto minimum await the owner's placement.
