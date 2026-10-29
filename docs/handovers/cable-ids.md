# Handover: rename the power cable ids (`feat/cable-ids`)

## Goal
Power cables get the ids P# (the physical cable you buy) and P#.1, P#.2 ... (its legs, only when it has more than
one); the C# ids disappear. Signal cables keep S#. Pure renaming plus a better "DC cables to buy" table; no change
to routing, lengths or plug choices.

## Where you work
- Git worktree `/home/pvieira/projects/pedalboard-cable-ids`, branch `feat/cable-ids` (checked out). Work ONLY here;
  never touch `/home/pvieira/projects/pedalboard` or `/home/pvieira/projects/pedalboard-fix-image-download`.
- `.cache/` is a copy (git-ignored) of the owner's Pedal Playground cache; the build needs it, do not delete it.
- Python 3.12 via uv: `uv sync` once, then `uv run ...`; never `pip install`. Tests: `uv run pytest tests -q`
  (~565 tests, ~60 s; plugins are disabled in pyproject).
- Commit when done, in one or a few commits on `feat/cable-ids` (messages end with
  `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`). Do not push, do not merge.

## Today (read the code to confirm)
- `scripts/jacks.py` ~line 493: `n_cable` numbers the physical DC cables `C1..` over the supply outputs: a SERIAL output
  is one cable (all its hops), a FORKED output one cable per pedal; every hop dict gets `"cable": f"C{n_cable}"` and
  `"style"`.
- `scripts/routing.py` ~line 1574-1595: builds the power cable list entries with `"id": f"P{n}"` (n = hop number over all
  hops) and `"cable": hop.get("cable") or spare_cable_id()` (`spare_cable_id` makes unused C ids for hand-made ctx).
- `routing.power_cable_summary` (~line 2185) groups legs by `cable` -> `ctx["power_cable_summary"]` (id, style,
  output, legs [P#], from, to, plugs, plug_types, min_mm = sum, estimate_mm, status).
- Serial-cable logic groups by `cable` (`routing.py` ~2311, 2355): keep it working.
- `scripts/power.py` `cable_ids(supplies)` (pedal -> P#, numbering every pedal, ignores the style) and
  `remap_overrides` (regex `P\d+`), used by `scripts/propose_layout.py` ~133.
- `cables.overrides.<id>` is read in `routing.py` (`~1316`, `~1325`, `~1550`, `~1757`); unknown keys are silently ignored.
- `scripts/build.py` ~571 cable table (column "DC cable" = `c.get("cable")`), ~588-620 "DC cables to buy"
  (`power_cable_summary`), text around README line "A power cable (P#) is one leg; the DC cable column says which
  physical cable it belongs to (C#...)".
- `scripts/svgdraw.py` ~338 power label `c.get("cable") or c["id"]`, ~698 iterates `power_cable_summary`.
- Tests mentioning P#/C#: test_svgdraw, test_power_types, test_plug_down, test_check, test_daisy_chains,
  test_plug_collisions, test_layout, test_routing, test_power_routing (grep `"C[0-9]` and `"P[0-9]`).

## Required behaviour (owner decisions, 2026-10-29)
1. Cable numbering = today's C# order (supply instance, output, per pedal for forked). Cable id `P{k}`.
2. Leg id: `P{k}` when the cable has one leg; `P{k}.{j}` (j = 1.. in daisy order, P{k}.1 starts at the supply port)
   when it has several. Each power entry of the cable list keeps `id` = leg id and `cable` = cable id.
   Example: gig C10 (psu2.SW_B -> phase_95 -> retrovibe) -> P10.1 + P10.2, cable P10.
3. Assign both ids in `jacks.check` (one place); `routing` takes the leg id from the hop (fallback for hand-made ctx
   without ids: each hop its own one-leg cable with the next unused P number). No C ids anywhere.
4. `power.cable_ids` returns the same leg ids for a project-style wiring: it must know the style of each output
   (`outputs[].style`, else `routing.daisy_style(project)`; change the signature as needed and update callers).
   `remap_overrides` matches `P\d+(\.\d+)?`. Add a test: on the gig project, `power.cable_ids` equals the leg ids
   `jacks.check` produces, per pedal.
5. `cables.overrides`: a key that is not the id of a cable of the project (S#, a one-leg P#, or a P#.n leg) is a build
   ERROR with a hint, e.g. "cables.overrides.P5: no such cable; P5 is a daisy chain with legs P5.1, P5.2: override a
   leg" or "cables.overrides.C3: C# ids were renamed to P# (see the cable table)". Projects today have no overrides
   (check `projects/*/project.json`); `propose_layout` must not produce such errors for remapped overrides.
6. README (`build.py`): drop the "DC cable" column of the cable table (the leg id names its cable); "DC cables to buy":
   one row per P# cable with its legs and each leg's min length, labelled as the minimum spacing between consecutive
   plugs (e.g. "P10.1 112 / P10.2 136"), plus the total; rewrite the explaining sentences for P# / P#.n (no C#).
7. SVG labels (`svgdraw.py`): each power leg labelled with its leg id.
8. Regenerate: `uv run scripts/build.py` (all projects) and commit the regenerated READMEs / SVGs.
9. Docs: in `CLAUDE.md` replace the C# / P# descriptions (search "C#", "P#", "power_cable_summary", "overrides.<P#>")
   with the new scheme in the same terse style; in `docs/TODO.md` tick the "Cable ids" item (section 2) with a short
   done note.

## Acceptance
- `uv run pytest tests -q` green (update the tests' expected ids; add tests for 2, 4, 5 and the README table).
- `uv run scripts/build.py` exits 0; guitar-gig README: no "C1" etc., cable lengths and statuses identical to before
  (diff the numbers: only ids and the table layout change).
- `grep -rn '"C[0-9]\|C#' scripts tests CLAUDE.md` finds nothing relevant left.

## Do not touch
Routing / plug choice / layout search logic, catalog data, `projects/*/playground_design.json`, `projects/*/board.json`,
the proposals' `<n>.json` files.

## Report back
Files changed, commits, test results, a before/after excerpt of the gig README's two power tables, anything left open.
