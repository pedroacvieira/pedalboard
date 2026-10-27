"""Power policy and power assignment (all mm). Pure: no network, no GUI.

- `output_findings` / `merge_18v_findings`: the checks of the power wiring, shared by `build.validate` (the owner's
  wiring in project.json) and `assign` (a wiring computed for a layout), so both apply exactly the same policy:
  operating voltage within the pedal's range, polarity, isolated outputs, digital pedals alone, clocked
  (BBD/digital) pedals never with gain/compressor pedals, mA limits, 18 V pedals sharing 18 V outputs.
- `assign`: puts the chain pedals on the project's supply outputs (ports, voltages, daisy-chain order) for one
  layout, minimising the DC cable length: Manhattan distance between the half-depth measure points of the plugs
  (as `jacks.check`), from the supply port through the daisy chain (a FORKED output, `outputs[].style`: the sum of the
  port -> pedal distances, one cable each). Used for layout proposals; the build keeps
  using the owner's hand wiring in project.json.
"""
import itertools
import math
import re

import design
import routing
WARNING_COST_MM = 1000.0   # a wiring with one more build warning must save more than this much DC cable


def volt_range(pc):
    lo, hi = pc.get("min_voltage_v"), pc.get("max_voltage_v")
    if lo is None or hi is None:
        return "?"
    return f"{lo}V" if lo == hi else f"{lo}-{hi}V"


def policy_settings(project):
    """(noise-sensitive tags, strength of the clocked rule, group_18v) from project `power_policy`."""
    policy = project.get("power_policy", {})
    return (set(policy.get("separate_clocked_from_tags", ["gain", "overdrive", "compressor"])),
            policy.get("strength", "required"), policy.get("group_18v", True))


def output_findings(oid, row_pedals, voltage, limit, out_polarity, pedals, sensitive, pol_strength, isolated=None):
    """(errors, warnings, load mA) of one supply output feeding `row_pedals` at `voltage` (limit in mA, None if the
    port has no such voltage: only the per-pedal checks run). `pedals`: chain pedals by id (others are ignored).
    `isolated`: the port's catalog flag (False: a pedal that needs an isolated output may not use it)."""
    errors, warnings, load = [], [], 0
    for pid in row_pedals:
        if pid not in pedals:
            continue
        pc = pedals[pid]["power_consumption"]
        lo, hi = pc.get("min_voltage_v"), pc.get("max_voltage_v")
        if lo is not None and hi is not None and not lo <= voltage <= hi:
            errors.append(f"{oid}: {pid} would run at {voltage}V but only accepts {volt_range(pc)}")
        pol = pc.get("polarity")
        if pol is not None and pol not in routing.POLARITIES:
            errors.append(f"{pid}: unknown polarity '{pol}' ({', '.join(routing.POLARITIES)})")
        elif pol and out_polarity and pol != out_polarity:
            warnings.append(f"{oid}: {pid} is {pol.replace('_', '-')} but the output is {out_polarity.replace('_', '-')}: "
                            f"use a polarity-reversing cable")
        if pc.get("needs_isolated_output") and len(row_pedals) > 1:
            errors.append(f"{oid}: {pid} needs an isolated output but shares it")
        elif pc.get("needs_isolated_output") and isolated is False:
            errors.append(f"{oid}: {pid} needs an isolated output but this port is not isolated")
        if pc.get("current_ma") is None:
            warnings.append(f"{oid}: {pid} has unknown current_ma (left out of totals)")
        else:
            load += pc["current_ma"]
    if len(row_pedals) > 1:
        pols = {pedals[x]["power_consumption"].get("polarity") for x in row_pedals if x in pedals} - {None}
        if len(pols) > 1:
            errors.append(f"{oid}: center-negative and center-positive pedals share one output (their grounds are "
                          f"joined through the audio cables): give them separate outputs")
        clocked = [x for x in row_pedals if pedals.get(x, {}).get("clocked_noise") is True]
        quiet = [x for x in row_pedals if sensitive & set(pedals.get(x, {}).get("tags", []))]
        if clocked and quiet:
            (errors if pol_strength == "required" else warnings).append(
                f"{oid}: time-based/clocked {clocked} share an output with noise-sensitive {quiet}")
        for pid in row_pedals:
            d = pedals.get(pid, {}).get("digital")
            if d is True:
                errors.append(f"{oid}: digital pedal '{pid}' shares an output with {[o for o in row_pedals if o != pid]}")
            elif d is None:
                warnings.append(f"{oid}: '{pid}' shares an output but its digital status is unknown")
    if limit is not None:
        if load > limit:
            errors.append(f"{oid}: {load} mA exceeds {limit} mA limit")
        elif load > 0.8 * limit:
            warnings.append(f"{oid}: {load} mA is over 80% of {limit} mA")
    return errors, warnings, load


