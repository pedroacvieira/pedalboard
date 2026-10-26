# Plan: `feat/pedal-outlines`: route around the pedal's real shape, not its bounding box

Status: plan (2026-10-23). Branch `feat/pedal-outlines` from `main` (after the routing-view merge).

## 0. Starting point
- Every pedal is a rectangle today: `design.footprint(item)` = the Pedal Playground box (rotated). The router (grid,
  `smooth`, `lanes`), plug clearance (`routing.blocked_parts`, `jacks.check` fixed box) and the layout surrogate
  (`layout.Model._opt_clearance`) all use it.
- Finding (2026-10-23): the Pedal Playground images (`.cache/images`) are tightly cropped RGBA. Pedal Playground's
  Width/Height cover the whole image INCLUDING the protruding jacks: the enclosure bodies measured from the alpha
  match standard Hammond sizes within ~1-2 mm (Phase 95 / Mini Ego / Beano body 38 x 94 mm = 1590A 38.5 x 92.6;
  Analog Chorus / Reticon / Sun Face 61-62 x 114 = 1590B 60 x 112; Flight Delay 94 x 121 = 1590BB 94 x 119.5).
  So the images are not squeezed and the jacks add ~3-5 mm per side to the box. (Hammond sizes as reference; the
  pedals' own maker pages not checked.)
- The gig's stacked corridors (S11/S13, S14/S15) sit in 5.4-5.6 mm box gaps; with the outlines they gain room.

## Decisions (owner, 2026-10-23: proceed with the recommendations)
1. Outlines are committed derived data: `catalog/outlines.json`, keyed by Pedal Playground IMAGE file name (derived
   from the image only; covers supplies and non-chain items too), written only by `scripts/outlines.py`. No images
   in the repo. Missing outline = bounding box (conservative), reported once in the README, not a warning.
2. The outline is used for routing AND plug clearance (build and layout surrogate agree).
3. Pedal-pedal overlap (layout feasibility, `free_distance`, swaps) keeps the bounding box: neighbours' jacks
   cannot interleave freely, and the owner's Pedal Playground layout is box-based.

## Outline model
- Per image: a list of axis-aligned rects in image fractions (unrotated, origin top-left), 4 decimals, that COVER
  every opaque pixel (alpha > 128): conservative, never smaller than the pedal. Rows of ~1 mm cells (mm size from
  the Pedal Playground Width/Height), each row's opaque runs (gaps >= 2 mm keep runs apart), consecutive rows with
  the same runs (ends within 1 mm) merged into bands; each band's runs become rects (union span). At most 16 rects
  per image (merge the most similar neighbouring bands until it fits).
- Canvas rects: `design.outline_rects(item, outlines)` maps each fraction rect with `jack_point` (rotation-aware,
  axis-aligned for 0/90/180/270) and falls back to `[design.footprint(item)]`.

## Phase 1: data + drawing (handover routing-view style, `docs/handovers/pedal-outlines-1.md`)
`scripts/outlines.py` (generator CLI), `catalog/outlines.json`, `design.outline_rects`, `layout["shapes"]`
{item id: [rects]} in `jacks.layout_from_items`, svgdraw draws the outline (box faint dashed), tests.

## Phase 2: consumers (`docs/handovers/pedal-outlines-2.md`)
Router grid / `front_y` / `smooth` / `lanes` with the shape rects; `routing.blocked_parts` and `jacks.check` against
the shapes (deepest hit per obstacle as today); layout surrogate clearance with per-pedal shapes (relative to the
centre per rotation, like `_geom`), overlap/feasibility unchanged (box); `common.proposal_inputs_sha1` includes the
project's outline entries; README text (footprints sentence) + outline coverage note; CLAUDE.md, TODO.

## Acceptance
- Outlines for every image in the three projects' layouts; the gig picture shows them; routes, lengths and findings
  change only where the shapes free room (report before/after: lengths, stacked corridors, clearance findings);
  layout proposals still pass the build check; tests for the decomposition (synthetic masks), rotation mapping,
  fallback, and the consumers on hand-made shapes.
