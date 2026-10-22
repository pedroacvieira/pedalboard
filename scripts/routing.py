"""Cable model and on-board cable routing (all mm). Pure: no network, no GUI.

Signal cables (each pedal's output -> the next pedal's input) are routed on the board surface:
  - the routing area is the pedalboard plus `edge_margin_mm` (default: one cable diameter) beyond its
    back and sides; nothing may run in front of (below) the lowest row of pedals;
  - pedal bodies are obstacles (supplies under the board are not);
  - the area is a grid of `grid_mm` cells (default 2 mm); pedals are grown by the cable radius minus half a
    cell, so any gap at least one cable diameter wide is a corridor; at most `max_stack` cables (default 2,
    stacked on top of each other) may share a cell;
  - plugs are modelled (catalog/cables.json, `cables.type` + per-cable `overrides.<id>.type`): a right-angle
    plug's cable leaves the head to the left or right of the jack's facing (the router tries both sides per
    end and keeps the feasible combination with the fewest blocked plugs, then the shortest route; a project
    can fix `exit_a` / `exit_b`), a straight plug's along the facing; the cable then runs `exit_run_mm`
    straight (default one diameter) before the router takes over. Without a cable type the cable leaves
    the jack straight out by the fixed clearance depth (`jacks.clearance.outward_mm`);
  - the grid path is the shortest 8-connected one; crowded cells are resolved by rip-up-and-reroute with
    rising congestion costs (negotiated congestion, as in FPGA routers);
  - the clearance of every signal jack with a modelled plug is checked here (head footprint + barrel +
    straight cable run on the chosen side against the other pedals); other jacks keep the fixed box (jacks.py).
Power cables get the same cable model (tips, centre polarity, under_board) and a length estimate, but are
not routed yet: the supplies sit under the board and under-board routing does not exist yet. Their plugs are
modelled for clearance: with `cables.power_type` (a DC plug type, role power) every power jack is checked with
that plug's head on the less blocked exit side; without it jacks.py uses the smaller `jacks.power_clearance` box.
"""
import heapq
import itertools
import math

import design

DEFAULTS = {
    "type": None,                # default patch cable type (catalog/cables.json, role patch); None: no plug model
    "power_type": None,          # DC plug type for power-jack clearance (role power); None: the jacks.power_clearance box
    "diameter_mm": 6.0,          # routing width of a signal cable; the type's diameter_mm (on-board width) when a type is set
    "max_stack": 2,              # cables allowed on top of each other in one cell
    "default_tip": "TS",         # signal plugs unless a jack or an override says TRS / XLR
    "power_tip": "DC 2.1 mm",
    "iterations": 40,
}
TIPS = ("TS", "TRS", "XLR", "DC 2.1 mm", "DC 2.5 mm")
POLARITIES = ("center_negative", "center_positive")
NEIGHBOURS = [(1, 0), (-1, 0), (0, 1), (0, -1), (1, 1), (1, -1), (-1, 1), (-1, -1)]


STYLES = ("right_angle", "straight")
ROLES = ("patch", "instrument", "power", "reference")   # what a catalog/cables.json type is for


def settings(project, types=None):
    """Routing settings: DEFAULTS + project `cables`. The routing width (`diameter_mm`) is the widest signal cable
    type in use (the default type and every override), so the grid corridors fit every cable."""
    given = project.get("cables") or {}
    s = {**DEFAULTS, **given}
    used = [s["type"]] + [(o or {}).get("type") for o in (given.get("overrides") or {}).values()]
    widths = [float(types[t]["diameter_mm"]) for t in used if t in (types or {}) and types[t].get("diameter_mm")
              and types[t].get("role") != "power"]
    if widths and "diameter_mm" not in given:
        s["diameter_mm"] = max(widths)
    s.setdefault("grid_mm", 2.0)
    s.setdefault("exit_run_mm", s["diameter_mm"])
    s.setdefault("edge_margin_mm", s["diameter_mm"])
    s.setdefault("overrides", {})
    return s


