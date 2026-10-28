"""Pedal positions: candidate model, hard constraints, surrogate score and search (all mm). Pure: no files, no GUI.

A candidate is a centre (cx, cy) and a rotation (0/90/270, never 180 unless the owner's layout has it) per chain
pedal placed in the owner's layout and per supply instance placed ON the board (`placement: "on_board"`: an obstacle
by its outline whose used output ports get the DC plug clearance and start the power cables; chain pedals first in
the state, then the supplies); the board, supplies under the board, other items and the chain order are fixed. Per pedal and allowed rotation, everything that moves with it is precomputed relative to its centre:
footprint half-sizes, plug options (signal: both exit sides of a right-angle plug and, where the board has holes, the option pointing DOWN
(its bend point relative to the centre; whether a candidate position allows it is tested per candidate with routing.down_available);
power: every exit of every DC plug type of `cables.power_types`; extra jacks: the fixed box), measure and exit points, footswitch points.
Moving a pedal translates cached rectangles.

Hard constraints (a candidate that breaks one is never scored): inside the board shrunk by `board_margin_mm`
(never overhang), no overlap beyond design.TOL_MM between pedals (touching allowed; `min_gap_mm` adds a gap), pins
fixed, rotation within the allowed set, at most `max_move_mm` from the owner's position.

Surrogate score (lower is better, "mm-equivalent"), weights in project.json `layout.weights`:
  clearance      per plug and obstacle: 50 / mm real penetration (smaller overlap side of the plug parts: how far
                 to move to clear) + clearance_margin 10 / mm of the extra penetration when the parts are grown by
                 `clearance_margin_mm` (2: plug sizes are estimates) + clearance_hit 100 per plug and obstacle that
                 really overlap (no margin; reported as "blocked" with the build's depth, design.part_depth). Plus the
                 same weights for PLUG COLLISIONS: the footprints (head, barrel, cable run; the fixed box of a jack without a plug
                 model) of two different jacks that overlap (reported in `collisions`, as the build's `plug_collisions`). A plug
                 end takes the option pointing DOWN where its bend point has a hole under it (owner rule: always, even if longer;
                 footprint = the head only); else a side option. Signal ends pick the exit side with the lowest clearance +
                 cable cost, DC plugs a feasible option (exit in the routing area and in no other pedal's outline) with the lowest
                 clearance cost over the exits of every plug type (ties: list order); where plugs collide the ends involved
                 choose again as the build does (`Model._resolve`: signal cables in chain order, then DC plugs, each seeing only
                 the plugs decided before it, ranked by blocked parts + collisions, then length / overlap / type order). One
                 simplification: a serial DC cable shares one pedal-end plug type in the build, here every plug takes its own best.
  routing_area   200 per signal plug exit outside the routing area (in front of the lowest pedals, beyond the margin)
  signal         1 / mm patch cable: per hop measure_a + measure_b + octile distance between the cable exits (the
                 router's 8-connected path length) + detour 0.6 x an estimate of the way around the pedals (grown
                 by the cable radius, so a gap narrower than the cable is closed) the straight line between the
                 exits crosses (layout.detour; 0.6 because the estimate is rough, calibrated on guitar-gig). A plug pointing down
                 has `measure_mm` = offset + jack height + deck and its cable starts UNDER the board at the bend point: down to
                 down = the octile distance (nothing in the way: no detour); down to a top exit = under the board to the crossing
                 (hole / edge point) nearest that exit (power setup's `Crossings`; else the exit itself) + the pass + the way on top
  power          0.1 / mm DC cable along each daisy chain between half-depth measure points for a fixed wiring (the search
                 keeps it; finalists get their own wiring from power.assign): the nearest-hole estimate of the power router
                 (power.hop_estimate: under the board, up through the usable hole nearest the pedal's power jack, a mm on top
                 counts `power_routing.top_cost`, a pass the hole transit; the points a candidate's pedals cover, or an under-board
                 supply covers, are not usable; a DC plug pointing down ends / starts the cable under the board at its bend point:
                 no pass up, + its measure); plain Manhattan without holes or a power cable type
  footswitch     2 x crowding: per pair of switches on different pedals priority x max(0, comfort - d)^2 / comfort
                 (footswitches.crowding; comfort `footswitches.comfort_mm`, default 100; priority per switch type:
                 bypass 1.0, boost 0.8, tap 0.8, function 0.5, a pair weighs the larger of its two): spacing is
                 maximised against the other terms, the closest pairs count most. With an optional
                 `footswitches.min_distance_mm` also footswitch_min 20 / mm below it + footswitch_pair 100 per pair
                 (times the priority). No footswitch data -> 0
  io             1 / mm: first pedal's input to the right board edge + last pedal's output to the nearest of the
                 left, right and back edges
  flow           0.1 / mm a pedal's centre lies to the right of the previous pedal's (signal flows right to left)
  access         1 x rule weight / mm: depth (footswitches' mean, else the centre) from the front edge ("front"),
                 from the back edge ("back"), or into the front half ("avoid_front"); rules per tag, per switch
                 type (a tap switch: front, and it cancels avoid_front; a boost switch: front) and per-pedal
                 overrides (`layout.access`)
  rotation       0 for 0 deg, rotation_used 10 for an angle another pedal on the board has, rotation_new 40 else
  move           0.2 / mm centre displacement from the owner's layout + move_pedal 25 per moved pedal +
                 rotate_change 20 per changed rotation (times the level's move factor): move few pedals, little
  touch          -0.02 / mm of edge two pedals share (touching, gap < 1 mm): a small compactness bonus
"""
import math
import random
import time

import design
import footswitches
import outlines as outlines_mod
import power
import routing
from common import px_to_mm

TOUCH_GAP_MM = 1.0
CROWD_STEP_MM = 8.0   # largest repair step for a crowded footswitch pair
# the power estimate's memos in `Model.score` are dropped whole when they reach these sizes (a default gig search makes ~34k / ~6.6k
# entries and answers 86 % of the nearest-crossing questions from the memo; 5000 entries still hit 85 %): a few MB at most
NEAR_MEMO_MAX = 20000
RECT_BITS_MAX = 10000
SQRT2_1 = math.sqrt(2) - 1

WEIGHTS = {"clearance": 50.0, "clearance_margin": 10.0, "clearance_hit": 100.0, "routing_area": 200.0, "signal": 1.0, "detour": 0.6, "power": 0.1,
           "footswitch": 2.0, "footswitch_min": 20.0, "footswitch_pair": 100.0, "io": 1.0, "flow": 0.1, "access": 1.0,
           "rotation_used": 10.0, "rotation_new": 40.0, "move": 0.2, "move_pedal": 25.0, "rotate_change": 20.0,
           "touch": 0.02}
ACCESS = {
    "tags": {"tuner": {"want": "back", "weight": 0.5},
             "eq": {"want": "front", "weight": 0.3}, "master": {"want": "front", "weight": 0.3},
             "boost": {"want": "front", "weight": 0.3},
             "overdrive": {"want": "front", "weight": 0.1}, "gain": {"want": "front", "weight": 0.1},
             "modulation": {"want": "avoid_front", "weight": 0.1}, "phaser": {"want": "avoid_front", "weight": 0.1},
             "vibe": {"want": "avoid_front", "weight": 0.1}, "flanger": {"want": "avoid_front", "weight": 0.1},
             "chorus": {"want": "avoid_front", "weight": 0.1}, "tremolo": {"want": "avoid_front", "weight": 0.1}},
    "switches": {"tap": {"want": "front", "weight": 0.1}, "boost": {"want": "front", "weight": 0.05}},
    "pedals": {},
}
WANTS = ("front", "back", "avoid_front")
LEVELS = {   # max_change: what the search may do
    "fix":       {"sigma": (8.0, 0.5), "swap": False, "rotate": False, "max_move_mm": 40.0, "move_factor": 1.0,
                  "iterations": 2000, "restarts": 6},
    "rearrange": {"sigma": (60.0, 1.0), "swap": True, "rotate": True, "max_move_mm": None, "move_factor": 0.25,
                  "iterations": 12000, "restarts": 4},
    "free":      {"sigma": (150.0, 1.0), "swap": True, "rotate": True, "max_move_mm": None, "move_factor": 0.0,
                  "iterations": 15000, "restarts": 4, "random_start": True},
}
DEFAULTS = {"pins": [], "rotations": {"default": [0, 90, 270]}, "board_margin_mm": 0.0, "min_gap_mm": 0.0,
            "clearance_margin_mm": 2.0, "max_change": "fix", "max_move_mm": "level",
            "search": {"seed": 1, "iterations": None, "restarts": None, "time_limit_s": 120, "top": 3}}


def settings(project):
    """Layout settings: DEFAULTS + project `layout` (weights, pair factors and access merged key by key)."""
    given = project.get("layout") or {}
    s = {**DEFAULTS, **{k: v for k, v in given.items() if k not in ("weights", "access", "search")}}
    s["weights"] = {**WEIGHTS, **(given.get("weights") or {})}
    acc = given.get("access") or {}
    s["access"] = {k: {**ACCESS[k], **(acc.get(k) or {})} for k in ("tags", "switches", "pedals")}
    s["search"] = {**DEFAULTS["search"], **(given.get("search") or {})}
    s["rotations"] = {**DEFAULTS["rotations"], **(given.get("rotations") or {})}
    return s


