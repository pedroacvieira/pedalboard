# Pedalboard planner: briefing for Claude / agents

Read this first. It gives the basics so a new conversation or agent only needs a goal and an approach.
Task-specific handovers live in `docs/handovers/` (one file per delegated task; read the one you are given).
Open work and questions for the owner: `docs/TODO.md` (hand-written backlog; keep it current). Planned features,
with owner decisions and the suggested order, are in its "Next features" section (one `feat/<name>` branch each).

## What this repo is
A data-driven planner for the owner's three pedalboards (projects): `guitar-gig` (Fender Professional Medium,
2x Strymon Ojai R30), `guitar-practice` (Rockboard Duo 2.1, 1 Ojai R30 still to buy), `bass` (Rockboard Duo 2.1,
Harley Benton PowerPlant ISO-5 Pro). Python 3.12, stdlib + Pillow (+ tkinter for the jack app) today. New
dependencies are fine when there is a reason for each: Python ones via uv only, anything else (npm, system
packages) only after asking the owner.
Dependencies are managed with **uv** (`pyproject.toml`, `uv.lock`, project `.venv`): never `pip install` into the
system; add a dependency with `uv add <pkg>` (dev-only: `uv add --dev`), run everything with `uv run`. pytest runs
with `--disable-plugin-autoload` (pyproject) so plugins from a global PYTHONPATH (ROS) are not loaded.

## Layout
- `catalog/pedals.json`: every pedal (specs that belong to the pedal: tags, digital, clocked_noise, bypass,
  `power_consumption` {current_ma (worst case), min_voltage_v, max_voltage_v, needs_isolated_output}, prices,
  `playground_title` = key into Pedal Playground's database, intrinsic ordering rules in `dependencies`).
- `catalog/power_supplies.json`: supply models (ports, voltage options, mA limits, quantity owned).
- `catalog/cables.json`: cable types with a `role` (patch | instrument | power | reference), `diameter_mm` = width ON
  THE BOARD (routing width; a flat ribbon's narrow side), `jacket`, plug style right_angle|straight, head
  depth/width/thickness, right-angle exit offset / body reach / barrel width, sources, `verified` list, notes. Data.
- `catalog/jacks.json`: jack positions per catalog id. Written ONLY by `scripts/pedal_editor.py` (Tkinter).
  x,y = fractions (0..1) of the Pedal Playground image (unrotated), at the OUTER EDGE of the physical jack;
  facing = side the plug enters from (left/right/top/down); function input|output|power|power_out|other.
- `catalog/outlines.json`: each pedal's real top-view shape per Pedal Playground IMAGE file name: up to 16 rects in
  fractions of the unrotated image that cover every opaque pixel (alpha > 128; protruding jacks and rounded corners
  included). Derived data written ONLY by `scripts/outlines.py` from the cached images (no images in the repo);
  missing = the Pedal Playground box. Pedal Playground's Width/Height include the jacks (images are not squeezed).
- `catalog/boards.json`: board holes per Pedal Playground BOARD image name: `holes` = rects in fractions of the unrotated
  image that lie INSIDE the transparent, border-disconnected regions (conservative), `hole_transit_mm` (15, unverified),
  optional `edge_transit_mm`. Derived data written ONLY by `scripts/boards.py` (keeps non-hole keys on `--refresh`).
- `catalog/footswitches.json`: footswitches per pedal id, written ONLY by `scripts/pedal_editor.py`. x,y = fractions of
  the image (unrotated) at the CENTRE of the switch cap; `type` bypass|tap|boost|function (bypass = turns the pedal or
  one side of it on/off, tap = tap tempo, boost = boost/extra-gain stomp, function = any other switch), optional
  `diameter_mm`. Spacing priority per type `footswitches.priority` (bypass 1.0, boost 0.8, tap 0.8, function 0.5; a
  pair weighs the max of its two). `[]` = verified no footswitch (kept);
  missing id = unknown. Supplies have none. The owner places the data (every project pedal has it, 2026-10-23).
- `projects/<name>/project.json`: everything that can change per board: board, signal_chain, rules (with
  priorities), sections, power wiring (`power.supplies[].outputs[]`, daisy-chain order = list order, operating
  voltage = output voltage; `power.supplies[].placement` under|on_board, default `jacks.supplies_layer`), power_policy,
  `power_routing` (edges front/left/right/back forbidden|avoid|allowed, avoid_penalty, top_cost, max_stack,
  edge_transit_mm), `jacks` (clearance = audio box, power_clearance = smaller DC box used only
  without a power type, extra_used, supplies_layer), `cables` (`type` = default patch type, must have role
  patch; `power_type` = DC plug type, role power; routing parameters; `overrides.<S#>` with `type`, `exit_a`,
  `exit_b` = left|right|auto, tips; `overrides.<P#>.exit_b` fixes a power plug's side; `under_board`, `hole_transit_mm`,
  `hole_penalty`, `under_cost`, `max_stack_under` for the under-board layer), `footswitches.comfort_mm`
  (default 100), optional `footswitches.min_distance_mm` (mm, default none) and `footswitches.priority` (spacing
  weight per switch type), `layout` (optional: pins,
  rotations, max_change, max_move_mm, clearance_margin_mm, weights, access, search), `validation` flags
  (`require_footswitches`, `strict_footswitches` among them).
- `projects/<name>/board.json` (optional): the owner's hole corrections, `boxes` [{type hole|filled, x0..y1 fractions of the
  board image}] applied in order on the derived holes (filled closes, hole opens, later wins; `design.board_holes`).
  Written ONLY by `scripts/board_editor.py`. guitar-gig has one (13 full slots + the handle cutout, 2026-10-26).
