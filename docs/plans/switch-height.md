# Plan: footswitch height and reach (`feat/switch-height`)

Status: plan only (2026-11-13). Nothing here is implemented. Implementation starts with the recommended defaults in
"Decisions for the owner".

## 1. Goal

The owner's backlog item (2026-10-27): a low pedal at the back of the board is harder to reach; a tall pedal is easier to
reach and may not need a topper. Today the footswitch model is flat. Every switch is a point on the canvas, and toppers add a
fixed 4.5 mm to the effective distance of a pair. This plan adds two things that use the pedal heights already in
`catalog/pedals.json` (`height_mm` = the footswitch top above the pedal's base):

1. **Height step in the spacing**: two neighbouring switches at different heights are harder to hit with one stomp than two
   level switches. The step adds part of itself to the pair's effective distance.
2. **Reach (shadow)**: a switch is "shadowed" when a taller switch stands just in front of it, in the path of the foot.
   The build reports shadowed switches, the topper suggestions weigh them, and the layout search (optionally) avoids them.

This is an approximation, not a 3D model. There are no shoe shapes and no knobs. Every pedal stands on the same flat deck
unless `deck_rise_mm` says otherwise.

## 2. What exists (code this plan touches)

- `scripts/footswitches.py`: `crowding(d, priority, comfort)`, `effective_distance(d, n_toppers, bonus)`, `topper_settings`,
  `suggest_toppers(pts, prs, prio, comfort, bonus, existing, max_toppers, min_gain, types)` (greedy), `points`, `pairs`,
  `check(ctx, cat_pedals, fs_data)` (fills `ctx["footswitch_points" | "footswitch_pairs" | "footswitch_settings" |
  "footswitch_suggestions"]`). Constants `COMFORT_MM` 100, `TOPPER_BONUS_MM` 4.5, `MAX_TOPPERS` 5, `TOPPER_MIN_GAIN` 0.02,
  `TOPPER_TYPES` ("bypass",).
- `scripts/layout.py`: the surrogate footswitch term (`Model.score`, about line 1121: crowding on plain distances, optional
  `min_distance_mm` penalty, repair `issues`), the `access` term (depth of a pedal's mean footswitch y from the front edge),
  `WEIGHTS`, `settings(project)`.
- `scripts/build.py`: `footswitch_section(ctx, cat_pedals)` (README: crowding text, closest pairs table, "Suggested toppers"),
  the proposals table rows "Footswitch crowding" / "Closest footswitch pair", the help text near line 1106.
- `scripts/preferences.py`: per-pedal profiles lower `pedals.<id>.toppers` to `footswitches.toppers`. Nothing changes there.
- Data: `height_mm` is known for every chain pedal of the three projects. Gig fixture range: 38.1 mm (flight_delay, the
  fixture's chain) to 63.5 mm (fulldrive_2). Practice: 45.0 to 69.9 mm (octahive). Bass: 43 to 53.3 mm.

## 3. The model

Notation: canvas mm, y grows toward the FRONT of the board (the player). `y_front` = the front edge of the board footprint
(`layout["board_rect"][3]`; for a composed board, the bounding box). For a switch s on pedal p:

```
H(s)      = height_mm(p) + deck(s)                       switch top above the floor line of the deck (mm)
deck(s)   = deck_rise_mm x (y_front - y_s) / board_depth  0 on a flat deck (default deck_rise_mm = 0)
H_t(s)    = H(s) + topper_mm  if s has a topper, else H(s)     (topper_mm = topper_bonus_mm, see D3)
```

An unknown `height_mm` (null) leaves H undefined. Every height term that touches that switch is then skipped: no step, no
shadow on it or from it. The build gives one aggregated warning per project.

### 3.1 Spacing: height step

For a pair (a, b) on different pedals at plain distance d (centre to centre, as today):

```
step(a, b) = height_gain x min(|H(a) - H(b)|, height_cap_mm)        # toppers NOT included (D2)
d_eff      = d + n_toppers x topper_bonus_mm + step(a, b)
crowding   = priority x max(0, comfort - d_eff)^2 / comfort         # unchanged formula
```

Defaults: `height_gain` 0.5, `height_cap_mm` 10 (estimates). Why half: a step protects in ONE direction only. Stomping the
higher switch leaves the lower one alone. Stomping the lower one puts the higher one under the sole first. Half the step is
the average over the two directions. Why a cap: once the step is larger than a switch's travel plus the sole's give, a
bigger step protects no more. 10 mm is about two toppers. The 4.5 mm topper bonus already says "a few mm of height is worth
the same mm of distance", so a full step of 10 mm counts as 5 mm of distance.

Toppers stay out of the step on purpose. If a topper raised H inside the step, a topper on the TALLER switch of a pair would
gain 4.5 + 2.25 mm and one on the shorter switch only 4.5 - 2.25 mm. The suggestions would then favour topping tall pedals,
which is the opposite of the owner's intuition ("a tall pedal may not need a topper"). The topper keeps its fixed bonus, and
its height counts in the reach model (3.2), where raising a LOW switch is what helps.

**Worked example 1** (gig fixture `tests/fixtures/guitar-gig/`, priorities bypass 1.0 / boost 0.8, comfort 100):

| Pair | d (mm) | heights (mm) | step | d_eff | crowding now | with step |
|---|--:|---|--:|--:|--:|--:|
| danelectro_3699.bypass / fulldrive_2.switch_2 (boost) | 48.52 | 59.0 / 63.5 | 0.5 x 4.5 = 2.25 | 50.77 | (100-48.52)^2/100 = 26.50 | (100-50.77)^2/100 = 24.23 |
| monk.bypass / belle_epoch.bypass | 45.58 | 56.0 / 61.0 | 0.5 x 5.0 = 2.50 | 48.08 | 29.62 | 26.96 |
| beano.bypass / mini_ego.bypass | 65.15 | 53.3 / 53.3 | 0 | 65.15 | 12.14 | 12.14 |

Pair priority = the larger of the two switches' priorities, so 1.0 in all three rows. The board's total crowding goes from
184.3 to 157.4 with the defaults (to 134.0 with gain 1.0). The ranking changes little: the closest pairs are mostly level
pairs.

### 3.2 Reach: shadow of a switch

The foot reaches a back switch from the front. The ball of the foot sits on the switch, and the sole runs forward over the
pedals in front, rising slightly (foot pitch). A taller switch inside that strip is in the way of the sole.

```
corridor(s) = the switches q on OTHER pedals with |x_q - x_s| <= foot_width_mm / 2 and 0 < y_q - y_s <= foot_length_mm
shadow(s)   = max(0, max over q in corridor(s) of [ H_t(q) - H_t(s) - tan(foot_pitch_deg) x (y_q - y_s) ])     (mm)
```

Only switch caps are obstacles: the footswitch is a pedal's tallest point (owner rule), and enclosure heights are unknown
for most pedals. Pedals without a footswitch and on-board supplies are no obstacles (see risks). The shadow uses H_t, so a
topper on s lowers its shadow and a topper on q raises the shadow of the switches behind q.

Defaults (estimates, D4): `foot_width_mm` 80 (corridor half-width 40), `foot_length_mm` 190 (ball of the foot to the heel),
`foot_pitch_deg` 5 (tan = 0.0875). The result depends strongly on the pitch. On the gig fixture, pitch 0 gives 7 shadowed
switches (up to 14.8 mm), pitch 5 gives 2, and pitch 15 gives none (front rows are about 125 mm ahead, and 15 degrees rise
33 mm over that run).

**Worked example 2** (gig fixture, defaults):

- reticon.bypass (46.2 mm, back row, x 119.1, y 67.6). belle_epoch.bypass (61.0 mm, x 116.8, y 192.5) lies in its corridor,
  dy = 124.9: 61.0 - 46.2 - 0.0875 x 124.9 = 14.8 - 10.93 = **3.9 mm**.
- retrovibe.bypass (50.0 mm, x 434.2, y 204.7). fulldrive_2.switch_2 (63.5 mm, x 443.0, y 331.2), dy = 126.5:
  13.5 - 11.07 = **2.4 mm**.
- With a topper (4.5 mm) on reticon.bypass, its shadow is max(0, 3.9 - 4.5) = 0. With a topper on belle_epoch.bypass
  instead, reticon's shadow grows to 8.4 mm.

**Reach cost** (suggestions and search): `reach = Σ_s priority(type of s) x shadow(s)` (mm). The depth from the front stays
with the existing `access` term of the layout search. It is reported, not added again (D5).

### 3.3 Toppers: how the benefit depends on height

Nothing new is needed in the topper formula. The dependence on height comes out of the model:

- Spacing: the gain of a topper is the drop in crowding of its pairs. Pairs already separated by a height step are less
  crowded, and crowding is quadratic, so the same 4.5 mm removes less there.
- Reach: a topper on a shadowed (low, back) switch removes up to 4.5 mm of its shadow. A topper on a tall front switch adds
  shadow to the switches behind it, which counts AGAINST that topper.

`suggest_toppers` minimises `crowding + reach_weight x reach` (`reach_weight` 1.0: one mm of shadow on a bypass switch
weighs one crowding unit). A greedy step's gain = the change of that sum. It is computed from the candidate's own pairs
plus the switches whose shadow involves the candidate (the candidate itself and the switches behind it). Ties as today,
then the larger shadow removed. `topper_min_gain` applies to the combined total at the start. Candidates stay bypass
switches only (`TOPPER_TYPES`). Every switch counts in the reach (a topper in front of a tap switch hurts the tap switch).

Gig fixture, defaults (start: crowding 157.4 + reach 6.3): monk.bypass (4.53), danelectro_3699.bypass (4.23),
analog_chorus.bypass (4.05), ratsbane.bypass (5.29), protein.switch_2 (4.15). Today's list is ratsbane, belle_epoch,
analog_chorus, protein.switch_2, danelectro. ratsbane moves down because its topper alone would shadow analog_chorus.bypass
(53.3 + 4.5 - 47.0 - 0.0875 x 82.7 = 3.6 mm). Once analog_chorus has a topper, ratsbane's topper costs nothing in reach.
belle_epoch drops out: its topper would deepen reticon's shadow. reticon itself is not chosen: 3.9 mm is less than the
other candidates' gains.

## 4. Build and README

`footswitches.check` (with `heights` on, the default):

- `ctx["footswitch_points"]`: each point adds `height_mm` (H, None if unknown), `height_t_mm`, `shadow_mm`,
  `shadow_plain_mm` (without toppers), `shadow_by` (the switch key or None), `depth_mm` (y_front - y).
- `ctx["footswitch_pairs"]`: each pair adds `step_mm`. `effective_mm` = d + toppers x bonus + step, and the sort, crowding
  and `too_close` use it. `crowding_plain` = without toppers but WITH the step (the step is not a choice the owner makes).
  `too_close_plain` likewise.
- `ctx["footswitch_settings"]`: adds `heights` (bool), `height_gain`, `height_cap_mm`, `deck_rise_mm`, `foot_width_mm`,
  `foot_length_mm`, `foot_pitch_deg`, `reach_weight`, `max_shadow_mm`, `reach` (sum with toppers), `reach_plain`,
  `heights_missing` [pedal ids].
- Findings: a warning `footswitches: height unknown for N of M pedals (ids): height step and shadow skipped for them`. With
  `footswitches.max_shadow_mm` set: `footswitch: <key> is shadowed by <key> (X mm, max Y)` as a warning, or an error with
  `validation.strict_footswitches`. There is no default limit, so no new warnings on the current projects.

README `footswitch_section`:

- The spacing paragraph explains the step in one sentence (gain, cap, keys).
- The closest pairs table gets a "Step (mm)" column, and "Distance (mm)" becomes plain plus "Effective (mm)". The effective
  column is shown whenever a step or a topper is non-zero.
- New `### Reach`: one sentence on the model (keys and defaults), then a table of the switches with shadow > 0 (with
  toppers): Switch | Type | Height (mm) | From the front (mm) | Shadowed by | Shadow (mm) [| without toppers]. "No switch is
  shadowed." when the table would be empty.
- `### Suggested toppers`: the intro says the objective is crowding + reach. The table gets a "Shadow removed (mm)" column,
  which can be negative.
- Proposals table: new row "Footswitch shadow (sum, mm)" from the build's `reach_plain` of each finalist. It is not a gate.

`footswitches.heights: false` turns all of this off: the build gives exactly today's output. Tests use it as a regression
guard.

## 5. Layout search

- **Step: yes, always (when heights are on).** It is constant per pair of pedals (no position dependency without a deck
  rise; with one, it is linear in y), so the per-pair cost is one addition. Without it, the surrogate's crowding would
  disagree with the build's, and the proposal metrics would mislead.
- **Shadow: yes, new term `reach`** (`layout.weights.reach` default 1.0 per mm x priority, D6) on plain heights (the search
  ignores toppers, as today). The cost is O(switches^2) per evaluation (24 switches on the gig: trivial next to routing).
  A shadow adds a repair issue `(pedal, other pedal, shadow mm)` like a crowded pair, so the move operators see it.
- The depth term (`access`) is unchanged.
- `--score` prints the new `reach` term. `proposal_inputs_sha1` needs no change: `height_mm` is in the project's catalog
  entries, and the new keys live in project.json, which is already hashed.

## 6. Config keys (project.json `footswitches`)

| Key | Default | Meaning |
|---|---|---|
| `heights` | true | false = today's model exactly (no step, no shadow) |
| `height_gain` | 0.5 | mm of effective distance per mm of height step |
| `height_cap_mm` | 10 | the step counts up to this |
| `deck_rise_mm` | 0 | how much higher the deck's back edge is than its front edge (0 = flat; owner to measure per board) |
| `foot_width_mm` | 80 | width of the sole strip in front of a switch (estimate) |
| `foot_length_mm` | 190 | how far forward the sole reaches (ball to heel, estimate) |
| `foot_pitch_deg` | 5 | the sole rises toward the front by tan(pitch) mm per mm (estimate) |
| `reach_weight` | 1.0 | topper suggestions: weight of one mm of shadow (x priority) against crowding |
| `max_shadow_mm` | null | optional: a larger shadow is a finding (warning; strict_footswitches: error) |

`topper_bonus_mm` (4.5) is also the topper's height in H_t (D3). Layout: `layout.weights.reach` 1.0. Validation follows
`topper_settings`: numbers >= 0, pitch 0..45, gain 0..1, a bad value is an error and falls back to the default.

## 7. Tests (hand-computed; gig numbers only from `tests/fixtures/guitar-gig/`)

`tests/test_footswitches.py` (pure):
1. `step`: heights 59.0 / 63.5, gain 0.5 -> 2.25; cap: 40 / 60 with cap 10 -> 5.0; unknown height -> 0.
2. `crowding` with step: d 48.52, step 2.25, priority 1 -> 24.23 (2 dp).
3. Toppers stay out of the step: a topper on either switch changes d_eff by exactly 4.5.
4. `shadow`: s (46.2) and q (61.0) 124.9 ahead, pitch 5 -> 3.87; q laterally 41 mm away (width 80) -> 0; q 191 mm ahead
   (length 190) -> 0; q behind s -> 0; q on the same pedal -> 0.
5. Toppers in the shadow: a topper on s -> max(0, 3.87 - 4.5) = 0; a topper on q -> 8.37.
6. `deck_rise_mm` 20, board depth 300: a switch 150 mm from the front gets +10 mm.
7. `suggest_toppers` with reach: 3 switches where the crowding-only pick would shadow a third switch, so the combined pick
   differs (hand-computed gains). Also: reach weight 0 gives today's result.
8. `heights: false`: `check` output equals today's for a small hand-made layout (pairs, crowding, suggestions).
9. Settings validation: bad gain / pitch / cap -> error + default; unknown keys ignored, as today.

`tests/test_build.py` / README:
10. A hand-made project: the README shows the Step column, the Reach table and "Shadow removed".
11. Unknown height -> one aggregated warning naming the pedal. `max_shadow_mm` -> a warning, and an error with
    strict_footswitches.

`tests/test_layout.py`:
12. Surrogate `raw["footswitch"]` == the build's crowding_plain on the gig fixture (with the step); surrogate `raw["reach"]`
    == the build's `reach_plain`.
13. Hand case: two pedals, a tall one directly in front of a short one, `reach` weight > 0: moving the short one sideways
    by more than foot_width/2 lowers the score by the expected amount.

Existing gig-fixture tests that assert crowding numbers or the topper list will change. Update them deliberately, with the
new hand-checked numbers from this plan (184.3 -> 157.4; the new topper list).

## 8. Implementation steps (one handover each, Sonnet)

Each step lives on `feat/switch-height`, runs the full test suite and ends with `uv run pb build` clean (no new errors).

**Step 1: pure model in `scripts/footswitches.py`.** Add `height_settings(project)` -> (settings, problems) with the keys of
section 6; `switch_heights(pts, cat_pedals, toppers, topper_mm, board_rect, deck_rise_mm)` -> {key: (H, H_t)};
`step_mm(ha, hb, gain, cap)`; `pair_distance(d, n_toppers, bonus, step)` (keep `effective_distance` as a wrapper);
`shadows(pts, heights, cfg)` -> {key: (shadow, by)} with a `toppers` argument. Tests 1-6 and 9. Do not touch `check`,
build.py or layout.py. Files: scripts/footswitches.py, tests/test_footswitches.py.

**Step 2: build integration.** In `check`: compute heights, steps and shadows, the new ctx fields, the warnings and
`max_shadow_mm`. Extend `suggest_toppers` with optional `heights=None, shadow_cfg=None, reach_weight=0`. Without them the
result equals today's, so existing callers and tests keep working. The objective and the gain follow section 3.3.
README changes in `build.footswitch_section` and the help text near build.py line 1106. Tests 7, 8, 10, 11. Update the
gig-fixture tests whose numbers change, and say which. Files: scripts/footswitches.py, scripts/build.py, tests.

**Step 3: layout search.** In `layout.Model`, precompute each pedal's switch heights. Add the step to the pair distance in
the footswitch term, through the same `footswitches.step_mm`. Add the `reach` term (`WEIGHTS["reach"]` 1.0) with repair
issues. Add the term to `--score`, and the proposals table row "Footswitch shadow (sum, mm)" from the finalists' build
ctx. Tests 12, 13. Files: scripts/layout.py, scripts/propose_layout.py, scripts/build.py (proposals row only),
tests/test_layout.py.

**Step 4: docs.** CLAUDE.md (the footswitch and topper conventions: the step, the shadow, the keys) and the module
docstrings of footswitches.py / layout.py (the term list). Regenerate the READMEs (`uv run pb build`). Proposals: the owner
reruns `pb propose` when they want new proposals; the agent does not.

## 9. Risks

- **Invented foot geometry.** Width, length and pitch are estimates, and the shadow depends strongly on the pitch (0 / 5 /
  15 degrees give 7 / 2 / 0 shadowed switches on the gig). Mitigation: defaults marked "estimate" in the README; the owner
  can measure his own foot and stance; `max_shadow_mm` stays off by default.
- **Heights are partly retailer figures** (`height_info.confidence`). A 2 mm error changes a step by 1 mm: harmless.
- **Board deck:** neither board's deck slope is known. A sloped deck (back higher) would cancel most shadows. Default 0.
- **Obstacles are switch caps only.** A pedal with no footswitch, a tall knob or an on-board supply in front is not seen.
  The owner rule makes the switch the tallest point, so this is acceptable for now.
- **Score drift:** the new terms change crowding numbers, topper lists and proposals. The frozen-fixture tests are updated
  once, on purpose. The `heights: false` switch keeps the old behaviour reachable.
- **Asymmetry folded into a constant:** the step's 0.5 averages two directions. A pair that the owner only ever stomps one
  way is mis-weighted. This is acceptable for comfort scoring.

## 10. Decisions for the owner (implementation starts with the recommended defaults)

- **D1. Should a height step count as spacing?** Recommended: yes, `height_gain` 0.5, `height_cap_mm` 10 (half the step,
  at most 5 mm of distance). Alternative: no, use heights for reach only.
- **D2. Do toppers enter the step?** Recommended: no. Toppers keep their fixed bonus and count in the reach only, so the
  suggestions do not favour topping tall pedals.
- **D3. What is a topper's height in the reach model?** Recommended: the same value as `topper_bonus_mm` (4.5), no new
  key.
- **D4. Foot geometry.** Recommended: width 80 mm, length 190 mm, pitch 5 degrees, all estimates. The owner may measure
  them.
- **D5. Should the depth from the front enter the reach cost?** Recommended: no. It stays in the existing `access` term of
  the search and is shown in the README Reach table. Depth weighting of the spacing: none.
- **D6. Should the layout search use the shadow?** Recommended: yes, `layout.weights.reach` 1.0 (the step is always
  used).
- **D7. Should a shadow be a finding?** Recommended: no by default. `footswitches.max_shadow_mm` is opt-in (warning;
  strict_footswitches: error).
- **D8. Deck slope.** Recommended: `deck_rise_mm` 0 until the owner measures the deck height at the front and back edges
  of each board (Fender Professional M, RockBoard Duo 2.1).
- **D9. Topper suggestion weight.** Recommended: `reach_weight` 1.0. One mm of shadow on a bypass switch weighs as much as
  one crowding unit, which makes a 4 mm shadow comparable with a typical topper's crowding gain (4-6) on the gig.
