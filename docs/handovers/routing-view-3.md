# Handover: routing-view phase 3: shared drawing module and `routing.svg`

Branch `feat/routing-view` (checked out; phases 1-2 committed). Do not commit. Python 3.12, run everything with
`uv run` (`uv run pytest tests -q`, `uv run scripts/build.py`). Units: mm everywhere. Stdlib + Pillow only.

## Goal
A picture the owner can wire the board from (and print at 1:1), drawn by one shared module that later features
(power.svg, a web UI) reuse. It replaces `routing.svg()` in scripts/routing.py and the file `cables.svg`.

## Owner decisions
- File renamed `cables.svg` -> `routing.svg` (the build deletes a leftover `cables.svg`).
- Sized in mm: `width="<w>mm" height="<h>mm"` with the viewBox in mm, so a browser prints it at true scale.
- The committed SVG has outlines only. Pedal images ONLY in a git-ignored local variant `routing.local.svg`, written
  by `uv run scripts/build.py --images` (images embedded as data URIs from `.cache/images`, never committed).
- Lanes are drawing only: draw `c["draw_path"]`; lengths are `c["min_mm"]` (centreline).

## Context (read these)
- `scripts/routing.py` `svg(ctx, names, overlay=None, legend=None)`, `PALETTE`, `FOOTSWITCH_STYLE`: today's drawing
  (board, dashed routing area, pedal boxes, overflow cells, plug heads, cables, footswitches, too-close lines,
  legend sentence). Callers: `scripts/build.py` main (~line 860, writes `cables.svg`) and README text in
  `routing_section` (~line 428: `![Cable routing](cables.svg)` and the "grey boxes" sentence);
  `scripts/propose_layout.py` (~line 267, `proposals/<n>.svg` with `overlay(...)` elements and an extra legend).
- Data available in ctx: `ctx["layout"]` = {"board", "placed" {cid: item}, "obstacles", "jacks" {cid: [jack]},
  ...}; an item has `left_mm, top_mm, w_mm, h_mm` (UNROTATED box), `rot` (0/90/180/270 about the centre), `image`
  (Pedal Playground file name), `title`; `design.footprint(item)` = rotated box (x0, y0, x1, y1);
  `design.jack_point(item, fx, fy)` / `design.jack_facing(item, facing)` = a jack's canvas point / rotated facing.
  A jack: {id, label, function input|output|power|power_out|other, x, y, facing}. `ctx["routing"]` = {grid,
  front_y, settings, overflow (cells), heads [{cable, rects [(part, rect)]}], plug_over}. `ctx["cable_list"]`:
  signal cables with id, from "<cid>.<jack>", to, min_mm, status, path, draw_path, stacked_with, exit_a/b; power
  cables (kind "power", not routed). `ctx["footswitch_points"]` [{x, y, type, ...}], `ctx["footswitch_pairs"]`.
- Image download: `fetch_image(image_name)` in `scripts/pedal_editor.py` (urllib into `.cache/images/`, exits the
  process on failure).

