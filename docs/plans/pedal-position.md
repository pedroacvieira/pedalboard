# Plan: `feat/pedal-position`: footswitch data, a pedal editor, and layout proposals

Status: plan (2026-10-22), written by a planning agent from `docs/handovers/pedal-position.md`; open questions for
the owner at the end. Branch `feat/pedal-position` from `main` (after the cable-routing merge).

## 0. What the plan builds on
- **Layout model.** `design.parse_design` gives items with `left_mm`, `top_mm`, `w_mm`, `h_mm`, `rot`; left/top
  describe the *unrotated* box and rotation is about its centre. Moving = `left_mm = cx - w/2`, `top_mm = cy - h/2`;
  rotating = changing `rot`. In the save file rotation is only a `rotate-N` class on the item div, so an in-place
  canvas rewrite is simple and safe.
- **guitar-gig today.** Board footprint (16, 22)-(625, 354) mm, 17 chain pedals and 2 Ojai R30s (under the board,
  not obstacles). Rotated: Polytune, Phase 95, Reticon at 270, Ratsbane at 90. Findings in `docs/TODO.md`:
  `monk.out` / `monk.power` blocked by the Belle Epoch, `red_muck.power` by the Analog Chorus.
- **Reusable pure pieces.** `design.jack_point/jack_facing/footprint/overlap/plug_geometry`,
  `routing.end_options/blocked_parts`, `routing.build_grid/route_all`. A full build of guitar-gig takes ~0.2-0.45 s:
  the router can score a handful of finalists, not run inside the search loop.
- **Problems found along the way.**
  1. `jacks.check` reads `playground_design.json` from disk (`ctx["dir"]`): a candidate layout cannot be scored
     without writing a file. Needs an items injection point (Phase 0).
  2. `jack_setter.py` uses `numpy` (line ~123), against the "stdlib + Pillow" rule. Replace with Pillow (Phase 2).
  3. `jacks.read_file` keeps the stored `_doc`, so changing `jacks.DOC` does not update `catalog/jacks.json`. The
     rename needs a one-time `_doc`-only change (positions untouched), or `save_jacks` always writes the current DOC.

## 1. Footswitch data model
**New file `catalog/footswitches.json`**, separate from `jacks.json` (jack positions are never rewritten), written
only by the editor, same diff-friendly format (one footswitch per line, ids sorted).

```json
{
  "_doc": "Footswitch positions per pedal catalog id. Written ONLY by scripts/pedal_editor.py. x,y = fractions (0..1) of the Pedal Playground image, origin top-left, UNROTATED pedal, at the CENTRE of the switch cap. [] = checked: the pedal has no footswitch. Missing id = unknown.",
  "footswitches": {
    "beano":   [{"id": "bypass", "label": "Bypass", "x": 0.5, "y": 0.79}],
    "protein": [{"id": "left", "label": "Bypass", "x": 0.27, "y": 0.8}, {"id": "right", "label": "Boost", "x": 0.73, "y": 0.8}],
    "some_always_on_pedal": []
  }
}
```
- Fields: `id` (unique per pedal, slug), `label`, `x`, `y` (4 decimals). Optional, documentation only in v1:
  `diameter_mm` (null if unknown), `kind` (`bypass|tap|preset|other`). No invented specs.
- `[]` = verified "no footswitch" and must be kept (unlike `jacks.save_jacks`, which deletes on `[]`); missing id =
  unknown, reported like missing jacks. Supplies have no footswitches (a non-pedal id is a validation error).
- Code: new `scripts/footswitches.py` mirroring `jacks.py` (`read_file`, `dumps`, `normalize`,
  `save_footswitches`, `usable`, `validate_file`, `check`, `COMMAND = "uv run scripts/pedal_editor.py"`). Optionally
  factor the shared line-per-item `dumps` into one helper.

