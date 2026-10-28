"""Cable model and on-board cable routing (all mm). Pure: no network, no GUI.

Signal cables (each pedal's output -> the next pedal's input) are routed on the board surface, and may run
under the board through the board's holes (see the last paragraph):
  - the routing area is the pedalboard plus `edge_margin_mm` (default: one cable diameter) beyond its
    back and sides; nothing may run in front of (below) the lowest row of pedals, unless `cables.route_in_front` extends
    the area to the board's front edge + the margin (`front_limit`);
  - pedal bodies and on-board supplies are obstacles (supplies under the board are not, on top);
  - the area is a grid of `grid_mm` cells (default 2 mm); pedals are grown by the cable radius minus half a
    cell, so any gap at least one cable diameter wide is a corridor; at most `max_stack` cables (default 2,
    stacked on top of each other) may share a cell;
  - plugs are modelled (catalog/cables.json, `cables.type` + per-cable `overrides.<id>.type`): a right-angle
    plug's cable leaves the head to the left or right of the jack's facing (the router tries both sides per
    end and keeps the feasible combination with the fewest blocked plugs, then the shortest route; a project
    can fix `exit_a` / `exit_b`), a straight plug's along the facing; the cable then runs `exit_run_mm`
    straight (default one diameter) before the router takes over. Without a cable type the cable leaves
    the jack straight out by the fixed clearance depth (`jacks.clearance.outward_mm`);
  - a right-angle plug whose bend point (the point a side exit bends at) has a board hole under it (the square of one cable width
    inside the effective holes, clear of the under-board supplies; `down_available`) may instead point straight DOWN
    (`design.DOWN`, option "down": the head alone on the board, the cable's first stretch is under the board; its measure is
    |exit offset - head depth / 2| + `cables.jack_height_mm` (12) + the deck, `hole_transit_mm`; no hole pass is counted). Owner
    decision: down is always chosen where it is available (even if longer), unless an override fixes a side; `exit_a` / `exit_b`
    "down" is honoured, and reported (`down_override_finding`) where no hole allows it. The cable's start / goal is then the under
    state of the bend point's cell (`state_of`); the search (`astar_layers`) and `Under.connected` take under starts and goals;
  - the grid path is the shortest 8-connected one; crowded cells are resolved by rip-up-and-reroute with
    rising congestion costs (negotiated congestion, as in FPGA routers); at most `max_over_plug` (default 2)
    other cables may cross one plug (head or barrel), handled the same way;
  - the grid path is then reduced to its necessary corners (`smooth`: any-angle straight segments that stay as
    far from the pedals as the grid path did and cross no plug it did not cross); the minimum cable length
    follows the smoothed path;
  - the clearance of every signal jack with a modelled plug is checked here (head footprint + barrel +
    straight cable run on the chosen side against the other pedals); other jacks keep the fixed box (jacks.py).
Under the board (`cables.under_board`, default true): a second layer over the board footprint (same cells as the
top grid, `Under`). A cable changes layer only in a HOLE CELL (below) or over an EDGE LINK: the owner draws edge
segments along the board border in the board editor (board.json, type "edge"; `layout["edge_segments"]`); every free
under cell on the border within a segment is joined to the top cell just outside it (`edge_links`), for
`edge_transit_mm` of extra cable (+ `cables.hole_penalty` in the signal search, like a hole pass). Segments at the front
count only with `cables.route_in_front`. A hole cell is: a cell whose centre lies inside an effective hole
(`layout["holes"]`) that is free on the top layer (not a pedal or on-board supply grown by the cable radius, so the
part of a hole a pedal covers is not usable) and free under the board (the under-board supplies' outlines, grown the
same way, are the only obstacles known there). The search runs over (cell, layer) states: under steps cost
`under_cost` (0.9) x the length, a pass through the deck `hole_transit_mm` (extra cable: `cables.hole_transit_mm`,
else the board data's, else 15 mm) + `hole_penalty` (15, search only). Cables start and end on top; the stacking
limit is per (cell, layer) (`max_stack`, `max_stack_under`); plug crossings count on top only. Each stretch is smoothed
on its own (the hole cells stay corners); `min_mm` = both plug measures + the top and under polylines + `hole_transit_mm`
per hole pass + `edge_transit_mm` per edge crossing. Lanes (drawing) only on top. The costs are unverified estimates.
Power cables (DC; `route_power`) get the same cable model (tips, centre polarity) and are routed on the same two
layers by `route_all`, with their own grids (the power cable's width), stacking and plug limits: they stay UNDER the
board (from an under-board supply port) and come up through the usable hole nearest their pedal's power jack, or over
an edge crossing (the owner draws them in the board editor as line segments along the border, type "edge",
`layout["edge_segments"]`: a cable may come round the board edge only along one), then run the short way on top; a mm on top costs `power_routing.top_cost`
(3) times a mm under the board. A hop that starts at a pedal (daisy chain) or at an on-board supply starts on top.
`min_mm` = both plug measures + the polylines + `hole_transit_mm` per hole pass + `edge_transit_mm` per edge crossing;
`estimate_mm` keeps jacks.check's right-angle estimate. Their plugs are modelled for clearance: with
`cables.power_type` (a DC plug type, role power) every power jack is checked with that plug's head on the less blocked
exit side; without it jacks.py uses the smaller `jacks.power_clearance` box (and the cables stay unrouted).
"""
import heapq
import itertools
import math
import re
import time

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
    "under_board": True,         # signal cables may pass under the board through holes
    "hole_penalty": 15.0,        # search-only cost (mm equivalent) of one pass through the deck
    "under_cost": 0.9,           # cost factor per mm of cable under the board (equal routes prefer under)
    "max_stack_under": None,     # cables allowed on top of each other in one cell under the board; None: max_stack
    "route_in_front": False,     # true: the routing area reaches the board's front edge + margin (cables may run in front of the pedals)
    "jack_height_mm": 12.0,      # height of a jack's axis above the deck (unverified estimate): the cable of a plug pointing down runs that far + the deck
}
HOLE_TRANSIT_FALLBACK = 15.0     # mm of extra cable per pass through the deck when neither the project nor the board data say
POWER_ROUTING = {                # project `power_routing` defaults (all optional)
    "top_cost": 3.0,             # cost factor per mm of power cable on top of the board (under the board: 1)
    "max_stack": None,           # power cables allowed on top of each other in one cell, per layer; None: cables.max_stack
    "edge_transit_mm": None,     # extra cable to go round the board edge; None: the board data's, else 2 x hole_transit_mm
    "daisy_style": "serial",     # default style of the supply outputs (`outputs[].style`): serial | forked (DAISY_STYLES)
}
REMOVED_POWER_KEYS = ("edges", "avoid_penalty")   # the old per-side edge modes (replaced by the board's edge segments)
SERIAL, FORKED = "serial", "forked"
DAISY_STYLES = (SERIAL, FORKED)   # a supply output's cabling: one cable through every pedal | one cable per pedal from the port
POWER_UNDER_COST = 1.0           # cost factor per mm of power cable under the board
POWER_TOP_WARN_MM = 150.0        # a power cable running more than this on top of the board is reported
TIPS = ("TS", "TRS", "XLR", "DC 2.1 mm", "DC 2.5 mm")
POLARITIES = ("center_negative", "center_positive")
NEIGHBOURS = [(1, 0), (-1, 0), (0, 1), (0, -1), (1, 1), (1, -1), (-1, 1), (-1, -1)]


STYLES = ("right_angle", "straight")
ROLES = ("patch", "instrument", "power", "reference")   # what a catalog/cables.json type is for


