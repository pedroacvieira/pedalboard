# Plan: `feat/u-turn-plugs` (a right-angle plug that turns its cable back)

Status: plan only (2026-11-13). Nothing implemented. Owner decisions at the end; the plan follows the recommended defaults.

## Owner decision 2026-11-13 (overrides Decision 1 and the keep-out design B below)
A cable doing a U-turn MAY cross its own plug: in real life the plug sits high enough on the pedal that one thin cable (the owner's
Ernie Ball flat patch cables) passes UNDER it. So:
- No keep-out of a cable's own head and barrel (sections 3.1, 3.4, 3.5 and 3.7 are dropped: `keepout_rects`, `forbid` in the search,
  the own rects in `smooth`, the lane check, the demotion of combinations, `around_own_plug`, the surrogate extra). A cable's own plugs stay
  free for it in `route_all` / `smooth`, as before; the router's side ranking (feasible, down, blocked + collisions, length) is unchanged.
- The crossing is the cable passing under its own plug: no climb, no extra length (`min_mm` stays along the routed path on the deck). Only
  ONE cable passes under a plug, its own; other cables still cross a plug over the top (`max_over_plug`). A right-angle DC plug passing
  under a neighbouring signal plug (`pass_pairs`) is unchanged.
- Information only (decision 4): the README Exits column reads e.g. `right (passes under its own plug)`, the build log prints
  `routing: N cables pass under their own plug (...)`, no warning. Signal and DC cables alike (`under_own_a` / `under_own_b`).
- The layout surrogate has no keep-out either, so it already agrees with the build (it neither adds length nor forbids anything).
- What is left of the feature: the detection (`routing.plug_body_rects`, `routing.passes_under_own_plug`) and the report. The first
  implementation attempt (keep-out, steps 1 and 2) was reverted on `feat/u-turn-plugs`; its measurements on the live projects (before the
  override) are in section 11.

## 1. Goal (owner's backlog, TODO 3.2)
When a right-angle plug cannot point to the side its cable has to go, point it the other way and turn the cable back (a
U-turn): longer minimum length, the turned cable occupies both sides of the plug; the router considers it when the direct side
is blocked or worse (signal AND DC plugs); the layout surrogate mirrors it.

## 2. Finding: the router already turns cables back, but over the plug and uncounted
The router can already pick the "wrong" side: `choose_signal` / `plug_rank` rank by feasibility, down, blocked parts + collisions
and only then by length, so a blocked or colliding direct side loses to the other one. The cable then has to come back. Today it
comes back straight across its own plug, because:
- `route_all` excludes a cable's own plugs from the plug limit (`crossed`: `name not in plugs[k][0]`) and its own plug cells cost
  nothing extra. The grid has pedals as walls, never plugs.
- `smooth(..., own_plugs)` lets a segment touch its own plugs freely.

So today's "U-turn" is a cable lying across the top of its own plug (a 3D fold, 12.7 mm high for the Ernie Ball block). Its
`min_mm` misses both the fold and the way round, and the plug's other side is never checked for room.

