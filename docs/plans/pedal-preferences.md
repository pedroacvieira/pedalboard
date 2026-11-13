# Plan: `feat/pedal-preferences`: one preference profile per pedal in a project

Status: plan (2026-11-13), waiting for the owner's decisions (last section; implementation can start with the recommended
defaults). Code read: `scripts/layout.py`, `scripts/build.py`, `scripts/power.py`, `scripts/footswitches.py`,
`scripts/propose_layout.py`, the three `project.json` files, `tests/fixtures/guitar-gig/project.json`.

## 1. Goal

Every per-pedal wish of a project in one place, `project.json` `pedals.<pedal id>`, so a later web UI can show one form per
pedal (values, drop-downs, toggles). Until then the owner edits it by hand. The build validates the profiles and reports
in a README table "Preferences" whether each wish is met in the owner's layout and in each layout proposal. The layout
search (`layout.py`) and the power assignment (`power.assign`) read it.

Out of scope: the web UI, per-pedal `max_move_mm`, preferences of supply instances (section 4.6), the signal chain
order itself (the owner sets `signal_chain`; order wishes are checked against it, as today's rules are).

## 2. Today's knobs (what exists and what the live projects use)

| Knob | Read by | Live use (2026-11-13) |
|---|---|---|
| `layout.pins` [ids] (pedals AND on-board supply instances) | `layout.settings` -> `Model.pins`; `propose_layout --pin` adds to it | none |
| `layout.rotations.<id>` [0/90/270] / "any" / "current" (`default` key too) | `Model.__init__` -> `Model.allowed` | none |
| `layout.access.pedals.<id>` {"want": front/back/avoid_front, "weight"} | `layout.settings`, `access_rule` (wins over tag / switch rules) | none |
| `rules` [{id, pedal, type, ..., strength, priority, reason}] | `build.validate` (ordering rules) | all three projects (gig 21, practice 8, bass 6); every id is `<pedal>.<name>` |
| `rule_overrides` {rule id: {disable, strength, priority}} | `build.validate` | none (all `{}`) |
| `power.supplies[].outputs[].pedals` (the hand wiring) | build (power checks, routing, DC cables), `power.assign(start=, run_v=)` | all three projects |
| `footswitches.toppers` ["<pedal>.<switch id>"] | `footswitches.topper_settings` | none |

Only `rules` and the power wiring carry live data. The fixture `tests/fixtures/guitar-gig/project.json` (frozen) uses the
old `rules` (21 entries with `"pedal"`), one of them for a pedal not in the chain (`double_dragon.after_sun_face_beano`:
skipped today, `ctx["skipped_rules"]`).

## 3. Schema

`project.json` gets a top-level object `pedals` {pedal id: profile}. Every field is optional; a missing field = no wish (today's
defaults). Example (guitar-gig, partly invented to show every field):

```json
"pedals": {
  "boss_dd200": {
    "position": { "side": "left", "depth": "front", "strength": "preferred", "weight": 0.3 },
    "rotations": [0],
    "order": {
      "position_last": { "type": "position", "value": "last", "strength": "required", "priority": 110, "reason": "Its looper records the whole chain" },
      "after_group_gain": { "type": "after_group", "group": "gain", "strength": "required", "reason": "Time-based effects after the dirt" }
    },
    "power": { "own_output": true, "supply": "psu1", "port": "F1", "voltage_v": 9, "strength": "required" },
    "toppers": ["switch_2"],
    "note": "free text, shown in the README table"
  },
  "polytune_3": { "pin": true, "position": { "depth": "back" } }
}
```

### 3.1 Fields, semantics, mapping

| Field | Values | Meaning | Today's knob (lowering, 5.1) |
|---|---|---|---|
| `position.side` | `left` / `right` / `any` (null = no wish) | where across the board the pedal sits: reference point = its BODY centre x (`design.body_rect`) | new (no knob) |
| `position.depth` | `front` / `back` / `avoid_front` / `any` (null = the tag / switch default) | depth on the board: reference point = mean of its footswitches, else the centre (exactly `access`); `any` = no depth wish at all, also cancels the tag default (new ability) | `layout.access.pedals.<id>` = {"want": depth, "weight"} (`any` -> want `"none"`) |
| `position.weight` | number >= 0, default 0.3 | score weight per mm (as the access rule weights: tuner back 0.5, eq/boost front 0.3, drive 0.1) | access `weight`; side: the new `position` term |
| `position.strength` | `preferred` (default) / `required` | required: a steep penalty in the search, a proposal gate, a build warning when not met (6) | new |
| `pin` | true / false (default) | the layout search never moves or rotates this pedal | `layout.pins` (pedal ids) |
| `rotations` | list of 0 / 90 / 270, or `"any"`, or `"current"` | rotations the search may give it (180 never; the owner's current rotation is always allowed, as today) | `layout.rotations.<id>` |
| `order.<name>` | today's rule entry minus `id` / `pedal`: `type` (after, before, after_group, before_group, position, no_buffered_before, as_early_as_possible) + its fields, `strength` (required), `priority` (default 0), `reason` | an ordering wish; the rule id is `<pedal>.<name>` (so every live id survives the migration unchanged, `rule_overrides` and messages keep working) | `rules[]` entries with `"pedal": <id>` |
| `power.own_output` | true / false | alone on its supply output | new (today only by hand wiring) |
| `power.supply` | a supply INSTANCE id of `power.supplies` (`psu1`) | on this supply | new |
| `power.port` | a port of that instance's catalog supply (`F1`); needs `supply` | on this output | new |
| `power.voltage_v` | number | operating voltage | `power.assign(run_v=)` takes it today from the hand wiring; a wish wins over it |
| `power.strength` | `preferred` (default) / `required` | see 8 | new |
| `toppers` | list of this pedal's switch ids (`catalog/footswitches.json` `id`) | a topper on these switches | `footswitches.toppers` ["<pedal>.<switch id>"] |
| `note` | string | owner's note, README only | new |

`name` keys of `order` match `[a-z0-9_]+`. Units mm; unknown values null (a null field = no wish, never "unknown spec": the
`no_unknown` flag does not apply to wishes).

What stays where it is (not per pedal): `signal_chain`, `sections` (orders groups of pedals), `rule_overrides` (decision D9),
`layout.rotations.default`, `layout.access.tags` / `switches`, `layout.weights`, `footswitches.*` other than `toppers`, the
power policy, the catalog's intrinsic rules (`catalog/pedals.json` `dependencies`), and the HAND POWER WIRING
`power.supplies[].outputs[]` (decision D2: it is the board's actual wiring with output-level data, voltage, style, notes and
the daisy order that names the P# cables; a profile holds only wishes about it).

## 4. Reading old keys and migration (the plan's choice: both, with a reason)

1. **Old keys stay readable** through one compatibility layer (`preferences.merge_legacy`): `rules` entries with `"pedal"`,
   `layout.pins` (pedal ids), `layout.rotations.<pedal id>`, `layout.access.pedals`, `footswitches.toppers`. Reason: the
   frozen fixture `tests/fixtures/guitar-gig/project.json` must stay old (it is frozen; the gig tests' expected values depend on it) and so
   keeps testing the compatibility path for free; `--pin` keeps working by adding to `layout.pins`.
2. **A one-off migration script** `scripts/migrate_preferences.py` (`uv run pb migrate-preferences <project...> [--dry-run]`)
   moves the old keys into `pedals.<id>` for the live projects. Reason: the web UI must write ONE place; two sources in a
   live file invite conflicts. Old keys are not a warning (a warning would change the fixture tests' counts); the
   README's Preferences section adds one note line "old keys in use: `uv run pb migrate-preferences <project>`".
3. **Conflict rule**: a wish set in both an old key and the profile is an error only when the values DIFFER (equal = fine,
   which makes the lowering in 5.1 idempotent).
4. On-board supply instances stay in `layout.pins` (they are no pedals; D8).
5. The script writes `project.json` with a formatter that keeps today's style (top-level keys indented, an object that fits
   in 160 characters on one line: one rule / one profile field per line), so the diff is reviewable; `--dry-run` prints it.
6. Proposals: migration changes `project.json`, so `proposal_inputs_sha1` changes and the README marks the proposals stale.
   The script re-stamps `proposals/meta.json` `inputs_sha1` ONLY when it matched before the migration AND the lowered project
   (5.1) equals the old one key by key (nothing the search reads changed) (D10).

## 5. Modules and functions

### 5.1 New `scripts/preferences.py` (pure, no files)
- `KEYS`, `SIDES = ("left", "right", "any")`, `DEPTHS = ("front", "back", "avoid_front", "any")`, `STRENGTHS`,
  `DEFAULT_WEIGHT = 0.3`, `DEFAULT_STRENGTH = "preferred"`.
- `profiles(project) -> {pedal id: profile}`: `project["pedals"]` merged with the old keys (`merge_legacy`), each field
  normalised (defaults filled, rotations as given).
- `validate(project, cat_pedals, cat_supplies, fs_data, chain) -> (errors, warnings, notes)`: schema and references (7).
- `lower(project) -> project copy` with the old keys FILLED from the profiles: `rules` (old entries first in their order,
  then profile rules: pedals in chain order, then pedals not in the chain alphabetically, names in their dict order; equal
  duplicates dropped), `layout.pins`, `layout.rotations.<id>`, `layout.access.pedals.<id>` (from `position.depth` + weight),
  `footswitches.toppers`. Idempotent (`lower(lower(p)) == lower(p)`). This is the core trick: every existing reader (rule
  engine, `layout.settings`, `Model`, `footswitches.topper_settings`) stays untouched and the live projects build the same
  by construction.
- `side_wishes(project, ids)`, `power_wishes(project) -> {pedal: {own_output, supply, port, voltage_v, strength}}`: views
  for the new consumers.
- `met_position(wish, ref_point, board_rect) -> (met, detail mm)` (shared by the build and the proposal metrics),
  `met_power(wish, wiring rows, pedal)`, `met_rotation(allowed, rot)`.

### 5.2 `scripts/build.py`
- `validate`: `project = preferences.lower(jacks.with_floor(project))` at the top; `preferences.validate` findings added;
  the rule loop records per rule id its status in `ctx["rule_status"]` {id: met | broken | overridden | skipped | disabled}
  (from `broken`, `overridden`, `skipped`; no change to the messages); after `footswitches.check` a new
  `preferences.check(ctx, cat_pedals)` fills `ctx["preferences"]` = [{"pedal", "kind" (position.side, position.depth,
  pin, rotations, order, power, toppers), "wish" (text), "strength", "met" (True / False / None = not applicable), "detail"}]
  and appends the findings of 6.
- `preferences_section(ctx, cat_pedals)` (README, 9), rendered after "Ordering rules"; `proposals_section` unchanged except
  the proposal gate row (10.3).
- `root_readme`: one paragraph on `pedals.<id>` (the documented schema for hand editing).

### 5.3 `scripts/layout.py`
- `settings(project)`: works on `preferences.lower(project)` (callers may pass an unlowered project, e.g. tests).
- `access_rule`: an override with want `"none"` returns None (the `any` depth).
- `Model.__init__`: `self.side_pref` per movable pedal {"want", "weight", "required"} from `preferences.side_wishes`;
  `self.depth_required` per pedal (the access rule says "how much", required says "must be met").
- `Model.score`: new term `position` (weight `layout.weights.position` 1.0): side: weight x distance of the body centre x
  from the wanted edge of `self.board` (as `access` does for depth, linear, always pulling); plus for a REQUIRED wish (side
  or depth) not met (reference point not in the wanted half): `preference_miss` 100 + `preference_miss_mm` 20 / mm beyond
  the half line (weights in `WEIGHTS`). `det["preferences"]` lists the unmet ones. Pins / rotations: unchanged code (fed by
  the lowering).
- Module docstring: the `position` term.

### 5.4 `scripts/power.py`
- `assign(..., wishes=None)` (8); `output_findings` unchanged.
- `wish_findings(wishes, supplies_rows) -> [(pedal, text, strength)]` for the build check of the hand wiring.

### 5.5 `scripts/propose_layout.py`
- `main`: `project = preferences.lower(...)` before `--pin` is merged; `evaluate` passes `wishes=preferences.power_wishes(project)`
  to `power.assign`; `metrics` adds `"preferences": {key: met}` (key `<pedal>.<kind>[.<name>]`) and `"pref_required_unmet"`;
  `rank_key` / `acceptable` use `pref_required_unmet` (10.3); `print_score` prints the `position` term.

### 5.6 `scripts/footswitches.py`
No code change: `topper_settings` reads the lowered `footswitches.toppers`. Its message names `footswitches.toppers`; the
validation in `preferences.validate` reports a bad `pedals.<id>.toppers` entry with the profile path first (7), so the owner
never sees a message about a key he did not write.

### 5.7 New `scripts/migrate_preferences.py`, `pb/__init__.py` command `migrate-preferences`; `common.dump_project(doc)` (the formatter of 4.5).

## 6. Findings (build)

| Wish | Not met in the owner's layout / hand wiring |
|---|---|
| order | exactly today's messages (`order (required|preferred): <rule id>: needs ...`), errors / warnings as today |
| position, required | warning `preferences: <pedal>: wants the <left|right|front|back> half (required); its <reference> is <N> mm past the middle` (error with `validation.strict_preferences`) |
| position, preferred | README only |
| power, required | warning `preferences: <pedal>: wants <own output | supply psu1 | port psu1.F1 | 18 V> (required); the wiring puts it on psu2.F1 with <x, y>` (error with `validation.strict_preferences`) |
| power, preferred | README only |
| rotations | README only (the search's allowed set; the owner's rotation is always allowed) |
| pin, toppers | applied settings: README shows "applied", never a finding |

## 7. Validation messages (errors unless noted)

- `pedals: '<id>' is not in catalog/pedals.json`
- a profile of a catalog pedal not in `signal_chain`: no finding, README "dormant" (as today's skipped rules; D11)
- `pedals.<id>: unknown key '<k>' (known: position, pin, rotations, order, power, toppers, note)`
- `pedals.<id>.position.side must be left, right or any, got ...`; same for `depth` (front, back, avoid_front, any),
  `strength` (required, preferred), `weight` (a number >= 0)
- `pedals.<id>.pin must be true or false`; warning `pedals.<id>: pinned, so its rotations wish has no effect` when both are set
- `pedals.<id>.rotations must be a list of 0, 90, 270, or "any" / "current", got ...` (180: `... 180 is never allowed`)
- `pedals.<id>.order: '<name>' is not a valid name ([a-z0-9_]+)`; type and field errors reuse today's rule messages with the
  derived id (`rules: <pedal>.<name>: unknown rule type 'x'`); `rules: duplicate rule id` covers an id in both places that differs
- `pedals.<id>.power.supply '<s>' is not a supply instance of power.supplies (psu1, psu2)`
- `pedals.<id>.power.port '<p>' is not a port of <supply catalog id> (F1, F2, ...)`; `... port needs supply`
- `pedals.<id>.power.voltage_v <v> is outside the pedal's range <min>-<max> V`; `... no output of the project's supplies offers <v> V`
- `pedals.<id>.power: own_output with port <p> but the wiring shares <p>`: only a finding of 6, not a schema error
- `pedals.<id>.toppers: '<s>' is not a footswitch of <id> (bypass, switch_2)`; without footswitch data: warning (as today)
- conflict: `pedals.<id>.<field> and <old key> disagree: <a> vs <b>` (4.3)

## 8. Power assignment (`power.assign(wishes=)`)

- `volts[p]` = the wish's `voltage_v`, else `run_v` (the hand wiring), else `default_voltage` (today).
- REQUIRED wishes are feasibility: `slot_check` returns infeasible when a member's `supply` / `port` differs from the slot, or
  when a member with `own_output` shares the slot. `greedy`'s "alone" set also takes `own_output` pedals first. A start
  wiring (`from_wiring`) that breaks one is dropped by the existing `total(s) is not None` filter; no wiring at all -> the
  existing ValueError -> the proposal keeps the owner's wiring (existing fallback) and the proposal table shows the error.
- PREFERRED wishes are a cost: `total` adds `PREFERENCE_COST_MM` (300, below `WARNING_COST_MM` 1000: a wish yields to a build
  warning, beats 30 cm of DC cable) per unmet wish (D7).
- Return value gains `"preferences": [(pedal, wish, met)]`.

## 9. README table "Preferences"

After "Ordering rules". Intro line (where the wishes live, how "met" is judged: the requested half of the board for side /
depth, the chain for order, the wiring for power). One row per wish; columns: Pedal | Wish | Strength | Owner's layout |
Proposal 1 | ... | (proposal columns only when `proposals/meta.json` exists and is not stale; a proposal made before this
feature shows `?`). Cells: `met`, `**not met** (<detail>)`, `applied` (pin, toppers), `-` (not applicable). Order rows are the
same in every column (the proposals keep the chain). The owner's power column uses the hand wiring, a proposal's its own
wiring (as the proposal table already says). Below: "Dormant (pedals not in the chain): ..." and the old-keys note. No
profile and no old keys: one line "No preferences set (`pedals.<id>` in project.json)".

## 10. Layout search

1. Pins, rotations, depth: through the lowered `layout.*` keys, no change in the search code.
2. Side and required misses: the `position` term (5.3). Required is NOT a hard constraint: a hard one could make the owner's
   start infeasible (the search starts from it; `repair_start` handles only the usable area), and the penalty plus the gate
   already keep a proposal from breaking it (D4).
3. Proposal gate: `acceptable` adds `m["pref_required_unmet"] <= owner["pref_required_unmet"]`; `rank_key` puts it after
   `fs_close`. With no wishes it is 0 everywhere, so today's results do not change.
4. `proposal_inputs_sha1` already hashes project.json: changed wishes make proposals stale (wanted).

## 11. Tests (hand-computed, pytest)

`tests/test_preferences.py`:
1. `lower` maps each field to its old key (pin, rotations "any"/"current"/list, depth -> access with weight, `any` ->
   `"none"`, toppers -> "<pedal>.<switch>", order -> rule with id `<pedal>.<name>` and `pedal`).
2. `lower` is idempotent; old + equal profile = no error; old + different = the conflict error.
3. Rule order of `lower`: old entries first, then chain order, then dormant pedals alphabetically.
4. Every message of 7 (one small case each).
5. Equivalence on the frozen fixture: `migrate(fixture project)` -> validate both (`gig_copy`) -> same SORTED errors and warnings,
   same cable `min_mm` (signal and power), same `active_rules` ids as sets, same `overrides`.
6. Migration script: `--dry-run` writes nothing; the formatter round-trips the three live files' content (load(dump(x)) == x);
   re-stamp only when the hash was fresh and the lowered projects are equal.
7. `met_position`: a pedal 10 mm left of the middle with side left = met; 10 mm right = not met, detail 10 mm; depth on the
   footswitch mean (two switches at y 80 and 100 on a 200 mm deep board = 90: back half met).
8. `layout.Model` `position` term: one pedal, side left, weight 0.3, centre 50 mm from the left edge -> 15.0; required and
   20 mm past the middle -> + 100 + 400.
9. `access_rule` with want `"none"` -> None (a tuner with depth `any` loses its tag rule).
10. `power.assign`: required port honoured even when longer; required `own_output` keeps the slot single; preferred port
    yields when it costs > 300 mm of cable and is kept below; voltage wish beats `run_v`; an impossible required wish raises
    ValueError.
11. Build findings: required side not met -> warning; with `strict_preferences` an error; preferred -> no finding, README `**not met**`.
12. README table: owner column, stale meta -> no proposal columns, old meta without "preferences" -> `?`.
13. `propose_layout.acceptable` rejects a proposal with more unmet required wishes than the owner's layout.
14. Gig regression: with no profiles the fixture's surrogate score and ranking are unchanged (existing agreement tests keep passing).

## 12. Implementation steps (one Sonnet handover each, in order, all on `feat/pedal-preferences`)

1. **Profiles + lowering, no behaviour change.** `scripts/preferences.py` (`profiles`, `merge_legacy`, `lower`, `validate`),
   called by `build.validate`, `layout.settings`, `propose_layout.main`. Tests 1-4, 5 (with an in-test migration helper),
   14. Acceptance: `uv run pb build` output byte-identical for the three live projects (no `pedals` key yet), all tests pass.
2. **Migration script.** `scripts/migrate_preferences.py`, `common.dump_project`, `pb migrate-preferences`, test 6. Run it
   with `--dry-run` on the three projects and attach the diffs to the review; the owner decides whether to apply (the agent
   does NOT write the live project.json files).
3. **Position wishes + build check.** `layout.py` term `position`, `access_rule` "none", `preferences.met_*`, `preferences.check`,
   `ctx["rule_status"]`, `ctx["preferences"]`, findings of 6 for position, `validation.strict_preferences`. Tests 7-9, 11.
4. **Power wishes.** `power.assign(wishes=)`, `power.wish_findings`, build findings for power, `propose_layout.evaluate`
   passes the wishes. Test 10 (+ 11 for power).
5. **README + proposals.** `build.preferences_section`, `propose_layout.metrics` / `rank_key` / `acceptable`, meta.json
   `preferences`, root README paragraph, `CLAUDE.md` (project.json bullet: `pedals.<id>` schema; conventions: lowering, old
   keys), `docs/TODO.md` 3.1 ticked. Tests 12, 13.

Each step ends with `uv run pb test` and `uv run pb build` (the live READMEs may change only in steps 3 and 5, by the new
section).

## 13. Risks

- **README rule order** changes once the live projects are migrated (rules then come per pedal in chain order); findings are
  the same (test 5 compares sorted lists). Accept, or sort the README's rule list by chain position now so it never moves.
- **Stale proposals** after the migration: handled by the re-stamp (4.6); otherwise a proposals rerun (~minutes per board).
- **Two sources** during the transition: the conflict rule (4.3) makes disagreement an error, never a silent winner.
- **Name clash**: board `position` (left/right/front/back) vs the order rule type `position` (first/last) inside
  `order.<name>.type`. Different levels, documented; renaming the rule type would change live ids' meaning, so not done.
- **Required wishes unsatisfiable** (two pedals both pinned to port psu1.F1 with `own_output`): `power.assign` raises, the
  proposals keep the owner's wiring; the build already reports the hand wiring.
- **"Met" by halves is coarse** on the narrow Duo 2.1 (142 mm deep): a pedal can be "back" yet only 5 mm from the middle.
  The detail column shows the mm; a `within_mm` field can come later (D5).
- **Score change**: the new term is 0 without side wishes or required misses, and the depth path is today's access code, so
  existing tests and proposals are unaffected until the owner sets wishes.

## 14. Decisions for the owner (recommended default first)

- **D1 Old keys**: keep reading them + one-off migration script for the live projects (rec.) / migration only (the frozen
  fixture would have to change) / reading only.
- **D2 Hand power wiring**: stays in `power.supplies[].outputs[]`; profiles hold only power WISHES (rec.) / move the wiring
  into the profiles (loses output-level data and the daisy order that names P#).
- **D3 Access override**: becomes `position.depth` (rec., one place for "where on the board") / a separate `access` field.
- **D4 Required position**: steep penalty + proposal gate + build warning (rec.) / a hard constraint in the search.
- **D5 "Met"**: the reference point is in the requested half of the board (rec.) / within N mm of that edge.
- **D6 Defaults**: `strength` preferred for position and power (order keeps its explicit strength); `weight` 0.3.
- **D7 Preferred power wish cost**: 300 mm of DC cable per unmet wish (rec.; a build warning costs 1000).
- **D8 Pins of on-board supplies**: stay in `layout.pins` (rec.) / a new `power.supplies[].pin`.
- **D9 `rule_overrides`**: stays top-level, also for the catalog's intrinsic rules (rec.) / per pedal in the profile.
- **D10 Proposals after migration**: re-stamp `meta.json` when nothing the search reads changed (rec.) / rerun proposals.
- **D11 Profiles of pedals not in the chain**: kept, listed as dormant, no finding (rec., as today's skipped rules) / warning.
- **D12 README rule order**: accept the one-time reordering (rec.) / sort by chain position from step 1 on.