def _is_number(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


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
    if not _is_number(s["jack_height_mm"]) or s["jack_height_mm"] < 0:   # (reported by validate_project_types)
        s["jack_height_mm"] = DEFAULTS["jack_height_mm"]
    s.setdefault("grid_mm", 2.0)
    s.setdefault("exit_run_mm", s["diameter_mm"])
    s.setdefault("edge_margin_mm", s["diameter_mm"])
    s.setdefault("overrides", {})
    if s.get("max_stack_under") is None:
        s["max_stack_under"] = s["max_stack"]
    return s


def power_settings(project, cfg=None):
    """`power_routing` of a project with the defaults filled in: {top_cost, max_stack,
    edge_transit_mm (None: decided with the board data, see route_power), daisy_style}. `cfg` = `settings(project)`: the default
    `max_stack` is `cables.max_stack`."""
    given = project.get("power_routing")
    given = given if isinstance(given, dict) else {}   # (a malformed value is reported by validate_power_routing)
    out = {**POWER_ROUTING, **{k: v for k, v in given.items() if k in POWER_ROUTING and v is not None}}
    if out["max_stack"] is None:
        out["max_stack"] = (cfg or settings(project))["max_stack"]
    return out


def daisy_style(project, output=None):
    """The style of a supply output (`power.supplies[].outputs[]` entry `output`): its own `style`, else the project's
    `power_routing.daisy_style`, else "serial". Always one of `DAISY_STYLES`: an unknown value (or a malformed
    `power_routing`) falls back to the next level; the problem itself is reported once where it is validated
    (`validate_power_routing`; build.validate for the output's own `style`)."""
    own = (output or {}).get("style")
    if own in DAISY_STYLES:
        return own
    given = project.get("power_routing")
    default = given.get("daisy_style") if isinstance(given, dict) else None
    return default if default in DAISY_STYLES else SERIAL


def validate_power_routing(project):
    """Problems in the project's `power_routing`, as strings."""
    given = project.get("power_routing")
    if given is None:
        return []
    if not isinstance(given, dict):
        return ["power_routing must be an object"]
    errs = [f"power_routing.{k} was removed: power cables come round a board edge only along an edge segment; draw them with "
            f"uv run scripts/board_editor.py <project>" if k in REMOVED_POWER_KEYS else
            f"power_routing: unknown setting '{k}' (top_cost, max_stack, edge_transit_mm, daisy_style)"
            for k in given if k not in POWER_ROUTING]
    num = lambda v: isinstance(v, (int, float)) and not isinstance(v, bool)
    for k, good, need in (("top_cost", lambda v: v > 0, "> 0"),
                          ("edge_transit_mm", lambda v: v >= 0, ">= 0"), ("max_stack", lambda v: v >= 1, ">= 1")):
        v = given.get(k)
        if v is not None and not (num(v) and good(v)):
            errs.append(f"power_routing.{k} must be a number {need}")
    if given.get("daisy_style") is not None and given["daisy_style"] not in DAISY_STYLES:
        errs.append(f"power_routing.daisy_style must be one of {', '.join(DAISY_STYLES)}, not {given['daisy_style']!r}")
    return errs


# --- grid ---------------------------------------------------------------------------------------
class Grid:
    """Square cells over the routing area; `free(c)` tells whether a cable may pass through a cell."""

    def __init__(self, x0, y0, x1, y1, cell):
        self.x0, self.y0, self.cell = x0, y0, cell
        self.nx, self.ny = max(1, math.ceil((x1 - x0) / cell)), max(1, math.ceil((y1 - y0) / cell))
        self._blocked = set()  # no cable centre here (pedal grown by the cable radius minus half a cell)
        self._body = set()     # cell centre inside a pedal body: never passable, even when squeezing
        self.version = 0       # bumped by every change of the walls: what the derived caches (here and `Under`) are valid for
        self._comps = {}
        self._open = {}
        self._open3 = None

    def _changed(self):
        """The walls changed (assigned or extended): drop the caches derived from them and bump `version`."""
        self.version += 1
        self._comps = {}
        self._open = {}
        self._open3 = None

    @property
    def blocked(self):
        return self._blocked

    @blocked.setter
    def blocked(self, cells):
        self._blocked = cells
        self._changed()

    @property
    def body(self):
        return self._body

    @body.setter
    def body(self, cells):
        self._body = cells
        self._changed()

    @property
    def stamp(self):
        """What the walls' derived caches are valid for: the version plus the two sets' sizes (an in-place add or discard behind
        the grid's back changes a size; `blocked` / `body` assignments and `block_rect` bump the version)."""
        return (self.version, len(self._blocked), len(self._body))

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
        self.blocked |= cells    # (the setter runs `_changed` after the in-place union)
        self.body |= {c for c in cells if r[0] <= self.centre(c)[0] <= r[2] and r[1] <= self.centre(c)[1] <= r[3]}

    def walls(self, squeeze=False):
        return self.body if squeeze else self.blocked

    def open_cells(self, squeeze=False):
        """The passable cells (inside the grid and not a wall) as a set, cached per mode (the search's one-lookup passability
        test). The caches are dropped whenever `blocked` / `body` are assigned (`_changed`; `block_rect` does it); the identity
        and size check also catches a set that was changed in place behind the grid's back (an add or discard that changes the
        size)."""
        walls = self.walls(squeeze)
        hit = self._open.get(squeeze)
        if hit is None or hit[0] is not walls or hit[1] != len(walls):
            cells = {(i, j) for i in range(self.nx) for j in range(self.ny)}
            cells -= walls
            hit = self._open[squeeze] = (walls, len(walls), cells)
        return hit[2]

    def open_states(self):
        """`open_cells` as under-board states (i, j, 1), cached like it (the under layer's passable set of the search)."""
        walls = self.blocked
        hit = self._open3
        if hit is None or hit[0] is not walls or hit[1] != len(walls):
            hit = self._open3 = (walls, len(walls), {(i, j, 1) for i, j in self.open_cells(False)})
        return hit[2]

    def components(self, squeeze=False):
        """{cell: component id} over passable cells (4-connected: a legal diagonal move implies a 4-connected
        detour, so reachability is the same), computed once per mode."""
        key = (squeeze, self.stamp)
        if key not in self._comps:
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
            self._comps[key] = comp
        return self._comps[key]

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


def front_limit(board_rect, foot_bottoms, cfg):
    """Where the routing area ends at the front: the lowest pedal's outline (nothing in front of it, never beyond the board's
    front edge), or with `cables.route_in_front` the board's front edge + `edge_margin_mm` (like the back and sides)."""
    if cfg.get("route_in_front"):
        return board_rect[3] + cfg["edge_margin_mm"]
    return min(board_rect[3], max(foot_bottoms, default=board_rect[3]))


def build_grid(board_rect, obstacle_rects, front_y, cfg):
    """Routing area = board + margin at the back and sides, cut off at `front_y` (`front_limit`)."""
    m = cfg["edge_margin_mm"]
    x0, y0, x1 = board_rect[0] - m, board_rect[1] - m, board_rect[2] + m
    g = Grid(x0, y0, x1, front_y, cfg["grid_mm"])
    # a gap narrower than one cable diameter may still pass by up to half a cell: grid accuracy
    grow = grow_of(cfg)
    for r in obstacle_rects:
        g.block_rect(r, grow=grow)
    return g


class Under:
    """The under-board layer: `grid` has the same origin and cell size as the top grid (cell (i, j) is the same place on
    both layers); its `blocked` cells are the ones outside the board footprint and the under-board obstacles grown by the
    cable radius. `holes`: the hole cells, where a cable may change layer (centre inside a hole, free on both layers).
    Search states are (i, j) on top and (i, j, 1) under the board."""

    def __init__(self, grid, holes, transit_mm, penalty, cost, max_stack, top_cost=1.0, edges=()):
        self.grid, self.holes = grid, set(holes)
        self.transit_mm, self.penalty, self.cost, self.max_stack = transit_mm, penalty, cost, max_stack
        self.top_cost = top_cost                # factor per mm on top of the board (power cables: `power_routing.top_cost`)
        self.hole_cost = transit_mm + penalty   # what one pass costs the search
        # board edges (edge segments, see `edge_links`): `edges` = [(under cell, top cell, cost)]: an under cell at the board edge joined to
        # the top cell just outside it, for `cost` (the edge transit); `up` / `down` index both ways
        self.edges = list(edges)
        self._landing = None
        self.tight = False   # tighter search heuristic that counts the layer changes (set for the power cables)
        self.up, self.down = {}, {}
        for u, t, e, *_ in self.edges:
            self.up.setdefault(u, []).append((t, e))
            self.down.setdefault(t, []).append((u, e))
        self._comps = {}

    def landing(self):
        """The top cells a cable comes up onto: the hole cells and the top cells of the edge links."""
        if self._landing is None:
            self._landing = list(self.holes | {t for _, t, *_ in self.edges})
        return self._landing

    def pass_cost(self):
        """The cheapest layer change the search can pay (a hole pass or an edge link); inf without any."""
        return min([self.hole_cost] * bool(self.holes) + [e for _, _, e, *_ in self.edges], default=math.inf)

    def pass_floor(self, slack):
        """A lower bound of the cost of one layer change for the search heuristic: the hole pass, or an edge link's cost minus
        `slack` (what the sideways cell of the link is worth at the cheapest layer factor); never below 0, inf without any."""
        return max(0.0, min([self.hole_cost] * bool(self.holes) + [e - slack for _, _, e, *_ in self.edges], default=math.inf))

    def edge_cost(self, a, b):
        """What the search pays for the edge crossing between consecutive states a, b (one of them under the board)."""
        if len(a) == 3:
            return min((e for t, e in self.up.get((a[0], a[1]), ()) if t == (b[0], b[1])), default=0.0)
        return min((e for u, e in self.down.get((a[0], a[1]), ()) if u == (b[0], b[1])), default=0.0)

    def limit(self, state, max_top):
        return self.max_stack if len(state) == 3 else max_top

    def components(self, top, squeeze=False):
        """{state: component id} over the passable states of both layers (4-connected; layers joined at hole cells and over
        the edge links); cached per (top grid, squeeze) while neither grid's walls change (`Grid.stamp`)."""
        key = (squeeze, top.stamp, self.grid.stamp)
        if self._comps.get("ref") is not top:
            self._comps = {"ref": top}   # the cache belongs to one top grid (held here, so its id cannot be reused)
        if key not in self._comps:
            live = set(top.open_cells(squeeze))
            live.update((i, j, 1) for i, j in self.grid.open_cells(False))   # the passable states of both layers
            holes, up, down = self.holes, self.up, self.down
            comp, n = {}, 0
            for st in live:
                if st in comp:
                    continue
                comp[st], todo = n, [st]
                while todo:
                    x = todo.pop()
                    i, j = x[0], x[1]
                    if len(x) == 2:
                        nbrs = [(i + 1, j), (i - 1, j), (i, j + 1), (i, j - 1)]
                        if (i, j) in holes:   # the other layer, same cell
                            nbrs.append((i, j, 1))
                        if up or down:   # the other layer over an edge link
                            nbrs += [(u[0], u[1], 1) for u, _ in down.get((i, j), ())]
                    else:
                        nbrs = [(i + 1, j, 1), (i - 1, j, 1), (i, j + 1, 1), (i, j - 1, 1)]
                        if (i, j) in holes:
                            nbrs.append((i, j))
                        if up or down:
                            nbrs += [t for t, _ in up.get((i, j), ())]
                    for c in nbrs:
                        if c in live and c not in comp:
                            comp[c] = n
                            todo.append(c)
                n += 1
            self._comps[key] = comp
        return self._comps[key]

    def connected(self, top, a, b, squeeze=False):
        """Whether a path can exist between states a and b on the two-layer graph (as `Grid.connected`): top cells (i, j) or, for a
        plug that points down into a hole, under states (i, j, 1)."""
        if a == b or (len(a) == len(b) and abs(a[0] - b[0]) + abs(a[1] - b[1]) == 1):
            return True
        comp = self.components(top, squeeze)

        def reach(c):
            near = [c] + [(c[0] + dx, c[1] + dy, *c[2:]) for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1))]
            return {comp[x] for x in near if x in comp}
        return bool(reach(a) & reach(b))


def hole_cells(top, under_grid, hole_rects):
    """Cells where a cable may change layer: centre inside an effective hole, free on top (not a wall: a pedal covers
    part of a hole) and free under the board."""
    out = set()
    for r in hole_rects or []:
        for c in rect_cells(top, r):
            if top.inside(c) and under_grid.inside(c) and c not in top.blocked and c not in under_grid.blocked:
                out.add(c)
    return out


def edge_transit(pcfg, layout, hole_transit):
    """(mm, source) of the extra cable round the board edge: `power_routing.edge_transit_mm`, else the board data's, else twice the
    hole transit."""
    if pcfg.get("edge_transit_mm") is not None:
        return float(pcfg["edge_transit_mm"]), "power_routing.edge_transit_mm"
    if layout.get("edge_transit_mm") is not None:
        return float(layout["edge_transit_mm"]), "the board data"
    return 2 * float(hole_transit), "twice the hole transit"


def usable_edge_segments(layout, cfg):
    """The layout's edge segments a cable can use: all, but without `cables.route_in_front` not the ones at the front (the routing
    area ends at the lowest pedals there)."""
    return [sg for sg in layout.get("edge_segments") or [] if sg[2] != "front" or cfg.get("route_in_front")]


def under_grid(top, board_rect, obstacle_rects, cfg):
    """The under-board grid over the board footprint (`board_rect`; the whole board, also in front of the lowest pedals),
    same origin and cells as `top`: the cells outside the board and the under-board `obstacle_rects` grown like pedals
    are blocked."""
    x1, y1 = board_rect[2], board_rect[3]
    g = Grid(top.x0, top.y0, x1, y1, top.cell)
    g.blocked = {(i, j) for i in range(g.nx) for j in range(g.ny)
                 if not (board_rect[0] <= g.centre((i, j))[0] <= x1 and board_rect[1] <= g.centre((i, j))[1] <= y1)}
    grow = grow_of(cfg)
    for r in obstacle_rects:
        g.block_rect(r, grow=grow)
    return g


def build_under(top, board_rect, obstacle_rects, hole_rects, cfg, transit_mm, edge_segments=(), edge_transit_mm=0.0):
    """The under-board layer (`under_grid`) with the hole cells and the edge links (`edge_links` over `edge_segments`, each costing
    `edge_transit_mm` + the deck penalty to the search, like a hole pass); None for the layer without either (nothing can
    change layer)."""
    g = under_grid(top, board_rect, obstacle_rects, cfg)
    holes = hole_cells(top, g, hole_rects)
    links = edge_links(top, g, board_rect, edge_segments, edge_transit_mm, float(cfg["hole_penalty"]))
    if not holes and not links:
        return g, None
    return g, Under(g, holes, float(transit_mm), float(cfg["hole_penalty"]), float(cfg["under_cost"]), int(cfg["max_stack_under"]),
                    edges=links)


def edge_links(top, ug, board_rect, edge_segments, transit_mm, penalty=0.0):
    """[(under cell, top cell, cost, side)]: every free under cell on the board border whose projection on its side lies within an
    edge segment of that side (`edge_segments` = `layout["edge_segments"]`: ((x0, y0), (x1, y1), side) in canvas mm), joined to
    the top cell just outside the board (the margin of the routing area). None where that cell is not in the top grid or is
    blocked (e.g. in front of the lowest pedals). cost = `transit_mm` + `penalty` (the search-only deck penalty of the signal
    cables), at least one cell (keeps the search heuristic consistent). No segments, no links."""
    x0, y0, x1, y1 = board_rect
    cols = [i for i in range(ug.nx) if x0 <= ug.centre((i, 0))[0] <= x1]   # the cells inside the board footprint
    rows = [j for j in range(ug.ny) if y0 <= ug.centre((0, j))[1] <= y1]
    if not edge_segments or not cols or not rows:
        return []
    sides = {"left": ([(cols[0], j) for j in rows], (-1, 0), 1), "right": ([(cols[-1], j) for j in rows], (1, 0), 1),
             "back": ([(i, rows[0]) for i in cols], (0, -1), 0), "front": ([(i, rows[-1]) for i in cols], (0, 1), 0)}
    cost = max(transit_mm + penalty, top.cell)
    out = []
    for side, (cells, (dx, dy), axis) in sides.items():
        spans = [(min(a[axis], b[axis]), max(a[axis], b[axis])) for a, b, sd in edge_segments if sd == side]   # along the side
        for c in cells:
            n = (c[0] + dx, c[1] + dy)
            if c in ug.blocked or not top.free(n):
                continue
            t = ug.centre(c)[axis]
            if any(lo <= t <= hi for lo, hi in spans):
                out.append((c, n, cost, side))
    return out


