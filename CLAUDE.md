# Pedalboard planner: briefing for Claude / agents

Read this first. It gives the basics so a new conversation or agent only needs a goal and an approach.
Task-specific handovers live in `docs/handovers/` (one file per delegated task; read the one you are given).
Open work and questions for the owner: `docs/TODO.md` (hand-written backlog; keep it current). Planned features,
with owner decisions and the suggested order, are in its "Next features" section (one `feat/<name>` branch each).

## What this repo is
A data-driven planner for the owner's three pedalboards (projects): `guitar-gig` (Fender Professional Medium,
2x Strymon Ojai R30), `guitar-practice` (Rockboard Duo 2.1, 1 Ojai R30 still to buy), `bass` (D'Addario XPND 1 + extension, a composed
board; Harley Benton PowerPlant ISO-5 Pro; no tuner, owner 2026-11-09). Python 3.12, stdlib + Pillow (+ tkinter for the jack app) today. New
dependencies are fine when there is a reason for each: Python ones via uv only, anything else (npm, system
packages) only after asking the owner.
Dependencies are managed with **uv** (`pyproject.toml`, `uv.lock`, project `.venv`): never `pip install` into the
system; add a dependency with `uv add <pkg>` (dev-only: `uv add --dev`), run everything with `uv run`. pytest runs
with `--disable-plugin-autoload` (pyproject) so plugins from a global PYTHONPATH (ROS) are not loaded.

Focus (owner, 2026-10-29): be able to assemble the board and GUARANTEE that pedals, plugs and cables fit; model as many
physical aspects as possible. Every cable gets a PRECISE minimum required length (`min_mm`): the owner uses it to pick
a cable that is long enough (a longer DC cable gets folded and tied). Lengths are optimised so no huge cables are
needed, but the tool does not track or match the owner's own cables (no DC cable inventory, owner 2026-10-29).