def access_rule(pedal, switch_types, acc):
    """The accessibility rule {"want", "weight"} of one pedal (None: no preference): a per-pedal override, else the
    strongest rule of its tags and its switch types (tap tempo, boost); a tap-tempo switch cancels "avoid_front"."""
    if pedal["id"] in acc["pedals"]:
        return acc["pedals"][pedal["id"]]
    rules = [acc["tags"][t] for t in pedal.get("tags", []) if t in acc["tags"]]
    if "tap" in switch_types:
        rules = [r for r in rules if r["want"] != "avoid_front"]
    rules += [acc["switches"][t] for t in sorted(set(switch_types)) if t in acc["switches"]]
    if not rules:
        return None
    return max(rules, key=lambda r: (r["weight"], -WANTS.index(r["want"]) if r["want"] in WANTS else 0))


def octile(a, b):
    dx, dy = abs(a[0] - b[0]), abs(a[1] - b[1])
    return max(dx, dy) + SQRT2_1 * min(dx, dy)


def detour(a, b, rects):
    """Extra cable length (mm) to get around the rectangles the straight line a -> b crosses: twice the smaller
    sideways offset (out and back) that clears all crossed rectangles on one side (touching pedals block together).
    Rectangles = pedals grown by the cable radius, so a gap narrower than the cable counts as closed. A rough
    stand-in for the router's detours."""
    dx, dy = b[0] - a[0], b[1] - a[1]
    seg = math.hypot(dx, dy)
    if seg < 1e-9:
        return 0.0
    nx, ny = -dy / seg, dx / seg
    x0, x1 = (b[0], a[0]) if b[0] < a[0] else (a[0], b[0])   # (min / max of two, without the builtins' calls)
    y0, y1 = (b[1], a[1]) if b[1] < a[1] else (a[1], b[1])
    offs = []
    for r in rects:
        if r[2] <= x0 or r[0] >= x1 or r[3] <= y0 or r[1] >= y1:
            continue
        # Liang-Barsky: does the open segment pass through the rectangle's interior?
        t0, t1 = 0.0, 1.0
        ok = True
        for pp, qq in ((-dx, a[0] - r[0]), (dx, r[2] - a[0]), (-dy, a[1] - r[1]), (dy, r[3] - a[1])):
            if -1e-12 < pp < 1e-12:
                if qq <= 0:
                    ok = False
                    break
                continue
            t = qq / pp
            if pp < 0:
                if t > t0:
                    t0 = t
            elif t < t1:
                t1 = t
            if t0 >= t1:
                ok = False
                break
        if not ok or (t1 - t0) * seg < 1e-6:
            continue
        offs += [(cx - a[0]) * nx + (cy - a[1]) * ny for cx in (r[0], r[2]) for cy in (r[1], r[3])]
    return 2 * min(max(offs), -min(offs)) if offs else 0.0


def _shift(r, dx, dy):
    return (r[0] + dx, r[1] + dy, r[2] + dx, r[3] + dy)


def _bbox(rects):
    return (min(r[0] for r in rects), min(r[1] for r in rects), max(r[2] for r in rects), max(r[3] for r in rects))


