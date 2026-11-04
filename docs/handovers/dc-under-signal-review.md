# Handover: review `feat/dc-under-signal`, fix the findings, merge into main

Repo `/home/pvieira/projects/pedalboard`, branch `feat/dc-under-signal` checked out (clean; tracks origin). Python 3.12, `uv run`
only (`uv run pytest tests -q`, ~150-260 s; `PEDALBOARD_SLOW=1 uv run pytest tests -q -k gig`; `uv run scripts/build.py`, exit 0).
Do not push. Commit messages end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## What the branch does (review `git diff main...feat/dc-under-signal`; commits 1d80355, af8a899, 8c6a106; the rest are
## merges of main, regenerated files, proposals and a handover)
Owner decisions (2026-11-03):
1. `catalog/cables.json` `dc_ra_owner_baseline.plug.exit_offset_mm` = 8.4 (owner rule of thumb: 70% of the 12 mm head depth;
   not measured, not in `verified`).
2. A right-angle DC plug may pass under ONE signal plug (patch plug or fixed audio box): plugged diagonally, the power cable
   always goes under the signal cable. Only when BOTH jacks face the same direction on the canvas (after rotation). One-to-one
   pairing (each DC plug at most one signal plug and vice versa), deterministic. Straight DC plugs, DC vs DC, any plug into a pedal
   body: unchanged (collision / blocked). Passes are not collisions: `ctx["plug_under"]`, README line "... passes under the plug at
   ...: plug it diagonally". Power cables drawn below signal cables. `max_over_plug` / stacking untouched.
3. A plug option that reaches past the board edge at the back or a side gets a plug zone (`routing.reaches_out`, `plug_zones`,
   `layout.in_area(board=)`): its cable may start there. Never at the front.
Code: `scripts/routing.py` (`DcRects`, `SigRects`, `like`, `pass_eligible`, `pass_depth`, `assign_passes`, `pass_pairs`,
`collision_count`, `plug_collision_findings`, `under_text`, `power_plug_pool`, `route_project`, `fixed_footprints`,
`refine_dc_sides`, `reaches_out`, `plug_zones`), `scripts/layout.py` (`_opt`, `_pool`, `_collisions`, `_count`, `_resolve`,
`in_area`, `_infeasible`), `scripts/build.py`, `scripts/svgdraw.py`, tests (`test_plug_collisions.py`, `test_layout.py`,
`test_geometry.py`, `test_pedal_body.py`, number updates in `test_daisy_chains.py`, `test_power_plug_side.py`, `test_propose.py`),
CLAUDE.md, docs/TODO.md.

## Review focus
- Correctness of the pairing: deterministic; one-to-one in the build AND in the ranking (`collision_count` with `everything`):
  can the ranking count a pass the final findings then do not grant (or the reverse), e.g. two DC plugs competing for one
  signal plug, or a pass decided against a footprint set that changes in later rounds? Build vs surrogate agreement.
- Facing: taken after the pedal's rotation for every footprint kind (signal options, fixed boxes, DC options of pedals and
  on-board supply ports); a footprint without facing never passes.
- `reaches_out` zones: cannot open cells in front of the lowest pedals; no needless grid growth; surrogate mirrors it.
- Exact-number test updates: justified by the offset / rule, not hiding a regression.
- Dead code, stale docstrings, comment style; CLAUDE.md terse and accurate.

## Then
Fix clear findings (tests where behaviour was wrong), regenerate with the build, all tests green (normal + slow gig), build
exit 0, nothing uncommitted. Commit on the branch. Then `git checkout main && git merge --no-ff feat/dc-under-signal -m "Merge
feat/dc-under-signal: a right-angle DC plug may pass under one same-facing signal plug; DC exit offset 8.4; plugs past the board
edge get a zone"` (with the trailer), rebuild (no changes expected; if generated files change, regenerate and commit), run the
tests once more on main. A finding that needs an owner decision: do NOT merge; report it.

## Report
Findings (file:line, severity, fixed or not), test counts, merge commit hash (or why not merged), open owner questions.
