# To do

Hand-written backlog (not generated). Build-derived findings (warnings, data to verify, shopping list) live in the
generated `README.md`; this file holds the work and the questions for the owner. Tick items off or delete them when
done, and keep `CLAUDE.md` current when a decision changes.

## Branch `feat/pedal-position` (merged into main 2026-10-23)
- [ ] Plan: `docs/plans/pedal-position.md` (handover `docs/handovers/pedal-position.md`); answer its open questions.
- [x] Phases 0-2 (2026-10-22): layout injection, `design.move` / `write_canvas`, footswitch data + spacing check,
      `scripts/pedal_editor.py` (renamed from jack_setter, footswitch mode, Pillow instead of numpy).
- [ ] Manual GUI check of the pedal editor (footswitch mode, J/F, no-footswitch box, the four-way switch type) by the owner.
- [x] Phases 3-5 (2026-10-22): `scripts/layout.py` (surrogate score, search), `scripts/power.py` (policy checks
      shared with the build, power assignment per layout), `scripts/propose_layout.py`, README "Layout proposals".
- [ ] Owner: look at the guitar-gig proposals (`projects/guitar-gig/proposals/1.json`, Load from File) and say whether
      the moves are acceptable; tune `layout.weights` / `max_move_mm` if not.
- [ ] Owner: try `--max-change rearrange` (bigger moves, swaps, rotations) once and judge the result.
- [x] Proposals rerun with all gig footswitches (2026-10-23).
- [ ] Surrogate vs router: the signal estimate (octile + detour around crossed pedals) still misjudges some routes
      (finalists are checked with the router, so proposals are safe, but the search may miss better ones).
- [x] `feat/cable-routing` merged into `main` and pushed.
- [x] uv project (2026-10-23): `pyproject.toml`, `uv.lock`, `.venv`; all commands are `uv run ...`.
- [x] Code review of the branch (2026-10-23): 9 findings fixed (fair power comparison, first/last jack and power
      side in the surrogate, one power policy, stale detection by input hash, write_canvas patterns, faster
      --list-missing, small cleanups); gig proposals regenerated.
- [ ] Code-review leftover (not fixed, efficiency only): the router runs A* to pick exit sides and then again in
      `route_all`; reuse the first path if the build ever gets slow (today ~0.2 s).

## Owner input needed
- [x] Footswitches of every project pedal placed (2026-10-23).
- [x] Footswitch spacing is comfort, no minimum (owner, 2026-10-23): crowding term, maximised by the search.
- [ ] Owner: judge whether the proposals spread the switches enough; tune `footswitches.comfort_mm` (100) or
      `layout.weights.footswitch` (2) if not.
- [ ] Measure one **Ernie Ball flat patch plug**: depth from the jack face (catalog: 6.4 mm, maker) and the length
      from the jack axis to where the ribbon leaves (catalog: 19 mm, estimate). Update
      `catalog/cables.json` `ernie_ball_flat_patch_ra` and its `verified` list.
- [ ] Measure one **Ojai DC plug** (depth from the jack face, width, height) and its cable thickness. The current
      `dc_ra_2_1_low_profile` (RockBoard 20 x 11 x 10.5 mm, mapped by interpretation, ~11 mm deep) is deeper than the
      Ernie Ball plug, against the owner's expectation; RockBoard's own page also gives 5/16 in height.
- [ ] Confirm the power-jack fallback box `jacks.power_clearance` (default 5.5 x 5.5 mm, estimate).
- [ ] Power plug side: when neither side is blocked the tool reports "left". Does the side matter?
- [ ] Polarity: every pedal and supply is recorded center-negative (owner); add the real value when a
      center-positive pedal arrives.

## Gig board layout
- [ ] Both findings below are fixed by the fix-level proposals (`projects/guitar-gig/README.md`, Layout proposals).
- [ ] Monk / Belle Epoch are too close: `monk.out` (1.0 mm) and `monk.power` (5.1 mm) plug heads are blocked by the
      Belle Epoch. Move one apart in Pedal Playground and re-save `projects/guitar-gig/playground_design.json`
      (or confirm with measurements that the plugs fit).
- [ ] `red_muck.power` DC head blocked 3.0 mm by the MXR Analog Chorus.