class Model:
    """Everything the score needs about one project and the owner's layout.

    Built from a parsed layout (`items`), the project dict and catalog data; `wiring`: [(port point or None,
    [pedal ids])] daisy chains for the power term (None: the project's own wiring)."""

    def __init__(self, project, items, cat_pedals, cat_supplies, jacks_data, fs_data, cable_types, wiring=None,
                 fs_limit=None, outlines=None, board_data=None, board_edits=None):
        import jacks
        self.project, self.items, self.cat_pedals = project, items, cat_pedals
        self.cfg = settings(project)
        self.w = self.cfg["weights"]
        chain = [p for p in project.get("signal_chain", []) if p in cat_pedals]
        insts = [{"inst": i, "sup": cat_supplies[i["supply"]], "rows": [{"port": o["port"], "pedals": o.get("pedals", [])}
                                                                         for o in i.get("outputs", [])]}
                 for i in (project.get("power") or {}).get("supplies", []) if i["supply"] in cat_supplies]
        jset = project.get("jacks", {})
        self.outlines = outlines = outlines_mod.load() if outlines is None else outlines   # read once
        lay = jacks.layout_from_items(items, chain, insts, cat_pedals, cat_supplies, jset, [], [], outlines=outlines,
                                      board_data=board_data, board_edits=board_edits)
        if lay["board"] is None:
            raise ValueError("the layout has no pedalboard item")
        self.board = design.footprint(lay["board"])
        self.placed = lay["placed"]
        self.inst_item, self.insts = lay["inst_item"], insts
        self.ids = [p for p in chain if p in self.placed]          # movable pedals, chain order
        self.n_ped = len(self.ids)
        sup_of = {s["inst"]["id"]: s for s in insts}
        on_board = [iid for iid in sorted(lay["inst_item"]) if lay["inst_placement"].get(iid) == "on_board"]
        clash = sorted(set(on_board) & set(self.ids))
        if clash:
            raise ValueError(f"supply instance id(s) {', '.join(clash)} are also pedal ids")
        self.ids += on_board                                       # then the movable on-board supplies
        self.mitem = {**self.placed, **{iid: lay["inst_item"][iid] for iid in on_board}}   # movable id -> layout item
        self.index = {p: n for n, p in enumerate(self.ids)}
        moving = {self.mitem[p]["id"] for p in self.ids}
        self.fixed = [o for o in lay["obstacles"] if o["id"] not in moving]
        self.fixed_feet = [(o["title"], design.footprint(o)) for o in self.fixed]
        self.fixed_shapes = [design.item_shapes(lay["shapes"], o) for o in self.fixed]   # outlines (clearance only)
        self.jacks_data = jacks.usable(jacks_data)
        self.fs_data = footswitches.usable(fs_data or {})
        self.cable_types = cable_types
        self.rcfg = routing.settings(project, cable_types)
        # a right-angle plug may point down into a board hole (routing.end_options / down_available): the holes and the under-board
        # supplies are fixed during the search (they do not move), availability depends on where a candidate puts the bend point
        self.holes = lay.get("holes") or []
        self.hole_box = _bbox(self.holes) if self.holes else None
        place = lay["inst_placement"]
        self.under_rects = [r for iid, it in lay["inst_item"].items() if place.get(iid) != "on_board"
                            for r in design.item_shapes(lay["shapes"], it)]
        given = (project.get("cables") or {}).get("hole_transit_mm")
        self.transit = float(given if given is not None else lay["hole_transit_mm"] if lay.get("hole_transit_mm") is not None
                             else routing.HOLE_TRANSIT_FALLBACK)
        self.down_on = bool(self.rcfg["under_board"] and self.holes)
        # the options' run settings: as route_project's cfg, which also carries the deck transit when the cables may go under
        self.dcfg = {**self.rcfg, "hole_transit_mm": self.transit} if self.rcfg["under_board"] else self.rcfg
        self.outward = float(jset.get("clearance", {}).get("outward_mm", jacks.CLEARANCE_DEFAULT["outward_mm"]))
        self.side = float(jset.get("clearance", {}).get("side_mm", jacks.CLEARANCE_DEFAULT["side_mm"]))
        self.p_out = float(jset.get("power_clearance", {}).get("outward_mm", jacks.POWER_CLEARANCE_DEFAULT["outward_mm"]))
        self.p_side = float(jset.get("power_clearance", {}).get("side_mm", jacks.POWER_CLEARANCE_DEFAULT["side_mm"]))
        self.extra_used = jset.get("extra_used", {})
        ptype_id = self.rcfg["power_type"]
        self.ptype = cable_types.get(ptype_id) if ptype_id else None
        self.p_depth = float(self.ptype["plug"]["head_depth_mm"]) if self.ptype else self.p_out
        # the DC plug types a power plug may take (cables.power_types, the default first; none without a default type: the box)
        self.pcands = [t for t in self.rcfg["power_types"] if t in cable_types] if self.ptype else []
        # (a fixed power plug side (cables.overrides.<P#>.exit_b) belongs to its pedal: the owner's wiring)
        # power cables run under the board and come up through the nearest usable hole: sample the holes once; per candidate
        # only the pedals' coverage of the points near each jack is tested (None: Manhattan between the measure points)
        self.power_setup = power.estimate_setup(project, lay, cable_types)
        self._rect_bits, self._near_memo = {}, {}   # score(): {footprint: bits of the hole points it covers}, {(point, covered bits): nearest crossing}
        self.inst_under = {iid: pl != "on_board" for iid, pl in lay["inst_placement"].items()}
        over = self.rcfg["overrides"]
        self.p_exit = {pid: (over.get(cid) or {}).get("exit_b")
                       for pid, cid in power.cable_ids((project.get("power") or {}).get("supplies", [])).items()}
        self.p_type = {pid: (over.get(cid) or {}).get("type_b")
                       for pid, cid in power.cable_ids((project.get("power") or {}).get("supplies", [])).items()}
        # an on-board supply's power cables start at its used ports: the cable's `exit_a` override (the first pedal's cable)
        pids = power.cable_ids((project.get("power") or {}).get("supplies", []))
        self.s_exit, self.s_type = {}, {}
        for iid in on_board:
            for r in sup_of[iid]["rows"]:
                if r["pedals"] and r["port"] not in self.s_exit.get(iid, {}):
                    self.s_exit.setdefault(iid, {})[r["port"]] = (over.get(pids.get(r["pedals"][0])) or {}).get("exit_a")
                    self.s_type.setdefault(iid, {})[r["port"]] = (over.get(pids.get(r["pedals"][0])) or {}).get("type_a")
        self.sup_ports = {iid: sorted({r["port"] for r in sup_of[iid]["rows"] if r["pedals"]}) for iid in on_board}
        self.sup_id = {iid: sup_of[iid]["sup"]["id"] for iid in on_board}
        self.owner = [self._state_of(self.mitem[p]) for p in self.ids]
        self.names = {p: cat_pedals[p].get("name", p) for p in self.ids[:self.n_ped]}
        for iid in on_board:
            sup = sup_of[iid]["sup"]
            self.names[iid] = sup_of[iid]["inst"].get("label") or f"{sup.get('brand', '')} {sup.get('model', sup['id'])}".strip()
        self.titles = [self.mitem[p]["title"] for p in self.ids]
        # allowed rotations (180 only if the owner's layout already has it)
        rots = self.cfg["rotations"]
        self.allowed = []
        for p, st in zip(self.ids, self.owner):
            want = rots.get(p, rots.get("default", [0, 90, 270]))
            want = [0, 90, 180, 270] if want == "any" else ([st[2]] if want == "current" else list(want))
            self.allowed.append(sorted({int(r) % 360 for r in want if int(r) % 360 != 180} | {st[2]}))
        self.pins = set(self.cfg.get("pins") or [])
        unknown_pins = self.pins - set(self.ids)
        if unknown_pins:
            raise ValueError(f"layout.pins: not a placed chain pedal or on-board supply: {', '.join(sorted(unknown_pins))}")
        # footswitches
        self.fs_known = any(self.fs_data.get(p) for p in self.ids)
        limit, self.fs_comfort, _, _ = footswitches.spacing_settings(project)
        self.fs_limit = limit if fs_limit is None else fs_limit
        self.fs_priority = footswitches.priorities(project)
        self.access = [access_rule({**cat_pedals[p], "id": p}, [f["type"] for f in self.fs_data.get(p) or []],
                                   self.cfg["access"]) for p in self.ids[:self.n_ped]] + [None] * len(on_board)
        self._geom = {}
        for n, p in enumerate(self.ids):
            for r in self.allowed[n]:
                self._geom[(n, r)] = self._geometry(n, r)
        self.set_wiring(wiring)

    # --- precomputation ------------------------------------------------------------------------
    @staticmethod
    def _state_of(item):
        cx, cy = design.centre(item)
        return (cx, cy, item["rot"])

    def _geometry(self, n, rot):
        """Everything of pedal n at rotation `rot` relative to its centre."""
        from jacks import default_jack, _jack_by_id
        pid = self.ids[n]
        it = self.mitem[pid]
        tmp = {**it, "rot": rot, "left_mm": -it["w_mm"] / 2, "top_mm": -it["h_mm"] / 2}
        f = design.footprint(tmp)
        have = self.jacks_data.get(pid) or []
        g = {"half": (f[2], f[3]), "shapes": design.outline_rects(tmp, self.outlines), "ends": {}, "power": None, "extra": [], "fs": [],
             "in": None, "out": None, "ports": [], "port_pt": {}}
        if n >= self.n_ped:
            return self._supply_geometry(g, tmp, pid)
        chain_pos = self.project["signal_chain"].index(pid)
        chain = self.project["signal_chain"]
        over = self.rcfg["overrides"]
        run_given = "exit_run_mm" in (self.project.get("cables") or {})
        for fn, end, hop in (("output", "a", chain_pos + 1), ("input", "b", chain_pos)):
            jk = default_jack(have, fn)
            if jk:
                g["in" if fn == "input" else "out"] = design.jack_point(tmp, jk["x"], jk["y"])
            if not jk:
                continue
            if hop < 1 or hop >= len(chain):   # guitar input / amp output: the fixed audio box, as jacks.check
                pt = design.jack_point(tmp, jk["x"], jk["y"])
                facing = design.jack_facing(tmp, jk["facing"])
                g["extra"].append({"jack": f"{pid}.{jk['id']}", "facing": facing, "down": [], "opts": [self._opt(
                    {"side": None, "rects": [("box", design.clearance_rect(pt, facing, self.outward, self.side))],
                     "exit": pt, "measure_mm": 0.0})]})
                continue
            cid = f"S{hop}"
            tid = routing.cable_type_id(self.project, cid)
            ctype = self.cable_types.get(tid) if tid else None
            run = self.dcfg if run_given or not ctype else {**self.dcfg, "exit_run_mm": float(ctype["diameter_mm"])}
            fixed = (over.get(cid) or {}).get(f"exit_{end}")
            if ctype is None:
                facing, opts = routing.end_options(tmp, jk, None, fixed, run, self.outward)
                pt = design.jack_point(tmp, jk["x"], jk["y"])
                for o in opts:
                    o["rects"] = [("box", design.clearance_rect(pt, facing, self.outward, self.side))]
                opts, downs = [self._opt(o) for o in opts], []
            else:
                facing, opts, downs = self._pool(tmp, jk, [(0, tid, ctype)], fixed, run)
            g["ends"][cid] = {"jack": f"{pid}.{jk['id']}", "facing": facing, "opts": opts, "down": downs}
        jk = default_jack(have, "power")
        if jk:
            pt = design.jack_point(tmp, jk["x"], jk["y"])
            facing = design.jack_facing(tmp, jk["facing"])
            opts, downs = self._power_options(tmp, jk, pt, facing, self.p_exit.get(pid), self.p_type.get(pid))
            g["power"] = {"jack": f"{pid}.{jk['id']}", "facing": facing, "opts": opts, "down": downs}
        for jid in self.extra_used.get(pid, []):
            jk = _jack_by_id(have, jid)
            if jk and f"{pid}.{jid}" not in {e["jack"] for e in g["extra"]}:   # each jack once, as jacks.check
                pt = design.jack_point(tmp, jk["x"], jk["y"])
                facing = design.jack_facing(tmp, jk["facing"])
                g["extra"].append({"jack": f"{pid}.{jid}", "facing": facing, "down": [], "opts": [self._opt(
                    {"side": None, "rects": [("box", design.clearance_rect(pt, facing, self.outward, self.side))],
                     "exit": pt, "measure_mm": 0.0})]})
        for fs in self.fs_data.get(pid) or []:
            x, y = design.jack_point(tmp, fs["x"], fs["y"])
            g["fs"].append((x, y, fs["type"], f"{pid}.{fs['id']}"))
        return g

    def _supply_geometry(self, g, tmp, iid):
        """An on-board supply: no signal ends, footswitches or extra jacks; its used output ports as plug-clearance ends (the DC
        plug as for a pedal's power jack, else the fixed power box) and their measure points (half the plug depth in front of
        the port, as power.measure_points) as the start of the power cables."""
        from jacks import _jack_by_id
        have = self.jacks_data.get(self.sup_id[iid]) or []
        for port in self.sup_ports[iid]:
            jk = _jack_by_id(have, port)
            if not jk:
                continue
            pt = design.jack_point(tmp, jk["x"], jk["y"])
            facing = design.jack_facing(tmp, jk["facing"])
            opts, downs = self._power_options(tmp, jk, pt, facing, self.s_exit.get(iid, {}).get(port), self.s_type.get(iid, {}).get(port))
            g["ports"].append({"jack": f"{iid}.{port}", "port": port, "facing": facing, "opts": opts, "down": downs})
            g["port_pt"][port] = design.stub(pt, facing, self.p_depth / 2)
        return g

    @staticmethod
    def _opt(o, **extra):
        """One plug option as the score needs it (relative to the pedal's centre): side, rects [(part, rect)], their bbox, `exit` (the
        point the cable leaves at, for a plug pointing down the bend point where it continues under the board), `measure_mm`, `measure` (the
        point cable lengths start at), `down`; `extra`: type, tidx (position in the project's DC plug types), diam (cable diameter)."""
        rects = [(part, r) for part, r in o["rects"]]
        return {"side": o["side"], "rects": rects, "bbox": _bbox([r for _, r in rects]) if rects else None,
                "exit": o["exit"], "measure_mm": o.get("measure_mm", 0.0), "measure": o.get("measure"),
                "down": bool(o.get("down")), **extra}

    def _pool(self, tmp, jk, cands, fixed, run):
        """(facing, side options, down options) of one jack for the plug types `cands` [(position in the list, id, cable type)] (routing.
        end_options; the down option of each type is kept apart: whether it may be used depends on where a candidate puts the bend
        point, see `_cands`). An exit override (`fixed`) of a side keeps only the options with that side (all if there is none); "down"
        and "auto" decide per candidate (down wins where the plug fits into a hole, as the build)."""
        fx = fixed if fixed in design.EXITS else None
        down = (lambda pt, d: True) if self.down_on else None
        sides, downs, facing = [], [], None
        for tidx, tid, ct in cands:
            facing, ts = routing.end_options(tmp, jk, ct, None if fx == design.DOWN else fx, run(ct) if callable(run) else run,
                                             self.outward, down=down)
            for o in ts:
                (downs if o.get("down") else sides).append(self._opt(o, type=tid, tidx=tidx, diam=float(ct["diameter_mm"])))
        if fx in design.SIDES:
            sides = [o for o in sides if o["side"] == fx] or sides
        return facing, sides, downs

    def _power_options(self, tmp, jk, pt, facing, fixed, fixed_type):
        """(side options, down options) of a DC plug at jack `jk` (point `pt`): every exit of every plug type the project offers (a type
        override `fixed_type` keeps that one), or the fixed power box without a DC plug type."""
        if not self.pcands:
            box = {"side": None, "rects": [("box", design.clearance_rect(pt, facing, self.p_out, self.p_side))], "exit": pt,
                   "measure_mm": 0.0, "measure": design.stub(pt, facing, self.p_depth / 2)}
            return [self._opt(box, type=None, tidx=0, diam=0.0)], []
        names = [fixed_type] if fixed_type in self.cable_types else self.pcands
        cands = [(0 if len(names) == 1 else i, t, self.cable_types[t]) for i, t in enumerate(names)]
        jh = self.rcfg.get("jack_height_mm", routing.DEFAULTS["jack_height_mm"])
        run = lambda ct: {"exit_run_mm": float(ct["diameter_mm"]), "jack_height_mm": jh,
                          "hole_transit_mm": self.dcfg.get("hole_transit_mm", 0.0)}
        _, sides, downs = self._pool(tmp, jk, cands, fixed, run)
        return sides, downs

    def set_wiring(self, wiring):
        """Daisy chains for the power term: [(port point or None, [pedal ids][, starts under the board[, (supply instance
        id, port)[, style]]])]; None = the project's own wiring (the flag defaults to True: under-board supplies). A port of a
        movable (on-board) supply instance follows it: stored as {"inst": state index, "port": port id} whatever point is given.
        style: "serial" (default: the cable runs port -> first pedal -> next ...) or "forked" (one cable per pedal from the
        port); the fourth item of each `self.wiring` entry."""
        if wiring is None:
            import power
            insts = [{"id": s["inst"]["id"], "supply": s["sup"]["id"]} for s in self.insts]
            _, ports = power.measure_points({}, self.inst_item, insts, self.jacks_data, self.p_depth)
            wiring = [(ports.get((s["inst"]["id"], o["port"])), list(o.get("pedals", [])), self.inst_under.get(s["inst"]["id"], True),
                       (s["inst"]["id"], o["port"]), routing.daisy_style(self.project, o))
                      for s in self.insts for o in s["inst"].get("outputs", [])]
        self.wiring = []
        for w in wiring:
            start = w[0]
            if len(w) > 3 and w[3] and w[3][0] in self.index and self.index[w[3][0]] >= self.n_ped:
                start = {"inst": self.index[w[3][0]], "port": w[3][1]}
            self.wiring.append((start, [self.index[p] for p in w[1] if p in self.index and self.index[p] < self.n_ped],
                                w[2] if len(w) > 2 else True, w[4] if len(w) > 4 and w[4] in routing.DAISY_STYLES else routing.SERIAL))

    # --- candidates --------------------------------------------------------------------------------
    def footprint(self, st, n):
        hw, hh = self._geom[(n, st[2])]["half"]
        return (st[0] - hw, st[1] - hh, st[0] + hw, st[1] + hh)

    def feasible_one(self, state, n, feet=None, tol=None):
        """Whether pedal n can sit where `state` puts it: inside the board, no overlap with any other pedal or
        fixed item, pins, rotation and max move respected."""
        st = state[n]
        if st[2] not in self.allowed[n]:
            return False
        own = self.owner[n]
        if self.ids[n] in self.pins and (abs(st[0] - own[0]) > 1e-6 or abs(st[1] - own[1]) > 1e-6 or st[2] != own[2]):
            return False
        mm = self.max_move
        if mm is not None and math.hypot(st[0] - own[0], st[1] - own[1]) > mm + 0.5:   # 0.5: px snapping
            return False
        f = self.footprint(st, n)
        m, b = float(self.cfg["board_margin_mm"]), self.board
        tol = self.overlap_tol if tol is None else tol
        if f[0] < b[0] + m - 1e-6 or f[1] < b[1] + m - 1e-6 or f[2] > b[2] - m + 1e-6 or f[3] > b[3] - m + 1e-6:
            return False
        gap = float(self.cfg["min_gap_mm"])
        g = (f[0] - gap, f[1] - gap, f[2] + gap, f[3] + gap) if gap else f
        for k in range(len(state)):
            if k != n:
                o = feet[k] if feet else self.footprint(state[k], k)
                if min(g[2], o[2]) - max(g[0], o[0]) > tol and min(g[3], o[3]) - max(g[1], o[1]) > tol:
                    return False
        for _, o in self.fixed_feet:
            if min(g[2], o[2]) - max(g[0], o[0]) > tol and min(g[3], o[3]) - max(g[1], o[1]) > tol:
                return False
        return True

    max_move = None             # set by the search level (hard limit, mm)
    overlap_tol = design.TOL_MM  # the search uses ~0 (strict touching) so that snapping to px stays within TOL_MM

    def feasible(self, state, tol=design.TOL_MM):
        """Every hard constraint holds (overlaps up to `tol`, default design.TOL_MM as the build)."""
        return all(self.feasible_one(state, n, tol=tol) for n in range(len(state)))

    def problems(self, state):
        """Hard-constraint problems of a candidate, as strings (empty: feasible)."""
        return [f"{self.ids[n]} is off the board, overlaps another item, or breaks a pin/rotation/max-move limit"
                for n in range(len(state)) if not self.feasible_one(state, n, tol=design.TOL_MM)]

    # --- score ----------------------------------------------------------------------------------
    def _down_ok(self, x, y, d):
        """Whether a plug may point down with its bend point at (x, y) and a cable `d` mm wide (routing.down_available on the holes the
        square touches; the holes and the under-board supplies are fixed)."""
        h, hb = d / 2, self.hole_box
        if x - h < hb[0] - 1e-6 or y - h < hb[1] - 1e-6 or x + h > hb[2] + 1e-6 or y + h > hb[3] + 1e-6:
            return False
        near = [r for r in self.holes if r[2] > x - h and r[0] < x + h and r[3] > y - h and r[1] < y + h]
        return bool(near) and routing.down_available(near, self.under_rects, (x, y), d)

    def _cands(self, end, st):
        """The options a plug end can take with its pedal at `st`: the options pointing down that fit into a hole there (owner rule:
        always down where available, even if longer), else every side option."""
        if end["down"]:
            x, y = st[0], st[1]
            ok = [o for o in end["down"] if self._down_ok(o["exit"][0] + x, o["exit"][1] + y, o["diam"])]
            if ok:
                return ok
        return end["opts"]

    def _under_span(self, oa, pa, ob, pb, holes, near):
        """The cable between the exits `pa`, `pb` of two plug options of a signal cable when one or both point down (mm; the plugs' own
        `measure_mm` come on top): both down = the octile distance under the board (no pedals in the way: no detour); one down = under
        the board from its bend point to the crossing (hole / edge point) nearest the other, exit, the pass and the way on top
        (`near` finds the crossing, `holes` the power setup's `Crossings`; without one, the other exit is taken as the crossing)."""
        if oa["down"] and ob["down"]:
            return octile(pa, pb)
        pd, pt = (pa, pb) if oa["down"] else (pb, pa)
        h = near(pt) if near else None
        if h is None:
            return octile(pd, pt) + self.transit
        return octile(pd, h) + holes.transit_of(h, self.transit) + math.hypot(h[0] - pt[0], h[1] - pt[1])

    def _clearance(self, end, st, n, obs, margin, area=None):
        """[((infeasible, cost), cost, option, hits, intrusion, part pairs, overlap sum)] of one plug end, one row per option of `_cands`; the choice is the row with the
        smallest first item (with `area`, the routing area: a feasible option first, as the router ranks a DC plug: its exit inside the area and
        in no other pedal's outline; else the lowest clearance cost)."""
        rows = []
        cands = self._cands(end, st)
        for o in cands:
            cost, hits, intr, nparts, ovsum = self._opt_clearance(end, o, st, n, obs, margin)
            bad = area is not None and len(cands) > 1 and self._infeasible(o, st, n, obs, area, cost)
            rows.append(((bad, cost), cost, o, hits, intr, nparts, ovsum))
        return rows

    @staticmethod
    def _infeasible(o, st, n, obs, area, cost):
        """Whether the cable of plug option `o` cannot leave it: the exit lies outside the routing area or (only a plug with a clearance cost can
        have it there) strictly inside another item's outline."""
        px, py = o["exit"][0] + st[0], o["exit"][1] + st[1]
        if not (area[0] <= px < area[2] and area[1] <= py < area[3]):
            return True
        if cost <= 0:
            return False
        for k, _, f, shp in obs:
            if k != n and f[0] < px < f[2] and f[1] < py < f[3] and any(r[0] < px < r[2] and r[1] < py < r[3] for r in shp):
                return True
        return False

    def _pair(self, oa, sa, ob, sb, margin):
        """(real, penetration) of two plug options at the pedal centres `sa`, `sb`: the deepest overlap of a part of each (smaller side, mm;
        design.overlap, TOL like the build) and the same with the first grown by `margin`."""
        tol = design.TOL_MM
        xa, ya, xb, yb = sa[0], sa[1], sb[0], sb[1]
        real = pen = 0.0
        for _, r in oa["rects"]:
            r0, r1, r2, r3 = r[0] + xa, r[1] + ya, r[2] + xa, r[3] + ya
            for _, q in ob["rects"]:
                q0, q1, q2, q3 = q[0] + xb, q[1] + yb, q[2] + xb, q[3] + yb
                g0, g1, g2, g3 = r0 - margin, r1 - margin, r2 + margin, r3 + margin   # (the first part grown by the margin)
                dx, dy = (g2 if g2 < q2 else q2) - (g0 if g0 > q0 else q0), (g3 if g3 < q3 else q3) - (g1 if g1 > q1 else q1)
                if dx > tol and dy > tol:   # (no overlap with the margin: none without it)
                    m = dx if dx < dy else dy
                    if m > pen:
                        pen = m
                    dx, dy = (r2 if r2 < q2 else q2) - (r0 if r0 > q0 else q0), (r3 if r3 < q3 else q3) - (r1 if r1 > q1 else q1)
                    if dx > tol and dy > tol:
                        m = dx if dx < dy else dy
                        if m > real:
                            real = m
        return real, (pen if pen > real else real)

    def _pair_cost(self, real, pen):
        """The cost of two colliding plugs: `clearance` per mm of the real overlap, `clearance_margin` per mm of the extra penetration with
        the margin, `clearance_hit` for a real overlap."""
        w = self.w
        return w["clearance"] * real + w["clearance_margin"] * (pen - real) + (w["clearance_hit"] if real > 0 else 0.0)

    @staticmethod
    def _boxes(state, items, margin):
        """The plug footprints of the choice `items` [(jack key, pedal index, option)] as (grown bbox x0, y0, x1, y1, key, index, option),
        sorted by x0."""
        out = []
        for key, n, o in items:
            if o["bbox"] is not None:
                x, y = state[n][0], state[n][1]
                b = o["bbox"]
                out.append((b[0] + x - margin, b[1] + y - margin, b[2] + x + margin, b[3] + y + margin, key, n, o))
        out.sort(key=lambda it: it[0])
        return out

    def _collisions(self, state, items, margin):
        """(cost, intrusion mm, [{"jack", "with", "depth_mm", "na", "nb"}]) of the plug footprints of different jacks that overlap
        (`_pair`; `na`, `nb` = the pedal / supply indices). Weights as the clearance (`_pair_cost`): the intrusion of every pair that comes
        within the margin counts, only those that really overlap are listed (as the build's `plug_collisions`). Candidate pairs
        come from a sweep over the bounding boxes."""
        boxes = self._boxes(state, items, margin)
        cost = intrusion = 0.0
        found = []
        for i, (ax0, ay0, ax1, ay1, ka, na, oa) in enumerate(boxes):
            for j in range(i + 1, len(boxes)):
                bx0, by0, bx1, by1, kb, nb, ob = boxes[j]
                if bx0 >= ax1:
                    break
                if by1 <= ay0 or by0 >= ay1:
                    continue
                real, pen = self._pair(oa, state[na], ob, state[nb], margin)
                if pen > 0:
                    intrusion += pen
                    cost += self._pair_cost(real, pen)
                    if real > 0:
                        found.append({"jack": ka, "with": kb, "depth_mm": real, "na": na, "nb": nb})
        return cost, intrusion, found

    def _against(self, state, o, n, others, margin):
        """The collision cost of plug option `o` of pedal `n` against the footprints `others` (`_boxes`)."""
        if o["bbox"] is None:
            return 0.0
        x, y = state[n][0], state[n][1]
        b = o["bbox"]
        bx0, by0, bx1, by1 = b[0] + x - margin, b[1] + y - margin, b[2] + x + margin, b[3] + y + margin
        cost = 0.0
        for ox0, oy0, ox1, oy1, _, k, oo in others:
            if ox0 < bx1 and ox1 > bx0 and oy0 < by1 and oy1 > by0:
                real, pen = self._pair(o, state[n], oo, state[k], margin)
                if pen > 0:
                    cost += self._pair_cost(real, pen)
        return cost

    @staticmethod
    def _chosen(recs):
        """[(jack key, pedal / supply index, option)] of the choice the recs (`score`, phase A) hold."""
        items = []
        for rec in recs:
            if rec[0] == "s":
                items += [(rec[4]["jack"], rec[2], rec[6][rec[11][1]]), (rec[5]["jack"], rec[3], rec[7][rec[11][2]])]
            else:
                items.append((rec[2]["jack"], rec[1], rec[4][2]))
        return items

    def _count(self, state, o, n, taken):
        """The build's `collision_count`: how many (part of option `o` of pedal `n`, other plug) pairs overlap (`taken` = `_boxes`-like tuples of
        the plugs decided so far)."""
        x, y = state[n][0], state[n][1]
        tol, count = design.TOL_MM, 0
        for _, r in o["rects"]:
            r0, r1, r2, r3 = r[0] + x, r[1] + y, r[2] + x, r[3] + y
            for tx0, ty0, tx1, ty1, _, k, oo in taken:
                if tx0 < r2 and tx1 > r0 and ty0 < r3 and ty1 > r1:
                    xk, yk = state[k][0], state[k][1]
                    for _, q in oo["rects"]:
                        q0, q1, q2, q3 = q[0] + xk, q[1] + yk, q[2] + xk, q[3] + yk
                        if (r2 if r2 < q2 else q2) - (r0 if r0 > q0 else q0) > tol and (r3 if r3 < q3 else q3) - (r1 if r1 > q1 else q1) > tol:
                            count += 1
                            break
        return count

    def _resolve(self, state, recs, bad, margin):
        """Where plugs collide (`bad`: their jack keys), the choice of the ends involved is made again as the build makes it: signal cables in
        chain order, then the DC plugs, each seeing only the plugs decided before it (and the fixed boxes), the options ranked by the number of
        blocked parts + plug collisions (`_count`), then (signal) the shorter cable / (DC plug) the smaller overlap and the type's position in
        the list. A choice without collision stays. Changes the picks in `recs`; returns whether any changed."""
        def box(key, n, o):
            x, y = state[n][0], state[n][1]
            b = o["bbox"]
            return (b[0] + x - margin, b[1] + y - margin, b[2] + x + margin, b[3] + y + margin, key, n, o)

        def fixed(o):
            return o["bbox"] is not None and o["rects"][0][0] == "box"
        items = self._chosen(recs)
        taken = [box(k, n, o) for k, n, o in items if fixed(o)]
        changed = False
        for rec in recs:
            if rec[0] == "s":
                _, cid, ia, ib, ea, eb, opa, opb, ca, cb, combos, cur = rec
                if len(combos) > 1 and {ea["jack"], eb["jack"]} & bad:
                    if self._against(state, opa[cur[1]], ia, taken, margin) + self._against(state, opb[cur[2]], ib, taken, margin) + \
                            self._pair_cost(*self._pair(opa[cur[1]], state[ia], opb[cur[2]], state[ib], margin)) > 0:
                        ha = [ca[k][3] + self._count(state, opa[k], ia, taken) for k in range(len(opa))]
                        hb = [cb[k][3] + self._count(state, opb[k], ib, taken) for k in range(len(opb))]

                        best = min(combos, key=lambda c: (c[4] or c[5], ha[c[1]] + hb[c[2]] +
                                                          self._parts(opa[c[1]], state[ia], opb[c[2]], state[ib]), c[3]))
                        if best is not cur:
                            cur = rec[11] = best
                            changed = True
                for e, n, o in ((ea, ia, opa[cur[1]]), (eb, ib, opb[cur[2]])):
                    if not fixed(o):
                        taken.append(box(e["jack"], n, o))
            else:
                _, n, end, rows, cur = rec
                o = cur[2]
                if fixed(o):
                    continue
                if len(rows) > 1 and end["jack"] in bad and self._against(state, o, n, taken, margin) > 0:
                    best = min(rows, key=lambda r: (r[0][0], r[5] + self._count(state, r[2], n, taken), r[6], r[2]["tidx"]))
                    if best is not cur:
                        cur = rec[4] = best
                        changed = True
                taken.append(box(end["jack"], n, cur[2]))
        return changed

    @staticmethod
    def _parts(oa, sa, ob, sb):
        """How many (part of `oa`, part of `ob`) pairs overlap (the build counts those between the two ends of a cable)."""
        tol, count = design.TOL_MM, 0
        for _, r in oa["rects"]:
            for _, q in ob["rects"]:
                a2, b2, a0, b0 = r[2] + sa[0], q[2] + sb[0], r[0] + sa[0], q[0] + sb[0]
                a3, b3, a1, b1 = r[3] + sa[1], q[3] + sb[1], r[1] + sa[1], q[1] + sb[1]
                if (a2 if a2 < b2 else b2) - (a0 if a0 > b0 else b0) > tol and (a3 if a3 < b3 else b3) - (a1 if a1 > b1 else b1) > tol:
                    count += 1
        return count

    def _obstacles(self, state, feet):
        """[(pedal index or None for a fixed item, title, footprint, outline rects at the candidate position)], once per
        candidate (`score`), for the clearance of every plug option."""
        return [(k, self.titles[k], f, [_shift(q, state[k][0], state[k][1]) for q in self._geom[(k, state[k][2])]["shapes"]])
                for k, f in enumerate(feet)] + \
               [(None, t, f, shp) for (t, f), shp in zip(self.fixed_feet, self.fixed_shapes)]

    def _opt_clearance(self, end, o, st, n, obs, margin):
        """(cost, hits, intrusion mm, overlapping part pairs, their overlap sum) of one plug option. Intrusion per obstacle = the penetration (smaller overlap
        side) of the plug parts grown by `margin`: how far the obstacle must move to clear, smooth for the search.
        A hit = a real overlap without the margin (as the build reports it: deepest part, design.part_depth).
        Also the number of (part, obstacle) pairs that really overlap and the sum of their overlaps (the build's `blocked_parts`, which
        ranks the options of a DC plug: `_resolve`). Obstacles are their outlines (`obs` from `_obstacles`; a cheap footprint test comes first), as the build."""
        if not o["rects"]:
            return 0.0, [], 0.0, 0, 0.0
        bb = o["bbox"]
        x, y = st[0], st[1]
        bx0, by0, bx1, by1 = bb[0] + x - margin, bb[1] + y - margin, bb[2] + x + margin, bb[3] + y + margin
        tol = design.TOL_MM
        hits, intrusion, cost, nparts, ovsum = [], 0.0, 0.0, 0, 0.0
        shape_overlap = design.shape_overlap
        for k, title, f, shp in obs:
            # (min(a, b) = b if b < a else a, max(a, b) = b if b > a else a: the builtins' results without the calls)
            f2, f0, f3, f1 = f[2], f[0], f[3], f[1]
            if k == n or (f2 if f2 < bx1 else bx1) - (f0 if f0 > bx0 else bx0) <= tol or (f3 if f3 < by1 else by1) - (f1 if f1 > by0 else by0) <= tol:
                continue
            pen, pen_real, deepest = 0.0, 0.0, None
            for part, r in o["rects"]:
                rr = (r[0] + x, r[1] + y, r[2] + x, r[3] + y)
                ov = shape_overlap((rr[0] - margin, rr[1] - margin, rr[2] + margin, rr[3] + margin), shp)
                if not ov:
                    continue
                m = ov[1] if ov[1] < ov[0] else ov[0]
                if m > pen:
                    pen = m
                real = shape_overlap(rr, shp) if margin else ov
                if real:
                    m = real[1] if real[1] < real[0] else real[0]
                    if m > pen_real:
                        pen_real = m
                    nparts += 1
                    ovsum += m
                    d = design.part_depth(part, end["facing"], o["side"], real)
                    if deepest is None or d > deepest[1]:
                        deepest = (part, d)
            intrusion += pen
            cost += self.w["clearance"] * pen_real + self.w["clearance_margin"] * (pen - pen_real)
            if deepest:
                hits.append((title, deepest[0], deepest[1]))
        cost += self.w["clearance_hit"] * len(hits)
        return cost, hits, intrusion, nparts, ovsum

    def score(self, state, margin=None, detail=False, move_factor=1.0):
        """Weighted surrogate score of a candidate (lower is better); with `detail` also the raw terms and the
        findings: (total, {"terms": {name: (raw, weighted)}, "blocked": [...], "collisions": [{"jack", "with", "depth_mm"}], "plugs": {jack key:
        {"side", "type", "down"}} (the option every used jack takes), "fs_close": [...], ...})."""
        w = self.w
        margin = float(self.cfg["clearance_margin_mm"]) if margin is None else margin
        feet = [self.footprint(st, n) for n, st in enumerate(state)]
        geo = [self._geom[(n, st[2])] for n, st in enumerate(state)]
        b = self.board
        em = self.rcfg["edge_margin_mm"]
        obs = self._obstacles(state, feet)
        # as the build: nothing in front of the lowest pedal OUTLINE (detour estimate: boxes, an approximation)
        front_y = routing.front_limit(b, [q[3] for k, _, _, shp in obs if k is not None for q in shp] if feet else [], self.rcfg)
        area = (b[0] - em, b[1] - em, b[2] + em, front_y)
        r, wd = self.rcfg["diameter_mm"] / 2, w["detour"]
        grown = [(f[0] - r, f[1] - r, f[2] + r, f[3] + r) for f in feet] + \
                [(f[0] - r, f[1] - r, f[2] + r, f[3] + r) for _, f in self.fixed_feet]
        terms = dict.fromkeys(("clearance", "routing_area", "signal", "power", "footswitch", "io", "flow", "access",
                               "rotation", "move", "touch"), 0.0)
        raw = dict.fromkeys(terms, 0.0)
        blocked, outside, fs_close, sig_lengths, issues = [], [], [], {}, []

        def note_hits(jack, n, side, hits):
            for title, part, d in hits:
                blocked.append({"jack": jack, "obstacle": title, "part": part, "depth_mm": d, "side": side})
                issues.append((n, title, d))

        # crossings (holes, edge points) the candidate's pedal footprints leave free: the power cables' nearest-crossing estimate, and the
        # signal cables with a plug pointing down; Manhattan / a straight guess without holes
        pw_near = pw_cfg = holes = None
        if self.power_setup:
            pr = self.power_setup["radius"]
            pw_blocked = [(f[0] - pr, f[1] - pr, f[2] + pr, f[3] + pr) for f in feet + [f for _, f in self.fixed_feet]]
            holes = self.power_setup["crossings"]   # (its points are already free under the board)
            pts = holes.holes.points
            # the nearest usable crossing depends on the query point and on WHICH hole points the footprints cover (one bit per point,
            # a footprint's bits are remembered), so (point, covered set) keys an answer kept over the whole search
            mask, over, rect_bits = 0, [], self._rect_bits
            for r in pw_blocked:
                bits = rect_bits.get(r)
                if bits is None:
                    bits = 0
                    for i, h in enumerate(pts):
                        if r[0] <= h[0] <= r[2] and r[1] <= h[1] <= r[3]:
                            bits |= 1 << i
                    if len(rect_bits) > RECT_BITS_MAX:
                        rect_bits.clear()
                    rect_bits[r] = bits
                if bits:
                    mask |= bits
                    over.append(r)
            memo = self._near_memo
            if len(memo) > NEAR_MEMO_MAX:
                memo.clear()

            def pw_near(p):
                key = (p, mask)
                if key not in memo:
                    memo[key] = holes.nearest(p, over)
                return memo[key]
            pw_cfg = self.power_setup["cfg"]
        # phase A: every plug end's options and costs, the best choice (a plug that fits into a hole points down)
        chain = self.project["signal_chain"]
        recs = []   # signal cables: ["s", cid, ia, ib, ea, eb, opa, opb, ca, cb, combos, pick]; other plug ends: ["p", n, end, rows, pick]
        for n_hop in range(1, len(chain)):
            cid = f"S{n_hop}"
            a, bb = chain[n_hop - 1], chain[n_hop]
            if a not in self.index or bb not in self.index:
                continue
            ia, ib = self.index[a], self.index[bb]
            ea, eb = geo[ia]["ends"].get(cid), geo[ib]["ends"].get(cid)
            if not ea or not eb:
                continue
            sa, sb = state[ia], state[ib]
            opa, opb = self._cands(ea, sa), self._cands(eb, sb)
            ca = [self._opt_clearance(ea, o, sa, ia, obs, margin) for o in opa]
            cb = [self._opt_clearance(eb, o, sb, ib, obs, margin) for o in opb]
            combos = []   # (cost, index a, index b, length, a outside, b outside) of every combination of the two ends' options
            for ka, oa in enumerate(opa):
                pa = (oa["exit"][0] + sa[0], oa["exit"][1] + sa[1])
                outa = not oa["down"] and not (area[0] <= pa[0] < area[2] and area[1] <= pa[1] < area[3])
                for kb, ob in enumerate(opb):
                    pb = (ob["exit"][0] + sb[0], ob["exit"][1] + sb[1])
                    outb = not ob["down"] and not (area[0] <= pb[0] < area[2] and area[1] <= pb[1] < area[3])
                    if oa["down"] or ob["down"]:
                        span = self._under_span(oa, pa, ob, pb, holes, pw_near)
                    else:
                        span = octile(pa, pb) + wd * detour(pa, pb, grown)
                    length = oa["measure_mm"] + ob["measure_mm"] + span
                    combos.append((ca[ka][0] + cb[kb][0] + w["routing_area"] * (outa + outb) + w["signal"] * length, ka, kb, length, outa, outb))
            recs.append(["s", cid, ia, ib, ea, eb, opa, opb, ca, cb, combos, min(combos, key=lambda c: c[0])])
        # power plugs and extra jacks: clearance only (feasible, then down, then the lowest clearance cost; power: feasible = its exit inside
        # the routing area and in no other pedal's outline)
        for n, g in enumerate(geo):
            for end in ([g["power"]] if g["power"] else []) + g["extra"] + g["ports"]:
                rows = self._clearance(end, state[n], n, obs, margin, area)
                recs.append(["p", n, end, rows, min(rows, key=lambda r: r[0])])
        # phase B: plugs of different jacks must not overlap (footprints: head, barrel, cable run, or the fixed box); where they do, the plugs
        # involved may take another option, as the build chooses its sides
        items = self._chosen(recs)
        c_cost, c_intr, found = self._collisions(state, items, margin)
        if found:
            if self._resolve(state, recs, {k for c in found for k in (c["jack"], c["with"])}, margin):
                c_cost, c_intr, found = self._collisions(state, self._chosen(recs), margin)
        terms["clearance"] += c_cost
        raw["clearance"] += c_intr
        for c in found:
            if c["na"] != c["nb"]:   # two pedals: either may move
                issues.append((c["na"], self.titles[c["nb"]], c["depth_mm"]))
        collisions = []
        if detail:   # the pair in natural key order, as the build lists it
            for c in found:
                lo, hi = sorted((c["jack"], c["with"]), key=routing.natural_key)
                collisions.append({"jack": lo, "with": hi, "depth_mm": c["depth_mm"]})
            collisions.sort(key=lambda c: (routing.natural_key(c["jack"]), routing.natural_key(c["with"])))
        # phase C: the terms of the final choice
        power_opt, port_opt = {}, {}   # pedal index -> the DC plug of its power jack, (supply index, port id) -> the plug of its port
        for rec in recs:
            if rec[0] == "s":
                _, cid, ia, ib, ea, eb, opa, opb, ca, cb, _, (cost, ka, kb, length, outa, outb) = rec
                terms["clearance"] += ca[ka][0] + cb[kb][0]
                raw["clearance"] += ca[ka][2] + cb[kb][2]
                terms["routing_area"] += w["routing_area"] * (outa + outb)
                terms["signal"] += w["signal"] * length
                raw["signal"] += length
                raw["routing_area"] += outa + outb
                sig_lengths[cid] = length
                if detail:
                    outside += [e["jack"] for e, o in ((ea, outa), (eb, outb)) if o]
                note_hits(ea["jack"], ia, opa[ka]["side"], ca[ka][1])
                note_hits(eb["jack"], ib, opb[kb]["side"], cb[kb][1])
            else:
                _, n, end, _, (_, cost, o, hits, intr, _, _) = rec
                terms["clearance"] += cost
                raw["clearance"] += intr
                note_hits(end["jack"], n, o["side"], hits)
                if end is geo[n]["power"]:
                    power_opt[n] = o
                elif "port" in end:
                    port_opt[(n, end["port"])] = o
        for port, members, under, style in self.wiring:
            prev, lead = port, 0.0
            if isinstance(port, dict):   # a port of an on-board supply: where the candidate puts it (a plug pointing down: under the board)
                po = port_opt.get((port["inst"], port["port"]))
                off = geo[port["inst"]]["port_pt"].get(port["port"]) if po is None else (po["exit"] if po["down"] else po["measure"])
                prev = (off[0] + state[port["inst"]][0], off[1] + state[port["inst"]][1]) if off else None
                if po is not None and po["down"]:
                    under, lead = True, po["measure_mm"]
            for n in members:
                po = power_opt.get(n)   # the DC plug the candidate puts on pedal n: its cable starts / ends at the plug's measure point,
                dn = po is not None and po["down"]   # or under the board at the bend point of a plug pointing down
                m = None if po is None else (po["exit"] if dn else po["measure"])
                here = (m[0] + state[n][0], m[1] + state[n][1]) if m else None
                if prev is not None and here is not None:
                    raw["power"] += power.hop_estimate(prev, here, under, holes, pw_cfg, pw_near, dst_under=dn) + lead + (po["measure_mm"] if dn else 0.0)
                if here is not None and style != routing.FORKED:   # forked: every cable starts at the port
                    prev, under, lead = here, dn, (po["measure_mm"] if dn else 0.0)
        terms["power"] = w["power"] * raw["power"]
        # footswitch spacing
        if self.fs_known:
            pts = [(n, g2[0] + state[n][0], g2[1] + state[n][1], g2[2], g2[3]) for n, g in enumerate(geo) for g2 in g["fs"]]
            lim, comfort = self.fs_limit, self.fs_comfort
            for i, p in enumerate(pts):
                for q in pts[i + 1:]:
                    if p[0] == q[0]:
                        continue
                    d = math.hypot(p[1] - q[1], p[2] - q[2])
                    if d >= comfort and (lim is None or d >= lim):
                        continue
                    fac = footswitches.pair_priority(self.fs_priority, p[3], q[3])
                    crowd = footswitches.crowding(d, fac, comfort)
                    raw["footswitch"] += crowd
                    terms["footswitch"] += w["footswitch"] * crowd
                    if d < 0.6 * comfort:   # the closest pairs: repair moves of a few mm (CROWD_STEP_MM at most)
                        issues.append((p[0], self.titles[q[0]], min((comfort - d) / 4, CROWD_STEP_MM)))
                    if lim is not None and d < lim - 1e-6:
                        terms["footswitch"] += fac * (w["footswitch_min"] * (lim - d) + w["footswitch_pair"])
                        fs_close.append({"a": p[4], "b": q[4], "distance_mm": d})
                        issues.append((p[0], self.titles[q[0]], lim - d))
        # io: first input to the right edge, last output to the nearest of left / right / back
        if self.n_ped and self.ids[0] == chain[0] and geo[0]["in"]:
            x = geo[0]["in"][0] + state[0][0]
            raw["io"] += max(0.0, b[2] - x)
        last = self.n_ped - 1
        if self.n_ped and self.ids[last] == chain[-1] and geo[last]["out"]:
            x, y = geo[last]["out"][0] + state[last][0], geo[last]["out"][1] + state[last][1]
            raw["io"] += max(0.0, min(x - b[0], b[2] - x, y - b[1]))
        terms["io"] = w["io"] * raw["io"]
        # flow: right to left
        for n in range(1, self.n_ped):
            raw["flow"] += max(0.0, state[n][0] - state[n - 1][0])
        terms["flow"] = w["flow"] * raw["flow"]
        # accessibility
        mid = (b[1] + b[3]) / 2
        for n, rule in enumerate(self.access):
            if not rule:
                continue
            fs = geo[n]["fs"]
            y = (sum(f[1] for f in fs) / len(fs) if fs else 0.0) + state[n][1]
            d = {"front": b[3] - y, "back": y - b[1], "avoid_front": max(0.0, y - mid)}.get(rule["want"], 0.0)
            raw["access"] += max(0.0, d) * rule["weight"]
        terms["access"] = w["access"] * raw["access"]
        # rotation preference
        for n, st in enumerate(state):
            if st[2] == 0:
                continue
            used = any(state[k][2] == st[2] for k in range(len(state)) if k != n)
            terms["rotation"] += w["rotation_used"] if used else w["rotation_new"]
            raw["rotation"] += 1
        # move cost
        for st, own in zip(state, self.owner):
            d = math.hypot(st[0] - own[0], st[1] - own[1])
            raw["move"] += d
            moved = d > 0.01 or st[2] != own[2]
            terms["move"] += move_factor * (w["move"] * d + (w["move_pedal"] if moved else 0.0)
                                            + (w["rotate_change"] if st[2] != own[2] else 0.0))
        # touching bonus
        tol = design.TOL_MM
        for i in range(len(feet)):
            fi = feet[i]
            for k in range(i + 1, len(feet)):
                fk = feet[k]
                gx = max(fi[0], fk[0]) - min(fi[2], fk[2])     # > 0: gap along x
                gy = max(fi[1], fk[1]) - min(fi[3], fk[3])
                if -tol <= gx <= TOUCH_GAP_MM and gy < 0:
                    raw["touch"] += -gy
                elif -tol <= gy <= TOUCH_GAP_MM and gx < 0:
                    raw["touch"] += -gx
        terms["touch"] = -w["touch"] * raw["touch"]
        total = sum(terms.values())
        if not detail:
            return total, issues
        return total, {"terms": {k: (raw[k], terms[k]) for k in terms}, "blocked": blocked, "collisions": collisions, "plugs": {k: {"side": o["side"], "type": o.get("type"), "down": o["down"]} for k, _, o in self._chosen(recs)},
                       "outside": outside,
                       "fs_close": fs_close, "signal": sig_lengths, "issues": issues,
                       "fs_known": self.fs_known, "fs_limit": self.fs_limit}

    # --- output -----------------------------------------------------------------------------------
    def items_for(self, state, snap=True):
        """The owner's items with the chain pedals and on-board supplies moved to `state` (design.move; snapped to whole px)."""
        by_id = {self.mitem[p]["id"]: n for n, p in enumerate(self.ids)}
        out = []
        for it in self.items:
            n = by_id.get(it["id"])
            if n is None:
                out.append(it)
            else:
                st = state[n]
                out.append(design.move(it, st[0], st[1], st[2], snap=snap))
        return out

    def snapped(self, state, move_factor=1.0):
        """The state with every moved pedal on whole Pedal Playground px (as the site stores positions; unchanged
        pedals stay put): per pedal the feasible rounding (floor/ceil of left and top) with the lowest score, so a
        footswitch pair or a plug right at its limit stays clear; if that paints a later pedal into a corner, the
        nearest feasible rounding per pedal (shifts of at most half a px each stay within design.TOL_MM between
        touching pedals); None if no rounding is feasible."""
        return self._snap(state, move_factor, True) or self._snap(state, move_factor, False)

    def _snap(self, state, move_factor, by_score):
        out = list(state)
        for n, st in enumerate(state):
            own = self.owner[n]
            if abs(st[0] - own[0]) < 1e-9 and abs(st[1] - own[1]) < 1e-9 and st[2] == own[2]:
                out[n] = tuple(own)
                continue
            it = self.mitem[self.ids[n]]
            raw = design.move(it, st[0], st[1], st[2], snap=False)
            lx, ty = raw["left_px"], raw["top_px"]
            best = None
            for px, py in sorted({(float(fx), float(fy)) for fx in (math.floor(lx), math.ceil(lx))
                                  for fy in (math.floor(ty), math.ceil(ty))}):
                out[n] = (px_to_mm(px, it["scale"]) + it["w_mm"] / 2, px_to_mm(py, it["scale"]) + it["h_mm"] / 2, st[2])
                if self.feasible_one(out, n, tol=design.TOL_MM):
                    sc = self.score(out, move_factor=move_factor)[0] if by_score else abs(px - lx) + abs(py - ty)
                    if best is None or sc < best[0]:
                        best = (sc, out[n])
            if best is None:
                return None
            out[n] = best[1]
        return out