**Footswitch clearance rule** (checked by `build.py` on the owner's layout, independent of the optimizer):
- Canvas position via `design.jack_point(item, fx, fy)` (handles rotation).
- Every pair of footswitches on **different** pedals: `d = hypot(dx, dy)`; below `min_distance_mm` -> finding
  `footswitch: beano.bypass and mini_ego.bypass are 52.3 mm apart (min 60)`. Same-pedal pairs are not checked.
- Project block `"footswitches": {"min_distance_mm": 60}`; flags `validation.require_footswitches` (missing data ->
  error) and `validation.strict_footswitches` (distance -> error); both default false (warnings).
- **Default 60 mm is an estimate**: minis butted together ~40-48 mm apart, standard (1590B) enclosures ~60-70 mm
  (Mini Ego / Beano today ~65 mm), front vs back row usually > 100 mm. Phase 1 prints the closest pairs of the current
  layout so the owner can calibrate.
- ctx: `footswitch_pairs` (sorted), `footswitch_fixes`, `footswitch_setup`. README "Footswitches" section (data
  status, commands for missing data, the 8 closest pairs, too-close marked). `cables.svg`: dots plus a red line
  between too-close pairs.

## 2. Pedal editor (rename and extend `jack_setter.py`)
- `git mv scripts/jack_setter.py scripts/pedal_editor.py`; update `jacks.COMMAND`, `jacks.DOC`, the `_doc` line of
  `catalog/jacks.json` (only that line), `build.py` text and generated READMEs, tests, `CLAUDE.md`, `docs/TODO.md`.
- No compatibility shim recommended (single user); optional 5-line shim if the owner wants one.
- UI: "Jacks / Footswitches" mode (keys J / F, `--footswitches` opens in that mode); click adds an item of the
  current mode; drag, arrow nudge, Delete, Ctrl+S for both. Footswitch marker = filled circle + crosshair; when
  selected, a dashed preview circle of radius `min_distance/2`. Other mode's markers dimmed. Panel: Label, x mm,
  y mm, optional Kind. Checkbox "This pedal has no footswitch" saves `[]`. Warning if a footswitch centre is not on
  the pedal body (alpha > 128). Replace numpy with Pillow. Save writes each file only if dirty. Supplies: footswitch
  mode disabled.
- CLI: `pedal_editor.py <id> [--footswitches] [--image FILE] [--refresh]`; `--list` shows jack and footswitch counts
  (`?` unknown, `0` verified none); `--list-missing [project ...] [--only jacks|footswitches]`.
- Testability: move problem checks and new-id logic to module-level pure functions.

## 3. Objective (scoring a layout)
State: centre `(cx, cy)` in mm and `rot` per chain pedal. Fixed: board, supplies (under the board; only give power
port positions), pinned pedals, non-chain items. Chain order and power wiring are inputs, not optimized.

**Hard constraints** (rejected, never scored): inside the board shrunk by `layout.board_margin_mm` (default 0); no
overlap beyond `design.TOL_MM` and gap >= `layout.min_gap_mm` (default 0); pins fixed; rotation within the allowed
set (default: current rotation only; 180 never by default).

**Soft costs** (mm, weighted sum):

| Term | Surrogate in the search | Default weight | Why |
|---|---|---|---|
| clearance | sum of intrusion depth into every used plug part (signal ends best side, power plugs best side, fixed boxes for extra jacks), plug rects grown by `clearance_margin_mm` (2) during search, + 100 per violation | 50 / mm | must dominate; margin because plug sizes are estimates |
| footswitch | sum of max(0, min - d) over pairs on different pedals, + 100 per pair | 20 / mm | ergonomics |
| signal | per hop `measure_a + measure_b + Manhattan(exit_a, exit_b)`, best side combination | 1 | cable to buy |
| power | Manhattan between half-depth measure points per daisy-chain hop incl. supply port (= `jacks.check` min_mm) | 1 | cable to buy |
| io | first pedal input to the input board edge + last pedal output to the output edge (`layout.io`) | 1 | proxy for the unmodelled instrument cables |
| move | sum of centre displacement from the owner's layout | 0.2 | move as little as possible |
| rotate | number of rotation changes | 40 | disruptive |
| routing_area | plug exit outside the routing area | 200 each | mirrors the router's "outside" status |

**Acceptance tiers** (final choice and README, lexicographic): 1) hard constraints OK; 2) blocked plugs (count,
then mm); 3) unroutable / squeezed cables (router); 4) footswitch pairs under the minimum; 5) weighted rest. A
proposal is written only if it is not worse than the owner's layout on tiers 2-4, else "no better layout found".

**Final scoring** with the real pipeline (`build.validate` with injected items): routed `min_mm`; penalties
squeezed 10 / mm, overflow 50 / cable, unroutable 1000.