# --- search -------------------------------------------------------------------------------------
SQUEEZE_COST = 25.0   # cost factor of a cell narrower than the cable when squeezing (see route_project)
CLOSED_COST = 1e6     # cost of an over-limit cell in route_all's clean-up pass (never taken while a free path exists)


def tight_heuristic(under, goal, cell):
    """The power cables' search heuristic (cost to reach `goal`: a top cell, or an under state for a plug pointing down) or None
    without a layer change to count (then the plain distance bound is used). For an under goal: from under the board just
    the distance (`lo` per mm), from the top at least one pass plus that. It counts the layer changes the cable must pay: from under the board one
    pass up plus the last top leg, at least the goal's distance to the nearest landing cell; from the top either straight
    (top cost) or two passes plus that last leg. Admissible: a pass costs at least `Under.pass_floor` (an edge link also
    moves the cable one cell sideways, which the distance bounds do not see, so its cost is reduced by that cell's
    cost at the cheaper layer factor)."""
    land = under.landing()
    lo = min(under.cost, under.top_cost)
    pas = under.pass_floor(cell * lo)
    if not land or pas == math.inf:
        return None
    tc = under.top_cost
    if len(goal) == 3:
        def h_under(c):
            d = math.hypot(c[0] - goal[0], c[1] - goal[1]) * cell
            return lo * d if len(c) == 3 else pas + lo * d
        return h_under
    dhg = min(math.hypot(q[0] - goal[0], q[1] - goal[1]) for q in land) * cell

    def h(c):
        d = math.hypot(c[0] - goal[0], c[1] - goal[1]) * cell
        if len(c) == 3:
            return pas + lo * d + (tc - lo) * dhg
        return min(tc * d, 2 * pas + tc * dhg + lo * max(0.0, d - dhg))
    return h


def _step_tables(cell, top_mult, under_mult):
    """(dx, dy, diagonal, step length) per neighbour in NEIGHBOURS order, for the top and the under layer; the step length is
    cell x (sqrt 2 or 1) x layer factor, multiplied in the same order as the search always did."""
    root2 = math.sqrt(2)
    return tuple([(dx, dy, bool(dx and dy), cell * (root2 if dx and dy else 1.0) * mult) for dx, dy in NEIGHBOURS]
                 for mult in (top_mult, under_mult))


def _search_cells(grid, walls_squeeze, extra):
    """(cells, add): the passable cell set of one search is `Grid.open_cells` (the cached set itself, never copied or changed)
    plus `add`, the `extra` cells (plug ends: always enterable) that lie inside the grid but are not in it (usually empty);
    a search tests `c in cells or c in add`."""
    cells = grid.open_cells(walls_squeeze)
    return cells, frozenset(c for c in extra if grid.inside(c) and c not in cells)


def astar_layers(grid, start, goal, cell_cost, squeeze, under, costs=None):
    """`astar` over (cell, layer) states (`Under`): within a layer as there; under steps cost `under.cost` x their length
    (and the cell cost of the under state), top steps `under.top_cost` x, the other layer is entered only at a hole cell
    for `under.hole_cost` (or over a board edge link, `under.edges`, for its cost). The start and the goal are
    top cells or, for a cable that starts / ends under the board (an under-board supply port, a plug pointing down into a hole),
    under states (i, j, 1) (always enterable).
    A state is (i, j) on top and (i, j, 1) under the board. `costs`: an optional dict that receives {state: cell cost} of every
    state the search asked the cell cost of. `cell_cost` None: the plain cost 1.0 everywhere (a squeezed cell SQUEEZE_COST), without
    asking; `costs` then receives the states the search reached (the ones it would have asked about, and the start)."""
    ug = under.grid
    uc, tc, hc, cell = under.cost, under.top_cost, under.hole_cost, grid.cell
    top_open, top_add = _search_cells(grid, squeeze, [c for c in (start, goal) if len(c) == 2])
    under_open = ug.open_states()   # (i, j, 1)
    under_add = frozenset(c for c in (start, goal) if len(c) == 3 and c not in under_open)   # the plug ends are always enterable
    blocked, holes, edges = grid.blocked, under.holes, under.edges
    t_orth, t_diag = cell * 1.0 * tc, cell * math.sqrt(2) * tc   # step lengths, multiplied in the order the search always did
    u_orth, u_diag = cell * 1.0 * uc, cell * math.sqrt(2) * uc
    hs = cell * min(1.0, uc, tc)
    h = tight_heuristic(under, goal, cell) if under.tight else None
    gx, gy, hypot, inf = goal[0], goal[1], math.hypot, math.inf
    heappush, heappop = heapq.heappush, heapq.heappop
    unit = cell_cost is None
    if costs is None or unit:
        seen, costs = costs, {}   # the cell cost of a state does not change within one search: ask `cell_cost` once per state
    else:
        seen = None
    costs_get = costs.get
    start_h = h(start) if h else hypot(start[0] - gx, start[1] - gy) * hs
    openq, best, came = [(start_h, 0.0, start)], {start: 0.0}, {}
    best_get = best.get
    while openq:
        _, g, c = heappop(openq)
        if c == goal:
            path = [c]
            while c in came:
                c = came[c]
                path.append(c)
            if unit and seen is not None:
                seen.update(best)
            return path[::-1]
        if g > best_get(c, inf):
            continue
        i, j = c[0], c[1]
        if len(c) == 3:
            ok, add, orth, diag = under_open, under_add, u_orth, u_diag
            e, w, d, u = (i + 1, j, 1), (i - 1, j, 1), (i, j + 1, 1), (i, j - 1, 1)   # east, west, down, up (NEIGHBOURS order)
            low = True
        else:
            ok, add, orth, diag = top_open, top_add, t_orth, t_diag
            e, w, d, u = (i + 1, j), (i - 1, j), (i, j + 1), (i, j - 1)
            low = False
        e_ok, w_ok, d_ok, u_ok = e in ok or e in add, w in ok or w in add, d in ok or d in add, u in ok or u in add
        moves = []   # (next state, step length) in NEIGHBOURS order; a diagonal needs both orthogonal cells beside it
        if e_ok:
            moves.append((e, orth))
        if w_ok:
            moves.append((w, orth))
        if d_ok:
            moves.append((d, orth))
        if u_ok:
            moves.append((u, orth))
        if e_ok:
            if d_ok:
                n = (i + 1, j + 1, 1) if low else (i + 1, j + 1)
                if n in ok or n in add:
                    moves.append((n, diag))
            if u_ok:
                n = (i + 1, j - 1, 1) if low else (i + 1, j - 1)
                if n in ok or n in add:
                    moves.append((n, diag))
        if w_ok:
            if d_ok:
                n = (i - 1, j + 1, 1) if low else (i - 1, j + 1)
                if n in ok or n in add:
                    moves.append((n, diag))
            if u_ok:
                n = (i - 1, j - 1, 1) if low else (i - 1, j - 1)
                if n in ok or n in add:
                    moves.append((n, diag))
        for n, step in moves:
            if unit:
                ng = g + step * (SQUEEZE_COST if squeeze and n in blocked else 1.0)
            else:
                cc = costs_get(n)
                if cc is None:
                    cc = costs[n] = cell_cost(n) * SQUEEZE_COST if (squeeze and n in blocked) else cell_cost(n)
                ng = g + step * cc
            if ng < best_get(n, inf):
                best[n], came[n] = ng, c
                heappush(openq, (ng + (h(n) if h else hypot(n[0] - gx, n[1] - gy) * hs), ng, n))
        if (i, j) in holes:
            n = (i, j) if low else (i, j, 1)
            ng = g + hc
            if ng < best_get(n, inf):
                best[n], came[n] = ng, c
                heappush(openq, (ng + (h(n) if h else hypot(i - gx, j - gy) * hs), ng, n))
        if edges:
            if low:
                emoves = [(t, e) for t, e in under.up.get((i, j), ()) if t in top_open or t in top_add]
            else:
                emoves = [((u[0], u[1], 1), e) for u, e in under.down.get((i, j), ()) if (u[0], u[1], 1) in under_open or (u[0], u[1], 1) in under_add]
            for n, e in emoves:
                ng = g + e
                if ng < best_get(n, inf):
                    best[n], came[n] = ng, c
                    heappush(openq, (ng + (h(n) if h else hypot(n[0] - gx, n[1] - gy) * hs), ng, n))
    if unit and seen is not None:
        seen.update(best)
    return None


def astar(grid, start, goal, cell_cost, squeeze=False, under=None, costs=None):
    """Cheapest 8-connected path from start to goal; diagonals may not cut obstacle corners.
    start/goal are always enterable (they are the plug ends, possibly squeezed against a pedal).
    squeeze=True: cells narrower than the cable (grown margin, not the pedal body) are passable at SQUEEZE_COST.
    under: an `Under` layer; the path is then a list of states ((i, j) on top, (i, j, 1) under the board).
    costs: an optional dict that receives {state: cell cost} of every state whose cell cost the search asked for."""
    if under is not None:
        return astar_layers(grid, start, goal, cell_cost, squeeze, under, costs)
    ok, add = _search_cells(grid, squeeze, (start, goal))
    blocked, cell = grid.blocked, grid.cell
    steps = _step_tables(cell, 1.0, 1.0)[0]
    gx, gy, hypot, inf = goal[0], goal[1], math.hypot, math.inf
    heappush, heappop = heapq.heappush, heapq.heappop
    if costs is None:
        costs = {}
    costs_get = costs.get
    openq, best, came = [(hypot(start[0] - gx, start[1] - gy) * cell, 0.0, start)], {start: 0.0}, {}
    best_get = best.get
    while openq:
        _, g, c = heappop(openq)
        if c == goal:
            path = [c]
            while c in came:
                c = came[c]
                path.append(c)
            return path[::-1]
        if g > best_get(c, inf):
            continue
        i, j = c
        for dx, dy, diag, step in steps:
            x, y = i + dx, j + dy
            if ((x, y) not in ok and (x, y) not in add) or (diag and (((x, j) not in ok and (x, j) not in add)
                                                                       or ((i, y) not in ok and (i, y) not in add))):
                continue
            n = (x, y)
            cc = costs_get(n)
            if cc is None:
                cc = costs[n] = cell_cost(n) * SQUEEZE_COST if (squeeze and n in blocked) else cell_cost(n)
            ng = g + step * cc
            if ng < best_get(n, inf):
                best[n], came[n] = ng, c
                heappush(openq, (ng + hypot(x - gx, y - gy) * cell, ng, n))
    return None


def plain_search(memo, grid, start, goal, squeeze, under):
    """`astar` with the plain cell cost 1.0, remembered in `memo` for `route_all` (see there)."""
    states = {}
    path = astar(grid, start, goal, None if under is not None else (lambda _: 1.0), squeeze=squeeze, under=under, costs=states)
    memo[(start, goal, squeeze)] = (path, states)
    return path


def _search(memo, grid, start, goal, cell_cost, squeeze, under, dead=None, history=None):
    """`astar`, or the remembered plain search (`plain_search`) when `cell_cost` is 1.0 on every state that search asked for.
    `dead` (a set, with `history`: the negotiation's history costs, which only grow): a remembered search that missed on a state
    with a history cost can never hit again (that cost is above 1.0 from then on), so its key goes into `dead` and later
    rounds skip the check."""
    key = (start, goal, squeeze)
    hit = memo.get(key) if memo and not (dead and key in dead) else None
    if hit is not None:
        if all(c == start or cell_cost(c) == 1.0 for c in hit[1]):
            return list(hit[0]) if hit[0] is not None else None
        if dead is not None and any(c != start and history.get(c) for c in hit[1]):
            dead.add(key)
    return astar(grid, start, goal, cell_cost, squeeze=squeeze, under=under)


