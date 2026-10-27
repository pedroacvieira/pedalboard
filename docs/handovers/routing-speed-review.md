# Handover: fix the code review of feat/routing-speed

Branch `feat/routing-speed` (checked out, committed). Do not commit; the reviewer commits. `uv run` only; tests
`uv run pytest tests -q`; build `uv run scripts/build.py`. No new dependencies. Do not edit CLAUDE.md / docs / data.

**Every result must stay identical** (the point of the branch): after your changes, all generated files
(`uv run scripts/build.py`, then `git status` shows nothing under `projects/`) and the output of
`uv run scripts/propose_layout.py guitar-gig --dry-run --seed 1` (minus the runtime line) must equal the current ones;
save the baseline first. The previous agent's fuzz scripts and baselines are in
/tmp/claude-1000/-home-pvieira-projects-pedalboard/fb554727-0b3c-4fdb-baa1-941120e25bae/scratchpad/speed (rerun them).

Fix each finding (line numbers approximate); report per finding fixed / not changed and why, plus the timings
(gig validate, default dry run, test suite) after.

1. `routing.py` ~507 `astar_layers`: `under_open | {start}` copies the whole passable set on every search whose
   under-board start is a wall (every power cable from an under-board supply). Handle start/goal with an explicit check
   instead of a copy.
2. `routing.py` ~490 `_search_cells`: same for plug ends inside a wall (`cells | set(add)` per call). Same fix.
3. `routing.py` ~657 `_search` memo: a memo entry that missed once can never hit again (history only grows); drop or
   flag it on the first miss so later rounds do not re-validate it.
4. `layout.py` ~586 `Model._near_memo` (up to 400k entries, big-int masks) and `_rect_bits`: bound the memory (e.g. a
   much smaller LRU, or clear per restart / per score call where the hit rate is low). Measure hit rate and memory
   (tracemalloc peak for one default dry run) before/after; keep the speed.
5. `tests/test_power_routing.py` ~204: the saturated single-hole case was made fast by cutting the iterations to 4.
   Look for a root-cause improvement in `route_all` that keeps results identical (e.g. stop early when a round's
   overflow set and paths are exactly the same as the previous round's AND further rounds provably cannot change them —
   only if provable). If none is safe, keep the test as it is and say why; also add a test that runs that case with the
   default iterations under a generous time bound only if it stays under ~2 s.
6. `power.py` ~292 `_walk_key`: derive the tie-break key from `_ring_offsets` (a cached dict) instead of a second
   closed-form encoding of the same order.
7. `routing.py` ~693 `route_all`: one source for the stacking limit (use `limit(c)` / a precomputed equivalent derived
   from it for both the cost and the overflow check).
8. `routing.py` ~184 `open_cells` / `open_states` cache validated by identity + length only; make it robust (e.g. a
   version counter bumped by every mutation path, or invalidate in the methods that change `blocked` / `body`), and
   key `Under.components` by the top grid as well as `squeeze`.
9. `tests/test_layout_io.py` ~40 and `tests/test_layout.py`: the lru_cache-shared build ctx can be mutated by a test;
   return deep copies (or module-scoped fixtures returning copies) so tests stay isolated; keep the speed.

## Acceptance
`uv run pytest tests -q` passes; outputs identical as above; fuzz scripts identical; timings reported.