## Next features (owner, 2026-10-23; one branch each, numbered as the owner listed them)
Each starts with a short plan in `docs/plans/<branch>.md` + owner decisions, then handovers, as feat/pedal-position.
Suggested order: 1 routing-view -> 3 supply-placement -> 2 power-routing -> 6 footswitch-toppers ->
5 pedal-preferences -> 4 web-ui.

### 1. `feat/routing-view`: a clearer signal routing picture (routing.svg; `cables.svg` today)
Goal: a picture the owner can wire the board from. Today: grid staircase paths, pedal boxes, S# labels.
- Owner (2026-10-23): the worst parts today are cables drawn on the same position where they could run in parallel,
  and hard angles everywhere: a cable should be a straight line between two necessary corners.
- [ ] Paths: reduce each routed path to its necessary corners (any-angle straight segments between them where the
      line stays clear of the grown pedals: line-of-sight smoothing / string pulling); lengths then follow the
      smoothed path (still no slack), tests updated with hand-computed cases.
- [ ] Parallel lanes: cables sharing a corridor get side-by-side lanes one cable width apart (ordered so they do
      not cross inside the corridor), not drawn on top of each other.
- [ ] Pedals: name labels, the jacks drawn (in/out/power/extra with facing), plug heads on the chosen exit side.
- [ ] Cables: colour per hop with a legend (S#, from -> to, min length), squeezed / over-stacking / unroutable
      styled distinctly; optional pedal images under the outlines (images from `.cache/images`, never committed).
- [ ] Shared SVG helpers (board, pedals, jacks, legend) in one module, so power.svg (2) and the web views (4) reuse them.
- Acceptance: same corridors as before; paths straighter and never overlapping (lengths can only get shorter);
  README embeds it.

### 2. `feat/power-routing`: power cables routed and drawn (power.svg)
Goal: real DC cable paths and lengths instead of the right-angle estimate. Needs 3 for where cables cross the board.
- Owner (2026-10-23): power cables stay UNDER the board as much as possible and come up next to each pedal (through
  a hole or an allowed edge). If there is no easy way to cross the board, a cable comes up once and routes on top.
  Board edges are per project allowed / avoided / forbidden: front usually forbidden (often not even possible),
  sides avoided (preferred: holes, then the back). Daisy chains are either FORKED (several cables from one source,
  each its own cable) or SERIAL (one long cable through every pedal, counted as one cable).
- [ ] Project settings: `power_routing.edges` {front: forbidden, left: avoid, right: avoid, back: allowed} (cost per
      avoided crossing), daisy-chain style per output (`forked` | `serial`, from the supply data or the project).
- [ ] Model per power cable: supply port -> under-board leg -> crossing (hole / allowed edge from 3) -> on-board leg
      -> pedal DC jack. Serial chains: one cable that surfaces at each pedal and goes back under where a crossing
      is near, else stays on top; forked: each branch from the source separately.
- [ ] Route the on-board legs with the grid router (power cable width, own stacking limit with signal cables?); the
      under-board legs on a separate layer (board frame / rails as obstacles, else free Manhattan).
- [ ] `power.svg` (top view: on-board legs solid, under-board legs dashed, supplies and crossings drawn) + table:
      cable, from -> to, min length, crossing used; README section next to the signal routing.
- [ ] `power.assign` and the layout surrogate use the routed (or crossing-aware) length instead of Manhattan.
- Owner (2026-10-23): power and patch cables are independent (they do not count against each other); the
  stacking limit (`max_stack`) applies among power cables in the same place, as among patch cables.

### 3. `feat/supply-placement`: supplies on or under the board, board holes
Goal: per supply instance `placement` on_board | under (today one global `jacks.supplies_layer`), and the board's
crossings (holes, slots, rail gaps, open edges) where power cables go from under to over the board.
- [ ] Data: `catalog/boards.json` (new): per board model the frame, rails/slots and access holes in mm (or image
      fractions, placed with a board mode in the pedal editor); research Fender Professional Medium and RockBoard
      Duo 2.1 (maker drawings first; "unverified" otherwise).
- [ ] Project: `power.supplies[].placement` + position under the board (x, y, rotation) for under-board supplies;
      on-board supplies are layout items (obstacles, port clearance, movable by the layout search).
- [ ] Build: on-board supply ports get the DC plug clearance; under-board supply positions must fit the board's
      underside (height/space data if known); each power cable needs a reachable crossing (finding if none).
- [ ] Board edges as crossings with the per-project allowed / avoided / forbidden setting of 2 (front forbidden by
      default); holes preferred.
- [ ] Layout search: optional term for DC length through crossings; optionally move on-board supplies.
- Acceptance: today's projects (all supplies under) give identical results with placement defaulting to under.

### 4. `feat/web-ui`: one local web app with tabs (last: wraps the stable features)
Goal: replace the Tkinter editor and the README-only views with a local browser app.
- Owner (2026-10-23): new dependencies are fine when there is a reason for each; Python ones via uv (`uv add`),
  anything else (npm, system packages) only after asking the owner.
- [ ] Stack (decide in the plan): a Python web framework via uv (e.g. FastAPI/Starlette or Flask) serving a JSON
      API over the existing functions (`build.validate`, `jacks.save_*`, `footswitches.save_footswitches`,
      `propose_layout`), front end plain JS/SVG first; a JS toolchain (npm) only with the owner's OK. Local only.
- [ ] Tabs: Board (layout, findings), Pedal editor (jacks + footswitches + toppers on the image: port of
      `pedal_editor.py`, same pure helpers), Signal routing (1), Power routing (2/3), Preferences (5), Proposals
      (compare, load into Pedal Playground).
- [ ] Writes only through the existing save functions (one-item-per-line JSON, same validation); the build stays the
      single source of findings; images still fetched server-side into `.cache/`.
- [ ] Keep the CLI working; retire the Tkinter editor once the web editor covers it.
- Open: drag pedals in the Board tab and save as a new layout file (never `playground_design.json` itself)?

### 5. `feat/pedal-preferences`: one preference profile per pedal in a project
Goal: every per-pedal wish in one place, editable with values, drop-downs and toggles (the tab comes with 4).
- [ ] Data: `projects/<name>/project.json` `pedals.<id>`: position (left/right/front/back/any + strength), pin,
      allowed rotations, order wishes (before/after X with priority -> expands into today's rules), power wishes
      (own output, preferred supply/port, voltage), footswitch topper (6), access override.
- [ ] Migrate today's scattered knobs into it (`layout.access.pedals`, `layout.pins`, `layout.rotations.<id>`,
      per-pedal rules, power output choice) with the old keys still read (or a one-off migration script).
- [ ] Build: validate the profile, README table "Preferences" (what each pedal asks for, met or not in the
      owner's layout and in each proposal); layout search and `power.assign` read it.
- [ ] Until 4: edit project.json by hand (documented schema); then the Preferences tab edits the same block.

### 6. `feat/footswitch-toppers`: toppers on footswitches
Goal: a topper (larger, higher cap) on a switch makes it easier to hit and its neighbour less likely to be hit too.
- Owner (2026-10-23): toppers are a finishing step AFTER the best layout is found; supply is unlimited, but a project
  may cap the total per board; the preference is always none or only a handful. So toppers are per project.
- [ ] Data: project `footswitches.toppers` ["<pedal>.<switch>", ...] (set by the owner in the pedal editor, later
      the web tab) and `footswitches.max_toppers` (optional cap per board).
- [ ] Spacing: a pair where one switch has a topper counts as less crowded (effective distance = d + bonus, or a
      crowding factor; owner picks the model); the README shows toppers in the footswitch table and the SVG.
- [ ] Suggestions (post-layout, never during the search): the fewest toppers that remove the most crowding, each
      on ONE switch of a crowded pair (a topper on a switch shared by several close pairs helps them all; then the
      higher priority type, then the one nearer the front), within `max_toppers`, stopping when the next topper
      gains little (threshold); listed in the README, not applied automatically.
- [ ] Layout search: ignores toppers entirely (the layout is optimised first, toppers finish it).

## Features
- [ ] Model the guitar -> board and board -> amp cables (`fender_pro_instrument_ra`, role instrument): needs guitar
      and amp positions (or board-edge exit points) in the project.
- [ ] Layouts for `guitar-practice` and `bass` (`playground_design.json`), so their cables and clearance are checked.
- [ ] Practice board: out of scope for now (owner, 2026-10-22); the third Ojai R30 is still to buy.

## Data
- [ ] Items in the generated README's "Data to verify" (power specs, Reticon, Protein, version assumptions).