# --- grid ---------------------------------------------------------------------------------------
class Grid:
    """Square cells over the routing area; `free(c)` tells whether a cable may pass through a cell."""

    def __init__(self, x0, y0, x1, y1, cell):
        self.x0, self.y0, self.cell = x0, y0, cell
        self.nx, self.ny = max(1, math.ceil((x1 - x0) / cell)), max(1, math.ceil((y1 - y0) / cell))
        self.blocked = set()   # no cable centre here (pedal grown by the cable radius minus half a cell)
        self.body = set()      # cell centre inside a pedal body: never passable, even when squeezing
        self._comps = {}

    def inside(self, c):
        return 0 <= c[0] < self.nx and 0 <= c[1] < self.ny

    def free(self, c):
        return self.inside(c) and c not in self.blocked

    def cell_of(self, x, y):
        return (int(math.floor((x - self.x0) / self.cell)), int(math.floor((y - self.y0) / self.cell)))

    def centre(self, c):
        return (self.x0 + (c[0] + 0.5) * self.cell, self.y0 + (c[1] + 0.5) * self.cell)

    def rect(self, c):
        x, y = self.x0 + c[0] * self.cell, self.y0 + c[1] * self.cell
        return (x, y, x + self.cell, y + self.cell)

    def block_rect(self, r, grow=0.0):
        """Block every cell whose centre lies inside rectangle r grown by `grow` (use the cable radius: a cable
        centred there would overlap the obstacle). Gaps at least one cable diameter wide stay open."""
        x0, y0, x1, y1 = r[0] - grow, r[1] - grow, r[2] + grow, r[3] + grow
        for i in range(max(0, int((x0 - self.x0) / self.cell) - 1), min(self.nx, int((x1 - self.x0) / self.cell) + 2)):
            for j in range(max(0, int((y0 - self.y0) / self.cell) - 1), min(self.ny, int((y1 - self.y0) / self.cell) + 2)):
                cx, cy = self.centre((i, j))
                if x0 <= cx <= x1 and y0 <= cy <= y1:
                    self.blocked.add((i, j))
                    if r[0] <= cx <= r[2] and r[1] <= cy <= r[3]:
                        self.body.add((i, j))
        self._comps = {}

    def walls(self, squeeze=False):
        return self.body if squeeze else self.blocked

    def components(self, squeeze=False):
        """{cell: component id} over passable cells (4-connected: a legal diagonal move implies a 4-connected
        detour, so reachability is the same), computed once per mode."""
        if squeeze not in self._comps:
            walls, comp, n = self.walls(squeeze), {}, 0
            for i in range(self.nx):
                for j in range(self.ny):
                    if (i, j) in walls or (i, j) in comp:
                        continue
                    comp[(i, j)], todo = n, [(i, j)]
                    while todo:
                        x, y = todo.pop()
                        for c in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
                            if self.inside(c) and c not in walls and c not in comp:
                                comp[c] = n
                                todo.append(c)
                    n += 1
            self._comps[squeeze] = comp
        return self._comps[squeeze]

    def connected(self, a, b, squeeze=False):
        """Whether a path can exist from cell a to cell b (both always enterable, like plug ends)."""
        if a == b:
            return True
        comp, walls = self.components(squeeze), self.walls(squeeze)

        def reach(c):
            near = [c] + [(c[0] + dx, c[1] + dy) for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1))]
            return {comp[x] for x in near if x in comp}
        if abs(a[0] - b[0]) + abs(a[1] - b[1]) == 1:
            return True
        return bool(reach(a) & reach(b))


def build_grid(board_rect, obstacle_rects, front_y, cfg):
    """Routing area = board + margin at the back and sides, cut off at `front_y` (no cables in front)."""
    m = cfg["edge_margin_mm"]
    x0, y0, x1 = board_rect[0] - m, board_rect[1] - m, board_rect[2] + m
    g = Grid(x0, y0, x1, front_y, cfg["grid_mm"])
    # grow by the cable radius minus half a cell: every gap at least one cable diameter wide keeps a row of free
    # cell centres whatever the grid alignment (a narrower gap may still pass by up to half a cell: grid accuracy)
    grow = max(0.0, cfg["diameter_mm"] / 2 - cfg["grid_mm"] / 2 - 0.01)
    for r in obstacle_rects:
        g.block_rect(r, grow=grow)
    return g


# --- search -------------------------------------------------------------------------------------
SQUEEZE_COST = 25.0   # cost factor of a cell narrower than the cable when squeezing (see route_project)


