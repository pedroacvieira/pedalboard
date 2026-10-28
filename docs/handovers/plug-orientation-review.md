# Handover: plug-orientation, fix the code review findings

Branch `feat/plug-orientation` (checked out; do not commit, the coordinator commits). Python 3.12, `uv run` only
(`uv run pytest tests -q`, ~60 s; `PEDALBOARD_SLOW=1 uv run pytest tests -q -k gig`; `uv run scripts/build.py`).
CLAUDE.md has an uncommitted edit by the coordinator: leave it alone.

## Context (the feature, briefly)
`scripts/routing.py`: plug-to-plug collisions (`collision_count`, `fixed_footprints`, `power_plug_keys`,
`plug_collision_findings`, `ctx["plug_collisions"]`), right-angle plugs pointing `down` into a board hole
(`down_available`, `end_options(..., down=)`), several DC plug types (`power_types`, `power_candidates`, `plug_rank`,
`exit_feasible`, `power_plug_pool`, `power_plug_choices`). `scripts/layout.py` mirrors them in the surrogate
(`_cands`, `_infeasible`, `_resolve`, `_count`, `_parts`, the power term). Owner rules: ranking per plug end =
feasible first, then down (always down when available), then blocked parts + collisions, then length (signal) /
overlap + type list order (power); one pedal-end DC type per serial cable.

## Findings to fix (line numbers approximate)
1. **Signal sides cannot see the DC plugs** (routing.py ~1627): power jacks are in `modelled`, so no box in `taken`,
   and their plugs are chosen after all signal sides. Gig: monk.out, red_muck.out, reticon.out, danelectro_3699.out
   collide with their own pedal's DC plug. Fix: iterate the choice: pass 1 as today; then re-choose the signal sides
   with `taken` = fixed boxes + the current DC plugs + the other signal plugs, then re-choose the DC plugs against
   the new signal plugs; repeat until nothing changes (max 3 rounds; the side search memo makes repeats cheap). Keep
   the ranking order of the owner rules. Mirror it in `layout.py` `_resolve` (it already re-chooses colliding ends;
   make it consider DC plugs when re-choosing signal ends). Report the gig collisions before/after.
2. **`exit_feasible` tests a down option against the TOP area** (routing.py ~2074; layout.py `_infeasible` ~271): a
   down plug continues under the board: test its bend point against the under area (board footprint, `ug.inside` /
   the board rect) instead. Test: a front-facing plug of the lowest pedal over a hole in front of front_y goes down.
3. **Fixed box vs fixed box** (`plug_collision_findings`): skip pairs where BOTH footprints are fixed boxes of the SAME
   item (nothing can clear them). Same in the surrogate's collision cost. Test.
4. **Surrogate `_cands` drops side options when down fits** (layout.py ~235): the build ranks feasibility first. Cheap
   fix: keep the side options available as a fallback when the down end is infeasible for the surrogate (e.g. its
   under cell is inside an under-board supply grown by the radius, which `down_available` already rejects: then
   down is simply not available). If there is no cheap test that matches the build's connectivity mode, leave it and
   write the approximation in the docstring. Say what you did.
5. **Power term bias against down plugs** (layout.py ~655): down plugs add their full `measure_mm` (offset + jack
   height + deck) at both ends and again as the next serial hop's lead, side plugs add no measure. Make both
   comparable: the same measure convention for side and down ends (e.g. side: its measure point, as today, plus
   nothing; down: the extra cable beyond a side plug = jack height + deck transit, and the hop then starts / ends
   under, so it does NOT pay the hole pass a side plug would pay; count it once per plug, not per hop). Hand-computed
   test: a hop whose target sits over a hole costs no more than the same hop with a side plug that has to go down
   through that hole.
6. **`power_candidates` accepts a non-power override type** (routing.py ~2051): only a type with role `power` may be
   used (the error is already reported; the router must then ignore the override). Test.
7. **`jacks.check` estimate uses the default DC type** (jacks.py ~290): fine as an estimate; add one sentence to its
   docstring / the README "~" note that the estimate uses the default type. No logic change.
8. **`power_plug_keys` duplicates `power_plug_choices`' enumeration** (routing.py ~669): share one helper that lists
   the DC plug jacks (key, item, jack, cables), used by both.
9. **`collision_count` recomputed per (oa, ob) pair** (routing.py ~1690): compute it once per option, add only the
   end-to-end term per pair. Same results.
10. **`layout.py` `_count` / `_parts` duplicate the collision count**: reuse `routing.collision_count` (or a shared
    helper in routing / design) unless that costs the search noticeable time (measure; if it does, keep the copy and
    add a test that both agree on a few cases).
11. **A chosen DC plug may be unroutable although another option routes** (from phase 3's gig trial with
    `power_types: [dc_ra_owner_baseline, dc_straight_owner_baseline]`: monk.power picks the straight plug, 2 hits
    vs 3, one of them 28 mm into the Belle Epoch, and P3 has no free path). Fix: after `route_power`, for each power
    leg with no path, mark the chosen options of its two plugs infeasible (`ok=False`) and redo the choice and the
    routing once (only if any plug has another option). Test with synthetic types. Re-run that gig trial (project dict
    copy passed to `build.validate(..., project=...)`, not saved) and report monk.power.

## Acceptance
- All tests pass (normal and `PEDALBOARD_SLOW=1 -k gig`), `uv run scripts/build.py` exit 0.
- Gig before/after with `uv run python /tmp/claude-1000/-home-pvieira-projects-pedalboard/08007042-4064-4da5-be57-4d44a51608ea/scratchpad/snap.py guitar-gig <out.json>`: changed exits / lengths and
  the collision / clearance findings (expect fewer collisions after 1). Build time of the gig (today ~1.5 s) and
  `time uv run scripts/propose_layout.py guitar-gig --seed 1 --top 1` (today ~21 s; restore `projects/guitar-gig/proposals/`
  with `git checkout` afterwards).
- Short report per finding: fixed how / left as is and why.

## Do not touch
`catalog/`, `projects/*/project.json`, `playground_design.json`, `projects/*/proposals/`, CLAUDE.md, docs/TODO.md, the plan.

## Status (2026-10-28, session stopped by the owner: out of tokens)
- Committed on the branch: catalog step, phases 1-4 (`3e4ec49`, `bb.. phase 2`, `e65c347`, `c7d8e28`), CLAUDE.md update.
- This review-fix task was STOPPED mid-edit (it was rewriting a block of `route_project` around lines 1650-1760 for
  finding 1). Its partial, untested diff of `scripts/` and `tests/` is saved in
  `docs/handovers/plug-orientation-review-wip.patch`; the working tree was reset to the last commit. Next time:
  either `git apply` the patch and finish/verify it, or start the findings again from the clean tree (simpler if the
  patch does not pass the tests). No finding is confirmed fixed.
- After the fixes (plan "How to run this" step 4): update `docs/TODO.md` (tick the plug-orientation item; open points:
  the gig's remaining collisions, whether to enable `power_types` with the straight plug on the gig, measure
  `jack_height_mm`), regenerate the gig proposals (`uv run scripts/propose_layout.py guitar-gig`, then
  `uv run scripts/build.py`), then ask the owner before merging into `main`.
- Gig numbers at `c7d8e28`: 14 warnings (4 blocked plugs, 10 plug collisions), 6 plugs point down, signal 2442 mm, DC
  3268 mm. The snapshot script `snap.py` was in a temporary scratchpad and is gone: rebuild it from
  `build.validate(...)["cable_list"]` + warnings if needed.