def merge_18v_findings(rows, pedals):
    """Warnings for 18 V outputs that could be merged into one. rows: [{"id", "voltage_v", "pedals", "limit"}]."""
    out = []
    rows18 = [r for r in rows if r["voltage_v"] == 18 and r["pedals"] and r["limit"]]
    for i, a in enumerate(rows18):
        for b in rows18[i + 1:]:
            both = a["pedals"] + b["pedals"]
            if sum(pedals[x]["power_consumption"]["current_ma"] or 0 for x in both if x in pedals) <= min(a["limit"], b["limit"]) \
                    and not any(pedals[x]["power_consumption"].get("needs_isolated_output") for x in both if x in pedals):
                out.append(f"power: 18V outputs {a['id']} and {b['id']} could be merged into one")
    return out


def cable_ids(supplies):
    """{pedal id: power cable id} of a project-style wiring (`power.supplies`): P1, P2... in the order jacks.check
    lists the power cables (supply, output, daisy chain), so `cables.overrides.<P#>` can follow its pedal."""
    ids, n = {}, 0
    for s in supplies:
        for o in s.get("outputs", []):
            for pid in o.get("pedals", []):
                n += 1
                ids.setdefault(pid, f"P{n}")
    return ids


def remap_overrides(overrides, old_supplies, new_supplies):
    """`cables.overrides` with the power cable entries renumbered from one wiring to another (by pedal); a P# entry
    that names no cable of the old wiring is dropped."""
    old, new = cable_ids(old_supplies), cable_ids(new_supplies)
    by_old = {cid: pid for pid, cid in old.items()}
    out = {k: v for k, v in overrides.items() if not re.fullmatch(r"P\d+", k)}   # signal (S#) overrides stay
    for k, v in overrides.items():
        if k in by_old and by_old[k] in new:
            out[new[by_old[k]]] = v
    return out


# --- assignment --------------------------------------------------------------------------------
def manhattan(a, b):
    return abs(a[0] - b[0]) + abs(a[1] - b[1])


HOLE_SAMPLE_MM = 6.0   # spacing of the hole points the power estimate looks for (`hole_sample`)