def route_all(grid, nets, max_stack, iterations=40, plugs=None, max_over_plug=2, under=None, quick=False, memo=None,
              shared=None):
    """nets: [(name, start_cell, goal_cell[, squeeze])]. Returns ({name: path or None}, {cell: [names]}, overflow cells,
    plug_over). With an `Under` layer the paths, usage and overflow are over states ((i, j) on top, (i, j, 1) under the
    board) and the stacking limit is `under.max_stack` under the board; plug crossings count on top only.

    Every round, each net is ripped up and re-routed against the others' current paths; a cell already holding
    `max_stack` cables costs more (present factor, growing each round), and cells that stayed over the limit
    get a permanent history cost, so cables spread out until the limit holds (or the rounds run out).

    plugs: {key: (owner cable name, a set of them (all the cables of a forked port own its plug) or None, cells)}. A net entering a cell of a plug it does not own, where that
    plug already carries `max_over_plug` OTHER cables (owner and this net excluded), pays the over-limit penalty
    like an over-stacked cell; plugs still over the limit after a round get a history cost (for the cables that
    do not own them). plug_over = {key: [names]}: the plugs that stayed over the limit, with their crossing cables.

    quick: skip the clean-up passes when the first round already left every limit satisfied (no history costs exist
    then, so the clean-up would repeat the same searches; used for the power cables, where time matters).

    memo: {(start, goal, squeeze): (path, states)} of searches already made with the plain cell cost 1.0 on this grid and layer
    (`plain_search`; `states` = the states whose cost that search asked for). A search here that would see cost 1.0 on every
    one of those states makes exactly the same moves, so it takes the remembered path instead of searching again.

    shared: cells (states) where cables meet by design and the stacking limit does not apply: the port of a forked power
    output, where every cable of the output starts (a splitter)."""
    plugs = {k: (o if isinstance(o, (set, frozenset)) else frozenset(() if o is None else (o,)), cells)
             for k, (o, cells) in (plugs or {}).items()}   # owners: a set of cable names
    plug_at = {}   # cell -> [plug keys]
    for key, (_, cells) in plugs.items():
        for c in cells:
            plug_at.setdefault(c, []).append(key)
    history, plug_history, paths, present = {}, {}, {}, 0.5
    dead = set()   # memo keys that can no longer hit in the rounds (see `_search`)
    first_clean = False
    limit = (lambda c: under.limit(c, max_stack)) if under is not None else (lambda c: max_stack)
    lim_top, lim_under = limit((0, 0)), limit((0, 0, 1))   # `limit` per layer, for the cost's hot path (one source for both uses)
    if shared:   # the shared cells are unlimited, every other cell keeps its layer's limit
        base_limit = limit
        limit = lambda c: math.inf if c in shared else base_limit(c)
    cross = {key: set() for key in plugs}   # plug key -> cables other than its owner whose path enters it

    def crossed(name, path):
        """plugs a path enters, not counting its own plugs nor its two end cells (a cable may start next to a plug)"""
        return {k for c in (path or [])[1:-1] for k in plug_at.get(c, ()) if name not in plugs[k][0]}

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
                over = usage.get(c, 0) + 1 - (lim_under if len(c) == 3 else lim_top)
                if shared and c in shared:
                    over = 0
                hist = history.get(c, 0.0)
                pk = plug_at.get(c)
                if pk and c != s and c != t:
                    over = max(0, over)
                    for key in pk:
                        if name not in plugs[key][0]:
                            over += len(cross[key]) >= max_over_plug
                            hist += plug_history.get(key, 0.0)
                elif over < 0:
                    over = 0
                if not over and not hist:
                    return 1.0   # (1.0 + 0.0) * (1.0 + present * 0 * 10)
                return (1.0 + hist) * (1.0 + present * over * 10)

            paths[name] = _search(memo, grid, s, t, cost, bool(sq and sq[0]), under, dead, history)
            for c in paths[name] or []:
                usage[c] = usage.get(c, 0) + 1
            for k in crossed(name, paths[name]):
                cross[k].add(name)
        overflow = {c for c, n in usage.items() if n > limit(c)}
        too_many = {k for k, v in cross.items() if len(v) > max_over_plug}
        if not overflow and not too_many:
            first_clean = _ == 0
            break
        for c in overflow:
            history[c] = history.get(c, 0.0) + 0.5
        for k in too_many:
            plug_history[k] = plug_history.get(k, 0.0) + 0.5
        present *= 1.6
    else:
        overflow = too_many = True   # the rounds ran out: no clean-up
    if not overflow and not too_many and not (quick and first_clean):
        # clean-up: the history costs of early rounds can leave a cable on a detour (e.g. under the board) it no
        # longer needs; re-route each cable once against the others' final paths, plain costs, over-limit cells
        # closed. The current path is still allowed, so a cable only gets cheaper and every limit still holds.
        for name, s, t, *sq in nets:
            for c in paths.get(name) or []:
                usage[c] -= 1
            for k in crossed(name, paths.get(name)):
                cross[k].discard(name)

            def plain(c):
                full = usage.get(c, 0) + 1 > limit(c) or (c != s and c != t and any(
                    name not in plugs[k][0] and len(cross[k]) >= max_over_plug for k in plug_at.get(c, ())))
                return CLOSED_COST if full else 1.0

            new = _search(memo, grid, s, t, plain, bool(sq and sq[0]), under)
            if new is not None and not any(plain(c) == CLOSED_COST for c in new[1:-1]):
                paths[name] = new
            for c in paths[name] or []:
                usage[c] = usage.get(c, 0) + 1
            for k in crossed(name, paths[name]):
                cross[k].add(name)
        if under is not None:
            paths = _back_on_top(grid, nets, paths, under, limit, plugs, plug_at, max_over_plug)
    users = {}
    for name, path in paths.items():
        for c in path or []:
            users.setdefault(c, []).append(name)
    plug_over = {k: sorted(v) for k, v in cross.items() if len(v) > max_over_plug}
    return paths, users, {c for c, u in users.items() if len(u) > limit(c)}, plug_over


def path_cost(grid, path, under):
    """What a state path costs the search with plain cell costs: octile steps, x `under.cost` under the board and
    x `under.top_cost` on top, one `under.hole_cost` per hole pass, the link's cost per board edge crossing."""
    total = 0.0
    for a, b in zip(path, path[1:]):
        if len(a) != len(b):
            total += under.hole_cost if (a[0], a[1]) == (b[0], b[1]) else under.edge_cost(a, b)
        else:
            total += grid.cell * (math.sqrt(2) if a[0] != b[0] and a[1] != b[1] else 1.0) * (under.cost if len(b) == 3 else under.top_cost)
    return total


def _back_on_top(grid, nets, paths, under, limit, plugs, plug_at, max_over_plug):
    """Second clean-up of a converged `route_all` over two layers: negotiation can send cable A under the board so that
    cable B takes A's corridor on top, although A on top and B on its old detour would cost less (one cable at a time
    cannot undo that). For each cable under the board: route it on the top layer only, re-route the cables it then
    crowds (both layers, full cells closed), and keep the change when every limit holds and the plain search cost of
    the cables involved drops. Returns the paths."""
    by_name = {n[0]: n for n in nets}

    def state(ps):
        usage, cross = {}, {k: set() for k in plugs}
        for name, p in ps.items():
            for c in p or []:
                usage[c] = usage.get(c, 0) + 1
            for c in (p or [])[1:-1]:
                for k in plug_at.get(c, ()):
                    if name not in plugs[k][0]:
                        cross[k].add(name)
        return usage, cross

    def closed_cost(name, s, t, usage, cross):
        def cost(c):
            full = usage.get(c, 0) + 1 > limit(c) or (c != s and c != t and any(
                name not in plugs[k][0] and len(cross[k]) >= max_over_plug for k in plug_at.get(c, ())))
            return CLOSED_COST if full else 1.0
        return cost

    for name in [n[0] for n in nets]:
        old = paths.get(name)
        if not old or not any(len(c) == 3 for c in old):
            continue
        _, s, t, *sq = by_name[name]
        if len(s) == 3 or len(t) == 3:   # starts / ends under the board: no top-only route exists
            continue
        trial = {k: v for k, v in paths.items() if k != name}
        usage, cross = state(trial)
        top = astar(grid, s, t, lambda c: 1.0, squeeze=bool(sq and sq[0]))   # on top, ignoring the others
        if top is None:
            continue
        full = {c for c in top if usage.get(c, 0) + 1 > limit(c)}
        over_plugs = {k for c in top[1:-1] for k in plug_at.get(c, ()) if name not in plugs[k][0] and len(cross[k]) >= max_over_plug}
        crowd = sorted({o for o, p in trial.items() if p and set(p) & full} | {o for k in over_plugs for o in cross[k]})
        trial[name] = top
        ok = True
        for o in crowd:
            _, so, to, *sqo = by_name[o]
            rest = {k: v for k, v in trial.items() if k != o}
            u2, c2 = state(rest)
            p = astar(grid, so, to, closed_cost(o, so, to, u2, c2), squeeze=bool(sqo and sqo[0]), under=under)
            if p is None or any(closed_cost(o, so, to, u2, c2)(c) == CLOSED_COST for c in p[1:-1]):
                ok = False
                break
            trial[o] = p
        if not ok:
            continue
        usage, cross = state(trial)
        if any(n > limit(c) for c, n in usage.items()) or any(len(v) > max_over_plug for v in cross.values()):
            continue
        involved = [name] + crowd
        if sum(path_cost(grid, trial[k], under) for k in involved) < sum(path_cost(grid, paths[k], under) for k in involved) - 1e-6:
            paths = trial
    return paths


def path_length(grid, path, transit_mm=0.0, edge_transit_mm=0.0):
    """Length of a grid path (octile steps); over states, a layer change at one cell adds `transit_mm`, a layer change over an
    edge link (two cells) adds `edge_transit_mm`."""
    total = 0.0
    for a, b in zip(path, path[1:]):
        if a[0] == b[0] and a[1] == b[1]:
            total += transit_mm
        elif len(a) != len(b):
            total += edge_transit_mm
        else:
            total += grid.cell * (math.sqrt(2) if a[0] != b[0] and a[1] != b[1] else 1.0)
    return total


def layer_passes(grid, runs, links=()):
    """The layer changes between the consecutive runs of `layer_stretches`: (hole points, edge points, edge sides): a hole pass at
    the shared hole cell's centre, an edge pass at the centre of its under cell, `links` = `edge_links` (for the side)."""
    side_of = {(u, t): side for u, t, _, side in links}
    holes, edges, sides = [], [], []
    for k in range(len(runs) - 1):
        a, b = runs[k][1][-1], runs[k + 1][1][0]
        if (a[0], a[1]) == (b[0], b[1]):
            holes.append(grid.centre(a))
        else:
            u, t = ((a[0], a[1]), (b[0], b[1])) if len(a) == 3 else ((b[0], b[1]), (a[0], a[1]))
            edges.append(grid.centre(u))
            sides.append(side_of.get((u, t), "?"))
    return holes, edges, sides


def layer_stretches(path):
    """A state path split by layer: [("top" | "under", [states])]. The hole cell where the layer changes is the last
    state of one stretch and the first of the next (the two states share the cell)."""
    out = []
    for c in path:
        layer = "under" if len(c) == 3 else "top"
        if not out or out[-1][0] != layer:
            out.append((layer, []))
        out[-1][1].append(c)
    return out


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
    if cfg.get("route_in_front") is not None and not isinstance(cfg["route_in_front"], bool):
        errs.append("cables.route_in_front must be true or false")
    if cfg.get("jack_height_mm") is not None and not (_is_number(cfg["jack_height_mm"]) and cfg["jack_height_mm"] >= 0):
        errs.append("cables.jack_height_mm must be a number >= 0 (mm)")

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


