# Handover: which gig pedals have a buffer (research only)

## Goal
For each of the 17 pedals below, find out from online sources whether it has a buffer:
- `buffered_bypass`: bypassed, the signal goes through a buffer (not true bypass / not relay true bypass).
- `buffer_switchable`: the owner can choose (switch, dip switch, internal jumper/trimpot, menu setting,
  button combo at power-up) between buffered and true bypass, OR the pedal has an always-on input buffer
  that matters even when bypassed. Say exactly how it is switched.
Also note an always-on input buffer that is active only when the effect is ON (note it, it is not "buffered bypass"),
and any "trails" mode that implies a buffer.

## Rules
- Never invent. Sources: maker (manual, product page) > retailer > forum. Give a URL per pedal and the confidence
  (maker | retailer | forum). If not found, say "unknown".
- Versions matter (e.g. Retrovibe Mk3 vs Mk4, PolyTune 3 Mini vs full size, Belle Epoch Deluxe Black Edition,
  Analog.Man Sun Face options, MXR Analog Chorus M234). When versions differ, give each.
- Research only: do NOT edit any repo file.

## Pedals (catalog id: maker model; current catalog values buffered/switchable, unsourced)
- sun_face: Analog.Man Sun Face (BC183) — F/F
- danelectro_3699: Danelectro 3699 Fuzz — F/F
- beano: Analog.Man Mini Beano Boost — F/F
- polytune_3: TC Electronic PolyTune 3 Mini Noir — T/T
- mini_ego: Wampler Mini Ego Compressor — F/F
- fulldrive_2: Fulltone Full-Drive 2 MOSFET — F/F
- phase_95: MXR Phase 95 (M290) — F/F
- retrovibe: Jam Pedals Retrovibe — F/F
- red_muck: Jam Pedals Red Muck Mk2 — F/F
- ratsbane: Wampler Ratsbane — F/F
- protein: Browne Amplification Protein V3 — F/F
- analog_chorus: MXR Analog Chorus (M234) — T/F
- reticon: PastFX Reticon Flanger — F/F
- monk: Jam Pedals Harmonious Monk Mk2 — F/F
- belle_epoch: Catalinbread Belle Epoch Deluxe (Black Edition) — F/T
- tumnus_deluxe: Wampler Tumnus Deluxe — T/T
- boss_dd200: BOSS DD-200 — T/F

## Deliverable
A table: id | buffered_bypass | buffer_switchable | how it is switched / notes | source URL | confidence,
and a short list of the catalog values that are wrong.