## Layout
- `catalog/pedals.json`: every pedal (specs that belong to the pedal: tags, digital, clocked_noise, bypass,
  `bypass_info` {confidence maker|retailer|forum|owner, source, url, notes} sources `buffered_bypass` / `buffer_switchable` (a
  switchable pedal's `buffered_bypass` = the factory default unless the owner set it; gig pedals researched 2026-11-06,
  handover `docs/handovers/gig-buffers.md`),
  `power_consumption` {current_ma (worst case), min_voltage_v, max_voltage_v, needs_isolated_output}, prices,
  `playground_title` = key into Pedal Playground's database, intrinsic ordering rules in `dependencies`).
  `height_mm` (optional, null = not found; not required by `no_unknown`) = how tall the pedal stands; the footswitch is
  assumed to be its tallest point, so the switch top = `height_mm` (owner, 2026-11-05; for footswitch reach / toppers
  later). `height_info` {measure overall|unspecified|enclosure_plus_switch, confidence maker|retailer|forum, source, url,
  notes}; an enclosure-only figure gets + 15.2 mm (`switch_allowance_mm`: Carbon Copy 47.0 overall - Sun Face 31.8
  enclosure, owner rule 2026-11-05; `enclosure_mm` keeps the published figure). Researched 2026-11-05, handover
  `docs/handovers/pedal-heights.md`.
- `catalog/power_supplies.json`: supply models (ports, voltage options, mA limits, quantity owned).
- `catalog/cables.json`: cable types with a `role` (patch | instrument | power | expression | reference), `diameter_mm` = width ON
  THE BOARD (routing width; a flat ribbon's narrow side), `jacket`, plug style right_angle|straight, head
  depth/width/thickness, right-angle exit offset / body reach / barrel width, sources, `verified` list, notes. Data.
- `catalog/jacks.json`: jack positions per catalog id. Written ONLY by `scripts/pedal_editor.py` (Tkinter).
  x,y = fractions (0..1) of the Pedal Playground image (unrotated), at the OUTER EDGE of the physical jack;
  facing = side the plug enters from (left/right/top/down); function input|output|power|power_out|other.
- `catalog/outlines.json`: each pedal's real top-view shape per Pedal Playground IMAGE file name: up to 16 rects in
  fractions of the unrotated image that cover every opaque pixel (alpha > 128; protruding jacks and rounded corners
  included). Derived data written ONLY by `scripts/outlines.py` from the cached images (no images in the repo);
  missing = the Pedal Playground box. Pedal Playground's Width/Height include the jacks (images are not squeezed).
  Top-level `bodies` {image name: [x0, y0, x1, y1]} (same fractions) = the pedal's BODY (enclosure without jacks): the median
  first / last opaque x over the rows that have an opaque pixel and the median first / last opaque y over the columns that have
  one (`outlines.body_from_alpha`; jacks, screws, knobs are ignored; filled by `outlines.py` without `--refresh` for images
  that have none; `outlines.load_bodies`); missing = the box. The usable board area is tested against the body.
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
  `power_routing` (top_cost, max_stack, edge_transit_mm; the old `edges` / `avoid_penalty` keys are errors), `jacks` (clearance = audio box, power_clearance = smaller DC box used only
  without a power type, extra_used, supplies_layer), `cables` (`type` = default patch type, must have role
  patch; `power_type` = default DC plug type, role power; `power_types` = the DC plug types the router may pick (default
  [power_type]); `jack_height_mm` (12, unverified: jack axis above the deck, for down plugs); routing parameters;
  `overrides.<S#>` with `type`, `exit_a`, `exit_b` = left|right|down|auto, tips; `overrides.<P#>` (a power cable id, see "Cable ids") `.exit_b` fixes a power
  plug's exit, `type_a` / `type_b` its port / pedal plug type; an override key that is no cable id is a build error; `under_board`, `hole_transit_mm`,
  `hole_penalty`, `under_cost`, `max_stack_under` for the under-board layer; `route_in_front` default false = nothing in
  front of the lowest pedals, true = the routing area reaches the board front), `footswitches.comfort_mm`
  (default 100), optional `footswitches.min_distance_mm` (mm, default none) and `footswitches.priority` (spacing
  weight per switch type), `layout` (optional: pins,
  rotations, max_change, max_move_mm, clearance_margin_mm, weights, access, search), `validation` flags
  (`require_footswitches`, `strict_footswitches`, `strict_bounds` among them).
- `projects/<name>/board.json` (optional): the owner's hole corrections, `boxes` [{type hole|filled, x0..y1 fractions of the
  board image}] applied in order on the derived holes (filled closes, hole opens, later wins; `design.board_holes`),
  and edge crossings `{type edge, side left|right|back|front, from, to}` (fractions along that side of the unrotated
  image; `design.board_edges`, `layout["edge_segments"]`; the editor snaps a drawn line to the nearest side).
  Optional `bounds` {back, front, left, right} = four lines (fractions of the unrotated image, back / front from its top edge,
  left / right from its left edge, a missing side = the image edge; `boards.load_bounds`, editor mode B): the pedals' BODIES
  must stay inside (their jacks may overhang; `design.board_bounds` -> `layout["usable"]`, the board footprint without bounds; read by the build, the router, the
  layout search and the drawings; the bounds never limit the cables (routing area = board + margin), under-board supplies are never checked).
  Written ONLY by `scripts/board_editor.py`. guitar-gig has one (13 full slots + the handle cutout, 2026-10-26).
  Optional `pieces` {"<board image file name>": {"boxes": [...], "bounds": {...}}} = the same two keys for the OTHER pieces of a
  composed board (the top-level `boxes` / `bounds` stay the FIRST piece's; `boards.load_pieces`; an image that is no piece of the
  layout = a build warning). Hand-written: the board editor edits the first piece only (and keeps `pieces` when it saves).
- `projects/<name>/playground_design.json`: the owner's Pedal Playground layout (only guitar-gig so far), a v2 site
  document (schema 3: items with image, width / height / x / y in inches, rotation in degrees; `design.parse_doc`; legacy v1
  saves `{"canvas": html}` still parse). Written ONLY by `scripts/fetch_playground.py` from the project's public share link
  (`project.json` `playground.share`); the version it replaces goes to the git-ignored `projects/<name>/playground_history/`
  (`<savedAt>_<name>.json`; the owner iterates over many versions). Pedal Playground 2.0 (2026-11) has no file load or save:
  the old `to_playground.py` / `playground.json` are gone.
  Generated per project: `README.md`, `signal-chain.mmd`, `power.mmd`, `routing.svg`, `power.svg` (power wiring only,
  supplies as translucent red silhouettes; `svgdraw.render_power`) (and the
  git-ignored `routing.local.svg` with pedal images, `build.py --images`);
  `proposals/` (`<n>.json` = the owner's document with the moved pedals changed, `design.write_design`; `<n>.svg`,
  `meta.json`) by `scripts/propose_layout.py`.