Measured on the current data (a scratch script on `build.validate`: routed polyline between the two exits, one cable radius
from the plug's own head / barrel; ends that point down left out because their cable goes into the head on purpose):

| project | signal ends with a side exit | ...whose cable crosses its own plug | DC pedal plugs with a side exit | ...crossing their own plug |
|---|---|---|---|---|
| tests/fixtures/guitar-gig | 29 | 2 | 13 | 2 |
| guitar-gig (live) | 24 | 0 | 12 | 2 |
| guitar-practice | 11 | 8 | 5 | 1 |
| bass | 3 | 1 (a 1.3 mm graze) | 3 | 0 |

Example, practice S3 (`ibanez_ts_mini.out` -> `duke_of_tone.in`): the two pedals stand 6.5 mm apart, with both jacks in that
gap. Pointing the plugs at each other makes their barrels collide, so both point away. The ribbon leaves the Ibanez plug upwards
(exit y 408), then runs straight down across its own 6.4 x 12.7 mm block to y 449. That is 41 mm of cable drawn through a plug.

The feature therefore has two parts: (1) make the turn physical: a cable may not cross its own plug; (2) let the router and the
surrogate model the U-turn and price it correctly. Once (1) holds, a correct U-turn follows from routing alone (section 3).

## 3. Design (recommended: the turn is ROUTED, no new plug option)
Two designs were considered:
- **A: a fixed U-turn option** (new exits `u_left` / `u_right` with fixed turn and return footprint parts). Section 10 describes
  it. This plan does not recommend it: once a cable may not cross its own plug, an ordinary side option whose route goes round
  the head front is the same physical set-up. Its footprint is smaller (head + barrel + run only), so it beats the fixed option on
  blocked parts and collisions and ties it on length. The fixed option would almost never win, so A only works with an extra
  artificial keep-out that stops ordinary options from turning back.
- **B (recommended): the own-plug keep-out.** Every cable keeps out of its own plugs' head and barrel, in the grid search AND in
  smoothing. A side option whose cable has to go to the other side is then routed round the front of the head: that route is
  the U-turn. The length is measured along it like any route, and the ranking needs no change. The build marks such ends as
  "turned back" for the README.

### 3.1 Geometry of the U-turn
The plug keeps today's geometry (`design.plug_geometry`, unchanged): head, barrel and cable run on the chosen side X; the cable
starts at `exit` (bend + `body_reach_mm` + run along X). New in this plan:
- **Keep-out of a plug option** (`routing.keepout_rects(o)`): the option's `head` and `barrel` rects, top layer only. A plug that
  points down has none: its cable goes down inside the head on purpose, under the board. A straight plug: its `head`. A fixed box
  (no plug model) has none. The `cable` run is no keep-out because the cable itself lies there.
- **Grid**: keep-out cells = `rect_cells(grid, r, grow_of(cfg))` of those rects (the same growth as walls, so a gap of one cable
  width in front of the head stays passable), minus the start and goal cells (always enterable, as today). Per net: the keep-out
  of BOTH end options of that cable. For a serial DC leg that starts at a pedal plug, that plug counts too, because its exit is the
  start.
- **Smoothing**: the own head / barrel rects are added to that cable's obstacle list in `smooth`, with the same clearance rule as
  pedals (never closer than the grid path, at most the radius). `own_plugs` still exempts the own plugs from the plug-touch rule
  (b). Without this the string pulling would cut back across the head.
- **The turn**: no bend radius, as for every cable (owner: all cables bend alike). The smoothed route hugs the grown head and
  barrel: from the exit diagonally to the barrel's grown outer front corner, along the head front at one radius, round the far
  front corner, then on to its target.
- **Extra length**: no separate term. `min_mm` = `measure_mm` (unchanged) + the routed polylines + transits, as today. The route
  now goes round the head instead of through it.

Hand-computed reference (the tests use it). The jack is at (0, 0) facing right (u = +x, side "right" = +y), the target is
straight up at q = (3.2, -30), continuous geometry (no grid), r = cable radius:
- Ernie Ball (`ernie_ball_flat_patch_ra`: depth 6.4, width 12.7, exit offset 3.2, reach 19, barrel 6.4, d 3.5, run 3.5): head x
  0..6.4, y -6.35..6.35; barrel x 0..6.4, y 6.35..19; exit (3.2, 22.5); `measure_mm` 22.5. Grown keep-out envelope: front x 8.15,
  y -8.1..20.75. Path: exit -> (8.15, 20.75) -> (8.15, -8.1) -> q = 5.2502 + 28.85 + 22.4524 = **56.5527**, so `min_mm` = **79.05**.
  Today's straight line across the plug is 52.5 (75.0 total). The direct "left" side would give 22.5 + 7.5 = 30.0.
- DC owner baseline (`dc_ra_owner_baseline`: depth 12, width 8, offset 8.4, reach 19, barrel 6, d 3.2, run 3.2): head x 0..12, y
  -4..4; barrel x 5.4..11.4, y 4..19; exit (8.4, 22.2); `measure_mm` |8.4 - 6| + 19 + 3.2 = 24.6. Convex front chain of the grown
  rects: exit -> (13.0, 20.6) -> (13.6, 5.6) -> (13.6, -5.6) -> q = 4.8703 + 15.0120 + 11.2 + 24.9479 = **56.0302** (the bounding
  box instead of the hull: 56.5894).

### 3.2 When it is offered and how it ranks
- The turn is not a separate option. Any side option whose cable must reach the other side gets it from the router. Nothing
  changes for down options and straight plugs. A straight plug's cable already leaves along the facing and only keeps out of its
  own head.
- Ranking (unchanged keys): signal `choose_signal` = (exit outside the area, mode, not down, blocked + collisions, length); DC
  `plug_rank` = (failed, infeasible, not down, blocked + collisions, side length, overlap, type order). "Direct side blocked" ->
  the blocked-parts / collisions key picks the other side, as today. "Direct side worse" -> the side length now includes the turn,
  so the shorter physical choice wins when the fit ties. Down still wins where available.
- **Mode with the keep-out** (signal): `Grid.connected` / `Under.connected` ignore the keep-out (components are cached per
  grid). Keep that test and demote lazily: in `choose_signal`, when the best-ranked combination's `plain_search` (with its
  keep-out) finds no path, set its mode to 1 (squeeze) and then 2, re-rank, and repeat until a combination has a path or none is
  left. DC: `route_power` already turns a cable without a path into `avoid` -> `retry_unroutable` picks another option.