- `projects/<name>/playground_design.json`: the owner's hand-made Pedal Playground layout (only guitar-gig so far).
  Generated per project: `README.md`, `signal-chain.mmd`, `power.mmd`, `routing.svg`, `power.svg` (power wiring only,
  supplies as translucent red silhouettes; `svgdraw.render_power`), `playground.json` (and the
  git-ignored `routing.local.svg` with pedal images, `build.py --images`);
  `proposals/` (`<n>.json` Pedal Playground layouts, `<n>.svg`, `meta.json`) by `scripts/propose_layout.py`.
- `scripts/`: `build.py` (validate all projects, write READMEs/diagrams; exit 1 on errors), `common.py` (paths,
  loaders, Pedal Playground DB cache, mm helpers, one-item-per-line JSON dump), `design.py` (parse Pedal Playground
  saves, jack geometry in mm, `move` / `write_canvas` to edit a layout in place),
  `jacks.py` (jack data, layout placement `layout_from_items`, fixed-box clearance, jack-to-jack length estimates),
  `footswitches.py` (footswitch data, spacing check), `outlines.py` (outline decomposition + CLI), `boards.py` (board
  holes from the board images + CLI, `load_edits`), `board_editor.py` (GUI: hole / filled boxes per project), `routing.py` (cable model, plug
  heads, side choice, grid router, smoothing, lanes, plug-head clearance), `svgdraw.py` (shared SVG drawing: board,
  pedals, jacks, plug heads, cables, legend; mm-sized), `power.py` (power policy checks shared with the build,
  `assign`: supply outputs + daisy chains for a layout), `layout.py` (pure: candidate model, hard constraints,
  surrogate score, annealing search), `propose_layout.py` (CLI: search, finalists checked with the build, proposals),
  `pedal_editor.py` (GUI: jacks and footswitches; pure helpers at module level), `to_playground.py` (write Pedal Playground layouts), `new_project.py` (scaffold).
- `tests/`: pytest (`uv run pytest tests`), ~380 tests, hand-computed geometry cases (`PEDALBOARD_SLOW=1` adds the
  full guitar-gig search).