def hole_sample(hole_rects, spacing=HOLE_SAMPLE_MM):
    """A cheap sample of the points of the board's holes (canvas mm): a grid of `spacing` mm over each hole rectangle,
    centred in it (a rectangle narrower than the spacing gets its centre line)."""
    out = []
    for x0, y0, x1, y1 in hole_rects or []:
        nx, ny = max(1, int((x1 - x0) // spacing)), max(1, int((y1 - y0) // spacing))
        ox, oy = (x1 - x0 - (nx - 1) * spacing) / 2, (y1 - y0 - (ny - 1) * spacing) / 2
        out += [(x0 + ox + i * spacing, y0 + oy + j * spacing) for i in range(nx) for j in range(ny)]
    return out


def edge_sample(segments, spacing=HOLE_SAMPLE_MM):
    """Points ON the board border along the edge segments (`layout["edge_segments"]`, canvas mm), `spacing` mm apart (centred in
    the segment; a segment shorter than the spacing gets its middle): the crossing points of the power estimate."""
    out = []
    for (x0, y0), (x1, y1), _ in segments or []:
        length = math.hypot(x1 - x0, y1 - y0)
        n = max(1, int(length // spacing))
        for i in range(n):
            f = 0.5 if length == 0 else (length - (n - 1) * spacing) / 2 / length + i * spacing / length
            out.append((x0 + (x1 - x0) * f, y0 + (y1 - y0) * f))
    return out


def covered(point, rects):
    return any(r[0] <= point[0] <= r[2] and r[1] <= point[1] <= r[3] for r in rects)


def estimate_setup(project, lay, cable_types):
    """What the layout-level power estimate needs, or None (then Manhattan is used): {"index": a `HoleIndex` of the hole
    points of the board that are free under the board (not inside an under-board supply's outline grown by the power
    cable's radius, as the router's hole cells), "edges": a `HoleIndex` of the points on the board border inside the
    owner's edge segments (`edge_sample`, likewise free under the board; never covered by a pedal: they are outside it),
    "cfg": {"top_cost", "transit_mm", "edge_transit_mm"}, "crossings": a `Crossings` of both, "radius": the power cable's
    radius}. `lay`: jacks.layout_from_items's result (its holes, edge segments, under-board supply items and outline shapes). Under-board supplies do not
    move in the layout search, so this is done once per model. None without a power cable type, without holes or with
    `cables.under_board: false`."""
    import routing
    cfg = routing.settings(project, cable_types)
    ptype = cable_types.get(cfg.get("power_type") or "")
    if not ptype or not cfg["under_board"] or not (lay.get("holes") or lay.get("edge_segments")):
        return None
    transit = cfg.get("hole_transit_mm")
    if transit is None:
        transit = lay["hole_transit_mm"] if lay.get("hole_transit_mm") is not None else routing.HOLE_TRANSIT_FALLBACK
    pcfg = routing.power_settings(project, cfg)
    edge_t = routing.edge_transit(pcfg, lay, transit)[0]
    radius = float(ptype["diameter_mm"]) / 2
    under = [r for iid, it in (lay.get("inst_item") or {}).items() if (lay.get("inst_placement") or {}).get(iid) != "on_board"
             for r in design.item_shapes(lay.get("shapes") or {}, it)]
    grown = [(a - radius, b - radius, c + radius, d + radius) for a, b, c, d in under]
    sample = [h for h in hole_sample(lay["holes"]) if not covered(h, grown)]
    edges = [h for h in edge_sample(routing.usable_edge_segments(lay, cfg)) if not covered(h, grown)]
    pw_cfg = {"top_cost": float(pcfg["top_cost"]), "transit_mm": float(transit), "edge_transit_mm": float(edge_t)}
    index, eindex = HoleIndex(sample), HoleIndex(edges)
    if not index and not eindex:
        return None
    return {"index": index, "edges": eindex, "cfg": pw_cfg, "crossings": Crossings(index, eindex, pw_cfg), "radius": radius}


def usable_holes(setup, rects):
    """The crossing points of the setup (`Crossings`) with the hole points that lie in none of `rects` (pedal outlines) grown
    by the power cable's radius (the edge points are outside every pedal), or None when no point is left."""
    r = setup["radius"]
    grown = [(a - r, b - r, c + r, d + r) for a, b, c, d in rects]
    out = Crossings(setup["index"].without(grown), setup["edges"], setup["cfg"])
    return out or None


SCAN_POINTS = 100   # a `HoleIndex` of at most this many points is scanned whole by `nearest`, a bigger one is walked square by square

_RINGS = {}
_RING_POS = {}


def _ring_offsets(r):
    """The (dx, dy) of the squares of ring r round a square, in walk order: the rows dy = -r, r for every dx, then the columns
    dx = -r, r for the dy between."""
    if r not in _RINGS:
        _RINGS[r] = [(0, 0)] if r == 0 else (
            [(dx, s) for dx in range(-r, r + 1) for s in (-r, r)] + [(s, dy) for dy in range(-r + 1, r) for s in (-r, r)])
    return _RINGS[r]


def _ring_position(r):
    """{(dx, dy): position in the walk order of ring r} (`_ring_offsets`), cached: the order's one definition."""
    if r not in _RING_POS:
        _RING_POS[r] = {off: k for k, off in enumerate(_ring_offsets(r))}
    return _RING_POS[r]


class HoleIndex:
    """The hole sample bucketed in `cell` mm squares: `nearest` looks at the squares round the query point, ring by ring
    (the layout search asks for the nearest usable hole point of every power jack of every candidate)."""

    def __init__(self, sample, cell=12.0):
        self.cell, self.buckets, self.points = cell, {}, list(sample)
        for h in self.points:
            self.buckets.setdefault((int(h[0] // cell), int(h[1] // cell)), []).append(h)
        keys = list(self.buckets)
        self.span = max([abs(i) for i, _ in keys] + [abs(j) for _, j in keys] + [0]) + 1   # rings never need to go beyond

    def __len__(self):
        return len(self.points)

    def without(self, rects):
        """A new index of the points that lie in none of `rects`."""
        return HoleIndex([h for h in self.points if not covered(h, rects)], self.cell)

    def nearest(self, point, blocked=(), reach=100.0):
        """The sample point nearest to `point` outside every `blocked` rectangle, or None. The rectangles farther than `reach`
        mm from the point are left out of the first search (they cannot cover a point that close); when that finds nothing
        within `reach`, the search is repeated over the whole sample with all of them."""
        x, y = point
        near = [r for r in blocked if r[0] <= x + reach and r[2] >= x - reach and r[1] <= y + reach and r[3] >= y - reach]
        h = self._nearest(point, near, reach)
        if h is not None:
            return h
        return self._nearest(point, blocked, math.inf)

    def _nearest(self, point, blocked, reach):
        """The sample point nearest to `point`, within `reach` mm, that no rectangle of `blocked` covers (None without one). Of two
        equally near points the one met first when walking the squares ring by ring round the query point (then by position in
        the ring, then in sample order) wins. A big sample is walked that way (`_nearest_rings`); a small one is cheaper to scan
        whole, with the walk's order only deciding ties."""
        if len(self.points) > SCAN_POINTS:
            return self._nearest_rings(point, blocked, reach)
        px, py = point
        best, bd, bkey = None, math.nextafter(reach * reach, math.inf), None   # d < bd: within reach
        for h in self.points:
            d = (h[0] - px) ** 2 + (h[1] - py) ** 2
            if d > bd:
                continue
            for q in blocked:
                if q[0] <= h[0] <= q[2] and q[1] <= h[1] <= q[3]:
                    break
            else:
                if d < bd:
                    best, bd, bkey = h, d, None
                elif best is not None:   # an equal distance
                    if bkey is None:
                        bkey = self._walk_key(best, point)
                    key = self._walk_key(h, point)
                    if key < bkey:
                        best, bkey = h, key
        return best

    def _nearest_rings(self, point, blocked, reach):
        c, (ci, cj) = self.cell, (int(point[0] // self.cell), int(point[1] // self.cell))
        px, py = point
        best, bd = None, math.inf
        limit = min(self.span + max(abs(ci), abs(cj)), int(reach // c) + 1 if reach < math.inf else 10 ** 6)
        buckets_get = self.buckets.get
        for r in range(limit + 1):
            for dx, dy in _ring_offsets(r):
                pts = buckets_get((ci + dx, cj + dy))
                if pts is None:
                    continue
                for h in pts:
                    d = (h[0] - px) ** 2 + (h[1] - py) ** 2
                    if d < bd:
                        for q in blocked:
                            if q[0] <= h[0] <= q[2] and q[1] <= h[1] <= q[3]:
                                break
                        else:
                            best, bd = h, d
            if best is not None and bd <= (r * c) ** 2:   # the next ring is at least r cells away
                break
        return best if best is not None and bd <= reach * reach else None

    def _walk_key(self, h, point):
        """(ring, position in the ring) of the square of `h` in the walk round the square of `point` (`_nearest_rings` order,
        `_ring_offsets`)."""
        c = self.cell
        dx, dy = int(h[0] // c) - int(point[0] // c), int(h[1] // c) - int(point[1] // c)
        r = max(abs(dx), abs(dy))
        return (r, _ring_position(r)[(dx, dy)])


class Crossings:
    """Where a power cable may change layer, for the estimate: a `HoleIndex` of hole points (a pass costs `cfg["transit_mm"]`) and
    one of edge points (round the board edge, `cfg["edge_transit_mm"]`; None / empty: holes only). `nearest` gives the
    cheapest crossing for a query point: transit + `top_cost` x the straight distance to it on top; `transit_of` the transit
    of a point it returned. Used wherever a `HoleIndex` is (`hop_estimate`, `assign`, `Model`)."""

    def __init__(self, holes, edges, cfg):
        self.holes, self.edges, self.cfg = holes, edges or HoleIndex([]), cfg
        self.edge_set = set(self.edges.points)

    def __len__(self):
        return len(self.holes) + len(self.edges)

    def without(self, rects):
        return Crossings(self.holes.without(rects), self.edges, self.cfg)

    def nearest(self, point, blocked=(), reach=100.0):
        if not self.edge_set:   # holes only (the common case): the plain nearest hole point
            return self.holes.nearest(point, blocked, reach)
        tc, tr = self.cfg.get("top_cost", 3.0), self.cfg.get("transit_mm", 15.0)
        te = self.cfg.get("edge_transit_mm", 2 * tr)
        best = None
        for index, tt, rects in ((self.holes, tr, blocked), (self.edges, te, ())):
            h = index.nearest(point, rects, reach) if index else None
            if h is not None:
                cost = tt + tc * math.hypot(h[0] - point[0], h[1] - point[1])
                if best is None or cost < best[0]:
                    best = (cost, h)
        return best[1] if best else None

    def transit_of(self, point, default):
        return self.cfg.get("edge_transit_mm", default) if point in self.edge_set else default


def hop_estimate(src, dst, src_under, holes, cfg, near=None):
    """Cheap estimate of one routed power hop from `src` to `dst` (measure points, mm), in the router's costs (`cfg`:
    `top_cost` per mm on top, `transit_mm` per hole pass; the under part costs 1 per mm):
      source under:  Manhattan under to the usable hole point nearest the target, the pass, the straight distance on top;
      source on top: the cheaper of Manhattan on top (x top_cost) and down through the hole nearest the source, Manhattan
                     under, up through the hole nearest the target.
    `holes`: a `HoleIndex` of the usable hole points or a `Crossings` (holes + edge points with their own transit; None / empty:
    today's plain Manhattan); `near(point)` finds the
    nearest usable one (default: `holes.nearest`, a caller may memoise it). Also returns plain Manhattan when no hole is
    usable near the target."""
    if not holes:
        return manhattan(src, dst)
    near = near or holes.nearest
    tc, tr = cfg.get("top_cost", 3.0), cfg.get("transit_mm", 15.0)
    transit = getattr(holes, "transit_of", lambda p, d: d)
    ht = near(dst)
    if ht is None:
        return manhattan(src, dst)
    up = transit(ht, tr) + tc * math.hypot(ht[0] - dst[0], ht[1] - dst[1])
    if src_under:
        return manhattan(src, ht) + up
    hs = near(src)
    top = tc * manhattan(src, dst)
    if hs is None:
        return top
    return min(top, tc * math.hypot(hs[0] - src[0], hs[1] - src[1]) + transit(hs, tr) + manhattan(hs, ht) + up)


def chain_order(start, members, points, length=None, start_under=False):
    """(length mm, order) of the shortest daisy chain from `start` through every member (Manhattan between measure
    points; unknown points cost 0). Exact up to 7 members, nearest neighbour beyond. `length(a, b, a_under)`: the cost of
    one hop instead of Manhattan (`hop_estimate`); `start_under`: the first hop starts under the board (a pedal's power
    jack is on top, so later hops never do)."""
    hop = length or (lambda a, b, under: manhattan(a, b))
    if length:   # the orders share their hops: every (from, to, under) pair is estimated once
        seen, estimate = {}, length

        def hop(a, b, under):
            key = (a, b, under)
            if key not in seen:
                seen[key] = estimate(a, b, under)
            return seen[key]

    def length(order):
        total, prev, under = 0.0, start, start_under
        for pid in order:
            here = points.get(pid)
            if prev is not None and here is not None:
                total += hop(prev, here, under)
            if here is not None:
                prev, under = here, False
        return total
    if len(members) <= 7:
        best = min(itertools.permutations(sorted(members)), key=lambda o: (length(o), o))
        return length(best), list(best)
    left, order, prev, under = sorted(members), [], start, start_under
    while left:
        nxt = min(left, key=lambda p: (hop(prev, points[p], under) if prev is not None and points.get(p) is not None else 0, p))
        order.append(nxt)
        left.remove(nxt)
        if points.get(nxt) is not None:
            prev, under = points[nxt], False
    return length(order), order


def fork_length(start, members, points, length=None, start_under=False, rank=None):
    """(length mm, order) of a FORKED output: one cable per member, each from `start` (the supply port) to the member's
    point, so the length is the sum of those hops (Manhattan between measure points, or `length(a, b, a_under)`; unknown
    points cost 0) and there is no order to optimise: `order` is the members sorted by `rank` ({id: position}, e.g. the
    signal chain; default the id) for a stable listing."""
    hop = length or (lambda a, b, under: manhattan(a, b))
    rank = rank or {}
    order = sorted(members, key=lambda p: (rank.get(p, len(rank)), p))
    total = sum(hop(start, points[p], start_under) for p in order if start is not None and points.get(p) is not None)
    return total, order


def default_voltage(pc):
    """Operating voltage for a pedal without a given one: 9 V if it accepts it, else its minimum."""
    lo, hi = pc.get("min_voltage_v"), pc.get("max_voltage_v")
    if lo is None or hi is None or lo <= 9 <= hi:
        return 9
    return lo


def assign(chain, pedals, insts, project, points, port_points, run_v=None, start=None, holes=None, cfg=None):
    """Power wiring for one layout: every chain pedal on one supply output, daisy chains ordered for the shortest
    DC cable, under the project's power policy.

    insts: [{"id", "label"?, "supply": catalog id, "sup": catalog supply}] (the project's supply instances).
    points: {pedal id: measure point (mm) of its power plug}; port_points: {(instance id, port): point}.
    run_v: {pedal id: operating voltage} to keep (the owner's choice); others get `default_voltage`.
    start: a project-style wiring ({inst id: [{"port", "voltage_v", "pedals"}]}) to improve from (else greedy).
    holes: a `HoleIndex` (or `Crossings`) of the usable crossing points (`hole_sample` minus the pedals, see `usable_holes`) and cfg {"top_cost", "transit_mm"}: the daisy chains are then
    measured with `hop_estimate` (power cables run under the board and come up through the hole nearest each pedal; an
    instance with `"under": False` starts its chain on top); without holes: Manhattan between the measure points.
    Returns {"supplies": [project.json power.supplies entries], "length_mm", "warnings": [build warnings of the
    wiring], "errors": []} or raises ValueError if no wiring satisfies the policy."""
    sensitive, strength, group_18v = policy_settings(project)
    chain = [p for p in chain if p in pedals]
    run_v = dict(run_v or {})
    volts = {p: run_v.get(p) or default_voltage(pedals[p]["power_consumption"]) for p in chain}
    under_of = {inst["id"]: inst.get("under", True) for inst in insts}
    hop_cache = {}
    cfg = cfg or {}
    rank = {p: i for i, p in enumerate(chain)}
    # style per output slot: the owner's (`start`) own `style`, else the project's `power_routing.daisy_style`
    given_style = {(iid, o["port"]): o.get("style") for iid, outs in (start or {}).items() for o in outs}
    style_of = {key: routing.daisy_style(project, {"style": st}) for key, st in given_style.items()}

    def near(p):
        if p not in hop_cache:
            hop_cache[p] = holes.nearest(p)
        return hop_cache[p]
    hop = (lambda a, b, under: hop_estimate(a, b, under, holes, cfg, near)) if holes else None
    slots = []   # (inst id, port, {voltage: max_ma}, polarity, isolated)
    for inst in insts:
        sup = inst["sup"]
        for o in sup.get("outputs") or []:
            opts = {op["voltage_v"]: op.get("max_ma") for op in o.get("options", [])}
            slots.append((inst["id"], o["port"], opts, o.get("polarity") or sup.get("polarity"), o.get("isolated")))
    slot_ix = {(s[0], s[1]): n for n, s in enumerate(slots)}
    cache = {}

    def slot_check(n, members):
        """(feasible, warning messages, chain length, order) of slot n with these members."""
        key = (n, tuple(sorted(members)))
        if key not in cache:
            inst, port, opts, pol, isolated = slots[n]
            if not members:
                cache[key] = (True, [], 0.0, [])
            else:
                vs = {volts[p] for p in members}
                v = next(iter(vs))
                if len(vs) > 1 or opts.get(v) is None:   # as the build: an option without max_ma is not available
                    cache[key] = (False, [], 0.0, [])
                else:
                    errs, warns, _ = output_findings(f"{inst}_{port}", sorted(members), v, opts[v], pol, pedals, sensitive,
                                                     strength, isolated)
                    if style_of.get((inst, port), routing.daisy_style(project)) == routing.FORKED:
                        length, order = fork_length(port_points.get((inst, port)), members, points, hop, under_of.get(inst, True), rank)
                    else:
                        length, order = chain_order(port_points.get((inst, port)), members, points, hop, under_of.get(inst, True))
                    cache[key] = (not errs, warns, length, order)
        return cache[key]

    def total(state):
        length, warns = 0.0, []
        for n, members in enumerate(state):
            ok, w, ln, _ = slot_check(n, members)
            if not ok:
                return None
            length += ln
            warns += w
        if group_18v:
            warns += merge_18v_findings(rows_of(state), pedals)
        return length + WARNING_COST_MM * len(warns), length, warns

    def rows_of(state):
        out = []
        for n, members in enumerate(state):
            if members:
                v = volts[members[0]]
                out.append({"id": f"{slots[n][0]}_{slots[n][1]}", "voltage_v": v, "pedals": list(members), "limit": slots[n][2].get(v)})
        return out

    def from_wiring(wiring):
        state = [[] for _ in slots]
        seen = set()
        for inst_id, outs in wiring.items():
            for o in outs:
                n = slot_ix.get((inst_id, o["port"]))
                if n is None:
                    return None
                for p in o.get("pedals", []):
                    if p in volts and p not in seen:
                        if volts[p] != o["voltage_v"]:
                            return None
                        state[n].append(p)
                        seen.add(p)
        return state if seen == set(volts) else None

    def greedy():
        """Cheapest feasible slot per pedal (most constrained pedals first), backtracking on a dead end."""
        alone = lambda p: pedals[p].get("digital") is not False or pedals[p]["power_consumption"].get("needs_isolated_output")
        order = sorted(chain, key=lambda p: (not alone(p), -(pedals[p]["power_consumption"].get("current_ma") or 0), p))
        state, budget = [[] for _ in slots], [20000]

        def place(k):
            if k == len(order):
                return True
            p, options = order[k], []
            for n in range(len(slots)):
                state[n].append(p)
                t = total(state)
                state[n].pop()
                if t is not None:
                    options.append((t[0], n))
            for _, n in sorted(options):
                budget[0] -= 1
                if budget[0] < 0:
                    return False
                state[n].append(p)
                if place(k + 1):
                    return True
                state[n].pop()
            return False
        return state if place(0) else None

    candidates = [s for s in (from_wiring(start) if start else None, greedy()) if s is not None and total(s) is not None]
    if not candidates:
        raise ValueError("no power wiring satisfies the power policy with these supplies")
    results = [improve(s, total) for s in candidates]
    state = min(results, key=lambda s: (total(s)[0], repr(s)))
    _, length, warns = total(state)
    by_inst = {inst["id"]: [] for inst in insts}
    for n, members in enumerate(state):
        if members:
            _, _, _, order = slot_check(n, members)
            by_inst[slots[n][0]].append({"port": slots[n][1], "voltage_v": volts[members[0]], "pedals": order,
                                         **({"style": given_style[slots[n][:2]]} if given_style.get(slots[n][:2]) else {})})
    supplies = []
    for inst in insts:
        entry = {"id": inst["id"], "supply": inst["supply"]}
        if inst.get("label"):
            entry["label"] = inst["label"]
        entry["outputs"] = by_inst[inst["id"]]
        supplies.append(entry)
    return {"supplies": supplies, "length_mm": length, "warnings": warns, "errors": []}


def improve(state, total):
    """First-improvement local search over moves of one pedal, swaps of two pedals and swaps of two outputs'
    contents (deterministic order) until nothing lowers `total`."""
    state = [list(m) for m in state]
    best = total(state)[0]
    improved = True
    while improved:
        improved = False
        n = len(state)
        for a in range(n):
            for i in range(len(state[a])):
                if i >= len(state[a]):
                    break
                p = state[a][i]
                for b in range(n):
                    if b == a:
                        continue
                    trial = [list(m) for m in state]
                    trial[a].remove(p)
                    trial[b].append(p)
                    t = total(trial)
                    if t is not None and t[0] < best - 1e-9:
                        state, best, improved = trial, t[0], True
                        break
                    for q in list(state[b]):
                        trial = [list(m) for m in state]
                        trial[a][trial[a].index(p)] = q
                        trial[b][trial[b].index(q)] = p
                        t = total(trial)
                        if t is not None and t[0] < best - 1e-9:
                            state, best, improved = trial, t[0], True
                            break
                    if improved:
                        break
                if improved:
                    break
            if improved:
                break
            for b in range(a + 1, n):
                trial = [list(m) for m in state]
                trial[a], trial[b] = trial[b], trial[a]
                t = total(trial)
                if t is not None and t[0] < best - 1e-9:
                    state, best, improved = trial, t[0], True
                    break
            if improved:
                break
    return state


def measure_points(placed, inst_item, insts, jacks_data, depth_mm):
    """({pedal id: point}, {(instance id, port): point}): where DC cable lengths are measured (mm), half the plug
    depth in front of each power jack, as jacks.check does. placed: {pedal id: layout item}; inst_item: {supply
    instance id: layout item}; insts: [{"id", "supply"}]."""
    from jacks import default_jack   # late: jacks imports routing lazily
    pts, ports = {}, {}
    for cid, it in placed.items():
        jk = default_jack(jacks_data.get(cid) or [], "power")
        if jk:
            pt = design.jack_point(it, jk["x"], jk["y"])
            pts[cid] = design.stub(pt, design.jack_facing(it, jk["facing"]), depth_mm / 2)
    for inst in insts:
        it = inst_item.get(inst["id"])
        for jk in jacks_data.get(inst["supply"]) or []:
            if it and jk["function"] == "power_out":
                pt = design.jack_point(it, jk["x"], jk["y"])
                ports[(inst["id"], jk["id"])] = design.stub(pt, design.jack_facing(it, jk["facing"]), depth_mm / 2)
    return pts, ports
