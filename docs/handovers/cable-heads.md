# Handover: model cable heads (plugs) for clearance and routing

Branch: `feat/cable-routing` (routing committed as 77514b7; nothing pushed). Read `CLAUDE.md` first.

## Goal
Replace the fixed jack clearance box (6.3 mm outward x 7 mm each side, `project.json` `jacks.clearance`) with a
realistic plug model: once we know which cable is used at a jack and which way the cable leaves the plug, the
space needed in front of that jack is the plug head's footprint, and the router starts the cable where it
leaves the head. Result: more realistic clearance warnings and cable lengths.

## Current state (what exists)
Implemented on `feat/cable-routing` (2026-10-22, uncommitted in the working tree), owner feedback of 2026-10-22 applied:
- `catalog/cables.json`: every type has a `role` (patch | instrument | power | reference); `diameter_mm` is the cable
  width on the board (routing width); `jacket` gives the cross section.
  - `ernie_ball_flat_patch_ra` (patch, default of all three projects): 3.5 mm on-board width (owner), ribbon 6.4 mm tall
    (Guitar Center 0.25 in); flat angled plug: head_depth 6.4 (Ernie Ball: "protrudes a quarter of an inch"), head
    width/thickness 12.7 (Guitar Center 0.5 in connector, retailer), exit_offset 3.2, body_reach 19 (inferred from a
    Gearank review: a '3 in' cable is a bit over 5 in overall), barrel 6.4. Only head_depth counts as verified; the
    rest are labelled estimates. No mm figures are published by Ernie Ball.
  - `fender_pro_instrument_ra` (instrument; was `fender_pro_patch_ra`): guitar/amp cable only, 8 mm jacket (Fender),
    head 20 x 16 placeholder; not modelled yet, no project uses it.
  - `dc_ra_2_1_low_profile` (power, `cables.power_type` of all three projects): RockBoard angled flat power plug
    20 x 11 x 10.5 mm (maker) mapped to depth 11 / height 10.5 / body reach 14.5 (our interpretation), cable 3.2 mm
    (generic 22 AWG), barrel 6 estimate. Nothing published for Strymon / Harley Benton / Cioks / Truetone heads.
  - `generic_straight`, `neutrik_np2rx`, `neutrik_np2x`: role reference only.
- `routing.validate_types` checks roles; `routing.validate_project_types`: `cables.type` must be a patch type,
  `cables.power_type` a power type, signal overrides may not use a power type.
- Power jacks: `routing.power_plug_clearance` (called at the end of `route_project`) puts the DC head + barrel + one
  power-cable-width run on each placed pedal's power jack, on the side with the fewest blocked parts (then least
  overlap; `cables.overrides.P#.exit_b` fixes it); violations name the type, side and part; heads drawn in the SVG;
  the power cable rows show the type and the pedal-end exit side. Without `power_type`, `jacks.check` uses the new
  `jacks.power_clearance` box (default 5.5 x 5.5 mm, the barrel OD; estimate) for power jacks and on-board supply
  ports; the audio box `jacks.clearance` (6.3 / 7) is only for other audio jacks.
- Gig result: before (Fender placeholder) 13/16 routed (2710 mm), 4 squeezed, S8/S9/S14 unroutable, 22 clearance
  warnings. After: 16/16 routed (2679 mm), none squeezed, 3 clearance warnings: monk.out (Ernie Ball head, 1.0 mm,
  Belle Epoch), red_muck.power (DC head, 3.0 mm, Analog Chorus), monk.power (DC head, 5.1 mm, Belle Epoch).
- Tests: 118 passing (new: real-type geometry, power plug side choice / overlap / override, role checks, power box);
  build ~0.25 s for all projects.
- Open: measure one Ernie Ball plug (depth from the jack face, block length from the jack axis to the ribbon) and one
  Ojai DC plug; confirm the reading of RockBoard's L x W x H; guitar/amp (Fender) cables still not modelled.

## Decisions taken (owner did not specify; use these defaults, all configurable)
- Cable types live in a new catalog file `catalog/cables.json` (data, not code): per type `diameter_mm`,
  `plug` {style: "right_angle" | "straight", head_depth_mm (how far the head sticks out from the jack face along
  the facing), head_width_mm (across), head_thickness_mm (height, informational)}, `tips` (TS/TRS/XLR), source/notes.
