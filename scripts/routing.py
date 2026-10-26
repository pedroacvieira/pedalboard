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
    rising congestion costs (negotiated congestion, as in FPGA routers); at most `max_over_plug` (default 2)
    other cables may cross one plug (head or barrel), handled the same way;
  - the grid path is then reduced to its necessary corners (`smooth`: any-angle straight segments that stay as
    far from the pedals as the grid path did and cross no plug it did not cross); the minimum cable length
    follows the smoothed path;
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
import re

import design

DEFAULTS = {
    "type": None,                # default patch cable type (catalog/cables.json, role patch); None: no plug model
    "power_type": None,          # DC plug type for power-jack clearance (role power); None: the jacks.power_clearance box
    "diameter_mm": 6.0,          # routing width of a signal cable; the type's diameter_mm (on-board width) when a type is set
    "max_stack": 2,              # cables allowed on top of each other in one cell
    "max_over_plug": 2,          # other cables allowed across one plug (head + barrel); the plug's own cable never counts
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
        cells = rect_cells(self, r, grow)
        self.blocked |= cells
        self.body |= {c for c in cells if r[0] <= self.centre(c)[0] <= r[2] and r[1] <= self.centre(c)[1] <= r[3]}
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


def grow_of(cfg):
    """How far pedals (and plugs, for the plug limit) are grown for the cell-centre test: the cable radius minus
    half a cell, so every gap at least one cable diameter wide keeps a row of free cell centres."""
    return max(0.0, cfg["diameter_mm"] / 2 - cfg["grid_mm"] / 2 - 0.01)


def rect_cells(grid, r, grow=0.0):
    """Cells whose centre lies inside rectangle r grown by `grow` (what `Grid.block_rect` blocks)."""
    x0, y0, x1, y1 = r[0] - grow, r[1] - grow, r[2] + grow, r[3] + grow
    out = set()
    for i in range(max(0, int((x0 - grid.x0) / grid.cell) - 1), min(grid.nx, int((x1 - grid.x0) / grid.cell) + 2)):
        for j in range(max(0, int((y0 - grid.y0) / grid.cell) - 1), min(grid.ny, int((y1 - grid.y0) / grid.cell) + 2)):
            cx, cy = grid.centre((i, j))
            if x0 <= cx <= x1 and y0 <= cy <= y1:
                out.add((i, j))
    return out


def build_grid(board_rect, obstacle_rects, front_y, cfg):
    """Routing area = board + margin at the back and sides, cut off at `front_y` (no cables in front)."""
    m = cfg["edge_margin_mm"]
    x0, y0, x1 = board_rect[0] - m, board_rect[1] - m, board_rect[2] + m
    g = Grid(x0, y0, x1, front_y, cfg["grid_mm"])
    # a gap narrower than one cable diameter may still pass by up to half a cell: grid accuracy
    grow = grow_of(cfg)
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


def route_all(grid, nets, max_stack, iterations=40, plugs=None, max_over_plug=2):
    """nets: [(name, start_cell, goal_cell[, squeeze])]. Returns ({name: path or None}, {cell: [names]}, overflow cells,
    plug_over).

    Every round, each net is ripped up and re-routed against the others' current paths; a cell already holding
    `max_stack` cables costs more (present factor, growing each round), and cells that stayed over the limit
    get a permanent history cost, so cables spread out until the limit holds (or the rounds run out).

    plugs: {key: (owner cable name or None, cells)}. A net entering a cell of a plug it does not own, where that
    plug already carries `max_over_plug` OTHER cables (owner and this net excluded), pays the over-limit penalty
    like an over-stacked cell; plugs still over the limit after a round get a history cost (for the cables that
    do not own them). plug_over = {key: [names]}: the plugs that stayed over the limit, with their crossing cables."""
    plugs = plugs or {}
    plug_at = {}   # cell -> [plug keys]
    for key, (_, cells) in plugs.items():
        for c in cells:
            plug_at.setdefault(c, []).append(key)
    history, plug_history, paths, present = {}, {}, {}, 0.5
    cross = {key: set() for key in plugs}   # plug key -> cables other than its owner whose path enters it

    def crossed(name, path):
        """plugs a path enters, not counting its own plugs nor its two end cells (a cable may start next to a plug)"""
        return {k for c in (path or [])[1:-1] for k in plug_at.get(c, ()) if plugs[k][0] != name}

    for _ in range(iterations):
        usage = {}
        for path in paths.values():
            for c in path or []:
                usage[c] = usage.get(c, 0) + 1
        for name, s, t, *sq in nets:
            for c in paths.get(name) or []:
                usage[c] -= 1
            for k in crossed(name, paths.get(name)):
                cross[k].discard(name)

            def cost(c):
                over = max(0, usage.get(c, 0) + 1 - max_stack)
                hist = history.get(c, 0.0)
                if c != s and c != t:
                    for key in plug_at.get(c, ()):
                        if plugs[key][0] != name:
                            over += len(cross[key]) >= max_over_plug
                            hist += plug_history.get(key, 0.0)
                return (1.0 + hist) * (1.0 + present * over * 10)

            paths[name] = astar(grid, s, t, cost, squeeze=bool(sq and sq[0]))
            for c in paths[name] or []:
                usage[c] = usage.get(c, 0) + 1
            for k in crossed(name, paths[name]):
                cross[k].add(name)
        overflow = {c for c, n in usage.items() if n > max_stack}
        too_many = {k for k, v in cross.items() if len(v) > max_over_plug}
        if not overflow and not too_many:
            break
        for c in overflow:
            history[c] = history.get(c, 0.0) + 0.5
        for k in too_many:
            plug_history[k] = plug_history.get(k, 0.0) + 0.5
        present *= 1.6
    users = {}
    for name, path in paths.items():
        for c in path or []:
            users.setdefault(c, []).append(name)
    plug_over = {k: sorted(v) for k, v in cross.items() if len(v) > max_over_plug}
    return paths, users, {c for c, u in users.items() if len(u) > max_stack}, plug_over


def path_length(grid, path):
    return sum(grid.cell * (math.sqrt(2) if a[0] != b[0] and a[1] != b[1] else 1.0) for a, b in zip(path, path[1:]))


# --- smoothing ----------------------------------------------------------------------------------
def point_rect_distance(p, r):
    return math.hypot(max(r[0] - p[0], 0.0, p[0] - r[2]), max(r[1] - p[1], 0.0, p[1] - r[3]))


def point_seg_distance(c, p, q):
    dx, dy = q[0] - p[0], q[1] - p[1]
    n = dx * dx + dy * dy
    t = 0.0 if n == 0 else max(0.0, min(1.0, ((c[0] - p[0]) * dx + (c[1] - p[1]) * dy) / n))
    return math.hypot(c[0] - (p[0] + t * dx), c[1] - (p[1] + t * dy))


def seg_rect_distance(p, q, r):
    """Exact distance between segment pq and the (closed) rectangle r = (x0, y0, x1, y1); 0 if they intersect."""
    t0, t1 = 0.0, 1.0   # Liang-Barsky: the part of the segment inside the rectangle
    for lo, hi, a, da in ((r[0], r[2], p[0], q[0] - p[0]), (r[1], r[3], p[1], q[1] - p[1])):
        if da == 0:
            if a < lo or a > hi:
                t0, t1 = 1.0, 0.0
            continue
        ta, tb = (lo - a) / da, (hi - a) / da
        t0, t1 = max(t0, min(ta, tb)), min(t1, max(ta, tb))
    if t0 <= t1:
        return 0.0
    # disjoint convex shapes: the minimum is reached at a vertex of one of them
    corners = ((r[0], r[1]), (r[2], r[1]), (r[2], r[3]), (r[0], r[3]))
    return min([point_rect_distance(p, r), point_rect_distance(q, r)] + [point_seg_distance(c, p, q) for c in corners])


def polyline_length(points):
    return sum(math.hypot(b[0] - a[0], b[1] - a[1]) for a, b in zip(points, points[1:]))


def smooth(points, obstacles, radius, plugs, own_plugs=()):
    """Reduce a routed polyline [exit_a, cell centres..., exit_b] to its necessary corners (string pulling).

    From the anchor p_i, p_j (j = i+2, i+3, ...) is accepted while the straight segment (p_i, p_j) is valid; the
    first invalid j stops the search and the last valid one becomes the next corner. A segment is valid when
      (a) it keeps at least min(radius, the closest any replaced point p_i..p_j came to that rectangle) from every
          obstacle rectangle: never closer to a pedal than the grid path was (a squeezed stretch stays as it is,
          a free one keeps the full cable radius);
      (b) every plug it touches (`plugs`: {key: [rects]}; touched = within `radius`) was also touched by one of the
          replaced consecutive segments, or is in `own_plugs`.
    The first and last point are kept."""
    eps = 1e-6
    n = len(points)
    if n <= 2:
        return list(points)
    # every segment between two path points lies in the points' bounding box: only plugs near it can be touched
    bx0, by0 = min(p[0] for p in points) - radius, min(p[1] for p in points) - radius
    bx1, by1 = max(p[0] for p in points) + radius, max(p[1] for p in points) + radius
    near = lambda r: r[0] <= bx1 and r[2] >= bx0 and r[1] <= by1 and r[3] >= by0
    plugs = {k: rs for k, rs in plugs.items() if k not in own_plugs and any(near(r) for r in rs)}
    obstacles = [o for o in obstacles if near(o)]   # farther than the radius from every segment: always clear
    touch = lambda p, q, key: any(seg_rect_distance(p, q, r) <= radius for r in plugs[key])
    # never closer than the grid path; a replaced point touching or inside a pedal (a plug exit inside a neighbour)
    # allows no shortcut through it: the segment must then stay clear of that pedal
    clear = lambda d, c: d >= min(radius, c) - eps if c > eps else d > eps
    steps = [{k for k in plugs if touch(a, b, k)} for a, b in zip(points, points[1:])]   # plugs per grid step
    out, i = [points[0]], 0
    while i < n - 1:
        # over the replaced points: closest approach per obstacle, plugs touched by the replaced segments
        closest = [min(point_rect_distance(points[i], o), point_rect_distance(points[i + 1], o)) for o in obstacles]
        allowed = set(steps[i])
        best, j = i + 1, i + 2
        while j < n:
            closest = [min(c, point_rect_distance(points[j], o)) for c, o in zip(closest, obstacles)]
            allowed |= steps[j - 1]
            p, q = points[i], points[j]
            if not all(clear(seg_rect_distance(p, q, o), c) for o, c in zip(obstacles, closest)):
                break
            if not all(k in allowed or k in own_plugs for k in plugs if touch(p, q, k)):
                break
            best, j = j, j + 1
        out.append(points[best])
        i = best
    return out


# --- lanes: drawing geometry for cables that share a corridor ---------------------------------------
def natural_key(cid):
    """Sort key putting S2 before S10."""
    return [int(t) if t.isdigit() else t for t in re.split(r"(\d+)", cid)]


def _unit(p, q):
    n = math.hypot(q[0] - p[0], q[1] - p[1])
    return None if n < 1e-9 else ((q[0] - p[0]) / n, (q[1] - p[1]) / n)


def lane_pair(s, t, width):
    """Segments s = (p, q) and t of two cables belong together when they are nearly parallel (<= 10 deg), overlap by at
    least `width` along the longer one and their centrelines stay closer than `width` over that overlap."""
    if polyline_length(s) < polyline_length(t):
        s, t = t, s
    u, v = _unit(*s), _unit(*t)
    if u is None or v is None or abs(u[0] * v[1] - u[1] * v[0]) > math.sin(math.radians(10)):
        return False
    n = (-u[1], u[0])
    ta, tb = ((p[0] - s[0][0]) * u[0] + (p[1] - s[0][1]) * u[1] for p in t)
    lo, hi = max(0.0, min(ta, tb)), min(polyline_length(s), max(ta, tb))
    if hi - lo < width - 1e-6:
        return False
    wa, wb = ((p[0] - s[0][0]) * n[0] + (p[1] - s[0][1]) * n[1] for p in t)   # t's side position at its two ends
    at = lambda x: wa + (x - ta) / (tb - ta) * (wb - wa)
    return max(abs(at(lo)), abs(at(hi))) < width - 1e-6


def lane_bundles(routes, width):
    """Groups of segments (cable id, segment index) that run side by side: pairs of `lane_pair` joined (union-find)."""
    segs = [(cid, j) for cid, (pts, _) in routes.items() for j in range(len(pts) - 1)]
    seg = lambda s: routes[s[0]][0][s[1]:s[1] + 2]
    parent = {s: s for s in segs}

    def find(s):
        while parent[s] != s:
            parent[s] = s = parent[parent[s]]
        return s

    for i, s in enumerate(segs):
        for t in segs[i + 1:]:
            if s[0] != t[0] and find(s) != find(t) and lane_pair(seg(s), seg(t), width):
                parent[find(s)] = find(t)
    groups = {}
    for s in segs:
        groups.setdefault(find(s), []).append(s)
    key = lambda s: (natural_key(s[0]), s[1])
    return sorted((sorted(g, key=key) for g in groups.values() if len(g) > 1), key=lambda g: key(g[0]))


def offset_polyline(pts, shift):
    """pts shifted per segment by shift[j] (a vector); the corners are mitred (intersection of the shifted lines),
    nearly parallel neighbours (< 5 deg) meet at the midpoint of their shifted ends, a sharper turn than 6 x the
    shift gets a bevel. The first and last point never move: a shifted first / last segment gets an extra corner.
    Returns (points, src): src[t] = index of the original segment the new segment t -> t+1 comes from."""
    m = len(pts) - 1
    out, src = [pts[0]], []
    plus = lambda p, v: (p[0] + v[0], p[1] + v[1])

    def add(p, j):
        out.append(p)
        src.append(j)

    if shift[0] != (0.0, 0.0):
        add(plus(pts[0], shift[0]), 0)
    for j in range(1, m):
        a, b = shift[j - 1], shift[j]
        if a == b == (0.0, 0.0):
            add(pts[j], j - 1)
            continue
        da, db = _unit(pts[j - 1], pts[j]), _unit(pts[j], pts[j + 1])
        pa, pb = plus(pts[j], a), plus(pts[j], b)
        cross = None if da is None or db is None else da[0] * db[1] - da[1] * db[0]
        if cross is None or abs(cross) < math.sin(math.radians(5)):
            add(((pa[0] + pb[0]) / 2, (pa[1] + pb[1]) / 2), j - 1)
            continue
        t = ((pb[0] - pa[0]) * db[1] - (pb[1] - pa[1]) * db[0]) / cross
        p = (pa[0] + t * da[0], pa[1] + t * da[1])
        if math.hypot(p[0] - pts[j][0], p[1] - pts[j][1]) > 6 * max(math.hypot(*a), math.hypot(*b)):
            add(pa, j - 1)
            add(pb, j - 1)
        else:
            add(p, j - 1)
    if shift[m - 1] != (0.0, 0.0):
        add(plus(pts[m], shift[m - 1]), m - 1)
    add(pts[m], m - 1)
    return out, src


LANE_STEP = 0.25   # mm: search step of a lane set's sideways shift (see lanes)


def lanes(routes, pedal_rects, plug_rects, area, width):
    """Draw cables that run along the same corridor side by side, `width` apart (drawing geometry only: lengths
    never change).  routes: {cable id: (corners, own plug keys)}, the corners from exit to exit; area = (x0, y0,
    x1, y1) of the routing area.  Returns {cable id: {"corners": the corners with the lane offsets, "stacked":
    sorted ids of the cables it is drawn on top of, "stacked_runs": the stacked stretches as polylines}}.

    Bundles (`lane_bundles`): each cable gets one lane per bundle, ordered by the side it comes from and goes to
    (perpendicular position of the corner before and after the bundle, summed; ties by id), so lanes do not cross.
    A bundle is accepted when every changed segment keeps the smoothing rules (at least min(radius, the original
    distance) from every pedal, touches no other plug than the original did) and stays inside the area; the lane set may
    shift sideways off its centre (cables hug pedal edges: closest to centred first), first at full, then at half
    spacing; else it stays on the original centrelines and its cables are `stacked`."""
    radius, eps = width / 2, 1e-6
    shifts = {cid: [(0.0, 0.0)] * (len(pts) - 1) for cid, (pts, _) in routes.items()}
    stacked = {cid: set() for cid in routes}
    stacked_segs = {cid: set() for cid in routes}   # segment indices of the cable in a stacked bundle
    touch = lambda p, q, rs: any(seg_rect_distance(p, q, r) <= radius for r in rs)
    clear = lambda d, orig: d >= min(radius, orig) - eps if orig > eps else d > eps   # as in smooth

    def valid(cid, trial):
        pts, own = routes[cid]
        new, src = offset_polyline(pts, trial)
        if not all(area[0] - eps <= x <= area[2] + eps and area[1] - eps <= y <= area[3] + eps for x, y in new):
            return False
        for (p, q), j in zip(zip(new, new[1:]), src):
            a, b = pts[j], pts[j + 1]
            if (p, q) == (a, b) or p == q:
                continue
            x0, y0 = min(p[0], q[0], a[0], b[0]) - radius, min(p[1], q[1], a[1], b[1]) - radius
            x1, y1 = max(p[0], q[0], a[0], b[0]) + radius, max(p[1], q[1], a[1], b[1]) + radius
            near = [r for r in pedal_rects if r[0] <= x1 and r[2] >= x0 and r[1] <= y1 and r[3] >= y0]   # others: clear
            if any(not clear(seg_rect_distance(p, q, r), seg_rect_distance(a, b, r)) for r in near):
                return False
            if any(k not in own and touch(p, q, rs) and not touch(a, b, rs) for k, rs in plug_rects.items()):
                return False
        return True

    for members in lane_bundles(routes, width):
        by_cable = {}
        for cid, j in members:
            by_cable.setdefault(cid, []).append(j)
        longest = max(members, key=lambda s: polyline_length(routes[s[0]][0][s[1]:s[1] + 2]))
        o, e = routes[longest[0]][0][longest[1]:longest[1] + 2]
        d = _unit(o, e)
        n = (-d[1], d[0])
        pos = lambda p: (p[0] - o[0]) * n[0] + (p[1] - o[1]) * n[1]

        def side(cid):
            pts, js = routes[cid][0], by_cable[cid]
            before = pts[min(js) - 1] if min(js) > 0 else pts[0]       # where the cable comes from / goes to
            after = pts[max(js) + 2] if max(js) + 2 < len(pts) else pts[-1]
            return round(pos(before) + pos(after), 6)

        order = sorted(by_cable, key=lambda c: (side(c), natural_key(c)))
        k = len(order)
        # smoothed cables hug pedal edges, so the lane set may shift off-centre: the first lane's offset is searched in
        # LANE_STEP steps from one spacing beyond one-sided on either side, closest to centred first
        span = lambda s: [round(-(k - 1) * s - s + LANE_STEP * m, 6) for m in range(int(round((k + 1) * s / LANE_STEP)) + 1)]
        for spacing, first in ((s, f) for s in (width, width / 2)
                               for f in sorted(span(s), key=lambda f: (abs(f + (k - 1) * s / 2), f))):
            trial = {cid: list(s) for cid, s in shifts.items()}
            for i, cid in enumerate(order):
                off = first + i * spacing
                for j in by_cable[cid]:
                    trial[cid][j] = (off * n[0], off * n[1])
            if all(valid(cid, trial[cid]) for cid in order):
                shifts = trial
                break
        else:
            for cid in order:
                stacked[cid] |= set(order) - {cid}
                stacked_segs[cid] |= set(by_cable[cid])

    def result(cid):
        pts = routes[cid][0]
        new, src = offset_polyline(pts, shifts[cid]) if any(s != (0.0, 0.0) for s in shifts[cid]) else \
            (list(pts), list(range(len(pts) - 1)))
        runs = []   # consecutive drawn segments that come from stacked segments, on the drawn (mitred) geometry
        for t, j in enumerate(src):
            if j not in stacked_segs[cid]:
                continue
            if runs and runs[-1][1] == t:
                runs[-1] = (runs[-1][0], t + 1)
            else:
                runs.append((t, t + 1))
        return {"corners": new, "stacked": sorted(stacked[cid], key=natural_key),
                "stacked_runs": [new[a:b + 1] for a, b in runs]}

    return {cid: result(cid) for cid in routes}


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


def blocked_parts(opt, own_id, obstacles, shapes=None):
    """[(part, obstacle item, overlap)] for one plug option against every other pedal's outline (`shapes` {item id:
    [canvas rects]}, else its footprint; `design.shape_overlap`), one hit per (part, obstacle)."""
    hits = []
    for part, r in opt["rects"]:
        for ob in obstacles:
            if ob["id"] == own_id:
                continue
            ov = design.shape_overlap(r, design.item_shapes(shapes, ob))
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
    from jacks import placement
    inst_by_id = {s["inst"]["id"]: s["inst"] for s in ctx.get("supplies") or []}
    for n, hop in enumerate((ctx.get("cables") or {}).get("power", []), 1):
        under = hop.get("under_board")   # jacks.check sets it per hop; else the placement of the instance the cable starts at
        if under is None:
            inst = inst_by_id.get(hop["from"].split(".")[0])
            under = placement(inst if inst is not None else {}, project) != "on_board"
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
    shapes = layout.get("shapes") or {}

    def shapes_of(it):
        return design.item_shapes(shapes, it)
    grid = None   # without a pedalboard item nothing is routed, but every plug is still checked
    if layout.get("board"):
        board = design.footprint(layout["board"])
        feet = [r for it in placed.values() for r in shapes_of(it)]
        front_y = min(board[3], max((f[3] for f in feet), default=board[3]))   # nothing in front of the lowest pedals
        grid = build_grid(board, [r for o in obstacles for r in shapes_of(o)], front_y, cfg)
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
                o["hits"] = blocked_parts(o, placed[cid]["id"], obstacles, shapes)
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

    # every plug of the layout (head + barrel): the power plugs' sides are chosen before routing, as the signal ones
    power_choices = power_plug_choices(ctx, cables, cable_types, cfg, obstacles) if grid else []
    plug_rects, plug_owner = {}, {}   # "<pedal id>.<jack id>" -> [head / barrel rects], owner cable id
    if grid:
        for c in (x for x in cables if x["kind"] == "signal" and x["id"] in chosen):
            for e, o in zip(c["_sides"], chosen[c["id"]]):
                if e and o:
                    plug_rects[f"{e['cid']}.{e['jack']['id']}"], plug_owner[f"{e['cid']}.{e['jack']['id']}"] = \
                        [r for part, r in o["rects"] if part in ("head", "barrel")], c["id"]
        for cid, jk, pc, _, o in power_choices:
            plug_rects[f"{cid}.{jk['id']}"], plug_owner[f"{cid}.{jk['id']}"] = \
                [r for part, r in o["rects"] if part in ("head", "barrel")], (pc or {}).get("id")
    plug_rects = {k: v for k, v in plug_rects.items() if v}
    grow = grow_of(cfg)
    plugs = {k: (plug_owner[k], set().union(*(rect_cells(grid, r, grow) for r in rs))) for k, rs in plug_rects.items()}
    paths, users, overflow, plug_over = (route_all(grid, nets, int(cfg["max_stack"]), int(cfg["iterations"]), plugs,
                                                   int(cfg["max_over_plug"])) if grid else ({}, {}, set(), {}))
    ctx["routing"]["overflow"] = overflow
    ctx["routing"]["plug_over"] = plug_over
    pedal_rects = [r for o in obstacles for r in shapes_of(o)]
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
        own = {f"{e['cid']}.{e['jack']['id']}" for e in c["_sides"]}
        corners = smooth([oa["exit"]] + [grid.centre(p) for p in path] + [ob["exit"]], pedal_rects, cfg["diameter_mm"] / 2,
                         plug_rects, own)
        c.update(min_mm=oa["measure_mm"] + ob["measure_mm"] + polyline_length(corners), status="routed",
                 path=list(oa["lead"][:-1]) + corners + list(reversed(ob["lead"]))[1:])
        c["_corners"], c["_own"] = corners, own
        c["_leads"] = (list(oa["lead"][:-1]), list(reversed(ob["lead"]))[1:])   # fixed geometry round the routed corners
        if c.get("_squeeze") and squeezed:
            c["status"] = "routed, squeezed (gap narrower than the cable)"
            sink.append(f"routing: {c['id']} ({c['from']} -> {c['to']}) only fits by squeezing about {squeezed:.0f} mm of cable "
                        f"through gaps narrower than the {cfg['diameter_mm']:g} mm cable (move the pedals apart)")
        crowded = sorted({x for p in path if p in overflow for x in users[p]} - {c["id"]})
        if crowded:
            c["status"] += ", over the stacking limit"
            sink.append(f"routing: {c['id']} shares cells with {', '.join(crowded)} beyond the limit of {cfg['max_stack']} stacked cables")
    by_id = {c["id"]: c for c in cables}
    for key, names in sorted(plug_over.items()):
        who = ", ".join(names[:-1]) + " and " + names[-1] if len(names) > 1 else names[0]
        sink.append(f"routing: {who} {'cross' if len(names) > 1 else 'crosses'} the plug at {key} (limit {cfg['max_over_plug']} other cables)")
        for n in names:
            by_id[n]["status"] += ", over the plug limit"   # appended: a cable keeps every problem it has

    # lanes: cables along the same corridor are drawn side by side (drawing only: path and min_mm stay on the centrelines)
    routed = {c["id"]: (c["_corners"], c["_own"]) for c in cables if "_corners" in c}
    laned = lanes(routed, pedal_rects, plug_rects, (grid.x0, grid.y0, grid.x0 + grid.nx * grid.cell, front_y),
                  cfg["diameter_mm"]) if routed else {}
    for c in cables:
        if c["id"] in laned:
            lead_a, lead_b = c["_leads"]
            c["draw_path"] = lead_a + laned[c["id"]]["corners"] + lead_b
            c["stacked_with"] = laned[c["id"]]["stacked"]
            c["stacked_runs"] = laned[c["id"]]["stacked_runs"]

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
    checked |= power_plug_clearance(ctx, cables, cable_types, cfg, obstacles, clear_sink, power_choices if grid else None)
    report_fixed_box(ctx, checked)
    for c in cables:
        for k in ("_ends", "_sides", "_squeeze", "_corners", "_own", "_leads"):
            c.pop(k, None)


def deepest_hits(opt, facing):
    """[(part, obstacle, depth)] per obstacle of one plug option: the part it reaches deepest into."""
    best = {}
    for part, ob, ov in opt["hits"]:
        depth = design.part_depth(part, facing, opt["side"], ov)
        if ob["id"] not in best or depth > best[ob["id"]][2]:
            best[ob["id"]] = (part, ob, depth)
    return list(best.values())


def power_plug_choices(ctx, cables, cable_types, cfg, obstacles):
    """The DC plug of every placed pedal's power jack (`cables.power_type`) with the exit side that has the fewest
    blocked parts (then the least overlap; a power cable override `exit_b` fixes it): [(pedal id, jack, power cable
    or None, facing, plug option)]. Sets the power cable's `exit_b`. Also every used port of an on-board supply
    ("<instance id>" instead of the pedal id; the cable starting at the port, its side is `exit_a`). Empty without a
    power type."""
    ptype = cable_types.get(cfg.get("power_type") or "")
    layout = ctx.get("layout") or {}
    if not ptype or not layout.get("placed"):
        return []
    from jacks import default_jack
    by_jack = {c["to"]: c for c in cables if c["kind"] == "power"}
    run = {"exit_run_mm": float(ptype["diameter_mm"])}
    out = []
    for cid, it in layout["placed"].items():
        jk = default_jack((layout.get("jacks") or {}).get(cid) or [], "power")
        if not jk:
            continue
        pc = by_jack.get(f"{cid}.{jk['id']}")
        facing, opts = end_options(it, jk, ptype, (pc or {}).get("exit_b"), run, layout.get("outward_mm", 0))
        for o in opts:
            o["hits"] = blocked_parts(o, it["id"], obstacles, layout.get("shapes"))
        o = min(opts, key=lambda o: (len(o["hits"]), sum(min(ov) for _, _, ov in o["hits"])))
        if pc is not None:
            pc["exit_b"] = o["side"]
        out.append((cid, jk, pc, facing, o))
    # the used ports of on-board supplies: the same DC plug at a power_out jack (the cable's supply end, `exit_a`)
    from jacks import _jack_by_id, placement
    by_port = {c["from"]: c for c in cables if c["kind"] == "power"}
    for s in ctx.get("supplies") or []:
        iid = s["inst"]["id"]
        it = (layout.get("inst_item") or {}).get(iid)
        if it is None or placement(s["inst"], ctx["project"]) != "on_board":
            continue
        for port in sorted({r["port"] for r in s["rows"] if r["pedals"]}):
            jk = _jack_by_id((layout.get("jacks") or {}).get(s["sup"]["id"]) or [], port)
            if not jk:
                continue
            pc = by_port.get(f"{iid}.{port}")
            facing, opts = end_options(it, jk, ptype, (pc or {}).get("exit_a"), run, layout.get("outward_mm", 0))
            for o in opts:
                o["hits"] = blocked_parts(o, it["id"], obstacles, layout.get("shapes"))
            o = min(opts, key=lambda o: (len(o["hits"]), sum(min(ov) for _, _, ov in o["hits"])))
            if pc is not None:
                pc["exit_a"] = o["side"]
            out.append((iid, jk, pc, facing, o))
    return out


def power_plug_clearance(ctx, cables, cable_types, cfg, obstacles, clear_sink, choices=None):
    """Clearance of every placed pedal's power jack with the project's DC plug (`cables.power_type`): head + barrel
    + the cable's first straight run (one power-cable diameter) on the exit side with the fewest blocked parts
    (`power_plug_choices`, pass its result as `choices` to avoid choosing twice). The power cable then drops under
    the board, so nothing is routed. Without a power type, jacks.check uses the `jacks.power_clearance` box instead."""
    if choices is None:
        choices = power_plug_choices(ctx, cables, cable_types, cfg, obstacles)
    checked = set()
    for cid, jk, pc, facing, o in choices:
        ctx["routing"]["heads"].append({"cable": (pc or {}).get("id"), "rects": o["rects"]})
        checked.add(f"{cid}.{jk['id']}")
        how = f"{cfg['power_type']} {cable_types[cfg['power_type']]['plug']['style'].replace('_', '-')} plug" + \
              (f", cable exits {o['side']}" if o["side"] else "")
        for part, ob, depth in deepest_hits(o, facing):
            ctx["violations"].append({"jack": f"{cid}.{jk['id']}", "obstacle": ob["title"], "depth_mm": depth,
                                      "cable": (pc or {}).get("id"), "cable_type": cfg["power_type"], "side": o["side"], "part": part})
            clear_sink.append(f"clearance: {cid}.{jk['id']} ({jk['label']}, facing {facing}, {how}) is blocked by "
                              f"{ob['title']}: it reaches {depth:.1f} mm into the plug's {part}")
    return checked
