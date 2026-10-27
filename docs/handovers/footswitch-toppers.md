# Handover: feat/footswitch-toppers: toppers on footswitches (spacing model + suggestions)

You work in your own git worktree on a new branch from `main`. Commit your work on that branch when done (message
ending with "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"). Python 3.12, `uv run` only (never pip); tests
`uv run pytest tests -q` (~30 s); build `uv run scripts/build.py`. No new dependencies. Do not edit CLAUDE.md /
docs/TODO.md / plans (the reviewer does), `playground_design.json`, `board.json`, catalog data. If `.cache/` is missing
in your worktree, copy it from /home/pvieira/projects/pedalboard/.cache (read-only source).

## Goal
A topper (a larger, higher cap) on a footswitch makes it easier to hit and its neighbour less likely to be hit too.
Projects can list the toppers they have; the spacing check counts a pair with a topper as less crowded; after the
layout, the build SUGGESTS the few toppers that remove the most crowding.

## Owner decisions (copy)
- Toppers are a finishing step AFTER the best layout is found; supply is unlimited, but a project may cap the total per
  board; the preference is always none or only a handful. So toppers are per project.
- Layout search ignores toppers entirely (the layout is optimised first, toppers finish it).
- Suggestions: post-layout, never during the search; the fewest toppers that remove the most crowding, each on ONE
  switch of a crowded pair (a topper on a switch shared by several close pairs helps them all; then the higher
  priority type, then the one nearer the front), within `max_toppers`, stopping when the next topper gains little
  (threshold); listed in the README, not applied automatically.
- Defaults chosen for the owner to confirm (list them in your report): spacing model = effective distance:
  d_eff = d + `footswitches.topper_bonus_mm` (default 10 mm, unverified) per topper on the pair (both switches: 2x);
  crowding then uses d_eff in the existing formula. Suggestion threshold `footswitches.topper_min_gain` = 0.05 (a
  topper must remove at least 5 % of the board's current crowding). `footswitches.max_toppers` optional (no cap
  by default). Toppers are set by hand in project.json (`footswitches.toppers`); no editor UI in this branch (the
  pedal editor is per catalog pedal, toppers are per project; the web UI comes later).

## Context (read first)
- `scripts/footswitches.py`: `PRIORITY`, `COMFORT_MM`, `priorities(project)`, `spacing_settings(project)`,
  `crowding(distance_mm, priority, comfort_mm)` = priority x max(0, comfort - d)^2 / comfort, `pair_priority`,
  `points(placed, fs_data)`, `pairs(pts)`, `check(ctx, cat_pedals, fs_data)` (fills `footswitch_points`,
  `footswitch_pairs` with too_close etc., the crowding sum, warnings for `min_distance_mm`).
- `scripts/build.py` `footswitch_section` (README: crowding, closest pairs table); `scripts/svgdraw.py` `footswitches`
  (routing.svg: switch markers by type, too-close lines), key entries.
- `scripts/layout.py`: the surrogate's footswitch term (must NOT use toppers; keep it exactly as today).
- Switch ids: "<pedal id>.<switch id>" as in `footswitch_points` (check the existing key format and reuse it).

## Tasks
1. Settings + validation: `footswitches.toppers` (list of "<pedal>.<switch>" that exist in the project's chain pedals'
   footswitch data; unknown = error), `topper_bonus_mm` (>= 0), `max_toppers` (int >= 0 or absent; more toppers listed
   than the cap = warning), `topper_min_gain` (0..1).
2. Spacing in the build: pairs use d_eff with the project's toppers; README shows the crowding with toppers and, when
   toppers are set, also without them ("x without toppers"); the closest-pairs table marks toppered switches and shows
   d and d_eff; `min_distance_mm` checks use d_eff (say so in the README text).
3. Suggestions (`footswitches.suggest_toppers(points, pairs/settings, existing, max_toppers, min_gain)`, pure): greedy
   — at each step evaluate adding a topper on each switch that is in at least one crowded pair (d_eff < comfort), pick
   the largest crowding reduction; ties: the switch in more crowded pairs, then higher type priority, then nearer the
   front (larger y on the board = front); stop at the cap or when the best gain < min_gain x the crowding before
   suggesting (fixed at the start). Return the ordered list with the gain of each and the crowding after.
   README: "Suggested toppers" list (switch, pedal name, type, gain, crowding after) or "none needed".
4. SVG: toppers drawn on routing.svg (a ring around the switch marker), suggested ones in a distinct dashed ring; key
   entries.
5. Layout search: untouched (add a test that the surrogate score is identical with and without toppers set).
6. Tests (hand-computed): d_eff and crowding with 0/1/2 toppers; validation errors; suggestion greedy order on a small
   synthetic set (a switch shared by two close pairs is picked first; ties by priority then front); cap and threshold
   stop; README section content with toppers; svg rings; surrogate unchanged.

## Acceptance
- `uv run pytest tests -q` passes; `uv run scripts/build.py` runs; the gig README gains the suggestions (no toppers are
  set, so the crowding value is unchanged); report the gig's suggested toppers (with gains) and the defaults chosen.
- Report: branch name, commit, files changed, tests, anything the owner must decide.