### 3.3 Override syntax
No new value. `cables.overrides.<S#>.exit_a` / `exit_b` and `<P#>.exit_b` keep left | right | down | auto. They fix the side the
plug POINTS to (the barrel side), and the router turns the cable back when its target lies the other way. The README tells the
owner when that happens (3.6). (Design A would need `u_left` / `u_right`: see section 10.)

### 3.4 Signal path (`routing.py`)
- `astar(..., forbid=frozenset())` / `astar_layers(..., forbid=)`: top cells in `forbid` are not enterable (like walls; the start
  and goal are always enterable). Under states are unaffected.
- `plain_search(memo, grid, start, goal, squeeze, under, forbid=frozenset())` and `_search(...)`: memo key `(start, goal,
  squeeze, forbid)`. A frozenset caches its hash. Build each option's `o["keep"]` (frozenset of cells) once per grid; a
  combination's forbid = `oa["keep"] | ob["keep"]` minus the two end cells.
- `route_all`: nets become `(name, s, t, squeeze, forbid)` (forbid optional, default empty), passed through the rounds, the
  clean-up and `_back_on_top`.
- `route_project`: `o["keep"]` per end option (top grid), the lazy demotion (3.2), nets with forbid, `path_geometry(...,
  own_rects=...)` passes the own head / barrel rects to `smooth` as extra obstacles for the top stretches.
- `lanes` is drawing only. Make `valid` reject a lane that crosses the cable's own head / barrel, so the drawing does not undo
  the turn.

### 3.5 DC path
- `route_power`: per net, the keep-out = the target plug's option (`ob`) plus, for a leg that starts at a pedal or an on-board
  port plug, the source option (`oa`), built on the power grid `pgrid`. A forked port: every leg of the fork keeps out of the port
  plug. Pass it to `route_all` and the smoothing (`path_geometry` own rects).
- `refine_dc_sides`: its `plain_search` calls pass the same forbid.
- `dc_estimator.length(o, key)`: add the around-the-plug extra (3.7) from the option's exit towards the point the estimate heads
  for first (the nearest crossing `near(exit)` when the leg starts on top here, else the other anchor). Same function as the
  surrogate.

### 3.6 Reporting (README, drawings, log)
- Per routed end, `routing.turns_back(o, facing, jack_pt, points, window)`: true when the cable's first top stretch from that exit
  crosses the jack's axis half-line in front of the head, at most `depth + 2 x diameter + one grid cell` from the jack face.
  Cables get `turn_a` / `turn_b` (bool; DC legs `turn_b`, and `turn_a` for a pedal-start leg).
- README cable table, Exits column: `right (turned back)` where set. The DC cables table gets the same per plug. Add one sentence
  to the routing notes: "a plug that points away from where its cable goes has the cable turned back round the front of its
  head (never across it); the length includes the turn".
- Build log: `routing: N plugs turn their cable back (signal S3, S7; power P4)` (only when N > 0). Not a warning: it is a valid
  set-up.
- `routing.svg` / `power.svg`: no change needed (the lead + routed path already show the turn). Optional: a small arc marker at
  the turn (decision 5, recommended no).
- `exit_how(o)` (clearance and collision messages) gains ", cable turned back" when known (after routing only).

### 3.7 Layout surrogate (`layout.py`)
- New pure helper `routing.around_own_plug(p, q, rects, radius, facing, jack_pt)`: if the segment p -> q enters the convex hull
  of the option's head + barrel rects grown by `radius`, return the shortest path p -> front hull vertices -> q (a tiny
  visibility graph over the hull vertices in front of the jack face, at most 8 nodes; the vertices behind the face lie in the
  pedal and are never used); else |p q|. Returns the extra over |p q| (>= 0). Bounding-box pre-check first: it runs inside the
  search.
- Signal combos in `Model.score` phase A: `span = octile(pa, pb) + wd * detour(pa, pb, grown) + extra_a + extra_b`, where
  `extra_a = around_own_plug(pa, pb, keepout of oa)` and likewise for b (0 for down options and fixed boxes). The extra goes
  into `length`, so it reaches the ranking (`combos`) and the signal term. Precompute the keep-out rects per option in `_opt`
  (relative to the pedal centre, shifted like `rects`).
- DC: `_dc_length` adds `around_own_plug(here, target)` with the same target as the build's `dc_estimator` (3.5), so
  `_dc_rel` / `_resolve` pick the same sides.
