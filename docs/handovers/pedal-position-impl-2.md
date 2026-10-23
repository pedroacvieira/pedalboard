# Handover: implement `feat/pedal-position`, part 2 (phases 3-5: score, search, proposals)

Branch `feat/pedal-position` (part 1 committed: 1b26276, a6c2056, 2fe2b4b). Read `CLAUDE.md`, then the plan
`docs/plans/pedal-position.md` INCLUDING the sections "Owner decisions, 2026-10-22" and "Owner corrections" at the
end (they override the plan body), and `docs/handovers/pedal-position-impl-1.md` "Current state" (what part 1 built:
items injection in `build.validate(..., items=)`, `design.move`, `design.write_canvas`, `scripts/footswitches.py`).

## Scope
- **Phase 3, `scripts/layout.py`** (pure): candidate model (centre + rot per chain pedal), precomputed per-rotation
  geometry, hard constraints (inside the board, never overhang; no overlap beyond `design.TOL_MM`; touching allowed;
  pins; rotations 0/90/270 only, never 180), the surrogate score with these terms (weights configurable in
  `project.json` `layout.weights`, defaults to propose and justify):
  - clearance (dominant; plug heads with a search margin), signal (patch cables, high priority),
    power (DC, low weight ~0.1), footswitch spacing (pairs below the limit; bypass pairs weigh more than pairs with a
    non-bypass switch; the limit is part 1's `min_distance_mm` incl. "auto"; no footswitch data -> term is 0, say so),
    first pedal's input to the RIGHT board edge, last pedal's output to the nearest of left/right/back edges,
    small right-to-left flow preference, accessibility (decision 12: front for boost/drive/gain/eq and tap-tempo
    pedals, Tumnus-like eq/boost stronger; tuner always back, strong; modulation avoid front unless tap; via
    `layout.access` per tag + per-pedal overrides; depth from footswitches, else centre), rotation preference
    (0 best, then angles already used on the board, then new ones; soft), move cost from the owner's layout,
    small touching/compactness bonus where clearance holds.
  - `uv run scripts/propose_layout.py <project> --score`: term breakdown of the owner's current layout.
- **Power re-assignment per arrangement** (decision 10): a pure function that assigns chain pedals to the project's
  supply outputs (ports, voltages, daisy-chain order) under the power policy already enforced by `build.validate`
  (digital alone, clocked vs gain/compressor, 18 V grouping, voltage range, mA limits, isolated needs, polarity),
  minimising DC length (half-depth measure points, as `jacks.check`). Reuse/extract the validation rules rather than
  duplicating them; the result must pass `build.validate`'s power checks (test that). Used for finalists (the search
  may use a cheap estimate). The owner's hand wiring in `project.json` stays what the build uses.
- **Phase 4, search + outputs** (`scripts/propose_layout.py`): simulated annealing + greedy polish as in the plan,
  `max_change` levels `fix` (default: small moves, no swaps) / `rearrange` (larger moves, swaps, rotations) / `free`
  (any position/rotation), `max_move_mm`, deterministic seed + iteration budget, finalists scored with the real
  pipeline (`build.validate(..., items=)` -> routed min lengths, router statuses), acceptance tiers (not worse than
  the owner's layout on blocked plugs / routing / footswitch pairs), `--top N` (default 3) proposals written to
  `projects/<name>/proposals/<n>.json` (Pedal Playground "Load from File", via `design.write_canvas`) + `<n>.svg`
  (before/after) + metadata (scores, moved pedals, the proposal's power wiring, command/seed). Never write
  `playground_design.json`.
- **Phase 5**: build renders a "Layout proposals" README section from `proposals/` (before/after scores, moved
  pedals, power wiring, stale detection); `CLAUDE.md`, `docs/TODO.md`.

## Constraints
- Approximation, not simulation (owner): keep models simple; mm everywhere; no images in the repo.
- Keep `uv run scripts/build.py` fast (rendering proposals must not run the search; budget +~0.5 s max) and green.
- Search targets on guitar-gig: `fix` < ~15 s, others < ~90 s. Mark long tests slow or keep budgets tiny in tests.
- Never change `catalog/jacks.json` / `catalog/footswitches.json` data or `playground_design.json`.
- Commit per phase on `feat/pedal-position` (messages end with
  `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`); do NOT push or merge.
- Add a "Current state" note at the end of this handover when done.

## Acceptance
- Tests pass (hand-computed scoring cases, feasibility, determinism, power assignment passes validation, gating).
- `uv run scripts/propose_layout.py guitar-gig` (fix level) writes up to 3 proposals; report for the best one:
  which pedals moved and by how much, whether the Monk/Belle Epoch and Red Muck power findings are gone, signal min
  length before/after, footswitch term (0 until data exists), runtime. Also run `--max-change rearrange` once and
  report the same (do not commit its proposal files unless they are the default run's).
- Report commits, test count, open questions and anything not verified.

## Current state (2026-10-22, end of part 2)
Phases 3-5 done on `feat/pedal-position` (not pushed, not merged), plus the owner's footswitch `type` correction:
- Footswitch types: `type` bypass|tap|boost|function replaces the bypass/tap flags (`footswitches.TYPES`,
  `priorities`/`pair_priority`, pedal editor radio buttons, README pairs table, cables.svg colours).
- Phase 3: `scripts/layout.py` (Model: per-rotation geometry, hard constraints, surrogate score with all terms of
  the handover; weights `layout.weights`), `scripts/power.py` (`output_findings` / `merge_18v_findings` used by
  `build.validate`; `assign` for a layout), `build.validate(..., project=)`.
- Phase 4: `layout.search` (annealing + polish, levels fix/rearrange/free, deterministic), `scripts/propose_layout.py`
  (`--score`, finalists with their own wiring checked by `build.validate`, gating, proposals/<n>.json + .svg +
  meta.json), `routing.svg(overlay=, legend=)`. Signal surrogate = octile + 0.6 x detour estimate (calibrated on
  guitar-gig: without it the router's detours made proposals longer than the owner's layout).
- Phase 5: README "Layout proposals" (`build.proposals_section`, stale detection by design-file sha1 + chain),
  root README command, scaffold `layout` block, `CLAUDE.md`, `docs/TODO.md`.
- guitar-gig, fix level (seed 1, ~14 s): best proposal moves 5 pedals (Monk 40 mm back, Red Muck 10, Retrovibe 7,
  Belle Epoch 4, Analog Chorus 2), 0 blocked plugs (was 3), routed signal 2576 -> 2453 mm, DC estimate 2710 ->
  2467 mm with its own wiring. Rearrange (~20 s, not committed): signal 2140 mm, 13 pedals moved, 3 rotations.
- Open: footswitch term is 0 until data exists; the surrogate still misjudges some routes (finalists are checked
  with the router); power `overrides.P#.exit_b` are ignored by the search (P numbering changes with the wiring).
