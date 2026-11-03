# Handover: review and merge `fix/cable-area`

Python 3.12, `uv run` only (`uv run pytest tests -q`, ~100 s; `PEDALBOARD_SLOW=1 uv run pytest tests -q -k gig`;
`uv run scripts/build.py`, exit 0 expected). Do not push. Another agent works in a separate git worktree on
`feat/power-plug-side` (branched from `fix/cable-area`): do not touch that worktree or branch.

## The change (one commit, 6c164c7, on top of main 7d98873)
Owner decision (2026-11-02): the usable board area (`projects/<name>/board.json` `bounds`, `layout["usable"]`) limits the
PEDALS only (their bodies), never the cables. Routing area = board footprint + `edge_margin_mm` at back and sides (nothing in
front unless `cables.route_in_front`), for the signal AND power grids; the under grid stays the whole board. Plugs of jacks
that overhang the usable area / board are opened as routing area via `routing.plug_zones` -> `build_grid(..., zones)` (only
the added cells beyond the board + margin are walls; without zones the grid must equal main's). The layout surrogate
(`layout.in_area`) counts an exit inside its own plug's footprint as inside only for such an overhanging jack.
Files: `scripts/routing.py`, `scripts/layout.py`, `scripts/build.py`, `scripts/svgdraw.py`, tests `tests/test_bounds.py`,
`tests/test_pedal_body.py`, CLAUDE.md, docs/TODO.md, generated READMEs / routing.svg.

## Review (`git diff main...fix/cable-area`)
Look for: any remaining place where `usable` / bounds still limit cables (grep `usable`, `bounds`, `area_rect` in routing.py,
layout.py, power.py, svgdraw.py, build.py); the signal and power grids treated alike; zones still working when bounds are
gone; surrogate and build agreeing; dead code or stale docstrings left from the removed logic; tests that lost coverage
(the diff deletes many test lines: is every deleted case either obsolete or still covered?); CLAUDE.md / TODO consistent
with the code; generated files regenerated (run the build, `git status` must stay clean).

## Then
- Small, clear findings: fix them on `fix/cable-area` (add tests where a behaviour was wrong), regenerate with the build,
  commit (message ends with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`).
- All tests (normal + `PEDALBOARD_SLOW=1 -k gig`) pass and the build exits 0 -> `git checkout main && git merge --no-ff
  fix/cable-area -m "Merge fix/cable-area: the bounds limit the pedals only, never the cables"` (same trailer), run the tests
  once more on main.
- A finding that needs an owner decision or a larger rework: do NOT merge; report it.

## Report
Findings (file:line, severity, fixed or not), test results, merge commit hash (or why not merged).