def down_available(holes, under_rects, point, diameter_mm):
    """Whether a plug may point down at `point` (its bend point, canvas mm): the square of side `diameter_mm` centred on it lies
    inside the effective board holes (`holes`, canvas rects: their union counts, a hair outside does not) and does not overlap
    an under-board obstacle (`under_rects`, grown by the cable radius; touching is fine). The top layer plays no part: the
    plug sits right next to its own pedal."""
    h = diameter_mm / 2
    sq = (point[0] - h, point[1] - h, point[0] + h, point[1] + h)
    left = [sq]
    for r in holes or []:
        left = [piece for q in left for piece in design._rect_minus(q, r)]
        if not left:
            break
    if any(q[2] - q[0] > 1e-6 and q[3] - q[1] > 1e-6 for q in left):
        return False
    return not any(design.overlap(sq, (r[0] - h, r[1] - h, r[2] + h, r[3] + h), 1e-6) for r in under_rects or [])


def end_options(item, jack, ctype, exit_fixed, cfg, outward, down=None):
    """Every way a plug can sit in one jack: [{side, rects, lead, exit, lead_mm}] (one per exit side for a
    right-angle plug, unless the project fixes it; one for a straight plug or with no cable type). `down`: None, or a
    callable `(bend point, cable diameter) -> bool` (`down_available`): a right-angle plug may then also point DOWN
    into a hole (side "down", `design.plug_geometry`; its measure includes `cfg["jack_height_mm"]` and the deck,
    `cfg["hole_transit_mm"]`). `exit_fixed` "down" offers only that option where it is available, else the usual
    ones (the caller reports the override: `exit_fixed == "down"` and no option with side "down"); a fixed side excludes down."""
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
    if down is not None and plug["style"] != "straight" and exit_fixed not in design.SIDES:
        drop = float(cfg.get("jack_height_mm", DEFAULTS["jack_height_mm"])) + float(cfg.get("hole_transit_mm") or 0.0)
        g = design.plug_geometry(pt, facing, plug, ctype["diameter_mm"], cfg["exit_run_mm"], design.DOWN, drop)
        if down(g["exit"], float(ctype["diameter_mm"])):
            opts = [{"side": design.DOWN, **g}] if exit_fixed == design.DOWN else opts + [{"side": design.DOWN, **g}]
    return facing, opts


def exit_how(o):
    """How a plug option leaves its jack, for messages: ', cable exits left', ', plug points down into a hole' or ''."""
    return ", plug points down into a hole" if o.get("down") else (f", cable exits {o['side']}" if o["side"] else "")


def down_override_finding(cable_id, key, jack_key, ctype):
    """The message for an override `exit_a` / `exit_b` of "down" that no board hole allows (the plug is then chosen automatically)."""
    why = ("straight plugs never point down" if ctype is not None and ctype["plug"]["style"] == "straight" else
           "there is no cable type" if ctype is None else
           "the cable's width does not fit inside the board holes under its bend point, an under-board supply is in the way, or "
           "the cables stay on top (cables.under_board: false)")
    return f"routing: {cable_id} {key} is down, but the plug at {jack_key} cannot point down: {why}; its exit is chosen automatically"


def state_of(grid, o):
    """The search state a plug option's cable starts / ends at: the top cell of its exit, or for a plug pointing down the
    under state of the cell under its bend point."""
    c = grid.cell_of(*o["exit"])
    return (c[0], c[1], 1) if o.get("down") else c


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


def collision_count(opt, own_key, taken):
    """How many (part of this plug option, other footprint) pairs overlap (`design.overlap`, TOL like pedals):
    `taken` = {"<id>.<jack id>": [(part, rect)]}, the fixed boxes and the plugs already chosen; the option's own key is skipped."""
    n = 0
    for _, r in opt["rects"]:
        for key, parts in taken.items():
            if key != own_key and any(design.overlap(r, r2) for _, r2 in parts):
                n += 1
    return n


def power_plug_keys(ctx, cable_types, cfg):
    """The jack keys ("<id>.<jack id>") `power_plug_choices` will model with the DC plug: the power jack of every placed
    pedal and every used port of an on-board supply (empty without `cables.power_type`)."""
    layout = ctx.get("layout") or {}
    if not cable_types.get(cfg.get("power_type") or "") or not layout.get("placed"):
        return set()
    from jacks import default_jack, _jack_by_id, placement
    keys = set()
    for cid in layout["placed"]:
        jk = default_jack((layout.get("jacks") or {}).get(cid) or [], "power")
        if jk:
            keys.add(f"{cid}.{jk['id']}")
    for s in ctx.get("supplies") or []:
        iid = s["inst"]["id"]
        if (layout.get("inst_item") or {}).get(iid) is None or placement(s["inst"], ctx["project"]) != "on_board":
            continue
        for port in sorted({r["port"] for r in s["rows"] if r["pedals"]}):
            if _jack_by_id((layout.get("jacks") or {}).get(s["sup"]["id"]) or [], port):
                keys.add(f"{iid}.{port}")
    return keys


def fixed_footprints(ctx, modelled):
    """The fixed boxes (`ctx["fixed_zones"]`, set by jacks.check) of the used jacks that get no plug model: ({key: [("box", rect)]},
    {key: kind}). `modelled` = the keys that do. kind says what the jack is ("first input, fixed box", "last output, fixed
    box", "extra jack, fixed box", "power box" or "audio box")."""
    zones = ctx.get("fixed_zones") or {}
    layout = ctx.get("layout") or {}
    jd, chain = layout.get("jacks") or {}, ctx.get("chain") or []
    from jacks import default_jack
    first = last = None
    if chain:
        ji, jo = default_jack(jd.get(chain[0]) or [], "input"), default_jack(jd.get(chain[-1]) or [], "output")
        first = f"{chain[0]}.{ji['id']}" if ji else None
        last = f"{chain[-1]}.{jo['id']}" if jo else None
    extra = {f"{cid}.{j}" for cid, ids in ((ctx["project"].get("jacks") or {}).get("extra_used") or {}).items() for j in ids}
    parts, kinds = {}, {}
    for key, z in zones.items():
        if key in modelled:
            continue
        parts[key] = [("box", z["rect"])]
        kinds[key] = ("first input, fixed box" if key == first else "last output, fixed box" if key == last else
                      "extra jack, fixed box" if key in extra else "power box" if z["zone"] == "power" else "audio box")
    return parts, kinds


def plug_collision_findings(ctx, footprints, meta, clear_sink):
    """Every pair of footprints of different jacks that overlap (`footprints` {key: [(part, rect)]}; `meta` {key: {kind,
    label, how, cable, cable_type, side}}): one finding per pair, its deepest part pair (depth = min(dx, dy) of the
    overlap, `design.overlap`). Appended to ctx["plug_collisions"] and sent to `clear_sink` (the pair in natural key order)."""
    keys = sorted(footprints, key=natural_key)
    for i, ka in enumerate(keys):
        for kb in keys[i + 1:]:
            best = None
            for pa, ra in footprints[ka]:
                for pb, rb in footprints[kb]:
                    ov = design.overlap(ra, rb)
                    if ov and (best is None or min(ov) > best[0]):
                        best = (min(ov), pa, pb)
            if best is None:
                continue
            ma, mb = meta.get(ka) or {}, meta.get(kb) or {}
            col = {"jack": ka, "part": best[1], "with": kb, "with_part": best[2], "depth_mm": best[0],
                   "cable": ma.get("cable"), "cable_type": ma.get("cable_type"), "side": ma.get("side"),
                   "with_kind": mb.get("kind"), "kind": ma.get("kind"), "label": ma.get("label"), "how": ma.get("how")}
            ctx["plug_collisions"].append(col)
            clear_sink.append(f"clearance: {collision_text(col)}")