Configuration (optional blocks, also in the `new_project.py` scaffold):
```json
"footswitches": { "min_distance_mm": 60 },
"layout": {
  "pins": [],
  "rotations": { "default": "current", "polytune_3": [90, 270] },
  "board_margin_mm": 0, "min_gap_mm": 0, "clearance_margin_mm": 2,
  "io": { "input_edge": "right", "output_edge": "left" },
  "weights": { "clearance": 50, "footswitch": 20, "signal": 1, "power": 1, "io": 1, "move": 0.2, "rotate": 40 },
  "search": { "mode": "polish", "iterations": 40000, "restarts": 4, "seed": 1, "time_limit_s": 60, "finalists": 5 }
}
```

## 4. Search
- Modules: `scripts/layout.py` (pure: model, feasibility, surrogate score, moves, annealer) and
  `scripts/propose_layout.py` (CLI, finalist check with the real pipeline, outputs).
- Precompute per pedal and allowed rotation, relative to its centre: half-sizes, jack points/facings, plug option
  rects for both exit sides (signal and power), measure and exit points, footswitch points. A move translates cached
  rects; one full score ~1 ms (17 pedals, ~60 plug options). Start with full re-scoring; add incremental deltas only
  if measured necessary (with equivalence tests).
- Simulated annealing from the owner's layout, then greedy polish. Moves: shift (Gaussian, sigma 25 -> 1 mm),
  slide (to contact), repair (move along the violating axis by the intrusion + margin), rotate (allowed set), swap
  (explore only). Infeasible candidates rejected; Metropolis acceptance, geometric cooling.
- Modes: `polish` (default; shift/slide/repair/rotate, sigma 8 -> 0.5 mm) fixes today's findings with minimal
  changes; `explore` adds swaps, sigma from 60 mm, move weight x 0.25.
- Restarts with seeds `seed, seed+1, ...`; keep the best distinct finalists (centres differ > 2 mm); per-pedal
  +-1 mm greedy polish; snap to whole Pedal Playground px (0.56 mm) and re-score.
- Deterministic: `random.Random(seed)`, budget = iteration count (`time_limit_s` only a safety cap). Targets on
  guitar-gig: polish < 10 s, explore < 60 s; finalists 5 x ~0.3 s with the router.

## 5. Outputs (never writes `playground_design.json`)
- `projects/<name>/layout-proposal.json`: Pedal Playground "Load from File" layout made by editing the owner's canvas
  in place (same ids, board, supplies, artwork; only left/top px and the `rotate-N` class of moved pedals change).
  Helpers `design.move(item, cx, cy, rot)` and `design.write_canvas(canvas_html, items)`. Owner workflow: load,
  tweak, save, replace `playground_design.json`, build.
- `projects/<name>/layout-proposal.svg`: owner footprints dashed grey, proposal filled, moved pedals highlighted,
  arrows old -> new with distance labels, plug heads, routed cables, footswitch dots and too-close lines. Reuse the
  `routing.svg` drawing code (factor out helpers).
- README section "Layout proposal" rendered by `build.py` (generated files stay owned by the build): before/after
  table (blocked plugs, footswitch pairs under the minimum + closest distance, routed signal total, power estimate
  total, io distance, unroutable/squeezed, weighted total), moved-pedals table (dx, dy, distance, rotation), SVG link,
  the producing command (from `layout-proposal.meta.json`), and a "stale: rerun" note when the proposal no longer
  matches the chain.
- CLI: `uv run scripts/propose_layout.py guitar-gig [--mode polish|explore] [--iterations N] [--restarts R]
  [--seed S] [--pin id ...] [--score] [--dry-run]`. `--score` prints the term breakdown of the current layout
  (weight calibration). Projects without a design file exit with a clear message.

## 6. Phases (small, reviewable; tests in each)
0. **Refactors, no behaviour change**: `jacks.check` layout part split out (`jacks.layout_from_items`),
   `build.validate(..., items=None)`, `design.move`, `design.write_canvas`. Tests: file vs injected items give an
   identical ctx; canvas round-trip; moving one item changes only its div; px rounding.
1. **Footswitch data + rule in the build**: `catalog/footswitches.json` (empty map), `scripts/footswitches.py`,
   build call, README section, SVG dots, scaffold, flags. Tests: file layer, hand-computed distances (incl. rot 90),
   same-pedal ignored, `[]` not missing, warnings vs strict errors, real file valid.
