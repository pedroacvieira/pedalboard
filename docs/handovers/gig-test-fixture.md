# Handover: tests use a frozen copy of the gig project (`feat/playground-v2`)

## Goal
About 20 tests read the LIVE project `projects/guitar-gig/` (its `project.json`, `playground_design.json`, `board.json`,
`proposals/`). The owner now fetches new layouts into it all the time (`scripts/fetch_playground.py`), so these tests
break whenever the owner iterates. Make every test that depends on the gig's content use a frozen fixture copy
instead, so the suite is independent of the owner's live data. No change to scripts' behaviour.

## Where you work
- The main checkout `/home/pvieira/projects/pedalboard`, branch `feat/playground-v2` (checked out; uncommitted work
  of the branch is in the tree: keep it, do not revert anything outside `tests/`). Do NOT commit.
- `uv run pytest tests -q` (~670 tests, ~90 s); never `pip install`.

## Facts
- The layout the tests were written against is the owner's previous one, now at
  `projects/guitar-gig/playground_history/2026-10-20T134405_design.json` (legacy v1 format `{"canvas": ...}`, still
  parsed by `design.parse_design`). The other inputs at that time = the committed versions on `main`:
  `git show main:projects/guitar-gig/project.json`, `git show main:projects/guitar-gig/board.json`,
  `git show main:projects/guitar-gig/proposals/meta.json` (and `1.json`.. `3.json`, `1.svg`.. if a test needs them).
  The only difference of `project.json` on this branch is `playground.share` (harmless; use the main version).
- Failing now (all because of the new live layout): test_daisy_chains.py (5), test_footswitches.py
  (`test_gig_build_with_switch_data_has_no_findings_without_a_minimum`), test_layout.py (5), test_layout_io.py (4),
  test_propose.py (5). Others that read the gig and still pass (test_check.py ~320, test_boards.py ~277,
  test_geometry.py ~135, test_footswitches.py ~190/381, test_pedal_editor.py ~113, test_edges.py ~136,
  test_board_editor.py ~310, test_bounds.py ~292) must also move to the fixture when they depend on the layout or the
  proposals (a test that only checks every project's files generically may stay live: say which in the report).
- Some tests already copy the gig into tmp_path (`test_propose.gig_copy`); `build.validate(pdir, ...)` takes any
  project dir; `common.project_dirs` / `PROJECTS` / `ROOT` can be monkeypatched where a script resolves names.

## Do
1. `tests/fixtures/guitar-gig/` with `project.json`, `playground_design.json` (the history file above), `board.json`,
   and `proposals/` (only what tests need), all as of main. A short `tests/fixtures/README.md`: what it is, frozen on
   purpose, update only deliberately.
2. One helper (e.g. in `tests/conftest.py`): `GIG_FIXTURE` path and `gig_copy(tmp_path, monkeypatch)` that copies it
   into a temp `projects/guitar-gig` and points `common.PROJECTS` (and whatever else is needed) there. Reuse it everywhere
   instead of `ROOT / "projects" / "guitar-gig"`.
3. Expected values in the tests stay as they are (they were computed on that layout); do not loosen assertions. If a
   value genuinely changed for another reason, report it instead of editing it.

## Acceptance
`uv run pytest tests -q` all green with the new live layout in place; `grep -rn '"projects" / "guitar-gig"\|projects/guitar-gig' tests`
only finds intentional live uses (listed in the report). The test run must not modify any file under `projects/`.

## Report back
Files changed, which tests now use the fixture, which stay live and why, the test result.
