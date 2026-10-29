# Plan: cable ids S# / P# / P#.n (`feat/cable-ids`)

Status: decided by the owner (2026-10-29), implementation delegated (`docs/handovers/cable-ids.md`).

## Today
- `S#`: a signal (patch) cable, numbered along the chain (S1 = first pedal out -> second pedal in).
- `P#`: one power LEG = one hop from plug to plug (supply port -> pedal, pedal -> next pedal), numbered over all hops
  in `jacks.check` order (supply instance, output, daisy order). `cables.overrides.<P#>` (`exit_b`, `type_a`,
  `type_b`) address a leg.
- `C#`: one physical DC cable (`jacks.check`, `routing.power_cable_summary`, README "DC cables to buy"): a SERIAL
  output is one cable through every pedal of the output (its legs are the hops), a FORKED output has one cable per
  pedal (one leg each).
- The owner reads "C" as "cable" and "P" as "power" and finds the two levels confusing.

## Decision (owner, 2026-10-29)
- Every power cable you buy is **P#**, as every signal cable is **S#**. No C# any more.
- The legs of a cable with more than one leg (a serial daisy chain) are **P#.1, P#.2 ...** in chain order (P#.1 starts at
  the supply port). A cable with one leg (a single pedal on an output, every forked cable) is just **P#**: the cable
  and its leg share the id.
- Numbering: the cables in today's C# order (supply instance, output, then per pedal for a forked output). Example on
  the gig: C10 (psu2.SW_B -> phase_95 -> retrovibe) becomes P10 = P10.1 (SW_B -> phase_95) + P10.2 (phase_95 -> retrovibe).
- Why the legs stay: each leg is routed on its own (path, exit sides, hole / edge crossings), overrides address one
  plug end of one leg, and for buying a daisy-chain cable each leg's min length is the minimum spacing between two
  plugs (the sum alone is not enough).

## Changes
1. Id assignment in one place: `jacks.check` gives every power hop `cable` (P#) and its leg id; `routing` uses that
   leg id as the cable list `id` instead of numbering hops `P{n}`. Hand-made ctx without `cable` (tests): each hop its
   own cable, the next unused P number.
2. `power.cable_ids` (pedal -> leg id of a project-style wiring) follows the same rule, including the output style
   (`outputs[].style`, else `routing.daisy_style(project)`), so `power.remap_overrides` keeps working (its `P\d+`
   pattern becomes P#, P#.n). One test asserts `power.cable_ids` and `jacks.check` agree on the gig.
3. `cables.overrides`: a key that names no cable of the project is an error with a hint (ids are S#, P# for a
   one-leg power cable, P#.n for a leg of a daisy chain; old C# ids were renamed). Today no project has overrides,
   so nothing to migrate; check `projects/*/project.json` anyway.
4. README: the cable table's "DC cable" column goes (the leg id names its cable); "DC cables to buy" lists per cable
   its legs with each leg's min length ("min plug spacing"), and the total. `power.svg` / `routing.svg` labels use
   the leg ids. Text that explains P# / C# follows.
5. `CLAUDE.md` (lines on P#, C#, `power_cable_summary`, overrides) and `docs/TODO.md` (tick "Cable ids") follow.

## Not in scope
Signal ids, power routing, plug choice, the layout search (no ids there beyond `remap_overrides`).