- Owner input so far: "Fender says the cable is 6 mm diameter and the jack head is 8 mm" (head size was
  explicitly ignored for the routing area). Research the Fender patch cable (and a typical straight plug) for
  head dimensions with sources; record unverified values as such. If nothing is found, use clearly labelled
  placeholders (right-angle: depth 20 mm, width 16 mm; straight: depth 40 mm, width 12 mm) and say so.
- Projects pick a default cable type (`project["cables"]["type"]`) and may override per cable
  (`cables.overrides.<cable id>.type`, `.exit_a` / `.exit_b`).
- Right-angle plugs: the cable leaves the head to the LEFT or RIGHT of the jack (relative to the facing, i.e.
  perpendicular to the facing, in the board plane). The router chooses the better side per end automatically
  (try both, keep the shorter feasible route); a project override can fix it. Straight plugs: cable leaves
  along the facing at head_depth.
- Clearance per used jack = the head footprint rectangle (depth x width, centred on the jack, extending along
  the facing) plus the first cable segment leaving the head on the chosen side. When a jack has no known cable
  type (power jacks, under-board), keep the current fixed box (`jacks.clearance`).
- Power cables: keep as today (modelled, not routed, under_board true); you may add a power plug type
  (DC barrel, right-angle) for clearance at the pedal's power jack if simple.

## Constraints
- mm everywhere; no images in the repo; keep findings as warnings (strict flags promote them).
- Keep `uv run scripts/build.py` fast (well under 1 s for guitar-gig today) and green; keep all tests passing;
  add tests with hand-computed geometry (head footprint for each facing and both exit sides, rotation 90/270,
  router choosing the shorter exit side).
- Do not edit generated files by hand; do not touch `catalog/jacks.json` positions (owner-placed).
- Do not commit or push; leave changes in the working tree on `feat/cable-routing`.
- Update `CLAUDE.md` (conventions) and the generated README text if the model changes.

## Acceptance
- `catalog/cables.json` with at least the Fender patch cable (right-angle) and a generic straight plug, sources noted.
- Clearance check uses head footprints for signal jacks; violations messages name the cable type and exit side.
- Router starts/ends cables at the head exit point on the chosen side; table shows type and exit sides.
- Tests pass; build green; a short report of what changed on the gig board (cables routed, lengths, warnings).

## Owner feedback, 2026-10-22 (supersedes the defaults above where they conflict)
- Patch cables on the boards are **Ernie Ball flat (ribbon) patch cables, red**, not Fender. They are flat: their
  width on the board is about **3-4 mm** (use 3.5 mm as the routing width unless research gives a better figure
  for the on-board width). Their plugs are **flat, angled (right-angle), low-profile heads** that take little space.
  Research the Ernie Ball flat ribbon patch cable plug dimensions (head depth from the jack face, head width, head
  thickness, where the cable leaves) with sources; mark unverified values; if nothing is published, derive a
  clearly labelled estimate from product photos/listings and say so.
- **No straight plugs are used.** Every patch plug is angled. Keep `generic_straight`/Neutrik types in the
  catalog as references only; nothing should default to them.
- **Fender** (Professional Series, 8 mm jacket per retailers) is only the **instrument-to-board cable** (guitar ->
  first pedal, last pedal -> amp), which is not modelled yet. Keep the Fender type in the catalog with a role/note
  saying so, but it must not be the patch-cable default.
- **Power jacks need much less clearance** than audio jacks: the 6.3 / 7 mm box was an audio default. Model the DC
  plug too: add a DC power-cable type (right-angle 2.1 mm barrel, low profile; research typical dimensions of the
  flat/right-angle DC cables supplied with Strymon Ojai / common isolated supplies, with sources) and use its
  head for power-jack clearance. If you keep a box fallback for power jacks, make it a separate, smaller,
  per-project parameter (e.g. `jacks.power_clearance`), not the audio one.
- Default patch type for all three projects: the Ernie Ball flat patch cable. The routing width (cable
  "diameter" in the grid) follows the cable type's on-board width.
- Expected effect: far fewer clearance warnings and more cables routed on the gig board; report before/after
  against the current state (13/16 routed, 22 clearance warnings, 4 squeezed, S8/S9/S14 unroutable).