def astar(grid, start, goal, cell_cost, squeeze=False):
    """Cheapest 8-connected path from start to goal; diagonals may not cut obstacle corners.
    start/goal are always enterable (they are the plug ends, possibly squeezed against a pedal).
    squeeze=True: cells narrower than the cable (grown margin, not the pedal body) are passable at SQUEEZE_COST."""
    walls, nx, ny = grid.walls(squeeze), grid.nx, grid.ny

    def passable(c):
        return 0 <= c[0] < nx and 0 <= c[1] < ny and (c not in walls or c == start or c == goal)

    if squeeze:
        base = cell_cost
        cell_cost = lambda c: base(c) * (SQUEEZE_COST if c in grid.blocked else 1.0)

    h = lambda c: math.hypot(c[0] - goal[0], c[1] - goal[1]) * grid.cell
    openq, best, came = [(h(start), 0.0, start)], {start: 0.0}, {}
    while openq:
        _, g, c = heapq.heappop(openq)
        if c == goal:
            path = [c]
            while c in came:
                c = came[c]
                path.append(c)
            return path[::-1]
        if g > best.get(c, math.inf):
            continue
        for dx, dy in NEIGHBOURS:
            n = (c[0] + dx, c[1] + dy)
            if not passable(n):
                continue
            if dx and dy and not (passable((c[0] + dx, c[1])) and passable((c[0], c[1] + dy))):
                continue
            step = grid.cell * (math.sqrt(2) if dx and dy else 1.0)
            ng = g + step * cell_cost(n)
            if ng < best.get(n, math.inf):
                best[n], came[n] = ng, c
                heapq.heappush(openq, (ng + h(n), ng, n))
    return None


def route_all(grid, nets, max_stack, iterations=40):
    """nets: [(name, start_cell, goal_cell[, squeeze])]. Returns ({name: path or None}, {cell: [names]}, overflow cells).

    Every round, each net is ripped up and re-routed against the others' current paths; a cell already holding
    `max_stack` cables costs more (present factor, growing each round), and cells that stayed over the limit
    get a permanent history cost, so cables spread out until the limit holds (or the rounds run out).
    """
    history, paths, present = {}, {}, 0.5
    for _ in range(iterations):
        usage = {}
        for path in paths.values():
            for c in path or []:
                usage[c] = usage.get(c, 0) + 1
        for name, s, t, *sq in nets:
            for c in paths.get(name) or []:
                usage[c] -= 1

            def cost(c):
                over = max(0, usage.get(c, 0) + 1 - max_stack)
                return (1.0 + history.get(c, 0.0)) * (1.0 + present * over * 10)

            paths[name] = astar(grid, s, t, cost, squeeze=bool(sq and sq[0]))
            for c in paths[name] or []:
                usage[c] = usage.get(c, 0) + 1
        overflow = {c for c, n in usage.items() if n > max_stack}
        if not overflow:
            break
        for c in overflow:
            history[c] = history.get(c, 0.0) + 0.5
        present *= 1.6
    users = {}
    for name, path in paths.items():
        for c in path or []:
            users.setdefault(c, []).append(name)
    return paths, users, {c for c, u in users.items() if len(u) > max_stack}


def path_length(grid, path):
    return sum(grid.cell * (math.sqrt(2) if a[0] != b[0] and a[1] != b[1] else 1.0) for a, b in zip(path, path[1:]))


# --- the project step ---------------------------------------------------------------------------
def validate_types(types):
    """Problems in catalog/cables.json, as strings."""
    errs = []
    for tid, t in types.items():
        plug = t.get("plug") or {}
        if plug.get("style") not in STYLES:
            errs.append(f"cables.json: {tid} plug.style must be one of {', '.join(STYLES)}")
        for k in ("head_depth_mm", "head_width_mm"):
            if not isinstance(plug.get(k), (int, float)) or plug[k] <= 0:
                errs.append(f"cables.json: {tid} plug.{k} must be a positive number")
        if not isinstance(t.get("diameter_mm"), (int, float)) or t["diameter_mm"] <= 0:
            errs.append(f"cables.json: {tid} diameter_mm must be a positive number")
        if t.get("role") not in ROLES:
            errs.append(f"cables.json: {tid} role must be one of {', '.join(ROLES)}")
    return errs