## Tasks
1. New `scripts/svgdraw.py` (pure string building, small functions; keep the repo's compact style):
   - `board(...)`, `routing_area(...)`, `pedal(item, name, ...)` (rotated box, name label centred, wrapped or
     shortened to fit, font scaled to the pedal), `jacks(item, jack_list, used)` (small symbol at each jack: colour
     by function: input blue, output green, power orange, other purple; a short tick showing the facing; used jacks
     filled, unused hollow), `plug_heads(heads)`, `footswitches(points, pairs)` (moved from routing.py, same style),
     `cables(cable_list)`, `legend_table(rows)`, `document(view_box, body)` (mm sizing).
   - Cables: colour per signal cable from a palette readable on white (no pastels; 16+ distinct colours; replace
     today's PALETTE), each drawn with a thin dark casing under the colour line so crossings stay readable; S# label
     at the middle of the cable's longest segment with a white halo (`paint-order="stroke"`). Styles: squeezed status
     -> dashed; over the stacking or plug limit -> red halo under the line; stacked_with -> the existing white dashes;
     unroutable -> dotted grey straight line between the two jacks (positions from the jacks), label still shown.
   - Legend table under the board: one row per signal cable: colour swatch, S#, from -> to, min length (mm, 0 dp), a
     short status if not plain "routed"; plus a key line for the symbols (jacks, plug heads, footswitch colours,
     dashed/stacked/red styles). Must be legible when printed at 1:1 (font >= 2.5 mm).
   - `render(ctx, names, overlay=None, legend=None, images=None)`: the full picture (what `routing.svg()` returns
     today, improved). `images` = {cid: path to PNG} draws each placed pedal's image under its outline: `<image>`
     with x/y/width/height = the unrotated box, `transform="rotate(rot cx cy)"`, `preserveAspectRatio="none"`,
     data URI (downscale with Pillow to at most ~600 px on the long side to keep the file small).
2. `routing.svg()` becomes a thin wrapper calling `svgdraw.render` (or remove it and update both callers; keep
   propose_layout's `overlay` and `legend` working). Remove the moved drawing code from routing.py.
3. Move `fetch_image` (+ `IMAGE_URLS`, `IMAGE_DIR`) to `scripts/common.py`, raising `RuntimeError` with the same
   message instead of exiting; `pedal_editor.py` imports it from common and keeps its current behaviour (exit with the
   message). Keep `pedal_editor`'s existing tests passing.
4. `build.py`: write `routing.svg` (delete a leftover `cables.svg`; delete `routing.svg` when there is no picture);
   new flag `--images`: also write `routing.local.svg` with the pedal images (fetch missing ones via
   `common.fetch_image`; a pedal whose image fails is drawn without it and the build prints one line naming it);
   without the flag, do not touch `routing.local.svg`. README: `![Signal routing](routing.svg)`, update the
   sentence about the picture (jacks, plug heads, lanes, stacked, legend; "prints at 1:1 from a browser") and
   mention `--images` once. `.gitignore`: `projects/*/routing.local.svg`.
5. `propose_layout.py`: proposals' `<n>.svg` drawn with the same renderer (outlines only), overlay unchanged.
6. Tests (new `tests/test_svgdraw.py`, style of the other tests): the output parses as XML (`xml.etree`); width and
   height end in "mm" and match the viewBox; one cable line per routed signal cable using `draw_path`; legend rows ==
   signal cables with their rounded min length; a jack symbol per jack of the placed pedals (used filled); a
   rotated pedal's image gets the rotate transform; no `<image>` without `images`; unroutable cable drawn dotted
   between its jacks; squeezed dashed. Use small hand-made ctx dicts (see `plug_ctx` in tests/test_routing.py) and
   a tiny PNG made with Pillow in `tmp_path`. Update existing tests that referenced `routing.svg()` output.
7. Run all tests and `uv run scripts/build.py` (and once with `--images`); check `projects/guitar-gig/routing.svg`
   by rendering it to PNG if a converter is available (else inspect the XML) and describe what it looks like:
   overlaps of labels with pedals or each other, unreadable spots. Report sizes of routing.svg and routing.local.svg.

## Constraints / do not touch
- No new dependencies. Do not change routing results (paths, lengths, findings), layout.py, catalog or project data.
  Generated files change only by running the build (and `proposals/*.svg` only if you rerun propose_layout:
  don't; the next propose run will pick the renderer up).
- Never commit images or `routing.local.svg`. Do not commit. Do not edit CLAUDE.md or docs/TODO.md.

## Acceptance
- All tests pass with the new ones; build writes routing.svg (no cables.svg left), README embeds it; `--images`
  writes routing.local.svg (git-ignored); short report: what changed, file sizes, how the gig picture looks, doubts.
