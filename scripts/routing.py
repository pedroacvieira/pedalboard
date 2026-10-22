"""Cable model and on-board cable routing (all mm). Pure: no network, no GUI.

Signal cables (each pedal's output -> the next pedal's input) are routed on the board surface:
  - the routing area is the pedalboard plus `edge_margin_mm` (default: one cable diameter) beyond its
    back and sides; nothing may run in front of (below) the lowest row of pedals;
  - pedal bodies are obstacles (supplies under the board are not);
  - the area is a grid of `grid_mm` cells (default 2 mm); pedals are grown by the cable radius minus half a
    cell, so any gap at least one cable diameter wide is a corridor; at most `max_stack` cables (default 2,
    stacked on top of each other) may share a cell;
  - each cable leaves its jack straight out along the jack's facing (the clearance depth), then follows
    the shortest 8-connected path; crowded cells are resolved by rip-up-and-reroute with rising
    congestion costs (negotiated congestion, as in FPGA routers).
Power cables get the same cable model (tips, centre polarity, under_board) and a length estimate, but are
not routed yet: the supplies sit under the board and under-board routing does not exist yet.
"""
import heapq
import math

import design

DEFAULTS = {
    "diameter_mm": 6.0,          # cable diameter (Fender patch cable); jack heads are ignored
    "max_stack": 2,              # cables allowed on top of each other in one cell
    "default_tip": "TS",         # signal plugs unless a jack or an override says TRS / XLR
    "power_tip": "DC 2.1 mm",
    "power_polarity": "center_negative",
    "iterations": 40,
}
TIPS = ("TS", "TRS", "XLR", "DC 2.1 mm", "DC 2.5 mm")
POLARITIES = ("center_negative", "center_positive")
NEIGHBOURS = [(1, 0), (-1, 0), (0, 1), (0, -1), (1, 1), (1, -1), (-1, 1), (-1, -1)]


def settings(project):
    s = {**DEFAULTS, **project.get("cables", {})}
    s.setdefault("grid_mm", 2.0)
    s.setdefault("edge_margin_mm", s["diameter_mm"])
    s.setdefault("overrides", {})
    return s