def validate_project_types(project, types):
    """Problems with the cable types a project picks, as strings: the default patch type must be a patch cable
    (instrument and reference types only by explicit per-cable override), the power type a DC plug."""
    cfg = project.get("cables") or {}
    errs = []

    def role(tid):
        return (types.get(tid) or {}).get("role")
    if cfg.get("type") and cfg["type"] in types and role(cfg["type"]) != "patch":
        errs.append(f"cables.type: {cfg['type']} is a {role(cfg['type'])} cable, not a patch cable (role in catalog/cables.json)")
    pt = cfg.get("power_type")
    if pt and pt not in types:
        errs.append(f"cables.power_type: {pt} is not in catalog/cables.json")
    elif pt and role(pt) != "power":
        errs.append(f"cables.power_type: {pt} is a {role(pt)} cable, not a DC power cable (role power)")
    for cid, o in (cfg.get("overrides") or {}).items():
        if (o or {}).get("type") in types and role(o["type"]) == "power" and not cid.startswith("P"):
            errs.append(f"cables.overrides.{cid}.type: {o['type']} is a DC power cable")
    return errs


def cable_type_id(project, cable_id):
    """The cable type a signal cable uses (override, else the project default), or None."""
    cfg = project.get("cables") or {}
    return ((cfg.get("overrides") or {}).get(cable_id) or {}).get("type") or cfg.get("type")


def end_options(item, jack, ctype, exit_fixed, cfg, outward):
    """Every way a plug can sit in one jack: [{side, rects, lead, exit, lead_mm}] (one per exit side for a
    right-angle plug, unless the project fixes it; one for a straight plug or with no cable type)."""
    pt = design.jack_point(item, jack["x"], jack["y"])
    facing = design.jack_facing(item, jack["facing"])
    if ctype is None:
        st = design.stub(pt, facing, outward)
        return facing, [{"side": None, "rects": [], "lead": [pt, st], "exit": st, "lead_mm": outward,
                         "measure": design.stub(pt, facing, outward / 2), "measure_mm": outward / 2}]
    plug = ctype["plug"]
    sides = [None] if plug["style"] == "straight" else ([exit_fixed] if exit_fixed in design.SIDES else list(design.SIDES))
    opts = []
    for side in sides:
        g = design.plug_geometry(pt, facing, plug, ctype["diameter_mm"], cfg["exit_run_mm"], side)
        opts.append({"side": side, **g})
    return facing, opts


def blocked_parts(opt, own_id, obstacles):
    """[(part, obstacle item, overlap)] for one plug option against every other pedal footprint."""
    hits = []
    for part, r in opt["rects"]:
        for ob in obstacles:
            if ob["id"] == own_id:
                continue
            ov = design.overlap(r, design.footprint(ob))
            if ov:
                hits.append((part, ob, ov))
    return hits


