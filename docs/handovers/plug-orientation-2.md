# Handover: plug-orientation phase 2, right-angle plugs pointing DOWN into a board hole

Branch `feat/plug-orientation` (checked out; do not commit, the coordinator commits). Python 3.12, `uv run` only
(`uv run pytest tests -q`, ~60 s; `uv run scripts/build.py`). Never `pip install`.

## Goal (owner)
A cable whose jack sits above a board hole may leave its right-angle plug straight DOWN into the hole, whether it then
stays under the board or comes back up elsewhere. It frees the space next to the pedal. Gig example: the Tumnus Deluxe's
three jacks (`out`, `power`, `in`, facing the back) sit right over a slot (effective hole x 38.5..186.6, y 201.3..219.8
mm); today its power cable P13 leaves its plug sideways along the pedal.

## Owner decisions (2026-10-28)
- New exit `down` for RIGHT-ANGLE plugs, signal (patch) and power alike. Straight plugs never go down.
- **Always down when available**, even if longer: per end, rank feasible first (inside the area / free path, as
  today), then down before left/right, then blocked parts + plug collisions, then length.
- Jack height: project setting `cables.jack_height_mm`, default 12 (unverified estimate of the jack axis above the deck).
- Overrides: `cables.overrides.<S#>.exit_a / exit_b` and `overrides.<P#>.exit_b` (and an on-board port's `exit_a`)
  accept `"down"`; an override `down` where no hole allows it is an error (routing sink is fine:
  `validation.strict_routing`), and the plug then falls back to the automatic choice.

## Model
- **Bend point** = jack point + facing x `exit_offset_mm` (default head depth / 2), the same point a side exit bends at
  (`design.plug_geometry`, right-angle branch: `bend`).
- **Available** when the square of side = the cable diameter centred on the bend point lies inside the effective holes
  (`layout["holes"]`, canvas mm rects; the union counts: e.g. every corner and the centre inside some hole rect) AND
  it does not overlap an under-board obstacle (the under-board supplies' outline rects, `under_rects` in
  `route_project`) grown by the cable radius. The top-layer "free" rule of hole cells does NOT apply (the plug sits
  right next to its own pedal). Signal plugs use the signal cable diameter, power plugs the power type's.
- **Footprint** on the board: the head rect only (no barrel, no cable run). Option dict as the side options:
  `{"side": "down", "rects": [("head", r)], "lead": [jack point, bend point], "exit": bend point, "lead_mm", "measure",
  "measure_mm", "down": True}`. Put the geometry in `design.plug_geometry(..., side="down")` (keep `design.SIDES` =
  ("left", "right") for the side exits; add e.g. `design.EXITS = (*SIDES, "down")`).
- **Length**: `measure_mm` = |exit_offset - head_depth/2| + `jack_height_mm` + the hole transit (`hole_transit_mm`
  in route_project's cfg: the board's deck). The routed path then starts / ends UNDER the board at the bend point's
  cell; that end is NOT a hole pass of the path (no second transit, not counted in `holes_used`... but say in the
  README "Exits" column `down`).
- **Routing**: that end of the net is the under state `(i, j, 1)` of the cell under the bend point (signal: the top
  grid's cell, `grid.cell_of(*bend)`; power: the power grid `pgrid`). From there the router continues under the board or
  comes back up through a hole / edge segment as usual.
  - `astar_layers` supports an under START (`start_under`, always enterable) but assumes a TOP goal. Add an under goal
    (always enterable, like the start; `tight_heuristic` needs a variant for an under goal: an admissible bound is
    `lo * d` from under and `pass_floor + lo * d` from the top). `Under.connected` takes top cells: extend it (or the
    caller) for under states, used by route_project's feasibility ranking (`combos`).
  - `path_geometry(grid, path, oa, ob, start_pt, ...)`: today `oa` None means "starts under the board at start_pt" (an
    under-board supply port) and `ob` is always on top. Make both ends work with a down option: an under first / last
    stretch starts / ends at the bend point, and `lead_a` / `lead_b` come from the option's lead (jack -> bend).
  - Signal cable fields: `under_board` = any stretch under (today `len(runs) > 1`), `under_mm`, `min_mm` = measures
    (including the down transit) + polylines + passes x transit.
  - Power (`route_power`): a down plug at the TARGET pedal makes the goal an under state; at a SOURCE pedal plug (a
    serial daisy hop starts at the previous pedal's plug) the start is under. An under-board supply port start stays
    as today. A forked output's legs share the port plug.
- **Choice**: `routing.end_options(item, jack, ctype, exit_fixed, cfg, outward, down=None)`: `down` = a callable
  `bend point, diameter -> bool` (availability) or None. Only `route_project` / `power_plug_choices` pass it, so the
  layout surrogate (`scripts/layout.py`, also calls `end_options`) is unchanged in this phase. In route_project's
  `combos` key add "number of ends not down" right after the feasibility fields (before blocked parts + collisions);
  in `power_plug_choices` put "not down" first in the key. The phase 1 collision code uses `o["rects"]`, so a down
  option's head-only footprint flows through.
- **Drawing** (`scripts/svgdraw.py`): `plug_heads` draws the head rects; for a down option also draw a marker at the
  bend point (a small filled circle with a cross; `ctx["routing"]["heads"]` entries get `"down": point` or similar).
  Under-board stretches are already drawn dashed. routing.svg and power.svg both. Legend entry "plug points down
  into a hole".
- **README** (`scripts/build.py`): the cable tables' "Exits" column shows `down`; the settings line mentions
  `jack_height_mm`. Look at how `exit_a` / `exit_b` are rendered.
- Validation: the exits check in `route_project` (`bad += [... not in (None, "auto", *design.SIDES)]`) and its message
  accept `down`; `cables.jack_height_mm` must be a number >= 0 (add to `settings()` defaults, see `DEFAULTS`).

## Tests (new `tests/test_plug_down.py`; synthetic cable types, hand-made layouts with a hole; never catalog values)
See `tests/test_power_routing.py`, `tests/test_edges.py`, `tests/test_plug_collisions.py` for ctx/layout builders.
- availability at a hole edge (inside by a hair vs out by a hair; the union of two adjacent hole rects; an under-board
  supply under the hole blocks it);
- hand-computed `measure_mm` and a whole `min_mm` for a cable with one down end;
- the choice prefers down even when a side route is shorter; side exit when no hole; override `down` honoured, and an
  error when unavailable;
- a signal cable with both ends down (under goal), a power hop down at both ends, a serial chain through a down plug;
- the drawing has the marker; the README shows `down`.

## Acceptance
- `uv run pytest tests -q` passes; `uv run scripts/build.py` exit 0.
- Gig before/after with `uv run python /tmp/claude-1000/-home-pvieira-projects-pedalboard/08007042-4064-4da5-be57-4d44a51608ea/scratchpad/snap.py guitar-gig <out.json>` (run it before your
  change too): list every cable whose exit / length / status changed (P13 at least), and the clearance / collision
  findings before and after (expected: Tumnus plugs go down, the Tumnus findings disappear). Check the speed:
  `time uv run scripts/build.py guitar-gig` before/after (today ~1.7 s); say if it got much slower.
- If gig-pinned tests change only because plugs now go down, update them and say which.
- Short report: changes per file, decisions you made, open points.

## Do not touch
`scripts/layout.py` (phase 4), `catalog/`, `projects/*/project.json`, `playground_design.json`, CLAUDE.md,
docs/TODO.md, the plan. No straight DC plugs / per-end plug types (phase 3).
