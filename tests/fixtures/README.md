# Test fixtures

`guitar-gig/` is a frozen copy of the guitar-gig project as it was on 2026-10-20 (the layout the tests' expected values
were computed on): `project.json`, `board.json` and `proposals/` as committed on `main` at that time, and
`playground_design.json` = the owner's layout `projects/guitar-gig/playground_history/2026-10-20T134405_design.json`
(legacy v1 format).

It is frozen on purpose: the live `projects/guitar-gig/` changes whenever the owner fetches a new layout, and tests must
not follow it. Update it only deliberately (and then re-check every expected value in the tests that use it). Tests never
write into it: use `gig_copy(tmp_path, monkeypatch)` from `tests/conftest.py` for anything that writes or resolves
project names.