def route_project(ctx, cat_pedals, cable_types=None):
    """Build ctx['cable_list'] (signal + power cables with attributes), route the signal cables and check the
    clearance of their plugs (appended to ctx['violations']).

    `min_mm` is the minimum cable length to buy: measured from a point on each jack's axis half the clearance
    depth in front of the jack (half the plug head depth, or half the fixed box), along the plug's cable exit
    and the routed path. No slack and no rounding: the owner picks the cable."""
    project, warnings, errors = ctx["project"], ctx["warnings"], ctx["errors"]
    if cable_types is None:
        from common import load_cable_types
        cable_types = load_cable_types()
    errors.extend(e for e in validate_types(cable_types) + validate_project_types(project, cable_types) if e not in errors)
    cfg = settings(project, cable_types)
    sink = errors if project.get("validation", {}).get("strict_routing") else warnings
    clear_sink = errors if project.get("validation", {}).get("strict_clearance") else warnings
    ctx["routing"] = {"settings": cfg, "grid": None, "overflow": set(), "front_y": None, "heads": []}
    ctx.setdefault("violations", [])
    layout = ctx.get("layout")
    cables = []
    over = cfg["overrides"]

    def pedal_polarity(jack_name):
        pc = (cat_pedals.get(jack_name.split(".")[0]) or {}).get("power_consumption") or {}
        return pc.get("polarity")   # None = unknown (never guessed)

    def tip_of(jack, default):
        return (jack or {}).get("connector") or default

    # signal cables, one per hop of the chain
    chain = ctx["chain"]
    jd = (layout or {}).get("jacks") or {}
    from jacks import default_jack  # late import: jacks imports design only
    for n, (a, b) in enumerate(zip(chain, chain[1:]), 1):
        ja, jb = default_jack(jd.get(a) or [], "output"), default_jack(jd.get(b) or [], "input")
        tid = cable_type_id(project, f"S{n}")
        c = {"id": f"S{n}", "kind": "signal", "from": f"{a}.{ja['id'] if ja else 'out'}", "to": f"{b}.{jb['id'] if jb else 'in'}",
             "type": tid, "exit_a": None, "exit_b": None,
             "tip_a": tip_of(ja, cfg["default_tip"]), "tip_b": tip_of(jb, cfg["default_tip"]), "under_board": False,
             "min_mm": None, "path": None, "status": "not routed", "_ends": (a, ja, b, jb)}
        cables.append(c)
    # power cables: model and estimate only (they run under the board)
    under = (project.get("jacks", {}).get("supplies_layer", "under") == "under")
    for n, hop in enumerate((ctx.get("cables") or {}).get("power", []), 1):
        cables.append({"id": f"P{n}", "kind": "power", "from": hop["from"], "to": hop["to"], "type": cfg["power_type"], "exit_b": None,
                       "tip_a": cfg["power_tip"], "tip_b": cfg["power_tip"],
                       "polarity": pedal_polarity(hop["to"]), "under_board": under, "min_mm": None,
                       "estimate_mm": hop.get("min_mm"), "path": None,
                       "status": "not routed (under the board)" if under else "not routed (power routing not implemented)"})
    for c in cables:
        for k, v in (over.get(c["id"]) or {}).items():
            if v is not None:              # null = keep the default (as cable_type_id does)
                c[k] = v
        bad = [f"{k}={c[k]}" for k in ("tip_a", "tip_b") if c[k] not in TIPS] + \
              ([f"polarity={c['polarity']}"] if c["kind"] == "power" and c["polarity"] not in (None, *POLARITIES) else [])
        if c["type"] is not None and c["type"] not in cable_types and not (c["kind"] == "power" and c["type"] == cfg["power_type"]):
            bad.append(f"type={c['type']} (not in catalog/cables.json)")
        bad += [f"{k}={c[k]}" for k in ("exit_a", "exit_b") if k in c and c[k] not in (None, "auto", *design.SIDES)]
        if bad:
            errors.append(f"cables: {c['id']} has unknown {', '.join(bad)} (tips: {', '.join(TIPS)}; polarity: {', '.join(POLARITIES)}; "
                          f"exits: left/right/auto)")
    ctx["cable_list"] = cables
    from jacks import report_fixed_box
    if not layout:
        report_fixed_box(ctx)
        return

    placed, outward, obstacles = layout["placed"], layout["outward_mm"], layout["obstacles"]
    grid = None   # without a pedalboard item nothing is routed, but every plug is still checked
    if layout.get("board"):
        board = design.footprint(layout["board"])
        feet = {cid: design.footprint(it) for cid, it in placed.items()}
        front_y = min(board[3], max((f[3] for f in feet.values()), default=board[3]))   # nothing in front of the lowest pedals
        grid = build_grid(board, [design.footprint(o) for o in obstacles], front_y, cfg)
        ctx["routing"].update(grid=grid, front_y=front_y)
    run_given = "exit_run_mm" in (project.get("cables") or {})

    nets, chosen = [], {}   # chosen: cable id -> (end a option or None, end b option or None)
    for c in (x for x in cables if x["kind"] == "signal"):
        a, ja, b, jb = c["_ends"]
        ctype = cable_types.get(c["type"]) if c["type"] else None
        ends = []
        for end, cid, jk in (("a", a, ja), ("b", b, jb)):
            if not (jk and cid in placed):
                ends.append(None)
                continue
            run = cfg if run_given or not ctype else {**cfg, "exit_run_mm": float(ctype["diameter_mm"])}   # one own diameter
            facing, opts = end_options(placed[cid], jk, ctype, c.get(f"exit_{end}"), run, outward)
            for o in opts:
                o["hits"] = blocked_parts(o, placed[cid]["id"], obstacles)
                o["cell"] = grid.cell_of(*o["exit"]) if grid else None
            ends.append({"cid": cid, "jack": jk, "facing": facing, "opts": opts})
        c["_sides"] = ends
        if grid is None or not all(ends):
            c["status"] = "not routed (no pedalboard in the layout)" if grid is None else "not routed (jack or placement missing)"
            # still choose a side per known end (fewest blocked parts) for the clearance check
            chosen[c["id"]] = tuple(min(e["opts"], key=lambda o: len(o["hits"])) if e else None for e in ends)
            c["exit_a"], c["exit_b"] = ((o or {}).get("side") for o in chosen[c["id"]])
            continue
        combos = []
        for oa, ob in itertools.product(ends[0]["opts"], ends[1]["opts"]):
            inside = grid.inside(oa["cell"]) and grid.inside(ob["cell"])
            mode = 2   # 0: free path, 1: only by squeezing through gaps narrower than the cable, 2: no path
            if inside:
                mode = 0 if grid.connected(oa["cell"], ob["cell"]) else (1 if grid.connected(oa["cell"], ob["cell"], True) else 2)
            combos.append(((not inside, mode, len(oa["hits"]) + len(ob["hits"])), oa, ob))
        top = min(k for k, _, _ in combos)
        best = None
        for key, oa, ob in (x for x in combos if x[0] == top):   # A* only for the best-ranked combinations
            path = astar(grid, oa["cell"], ob["cell"], lambda _: 1.0, squeeze=key[1] == 1) if key[1] < 2 else None
            length = (oa["measure_mm"] + ob["measure_mm"] + path_length(grid, path)) if path else \
                math.hypot(oa["exit"][0] - ob["exit"][0], oa["exit"][1] - ob["exit"][1])
            if best is None or length < best[0][3]:
                best = ((*key, length), oa, ob)
        (outside, mode, _, _), oa, ob = best
        chosen[c["id"]] = (oa, ob)
        c["exit_a"], c["exit_b"] = oa["side"], ob["side"]
        if outside:
            c["status"] = "unroutable: a plug end is outside the routing area (in front of the lowest pedals or beyond the margin)"
            sink.append(f"routing: {c['id']} ({c['from']} -> {c['to']}) {c['status'][len('unroutable: '):]}")
            continue
        if mode == 2:
            inner = [e["cid"] for e, o in zip(ends, (oa, ob)) if o["cell"] in grid.body]
            why = (f"the cable exit of the plug at {' and '.join(inner)} lies inside another pedal (see clearance)" if inner
                   else "no free path between the pedals")
            c["status"] = f"unroutable: {why}"
            sink.append(f"routing: {c['id']} ({c['from']} -> {c['to']}) is unroutable: {why}")
            continue
        c["_squeeze"] = bool(mode)
        nets.append((c["id"], oa["cell"], ob["cell"], bool(mode)))

    paths, users, overflow = route_all(grid, nets, int(cfg["max_stack"]), int(cfg["iterations"])) if grid else ({}, {}, set())
    ctx["routing"]["overflow"] = overflow
    for c in cables:
        if c["id"] not in paths:
            continue
        path = paths[c["id"]]
        if path is None:
            c["status"] = "unroutable: no free path between the pedals"
            sink.append(f"routing: {c['id']} ({c['from']} -> {c['to']}) has no free path between the pedals")
            continue
        oa, ob = chosen[c["id"]]
        squeezed = sum(1 for p in path if p in grid.blocked) * grid.cell
        first, last = grid.centre(path[0]), grid.centre(path[-1])
        ea, eb = oa["exit"], ob["exit"]
        length = (oa["measure_mm"] + ob["measure_mm"] + math.hypot(ea[0] - first[0], ea[1] - first[1]) + path_length(grid, path)
                  + math.hypot(eb[0] - last[0], eb[1] - last[1]))
        c.update(min_mm=length, status="routed",
                 path=list(oa["lead"]) + [grid.centre(p) for p in path] + list(reversed(ob["lead"])))
        if c.get("_squeeze") and squeezed:
            c["status"] = "routed, squeezed (gap narrower than the cable)"
            sink.append(f"routing: {c['id']} ({c['from']} -> {c['to']}) only fits by squeezing about {squeezed:.0f} mm of cable "
                        f"through gaps narrower than the {cfg['diameter_mm']:g} mm cable (move the pedals apart)")
        crowded = sorted({x for p in path if p in overflow for x in users[p]} - {c["id"]})
        if crowded:
            c["status"] = "routed, over the stacking limit"
            sink.append(f"routing: {c['id']} shares cells with {', '.join(crowded)} beyond the limit of {cfg['max_stack']} stacked cables")

    # clearance of every modelled plug, on the side the router chose
    checked = set()   # "<id>.<jack id>" checked with a plug model; the others keep jacks.check's fixed box
    for c in cables:
        if c["kind"] != "signal" or c["id"] not in chosen or c["type"] not in cable_types:
            continue
        ctype = cable_types[c["type"]]
        for e, o in zip(c["_sides"], chosen[c["id"]]):
            if not e or not o:
                continue
            ctx["routing"]["heads"].append({"cable": c["id"], "rects": o["rects"]})
            jk, facing = e["jack"], e["facing"]
            checked.add(f"{e['cid']}.{jk['id']}")
            how = f"{c['type']} {ctype['plug']['style'].replace('_', '-')} plug" + (f", cable exits {o['side']}" if o["side"] else "")
            for part, ob, depth in deepest_hits(o, facing):
                ctx["violations"].append({"jack": f"{e['cid']}.{jk['id']}", "obstacle": ob["title"], "depth_mm": depth,
                                          "cable": c["id"], "cable_type": c["type"], "side": o["side"], "part": part})
                clear_sink.append(f"clearance: {e['cid']}.{jk['id']} ({jk['label']}, facing {facing}, {how}) is blocked by "
                                  f"{ob['title']}: it reaches {depth:.1f} mm into the plug's {part}")
    checked |= power_plug_clearance(ctx, cables, cable_types, cfg, obstacles, clear_sink)
    report_fixed_box(ctx, checked)
    for c in cables:
        for k in ("_ends", "_sides", "_squeeze"):
            c.pop(k, None)