- No new weight. The extra is cable length, priced by `signal` (1/mm) and `power` (0.1/mm) as any length.

## 4. What does not change
`design.plug_geometry`, footprints, `blocked_parts`, `collision_count`, passes under, plug zones, `in_area`, down rules, the plug
limit for OTHER cables (`max_over_plug`), cable ids, `proposal_inputs_sha1` (code is no input; the owner reruns proposals after
the merge).

## 5. Tests (pytest, hand-computed; gig cases on `tests/fixtures/guitar-gig/`)
New file `tests/test_u_turn.py` unless noted.
1. `keepout_rects`: right-angle side option = head + barrel only; down option = []; straight = head; fixed box = [].
2. `around_own_plug`: the EB example = 56.5527 (extra 4.0527 over 52.5); the DC example = 56.0302; a target on the plug's own side
   (e.g. q = (3.2, 40)) -> extra 0; a segment that clears the hull -> 0; never uses vertices behind the jack face.
3. `astar` / `plain_search` with `forbid`: a 2 mm grid scene where the straight path crosses a forbidden block -> the path goes
   round; the same start / goal without forbid is memoised separately (two keys).
4. `route_project`, hand-made two-pedal scene (as in tests/test_routing.py): jack facing right, the direct side blocked by a
   neighbour 10 mm away, target behind. The chosen side is the other one, `turn_b` is True, no routed segment comes closer than
   radius - 1e-6 to the own head / barrel, and `min_mm` = 79.05 within one grid cell (2 mm).
5. The same scene with the direct side free -> direct side, `turn_*` False, `min_mm` unchanged from today (regression).
6. "Worse, not blocked": the direct side is free, but its exit leads into a dead end that costs a long detour -> the other side
   with a turn wins on length.
7. Lazy demotion: a 6.5 mm gap scene like practice S3 (both jacks in the gap) -> no "routed" cable crosses its own plug. The
   result is either another combination or a squeezed / unroutable finding, never a path through the head.
8. DC: `route_power` scene with a pedal plug whose direct side is blocked -> the leg goes round its own plug (`turn_b`), and
   `refine_dc_sides` respects the keep-out (tests/test_power_plug_side.py style).
9. Serial daisy: a leg that starts at a pedal plug keeps out of that plug too (tests/test_daisy_chains.py style).
10. Gig fixture (test_layout.py / test_routing.py): no routed signal or DC segment crosses its own plug (the section 2 scan as an
    assertion). Update every gig-fixture expectation that moves (lengths, sides) deliberately, with a comment naming this
    feature; the fixture files themselves stay frozen.
11. Surrogate agreement (tests/test_layout.py): on the EB scene the surrogate's signal length is within 3 mm of the build's
    `min_mm`; the existing gig agreement tests (plug sides, blocked, collisions, passes) still agree.
12. README: the Exits cell reads `right (turned back)` for scene 4 (tests/test_check.py style).

## 6. Implementation steps (each a self-contained handover for a Sonnet agent, one branch `feat/u-turn-plugs`)
Write each as `docs/handovers/u-turn-<n>.md`, with the relevant lines of sections 3 and 5 copied in.
1. **Geometry helpers (no behaviour change)**: `routing.keepout_rects`, `routing.around_own_plug`, `routing.turns_back` +
   tests 1, 2. Files: scripts/routing.py, tests/test_u_turn.py.