def collision_text(col):
    """'a.power (Power, dc_ra right-angle plug, cable exits left) collides with the plug at a.out (last output, fixed box): 4.2 mm
    (its barrel into the box)' for one `ctx["plug_collisions"]` entry."""
    part = lambda p: "cable run" if p == "cable" else p
    return (f"{col['jack']} ({col['label']}, {col['how']}) collides with the plug at {col['with']} ({col['with_kind']}): "
            f"{col['depth_mm']:.1f} mm (its {part(col['part'])} into the {part(col['with_part'])})")


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
    errors.extend(e for e in validate_types(cable_types) + validate_project_types(project, cable_types)
                  if e not in errors)
    cfg = settings(project, cable_types)
    sink = errors if project.get("validation", {}).get("strict_routing") else warnings
    clear_sink = errors if project.get("validation", {}).get("strict_clearance") else warnings
    ctx["routing"] = {"settings": cfg, "grid": None, "overflow": set(), "overflow_under": set(), "front_y": None, "heads": [],
                      "under": None, "hole_cells": set(), "power": {"settings": power_settings(project, cfg)}}
    ctx.setdefault("violations", [])
    ctx["plug_collisions"] = []
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
             "under_mm": 0.0, "holes_used": 0, "min_mm": None, "path": None, "status": "not routed", "_ends": (a, ja, b, jb)}
        cables.append(c)
    # power cables: model and estimate only (they run under the board)
    from jacks import placement
    inst_by_id = {s["inst"]["id"]: s["inst"] for s in ctx.get("supplies") or []}
    taken = {h["cable"] for h in (ctx.get("cables") or {}).get("power", []) if h.get("cable")}
    spare = iter(range(1, 10 ** 6))

    def spare_cable_id():   # a hop without a cable id (hand-made ctx): its own cable, never one of the real ids
        while True:
            cid = f"C{next(spare)}"
            if cid not in taken:
                taken.add(cid)
                return cid
    for n, hop in enumerate((ctx.get("cables") or {}).get("power", []), 1):
        under = hop.get("under_board")   # jacks.check sets it per hop; else the placement of the instance the cable starts at
        if under is None:
            inst = inst_by_id.get(hop["from"].split(".")[0])
            under = placement(inst if inst is not None else {}, project) != "on_board"
        cables.append({"id": f"P{n}", "kind": "power", "from": hop["from"], "to": hop["to"], "type": cfg["power_type"], "exit_b": None,
                       "cable": hop.get("cable") or spare_cable_id(), "style": hop.get("style") or SERIAL, "output": hop.get("output"),
                       "tip_a": cfg["power_tip"], "tip_b": cfg["power_tip"],
                       "polarity": pedal_polarity(hop["to"]), "under_board": under, "min_mm": None,
                       "estimate_mm": hop.get("min_mm"), "path": None,
                       "status": "not routed"})
    for c in cables:
        for k, v in (over.get(c["id"]) or {}).items():
            if v is not None:              # null = keep the default (as cable_type_id does)
                c[k] = v
        bad = [f"{k}={c[k]}" for k in ("tip_a", "tip_b") if c[k] not in TIPS] + \
              ([f"polarity={c['polarity']}"] if c["kind"] == "power" and c["polarity"] not in (None, *POLARITIES) else [])
        if c["type"] is not None and c["type"] not in cable_types and not (c["kind"] == "power" and c["type"] == cfg["power_type"]):
            bad.append(f"type={c['type']} (not in catalog/cables.json)")
        bad += [f"{k}={c[k]}" for k in ("exit_a", "exit_b") if k in c and c[k] not in (None, "auto", *design.EXITS)]
        if bad:
            errors.append(f"cables: {c['id']} has unknown {', '.join(bad)} (tips: {', '.join(TIPS)}; polarity: {', '.join(POLARITIES)}; "
                          f"exits: left/right/down/auto)")
    ctx["cable_list"] = cables
    ctx["power_cable_summary"] = power_cable_summary(cables)
    from jacks import report_fixed_box
    if not layout:
        report_fixed_box(ctx)
        return

    placed, outward, obstacles = layout["placed"], layout["outward_mm"], layout["obstacles"]
    shapes = layout.get("shapes") or {}

    def shapes_of(it):
        return design.item_shapes(shapes, it)
    grid, layers, under_rects = None, None, []   # without a pedalboard item nothing is routed, but every plug is still checked
    if layout.get("board"):
        board = design.footprint(layout["board"])
        feet = [r for it in placed.values() for r in shapes_of(it)]
        front_y = front_limit(board, [f[3] for f in feet], cfg)   # nothing in front of the lowest pedals (unless cables.route_in_front)
        grid = build_grid(board, [r for o in obstacles for r in shapes_of(o)], front_y, cfg)
        ctx["routing"].update(grid=grid, front_y=front_y)
        if cfg["under_board"]:
            place = layout.get("inst_placement") or {}
            under_rects = [r for iid, it in (layout.get("inst_item") or {}).items()
                           if place.get(iid, placement(inst_by_id.get(iid) or {}, project)) != "on_board" for r in shapes_of(it)]
            given = (project.get("cables") or {}).get("hole_transit_mm")
            transit = given if given is not None else (layout.get("hole_transit_mm")
                                                       if layout.get("hole_transit_mm") is not None else HOLE_TRANSIT_FALLBACK)
            cfg["hole_transit_mm"] = float(transit)
            edge_t, edge_src = edge_transit(power_settings(project, cfg), layout, transit)
            ctx["routing"].update(edge_transit_mm=edge_t, edge_transit_source=edge_src)
            segments = usable_edge_segments(layout, cfg)
            ugrid, layers = build_under(grid, board, under_rects, layout.get("holes"), cfg, transit, segments, edge_t)
            ctx["routing"].update(under=ugrid, hole_cells=set(layers.holes) if layers else set(), edge_links=len(layers.edges) if layers else 0)
            for n, seg in enumerate(layout.get("edge_segments") or [], 1):   # an edge segment no cable can use
                if seg not in segments:
                    sink.append(f"routing: board.json: edge segment {n} is at the front, where the cable area ends at the lowest pedals: "
                                f"it cannot be used (set cables.route_in_front to true to route in front of the pedals)")
                elif not edge_links(grid, ugrid, board, [seg], edge_t):
                    sink.append(f"routing: board.json: edge segment {n} ({seg[2]}) has no usable crossing "
                                f"(its border cells are blocked or outside the cable area)")
    run_given = "exit_run_mm" in (project.get("cables") or {})
    # a right-angle plug may point down into a board hole (`end_options`): signal cables need the under layer (`layers`), the power
    # cables have their own
    down_any = None
    if grid is not None and cfg["under_board"] and layout.get("holes"):
        down_any = lambda pt, d: down_available(layout["holes"], under_rects, pt, d)
    down_signal = down_any if layers is not None else None

    memo = {}   # the side choice's plain searches, reused by route_all where the negotiated costs leave them unchanged
    nets, chosen = [], {}   # chosen: cable id -> (end a option or None, end b option or None)
    # plug footprints for the collision check: {"<id>.<jack id>": [(part, rect)]}. Jacks with a plug model (signal ends with a
    # cable type, DC plugs) get theirs when their side is chosen; every other used jack keeps its fixed box from the start.
    modelled = set(power_plug_keys(ctx, cable_types, cfg))
    for c in (x for x in cables if x["kind"] == "signal"):
        if c["type"] in cable_types:
            modelled |= {f"{cid}.{jk['id']}" for cid, jk in ((c["_ends"][0], c["_ends"][1]), (c["_ends"][2], c["_ends"][3]))
                         if jk and cid in placed}
    taken, kinds = fixed_footprints(ctx, modelled)
    meta = {k: {"kind": kd, "label": ctx["fixed_zones"][k]["label"], "how": kd, "cable": None, "cable_type": None, "side": None}
            for k, kd in kinds.items()}

    def take_signal(c, ends, opts):
        """Footprints of the chosen options of signal cable `c` (the later choices avoid them)."""
        ctype = cable_types.get(c["type"]) if c["type"] else None
        for e, o in zip(ends, opts):
            if not (e and o and ctype):
                continue
            key = f"{e['cid']}.{e['jack']['id']}"
            taken[key] = list(o["rects"])
            meta[key] = {"kind": f"{c['type']} plug", "label": e["jack"]["label"], "cable": c["id"], "cable_type": c["type"],
                         "side": o["side"], "how": f"{c['type']} {ctype['plug']['style'].replace('_', '-')} plug" + exit_how(o)}

    def hits_and_collisions(e, o, other=None):
        """Blocked parts + plug collisions of one end option (with the footprints taken so far and, when given, the other end's
        option of the same cable)."""
        key = f"{e['cid']}.{e['jack']['id']}"
        n = len(o["hits"]) + collision_count(o, key, taken)
        if other is not None:
            okey, oo = other
            n += sum(1 for _, r in o["rects"] for _, r2 in oo["rects"] if design.overlap(r, r2)) if okey != key else 0
        return n

    for c in (x for x in cables if x["kind"] == "signal"):
        a, ja, b, jb = c["_ends"]
        ctype = cable_types.get(c["type"]) if c["type"] else None
        ends = []
        for end, cid, jk in (("a", a, ja), ("b", b, jb)):
            if not (jk and cid in placed):
                ends.append(None)
                continue
            run = cfg if run_given or not ctype else {**cfg, "exit_run_mm": float(ctype["diameter_mm"])}   # one own diameter
            facing, opts = end_options(placed[cid], jk, ctype, c.get(f"exit_{end}"), run, outward, down=down_signal)
            if c.get(f"exit_{end}") == design.DOWN and not any(o["side"] == design.DOWN for o in opts):
                sink.append(down_override_finding(c["id"], f"exit_{end}", f"{cid}.{jk['id']}", ctype))
            for o in opts:
                o["hits"] = blocked_parts(o, placed[cid]["id"], obstacles, shapes)
                o["cell"] = state_of(grid, o) if grid else None
            ends.append({"cid": cid, "jack": jk, "facing": facing, "opts": opts})
        c["_sides"] = ends
        if grid is None or not all(ends):
            c["status"] = "not routed (no pedalboard in the layout)" if grid is None else "not routed (jack or placement missing)"
            # still choose a side per known end (fewest blocked parts) for the clearance check
            chosen[c["id"]] = tuple(min(e["opts"], key=lambda o, e=e: (not o.get("down"), hits_and_collisions(e, o))) if e else None
                                    for e in ends)
            c["exit_a"], c["exit_b"] = ((o or {}).get("side") for o in chosen[c["id"]])
            take_signal(c, ends, chosen[c["id"]])
            continue
        combos = []
        for oa, ob in itertools.product(ends[0]["opts"], ends[1]["opts"]):
            area = lambda st: (layers.grid if len(st) == 3 else grid).inside(st)   # a plug pointing down ends in the under layer
            inside = area(oa["cell"]) and area(ob["cell"])
            mode = 2   # 0: free path, 1: only by squeezing through gaps narrower than the cable, 2: no path
            conn = (lambda a, b, sq=False: layers.connected(grid, a, b, sq)) if layers else grid.connected   # through the holes too
            if inside:
                mode = 0 if conn(oa["cell"], ob["cell"]) else (1 if conn(oa["cell"], ob["cell"], True) else 2)
            blocked = hits_and_collisions(ends[0], oa, (f"{ends[1]['cid']}.{ends[1]['jack']['id']}", ob)) + \
                hits_and_collisions(ends[1], ob)
            # feasible first, then the plugs pointing down (always down where available, even if longer), then blocked + collisions
            combos.append(((not inside, mode, sum(1 for o in (oa, ob) if not o.get("down")), blocked), oa, ob))
        top = min(k for k, _, _ in combos)
        best = None
        for key, oa, ob in (x for x in combos if x[0] == top):   # A* only for the best-ranked combinations
            path = plain_search(memo, grid, oa["cell"], ob["cell"], key[1] == 1, layers) if key[1] < 2 else None
            length = (oa["measure_mm"] + ob["measure_mm"] + path_length(grid, path, cfg.get("hole_transit_mm", 0.0),
                                                                        ctx["routing"].get("edge_transit_mm", 0.0))) if path else \
                math.hypot(oa["exit"][0] - ob["exit"][0], oa["exit"][1] - ob["exit"][1])
            if best is None or length < best[0][4]:
                best = ((*key, length), oa, ob)
        (outside, mode, _, _, _), oa, ob = best
        chosen[c["id"]] = (oa, ob)
        c["exit_a"], c["exit_b"] = oa["side"], ob["side"]
        take_signal(c, ends, (oa, ob))
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
    power_choices = power_plug_choices(ctx, cables, cable_types, cfg, obstacles, taken, down=down_any)   # avoids the signal plugs and fixed boxes
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
                                                   int(cfg["max_over_plug"]), under=layers, memo=memo) if grid else ({}, {}, set(), {}))
    ctx["routing"]["overflow"] = {c for c in overflow if len(c) == 2}
    ctx["routing"]["overflow_under"] = {c for c in overflow if len(c) == 3}
    ctx["routing"]["plug_over"] = plug_over
    pedal_rects = [r for o in obstacles for r in shapes_of(o)]
    radius, transit = cfg["diameter_mm"] / 2, cfg.get("hole_transit_mm", 0.0)
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
        # one smoothed polyline per layer stretch; the hole cells where the cable changes layer are fixed corners
        g = path_geometry(grid, path, oa, ob, None, pedal_rects, under_rects, radius, plug_rects, own)
        runs, stretches, top_mm, under_mm, lead_a, lead_b = g["runs"], g["stretches"], g["top_mm"], g["under_mm"], g["lead_a"], g["lead_b"]
        hole_pts, edge_pts, sides = layer_passes(grid, runs, layers.edges if layers else ())
        edge_t = ctx["routing"].get("edge_transit_mm", 0.0)
        c.update(min_mm=oa["measure_mm"] + ob["measure_mm"] + top_mm + under_mm + len(hole_pts) * transit + len(edge_pts) * edge_t,
                 status="routed", under_board=any(len(q) == 3 for q in path), under_mm=under_mm, holes_used=len(hole_pts), edges_used=len(edge_pts),
                 edge_sides=sides, hole_points=hole_pts, edge_points=edge_pts, path=g["path"])
        c["_stretches"], c["_own"] = stretches, own
        c["_leads"] = (lead_a, lead_b)   # fixed geometry round the routed corners
        if c.get("_squeeze") and squeezed:
            c["status"] = "routed, squeezed (gap narrower than the cable)"
            sink.append(f"routing: {c['id']} ({c['from']} -> {c['to']}) only fits by squeezing about {squeezed:.0f} mm of cable "
                        f"through gaps narrower than the {cfg['diameter_mm']:g} mm cable (move the pedals apart)")
        stacking_findings(c, path, overflow, users, cfg["max_stack"], cfg["max_stack_under"], "cables", sink)
    plug_limit_findings(plug_over, {c["id"]: c for c in cables}, "the plug", cfg["max_over_plug"], sink)

    # lanes: cables along the same corridor are drawn side by side (drawing only: path and min_mm stay on the centrelines);
    # only top stretches take part, each as its own entry when a cable has several
    routed, entry = {}, {}   # entry id -> (cable id, stretch index)
    for c in cables:
        if "_stretches" not in c:
            continue
        tops = [k for k, st in enumerate(c["_stretches"]) if st["layer"] == "top"]
        for k in tops:
            eid = c["id"] if len(c["_stretches"]) == 1 else f"{c['id']}#{k}"
            routed[eid], entry[eid] = (c["_stretches"][k]["points"], c["_own"]), (c["id"], k)
    laned = lanes(routed, pedal_rects, plug_rects, (grid.x0, grid.y0, grid.x0 + grid.nx * grid.cell, front_y),
                  cfg["diameter_mm"]) if routed else {}
    drawn = {}   # cable id -> {stretch index: lane result}
    for eid, res in laned.items():
        drawn.setdefault(entry[eid][0], {})[entry[eid][1]] = {**res, "eid": eid}
    for c in cables:
        if "_stretches" not in c:   # (a cable with both plugs pointing down runs under the board only: no lanes, but still drawn)
            continue
        lead_a, lead_b = c["_leads"]
        draw, stacked, runs_st = [], set(), []
        for k, st in enumerate(c["_stretches"]):
            res = drawn.get(c["id"], {}).get(k)
            pts = res["corners"] if res else st["points"]
            if k == 0:
                pts = lead_a + pts
            if k == len(c["_stretches"]) - 1:
                pts = pts + lead_b
            draw.append({"layer": st["layer"], "points": pts})
            if res:
                stacked |= {entry[x][0] for x in res["stacked"]} - {c["id"]}
                runs_st += res["stacked_runs"]
        c["draw_path"] = [p for st in draw for p in st["points"]]
        c["stretches"] = draw
        c["stacked_with"] = sorted(stacked, key=natural_key)
        c["stacked_runs"] = runs_st

    # clearance of every modelled plug, on the side the router chose
    checked = set()   # "<id>.<jack id>" checked with a plug model; the others keep jacks.check's fixed box
    for c in cables:
        if c["kind"] != "signal" or c["id"] not in chosen or c["type"] not in cable_types:
            continue
        ctype = cable_types[c["type"]]
        for e, o in zip(c["_sides"], chosen[c["id"]]):
            if not e or not o:
                continue
            ctx["routing"]["heads"].append({"cable": c["id"], "rects": o["rects"], **({"down": o["exit"]} if o.get("down") else {})})
            jk, facing = e["jack"], e["facing"]
            checked.add(f"{e['cid']}.{jk['id']}")
            how = f"{c['type']} {ctype['plug']['style'].replace('_', '-')} plug" + exit_how(o)
            for part, ob, depth in deepest_hits(o, facing):
                ctx["violations"].append({"jack": f"{e['cid']}.{jk['id']}", "obstacle": ob["title"], "depth_mm": depth,
                                          "cable": c["id"], "cable_type": c["type"], "side": o["side"], "part": part})
                clear_sink.append(f"clearance: {e['cid']}.{jk['id']} ({jk['label']}, facing {facing}, {how}) is blocked by "
                                  f"{ob['title']}: it reaches {depth:.1f} mm into the plug's {part}")
    if grid:
        route_power(ctx, cables, cable_types, cfg, grid, board, front_y, pedal_rects, under_rects, power_choices, sink)
    else:
        for c in (x for x in cables if x["kind"] == "power"):
            c["status"] = "not routed (no pedalboard in the layout)"
    checked |= power_plug_clearance(ctx, cables, cable_types, cfg, obstacles, clear_sink, power_choices)
    ptype = cable_types.get(cfg.get("power_type") or "")
    for cid, jk, pc, _, o in power_choices:
        meta[f"{cid}.{jk['id']}"] = {"kind": "DC plug", "label": jk["label"], "cable": (pc or {}).get("id"), "cable_type": cfg["power_type"],
                                     "side": o["side"], "how": f"{cfg['power_type']} {ptype['plug']['style'].replace('_', '-')} plug" + exit_how(o)}
    plug_collision_findings(ctx, {k: v for k, v in taken.items() if v}, meta, clear_sink)
    report_fixed_box(ctx, checked)
    for c in cables:
        for k in ("_ends", "_sides", "_squeeze", "_stretches", "_own", "_leads"):
            c.pop(k, None)
    ctx["power_cable_summary"] = power_cable_summary(cables)


