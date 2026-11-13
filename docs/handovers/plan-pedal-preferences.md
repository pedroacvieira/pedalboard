# Handover: write the plan for `feat/pedal-preferences` (planning only, no code)

## Goal
Write `docs/plans/pedal-preferences.md`: an implementation plan for ONE preference profile per pedal in a project, then stop.
Do not change any code or data. The plan is read by the owner and then split into implementation handovers.

## The feature (owner's backlog)
Every per-pedal wish in one place, later editable in a web UI with values, drop-downs and toggles:
- Data: `project.json` `pedals.<id>`: position (left / right / front / back / any + strength), pin, allowed rotations, order
  wishes (before / after X with priority -> today's ordering rules), power wishes (own output, preferred supply / port,
  voltage), footswitch topper, access override.
- Migrate today's scattered knobs: `layout.pins`, `layout.rotations.<id>`, `layout.access.pedals` (scripts/layout.py
  `DEFAULTS`, `config`, `Model`), per-pedal rules (`project.rules` entries with `"pedal"`, read in scripts/build.py
  `validate`), the power output choice (`power.supplies[].outputs[].pedals`), `footswitches.toppers`. Old keys still read
  (or a one-off migration script: the plan decides, with a reason).
- Build: validate the profile, README table "Preferences" (asked for, met or not in the owner's layout and in each layout
  proposal); the layout search (scripts/layout.py) and `power.assign` (scripts/power.py) read it.
- Until the web UI: the owner edits project.json by hand (documented schema).

## Constraints (keep)
- Units mm. Unknown values null. Python 3.12, run with `uv run`. Findings start as warnings; projects promote them.
- Rules: priorities, required / preferred; rules expand to pairwise "a before b"; higher priority wins.
- Generated files (READMEs, svg) are never edited by hand. Tests: pytest, hand-computed cases; gig-dependent tests use the
  frozen fixture `tests/fixtures/guitar-gig/`.
- The live projects (`projects/guitar-gig`, `guitar-practice`, `bass`) must build the same before and after migration.

## The plan must contain
Schema (with an example), semantics of each field and how it maps onto today's knobs, migration path, which modules change
(functions), validation messages, README table, how the layout search and power assignment use it, test list, the order of
implementation steps (each step a self-contained handover for a Sonnet agent), risks, and a short "Decisions for the owner"
list with a recommended default for each (so implementation can start with the defaults).

Read the code you need (scripts/layout.py, scripts/build.py, scripts/power.py, scripts/footswitches.py, the three
project.json files); do not read other plans or handovers.

## Deliverable
The plan file written, and a 10-line summary with the owner decisions and your recommended defaults.
