# Handover: review `feat/power-plug-side`, fix the findings, commit

Worktree `/home/pvieira/projects/pedalboard/.claude/worktrees/agent-ada2ea11d0ee3779b`, branch `feat/power-plug-side`
(feature commit + a merge of main 5f79dc6; clean). Work only there. Python 3.12, `uv run` only (`uv run pytest tests -q`,
~150 s; `PEDALBOARD_SLOW=1 uv run pytest tests -q -k gig`, ~55 s; `uv run scripts/build.py`, exit 0). Do not push, do not
merge into main.

## The feature (spec: `docs/plans/power-plug-side.md`, short, read it)
Owner decision: when a DC plug's sides tie on fit (feasible, down, blocked parts + plug collisions), take the side with the
shorter power cable. Owner defaults: `SWITCH_MM` 5, both stages (estimate + routed A* refinement), length beats overlap.
Implementer's own decision (accepted for now): length only separates sides of the SAME plug type; the type still follows
`power_types` list order (`rank_pool` subtracts the least estimate per type and fit).
Implementation: `scripts/routing.py` (`TIE_MM`, `SWITCH_MM`, `plug_rank`, `rank_pool`, `best_option`, `dc_estimator`,
`power_plug_choices` / `decide_group`, `choose_dc`, `route_power_choosing` split into `retry_unroutable` + `refine_dc_sides`,
`route_power` now returns `(grid, layers)`), `scripts/layout.py` (surrogate DC option by clearance, then estimated legs;
power term from the chosen option's exit + `measure_mm`; `_resolve`), `scripts/build.py` (log line `power: N DC plugs took
the shorter side (saved X mm)`), tests `tests/test_power_plug_side.py` (new), `test_daisy_chains.py`, `test_power_types.py`,
`test_layout.py`; CLAUDE.md, docs/TODO.md. Diff: `git diff 7d98873 HEAD -- scripts tests CLAUDE.md docs` minus main's part
(or `git show HEAD^1` for the feature commit alone).

## Review focus
- Correctness: can length ever beat a fit criterion (down, blocked, collisions, feasibility)? Does an `exit_b` override
  always hold? Serial cables: one type per cable kept; a middle plug's change counted on both legs?
- `refine_dc_sides`: accepts only if no leg unroutable and the total did not grow; switches only by > `SWITCH_MM`; considers
  collisions with the chosen signal plugs (no new collision introduced by a switch?). Is the extra "old sides" routing
  (only for the log's "saved" figure) worth its cost, or can the saving be computed without it? Build time before/after.
- Reported side-effects: danelectro collision moves from .out/power to .in/power (same count); live gig retrovibe +58 mm.
  Are these legitimate consequences of the rule or a bug (e.g. a tie decided by length where collisions should differ)?
- Two loosened surrogate-vs-build tests in `tests/test_layout.py` (exits differing up to 6/49, collision pairs >= 4/7): is
  the loosening necessary, or can the surrogate mirror the build better cheaply? Do not loosen further.
- Dead code, duplicated logic, stale docstrings, comment style matching the surrounding code; CLAUDE.md accurate and terse.

## Then
Fix clear findings (tests where behaviour was wrong), rebuild, all tests green (normal + slow gig), build exit 0 and no
uncommitted generated changes. Commit on `feat/power-plug-side` (message ends with
`Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`). Anything needing an owner decision: leave it, report it.

## Report
Findings (file:line, severity, fixed or not), test counts, build time before/after, commit hash, open owner questions.