2. **Pedal editor**: rename, references, `_doc` line, footswitch mode, "no footswitch", Pillow instead of numpy,
   CLI flags. Tests: pure helpers, `--list-missing` output, `jacks.json` positions unchanged. Manual check in the GUI.
   **Owner task after merge:** place the footswitches of the 17 gig pedals, then calibrate `min_distance_mm`.
3. **Surrogate score (`layout.py`)** + `--score`. Tests: hand-made boards (clearance depth = route_project's
   violation depth; signal surrogate ~ routed min within a cell; power = jacks.check min_mm; footswitch hinge;
   feasibility); consistency on the real gig layout (surrogate violations = the build's).
4. **Search and outputs (`propose_layout.py`)**. Tests on synthetic boards: blocked plug separated, pins respected,
   always feasible over 20 seeds, explore shortens a wrong order, footswitch pair pushed apart, deterministic output,
   "no better layout" gating, snapping safe. Slow smoke test on guitar-gig polish: today's findings gone, <= 3 moved.
5. **README integration and docs**: "Layout proposal" section, `CLAUDE.md`, `docs/TODO.md`.

Phases 1-2 give value (footswitch check on the real layout) before any optimizer; phase 3 alone is useful as
`--score`. Each phase one or two commits; merge after a code review.

## 7. Risks
- Plug dimensions mostly estimates: `clearance_margin_mm`, README states assumptions; owner measurements stay a
  priority.
- Surrogate vs router disagreement: several finalists checked with the router, penalties for router statuses.
- Rows / aesthetics not modelled: polish + move weight keep the owner's structure; explore is opt-in.
- Power wiring fixed while pedals move (joint optimization later).
- Pedal Playground compatibility of the edited canvas: only left/top/class change; owner loads it once to accept.

## Open questions for the owner
1. Footswitch minimum distance: 60 mm centre to centre between switches of different pedals? Different limits
   side-to-side vs front-to-back? (Confirm after the closest-pairs table.)
2. What counts as a footswitch: tap tempo and preset switches like bypass? Soft-touch / small toggles?
3. Editor name `scripts/pedal_editor.py`; shim for `jack_setter.py` or a clean break?
4. Board input/output edges: guitar input on the right, amp output on the left? Use the "io" proxy until the
   instrument cables are modelled?
5. Pins: which pedals must not move (tuner, most-stomped)? Can the Ojai R30s move?
6. Rotations: may the optimizer rotate pedals? Others allowed 90/270? (180 never.)
7. Weights: 1 mm of DC cable = 1 mm of patch cable? Is "50 mm of moving must save 10 mm of cable" right?
8. Mode: only polish for now, or also explore?
9. Board edges and gaps: overhang allowed? Minimum gap between pedals (velcro, fingers)?
10. Power wiring: later re-pick ports / daisy chains after moves, or keep hand-chosen?
11. Proposal files: `projects/<name>/layout-proposal.json` (+ .svg) OK? Keep several (polish and explore)?

## Owner decisions, 2026-10-22 (supersede the plan above where they conflict)
1. **Footswitch spacing**: no fixed number yet. The owner's current layout is thought through, so its smallest
   distance between switches of different pedals is the lower limit: `footswitches.min_distance_mm` defaults to
   `"auto"` = that minimum, computed from `playground_design.json` (the owner's file, never from a proposal) and
   shown in the README; a number overrides it. Revisit after the first results.
2. **All switches are recorded and considered** (bypass, tap, preset, toggles...). Each switch has
   `"bypass": true|false`; a pedal may have several bypass switches (the Protein is effectively two pedals in one
   case). Non-bypass switches still need clearance, but pairs involving bypass switches weigh more (e.g. weight
   factor 1.0 for bypass-bypass, lower for pairs with a non-bypass switch; configurable). The `kind` field from the
   plan becomes this `bypass` flag (an optional free-text `label` stays).
3. **Rename** `jack_setter.py` -> `pedal_editor.py`, clean break (no shim).
4. **Input/output**: the guitar input is wherever the first pedal's input is, the amp output wherever the last
   pedal's output is: no board-edge parameters. Signal flow is generally right to left on the owner's boards: add a
   soft "flow" preference (each next pedal not to the right of the previous one; small weight) instead of the `io`
   edge term.
5. **All pedals can move** (no default pins; `layout.pins` stays as an option). Allowed rotations 0, 90, 270 (=-90),
   never 180. Preference, soft only: 0 first; then angles already used on the board (if the board has 0 and 90, try
   90 before 270; if only 0, 0 before anything else); then a new angle. A rotation that gives better routing and
   footswitch clearance still wins. Implement as a rotation cost: 0 for 0 deg, small for an angle in use on the
   current candidate board, larger for a new one; the move generator tries used angles first.
6. Later the owner wants entirely new positions and rotations: plan the search for that now (see 8).
7. **Weights**: patch (signal) cables matter most; DC cables little (they run under the board and are easy): power
   weight well below signal (e.g. 0.1).
8. **Edit level**: only small fixes now, but plan for bigger changes with a `max_change` parameter giving levels,
   e.g. `"max_change": "fix"` (small moves near the start, no swaps; default), `"rearrange"` (larger moves, swaps,
   rotations), `"free"` (any position/rotation, start may be random); plus `max_move_mm` per pedal (null = no limit).
9. **Board edges and contact**: pedals never overhang the board (hard). Pedals may touch as long as plug clearance
   holds; two pedals with top-mounted jacks side by side are even preferred to touch (a small bonus for touching /
   compactness where clearance allows, or simply no minimum gap: `min_gap_mm` 0).
10. **Power wiring is recomputed per arrangement**: a power assignment step (outputs and daisy-chain order) under the
    power policy (digital alone, clocked vs gain/compressor, 18 V grouping, voltage range, mA limits, isolated
    needs, polarity) minimising DC length, run for each finalist (and cheaply in the search, or as a fixed-cost
    estimate there). The owner's hand wiring in `project.json` stays the source for the build; the proposal reports
    its own wiring.
11. **Several proposals**: the script keeps the best N (`--top N`, default 3), written as
    `projects/<name>/proposals/<n>.json` (+ `.svg`), ranked, each with its scores and wiring.

### Owner corrections, 2026-10-22 (later; override decision 4 and add accessibility)
4'. **Input/output edges after all**: push the **first pedal to the right of the board** (its input near the right
   edge: soft cost = distance from its input jack to the right board edge). The **last pedal can be anywhere near an
   edge** (soft cost = distance from its output jack to the nearest of the left, right and back edges), because an
   amp cable running over the board is a problem. Keep the small right-to-left flow preference.
12. **Accessibility (soft, per pedal)**: the board depth is split from front (nearest the player) to back; a pedal's
   position = its footswitches' (else its centre's) depth.
   - **Front preferred (slight)**: boosts and drives (tags `boost`, `overdrive`, `gain`, i.e. fuzz/distortion too),
     and every pedal with a **tap-tempo switch**. EQ/boost pedals such as the **Tumnus** (tags `eq`/`master`/`boost`)
     must be easily accessible: front, stronger.
   - **Back, always (strong)**: the **tuner** (tag `tuner`); other utility pedals may sit in the middle/back.
   - **Avoid the front**: modulation (tags `modulation`, `phaser`, `vibe`, `flanger`, `chorus`, `tremolo`), not
     stepped on often, **unless it has a tap-tempo switch**.
   - Configurable: `layout.access` = tag -> `front` | `back` | `avoid_front` with weights, plus per-pedal overrides.
   - Tap tempo comes from the footswitch data: each switch has an optional `"tap": true` (tap-tempo switch), set in the
     pedal editor next to the bypass flag.

### Owner correction, 2026-10-22: footswitch types
Each footswitch has a **`type`**: `bypass` | `tap` (tap tempo) | `boost` | `function` (a function switch: octave, hard
clipping, extra gain stage, multiple/single delay, ...). It replaces the `bypass` / `tap` booleans (the data file is
still empty, so no migration). Spacing priority by type, configurable (`footswitches.priority`), proposed defaults:
bypass 1.0, boost 0.8, tap 0.8, function 0.5; a pair weighs the max of its two switches' priorities (a pair with a
bypass switch counts fully). Accessibility: a pedal with a `tap` switch counts as tap tempo (front, modulation
exception); a `boost` switch also prefers the front. The pedal editor picks the type per switch (one choice of four,
default `bypass` for the first switch, `function` after that).
Clarification (owner): a `boost` **switch** only slightly prefers the front (weaker than a tap switch or a drive);
a **boost pedal** (tags `boost` / `eq` / `master`, e.g. the Tumnus) has the higher front priority.