def deepest_hits(opt, facing):
    """[(part, obstacle, depth)] per obstacle of one plug option: the part it reaches deepest into."""
    best = {}
    for part, ob, ov in opt["hits"]:
        depth = design.part_depth(part, facing, opt["side"], ov)
        if ob["id"] not in best or depth > best[ob["id"]][2]:
            best[ob["id"]] = (part, ob, depth)
    return list(best.values())


def power_plug_clearance(ctx, cables, cable_types, cfg, obstacles, clear_sink):
    """Clearance of every placed pedal's power jack with the project's DC plug (`cables.power_type`): head + barrel
    + the cable's first straight run (one power-cable diameter) on the exit side with the fewest blocked parts
    (then the least overlap; a power cable override `exit_b` fixes it). The power cable then drops under the
    board, so nothing is routed. Without a power type, jacks.check uses the `jacks.power_clearance` box instead."""
    ptype = cable_types.get(cfg.get("power_type") or "")
    layout = ctx.get("layout") or {}
    checked = set()
    if not ptype or not layout.get("placed"):
        return checked
    from jacks import default_jack
    by_jack = {c["to"]: c for c in cables if c["kind"] == "power"}
    run = {"exit_run_mm": float(ptype["diameter_mm"])}
    for cid, it in layout["placed"].items():
        jk = default_jack((layout.get("jacks") or {}).get(cid) or [], "power")
        if not jk:
            continue
        pc = by_jack.get(f"{cid}.{jk['id']}")
        facing, opts = end_options(it, jk, ptype, (pc or {}).get("exit_b"), run, layout.get("outward_mm", 0))
        for o in opts:
            o["hits"] = blocked_parts(o, it["id"], obstacles)
        o = min(opts, key=lambda o: (len(o["hits"]), sum(min(ov) for _, _, ov in o["hits"])))
        if pc is not None:
            pc["exit_b"] = o["side"]
        ctx["routing"]["heads"].append({"cable": (pc or {}).get("id"), "rects": o["rects"]})
        checked.add(f"{cid}.{jk['id']}")
        how = f"{cfg['power_type']} {ptype['plug']['style'].replace('_', '-')} plug" + (f", cable exits {o['side']}" if o["side"] else "")
        for part, ob, depth in deepest_hits(o, facing):
            ctx["violations"].append({"jack": f"{cid}.{jk['id']}", "obstacle": ob["title"], "depth_mm": depth,
                                      "cable": (pc or {}).get("id"), "cable_type": cfg["power_type"], "side": o["side"], "part": part})
            clear_sink.append(f"clearance: {cid}.{jk['id']} ({jk['label']}, facing {facing}, {how}) is blocked by "
                              f"{ob['title']}: it reaches {depth:.1f} mm into the plug's {part}")
    return checked


