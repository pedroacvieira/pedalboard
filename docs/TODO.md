# To do

Hand-written backlog (not generated). Build-derived findings (warnings, data to verify, shopping list) live in the
generated `README.md`; this file holds the work and the questions for the owner. Tick items off or move them to
"Done" when finished, and keep `CLAUDE.md` current when a decision changes.

Sections: 1 owner input (measurements, decisions, checks) · 2 gig board · 3 next features (in order) · 4 later /
ideas · 5 data · 6 done.

## 1. Owner input

### Measurements (each replaces an estimate that feeds every cable length / clearance check)
- [ ] **Jack height** above the deck (`cables.jack_height_mm`, 12, estimate): the length of a plug pointing down.
- [ ] **Owner's own DC plugs** (right-angle and straight): `dc_ra_owner_baseline` / `dc_straight_owner_baseline` are a
      random cable's sizes (12 x 8, body reach 19 / 34 x 10), likely bigger than the owner's.
- [ ] **Fender Pro Medium deck**: thickness (+ the bend of a ribbon through a slot) for `hole_transit_mm` (15,
      estimate) and the board height at the back edge for `edge_transit_mm` (30 = 2 x hole transit, estimate); put
      them in `catalog/boards.json` (`fender-pro-medium.png`).
- [ ] **Ernie Ball flat patch plug**: depth from the jack face (catalog 6.4 mm, maker) and the length from the jack axis
      to where the ribbon leaves (catalog 19 mm, estimate) -> `catalog/cables.json` `ernie_ball_flat_patch_ra` and its
      `verified` list.
- [ ] **Ojai DC plug** (a random DC cable was measured by the owner 2026-10-28: right-angle 12 out / 19 bend side / 4
      other side, straight 34 out / 5 radius; used in `docs/plans/plug-orientation.md`; the Ojai's own plug is still open): depth from the jack face, width, height, and the cable thickness. Today
      `dc_ra_2_1_low_profile` (RockBoard 20 x 11 x 10.5 mm, mapped by interpretation, ~11 mm deep) is deeper than the
      Ernie Ball plug, against the owner's expectation; RockBoard's own page also gives 5/16 in height.
- [ ] Confirm the power-jack fallback box `jacks.power_clearance` (5.5 x 5.5 mm, estimate; only used without a
      `cables.power_type`).

### Decisions
- [ ] Power plug side: when neither side is blocked the tool reports "left". Does the side matter?
- [ ] Power routes on top: P2 / P12 / P17 run 111-140 mm on top of the gig board (on-top mm cost 3 x,
      `power_routing.top_cost`). Acceptable, or tune it?
- [ ] Footswitch spacing: do the proposals spread the switches enough? Else tune `footswitches.comfort_mm` (100) or
      `layout.weights.footswitch` (2).
- [ ] Layout proposals: are the moves acceptable (else tune `layout.weights` / `max_move_mm`)? Try
      `--max-change rearrange` (bigger moves, swaps, rotations) once and judge it.
- [ ] Answer the open questions of `docs/plans/pedal-position.md`.

### Checks by eye
- [ ] `projects/guitar-gig/routing.svg` and `power.svg` (and `uv run scripts/build.py --images` for
      `routing.local.svg`): label placement is basic (some S# labels on short segments or overlapping in lanes).
- [ ] Pedal editor GUI: footswitch mode, J/F, the no-footswitch box, the four-way switch type.
- [ ] Duo 2.1 holes (practice / bass have no layout yet): `uv run scripts/board_editor.py bass`.

### Later, when it happens
- [ ] Polarity: every pedal and supply is recorded center-negative (owner); add the real value when a
      center-positive pedal arrives.

## 2. Gig board
- [ ] The owner's layout has 5 blocked plugs (monk.out / monk.power by the Belle Epoch, danelectro_3699.out by the
      Retrovibe, red_muck / analog_chorus DC heads) and 7 plug collisions (mostly a patch plug vs the DC plug on the
      same pedal). All three layout proposals reach 0 / 0 (2026-10-28): load `projects/guitar-gig/proposals/1.json` in
      Pedal Playground (Load from File) and re-save `projects/guitar-gig/playground_design.json`, or move by hand.
- Current state (2026-10-28, measured DC plug): signal 2624 mm, DC 3355 mm; 6 plugs point down into slots (Tumnus,
  S15 / S16 ends, P1, P11, P13); one owner-drawn edge crossing at the back (handle area), unused.

## 3. Next features (one branch each: plan in `docs/plans/<branch>.md` + owner decisions, then handovers)
Order (owner, 2026-10-29): pedal preferences -> web UI. Next: `feat/pedal-preferences` (no plan file yet: write
`docs/plans/pedal-preferences.md` first, owner decisions, then handovers).
Project focus (owner, 2026-10-29): be able to assemble the board and guarantee that pedals, plugs and cables FIT;
model as many physical aspects as possible; every cable gets a precise minimum required length, from which the owner
picks a long-enough cable (no tracking of owned cables). Lengths are optimised so no huge cables are needed.

### 3.1 `feat/pedal-preferences`: one preference profile per pedal in a project
Every per-pedal wish in one place, editable with values, drop-downs and toggles (the tab comes with the web UI).
- [ ] Data: `project.json` `pedals.<id>`: position (left/right/front/back/any + strength), pin, allowed rotations,
      order wishes (before/after X with priority -> today's rules), power wishes (own output, preferred supply/port,
      voltage), footswitch topper, access override.
- [ ] Migrate today's scattered knobs (`layout.access.pedals`, `layout.pins`, `layout.rotations.<id>`, per-pedal rules,
      power output choice), old keys still read (or a one-off migration script).