## Commands
```
uv sync                                        # once: create .venv (Pillow, pytest)
uv run scripts/build.py [project...] [--images]   # validate + regenerate (fast, no network after the DB cache;
                                               # --images: also routing.local.svg with pedal images, git-ignored)
uv run pytest tests -q                     # all tests
uv run scripts/pedal_editor.py <catalog id> [--footswitches]   # place jacks / footswitches (needs a display; J/F keys)
uv run scripts/pedal_editor.py --list-missing [project...] [--only jacks|footswitches]   # what is still missing
uv run scripts/pedal_editor.py --list         # jack and footswitch counts per id (? unknown, 0 verified none)
uv run scripts/outlines.py [project...] [--image NAME] [--refresh]   # pedal outlines from the images
uv run scripts/boards.py [project...] [--image NAME] [--refresh]     # board holes from the board images
uv run scripts/board_editor.py <project> | --list   # correct a project's holes (drag a box, T hole/filled, E effective)
uv run scripts/to_playground.py [project...]  # Pedal Playground "Load from File" layouts
uv run scripts/propose_layout.py <project> [--max-change fix|rearrange|free] [--seed S] [--top N] [--pin ID ...]
                                               # layout proposals in projects/<name>/proposals/ (then build)
uv run scripts/propose_layout.py <project> --score   # surrogate term breakdown of the owner's layout
```

## Conventions and decisions (keep them)
- **Units: mm** for everything we compute, store and show. Pedal Playground files only hold inches (data-width/
  height) and px (left/top at data-scale px/in); convert at the boundary (`design.py`, `common.px_to_mm`).
- **No pedal images in the repo.** Images are fetched on demand into git-ignored `.cache/images/` (the site sends
  no CORS headers, so fetch server-side with urllib).
- Unknown values are `null`; `validation.no_unknown` makes them errors. Never invent specs or prices: research
  with sources (maker > retailer > forum) and say "unverified" when needed.
- Findings start as **warnings**; projects promote them with `validation.require_jacks`, `strict_clearance`,
  `strict_routing`. A required ordering rule breaks the build.
- Rule priorities: rules expand to pairwise "a before b" constraints; higher priority wins, overrides are listed.
- Power policy: digital pedals alone on an output; clocked (BBD/digital) pedals never share with gain/compressor;
  18V pedals share 18V outputs; operating voltage must be within the pedal's range.
  Polarity: `power_consumption.polarity` per pedal and `polarity` per supply (an output may override it); a
  mismatch warns (use a polarity-reversing cable), mixed polarities on one output are an error; power cables carry
  the pedal's polarity. Every current pedal is center-negative (owner, 2026-10-22).
- Supply placement per instance (`power.supplies[].placement`, default `jacks.supplies_layer`, all projects "under"):
  an under-board supply is not an obstacle on top (it is one on the under layer); an on-board supply is an obstacle by
  its outline, its used ports get the DC plug clearance (key "<instance>.<port>") and the layout search may move it.
- Board holes (plan `docs/plans/supply-placement.md`): effective holes = `catalog/boards.json` derived holes + the
  project's `board.json` edits, `layout["holes"]` (canvas mm). A cable changes layer only in a hole cell: centre inside
  a hole AND free on top (a pedal over part of a hole blocks that part) AND free under. No under-board fit check.
- Two-layer routing (`routing.py`, `Under`): the under layer = the board footprint (under-board supplies are its only
  obstacles), same cells as the top grid. Signal cables start/end on top and may go under through holes: per pass
  `hole_transit_mm` (length, board data 15, unverified) + `hole_penalty` 15 (search only), under mm cost 0.9; own
  stacking limit `max_stack_under`; per-layer smoothing; lanes on top only. `route_all` ends with clean-ups (re-route
  each cable with plain costs; `_back_on_top` undoes a cable sent under so another could take its corridor), so
  congestion history never leaves a needless detour. Gig: no signal cable goes under (2026-10-26).
- Power cables are routed (`routing.route_power`, own grids with the DC cable width, own stacking, not counted against
  signal cables): an under-board supply's hop starts under the board, daisy hops and on-board supply hops on top; under
  mm cost 1, top mm `power_routing.top_cost` 3, up through holes or allowed / avoided edges (`edge_transit_mm`: board
  data, else 2 x hole transit; avoid +100 search only; front forbidden by default). Min length = plug measures +
  polylines + transits. A long top run (> 150 mm) warns. `power.assign` and the layout surrogate use the
  nearest-usable-hole estimate (`power.hop_estimate`, a cost in mm-equivalents with top mm x top_cost).
