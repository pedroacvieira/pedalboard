# Handover: three new catalog pedals (research + catalog entries)

## Goal
Add three pedals to `catalog/pedals.json` (append at the end of the `"pedals"` list, same text style as the existing
entries: one key per line, small nested objects on one line; keep the file valid JSON). Then run `uv run pb build`
(it must not crash; existing warnings are fine) and `uv run pytest tests/test_power.py -q`.

| id | Pedal Playground title (`playground_title`, exact) | owned | instruments |
|---|---|---|---|
| `ibanez_ts_mini` | `Ibanez Tube Screamer Mini` | true (owner's practice board, owned gear only) | ["guitar"] |
| `mxr_bass_chorus_deluxe` | `MXR Bass Chorus Deluxe` (MXR M83) | false (to buy) | ["bass"] |
| `mxr_bass_envelope_filter` | `MXR Bass Envelope Filter` (MXR M82) | false (to buy) | ["bass"] |

## Fields (copy the shape of the existing `mxr_bass_synth` entry)
id, owned, instruments, brand, name, digital, clocked_noise, buffered_bypass, buffer_switchable, `bypass_info`
{confidence, source, url, notes}, tags, playground_title, power_consumption {current_ma (worst case), min_voltage_v,
max_voltage_v, needs_isolated_output, polarity "center_negative"|"center_positive"}, height_mm, height_info {measure
overall|unspecified|enclosure_plus_switch, confidence, source, url, notes}, dependencies [], comments (sources and
caveats in prose), and for the two NOT owned pedals: price_eur + price_info {store "thomann.de", url, checked
"2026-11-09", variant, availability, confidence page|snippet, notes}.

Rules:
- Never invent. Sources: maker (manual, product page) > retailer > forum; say "unverified" in notes/comments when
  needed; unknown = null.
- digital = has a DSP/digital circuit; clocked_noise = BBD or digital clock (an analog BBD chorus is clocked_noise true,
  digital false).
- Tags: reuse existing tags where they fit (see other entries: "gain", "overdrive", "modulation", "chorus", "filter",
  "fuzz", ...; "gain" + "overdrive" for the Tube Screamer).
- height: if only an enclosure height is published, measure "enclosure_plus_switch", add 15.2 mm and keep the published
  figure in `enclosure_mm` plus `"switch_allowance_mm": 15.2`.
- Power: worst-case mA from the maker if possible.

Do not touch any other file (jacks.json / footswitches.json are written only by the owner's editor).

## Deliverable
The three entries written, build and test result, and a short table of the values with their confidence.