- [ ] Build: validate the profile, README table "Preferences" (asked for, met or not in the owner's layout and in
      each proposal); the layout search and `power.assign` read it.
- [ ] Until the web UI: edit project.json by hand (documented schema).

### 3.2 `feat/web-ui`: one local web app with tabs (last: wraps the stable features)
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
- Power-cable inventory (owned DC cable models, fit, automatic style / cable choice): PARKED by the owner (2026-10-29),
  plan kept in `docs/plans/power-cable-inventory.md`. DC cables are cheap and easy to get; not relevant for now.
- DIY patch cables: when the owner builds a board with DIY patch cables, cut lengths (plug allowances on top of the
  precise `min_mm`) may be wanted.
- [ ] Layouts for `guitar-practice` and `bass` (`playground_design.json`), so their cables and clearance are checked.
      The Harley Benton ISO-5 Pro has no Pedal Playground entry (`playground_title`), so it never appears in a layout
      and has no outline. Practice board: out of scope for now (owner, 2026-10-22); its Ojai R30 is still to buy.
- [ ] Guitar -> board and board -> amp cables (`fender_pro_instrument_ra`, role instrument): need guitar and amp
      positions (or board-edge exit points) in the project.
- [ ] Layout surrogate vs router: the signal estimate (octile + detour around crossed pedals) misjudges some routes and
      overestimates the smoothed router by up to ~8 % per cable; an any-angle estimate in `layout.py` (finalists are
      checked with the router, so proposals are safe, but the search may miss better ones).
- [ ] U-turn plugs: when a right-angle plug cannot point to the side its cable has to go, point it the other way and
      turn the cable back; longer minimum length, the turned cable occupies both sides; the router considers it when
      the direct side is blocked or worse.
- [ ] Many cables side by side (5-10) should add length (lane offsets); ignored for now (owner).
- [ ] Under-board fit (supply height vs space under the deck) is not checked (owner decision); a later branch if needed.
- [ ] The saturated single-hole routing case (two cables forced through one one-cell hole) never converges and runs
      all `cables.iterations` rounds; no provably safe early stop found (feat/routing-speed review).

- [ ] Toppers and pedal height (owner, 2026-10-27): a low pedal at the back of the board is harder to reach, a tall pedal
      is naturally easier to reach and may not need a topper at all. Needs a height per pedal (enclosure height, and
      the switch height above the board) and a reach / position model (back vs front row); then the spacing model
      (`topper_bonus_mm`) and the suggestions weigh a switch by its height and position (a tall pedal's switch gets a
      bonus of its own, a low one at the back a penalty).

## 5. Data
- [ ] Items in the generated README's "Data to verify" (power specs, Reticon, Protein, version assumptions).

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
- `feat/daisy-chains` (2026-10-27): serial / forked per output, physical DC cables (C#) and "DC cables to buy";
  gig unchanged (all serial).
- `feat/footswitch-toppers` (2026-10-27, defaults 2026-10-28): `footswitches.toppers`, effective distance (+4.5 mm per
  topper = its added height), cap 5 per board, post-layout suggestions (gig: ratsbane, belle_epoch, fulldrive_2 boost,
  monk tap, protein blue: crowding 184 -> 157).
- `feat/plug-orientation` (2026-10-28, `docs/plans/plug-orientation.md`): plug-to-plug collisions, right-angle plugs
  pointing down into a hole (always when available), several DC plug types per project (`cables.power_types`, one
  pedal-end type per serial cable), owner-measured DC plugs, the layout surrogate mirrors all three.
- Owner data: every project pedal's footswitches placed (2026-10-23); footswitch spacing is comfort, no minimum;
  gig chain: chorus before the Reticon (2026-10-27).
