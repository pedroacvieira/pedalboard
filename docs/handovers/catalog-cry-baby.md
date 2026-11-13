# Handover: Dunlop Cry Baby GCB95F Classic in the catalog

## Goal
Append one entry to `catalog/pedals.json` (end of the `"pedals"` list, same text style as the last entries: one key per
line, small nested objects on one line; valid JSON). Then `uv run pb build` must not crash and
`uv run pytest tests/test_power.py -q` must pass.

- id `dunlop_cry_baby_gcb95f`, brand "Dunlop", name "Cry Baby GCB95F Classic", owned true, instruments ["guitar", "bass"]
  only if the maker says it suits bass, else ["guitar"].
- `"floor_device": true` (a pedal that is not on any board: it sits on the floor and can be used with any board; owner).
- `playground_title`: the exact Pedal Playground name if it exists in `.cache/catalog.json` (search its `pedals` list for
  brand "Dunlop" and a name with "Cry Baby" / "GCB95"; `title` = brand + " " + name); else null.
- Fields like the existing `mxr_bass_envelope_filter` entry: digital, clocked_noise, buffered_bypass,
  buffer_switchable, bypass_info {confidence, source, url, notes}, tags (reuse "filter"; add "wah"), power_consumption
  {current_ma worst case, min/max voltage, needs_isolated_output, polarity} (it may run on a battery or a 9 V adapter:
  give the adapter specs), height_mm + height_info (a treadle pedal: measure "overall", note heel/toe if given),
  dependencies [], comments (sources, caveats). Owned: no price.

Rules: never invent; maker (Dunlop manual / product page) > retailer > forum; unknown = null; say "unverified" when
needed. Do not touch any other file.

## Deliverable
The entry written, build and test result, a short table of the values with their confidence.