- `scripts/`: `build.py` (validate all projects, write READMEs/diagrams; exit 1 on errors), `common.py` (paths,
  loaders, Pedal Playground DB cache, mm helpers, one-item-per-line JSON dump), `design.py` (parse Pedal Playground
  layouts: v2 documents `parse_doc` / legacy `parse_canvas`, jack geometry in mm, `move` / `write_design` to edit a layout),
  `jacks.py` (jack data, layout placement `layout_from_items`, fixed-box clearance, jack-to-jack length estimates),
  `footswitches.py` (footswitch data, spacing check), `outlines.py` (outline decomposition + CLI), `boards.py` (board
  holes from the board images + CLI, `load_edits`, `load_bounds`, `load_pieces`), `board_editor.py` (GUI: hole / filled boxes per project), `routing.py` (cable model, plug
  heads, side choice, grid router, smoothing, lanes, plug-head clearance), `svgdraw.py` (shared SVG drawing: board,
  pedals, jacks, plug heads, cables, legend; mm-sized), `power.py` (power policy checks shared with the build,
  `assign`: supply outputs + daisy chains for a layout), `layout.py` (pure: candidate model, hard constraints,
  surrogate score, annealing search), `propose_layout.py` (CLI: search, finalists checked with the build, proposals),
  `pedal_editor.py` (GUI: jacks and footswitches; pure helpers at module level), `fetch_playground.py` (the shared layout from
  Pedal Playground: the site's Supabase REST with the public key from its scripts, read-only), `new_project.py` (scaffold).
- `tests/`: pytest (`uv run pb test` = `uv run pytest tests -q`), ~780 tests, ~250 s, hand-computed geometry cases
  (`PEDALBOARD_SLOW=1` adds the full guitar-gig search). Tests that depend on the gig's layout, wiring or proposals use the
  FROZEN copy `tests/fixtures/guitar-gig/` (`conftest.gig_copy` / `GIG_FIXTURE`), never the live project (the owner fetches
  new layouts all the time); update the fixture only deliberately.
- `pb/__init__.py`: `uv run pb <command>` = one entry point for the scripts (`pb --help` lists them: build, fetch,
  propose, new, pedal-editor, board-editor, outlines, boards, test); it runs the script's `main()`, the scripts stay
  runnable as `uv run scripts/<name>.py`. pyproject `[project.scripts]` + `uv_build` (package `pb` only).

## Commands
`uv run pb <command> ...` runs the same scripts (`uv run pb --help`); the long forms:
```
uv sync                                        # once: create .venv (Pillow, pytest) and the `pb` command
uv run scripts/build.py [project...] [--images]   # validate + regenerate (fast, no network after the DB cache;
                                               # --images: also routing.local.svg with pedal images, git-ignored)
uv run pytest tests -q                     # all tests
uv run scripts/pedal_editor.py <catalog id> [--footswitches]   # place jacks / footswitches (needs a display; J/F keys)
uv run scripts/pedal_editor.py --list-missing [project...] [--only jacks|footswitches]   # what is still missing
uv run scripts/pedal_editor.py --list         # jack and footswitch counts per id (? unknown, 0 verified none)
uv run scripts/outlines.py [project...] [--image NAME] [--refresh]   # pedal outlines from the images
uv run scripts/boards.py [project...] [--image NAME] [--refresh]     # board holes from the board images
uv run scripts/board_editor.py <project> | --list   # holes and edge crossings (drag; T hole/filled/edge; E effective)
uv run scripts/fetch_playground.py <project> [--share LINK] [--dry-run]   # the shared layout -> playground_design.json
                                               # (--share: saved in project.json when it has none; new_project.py --share too)
uv run scripts/propose_layout.py <project> [--max-change fix|rearrange|free] [--seed S] [--top N] [--pin ID ...]
                                               # layout proposals in projects/<name>/proposals/ (then build)
uv run scripts/propose_layout.py <project> --score   # surrogate term breakdown of the owner's layout
```

## Conventions and decisions (keep them)
- **Units: mm** for everything we compute, store and show. Pedal Playground layouts hold inches (v2: width / height /
  x / y; legacy: data-width / height and px at data-scale px/in); convert at the boundary (`design.py`, `common.px_to_mm`).
- **No pedal images in the repo.** Images are fetched on demand into git-ignored `.cache/images/` (the site sends
  no CORS headers, so fetch server-side with urllib). Source (since 2026-10-29): `https://pedalplayground.com/catalog/catalog.json`
  (cached in `.cache/catalog.json`; `assets.<kind>[<image>].img` = a WebP, converted to PNG with Pillow, alpha kept);
  `common.fetch_image` / `database` reject anything that is not an image / JSON (the old URLs answer an HTML page).
  An existing legacy `.cache/pedals.json` / `pedalboards.json` is used as is; else it is built from catalog.json.
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
  obstacles), same cells as the top grid. Cables cross the deck ONLY through holes and the owner's edge
  segments (round the board edge where the border lies inside a segment, `edge_transit_mm` per crossing: board data,
  else `power_routing.edge_transit_mm`, else 2 x hole transit; a front segment only with `cables.route_in_front`).
  No edge segments = holes only; an under-board supply with neither usable holes nor segments is an error (owner,
  2026-10-26). Signal cables start/end on top and may go under through holes or segments: per pass
  `hole_transit_mm` (length, board data 15, unverified) + `hole_penalty` 15 (search only), under mm cost 0.9; own
  stacking limit `max_stack_under`; per-layer smoothing; lanes on top only. `route_all` ends with clean-ups (re-route
  each cable with plain costs; `_back_on_top` undoes a cable sent under so another could take its corridor), so
  congestion history never leaves a needless detour. Gig: no signal cable goes under (2026-10-26).
