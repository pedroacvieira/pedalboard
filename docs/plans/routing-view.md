# Plan: `feat/routing-view`: a signal routing picture to wire the board from

Status: plan (2026-10-23) with the owner's decisions. Branch `feat/routing-view` from `main`.

## 0. Starting point
- `routing.route_all` returns 8-connected grid-cell paths (2 mm cells) per signal cable; the stacking limit
  (`cables.max_stack`, 2) is negotiated by rip-up-and-reroute. Plug heads are clearance-checked against pedals but are
  NOT obstacles or capacity limits for other cables today.
- `routing.svg()` draws the cell paths as raw polylines (staircases, shared cells on top of each other) into
  `cables.svg` (`build.py`) and `proposals/<n>.svg` (`propose_layout.py`).
- Owner (2026-10-23): worst today = cables drawn in the same place where they could run in parallel, and hard angles
  everywhere; a cable should be a straight line between two necessary corners.

## Owner decisions (2026-10-23)
1. Any-angle segments (not only 0/45/90).
2. Lane offsets do not count towards the minimum length (centreline length). Later: many cables side by side (5-10)
   should add length; ignored for now (TODO).
3. Rename `cables.svg` -> `routing.svg` (the build deletes the old file).
4. Committed SVG = outlines only. Pedal images only in a git-ignored local variant (`routing.local.svg`, behind a
   flag), images embedded from `.cache/images`.
5. Plug heads: one or two other cables can pass over/under a plug head. New limit `cables.max_over_plug` (default 2)
   = other cables crossing one plug (head + barrel, signal and power plugs; its own cable excluded). Enforced by the
   router (congestion cost, like `max_stack`) and kept by the smoothing.
6. SVG sized in mm (`width="..mm" height="..mm"`), so a browser prints it at 1:1.

## Phase 1: plug-head limit + path smoothing (`routing.py`)
- Plug heads in the router: every chosen plug's `head`/`barrel` rects (signal ends AND power plugs: the power side
  choice depends on pedals only, so it moves before routing) mark grid cells (centre inside the rect grown like the
  pedals). `route_all` gets the heads; a cell of a head that already has `max_over_plug` other cables costs like an
  over-stacked cell; leftover excess is a routing finding (`sink`) naming the cable and the plug (`monk.power`).
- Smoothing (pure `routing.smooth(...)`): the polyline from end A's exit through the cell centres to end B's exit is
  reduced to its necessary corners by string pulling: from an anchor, extend to the farthest following point while
  EVERY intermediate segment is valid (stop at the first invalid one: keeps the corridor, never jumps an obstacle).
  Valid segment: (a) per pedal, distance from the segment to the pedal rect >= min(cable radius, the smallest
  distance of the replaced grid points to it) (never closer than the grid path; squeezed paths do not get worse);
  (b) it crosses no plug head that the replaced grid sub-path did not cross. The plug leads (jack -> bend -> exit)
  stay as they are.
- `min_mm` and `path` follow the smoothed polyline (shorter or equal: triangle inequality). Stacking/overflow stays
  computed on the grid paths (corridor capacity).
- Tests: hand-computed cases (open field -> one segment; L around a pedal corner -> one corner; squeezed path not
  closer; head subset rule; head limit spreads a third cable; lengths never longer).

## Phase 2: parallel lanes (drawing geometry)
- After smoothing, segments of different cables closer than one cable width and roughly parallel form a bundle;
  each bundle gets lanes one cable width apart, ordered so cables do not cross inside it (order by where they
  enter/leave). A lane offset is used only if the offset segment stays valid (same rule as smoothing); else the
  cables are drawn stacked (distinct style). Lengths unchanged (decision 2). Output: `c["draw_path"]` per cable.

## Phase 3: shared drawing module + `routing.svg`
- New `scripts/svgdraw.py`: board, routing area, pedals with name labels, jacks (in/out/power/extra symbols with
  facing), plug heads on the chosen side, footswitches (moved from routing.py), legend table, mm sizing (1:1).
- Cables: one colour per hop; legend table S#, from -> to, min length; squeezed (dashed), over-stacked / over a
  plug limit (red halo), unroutable (straight dotted line between the jacks).
- `routing.local.svg` (git-ignored, `build.py --images`): the same picture with pedal images (rotated) under the
  outlines, embedded as data URIs from `.cache/images`.

## Phase 4: wiring in
- `build.py` writes `routing.svg`, removes `cables.svg`; README embeds it; `propose_layout.py` proposals use the same
  renderer. CLAUDE.md, TODO, `.gitignore`. Code review, merge.

## Acceptance
- Same corridors as before; paths straighter and never drawn on top of each other where a lane fits; lengths <=
  today's; plug-head limit reported; all tests pass (+ new ones); README shows `routing.svg`; prints at 1:1.