# --- search ---------------------------------------------------------------------------------------
def level_settings(model, level, max_move_mm="level"):
    if level not in LEVELS:
        raise ValueError(f"max_change must be one of {', '.join(LEVELS)}, got {level!r}")
    lv = dict(LEVELS[level])
    if max_move_mm != "level":
        lv["max_move_mm"] = None if max_move_mm is None else float(max_move_mm)
    return lv


def search(model, level="fix", seed=1, iterations=None, restarts=None, max_move_mm="level", time_limit_s=None,
           log=None):
    """Simulated annealing from the owner's layout (or a shuffled start for `free`) plus a greedy polish, per
    restart (seeds seed, seed+1, ...). Deterministic for a given seed and iteration budget (`time_limit_s` is only
    a safety cap). Returns [(score, state)] of the distinct, snapped, feasible results, best first, including the
    owner's layout itself (score of the start) so callers can compare."""
    lv = level_settings(model, level, max_move_mm)
    model.max_move = lv["max_move_mm"]
    try:
        model.overlap_tol = 1e-6
        return _search(model, lv, seed, iterations, restarts, time_limit_s, log)
    finally:
        model.overlap_tol = design.TOL_MM


def _search(model, lv, seed, iterations, restarts, time_limit_s, log):
    iterations = int(iterations or lv["iterations"])
    restarts = int(restarts or lv["restarts"])
    mf = lv["move_factor"]
    t_end = time.monotonic() + time_limit_s if time_limit_s else None
    movable = [n for n, p in enumerate(model.ids) if p not in model.pins]
    owner = [tuple(s) for s in model.owner]
    results = []
    for r in range(restarts):
        rng = random.Random(seed + r)
        state = list(owner)
        if lv.get("random_start"):
            state = shuffle_start(model, state, rng, movable)
        cur, issues = model.score(state, move_factor=mf)
        best, best_state = cur, list(state)
        temps = []
        for _ in range(30):   # starting temperature: typical score change of a random move
            cand = propose(model, state, rng, lv, lv["sigma"][0], issues, movable)
            if cand is not None:
                temps.append(abs(model.score(cand, move_factor=mf)[0] - cur))
        temps = sorted(t for t in temps if t > 0)
        t0 = temps[len(temps) // 2] if temps else 10.0
        t1 = max(t0 / 1000.0, 0.01)
        s0, s1 = lv["sigma"]
        for it in range(iterations):
            if t_end and time.monotonic() > t_end:
                break
            frac = it / max(1, iterations - 1)
            temp = t0 * (t1 / t0) ** frac
            sigma = s0 * (s1 / s0) ** frac
            cand = propose(model, state, rng, lv, sigma, issues, movable)
            if cand is None:
                continue
            sc, iss = model.score(cand, move_factor=mf)
            if sc <= cur or rng.random() < math.exp(-(sc - cur) / temp):
                state, cur, issues = cand, sc, iss
                if sc < best:
                    best, best_state = sc, list(cand)
        state = model.snapped(polish(model, best_state, mf), mf)
        if state is None or not model.feasible(state):
            state = model.snapped(best_state, mf)
            if state is None or not model.feasible(state):
                if log:
                    log(f"  restart {r + 1}/{restarts} (seed {seed + r}): no feasible snapped result")
                continue
        sc = model.score(state, move_factor=mf)[0]
        results.append((sc, state))
        if log:
            log(f"  restart {r + 1}/{restarts} (seed {seed + r}): score {sc:.1f}")
    start = model.score(owner, move_factor=mf)[0]
    out = [(start, owner)]
    for sc, st in sorted(results, key=lambda x: x[0]):
        if all(max(max(abs(a[0] - b[0]), abs(a[1] - b[1])) for a, b in zip(st, o)) > 2.0 or
               any(a[2] != b[2] for a, b in zip(st, o)) for _, o in out):
            out.append((sc, st))
    return sorted(out, key=lambda x: x[0])


def propose(model, state, rng, lv, sigma, issues, movable):
    """A random feasible neighbour of `state` (None if the drawn move is infeasible)."""
    if not movable:
        return None
    cand = list(state)
    kinds = ["shift", "shift", "slide", "reset"] + (["repair", "repair"] if issues else []) \
        + (["swap"] if lv["swap"] and len(movable) > 1 else []) + (["rotate"] if lv["rotate"] else [])
    kind = rng.choice(kinds)
    touched = []
    if kind == "repair":
        n, title, depth = rng.choice(issues)
        if rng.random() < 0.5:   # move the obstacle instead, when it is a movable pedal
            k = next((k for k, t in enumerate(model.titles) if t == title and k in movable), None)
            n = k if k is not None else n
        if n not in movable:
            return None
        ang = rng.choice((0, 90, 180, 270))
        step = depth + float(model.cfg["clearance_margin_mm"]) + rng.random() * 2
        dx, dy = {0: (step, 0), 90: (0, step), 180: (-step, 0), 270: (0, -step)}[ang]
        cand[n] = (state[n][0] + dx, state[n][1] + dy, state[n][2])
        touched = [n]
    elif kind == "shift":
        n = rng.choice(movable)
        cand[n] = (state[n][0] + rng.gauss(0, sigma), state[n][1] + rng.gauss(0, sigma), state[n][2])
        touched = [n]
    elif kind == "slide":
        n = rng.choice(movable)
        axis = rng.choice(((1, 0), (-1, 0), (0, 1), (0, -1)))
        d = free_distance(model, state, n, axis)
        if d <= 0.05:
            return None
        d = min(d, sigma * 4) * (1.0 if rng.random() < 0.5 else rng.random())
        cand[n] = (state[n][0] + axis[0] * d, state[n][1] + axis[1] * d, state[n][2])
        touched = [n]
    elif kind == "swap":   # exchange places: same centre x, front edges aligned (pedals in a row share the front)
        n, k = rng.sample(movable, 2)
        fn, fk = model.footprint(state[n], n), model.footprint(state[k], k)
        cand[n] = (state[k][0], fk[3] - (fn[3] - state[n][1]), state[n][2])
        cand[k] = (state[n][0], fn[3] - (fk[3] - state[k][1]), state[k][2])
        touched = [n, k]
    elif kind == "reset":   # back to the owner's position and rotation
        moved = [n for n in movable if tuple(state[n]) != tuple(model.owner[n])]
        if not moved:
            return None
        n = rng.choice(moved)
        cand[n] = tuple(model.owner[n])
        touched = [n]
    else:   # rotate: angles other pedals already use first
        n = rng.choice(movable)
        others = [r for r in model.allowed[n] if r != state[n][2]]
        if not others:
            return None
        used = [r for r in others if any(state[k][2] == r for k in range(len(state)) if k != n)]
        r = rng.choice(used if used and rng.random() < 0.7 else others)
        cand[n] = (state[n][0], state[n][1], r)
        touched = [n]
    feet = [model.footprint(st, k) for k, st in enumerate(cand)]
    return cand if all(model.feasible_one(cand, n, feet) for n in touched) else None


def free_distance(model, state, n, axis):
    """How far pedal n can slide along `axis` before it touches another item or the board edge (mm)."""
    f = model.footprint(state[n], n)
    b, m = model.board, float(model.cfg["board_margin_mm"])
    dist = {(1, 0): b[2] - m - f[2], (-1, 0): f[0] - (b[0] + m), (0, 1): b[3] - m - f[3], (0, -1): f[1] - (b[1] + m)}[axis]
    others = [model.footprint(st, k) for k, st in enumerate(state) if k != n] + [o for _, o in model.fixed_feet]
    for o in others:
        if axis[0]:
            if min(f[3], o[3]) - max(f[1], o[1]) <= design.TOL_MM:
                continue
            gap = o[0] - f[2] if axis[0] > 0 else f[0] - o[2]
        else:
            if min(f[2], o[2]) - max(f[0], o[0]) <= design.TOL_MM:
                continue
            gap = o[1] - f[3] if axis[1] > 0 else f[1] - o[3]
        if gap >= -design.TOL_MM:
            dist = min(dist, max(0.0, gap))
    return max(0.0, dist)


def polish(model, state, move_factor=1.0):
    """Greedy: per pedal, steps of 4, 2, 1 and 0.5 mm along x and y while the score improves."""
    state = list(state)
    cur = model.score(state, move_factor=move_factor)[0]
    movable = [n for n, p in enumerate(model.ids) if p not in model.pins]
    for n in movable:   # back to the owner's position where that is not worse
        if tuple(state[n]) != tuple(model.owner[n]):
            cand = list(state)
            cand[n] = tuple(model.owner[n])
            if model.feasible_one(cand, n):
                sc = model.score(cand, move_factor=move_factor)[0]
                if sc <= cur + 1e-6:
                    state, cur = cand, sc
    for step in (4.0, 2.0, 1.0, 0.5):
        improved = True
        while improved:
            improved = False
            for n in movable:
                for dx, dy in ((step, 0), (-step, 0), (0, step), (0, -step)):
                    cand = list(state)
                    cand[n] = (state[n][0] + dx, state[n][1] + dy, state[n][2])
                    if not model.feasible_one(cand, n):
                        continue
                    sc = model.score(cand, move_factor=move_factor)[0]
                    if sc < cur - 1e-6:
                        state, cur, improved = cand, sc, True
    return state


def shuffle_start(model, state, rng, movable):
    """A random feasible start for the `free` level: many random swaps and rotations of the owner's layout."""
    lv = {"swap": True, "rotate": True}
    for _ in range(400):
        cand = propose(model, state, rng, lv, 60.0, [], movable)
        if cand is not None:
            state = cand
    return state