- Power cables are routed (`routing.route_power`, own grids with the DC cable width, own stacking, not counted against
  signal cables): an under-board supply's hop starts under the board, daisy hops and on-board supply hops on top; under
  mm cost 1, top mm `power_routing.top_cost` 3, up through holes or edge segments (edge transit, no penalty). Min length = plug measures +
  polylines + transits. A long top run (> 150 mm) warns. `power.assign` and the layout surrogate use the
  nearest-crossing estimate (`power.Crossings`: holes + edge points, `power.hop_estimate`, a cost in mm-equivalents with top mm x top_cost).
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
- Cable under its own plug (`feat/u-turn-plugs`, plan `docs/plans/u-turn-plugs.md`, owner 2026-11-13): a right-angle plug that does not point to
  the side its cable goes to has the cable turn back ACROSS it: the plug sits high enough on the pedal for one thin cable to pass under it. No
  keep-out (a cable's own plugs stay free for it in `route_all` / `smooth`; the side ranking is unchanged), no climb, no extra length (`min_mm`
  stays along the routed path on the deck); only ONE cable can pass under a plug, its own (other cables cross a plug over the top,
  `max_over_plug`; a right-angle DC plug under a neighbouring signal plug is `pass_pairs`, unchanged). The crossing is reported, information
  only: `routing.passes_under_own_plug(o, polylines)` (a segment of a top polyline more than `UNDER_OWN_MIN_MM` inside the option's
  `plug_body_rects` = head + barrel) sets `under_own_a` / `under_own_b` on every routed signal and DC cable (a pedal-start daisy leg: `under_own_a`
  = the previous pedal's plug); README Exits column `right (passes under its own plug)` (`build.exits_cell`), the sentence under the cable table
  (`build.under_own_text`), the build log line `routing: N cables pass under their own plug (S3, P4)` (`build.under_own_line`). The layout surrogate
  has no keep-out, so it agrees with the build.
- Plug orientation (`feat/plug-orientation`, plan `docs/plans/plug-orientation.md`, owner 2026-10-28):
  **collisions**: every used plug's footprint (chosen option: head, barrel, run; jacks without a plug model keep their
  fixed box from `ctx["fixed_zones"]`: first input, last output, extra jacks) must not overlap another jack's
  (`routing.plug_collision_findings`, `ctx["plug_collisions"]`, clearance warnings; NOT in `ctx["violations"]`); the
  side choice counts a collision like a blocked part (signal cables in chain order, then the DC plugs); proposals gate
  on `collisions`. **A DC plug passes under ONE signal plug** (owner 2026-11-03, `feat/dc-under-signal`: real angled DC plugs are plugged
  diagonally and go under a neighbouring patch plug; no 3D, no diagonal orientation): an overlap of a RIGHT-ANGLE DC plug's footprint (any
  option, pedal or on-board supply port) with a SIGNAL footprint (a modelled patch plug or a fixed audio box of a first input / last output /
  extra jack) is no collision, but ONLY when the two jacks face the same way on the canvas (`design.jack_facing`, after the pedal's rotation; a
  perpendicular or opposite pair is an ordinary collision; owner 2026-11-03). One pass per DC plug and per signal plug (`routing.pass_pairs` / `assign_passes`: DC plugs in natural key
  order, each takes its deepest overlap with a signal plug not paired yet; the rest collide as before). Not covered: straight DC plugs, DC
  vs DC, anything vs a pedal body (blocked parts stay). Footprints are marked (`routing.DcRects` with `right_angle` + `facing` for DC options, `routing.SigRects` with `facing` for signal
  options and fixed audio boxes, a fixed power box a non-right-angle `DcRects`, `like` keeps the marks; a plain list has no facing and never passes; `pass_eligible` tests it), so `collision_count` (plug ranking of both ends, `choose_signal`, `refine_dc_sides`, the surrogate's `_count`) is the same
  rule (it also counts the passes of OTHER plugs the option ends or creates by reshuffling the pairing: the change of the findings); passes go to `ctx["plug_under"]` [{"dc", "signal", "depth_mm", "cable", "signal_cable"}] (README line per pass via
  `routing.under_text`, power cables drawn below the signal cables in `routing.svg`), not to `plug_collisions`; the surrogate reports
  `det["plug_under"]` and agrees with the build (`tests/test_layout.py` gig agreement). **Down**: a right-angle plug (signal or power) may point down into a hole: `routing.down_available`
  (a cable-wide square at the bend point inside the effective holes, clear of under-board supplies; the top "free"
  rule does not apply); footprint = the head; measure = |exit_offset - depth/2| + `cables.jack_height_mm` + hole
  transit; the route starts / ends under the board. Owner: **always down when available**, even if longer (ranking:
  feasible, down, blocked + collisions, length). **DC plug types**: `cables.power_types`, per plug `routing.plug_rank`
  (feasible exit, down, blocked + collisions, side length, overlap, list order); one pedal-end type per serial cable (the port plug
  apart), per leg when forked; cables carry `type_a` / `type_b`; the power grid uses the widest type. The layout
  surrogate mirrors all three (per plug best type, no serial rule).
  **DC plug side by length** (`feat/power-plug-side`, plan `docs/plans/power-plug-side.md`, owner 2026-10-29): the exit side only matters
  for the cable, so among options that tie on the fit (same type, same fit key) the SHORTER cable wins, not "left" (the length only tells
  SIDES apart: `routing.rank_pool` subtracts the least estimate of the same type and fit, so the list order of the types is untouched).
  Two stages: (1) ESTIMATE in `power_plug_choices` (`dc_estimator`: the option's measure + `power.hop_estimate` for every leg that touches the
  plug, same function as the surrogate; part of `choose_dc`, so the signal plugs see the new footprints); (2) ROUTED refinement after the
  power routing (`refine_dc_sides`, in `route_power_choosing`): per plug the options on the same type and fit that are within `TIE_MM` (5)
  of the best estimate, plus the old ranking's pick (`o["legacy"]`), get an A* (plain costs, `plain_search`) for their legs; the plug
  starts from the old side and moves only when another saves more than `SWITCH_MM` (5); after changes the cables are routed once more and
  the result stands only if no leg became unroutable and the total did not grow. An override `exit_b` fixes the side (no choice). The
  build log prints `power: N DC plugs took the shorter side (saved X mm)` (`ctx["routing"]["power"]["side_savings"]`; X = the refinement's
  A* lengths, old side less kept side, no extra routing). Surrogate: the DC option of a plug is picked by (clearance cost, estimated cable of
  its legs, `Model._dc_length`, only between tied sides: `Model._dc_rel`) and the power term uses the chosen option's exit + measure
  (`measure_mm`) instead of the jack's measure point; the holes a candidate covers are tested against the pedal OUTLINES, as the build's
  `power.usable_holes` (so both estimates agree). A pedal-start daisy hop never gets `exit_a` (its plug is the previous leg's `exit_b`).
- Cable types in use (owner, 2026-10-22): patch cables are **Ernie Ball flat ribbon** (`ernie_ball_flat_patch_ra`,
  3.5 mm on-board width, flat angled plug 6.4 deep x 12.7 wide, ribbon leaves 19 mm from the jack axis: mostly
  estimates, see the file); every patch plug is angled, no straight plugs (straight/Neutrik types are role
  `reference` only). Fender Professional (`fender_pro_instrument_ra`, role instrument) is only the guitar/amp cable,
  not modelled yet. Power jacks: `cables.power_type` = `dc_ra_owner_baseline` (owner-measured random DC cable,
  2026-10-28: 12 deep x 8 wide, body reach 19, exit offset 8.4 = 70% of the depth (owner's rule of thumb, 2026-11-03, not measured);
  `dc_straight_owner_baseline` 34 x 10; both a baseline the owner may shrink; RockBoard `dc_ra_2_1_low_profile` kept as reference data): the head on the less blocked exit side (fewest blocked parts, then least overlap) plus a
  one-cable-width run is checked in `routing.power_plug_clearance`; without a power type `jacks.power_clearance`
  (default 5.5 / 5.5 mm) is used, never the audio box.
- Cable routing (`routing.py`): 2 mm grid; pedals grown by cable radius minus half a cell (any gap >= one cable
  diameter is a corridor); area = the board footprint + `edge_margin_mm` (default one diameter, 6 mm) at back and sides,
  nothing in front of the lowest pedals unless `cables.route_in_front` (then the board front + margin). The usable board area
  (board.json `bounds`) limits the PEDALS only, never the cables (owner, 2026-11-02: `fix/cable-area`); signal and power grids
  alike, the under grid stays the whole board; at most `max_stack` (2) cables per cell; at most `max_over_plug` (2) other
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
- Extra jacks (Exp, Tap, Thru, XLR...) are documentation only until listed in a project's `jacks.extra_used`. A used extra jack gets
  the audio clearance box, or with `cables.extra_type` (per jack `cables.extra_types` {"<pedal>.<jack>": type}; a STRAIGHT plug, role
  expression|patch) a box of head depth + one cable diameter x head width (`jacks.extra_plug_box`, mirrored in `layout.py`; owner
  2026-11-06: every expression cable is straight on the board side; gig: `exp_trs_straight_baseline`, a 40 x 12 mm placeholder). The
  cable itself is not routed or measured.
- Floor devices (owner, 2026-11-13, `feat/floor-devices`): pedals that sit on the floor, not on a board, and go with any board (the
  BOSS EV-30 expression pedal, the Dunlop Cry Baby GCB95F): catalog `floor_device: true`; never in a `signal_chain` (error); a project lists
  the ones it uses in `floor` [{"device", "controls": ["<pedal>.<jack>", ...], "note"}]: the jacks a device drives count as used extra
  jacks (`jacks.with_floor` merges them into `jacks.extra_used` in `build.validate` and `propose_layout`; `jacks.floor_findings`
  validates). README: project "Floor devices", root "Floor devices" (never shared gear). Their cables are not routed or measured.
- Generated files (READMEs, .mmd, .svg) are never edited by hand; change the generator/data.
- Layout injection: `build.validate(..., items=...)` checks a parsed layout instead of `playground_design.json`
  (`ctx["layout_source"]` file|injected); `playground_design.json` is the owner's layout: only `fetch_playground.py` writes it.
- Footswitch spacing is comfort, not a hard rule (owner, 2026-10-23: no real minimum; maximise the distance against
  the other goals). Crowding of a pair of switches on DIFFERENT pedals = priority x max(0, comfort - d)^2 / comfort
  (`footswitches.crowding`, comfort `footswitches.comfort_mm` default 100 mm): the closest pairs count most. The
  build reports the sum (README: crowding, 8 closest pairs with types); the layout search minimises it (weight
  `layout.weights.footswitch` 2). An optional `footswitches.min_distance_mm` makes closer pairs warnings (strict:
  errors) and adds a steep penalty in the search; no default ("auto" was dropped). Missing data is one
  aggregated warning per project. `routing.svg` draws the switches (colour per type) and too-close lines.
- Cable ids (owner, 2026-10-29): signal cables S1.. along the chain; every power cable you buy is **P#** (numbered over
  supply instance, output, then per pedal for a forked output; a serial output is one cable); a cable with several legs
  (serial daisy chain) names them **P#.1, P#.2...** in daisy order (P#.1 starts at the supply port), a one-leg cable is just
  P#. No C# ids. `jacks.check` assigns both (hop `cable` = P#, `id` = leg id, `routing.power_leg_id`), `routing` uses the hop
  `id` as the cable list id (hand-made ctx without ids: each hop its own P#); `power.cable_ids(supplies, project)` gives
  the same leg ids per pedal (output `style`, else `power_routing.daisy_style`). `cables.overrides` keys must be a
  cable list id (S#, one-leg P#, P#.n): else a build error with a hint (`routing.override_id_errors`). A leg is routed,
  overridden and drawn (label) on its own; for buying, each leg's min length is the spacing between two plugs.
- Power daisy chains (2026-10-27): per output `power.supplies[].outputs[].style` serial | forked (project default
  `power_routing.daisy_style`, default serial = one cable through every pedal, routed leg by leg); forked = one cable
  per pedal from the port (fork starts share the port cell without a stacking limit; every leg owns the port plug).
  Each leg has `cable` (its P#) and `style`; `ctx["power_cable_summary"]` = physical cables (plugs, `leg_mm`, min_mm =
  sum of legs, None if a leg is unrouted); README "DC cables to buy" (one row per P#, each leg's min spacing); `power.assign` and the
  surrogate: forked = sum of port -> pedal estimates, serial = chain order. Constants `routing.SERIAL` / `FORKED`.
- Footswitch toppers (owner, 2026-10-27): per project `footswitches.toppers` ["<pedal>.<switch>"], set by hand;
  a pair's effective distance = d + `topper_bonus_mm` per topper on it (default 4.5 mm = the height a topper
  adds, RockBoard StomPete, retailer listing: a rough proxy, owner 2026-10-28); the build's crowding and
  `min_distance_mm` use the effective distance, the README also shows it without toppers. Post-layout suggestions
  only on BYPASS switches (`footswitches.TOPPER_TYPES`, owner 2026-11-04: the switches stepped on most; never a boost switch; a
  tap switch in the middle of the board, e.g. the Monk's, only by hand in `footswitches.toppers`)
  (`footswitches.suggest_toppers`, greedy: largest crowding reduction, ties more crowded pairs > type priority > nearer
  the front; stop at `max_toppers` (default 5 per board, owner; null = no cap) or below `topper_min_gain` 0.02 of the crowding). The layout search, the proposal
  metrics / finalist gate and `proposal_inputs_sha1` ignore toppers (post-layout finishing step).
- Layout proposals (`layout.py`, `propose_layout.py`; plan `docs/plans/pedal-position.md` + owner decisions): all
  chain pedals may move (`layout.pins` optional), rotations 0/90/270 (never 180), their BODY never outside the usable board area
  (board.json `bounds` shrunk by `board_margin_mm`; the board without bounds; pedals and on-board supplies; `Model.body`,
  precomputed per rotation from `design.body_rect`, used by `feasible_one`, `repair_start` and `free_distance`'s board term; pre-processing
  pushes a pedal outside the least distance inside, a pinned one too, which then stays pinned there), no
  overlap beyond TOL (touching allowed). Surrogate score (weights `layout.weights`): clearance dominates (real
  penetration 50/mm, 2 mm margin 10/mm, 100 per blocked plug), signal 1/mm (exits octile + 0.6 x detour around
  crossed pedals), power 0.1/mm, footswitch crowding by type priority, first input to the right edge, last output
  to the nearest left/right/back edge, small right-to-left flow, accessibility (tuner back; boost/eq/master pedals
  front 0.3; drives and tap switches front 0.1; a boost switch front 0.05; modulation avoids the front unless tap),
  rotation preference (0, then angles in use), move cost (0.2/mm + 25 per moved pedal). The surrogate checks the
  same jacks as the build (first input / last output: fixed audio box; power plug side overrides). `max_change` fix
  (default: max 40 mm, no swaps/rotations) / rearrange / free. Finalists AND the owner's layout get their own power
  wiring (`power.assign`, same policy as the build via `power.output_findings`; `cables.overrides.<P#>` / `<P#.n>` follow their
  pedal, `power.remap_overrides`) and are checked with `build.validate(items=, project=)`; a proposal must not be
  worse than the owner's layout on errors, blocked plugs, routing problems (power cables without a path included) and footswitch pairs below a set minimum. Proposals never
  touch `playground_design.json` or the owner's power wiring in project.json; the README section is rendered from
  `proposals/meta.json`, stale when `common.proposal_inputs_sha1` changed (design file, project.json, cables, the
  project's catalog entries incl. jacks and footswitches) or the chain changed. A pedal of the owner's layout outside the usable
  area is moved to the nearest feasible spot first (`layout.repair_start`, a move for the move cost; `CannotPlace` -> the CLI
  stops naming the pedals); the build warns about every item outside (`jacks.outside_usable`: `layout: <pedal> is outside the
  usable board area by N mm (back)`, an error with `validation.strict_bounds`; under-board supplies never); the proposal
  table has a row "Outside the usable area" (proposals: 0).
- Pictures (`svgdraw.render`): sized in mm (prints 1:1 from a browser); committed SVGs have outlines only, pedal
  images only in git-ignored `routing.local.svg` (data URIs from `.cache/images`, `common.fetch_image`).
- Pedal outlines (`design.outline_rects`, `layout["shapes"]` {item id: [rects]}): the router (grid, smoothing, lanes),
  plug clearance (`routing.blocked_parts`, `jacks.check` fixed box) and the layout surrogate's clearance use the
  outline; pedal-pedal overlap, layout feasibility, moves and swaps keep the Pedal Playground box (owner, 2026-10-23).
- Pedal bodies (owner, 2026-11-02, `feat/pedal-body`, plan `docs/plans/pedal-body.md`): ONLY the bounds tests use the body
  (`design.body_rect(item, bodies)`, `layout["bodies"]` {item id: canvas rect}; `jacks.outside_usable`, the layout model; no
  body data = the box); side jacks may overhang the usable area and the board. The plug of a jack that lies OUTSIDE the usable
  area (`routing.jack_overhangs`, back or sides, > 0.05 mm), and every plug option that reaches past the board edge at the back or a
  side (`routing.reaches_out`, owner 2026-11-03: a plug sticking out over the edge), is routing area: `routing.plug_zones` (head, barrel, run,
  exit; kept in `ctx["routing"]["plug_zones"]`) -> `build_grid(..., zones)` opens the cells within the cable radius of a zone (the
  extent grows at the back / sides by whole cells, only the added cells are walls, so without zones the grid is main's; `area_rect`
  ignores them; pedals still block; nothing in front); the layout surrogate counts an exit inside its own plug's footprint as inside
  for such a plug only (`layout.in_area`). Every other plug keeps the plain test (its exit must lie in the board + margin). `bodies` is threaded like `outlines` (`build.validate(body_data=)`, `jacks.check`, `layout_from_items`,
  `layout.Model(bodies=)`); a caller that passes its own `outlines` and no `bodies` gets no bodies (the boxes); `proposal_inputs_sha1`
  includes the bodies.
- Composed boards (owner, 2026-11, `feat/board-pieces`, handover `docs/handovers/board-pieces.md`): a layout may hold several `pedalboard` items (the
  bass board: a D'Addario XPND 1 + its extension, which slide on each other). The pieces are SUMMED and evaluated as ONE board: the deck
  is the union of the footprints (pieces may overlap; a pedal may straddle a joint), under the deck cables pass freely between pieces.
  `jacks.layout_from_items` returns `pieces`, `board_rects` (footprints), `board_rect` (their bounding box: the extent everywhere the single
  footprint was used: `design.layout_board_rect(s)`), `usable_rects` (per piece `design.board_bounds` with ITS bounds), `usable` = their
  bounding box, `holes` / `edge_segments` = every piece's, `board` = the first piece; `hole_transit_mm` / `edge_transit_mm` = the first
  piece's entry that has one. Bounds test = the body inside the UNION of `usable_rects` (`design.inside_union`, `outside_union` -> (side,
  mm) = the least single-axis shift that brings it inside, one rect = the worst side as before, `slide_room`; `jacks.outside_usable`,
  `layout.Model.inside_usable` / `free_distance`; `has_bounds` = any piece's usable rect differs). Routing: `build_grid(..., pieces=)`
  makes the cells farther than `edge_margin_mm` from every piece walls, `under_grid(..., pieces)` blocks the cells outside every piece,
  `edge_links(..., pieces=)` takes border cells of the union (a joint is no edge), `jack_overhangs` / `reaches_out` (plug zones) test
  against the union; `route_project` / `route_power` pass `layout["board_rects"]`. One piece = today, cell for cell. The layout surrogate's
  `in_area` takes the same union (`Model.pieces`); its routing area `area_box` is the bounding box (an estimate). Seams: `design.UNION_TOL`
  (float noise between abutting pieces is no gap). Holes where pieces overlap: a way through only where every covering piece has a hole
  (`design.composed_holes`). A `pieces` entry for an image wins over the top-level keys, also for the first piece. Drawings: every piece and every
  usable rect. `boards.py` derives the holes of every piece's image.
- `build.validate(..., route=False)` skips the cable router (data findings only; used by `--list-missing`).

## Working agreements with the owner
- Commit/push only when asked; feature work on `feat/<name>` branches, merged into `main` after a code review.
- Commit messages end with the Co-Authored-By line given by the harness.
- When delegating to an agent, write a handover (goal, context, constraints, files, acceptance, what not to
  touch) to `docs/handovers/<task>.md` and point the agent at that handover only. Keep its scope and inputs
  minimal: one well-bounded task, only the decisions, conventions and file/function names that task needs
  (copy the relevant lines in), no "read the whole plan / other handovers / all of CLAUDE.md" pointers.
- Delegated agents (`general-purpose`: implementation AND code review) run on `model: sonnet`; Opus only for
  planning or when the owner asks.
- Keep this file current when structure, conventions or decisions change.