def route_power(ctx, cables, cable_types, cfg, grid, board, front_y, pedal_rects, under_rects, choices, sink):
    """Route the power cables (`power_routing`, see the module docstring) and fill their fields: `min_mm`, `status`,
    `under_board` (any stretch under), `under_mm`, `top_mm`, `holes_used`, `edges_used`, `edge_sides`, `hole_points`,
    `edge_points`, `path`, `draw_path`, `stretches`; `estimate_mm` (jacks.check's right-angle estimate) is kept.

    One net per hop of the daisy chains. The power grids have the power cable's width (own grown walls, the cells of the
    signal grid `grid`); `choices` (`power_plug_choices`) gives each power plug's exit. A hop from an under-board supply
    port starts under the board at the port's measure point, any other hop on top at its source plug's exit; every
    hop ends on top at the target plug's exit. Power cables count against each other only (stacking per layer,
    `power_routing.max_stack`; the plug limit counts power plugs only: a signal cable never blocks a power cable and the
    other way round, the board's signal routes do not change)."""
    from jacks import _jack_by_id, placement
    t0 = time.perf_counter()
    project, layout = ctx["project"], ctx["layout"]
    pcables = [c for c in cables if c["kind"] == "power"]
    pw = ctx["routing"]["power"]
    ptype = cable_types.get(cfg.get("power_type") or "")
    if not pcables:
        return
    if not ptype or not cfg["under_board"]:
        for c in pcables:
            c["status"] = "not routed (no power cable type: set cables.power_type)" if not ptype else "not routed (cables.under_board is false)"
        return
    pcfg = pw["settings"]
    pd = float(ptype["diameter_mm"])
    pc_cfg = {**cfg, "diameter_mm": pd}
    transit = cfg["hole_transit_mm"]
    edge_t, source = edge_transit(pcfg, layout, transit)
    pw.update(edge_transit_mm=edge_t, edge_transit_source=source, hole_transit_mm=float(transit), diameter_mm=pd)
    pgrid = build_grid(board, pedal_rects, front_y, pc_cfg)
    ug = under_grid(pgrid, board, under_rects, pc_cfg)
    holes = hole_cells(pgrid, ug, layout.get("holes"))
    links = edge_links(pgrid, ug, board, usable_edge_segments(layout, cfg), edge_t)
    layers = Under(ug, holes, float(transit), float(cfg["hole_penalty"]), POWER_UNDER_COST, int(pcfg["max_stack"]),
                   top_cost=float(pcfg["top_cost"]), edges=links)
    layers.tight = True
    pw.update(hole_cells=set(holes), edge_cells=len(links))
    by_key = {f"{cid}.{jk['id']}": (cid, jk, pc, facing, o) for cid, jk, pc, facing, o in choices}
    inst_by_id = {s["inst"]["id"]: s["inst"] for s in ctx.get("supplies") or []}
    place = layout.get("inst_placement") or {}
    depth = float(ptype["plug"]["head_depth_mm"])
    nets, ends = [], {}
    for c in pcables:
        c["status"] = "not routed"
        iid = c["from"].split(".")[0]
        tgt, src = by_key.get(c["to"]), by_key.get(c["from"])
        if tgt is None:
            c["status"] = "not routed (power jack or placement missing)"
            continue
        ob = tgt[4]
        if iid in inst_by_id and place.get(iid, placement(inst_by_id[iid], project)) != "on_board":   # an under-board supply port
            jk = _jack_by_id((layout.get("jacks") or {}).get(inst_by_id[iid]["supply"]) or [], c["from"].partition(".")[2])
            it = (layout.get("inst_item") or {}).get(iid)
            if not jk or not it:
                c["status"] = "not routed (supply port position unknown)"
                continue
            pt = design.jack_point(it, jk["x"], jk["y"])
            start_pt = design.stub(pt, design.jack_facing(it, jk["facing"]), depth / 2)
            cell = pgrid.cell_of(*start_pt)
            start, oa = (cell[0], cell[1], 1), None
            if not (board[0] <= start_pt[0] <= board[2] and board[1] <= start_pt[1] <= board[3] and ug.inside(cell)):   # the under layer = the board footprint
                c["status"] = "unroutable: the supply port is outside the board footprint"
                sink.append(f"routing: {c['id']} ({c['from']} -> {c['to']}) is unroutable: {c['status'][len('unroutable: '):]}")
                continue
        elif src is not None:
            oa, start, start_pt = src[4], state_of(pgrid, src[4]), src[4]["exit"]   # a plug pointing down starts under the board
        else:
            c["status"] = "not routed (source jack or placement missing)"
            continue
        goal = state_of(pgrid, ob)
        area = lambda st: (ug if len(st) == 3 else pgrid).inside(st)
        if not area(goal) or not area(start):
            c["status"] = "unroutable: a plug end is outside the routing area (in front of the lowest pedals or beyond the margin)"
            sink.append(f"routing: {c['id']} ({c['from']} -> {c['to']}) {c['status'][len('unroutable: '):]}")
            continue
        ends[c["id"]] = (oa, ob, start_pt, c["from"], c["to"])
        nets.append((c["id"], start, goal))
    if not nets:
        return
    grow = grow_of(pc_cfg)
    plug_rects = {k: [r for part, r in o["rects"] if part in ("head", "barrel")] for k, (_, _, _, _, o) in by_key.items()}
    plug_rects = {k: v for k, v in plug_rects.items() if v}
    forked_from = {}   # port key -> the cables of a forked output from it: all of them own the port's plug
    for c in pcables:
        if c["style"] == FORKED:
            forked_from.setdefault(c["from"], set()).add(c["id"])
    plugs = {k: ({(by_key[k][2] or {}).get("id")} - {None} | forked_from.get(k, set()),
                 set().union(*(rect_cells(pgrid, r, grow) for r in rs))) for k, rs in plug_rects.items()}
    args = (int(pcfg["max_stack"]), int(cfg["iterations"]), plugs, int(cfg["max_over_plug"]))
    by_id = {c["id"]: c for c in pcables}
    forks = {}   # start cell -> forked nets starting there (a splitter at the port: they may share that cell)
    for name, start, _ in nets:
        if by_id[name]["style"] == FORKED:
            forks[start] = forks.get(start, 0) + 1
    shared = {cell for cell, n in forks.items() if n > 1}
    paths, users, overflow, plug_over = route_all(pgrid, nets, *args, under=layers, quick=True, shared=shared)
    stuck = {n for n, p in paths.items() if p is None}
    if stuck:   # the cables with no free path may squeeze through gaps narrower than the cable
        paths, users, overflow, plug_over = route_all(pgrid, [(*n, n[0] in stuck) for n in nets], *args, under=layers, quick=True,
                                                      shared=shared)
    radius = pd / 2
    for name, path in paths.items():
        c = by_id[name]
        if path is None:
            c["status"] = "unroutable: no free path between the pedals"
            sink.append(f"routing: {c['id']} ({c['from']} -> {c['to']}) has no free path (power cable)")
            continue
        oa, ob, start_pt, a_key, b_key = ends[name]
        g = path_geometry(pgrid, path, oa, ob, start_pt, pedal_rects, under_rects, radius, plug_rects, {a_key, b_key})
        runs, stretches, top_mm, under_mm, lead_a, lead_b = g["runs"], g["stretches"], g["top_mm"], g["under_mm"], g["lead_a"], g["lead_b"]
        hole_pts, edge_pts, sides = layer_passes(pgrid, runs, links)
        draw = [{"layer": st["layer"], "points": (lead_a if k == 0 else []) + st["points"] + (lead_b if k == len(stretches) - 1 else [])}
                for k, st in enumerate(stretches)]
        c.update(min_mm=(oa["measure_mm"] if oa else 0.0) + ob["measure_mm"] + top_mm + under_mm + len(hole_pts) * transit + len(edge_pts) * edge_t,
                 status="routed", under_board=under_mm > 0, under_mm=under_mm, top_mm=top_mm, holes_used=len(hole_pts),
                 edges_used=len(edge_pts), edge_sides=sides, hole_points=hole_pts, edge_points=edge_pts,
                 path=g["path"], stretches=draw, draw_path=[q for st in draw for q in st["points"]], end_point=ob["exit"])
        if any(q in pgrid.blocked for q in path if len(q) == 2) and name in stuck:
            squeezed = sum(1 for q in path if len(q) == 2 and q in pgrid.blocked) * pgrid.cell
            if squeezed:
                c["status"] = "routed, squeezed (gap narrower than the cable)"
                sink.append(f"routing: {c['id']} ({c['from']} -> {c['to']}) only fits by squeezing about {squeezed:.0f} mm of power cable "
                            f"through gaps narrower than the {pd:g} mm cable (move the pedals apart)")
        if top_mm > POWER_TOP_WARN_MM:
            sink.append(f"routing: {c['id']} ({c['from']} -> {c['to']}) runs {top_mm:.0f} mm on top of the board "
                        f"(power cables should stay under it: no usable hole or edge near the pedal's power jack)")
        stacking_findings(c, path, overflow, users, pcfg["max_stack"], pcfg["max_stack"], "power cables", sink)
    plug_limit_findings(plug_over, by_id, "the power plug", cfg["max_over_plug"], sink)
    pw["time_s"] = time.perf_counter() - t0


