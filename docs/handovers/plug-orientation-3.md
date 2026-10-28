# Handover: plug-orientation phase 3, several DC plug types (straight DC plugs), a plug type per cable end

Branch `feat/plug-orientation` (checked out; do not commit, the coordinator commits). Python 3.12, `uv run` only
(`uv run pytest tests -q`, ~60 s; `uv run scripts/build.py`). Never `pip install`.

## Goal (owner)
A straight DC plug is slimmer than a right-angle one but takes more room outwards from the jack. Let a project offer
several DC plug types and let the router pick, per power plug, the type and exit that fit best. The owner's measured
cable has one straight and one right-angle end, so the plug at the supply port and the plug at a pedal may differ.

## Owner decisions (2026-10-28)
- `cables.power_types`: [type ids] (each role `power` in `catalog/cables.json`); default `[cables.power_type]`.
  `cables.power_type` stays the project's default DC type (first in the ranking ties, used for estimates and for the
  ports of under-board supplies, whose plug is not on top of the board). If `power_types` is given without
  `power_type` in it, put `power_type` first. Unknown ids / wrong role: errors (as `validate_project_types` does for
  `power_type`).
- **One style per serial cable**: all the pedal-end plugs of one SERIAL daisy-chain cable (one `cable` id C#, legs
  P#) share one plug type; only the port plug (supply end) may differ. A FORKED output has one cable per pedal: each
  picks its pedal-end type itself; the port plug (shared by the output's legs) has one type.
- Ranking per plug, as today plus the type: "down" first when available (phase 2: right-angle only; straight plugs
  never go down), then blocked parts + plug collisions, then the overlap sum, then the order of `power_types`. For a
  serial cable: try each type for the whole cable (each pedal plug takes its best exit for that type) and keep the
  type with the best summed key (down count, then blocked + collisions, overlap, list order).
- Overrides: `cables.overrides.<P#>.type_b` fixes the pedal-end type of that leg (serial: the whole cable's pedal
  ends; two legs of one serial cable fixing different types -> a routing warning, the first leg wins);
  `overrides.<P#>.type_a` fixes the port plug type (an on-board port's plug; for an under-board port it only says
  which plug to buy). `exit_b` / `exit_a` keep working; an exit that the chosen type cannot do (a side or `down` for a
  straight plug) is an error-free fallback: say so in a routing warning.

## Where things are today (read these functions)
- `scripts/routing.py`:
  - `power_plug_choices(ctx, cables, cable_types, cfg, obstacles, taken=None)`: one DC type
    (`cfg["power_type"]`), per pedal power jack and per used on-board port: options from `end_options`, ranked, the
    chosen side written to the cable's `exit_b` / `exit_a`. Returns [(id, jack, power cable or None, facing, option)].
    Phase 2 adds the down option (`end_options(..., down=...)`). It must now return the chosen type with each entry
    (e.g. in the option dict: `o["type"]`), and set `type_a` / `type_b` on the power cables (each leg: `type_b` = its
    target pedal's plug type, `type_a` = its source plug's type: the port's for the first / forked legs, the previous
    pedal's for a serial daisy hop, since that plug is the same physical plug).
  - `route_power`: builds the power grids with `ptype["diameter_mm"]` of the one power type. With several types, use
    the widest diameter of the types in use (as the signal grid uses the widest signal cable). Its port start uses
    `ptype["plug"]["head_depth_mm"]`: take the port's type.
  - `power_plug_clearance`: messages and violations name `cfg['power_type']`: use the chosen type.
  - route_project's power cable dicts: `"type": cfg["power_type"]`; keep `type` (= the pedal-end type, `type_b`) for
    the existing readers and add `type_a` / `type_b`. The exits check / unknown-type check accept the new keys.
  - `power_cable_summary(cables)`: per physical cable add `plug_types`: e.g. {"port": type, "pedals": type} (serial)
    or the per-leg pair (forked).
- `scripts/build.py`: the cable table's "Type" column shows `type_a / type_b` for power cables when they differ;
  `dc_cable_table` ("DC cables to buy") gets a "Plugs" description such as `1 x dc_ra_owner_baseline (port) + 4 x
  dc_straight_owner_baseline`; the settings text lists the power types.
- `scripts/jacks.py` `check`: the right-angle length estimate uses `power_type`'s depth: leave it.
- Catalog types exist: `dc_ra_owner_baseline` (right-angle) and `dc_straight_owner_baseline` (straight, 34 deep x 10
  wide): do not edit them; tests use synthetic types.

## Tests (new `tests/test_power_types.py`; synthetic types and hand-made layouts, see `tests/test_power_routing.py`,
`tests/test_plug_collisions.py`, `tests/test_daisy_chains.py` for builders)
- default (`power_types` absent) = today's results exactly (a regression check on a small layout);
- a pedal whose right-angle exits are both blocked takes the straight plug; one whose straight head is blocked keeps
  the right-angle; down (phase 2) beats straight when a hole allows it;
- serial cable: one pedal-end type for all its pedal plugs (the type with the best summed key), port type separate;
  forked: per-leg types;
- overrides `type_a` / `type_b` honoured; conflicting `type_b` on two legs of one serial cable -> warning;
- the power grid uses the widest diameter; `min_mm` uses each end's own plug measure (hand-computed);
- README: per-leg types, the "DC cables to buy" plug description; validation errors for unknown / non-power types.

## Acceptance
- `uv run pytest tests -q` passes; `uv run scripts/build.py` exit 0 (the projects do not set `power_types` yet:
  their results must not change; compare with
  `uv run python /tmp/claude-1000/-home-pvieira-projects-pedalboard/08007042-4064-4da5-be57-4d44a51608ea/scratchpad/snap.py guitar-gig <out.json>` before/after).
- Then, as a trial without saving it in the project (a copy of the project dict passed to `build.validate(...,
  project=...)`), report the gig with `power_types: ["dc_ra_owner_baseline", "dc_straight_owner_baseline"]`: which
  plugs turn straight, length changes, findings before/after.
- Short report: changes per file, decisions, open points.

## Do not touch
`scripts/layout.py` (phase 4), `catalog/`, `projects/*/project.json`, `playground_design.json`, CLAUDE.md,
docs/TODO.md, the plan.