# --- picture ------------------------------------------------------------------------------------
PALETTE = ["#e6194b", "#3cb44b", "#4363d8", "#f58231", "#911eb4", "#46f0f0", "#f032e6", "#9a6324",
           "#008080", "#800000", "#808000", "#000075", "#e6beff", "#aaffc3", "#ffd8b1", "#808080"]


def svg(ctx, names):
    """An SVG of the board, the routing area, the pedals and the routed signal cables."""
    r = ctx.get("routing") or {}
    grid, layout = r.get("grid"), ctx.get("layout")
    if not grid or not layout:
        return None
    board = design.footprint(layout["board"])
    pad = 20
    x0, y0 = grid.x0 - pad, grid.y0 - pad
    w, h = grid.nx * grid.cell + 2 * pad, (board[3] - grid.y0) + 2 * pad + 20
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{x0:.1f} {y0:.1f} {w:.1f} {h:.1f}" width="{w * 1.6:.0f}" '
           f'font-family="sans-serif">',
           f'<rect x="{x0}" y="{y0}" width="{w}" height="{h}" fill="#ffffff"/>',
           f'<rect x="{board[0]:.1f}" y="{board[1]:.1f}" width="{board[2] - board[0]:.1f}" height="{board[3] - board[1]:.1f}" '
           f'fill="#eceff1" stroke="#90a4ae" stroke-width="1"/>',
           f'<rect x="{grid.x0:.1f}" y="{grid.y0:.1f}" width="{grid.nx * grid.cell:.1f}" height="{r["front_y"] - grid.y0:.1f}" '
           f'fill="none" stroke="#78909c" stroke-dasharray="4 3" stroke-width="0.8"/>']
    for o in layout["obstacles"]:
        f = design.footprint(o)
        out.append(f'<rect x="{f[0]:.1f}" y="{f[1]:.1f}" width="{f[2] - f[0]:.1f}" height="{f[3] - f[1]:.1f}" fill="#cfd8dc" '
                   f'stroke="#455a64" stroke-width="0.8" rx="2"/>')
    for cid, it in layout["placed"].items():
        f = design.footprint(it)
        out.append(f'<text x="{(f[0] + f[2]) / 2:.1f}" y="{(f[1] + f[3]) / 2:.1f}" font-size="7" text-anchor="middle" fill="#263238">'
                   f'{names.get(cid, cid)[:18]}</text>')
    for c in r.get("overflow") or []:
        x, y, x2, y2 = grid.rect(c)
        out.append(f'<rect x="{x:.1f}" y="{y:.1f}" width="{x2 - x:.1f}" height="{y2 - y:.1f}" fill="#ff1744" opacity="0.35"/>')
    for h in r.get("heads") or []:
        for _, (hx0, hy0, hx1, hy1) in h["rects"]:
            out.append(f'<rect x="{hx0:.1f}" y="{hy0:.1f}" width="{hx1 - hx0:.1f}" height="{hy1 - hy0:.1f}" fill="#90a4ae" '
                       f'opacity="0.45" stroke="#37474f" stroke-width="0.3"/>')
    sig = [c for c in ctx.get("cable_list", []) if c["kind"] == "signal" and c.get("path")]
    for n, c in enumerate(sig):
        pts = " ".join(f"{x:.1f},{y:.1f}" for x, y in c["path"])
        col = PALETTE[n % len(PALETTE)]
        out.append(f'<polyline points="{pts}" fill="none" stroke="{col}" stroke-width="2.2" stroke-linejoin="round" opacity="0.85"/>')
        mx, my = c["path"][len(c["path"]) // 2]
        out.append(f'<text x="{mx:.1f}" y="{my - 2:.1f}" font-size="6" fill="{col}" font-weight="bold">{c["id"]}</text>')
    for pr in (x for x in ctx.get("footswitch_pairs") or [] if x.get("too_close")):
        (ax, ay), (bx, by) = pr["points"]
        out.append(f'<line x1="{ax:.1f}" y1="{ay:.1f}" x2="{bx:.1f}" y2="{by:.1f}" stroke="#d50000" stroke-width="1.2" '
                   f'stroke-dasharray="3 2"/>')
    for fp in ctx.get("footswitch_points") or []:   # filled: bypass switch, hollow: other switch
        out.append(f'<circle cx="{fp["x"]:.1f}" cy="{fp["y"]:.1f}" r="3.5" fill="{"#263238" if fp["bypass"] else "#ffffff"}" '
                   f'stroke="#263238" stroke-width="0.8"/>')
    out.append(f'<text x="{grid.x0:.1f}" y="{board[3] + 14:.1f}" font-size="7" fill="#455a64">dashed: routing area '
               f'(board + {r["settings"]["edge_margin_mm"]:g} mm at back and sides, nothing in front of the lowest pedals); '
               f'red: more than {r["settings"]["max_stack"]} stacked cables; grey: plug heads and their cable exits'
               + ('; dots: footswitches (filled = bypass), red dashed line: closer than the minimum'
                  if ctx.get("footswitch_points") else '') + '</text>')
    out.append("</svg>")
    return "\n".join(out) + "\n"