- Plug heads (`design.plug_geometry`): head = depth x width rectangle centred on the jack, extending along the
  facing. Right-angle: cable leaves to the LEFT or RIGHT of the facing (seen from above looking out along the
  facing; facing right -> left is up), `exit_offset_mm` out (default depth/2), body to `body_reach_mm` from the jack
  axis (default width/2), then `cables.exit_run_mm` (default one diameter) straight: the router starts there.
  Straight: cable leaves along the facing at head depth, then the run. The router picks each end's side: feasible
  first (free path, else "squeezed" through gaps narrower than the cable, never through a pedal body), then fewest
  blocked plug parts, then shortest route; overrides fix a side. Clearance of signal jacks whose cable has a type
  = head + barrel + run on the chosen side (checked in `routing.route_project`, also without a pedalboard item).
  Every used jack is checked exactly once: `jacks.check(defer=True)` computes the fixed box for all of them into
  `ctx["fixed_box"]`, and `route_project` reports it (`jacks.report_fixed_box`) for the jacks it did not
  plug-check (extra and first-in / last-out jacks, unknown types, projects without `cables.type`). Warnings name
  the plug part an obstacle reaches deepest. The routing width is the widest signal cable type in use; each
  plug's straight run is one diameter of its own type.
- Cable types in use (owner, 2026-10-22): patch cables are **Ernie Ball flat ribbon** (`ernie_ball_flat_patch_ra`,
  3.5 mm on-board width, flat angled plug 6.4 deep x 12.7 wide, ribbon leaves 19 mm from the jack axis: mostly
  estimates, see the file); every patch plug is angled, no straight plugs (straight/Neutrik types are role
  `reference` only). Fender Professional (`fender_pro_instrument_ra`, role instrument) is only the guitar/amp cable,
  not modelled yet. Power jacks: `cables.power_type` = `dc_ra_2_1_low_profile` (RockBoard angled plug 20 x 11 x
  10.5 mm as reference): the head on the less blocked exit side (fewest blocked parts, then least overlap) plus a
  one-cable-width run is checked in `routing.power_plug_clearance`; without a power type `jacks.power_clearance`
  (default 5.5 / 5.5 mm) is used, never the audio box.
- Cable routing (`routing.py`): 2 mm grid; pedals grown by cable radius minus half a cell (any gap >= one cable
  diameter is a corridor); area = board + `edge_margin_mm` (default one diameter, 6 mm) at back and sides,
  nothing in front of the lowest pedals; at most `max_stack` (2) cables per cell; at most `max_over_plug` (2) other
  cables across one plug (head + barrel, signal and power plugs; its own cable excluded); signal cables only.
  The grid path is then smoothed (`routing.smooth`: string pulling to any-angle segments, never closer to a pedal
  than the grid path, no new plug crossings); `min_mm` and `path` follow it. Stacking is counted on the grid paths.
  `routing.lanes` (drawing only, `draw_path` / `stacked_with` / `stacked_runs`): cables sharing a corridor are drawn
  side by side one width apart (the lane set may shift off-centre), else marked stacked; lanes never change lengths.
- Cable lengths are a **minimum to buy**, not a product suggestion (owner uses DIY kits / any brand): measured from a
  point on each jack's axis half the clearance depth in front of the jack (half the plug head depth, else half the
  fixed box), along the plug's cable exit and the routed path; no slack, no rounding (`min_mm`). Power cables: routed (see above); `estimate_mm` keeps
  the old right-angle estimate for comparison. Goal is an approximation, not a real 3D simulation: all cables bend
  the same (no bend radius, flat or round), routes are not hand-tuned.
- Extra jacks (Exp, Tap, Thru, XLR...) are documentation only until listed in a project's `jacks.extra_used`.
- Generated files (READMEs, .mmd, .svg, playground.json) are never edited by hand; change the generator/data.
- Layout injection: `build.validate(..., items=...)` checks a parsed layout instead of `playground_design.json`
  (`ctx["layout_source"]` file|injected); `playground_design.json` is the owner's file and never written by tools.
