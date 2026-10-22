# Pedalboard planner: briefing for Claude / agents

Read this first. It gives the basics so a new conversation or agent only needs a goal and an approach.
Task-specific handovers live in `docs/handovers/` (one file per delegated task; read the one you are given).
Open work and questions for the owner: `docs/TODO.md` (hand-written backlog; keep it current).

## What this repo is
A data-driven planner for the owner's three pedalboards (projects): `guitar-gig` (Fender Professional Medium,
2x Strymon Ojai R30), `guitar-practice` (Rockboard Duo 2.1, 1 Ojai R30 still to buy), `bass` (Rockboard Duo 2.1,
Harley Benton PowerPlant ISO-5 Pro). Python 3.12, stdlib + Pillow (+ tkinter for the jack app). No other deps.

## Layout
- `catalog/pedals.json`: every pedal (specs that belong to the pedal: tags, digital, clocked_noise, bypass,
  `power_consumption` {current_ma (worst case), min_voltage_v, max_voltage_v, needs_isolated_output}, prices,
  `playground_title` = key into Pedal Playground's database, intrinsic ordering rules in `dependencies`).
- `catalog/power_supplies.json`: supply models (ports, voltage options, mA limits, quantity owned).
- `catalog/cables.json`: cable types with a `role` (patch | instrument | power | reference), `diameter_mm` = width ON
  THE BOARD (routing width; a flat ribbon's narrow side), `jacket`, plug style right_angle|straight, head
  depth/width/thickness, right-angle exit offset / body reach / barrel width, sources, `verified` list, notes. Data.
- `catalog/jacks.json`: jack positions per catalog id. Written ONLY by `scripts/jack_setter.py` (Tkinter).
  x,y = fractions (0..1) of the Pedal Playground image (unrotated), at the OUTER EDGE of the physical jack;
  facing = side the plug enters from (left/right/top/down); function input|output|power|power_out|other.
- `projects/<name>/project.json`: everything that can change per board: board, signal_chain, rules (with
  priorities), sections, power wiring (`power.supplies[].outputs[]`, daisy-chain order = list order, operating
  voltage = output voltage), power_policy, `jacks` (clearance = audio box, power_clearance = smaller DC box used only
  without a power type, extra_used, supplies_layer, slack_mm), `cables` (`type` = default patch type, must have role
  patch; `power_type` = DC plug type, role power; routing parameters; `overrides.<S#>` with `type`, `exit_a`,
  `exit_b` = left|right|auto, tips; `overrides.<P#>.exit_b` fixes a power plug's side), `validation` flags.
- `projects/<name>/playground_design.json`: the owner's hand-made Pedal Playground layout (only guitar-gig so far).
  Generated per project: `README.md`, `signal-chain.mmd`, `power.mmd`, `cables.svg`, `playground.json`.
- `scripts/`: `build.py` (validate all projects, write READMEs/diagrams; exit 1 on errors), `common.py` (paths,
  loaders, Pedal Playground DB cache, mm helpers), `design.py` (parse Pedal Playground saves, jack geometry in mm),
  `jacks.py` (jack data, fixed-box clearance, jack-to-jack length estimates), `routing.py` (cable model, plug
  heads, side choice, grid router, plug-head clearance),
  `jack_setter.py` (GUI), `to_playground.py` (write Pedal Playground layouts), `new_project.py` (scaffold).
- `tests/`: pytest (`python3 -m pytest tests`), ~118 tests, hand-computed geometry cases.

## Commands
```
python3 scripts/build.py [project...]          # validate + regenerate (fast, no network after the DB cache)
python3 -m pytest tests -q                     # all tests
python3 scripts/jack_setter.py <catalog id>    # place jacks on a pedal image (needs a display)
python3 scripts/jack_setter.py --list-missing  # what still needs jacks
python3 scripts/to_playground.py [project...]  # Pedal Playground "Load from File" layouts
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
- Supplies sit under the board (`supplies_layer: "under"`): not obstacles; power cables are modelled, not routed.
- Plug heads (`design.plug_geometry`): head = depth x width rectangle centred on the jack, extending along the
  facing. Right-angle: cable leaves to the LEFT or RIGHT of the facing (seen from above looking out along the
  facing; facing right -> left is up), `exit_offset_mm` out (default depth/2), body to `body_reach_mm` from the jack
  axis (default width/2), then `cables.exit_run_mm` (default one diameter) straight: the router starts there.
  Straight: cable leaves along the facing at head depth, then the run. The router picks each end's side: feasible
  first (free path, else "squeezed" through gaps narrower than the cable, never through a pedal body), then fewest
  blocked plug parts, then shortest route; overrides fix a side. Clearance of signal jacks whose cable has a type
  = head + barrel + run on the chosen side (checked in `routing.route_project`); power, extra and first-in /
  last-out jacks, and projects without `cables.type`, keep the fixed box (`jacks.clearance`, in `jacks.check`).
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
  nothing in front of the lowest pedals; at most `max_stack` (2) cables per cell; signal cables only.
- Extra jacks (Exp, Tap, Thru, XLR...) are documentation only until listed in a project's `jacks.extra_used`.
- Generated files (READMEs, .mmd, .svg, playground.json) are never edited by hand; change the generator/data.

## Working agreements with the owner
- Commit/push only when asked; feature work on `feat/<name>` branches, merged into `main` after a code review.
- Commit messages end with the Co-Authored-By line given by the harness.
- When delegating to an agent, write a handover (goal, context, constraints, files, acceptance, what not to
  touch) to `docs/handovers/<task>.md` and point the agent at this file plus the handover.
- Keep this file current when structure, conventions or decisions change.
