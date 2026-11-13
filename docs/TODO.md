# To do

Hand-written backlog (not generated). Build-derived findings (warnings, data to verify, shopping list) live in the
generated `README.md`; this file holds the work and the questions for the owner. Tick items off or move them to
"Done" when finished, and keep `CLAUDE.md` current when a decision changes.

Sections: 1 owner input (measurements, decisions, checks) · 2 boards · 3 next features (in order) · 4 later /
ideas · 5 data · 6 done.

## 1. Owner input

### Measurements (each replaces an estimate that feeds every cable length / clearance check)
- [ ] **Jack height** above the deck (`cables.jack_height_mm`, 12, estimate): the length of a plug pointing down.
- [ ] **Owner's own DC plugs** (right-angle and straight): `dc_ra_owner_baseline` / `dc_straight_owner_baseline` are a
      random cable's sizes (12 x 8, body reach 19, exit offset 8.4 = 70 % rule of thumb / 34 x 10), likely bigger than
      the owner's.
- [ ] **Ojai DC plug**: depth from the jack face, width, height, cable thickness. Today `dc_ra_2_1_low_profile`
      (RockBoard 20 x 11 x 10.5 mm, mapped by interpretation, ~11 mm deep) is deeper than the Ernie Ball plug, against
      the owner's expectation; RockBoard's own page also gives 5/16 in height.
- [ ] **Fender Pro Medium deck**: thickness (+ the bend of a ribbon through a slot) for `hole_transit_mm` (15,
      estimate) and the board height at the back edge for `edge_transit_mm` (30 = 2 x hole transit, estimate); put
      them in `catalog/boards.json` (`fender-pro-medium.png`). Same for the Duo 2.1 (`rockboard-duo-21.png`).
- [ ] **Expression cable's straight plug** (board side): head length and width, cable thickness -> `exp_trs_straight_baseline`
      (40 x 12 mm, 6 mm cable: placeholder).
- [ ] **Ernie Ball flat patch plug**: depth from the jack face (catalog 6.4 mm, maker) and the length from the jack axis
      to where the ribbon leaves (catalog 19 mm, estimate) -> `catalog/cables.json` `ernie_ball_flat_patch_ra` and its
      `verified` list.
- [ ] Confirm the power-jack fallback box `jacks.power_clearance` (5.5 x 5.5 mm, estimate; only used without a
      `cables.power_type`).

### Decisions
- [ ] Load a proposal into Pedal Playground 2.0 (parked, owner 2026-11-02): the site has no file load (a hidden importer,
      no button) and no save to file. It reads `localStorage["pp:playground:v3"]` on start (not logged in), so a
      proposal could be loaded from the console (untested); or write it into the owner's account as a new playground
      (needs the owner's login). Until then: move the pedals by hand (README move table: dx + = right, dy + = towards the
      front; proposal SVG).

### Checks by eye
- [ ] Duo 2.1 holes (practice now has a layout): `uv run pb board-editor guitar-practice`; also its usable area
      (`bounds`, key B), if the rounded edges need one.

### Later, when it happens
- [ ] Polarity: every pedal and supply is recorded center-negative (owner); add the real value when a
      center-positive pedal arrives.

## 2. Boards

### Gig (layout 2026-11-06 13:47; Tumnus at the end of the drive section, Retrovibe before Phase 95)
- State (2026-11-06): 17 pedals, signal 2713 mm, DC 3388 mm over 10 cables, crowding 170.7, 0 blocked plugs.
  Exp jacks of Retrovibe, Belle Epoch, DD-200 in `jacks.extra_used` (driven by the BOSS EV-30). One warning: the Belle
  Epoch's Exp box collides with its own output plug (4.3 mm; jacks ~22 mm apart, the flat plug reaches 19 mm sideways).
- [ ] **Belle Epoch Exp vs output plug**: the Exp jacks now take a straight plug (`exp_trs_straight_baseline`, 40 x 12 mm
      placeholder, owner 2026-11-06); the Belle's output plug's cable run still crosses it (3.5 mm). Fix: a slimmer angled plug
      on S16, or measure the Ernie Ball plug and the expression cable's straight plug first.
- EV-30 = a floor device (2026-11-13): `floor` in project.json drives the three Exp jacks; not on the board.
- [ ] Proposals (rerun 2026-11-13, README "Layout proposals"): all three move the Belle Epoch 4.5 mm (clears the Exp collision:
      0 collisions) and cut crowding 171 -> 146..163; #1 moves Beano, Phase 95, Protein, Belle (signal +25 mm, crowding 146),
      #2 six pedals (signal -15 mm, crowding 147). Owner picks one (or not), moves the pedals in Pedal Playground, fetch.
- Tumnus Deluxe body (checked 2026-11-13): the 5 mm right inset is correct: the image shows the side-mounted buffered / true
  bypass switch sticking out on the right (60 px of 860 at ~63 % of the height); every jack is on the top edge.