- Footswitch spacing is comfort, not a hard rule (owner, 2026-10-23: no real minimum; maximise the distance against
  the other goals). Crowding of a pair of switches on DIFFERENT pedals = priority x max(0, comfort - d)^2 / comfort
  (`footswitches.crowding`, comfort `footswitches.comfort_mm` default 100 mm): the closest pairs count most. The
  build reports the sum (README: crowding, 8 closest pairs with types); the layout search minimises it (weight
  `layout.weights.footswitch` 2). An optional `footswitches.min_distance_mm` makes closer pairs warnings (strict:
  errors) and adds a steep penalty in the search; no default ("auto" was dropped). Missing data is one
  aggregated warning per project. `routing.svg` draws the switches (colour per type) and too-close lines.
- Layout proposals (`layout.py`, `propose_layout.py`; plan `docs/plans/pedal-position.md` + owner decisions): all
  chain pedals may move (`layout.pins` optional), rotations 0/90/270 (never 180), never overhang the board, no
  overlap beyond TOL (touching allowed). Surrogate score (weights `layout.weights`): clearance dominates (real
  penetration 50/mm, 2 mm margin 10/mm, 100 per blocked plug), signal 1/mm (exits octile + 0.6 x detour around
  crossed pedals), power 0.1/mm, footswitch crowding by type priority, first input to the right edge, last output
  to the nearest left/right/back edge, small right-to-left flow, accessibility (tuner back; boost/eq/master pedals
  front 0.3; drives and tap switches front 0.1; a boost switch front 0.05; modulation avoids the front unless tap),
  rotation preference (0, then angles in use), move cost (0.2/mm + 25 per moved pedal). The surrogate checks the
  same jacks as the build (first input / last output: fixed audio box; power plug side overrides). `max_change` fix
  (default: max 40 mm, no swaps/rotations) / rearrange / free. Finalists AND the owner's layout get their own power
  wiring (`power.assign`, same policy as the build via `power.output_findings`; `cables.overrides.<P#>` follow their
  pedal, `power.remap_overrides`) and are checked with `build.validate(items=, project=)`; a proposal must not be
  worse than the owner's layout on errors, blocked plugs, routing problems and footswitch pairs below a set minimum. Proposals never
  touch `playground_design.json` or the owner's power wiring in project.json; the README section is rendered from
  `proposals/meta.json`, stale when `common.proposal_inputs_sha1` changed (design file, project.json, cables, the
  project's catalog entries incl. jacks and footswitches) or the chain changed.
- Pictures (`svgdraw.render`): sized in mm (prints 1:1 from a browser); committed SVGs have outlines only, pedal
  images only in git-ignored `routing.local.svg` (data URIs from `.cache/images`, `common.fetch_image`).
- Pedal outlines (`design.outline_rects`, `layout["shapes"]` {item id: [rects]}): the router (grid, smoothing, lanes),
  plug clearance (`routing.blocked_parts`, `jacks.check` fixed box) and the layout surrogate's clearance use the
  outline; pedal-pedal overlap, layout feasibility, moves and swaps keep the Pedal Playground box (owner, 2026-10-23).
- `build.validate(..., route=False)` skips the cable router (data findings only; used by `--list-missing`).

## Working agreements with the owner
- Commit/push only when asked; feature work on `feat/<name>` branches, merged into `main` after a code review.
- Commit messages end with the Co-Authored-By line given by the harness.
- When delegating to an agent, write a handover (goal, context, constraints, files, acceptance, what not to
  touch) to `docs/handovers/<task>.md` and point the agent at that handover only. Keep its scope and inputs
  minimal: one well-bounded task, only the decisions, conventions and file/function names that task needs
  (copy the relevant lines in), no "read the whole plan / other handovers / all of CLAUDE.md" pointers.
- Delegated implementation agents (`general-purpose`) run on `model: sonnet`; use Opus only for planning, code
  review, or when the owner asks.
- Keep this file current when structure, conventions or decisions change.
