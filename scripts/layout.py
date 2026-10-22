"""Pedal positions: candidate model, hard constraints, surrogate score and search (all mm). Pure: no files, no GUI.

A candidate is a centre (cx, cy) and a rotation (0/90/270, never 180 unless the owner's layout has it) per chain
pedal placed in the owner's layout; the board, supplies (under the board), other items and the chain order are
fixed. Per pedal and allowed rotation, everything that moves with it is precomputed relative to its centre:
footprint half-sizes, plug options (signal: both exit sides of a right-angle plug, power: the DC plug, extra jacks:
the fixed box), measure and exit points, footswitch points. Moving a pedal translates cached rectangles.

Hard constraints (a candidate that breaks one is never scored): inside the board shrunk by `board_margin_mm`
(never overhang), no overlap beyond design.TOL_MM between pedals (touching allowed; `min_gap_mm` adds a gap), pins
fixed, rotation within the allowed set, at most `max_move_mm` from the owner's position.

Surrogate score (lower is better, "mm-equivalent"), weights in project.json `layout.weights`:
  clearance      per plug and obstacle: 50 / mm real penetration (smaller overlap side of the plug parts: how far
                 to move to clear) + clearance_margin 10 / mm of the extra penetration when the parts are grown by
                 `clearance_margin_mm` (2: plug sizes are estimates) + clearance_hit 100 per plug and obstacle that
                 really overlap (no margin; reported as "blocked" with the build's depth, design.part_depth). Signal ends pick the exit side with the lowest clearance +
                 cable cost, power plugs the side with the lowest clearance cost (as the router does).
  routing_area   200 per signal plug exit outside the routing area (in front of the lowest pedals, beyond the margin)
  signal         1 / mm patch cable: per hop measure_a + measure_b + octile distance between the cable exits (the
                 router's 8-connected path length without obstacles)
  power          0.1 / mm DC cable: Manhattan between half-depth measure points along each daisy chain (jacks.check)
                 for a fixed wiring (the search keeps it; finalists get their own wiring from power.assign)
  footswitch     20 / mm below the minimum distance + footswitch_pair 100 per pair, both times the pair's priority
                 (footswitches.priority per switch type: bypass 1.0, boost 0.8, tap 0.8, function 0.5; a pair weighs
                 the larger of its two); no footswitch data -> 0
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

import design
import footswitches
import routing
from common import px_to_mm

TOUCH_GAP_MM = 1.0
SQRT2_1 = math.sqrt(2) - 1

WEIGHTS = {"clearance": 50.0, "clearance_margin": 10.0, "clearance_hit": 100.0, "routing_area": 200.0, "signal": 1.0, "power": 0.1,
           "footswitch": 20.0, "footswitch_pair": 100.0, "io": 1.0, "flow": 0.1, "access": 1.0,
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
                  "iterations": 2500, "restarts": 6},
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


def _shift(r, dx, dy):
    return (r[0] + dx, r[1] + dy, r[2] + dx, r[3] + dy)


def _bbox(rects):
    return (min(r[0] for r in rects), min(r[1] for r in rects), max(r[2] for r in rects), max(r[3] for r in rects))


class Model:
    """Everything the score needs about one project and the owner's layout.

    Built from a parsed layout (`items`), the project dict and catalog data; `wiring`: [(port point or None,
    [pedal ids])] daisy chains for the power term (None: the project's own wiring)."""

    def __init__(self, project, items, cat_pedals, cat_supplies, jacks_data, fs_data, cable_types, wiring=None,
                 fs_limit=None):
        import jacks
        self.project, self.items, self.cat_pedals = project, items, cat_pedals
        self.cfg = settings(project)
        self.w = self.cfg["weights"]
        chain = [p for p in project.get("signal_chain", []) if p in cat_pedals]
        insts = [{"inst": i, "sup": cat_supplies[i["supply"]], "rows": [{"port": o["port"], "pedals": o.get("pedals", [])}
                                                                         for o in i.get("outputs", [])]}
                 for i in (project.get("power") or {}).get("supplies", []) if i["supply"] in cat_supplies]
        jset = project.get("jacks", {})
        lay = jacks.layout_from_items(items, chain, insts, cat_pedals, cat_supplies, jset, [], [])
        if lay["board"] is None:
            raise ValueError("the layout has no pedalboard item")
        self.board = design.footprint(lay["board"])
        self.placed = lay["placed"]
        self.inst_item, self.insts = lay["inst_item"], insts
        self.ids = [p for p in chain if p in self.placed]          # movable pedals, chain order
        self.index = {p: n for n, p in enumerate(self.ids)}
        moving = {self.placed[p]["id"] for p in self.ids}
        self.fixed = [o for o in lay["obstacles"] if o["id"] not in moving]
        self.fixed_feet = [(o["title"], design.footprint(o)) for o in self.fixed]
        self.jacks_data = jacks.usable(jacks_data)
        self.fs_data = footswitches.usable(fs_data or {})
        self.cable_types = cable_types
        self.rcfg = routing.settings(project, cable_types)
        self.outward = float(jset.get("clearance", {}).get("outward_mm", jacks.CLEARANCE_DEFAULT["outward_mm"]))
        self.side = float(jset.get("clearance", {}).get("side_mm", jacks.CLEARANCE_DEFAULT["side_mm"]))
        self.p_out = float(jset.get("power_clearance", {}).get("outward_mm", jacks.POWER_CLEARANCE_DEFAULT["outward_mm"]))
        self.p_side = float(jset.get("power_clearance", {}).get("side_mm", jacks.POWER_CLEARANCE_DEFAULT["side_mm"]))
        self.extra_used = jset.get("extra_used", {})
        ptype_id = (project.get("cables") or {}).get("power_type")
        self.ptype = cable_types.get(ptype_id) if ptype_id else None
        self.p_depth = float(self.ptype["plug"]["head_depth_mm"]) if self.ptype else self.p_out
        self.owner = [self._state_of(self.placed[p]) for p in self.ids]
        self.names = {p: cat_pedals[p].get("name", p) for p in self.ids}
        self.titles = [self.placed[p]["title"] for p in self.ids]
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
            raise ValueError(f"layout.pins: not a placed chain pedal: {', '.join(sorted(unknown_pins))}")
        # footswitches
        self.fs_known = any(self.fs_data.get(p) for p in self.ids)
        self.fs_limit = fs_limit
        if self.fs_limit is None:
            setting = (project.get("footswitches") or {}).get("min_distance_mm", "auto")
            if setting == "auto":
                prs = footswitches.pairs(footswitches.points(self.placed, self.fs_data))
                self.fs_limit = prs[0]["distance_mm"] if prs else None
            else:
                self.fs_limit = float(setting)
        self.fs_priority = footswitches.priorities(project)
        self.access = [access_rule({**cat_pedals[p], "id": p}, [f["type"] for f in self.fs_data.get(p) or []],
                                   self.cfg["access"]) for p in self.ids]
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
        it = self.placed[pid]
        tmp = {**it, "rot": rot, "left_mm": -it["w_mm"] / 2, "top_mm": -it["h_mm"] / 2}
        f = design.footprint(tmp)
        have = self.jacks_data.get(pid) or []
        g = {"half": (f[2], f[3]), "ends": {}, "power": None, "extra": [], "fs": [], "in": None, "out": None}
        chain_pos = self.project["signal_chain"].index(pid)
        chain = self.project["signal_chain"]
        over = self.rcfg["overrides"]
        run_given = "exit_run_mm" in (self.project.get("cables") or {})
        for fn, end, hop in (("output", "a", chain_pos + 1), ("input", "b", chain_pos)):
            jk = default_jack(have, fn)
            if jk:
                g["in" if fn == "input" else "out"] = design.jack_point(tmp, jk["x"], jk["y"])
            if not jk or hop < 1 or hop >= len(chain):
                continue
            cid = f"S{hop}"
            tid = routing.cable_type_id(self.project, cid)
            ctype = self.cable_types.get(tid) if tid else None
            run = self.rcfg if run_given or not ctype else {**self.rcfg, "exit_run_mm": float(ctype["diameter_mm"])}
            facing, opts = routing.end_options(tmp, jk, ctype, (over.get(cid) or {}).get(f"exit_{end}"), run, self.outward)
            if ctype is None:
                pt = design.jack_point(tmp, jk["x"], jk["y"])
                for o in opts:
                    o["rects"] = [("box", design.clearance_rect(pt, facing, self.outward, self.side))]
            g["ends"][cid] = {"jack": f"{pid}.{jk['id']}", "facing": facing, "opts": [self._opt(o) for o in opts]}
        jk = default_jack(have, "power")
        if jk:
            pt = design.jack_point(tmp, jk["x"], jk["y"])
            facing = design.jack_facing(tmp, jk["facing"])
            if self.ptype:
                _, opts = routing.end_options(tmp, jk, self.ptype, None, {"exit_run_mm": float(self.ptype["diameter_mm"])}, self.outward)
            else:
                opts = [{"side": None, "rects": [("box", design.clearance_rect(pt, facing, self.p_out, self.p_side))],
                         "exit": pt, "measure_mm": 0.0}]
            g["power"] = {"jack": f"{pid}.{jk['id']}", "facing": facing, "opts": [self._opt(o) for o in opts],
                          "measure": design.stub(pt, facing, self.p_depth / 2)}
        for jid in self.extra_used.get(pid, []):
            jk = _jack_by_id(have, jid)
            if jk:
                pt = design.jack_point(tmp, jk["x"], jk["y"])
                facing = design.jack_facing(tmp, jk["facing"])
                g["extra"].append({"jack": f"{pid}.{jid}", "facing": facing, "opts": [self._opt(
                    {"side": None, "rects": [("box", design.clearance_rect(pt, facing, self.outward, self.side))],
                     "exit": pt, "measure_mm": 0.0})]})
        for fs in self.fs_data.get(pid) or []:
            x, y = design.jack_point(tmp, fs["x"], fs["y"])
            g["fs"].append((x, y, fs["type"], f"{pid}.{fs['id']}"))
        return g

    @staticmethod
    def _opt(o):
        rects = [(part, r) for part, r in o["rects"]]
        return {"side": o["side"], "rects": rects, "bbox": _bbox([r for _, r in rects]) if rects else None,
                "exit": o["exit"], "measure_mm": o.get("measure_mm", 0.0)}

    def set_wiring(self, wiring):
        """Daisy chains for the power term: [(port point or None, [pedal ids])]; None = the project's own wiring."""
        if wiring is None:
            import power
            insts = [{"id": s["inst"]["id"], "supply": s["sup"]["id"]} for s in self.insts]
            _, ports = power.measure_points({}, self.inst_item, insts, self.jacks_data, self.p_depth)
            wiring = [(ports.get((s["inst"]["id"], o["port"])), list(o.get("pedals", [])))
                      for s in self.insts for o in s["inst"].get("outputs", [])]
        self.wiring = [(pt, [self.index[p] for p in pids if p in self.index]) for pt, pids in wiring]

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
    def _clearance(self, end, st, n, feet, margin):
        """(cost, option index, hits, intrusion) of one plug end: the option with the lowest clearance cost."""
        best = None
        for k, o in enumerate(end["opts"]):
            cost, hits, intr = self._opt_clearance(end, o, st, n, feet, margin)
            if best is None or cost < best[0]:
                best = (cost, k, hits, intr)
        return best

    def _opt_clearance(self, end, o, st, n, feet, margin):
        """(cost, hits, intrusion mm) of one plug option. Intrusion per obstacle = the penetration (smaller overlap
        side) of the plug parts grown by `margin`: how far the obstacle must move to clear, smooth for the search.
        A hit = a real overlap without the margin (as the build reports it: deepest part, design.part_depth)."""
        if not o["rects"]:
            return 0.0, [], 0.0
        bb = o["bbox"]
        x, y = st[0], st[1]
        bx0, by0, bx1, by1 = bb[0] + x - margin, bb[1] + y - margin, bb[2] + x + margin, bb[3] + y + margin
        tol = design.TOL_MM
        hits, intrusion, cost = [], 0.0, 0.0
        obstacles = [(self.titles[k], f) for k, f in enumerate(feet) if k != n] + self.fixed_feet
        for title, f in obstacles:
            if min(bx1, f[2]) - max(bx0, f[0]) <= tol or min(by1, f[3]) - max(by0, f[1]) <= tol:
                continue
            pen, pen_real, deepest = 0.0, 0.0, None
            for part, r in o["rects"]:
                rr = (r[0] + x, r[1] + y, r[2] + x, r[3] + y)
                ov = design.overlap((rr[0] - margin, rr[1] - margin, rr[2] + margin, rr[3] + margin), f)
                if not ov:
                    continue
                pen = max(pen, min(ov))
                real = design.overlap(rr, f) if margin else ov
                if real:
                    pen_real = max(pen_real, min(real))
                    d = design.part_depth(part, end["facing"], o["side"], real)
                    if deepest is None or d > deepest[1]:
                        deepest = (part, d)
            intrusion += pen
            cost += self.w["clearance"] * pen_real + self.w["clearance_margin"] * (pen - pen_real)
            if deepest:
                hits.append((title, deepest[0], deepest[1]))
        cost += self.w["clearance_hit"] * len(hits)
        return cost, hits, intrusion

    def score(self, state, margin=None, detail=False, move_factor=1.0):
        """Weighted surrogate score of a candidate (lower is better); with `detail` also the raw terms and the
        findings: (total, {"terms": {name: (raw, weighted)}, "blocked": [...], "fs_close": [...], ...})."""
        w = self.w
        margin = float(self.cfg["clearance_margin_mm"]) if margin is None else margin
        feet = [self.footprint(st, n) for n, st in enumerate(state)]
        geo = [self._geom[(n, st[2])] for n, st in enumerate(state)]
        b = self.board
        em = self.rcfg["edge_margin_mm"]
        front_y = min(b[3], max(f[3] for f in feet)) if feet else b[3]
        area = (b[0] - em, b[1] - em, b[2] + em, front_y)
        terms = dict.fromkeys(("clearance", "routing_area", "signal", "power", "footswitch", "io", "flow", "access",
                               "rotation", "move", "touch"), 0.0)
        raw = dict.fromkeys(terms, 0.0)
        blocked, outside, fs_close, sig_lengths, issues = [], [], [], {}, []

        def note_hits(jack, n, side, hits):
            for title, part, d in hits:
                blocked.append({"jack": jack, "obstacle": title, "part": part, "depth_mm": d, "side": side})
                issues.append((n, title, d))

        # signal cables: clearance of both ends + length, best side combination
        chain = self.project["signal_chain"]
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
            ca = [self._opt_clearance(ea, o, sa, ia, feet, margin) for o in ea["opts"]]
            cb = [self._opt_clearance(eb, o, sb, ib, feet, margin) for o in eb["opts"]]
            best = None
            for ka, oa in enumerate(ea["opts"]):
                pa = (oa["exit"][0] + sa[0], oa["exit"][1] + sa[1])
                outa = not (area[0] <= pa[0] < area[2] and area[1] <= pa[1] < area[3])
                for kb, ob in enumerate(eb["opts"]):
                    pb = (ob["exit"][0] + sb[0], ob["exit"][1] + sb[1])
                    outb = not (area[0] <= pb[0] < area[2] and area[1] <= pb[1] < area[3])
                    length = oa["measure_mm"] + ob["measure_mm"] + octile(pa, pb)
                    cost = ca[ka][0] + cb[kb][0] + w["routing_area"] * (outa + outb) + w["signal"] * length
                    if best is None or cost < best[0]:
                        best = (cost, ka, kb, length, outa, outb)
            cost, ka, kb, length, outa, outb = best
            terms["clearance"] += ca[ka][0] + cb[kb][0]
            raw["clearance"] += ca[ka][2] + cb[kb][2]
            terms["routing_area"] += w["routing_area"] * (outa + outb)
            terms["signal"] += w["signal"] * length
            raw["signal"] += length
            raw["routing_area"] += outa + outb
            sig_lengths[cid] = length
            if detail:
                outside += [e["jack"] for e, o in ((ea, outa), (eb, outb)) if o]
            note_hits(ea["jack"], ia, ea["opts"][ka]["side"], ca[ka][1])
            note_hits(eb["jack"], ib, eb["opts"][kb]["side"], cb[kb][1])
        # power plugs and extra jacks: clearance only
        for n, g in enumerate(geo):
            for end in ([g["power"]] if g["power"] else []) + g["extra"]:
                cost, k, hits, intr = self._clearance(end, state[n], n, feet, margin)
                terms["clearance"] += cost
                raw["clearance"] += intr
                note_hits(end["jack"], n, end["opts"][k]["side"], hits)
        # power cable length for the fixed wiring
        for port, members in self.wiring:
            prev = port
            for n in members:
                m = geo[n]["power"]["measure"] if geo[n]["power"] else None
                here = (m[0] + state[n][0], m[1] + state[n][1]) if m else None
                if prev is not None and here is not None:
                    raw["power"] += abs(prev[0] - here[0]) + abs(prev[1] - here[1])
                prev = here if here is not None else prev
        terms["power"] = w["power"] * raw["power"]
        # footswitch spacing
        if self.fs_limit is not None and self.fs_known:
            pts = [(n, g2[0] + state[n][0], g2[1] + state[n][1], g2[2], g2[3]) for n, g in enumerate(geo) for g2 in g["fs"]]
            lim = self.fs_limit
            for i, p in enumerate(pts):
                for q in pts[i + 1:]:
                    if p[0] == q[0]:
                        continue
                    d = math.hypot(p[1] - q[1], p[2] - q[2])
                    if d < lim - 1e-6:
                        fac = footswitches.pair_priority(self.fs_priority, p[3], q[3])
                        terms["footswitch"] += fac * (w["footswitch"] * (lim - d) + w["footswitch_pair"])
                        raw["footswitch"] += lim - d
                        fs_close.append({"a": p[4], "b": q[4], "distance_mm": d})
                        issues.append((p[0], self.titles[q[0]], lim - d))
        # io: first input to the right edge, last output to the nearest of left / right / back
        if self.ids and self.ids[0] == chain[0] and geo[0]["in"]:
            x = geo[0]["in"][0] + state[0][0]
            raw["io"] += max(0.0, b[2] - x)
        last = len(self.ids) - 1
        if self.ids and self.ids[-1] == chain[-1] and geo[last]["out"]:
            x, y = geo[last]["out"][0] + state[last][0], geo[last]["out"][1] + state[last][1]
            raw["io"] += max(0.0, min(x - b[0], b[2] - x, y - b[1]))
        terms["io"] = w["io"] * raw["io"]
        # flow: right to left
        for n in range(1, len(state)):
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
        return total, {"terms": {k: (raw[k], terms[k]) for k in terms}, "blocked": blocked, "outside": outside,
                       "fs_close": fs_close, "signal": sig_lengths, "issues": issues,
                       "fs_known": self.fs_known, "fs_limit": self.fs_limit}

    # --- output -----------------------------------------------------------------------------------
    def items_for(self, state, snap=True):
        """The owner's items with the chain pedals moved to `state` (design.move; snapped to whole px)."""
        by_id = {self.placed[p]["id"]: n for n, p in enumerate(self.ids)}
        out = []
        for it in self.items:
            n = by_id.get(it["id"])
            if n is None:
                out.append(it)
            else:
                st = state[n]
                out.append(design.move(it, st[0], st[1], st[2], snap=snap))
        return out

    def snapped(self, state):
        """The state with every moved pedal on whole Pedal Playground px (as the site stores positions; unchanged
        pedals stay put). Per pedal the nearest px first, then the other roundings, keeping the candidate feasible
        when one of them is; None if no rounding is feasible."""
        out = list(state)
        for n, st in enumerate(state):
            own = self.owner[n]
            if abs(st[0] - own[0]) < 1e-9 and abs(st[1] - own[1]) < 1e-9 and st[2] == own[2]:
                out[n] = tuple(own)
                continue
            it = self.placed[self.ids[n]]
            raw = design.move(it, st[0], st[1], st[2], snap=False)
            lx, ty = raw["left_px"], raw["top_px"]
            opts = sorted({(float(fx), float(fy)) for fx in (math.floor(lx), math.ceil(lx)) for fy in (math.floor(ty), math.ceil(ty))},
                          key=lambda p: (abs(p[0] - lx) + abs(p[1] - ty), p))
            for px, py in opts:
                cx = px_to_mm(px, it["scale"]) + it["w_mm"] / 2
                cy = px_to_mm(py, it["scale"]) + it["h_mm"] / 2
                out[n] = (cx, cy, st[2])
                if self.feasible_one(out, n, tol=design.TOL_MM):
                    break
            else:
                return None
        return out