2. **Search with forbid**: `astar` / `astar_layers` / `_search` / `plain_search` / memo key / `route_all` nets with forbid
   (default empty = today's results bit for bit) + test 3. The full suite must pass unchanged.
3. **Signal keep-out**: `route_project` (`o["keep"]`, nets, lazy demotion in `choose_signal`), `path_geometry` / `smooth` own
   rects, `lanes` check, `turn_a` / `turn_b` + tests 4-7, 10 (signal part). Update moved expectations deliberately and list them
   in the report. Record the build time of all projects before and after (`time uv run pb build`).
4. **DC keep-out**: `route_power`, `refine_dc_sides`, `dc_estimator` extra, DC `turn_*` + tests 8, 9, 10 (DC part).
5. **Surrogate**: `layout.Model` (`_opt` keep-out, signal combos, `_dc_length`) + test 11; check the search speed (the gig
   `--score` and one `propose_layout.py guitar-gig --seed 1` before / after).
6. **Reporting + docs**: README Exits column and DC table, routing note, build log line, `exit_how`, test 12; CLAUDE.md (the
   own-plug rule in "Cable routing" and "Plug orientation", the U-turn sentence); TODO 3.2 ticked; then `uv run pb build` for all
   projects (the owner reviews the practice board diff).
Then a code review (Sonnet, `general-purpose`), then merge after the owner's OK.

## 7. Risks
- **Practice board**: 8 of its 11 side-exit signal ends cross their own plug today. With the keep-out some cables may change
  sides, get longer, become squeezed, or (in 6.5 mm gaps full of plugs) become unroutable. That is the honest result for "fit",
  but it will look like a regression. Decision 1 covers it; step 3 reports the before / after per project.
- **Run time**: per-combination forbid sets lower memo sharing between combinations. There are more A* runs in `choose_signal`
  (lazy demotion) and in the power refinement. Measure in steps 3-5 and keep the test suite near 150 s.
- **Grid vs continuous**: the routed turn is on a 2 mm grid, then smoothed. Its length differs from the hand value by up to about
  a cell (tests use a 2 mm tolerance). Keep-out cells use the wall growth, so a one-cable gap in front of the head stays open.
- **Surrogate drift**: the hull path ignores neighbouring pedals near the turn (as `detour` is rough elsewhere). The agreement
  tests watch the plug choices, not exact lengths.
- **Lanes**: a lane shift could draw a cable over its own plug again (drawing only); the `valid` check prevents it.
- **Stale proposals**: existing `proposals/meta.json` were scored without the turn. Their README section is not marked stale
  (the code is no input). Note it in the merge message, and the owner reruns `propose_layout.py`.

## 8. Out of scope
Bend radius, the cable climbing over OTHER plugs (still allowed up to `max_over_plug`, with no length for the climb), twisting a
flat ribbon, any 3D model, guitar / amp cables.

## 9. Decisions for the owner (recommended default first)
1. **May a cable cross back over its own plug (fold over the top)?** Recommended: **no**: a hard keep-out of its own head and
   barrel, for signal and DC alike. This is the safer reading of "guarantee fit" and fixes the uncounted fold (8 ends on the
   practice board). Alternative: allow it, but count it like a crossing of another plug (`max_over_plug`) with a climb
   allowance of 2 x `head_thickness_mm` added to `min_mm`.
2. **Routed turn (B) or a fixed U-turn option (A)?** Recommended: **B** (less code, no new exit values, no duplicate options,
   the shortest physical turn by construction). A only if you want the turn as a fixed, labelled plug part.
3. **Turn geometry**: recommended **no bend radius**: the cable passes one radius from the head front, as every cable bends
   alike. Alternative: a minimum turn spacing (a bend radius) in catalog/cables.json per type.
4. **Report**: recommended **info only**: "(turned back)" in the README Exits column and a build log line, no warning.
   Alternative: a warning per turned plug (strict_routing makes it an error).
5. **Drawing marker** at the turn: recommended **none** (the path shows it). Alternative: a small arc marker plus a legend entry.

## 10. Design A in brief (not recommended, for reference)
Exits `u_left` / `u_right` = the cable ends up on that side and the plug points the other way (README: "plug points right, cable
turns back to the left"). Footprint: head, barrel and run on the pointing side X as today, plus `turn` (along the facing from
`off - d/2` to `R + d/2` at lateral `L = reach + run`) and `return` (at `R` along the facing, lateral from `L` back to
`-(width/2 + d)`), where `R = max(off + d, off + barrel/2 + d/2, depth + d/2)`. Exit = (R, -(width/2 + d)). `measure_mm =
|off - depth/2| + L + (R - off) + (L + width/2 + d)`; Ernie Ball: R 8.15, measure 59.8, and with the example target 80.55 in
total (B: 79.05). Offered for every right-angle side option unless an override fixes a plain side. Ranked after the plain sides
on ties. It needs the B keep-out anyway, plus a keep-out of the strip in front of the head for plain options, or it never wins.
The surrogate gets it for free through `end_options`.

## 11. What the keep-out attempt measured (2026-11-13, reverted: kept for the record)
Steps 1 and 2 (helpers, search with `forbid`) and an uncommitted step 3 (own-plug keep-out in `route_project`) ran on the live projects
before the owner's override. Cables with a keep-out: bass S3 +0.4 mm; guitar-gig none; guitar-practice S1 +7.7, S2 +2.6, S3 +189 (the 6.5 mm
gap: the cable went round the whole Duke of Tone, 275 mm; with the gap plugs filling the gap the cable could not pass), S4 +28, S5 +1.9,
S6 +43 mm; the gig fixture S11 +4.2, S15 +124 mm. Build times were unchanged (0.2 s per project, fixture 4 s). The owner's rule (a cable
passes under its own plug) makes all of those lengths the shorter ones they were; only the report is new.