- [ ] Toppers: left automatic for now (owner, 2026-11-04); the owner picks them later (`footswitches.toppers`). Suggestions
      are bypass switches only; a tap switch in the middle of the board (the Monk's) only by hand.

### Practice (layout 2026-11-09, owned gear only)
- State (2026-11-13): PolyTune 2 Mini -> Octahive -> Tube Screamer Mini -> Duke of Tone -> E-Lady -> Carbon Copy -> Ditto on
  the Duo 2.1 (the bass board is the XPND now) and the ISO-5 Pro (also on the bass board: the "shared" warning stays until a
  second supply); Cry Baby GCB95F as a floor device; all 6 signal (480 mm) and 5 DC cables (1402 mm) routed. Two warnings
  (2.6 mm each): the Octahive reaches into the PolyTune's output plug; Carbon Copy out collides with Ditto in.
- Supply under the board (owner, 2026-11-13: that is what "behind the board" meant).

### Bass (layout 2026-11-09: D'Addario XPND 1 + extension, one composed board)
- State: no tuner (owner, 2026-11-09); chain Hyper Luminal -> Bass Synth -> Bass Envelope Filter -> Bass Big Muff 2 -> VT Bass DI
  (the Envelope Filter and the Synth not owned; the Chorus Deluxe off the board for now, owner 2026-11-13).
- [ ] Board: the board editor edits only the first piece (`board.json` `pieces` by hand for the other); check the XPND
      holes by eye.

## 3. Next features (one branch each: plan in `docs/plans/<branch>.md` + owner decisions, then handovers)
Order (owner, 2026-10-29; U-turn plugs added 2026-11-05): pedal preferences -> U-turn plugs -> web UI (last: it wraps
the stable features).
Project focus (owner, 2026-10-29): be able to assemble the board and guarantee that pedals, plugs and cables FIT;
model as many physical aspects as possible; every cable gets a precise minimum required length, from which the owner
picks a long-enough cable (no tracking of owned cables). Lengths are optimised so no huge cables are needed.

### 3.1 `feat/pedal-preferences`: one preference profile per pedal in a project
Plan `docs/plans/pedal-preferences.md` (owner decisions D1-D12: the recommended defaults); implemented on the branch `feat/pedal-preferences`
(waiting for the code review and the merge; the live project.json files are NOT migrated yet).
Every per-pedal wish in one place, editable with values, drop-downs and toggles (the tab comes with the web UI).
- [x] Data: `project.json` `pedals.<id>`: position (left/right/front/back/any + strength), pin, allowed rotations,
      order wishes (before/after X with priority -> today's rules), power wishes (own output, preferred supply/port,
      voltage), footswitch topper, note (the access override is `position.depth`).
- [x] Migrate today's scattered knobs (`layout.access.pedals`, `layout.pins`, `layout.rotations.<id>`, per-pedal rules,
      toppers): old keys still read AND the one-off script `uv run pb migrate-preferences <project> [--dry-run]`
      (the hand power wiring stays in `power.supplies[].outputs[]`). Owner: run it per project when ready.
- [x] Build: validate the profile, README table "Preferences" (asked for, met or not in the owner's layout and in
      each proposal); the layout search and `power.assign` read it. Rerun the proposals of each board to fill the proposal columns.
- [x] Until the web UI: edit project.json by hand (documented schema, CLAUDE.md and the root README).

### 3.2 `feat/u-turn-plugs`: a right-angle plug that turns its cable back
Plan `docs/plans/u-turn-plugs.md`; owner decision 2026-11-13: the cable MAY cross its own plug (one thin cable passes under it).
- [x] A right-angle plug that cannot point to the side its cable goes to: the router already picks sides by fit, then length; the
      turned cable crosses its own plug, which adds no length. Now reported (information only): `under_own_a` / `under_own_b`, the
      README Exits column ("right (passes under its own plug)"), a build log line. Signal and DC plugs; the layout surrogate has no
      keep-out and so agrees. Needs the owner's review of the practice board: all 6 signal cables pass under a plug of their own.
- Done 2026-11-13 (merged; proposals rerun on all three boards after the merge and the preferences migration).

### 3.3 `feat/web-ui`: one local web app with tabs
Replaces the Tkinter editors and the README-only views with a local browser app.
- Owner (2026-10-23): new dependencies are fine with a reason each; Python ones via uv, anything else (npm, system
  packages) only after asking.
- [ ] Stack (decide in the plan): a Python web framework via uv (FastAPI/Starlette or Flask) serving a JSON API over
      the existing functions (`build.validate`, the save functions, `propose_layout`); front end plain JS/SVG first.
      Local only.