# --- grid ---------------------------------------------------------------------------------------
class Grid:
    """Square cells over the routing area; `free(c)` tells whether a cable may pass through a cell."""

    def __init__(self, x0, y0, x1, y1, cell):
        self.x0, self.y0, self.cell = x0, y0, cell
        self.nx, self.ny = max(1, math.ceil((x1 - x0) / cell)), max(1, math.ceil((y1 - y0) / cell))
        self.blocked = set()

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
def astar(grid, start, goal, cell_cost):
    """Cheapest 8-connected path from start to goal; diagonals may not cut obstacle corners.
    start/goal are always enterable (they are the plug ends, possibly squeezed against a pedal)."""
    def passable(c):
        return grid.inside(c) and (c in (start, goal) or c not in grid.blocked)

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
    """nets: [(name, start_cell, goal_cell)]. Returns ({name: path or None}, {cell: [names]}, overflow cells).

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
        for name, s, t in nets:
            for c in paths.get(name) or []:
                usage[c] -= 1

            def cost(c):
                over = max(0, usage.get(c, 0) + 1 - max_stack)
                return (1.0 + history.get(c, 0.0)) * (1.0 + present * over * 10)

            paths[name] = astar(grid, s, t, cost)
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
def _round_up(mm, step=50):
    return int(math.ceil(mm / step) * step)


def route_project(ctx, cat_pedals, slack_mm=50):
    """Build ctx['cable_list'] (signal + power cables with attributes) and route the signal cables."""
    project, warnings, errors = ctx["project"], ctx["warnings"], ctx["errors"]
    cfg = settings(project)
    sink = errors if project.get("validation", {}).get("strict_routing") else warnings
    ctx["routing"] = {"settings": cfg, "grid": None, "overflow": set(), "front_y": None}
    layout = ctx.get("layout")
    cables = []
    over = cfg["overrides"]

    def tip_of(jack, default):
        return (jack or {}).get("connector") or default

    # signal cables, one per hop of the chain
    chain = ctx["chain"]
    jd = (layout or {}).get("jacks") or {}
    from jacks import default_jack  # late import: jacks imports design only
    for n, (a, b) in enumerate(zip(chain, chain[1:]), 1):
        ja, jb = default_jack(jd.get(a) or [], "output"), default_jack(jd.get(b) or [], "input")
        c = {"id": f"S{n}", "kind": "signal", "from": f"{a}.{ja['id'] if ja else 'out'}", "to": f"{b}.{jb['id'] if jb else 'in'}",
             "tip_a": tip_of(ja, cfg["default_tip"]), "tip_b": tip_of(jb, cfg["default_tip"]), "under_board": False,
             "routed_mm": None, "suggested_mm": None, "path": None, "status": "not routed", "_ends": (a, ja, b, jb)}
        cables.append(c)
    # power cables: model and estimate only (they run under the board)
    under = (project.get("jacks", {}).get("supplies_layer", "under") == "under")
    for n, hop in enumerate((ctx.get("cables") or {}).get("power", []), 1):
        cables.append({"id": f"P{n}", "kind": "power", "from": hop["from"], "to": hop["to"], "tip_a": cfg["power_tip"], "tip_b": cfg["power_tip"],
                       "polarity": cfg["power_polarity"], "under_board": under, "routed_mm": None,
                       "suggested_mm": hop.get("suggested_mm"), "estimate_mm": hop.get("routed_mm"), "path": None,
                       "status": "not routed (under the board)" if under else "not routed (power routing not implemented)"})
    for c in cables:
        for k, v in over.get(c["id"], {}).items():
            c[k] = v
        bad = [f"{k}={c[k]}" for k in ("tip_a", "tip_b") if c[k] not in TIPS] + \
              ([f"polarity={c['polarity']}"] if c["kind"] == "power" and c["polarity"] not in POLARITIES else [])
        if bad:
            errors.append(f"cables: {c['id']} has unknown {', '.join(bad)} (tips: {', '.join(TIPS)}; polarity: {', '.join(POLARITIES)})")
    ctx["cable_list"] = cables
    if not layout or not layout.get("board"):
        return

    placed, outward = layout["placed"], layout["outward_mm"]
    board = design.footprint(layout["board"])
    feet = {cid: design.footprint(it) for cid, it in placed.items()}
    front_y = min(board[3], max((f[3] for f in feet.values()), default=board[3]))   # nothing in front of the lowest pedals
    grid = build_grid(board, [design.footprint(o) for o in layout["obstacles"]], front_y, cfg)
    ctx["routing"].update(grid=grid, front_y=front_y)

    nets = []
    for c in (x for x in cables if x["kind"] == "signal"):
        a, ja, b, jb = c["_ends"]
        if not (ja and jb and a in placed and b in placed):
            c["status"] = "not routed (jack or placement missing)"
            continue
        ends = []
        for cid, jk in ((a, ja), (b, jb)):
            pt = design.jack_point(placed[cid], jk["x"], jk["y"])
            st = design.stub(pt, design.jack_facing(placed[cid], jk["facing"]), outward)
            ends.append((pt, st, grid.cell_of(*st)))
        if not all(grid.inside(e[2]) for e in ends):
            c["status"] = "unroutable: a plug end is outside the routing area (in front of the lowest pedals or beyond the margin)"
            sink.append(f"routing: {c['id']} ({c['from']} -> {c['to']}) {c['status'][len('unroutable: '):]}")
            continue
        c["_geom"] = ends
        nets.append((c["id"], ends[0][2], ends[1][2]))

    paths, users, overflow = route_all(grid, nets, int(cfg["max_stack"]), int(cfg["iterations"]))
    ctx["routing"]["overflow"] = overflow
    for c in cables:
        if c["id"] not in paths:
            continue
        path = paths[c["id"]]
        if path is None:
            c["status"] = "unroutable: no free path between the pedals"
            sink.append(f"routing: {c['id']} ({c['from']} -> {c['to']}) has no free path between the pedals")
            continue
        (pa, sa, _), (pb, sb, _) = c["_geom"]
        first, last = grid.centre(path[0]), grid.centre(path[-1])
        length = (2 * outward + math.hypot(sa[0] - first[0], sa[1] - first[1]) + path_length(grid, path)
                  + math.hypot(sb[0] - last[0], sb[1] - last[1]))
        c.update(routed_mm=length, suggested_mm=_round_up(length + slack_mm), status="routed",
                 path=[pa, sa] + [grid.centre(p) for p in path] + [sb, pb])
        crowded = sorted({x for p in path if p in overflow for x in users[p]} - {c["id"]})
        if crowded:
            c["status"] = "routed, over the stacking limit"
            sink.append(f"routing: {c['id']} shares cells with {', '.join(crowded)} beyond the limit of {cfg['max_stack']} stacked cables")
    for c in cables:
        c.pop("_ends", None)
        c.pop("_geom", None)


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
    sig = [c for c in ctx.get("cable_list", []) if c["kind"] == "signal" and c.get("path")]
    for n, c in enumerate(sig):
        pts = " ".join(f"{x:.1f},{y:.1f}" for x, y in c["path"])
        col = PALETTE[n % len(PALETTE)]
        out.append(f'<polyline points="{pts}" fill="none" stroke="{col}" stroke-width="2.2" stroke-linejoin="round" opacity="0.85"/>')
        mx, my = c["path"][len(c["path"]) // 2]
        out.append(f'<text x="{mx:.1f}" y="{my - 2:.1f}" font-size="6" fill="{col}" font-weight="bold">{c["id"]}</text>')
    out.append(f'<text x="{grid.x0:.1f}" y="{board[3] + 14:.1f}" font-size="7" fill="#455a64">dashed: routing area '
               f'(board + {r["settings"]["edge_margin_mm"]:g} mm at back and sides, nothing in front of the lowest pedals); '
               f'red: more than {r["settings"]["max_stack"]} stacked cables</text>')
    out.append("</svg>")
    return "\n".join(out) + "\n"
