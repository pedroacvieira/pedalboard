# Handover: implement `feat/board-editor-pieces`

## Goal
Implement the feature planned in /home/pvieira/projects/pedalboard/docs/plans/board-editor-pieces.md (absolute path: the plan is not in
your worktree yet). Read only that plan's design, decisions, tests and implementation-step sections; follow its steps in
order. Owner (2026-11-13): use the plan's RECOMMENDED DEFAULT for every "Decision for the owner".

## Rules
- Work in your worktree on a new branch `feat/board-editor-pieces` (from the current HEAD). One commit per plan step; messages end with
  `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. Do NOT merge, push or touch `main`.
- Run everything with `uv run` (`uv sync` first if needed). Tests: `uv run pytest tests -q` (~4 min) must pass at the
  end; run the touched test files after each step. `uv run pb build` must end OK.
- Data you may not edit: `catalog/jacks.json`, `catalog/footswitches.json`, `projects/*/playground_design.json`.
  Do not run `fetch_playground.py`. Generated files (READMEs, .mmd, .svg) only via `uv run pb build`.
- Keep `CLAUDE.md` current (same terse style) for the structure / conventions you change.
- Another agent implements a different feature in parallel on another branch: keep your changes to what your plan needs.

## Deliverable
Branch with commits, full test result, the build result, every behaviour change on the live projects (lengths, warnings),
and anything left open.