- [ ] Tabs: Board (layout, findings), Pedal editor (jacks, footswitches, toppers), Board editor (holes, edge segments),
      Signal routing, Power routing, Preferences, Proposals (compare, load into Pedal Playground).
- [ ] Writes only through the existing save functions (one-item-per-line JSON, same validation); the build stays the
      single source of findings; images still fetched server-side into `.cache/`.
- [ ] Keep the CLI working; retire the Tkinter editors once the web ones cover them.
- Open: drag pedals in the Board tab and save as a new layout file (never `playground_design.json` itself)?

## 4. Later / ideas
- [ ] **Expression cables** (owner, 2026-11-06): route and measure the TRS cables from the EV-30 (2 outputs) to the Exp
      jacks of Retrovibe, Belle Epoch, DD-200 (one or two at a time: the owner re-patches; so maybe one cable per target).
- [ ] **Jack / footswitch templates per enclosure family** (owner, 2026-10-29): pedals of one brand and one enclosure
      size usually share their in / out / power jack and footswitch positions (exceptions exist, so a template is a
      proposal, never verified data). Families: EHX Pico / Nano / normal / double, MXR mini / normal / double, Boss
      compact (all single pedals), 200-series and 500-series, also JHS, JAM, Wampler. Owner's examples: Wampler Mini Ego
      and Ratsbane, Jam Red Muck and Monk, TC PolyTune 2 / 3 and Ditto look alike.
      - Data: `catalog/templates.json` (or similar): per family the jacks and footswitches in image fractions (as
        `catalog/jacks.json` / `footswitches.json`) and how to recognise members (brand + Pedal Playground size,
        within a tolerance); a pedal may name its family by hand.
      - Use: for a pedal without jack / footswitch data, propose the template (pedal editor: "apply template", then the
        owner checks and saves; `--list-missing` names the matching template); never use unconfirmed template data
        silently in the build (or only as a marked estimate: decide in the plan).
      - Detection help: signal jacks often show as bumps on the outline (`catalog/outlines.json`): snap or suggest jack
        positions from them.
      - Footswitch shape: Boss compact pedals have one big rectangular pedal-style switch, not a small round one: add an
        optional rectangular footswitch (`shape` round|rect, width x height) to `catalog/footswitches.json`, the
        editor, the spacing model (distance between shapes, not centres) and the drawing.
      - Test cases: boss_dd8 (Boss compact: template + rectangular switch), boss_dd200 (200-series, placed by the owner),
        ehx_pico_pog / ehx_pico_pitch_fork (EHX Pico pair), jhs_angry_charlie / jhs_the_violet (JHS).
- [ ] Toppers and pedal height (owner, 2026-10-27): a low pedal at the back of the board is harder to reach, a tall pedal
      is naturally easier to reach and may not need a topper at all. Needs a height per pedal (enclosure height, and
      the switch height above the board) and a reach / position model (back vs front row); then the spacing model
      (`topper_bonus_mm`) and the suggestions weigh a switch by its height and position.
- [ ] Guitar -> board and board -> amp cables (`fender_pro_instrument_ra`, role instrument): need guitar and amp
      positions (or board-edge exit points) in the project.
- [ ] Layout search: a penalty for an infeasible DC plug exit in the surrogate (today the build's check rejects such a
      finalist, so the search spends finalists on them).
- [ ] Layout surrogate vs router: the signal estimate (octile + detour around crossed pedals) overestimates the smoothed
      router by up to ~8 % per cable; an any-angle estimate in `layout.py` (finalists are checked with the router, so
      proposals are safe, but the search may miss better ones). The surrogate cannot see the routed DC side refinement
      either (gig fixture: 44 of 49 exits agree).
- [ ] Many cables side by side (5-10) should add length (lane offsets); ignored for now (owner).
- [ ] Under-board fit (supply height vs space under the deck) is not checked (owner decision); a later branch if needed.
- [ ] The saturated single-hole routing case (two cables forced through one one-cell hole) never converges and runs
      all `cables.iterations` rounds; no provably safe early stop found (feat/routing-speed review).
- Power-cable inventory (owned DC cable models, fit, automatic style / cable choice): PARKED by the owner (2026-10-29),
  plan kept in `docs/plans/power-cable-inventory.md`. DC cables are cheap and easy to get.
- DIY patch cables: when the owner builds a board with DIY patch cables, cut lengths (plug allowances on top of the
  precise `min_mm`) may be wanted.

## 5. Data
- [ ] Candidate pedals (catalog only, not in a project): boss_dd8, jhs_angry_charlie (V3), jhs_the_violet, ehx_pico_pog,
      ehx_pico_pitch_fork. Unverified: DD-8 voltage range (9 V only assumed), DD-200 voltage (9 V, Thomann); Angry
      Charlie 9-18 V (2016 JHS manual); every Violet figure (retailers only). Both BOSS delays are center-negative
      (owner, 2026-11-05). Before moving one into a project: jacks and footswitches with `uv run pb pedal-editor <id>`.