def path_geometry(grid, path, oa, ob, start_pt, pedal_rects, under_rects, radius, plug_rects, own):
    """What the signal and the power cables share after the grid search: the state `path` cut into per-layer runs (a
    hole cell or an edge link is a layer change), each run smoothed (`smooth`: top runs against the pedals and the other
    plugs, `own` = this cable's plug keys, under runs against the under-board `under_rects`) with the plug exits as
    fixed ends. `oa` / `ob`: the plug options of the two ends (`oa` None: the cable starts under the board at
    `start_pt`; a plug option that points down (`"down"`) starts / ends the cable under the board at its bend point, `exit`). Returns {"runs", "stretches" [{"layer", "points"}], "top_mm", "under_mm" (the smoothed polylines only), "lead_a",
    "lead_b" (the fixed geometry round the plugs), "path" (lead_a + the corners + lead_b)}."""
    runs = layer_stretches(path)
    stretches = []
    for n, (layer, states) in enumerate(runs):
        pts = [grid.centre(q) for q in states]
        if layer == "top":
            pts = ([oa["exit"]] if n == 0 and oa else []) + pts + ([ob["exit"]] if n == len(runs) - 1 else [])
            stretches.append({"layer": "top", "points": smooth(pts, pedal_rects, radius, plug_rects, own)})
        else:
            first = start_pt if start_pt else (oa["exit"] if oa and oa.get("down") else None)
            pts = ([first] if n == 0 and first else []) + pts + ([ob["exit"]] if n == len(runs) - 1 and ob.get("down") else [])
            stretches.append({"layer": "under", "points": smooth(pts, under_rects, radius, {}, ())})
    mm = lambda layer: sum(polyline_length(st["points"]) for st in stretches if st["layer"] == layer)
    lead_a = list(oa["lead"][:-1]) if oa else []
    lead_b = list(reversed(ob["lead"]))[1:]
    corners = [q for st in stretches for q in st["points"]]
    return {"runs": runs, "stretches": stretches, "top_mm": mm("top"), "under_mm": mm("under"), "lead_a": lead_a, "lead_b": lead_b,
            "path": lead_a + [q for k, q in enumerate(corners) if k == 0 or q != corners[k - 1]] + lead_b}


def stacking_findings(c, path, overflow, users, limit_top, limit_under, noun, sink):
    """Per layer the other cables sharing cells of `path` beyond the stacking limit: the cable's status gets
    ", over the stacking limit" and `sink` one message per layer (`noun`: "cables" | "power cables")."""
    for where, limit_n, tail in (("top", limit_top, ""), ("under", limit_under, " under the board")):
        crowded = sorted({x for q in path if q in overflow and (len(q) == 3) == (where == "under") for x in users[q]} - {c["id"]})
        if crowded:
            if "over the stacking limit" not in c["status"]:
                c["status"] += ", over the stacking limit"
            sink.append(f"routing: {c['id']} shares cells with {', '.join(crowded)} beyond the limit of {limit_n} stacked {noun}{tail}")


def plug_limit_findings(plug_over, by_id, what, limit, sink):
    """One message per plug crossed by more than `limit` other cables; every cable involved gets ", over the plug limit"
    appended to its status (a cable keeps every problem it has). `what`: "the plug" | "the power plug"."""
    for key, names in sorted(plug_over.items()):
        who = ", ".join(names[:-1]) + " and " + names[-1] if len(names) > 1 else names[0]
        sink.append(f"routing: {who} {'cross' if len(names) > 1 else 'crosses'} {what} at {key} (limit {limit} other cables)")
        for n in names:
            by_id[n]["status"] += ", over the plug limit"


def deepest_hits(opt, facing):
    """[(part, obstacle, depth)] per obstacle of one plug option: the part it reaches deepest into."""
    best = {}
    for part, ob, ov in opt["hits"]:
        depth = design.part_depth(part, facing, opt["side"], ov)
        if ob["id"] not in best or depth > best[ob["id"]][2]:
            best[ob["id"]] = (part, ob, depth)
    return list(best.values())


def power_cable_summary(cables):
    """The physical DC cables of a cable list (`ctx["cable_list"]`), one entry per `cable` id (C1, C2... in order):
    {"id", "style", "output", "legs": [P#], "from": port, "to": [pedal power jacks], "plugs": DC plugs on the cable (serial:
    pedals + 1, forked: 2), "min_mm": sum of the legs' min_mm (None when any leg is not routed), "estimate_mm": sum of the
    legs' right-angle estimates (None when any is unknown), "status": "routed" when every leg is, else the first leg's
    status that is not}. A serial cable is one cable through every pedal of its output (its legs are the hops), a forked
    output has one cable per pedal."""
    groups = {}
    for c in cables:
        if c["kind"] == "power":
            groups.setdefault(c["cable"], []).append(c)
    out = []
    for cid, legs in groups.items():
        style = legs[0]["style"]
        bad = [c["status"] for c in legs if not c["status"].startswith("routed")]
        out.append({"id": cid, "style": style, "output": legs[0].get("output"), "legs": [c["id"] for c in legs],
                    "from": legs[0]["from"], "to": [c["to"] for c in legs],
                    "plugs": len(legs) + 1 if style == SERIAL else 2,
                    "min_mm": None if any(c["min_mm"] is None for c in legs) else sum(c["min_mm"] for c in legs),
                    "estimate_mm": None if any(c.get("estimate_mm") is None for c in legs) else sum(c["estimate_mm"] for c in legs),
                    "status": bad[0] if bad else "routed"})
    return out


def power_plug_choices(ctx, cables, cable_types, cfg, obstacles, taken=None, down=None):
    """The DC plug of every placed pedal's power jack (`cables.power_type`) with the exit side that has the fewest
    blocked parts (then the least overlap; a power cable override `exit_b` fixes it): [(pedal id, jack, power cable
    or None, facing, plug option)]. `taken` {"<id>.<jack id>": [(part, rect)]} = the signal plugs and fixed boxes: a part
    overlapping one of them counts like a blocked part, and every chosen plug is added to it for the next ones (None: no
    collision check). A plug pointing down into a hole (`end_options`, `down` = its availability callable) always wins
    over the side exits (owner decision), unless an override fixes a side. Sets the power cable's `exit_b`. Also every used port of an on-board supply
    ("<instance id>" instead of the pedal id; the cable starting at the port, its side is `exit_a`). Empty without a
    power type."""
    ptype = cable_types.get(cfg.get("power_type") or "")
    layout = ctx.get("layout") or {}
    if not ptype or not layout.get("placed"):
        return []
    from jacks import default_jack
    by_jack = {c["to"]: c for c in cables if c["kind"] == "power"}
    run = {"exit_run_mm": float(ptype["diameter_mm"]), "jack_height_mm": cfg.get("jack_height_mm", DEFAULTS["jack_height_mm"]),
           "hole_transit_mm": cfg.get("hole_transit_mm", 0.0)}
    sink = ctx["errors"] if ctx["project"].get("validation", {}).get("strict_routing") else ctx["warnings"]
    out = []
    for cid, it in layout["placed"].items():
        jk = default_jack((layout.get("jacks") or {}).get(cid) or [], "power")
        if not jk:
            continue
        pc = by_jack.get(f"{cid}.{jk['id']}")
        facing, opts = end_options(it, jk, ptype, (pc or {}).get("exit_b"), run, layout.get("outward_mm", 0), down=down)
        key = f"{cid}.{jk['id']}"
        if (pc or {}).get("exit_b") == design.DOWN and not any(o["side"] == design.DOWN for o in opts):
            sink.append(down_override_finding(pc["id"], "exit_b", key, ptype))
        for o in opts:
            o["hits"] = blocked_parts(o, it["id"], obstacles, layout.get("shapes"))
        o = min(opts, key=lambda o: (not o.get("down"), len(o["hits"]) + (collision_count(o, key, taken) if taken is not None else 0),
                                     sum(min(ov) for _, _, ov in o["hits"])))
        if taken is not None:
            taken[key] = list(o["rects"])
        if pc is not None:
            pc["exit_b"] = o["side"]
        out.append((cid, jk, pc, facing, o))
    # the used ports of on-board supplies: the same DC plug at a power_out jack (the cable's supply end, `exit_a`)
    from jacks import _jack_by_id, placement
    by_port = {}   # port -> its cables (a forked output has one per pedal: they share the port, so one plug side)
    for c in cables:
        if c["kind"] == "power":
            by_port.setdefault(c["from"], []).append(c)
    for s in ctx.get("supplies") or []:
        iid = s["inst"]["id"]
        it = (layout.get("inst_item") or {}).get(iid)
        if it is None or placement(s["inst"], ctx["project"]) != "on_board":
            continue
        for port in sorted({r["port"] for r in s["rows"] if r["pedals"]}):
            jk = _jack_by_id((layout.get("jacks") or {}).get(s["sup"]["id"]) or [], port)
            if not jk:
                continue
            pcs = by_port.get(f"{iid}.{port}") or []
            pc = pcs[0] if pcs else None
            fixed = next((c["exit_a"] for c in pcs if c.get("exit_a")), None)
            clash = [c for c in pcs if c.get("exit_a") not in (None, "auto", fixed)]
            if clash:   # the legs of a forked output share the port's plug: one side
                first = next(c for c in pcs if c.get("exit_a"))
                sink.append(f"routing: {first['id']} (exit_a {fixed}) and {clash[0]['id']} (exit_a {clash[0]['exit_a']}) leave the same "
                            f"port {iid}.{port}, which has one plug: {fixed} is used for both")
            facing, opts = end_options(it, jk, ptype, fixed, run, layout.get("outward_mm", 0), down=down)
            key = f"{iid}.{port}"
            if fixed == design.DOWN and not any(o["side"] == design.DOWN for o in opts):
                sink.append(down_override_finding(next(c["id"] for c in pcs if c.get("exit_a") == fixed), "exit_a", key, ptype))
            for o in opts:
                o["hits"] = blocked_parts(o, it["id"], obstacles, layout.get("shapes"))
            o = min(opts, key=lambda o: (not o.get("down"), len(o["hits"]) + (collision_count(o, key, taken) if taken is not None else 0),
                                         sum(min(ov) for _, _, ov in o["hits"])))
            if taken is not None:
                taken[key] = list(o["rects"])
            for c in pcs:
                c["exit_a"] = o["side"]
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
        ctx["routing"]["heads"].append({"cable": (pc or {}).get("id"), "rects": o["rects"], **({"down": o["exit"]} if o.get("down") else {})})
        checked.add(f"{cid}.{jk['id']}")
        how = f"{cfg['power_type']} {cable_types[cfg['power_type']]['plug']['style'].replace('_', '-')} plug" + exit_how(o)
        for part, ob, depth in deepest_hits(o, facing):
            ctx["violations"].append({"jack": f"{cid}.{jk['id']}", "obstacle": ob["title"], "depth_mm": depth,
                                      "cable": (pc or {}).get("id"), "cable_type": cfg["power_type"], "side": o["side"], "part": part})
            clear_sink.append(f"clearance: {cid}.{jk['id']} ({jk['label']}, facing {facing}, {how}) is blocked by "
                              f"{ob['title']}: it reaches {depth:.1f} mm into the plug's {part}")
    return checked
