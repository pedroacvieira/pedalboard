# Handover: add six candidate pedals to the catalog (2026-10-29)

Branch: `main` is fine (data only; do not commit, the coordinator commits). `uv run` only, never `pip install`.

## Goal
The owner is considering new pedals. Add them to `catalog/pedals.json` ONLY (not to any project; the owner decides
later). Pedals and their Pedal Playground database names (`playground_title` = "<Brand> <Name>" exactly as in the
cached database `.cache/pedals.json`, e.g. "Analog.Man Sunface"):

| id (suggested) | pedal | playground_title |
|---|---|---|
| `boss_dd8` | Boss DD-8 Digital Delay | `BOSS DD-8 Digital Delay` |
| `boss_dd200` | Boss DD-200 Digital Delay | `BOSS DD-200 Digital Delay` |
| `jhs_angry_charlie` | JHS Angry Charlie (current version, V3 in Pedal Playground) | `JHS Angry Charlie V3` |
| `jhs_the_violet` | JHS The Violet (Lari Basilio signature distortion) | `JHS The Violet` |
| `ehx_pico_pog` | Electro-Harmonix Pico POG | `Electro-Harmonix Pico POG` |
| `ehx_pico_pitch_fork` | Electro-Harmonix Pico Pitch Fork | `Electro-Harmonix Pico Pitch Fork` |

## What each entry needs (copy the structure of the existing entries; read 3-4 of them first, e.g. `flight_delay`,
`carbon_copy`, `jhs_hard_drive`, `tumnus_deluxe`)
`id`, `owned: false`, `instruments`, `brand`, `name`, `digital`, `clocked_noise`, `buffered_bypass`,
`buffer_switchable`, `tags` (use tags already used in the catalog where they fit), `playground_title`,
`power_consumption` {current_ma (worst case), min_voltage_v, max_voltage_v, needs_isolated_output, polarity},
`dependencies` (only intrinsic, sourced ordering rules, else []), `comments`, `price_eur`, `price_info` (store, url,
checked date, variant, availability, confidence, notes; German/EU stores preferred, e.g. Thomann, as the other entries).

## Rules (CLAUDE.md)
- Never invent specs or prices: research with sources (maker manual / spec page > retailer > forum). Unknown = `null`
  and say "unverified" in `comments`. Put the sources in `comments` / `price_info` as the existing entries do.
- Power: the maker's current draw at the rated voltage; voltage range as the maker states it (e.g. EHX Pico pedals
  ship with a 9.6 V supply: record what EHX says about 9 V supplies and the draw; the DD-200 draw is high).
- Digital pedals: `digital: true` (the power policy puts them alone on an output); `clocked_noise` true for digital /
  BBD.

## Also
- Outlines: `uv run scripts/outlines.py --image <image file>` for each pedal's Pedal Playground image (names in
  `.cache/pedals.json` "Image": boss-dd8.png, boss-dd200.png, jhs-angry-charlie-v3.png, jhs-the-violet.png,
  ehx-pico-pog.png, ehx-pico-pitch-fork.png); it fetches the images into the git-ignored cache and writes
  `catalog/outlines.json`. If it needs a project argument, check its `--help`.
- Jacks and footswitches are placed by the owner with the GUI (`scripts/pedal_editor.py`): do not add them.
- `uv run scripts/build.py` and `uv run pytest tests -q` must pass (catalog validation).

## Report
Per pedal: power (mA, V range, polarity, isolated?), digital, bypass, tags, price, sources, and every value you left
null / unverified.

## Do not touch
`projects/`, `catalog/jacks.json`, `catalog/footswitches.json`, scripts, tests, CLAUDE.md, docs/TODO.md.