- [ ] Items in the generated READMEs' "Data to verify" (power specs, Reticon, Protein, version assumptions).
- [ ] Bass shopping list: MXR Bass Synth (`owned: false`); mark it owned if it is.

## 6. Done (merged into main; details in the plans and handovers)
- `feat/jack-tracking`, `feat/cable-routing` (2026-10-22): jack data, clearance, cable model and grid router.
- `feat/pedal-position` (2026-10-23, `docs/plans/pedal-position.md`): layout injection, footswitches and spacing,
  `pedal_editor.py`, layout search and proposals, power assignment; uv project.
- `feat/routing-view` (2026-10-23, `docs/plans/routing-view.md`): plug limit, smoothing, lanes, `routing.svg`
  (1:1 print, legend), `routing.local.svg` with images, shared `svgdraw.py`.
- `feat/pedal-outlines` (2026-10-26, `docs/plans/pedal-outlines.md`): real pedal shapes for routing and clearance
  (gig signal 2512 -> 2400 mm).
- `feat/supply-placement` (2026-10-27, `docs/plans/supply-placement.md`): board holes (`boards.py`, board editor,
  owner's gig corrections), per-supply placement, signal cables under the board, routed power cables, `power.svg`,
  edge crossings as owner-drawn segments, `cables.route_in_front`, on-board supplies movable in the search.
- `feat/routing-speed` (2026-10-27, results identical): gig check 1.2 -> 0.7 s, layout search ~47 -> 15 s, tests
  73 -> 30 s; side-choice searches reused by `route_all`.
- `feat/daisy-chains` (2026-10-27): serial / forked per output, physical DC cables and "DC cables to buy".
- `feat/footswitch-toppers` (2026-10-27, defaults 2026-10-28): `footswitches.toppers`, effective distance (+4.5 mm per
  topper = its added height), cap 5 per board, post-layout suggestions; bypass switches only (owner, 2026-11-04).
- `feat/plug-orientation` (2026-10-28, `docs/plans/plug-orientation.md`): plug-to-plug collisions, right-angle plugs
  pointing down into a hole (always when available), several DC plug types per project (`cables.power_types`),
  owner-measured DC plugs, the layout surrogate mirrors all three.
- `feat/cable-ids` (2026-10-29, `docs/plans/cable-ids.md`): power cables are P#, daisy-chain legs P#.1, P#.2...;
  unknown `cables.overrides` keys are errors; "DC cables to buy" lists each leg's min plug spacing.
- `feat/board-bounds` (2026-10-29, `docs/plans/board-bounds.md`): usable board area per project (`board.json` `bounds`,
  board editor key B); pedals and on-board supplies must sit inside; gig bounds back 11.0 mm, front 8.5 mm.
- `feat/pedal-body` (2026-11-02, `docs/plans/pedal-body.md`): the usable board area holds a pedal's BODY, not its jacks;
  every overhanging plug footprint is routing area (`routing.plug_zones`).
- `fix/image-download` (2026-10-29): images and the database come from Pedal Playground's catalog.json.
- `fix/cable-area` (2026-11-02): the bounds limit the pedals only; the routing area is the board + margin again (fixed
  the unrouted DC cables of fix proposals); unrouted DC cables count as a routing problem in the proposal gate.
- `feat/power-plug-side` (2026-11-03, `docs/plans/power-plug-side.md`): a DC plug takes the side with the shorter cable
  (estimate + routed refinement, `TIE_MM` / `SWITCH_MM` 5).
- `feat/dc-under-signal` (2026-11-03): a right-angle DC plug may pass under ONE same-facing signal plug ("plug it
  diagonally", not a collision); DC exit offset 8.4 mm (70 % of the depth, rule of thumb); a plug past the board edge
  gets a plug zone. Diagonal plugging and plug height are not modelled.
- Gig (2026-11-04): DD-200 replaces the DD-8 and comes last, after the Tumnus (its looper records the whole chain);
  Pico Pitch Fork and the parked Carbon Copy removed; every Ojai output in use (Analog Chorus alone on psu1 SW_B, DC
  3649 -> 3322 mm). Proposals: unmoved pedals keep their exact position (the whole-px snap had rejected every
  candidate); README says to move the pedals by hand.
- `feat/guitar-practice-layout` (2026-11-04): practice rig with owned gear only, first layout, the bass rig's Duo 2.1
  and ISO-5 Pro (Pedal Playground stand-in image: ISO-1AC Pro, outputs marked by the owner).
- Owner decisions kept: footswitch spacing is comfort, no minimum (`comfort_mm` 100, weight 2); power routes on top up to
  150 mm are fine (`top_cost` 3); `routing.svg` labels and the pedal editor's footswitch mode are ok for now.
