"""Power policy and power assignment (all mm). Pure: no network, no GUI.

- `output_findings` / `merge_18v_findings`: the checks of the power wiring, shared by `build.validate` (the owner's
  wiring in project.json) and `assign` (a wiring computed for a layout), so both apply exactly the same policy:
  operating voltage within the pedal's range, polarity, isolated outputs, digital pedals alone, clocked
  (BBD/digital) pedals never with gain/compressor pedals, mA limits, 18 V pedals sharing 18 V outputs.
- `assign`: puts the chain pedals on the project's supply outputs (ports, voltages, daisy-chain order) for one
  layout, minimising the DC cable length: Manhattan distance between the half-depth measure points of the plugs
  (as `jacks.check`), from the supply port through the daisy chain. Used for layout proposals; the build keeps
  using the owner's hand wiring in project.json.
"""
import itertools

from routing import POLARITIES
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


def output_findings(oid, row_pedals, voltage, limit, out_polarity, pedals, sensitive, pol_strength):
    """(errors, warnings, load mA) of one supply output feeding `row_pedals` at `voltage` (limit in mA, None if the
    port has no such voltage: only the per-pedal checks run). `pedals`: chain pedals by id (others are ignored)."""
    errors, warnings, load = [], [], 0
    for pid in row_pedals:
        if pid not in pedals:
            continue
        pc = pedals[pid]["power_consumption"]
        lo, hi = pc.get("min_voltage_v"), pc.get("max_voltage_v")
        if lo is not None and hi is not None and not lo <= voltage <= hi:
            errors.append(f"{oid}: {pid} would run at {voltage}V but only accepts {volt_range(pc)}")
        pol = pc.get("polarity")
        if pol is not None and pol not in POLARITIES:
            errors.append(f"{pid}: unknown polarity '{pol}' ({', '.join(POLARITIES)})")
        elif pol and out_polarity and pol != out_polarity:
            warnings.append(f"{oid}: {pid} is {pol.replace('_', '-')} but the output is {out_polarity.replace('_', '-')}: "
                            f"use a polarity-reversing cable")
        if pc.get("needs_isolated_output") and len(row_pedals) > 1:
            errors.append(f"{oid}: {pid} needs an isolated output but shares it")
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


# --- assignment --------------------------------------------------------------------------------
def manhattan(a, b):
    return abs(a[0] - b[0]) + abs(a[1] - b[1])


def chain_order(start, members, points):
    """(length mm, order) of the shortest daisy chain from `start` through every member (Manhattan between measure
    points; unknown points cost 0). Exact up to 7 members, nearest neighbour beyond."""
    def length(order):
        total, prev = 0.0, start
        for pid in order:
            here = points.get(pid)
            if prev is not None and here is not None:
                total += manhattan(prev, here)
            prev = here if here is not None else prev
        return total
    if len(members) <= 7:
        best = min(itertools.permutations(sorted(members)), key=lambda o: (length(o), o))
        return length(best), list(best)
    left, order, prev = sorted(members), [], start
    while left:
        nxt = min(left, key=lambda p: (manhattan(prev, points[p]) if prev is not None and points.get(p) is not None else 0, p))
        order.append(nxt)
        left.remove(nxt)
        prev = points.get(nxt) if points.get(nxt) is not None else prev
    return length(order), order


def default_voltage(pc):
    """Operating voltage for a pedal without a given one: 9 V if it accepts it, else its minimum."""
    lo, hi = pc.get("min_voltage_v"), pc.get("max_voltage_v")
    if lo is None or hi is None or lo <= 9 <= hi:
        return 9
    return lo


def assign(chain, pedals, insts, project, points, port_points, run_v=None, start=None):
    """Power wiring for one layout: every chain pedal on one supply output, daisy chains ordered for the shortest
    DC cable, under the project's power policy.

    insts: [{"id", "label"?, "supply": catalog id, "sup": catalog supply}] (the project's supply instances).
    points: {pedal id: measure point (mm) of its power plug}; port_points: {(instance id, port): point}.
    run_v: {pedal id: operating voltage} to keep (the owner's choice); others get `default_voltage`.
    start: a project-style wiring ({inst id: [{"port", "voltage_v", "pedals"}]}) to improve from (else greedy).
    Returns {"supplies": [project.json power.supplies entries], "length_mm", "warnings": [build warnings of the
    wiring], "errors": []} or raises ValueError if no wiring satisfies the policy."""
    sensitive, strength, group_18v = policy_settings(project)
    chain = [p for p in chain if p in pedals]
    run_v = dict(run_v or {})
    volts = {p: run_v.get(p) or default_voltage(pedals[p]["power_consumption"]) for p in chain}
    slots = []   # (inst id, port, {voltage: (limit, polarity)}, isolated)
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
                if len(vs) > 1 or v not in opts:
                    cache[key] = (False, [], 0.0, [])
                else:
                    errs, warns, _ = output_findings(f"{inst}_{port}", sorted(members), v, opts[v], pol, pedals, sensitive, strength)
                    iso_bad = isolated is False and any(pedals[p]["power_consumption"].get("needs_isolated_output") for p in members)
                    length, order = chain_order(port_points.get((inst, port)), members, points)
                    cache[key] = (not errs and not iso_bad, warns, length, order)
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
            by_inst[slots[n][0]].append({"port": slots[n][1], "voltage_v": volts[members[0]], "pedals": order})
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
    import design
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
