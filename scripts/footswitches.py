"""Footswitch data: catalog/footswitches.json (loading, saving, validation) and the spacing check of the build.

catalog/footswitches.json holds, per pedal catalog id, a list of footswitches:

    {"id": "bypass", "label": "Bypass", "x": 0.5, "y": 0.79, "type": "bypass"}

x, y are fractions (0..1) of the Pedal Playground image (origin top-left, unrotated pedal) at the CENTRE of the
switch cap; `type` is one of TYPES: bypass (turns the pedal, or one side of it, on and off), tap (tap tempo), boost
(a boost / extra-gain stomp on the pedal), function (any other switch: octave, hard clipping, preset, multiple/single
delay...).
`[]` = checked: the pedal has no footswitch. A missing id = unknown. Optional: `diameter_mm` (null if unknown).
Written only by scripts/pedal_editor.py; jack positions live in catalog/jacks.json and are never touched here.

Spacing (owner, 2026-10-23: there is no real minimum, it is comfort): switches on DIFFERENT pedals should be as far
apart as the other goals allow. Crowding of a pair = priority x max(0, comfort - d)^2 / comfort (mm; d centre to
centre, comfort = `footswitches.comfort_mm`, default COMFORT_MM; priority per switch type, PRIORITY): the closest
pairs count most, pairs at least `comfort_mm` apart not at all. The layout search minimises the sum; the build
reports it. Optional `footswitches.min_distance_mm` (mm, default none): pairs closer are warnings.

Toppers (a larger, higher cap on a switch: easier to hit, the neighbour less likely to be hit too) are a finishing step
after the layout, per project: `footswitches.toppers` lists "<pedal id>.<switch id>" keys. Spacing model: effective
distance d_eff = d + `topper_bonus_mm` (default TOPPER_BONUS_MM: the height a topper adds, a rough proxy) per topper
on the pair (both switches: 2x); crowding and `min_distance_mm` use d_eff. The layout search ignores toppers (layout.py uses `crowding` on the
plain distances). `suggest_toppers` picks, greedily and after the layout, the few toppers that remove the most
crowding (at most `max_toppers` in all, default MAX_TOPPERS, stopping when the next gain is below `topper_min_gain` x the crowding),
on bypass switches only (TOPPER_TYPES; a tap switch gets one by hand, never a boost one: owner, 2026-11-04).
"""
import json
import math
import os
from pathlib import Path

import design
from common import FOOTSWITCHES_FILE, dumps_per_line

KEY_ORDER = ("id", "label", "x", "y", "type", "diameter_mm")
REQUIRED = ("id", "label", "x", "y", "type")
TYPES = ("bypass", "tap", "boost", "function")
PRIORITY = {"bypass": 1.0, "boost": 0.8, "tap": 0.8, "function": 0.5}   # spacing weight per type (layout search)
COMMAND = "uv run scripts/pedal_editor.py"
DOC = ("Footswitch positions per pedal catalog id. Written ONLY by scripts/pedal_editor.py. x,y are fractions (0..1) of "
       "the Pedal Playground image, origin top-left, in the UNROTATED pedal, at the CENTRE of the switch cap. type: "
       "bypass (turns the pedal, or one side of it, on/off) | tap (tap tempo) | boost (a boost / extra-gain stomp) | "
       "function (any other switch: octave, clipping, preset...). Optional diameter_mm (null if unknown). "
       "[] = checked: the pedal has no footswitch. A missing id = unknown. "
       "No image is stored.")
TOP_PAIRS = 8   # closest pairs shown in the README
COMFORT_MM = 100.0   # pairs at least this far apart are not crowded
# effective distance gained per topper on a pair = the height a topper adds to the switch (owner, 2026-10-28: a rough
# proxy, good enough for now). RockBoard StomPete about 4.5 mm, BigToe about 2.9 mm (retailer listings, unverified).
TOPPER_BONUS_MM = 4.5
MAX_TOPPERS = 5          # default cap per board (owner, 2026-10-28); `footswitches.max_toppers: null` = no cap
TOPPER_MIN_GAIN = 0.02   # a suggested topper must remove at least this share of the board's crowding (2 %: with the
                         # 4.5 mm height bonus one topper removes 2.5-3.5 % on the gig)
TOPPER_TYPES = ("bypass",)  # switch types a topper is suggested for (owner, 2026-11-04: the switches the owner steps on most; never
                            # a boost switch; a tap switch in the middle of the board only by hand, `footswitches.toppers`)


# --- file ---------------------------------------------------------------------------------------
def read_file(path=FOOTSWITCHES_FILE):
    """The whole file as a dict {"_doc", "footswitches"}; a fresh one if it does not exist."""
    p = Path(path)
    if not p.exists():
        return {"_doc": DOC, "footswitches": {}}
    data = json.loads(p.read_text())
    data.setdefault("_doc", DOC)
    data.setdefault("footswitches", {})
    return data


def dumps(data):
    """Compact, diff-friendly JSON: one footswitch per line, ids sorted, `[]` kept."""
    return dumps_per_line(data.get("_doc", DOC), "footswitches", data["footswitches"], KEY_ORDER)


def normalize(fs):
    """Round x/y for storage; keep only the known keys."""
    out = {"id": fs["id"], "label": fs["label"], "x": round(float(fs["x"]), 4), "y": round(float(fs["y"]), 4),
           "type": fs["type"]}
    if "diameter_mm" in fs:
        out["diameter_mm"] = fs["diameter_mm"]
    return out


def save_footswitches(catalog_id, fs_list, path=FOOTSWITCHES_FILE):
    """Replace one pedal's footswitches. [] is stored (verified: no footswitch); None removes the id (unknown).
    Re-reads the file first, so other ids are never lost; the current DOC is always written."""
    data = read_file(path)
    data["_doc"] = DOC
    if fs_list is None:
        data["footswitches"].pop(catalog_id, None)
    else:
        data["footswitches"][catalog_id] = [normalize(f) for f in fs_list]
    tmp = Path(str(path) + ".tmp")
    tmp.write_text(dumps(data))
    os.replace(tmp, path)


def _ok(f):
    return (isinstance(f, dict) and all(k in f for k in REQUIRED) and f["type"] in TYPES
            and all(isinstance(f[k], (int, float)) and not isinstance(f[k], bool) for k in ("x", "y")))


def usable(fs_data):
    """Only well-formed footswitches (the rest are reported by validate_file); `[]` is kept (no footswitch)."""
    return {cid: [f for f in fs if _ok(f)] for cid, fs in (fs_data or {}).items() if isinstance(fs, list)}


def validate_file(data, pedals, supplies):
    """{catalog id: [problems]} for every id with a problem (unknown ids and supplies included)."""
    problems = {}
    for cid, fs in data.get("footswitches", {}).items():
        errs = []
        if cid in supplies:
            errs.append("power supplies have no footswitches")
        elif cid not in pedals:
            errs.append("not a pedal id in the catalog")
        if not isinstance(fs, list):
            problems[cid] = errs + ["must be a list ([] = no footswitch)"]
            continue
        seen = set()
        for f in fs:
            tag = f.get("id", "?") if isinstance(f, dict) else "?"
            miss = [k for k in REQUIRED if not isinstance(f, dict) or k not in f]
            if miss:
                errs.append(f"footswitch {tag}: missing {', '.join(miss)}")
                continue
            if tag in seen:
                errs.append(f"duplicate footswitch id '{tag}'")
            seen.add(tag)
            if not all(isinstance(f[k], (int, float)) and not isinstance(f[k], bool) and 0 <= f[k] <= 1 for k in ("x", "y")):
                errs.append(f"footswitch {tag}: x,y must be numbers in 0..1")
            if f["type"] not in TYPES:
                errs.append(f"footswitch {tag}: type must be one of {', '.join(TYPES)}, got {f['type']!r}")
            d = f.get("diameter_mm")
            if d is not None and not (isinstance(d, (int, float)) and not isinstance(d, bool) and d > 0):
                errs.append(f"footswitch {tag}: diameter_mm must be a positive number or null")
        if errs:
            problems[cid] = errs
    return problems


def priorities(project):
    """Spacing priority per switch type: PRIORITY + project `footswitches.priority`."""
    return {**PRIORITY, **((project.get("footswitches") or {}).get("priority") or {})}


def spacing_settings(project):
    """(min_distance_mm or None, comfort_mm, [problems], [notes]) from project `footswitches` (problems are errors,
    notes warnings)."""
    cfg = project.get("footswitches") or {}
    problems = []
    num = lambda v: isinstance(v, (int, float)) and not isinstance(v, bool) and v > 0
    lim = cfg.get("min_distance_mm")
    notes = []
    if lim == "auto":
        notes.append("footswitches.min_distance_mm \"auto\" is no longer used (spacing is a comfort term, no minimum): remove it")
        lim = None
    if lim is not None and not num(lim):
        problems.append(f"footswitches.min_distance_mm must be a positive number (mm) or null (no minimum), got {lim!r}")
        lim = None
    comfort = cfg.get("comfort_mm", COMFORT_MM)
    if not num(comfort):
        problems.append(f"footswitches.comfort_mm must be a positive number (mm), got {comfort!r}")
        comfort = COMFORT_MM
    return (None if lim is None else float(lim)), float(comfort), problems, notes


def crowding(distance_mm, priority, comfort_mm):
    """Crowding of one pair (mm): priority x max(0, comfort - d)^2 / comfort."""
    gap = max(0.0, comfort_mm - distance_mm)
    return priority * gap * gap / comfort_mm


def topper_settings(project, switch_keys, no_data=()):
    """(settings, problems, notes) of the project's toppers. settings = {toppers: [keys], bonus_mm, max_toppers (int or
    None), min_gain}. `switch_keys` = every "<pedal id>.<switch id>" of the project's chain pedals, `no_data` = chain
    pedal ids without footswitch data. Problems are errors (unknown pedal or switch, bad numbers); notes are warnings
    (a topper listed twice: kept once; a topper on a chain pedal whose footswitch data is missing: ignored; more
    toppers than `max_toppers`)."""
    cfg = project.get("footswitches") or {}
    problems, notes = [], []
    num = lambda v: isinstance(v, (int, float)) and not isinstance(v, bool)
    toppers = cfg.get("toppers", [])
    if not isinstance(toppers, list) or not all(isinstance(t, str) for t in toppers):
        problems.append(f"footswitches.toppers must be a list of \"<pedal id>.<switch id>\" strings, got {toppers!r}")
        toppers = []
    seen = set()
    keep = []
    for t in toppers:
        if t in seen:
            notes.append(f"footswitches.toppers: {t} is listed twice (counted once)")
            continue
        seen.add(t)
        if t in switch_keys:
            keep.append(t)
        elif t.split(".", 1)[0] in no_data:
            notes.append(f"footswitches.toppers: {t} ignored, the footswitch data of {t.split('.', 1)[0]} is missing")
        else:
            problems.append(f"footswitches.toppers: {t} is not a footswitch of a pedal in the signal chain")
    bonus = cfg.get("topper_bonus_mm", TOPPER_BONUS_MM)
    if not num(bonus) or bonus < 0:
        problems.append(f"footswitches.topper_bonus_mm must be a number >= 0 (mm), got {bonus!r}")
        bonus = TOPPER_BONUS_MM
    cap = cfg.get("max_toppers", MAX_TOPPERS)
    if cap is not None and (not isinstance(cap, int) or isinstance(cap, bool) or cap < 0):
        problems.append(f"footswitches.max_toppers must be an integer >= 0 or null (no cap), got {cap!r}")
        cap = MAX_TOPPERS
    gain = cfg.get("topper_min_gain", TOPPER_MIN_GAIN)
    if not num(gain) or not 0 <= gain <= 1:
        problems.append(f"footswitches.topper_min_gain must be a number in 0..1, got {gain!r}")
        gain = TOPPER_MIN_GAIN
    if cap is not None and len(keep) > cap:
        notes.append(f"footswitches: {len(keep)} toppers are listed, more than max_toppers ({cap})")
    return {"toppers": keep, "bonus_mm": float(bonus), "max_toppers": cap, "min_gain": float(gain)}, problems, notes


def pair_distance(distance_mm, n_toppers, bonus_mm, step_mm=0.0):
    """d_eff = d + bonus per topper on the pair (0, 1 or 2) + the pair's height step (`step_mm`, 0 without heights)."""
    return distance_mm + n_toppers * bonus_mm + step_mm


def effective_distance(distance_mm, n_toppers, bonus_mm):
    """d_eff = d + bonus per topper on the pair (0, 1 or 2); no height step (`pair_distance` has one)."""
    return pair_distance(distance_mm, n_toppers, bonus_mm)


# --- heights: step and reach (plan docs/plans/switch-height.md) ----------------------------------
# All estimates (owner decisions 2026-11-13, the plan's recommended defaults).
HEIGHT_DEFAULTS = {"heights": True,          # False = the flat model (no step, no shadow)
                   "height_gain": 0.5,       # mm of effective distance per mm of height step (half: a step protects one way only)
                   "height_cap_mm": 10.0,    # the step counts up to this
                   "deck_rise_mm": 0.0,      # the deck's back edge above its front edge (0 = flat)
                   "foot_width_mm": 80.0,    # width of the sole strip in front of a switch
                   "foot_length_mm": 190.0,  # how far forward the sole reaches (ball to heel)
                   "foot_pitch_deg": 5.0,    # the sole rises toward the front by tan(pitch) mm per mm
                   "reach_weight": 1.0,      # topper suggestions: one mm of shadow (x priority) against crowding
                   "max_shadow_mm": None}    # a larger shadow is a finding (None = no limit)


def height_settings(project):
    """(settings, problems) of the height model from project `footswitches` (keys of HEIGHT_DEFAULTS). A bad value is a
    problem (an error for the caller) and falls back to its default; unknown keys are ignored."""
    cfg = project.get("footswitches") or {}
    out, problems = dict(HEIGHT_DEFAULTS), []
    num = lambda v: isinstance(v, (int, float)) and not isinstance(v, bool)
    ranges = {"height_gain": (0, 1), "height_cap_mm": (0, None), "deck_rise_mm": (0, None), "foot_width_mm": (0, None),
              "foot_length_mm": (0, None), "foot_pitch_deg": (0, 45), "reach_weight": (0, None)}
    for k, v in cfg.items():
        if k not in HEIGHT_DEFAULTS:
            continue
        if k == "heights":
            if isinstance(v, bool):
                out[k] = v
            else:
                problems.append(f"footswitches.heights must be true or false, got {v!r}")
        elif k == "max_shadow_mm":
            if v is None or (num(v) and v >= 0):
                out[k] = None if v is None else float(v)
            else:
                problems.append(f"footswitches.max_shadow_mm must be a number >= 0 (mm) or null (no limit), got {v!r}")
        else:
            lo, hi = ranges[k]
            if num(v) and v >= lo and (hi is None or v <= hi):
                out[k] = float(v)
            else:
                span = f"in {lo}..{hi}" if hi is not None else f">= {lo}"
                problems.append(f"footswitches.{k} must be a number {span}, got {v!r}")
    return out, problems


def step_mm(h_a, h_b, gain, cap_mm):
    """Height step of a pair counted as distance: gain x min(|Ha - Hb|, cap); 0 when a height is unknown (None)."""
    if h_a is None or h_b is None:
        return 0.0
    return gain * min(abs(h_a - h_b), cap_mm)


def switch_heights(pts, cat_pedals, toppers, topper_mm, board_rect=None, deck_rise_mm=0.0):
    """{switch key: (H, H_t)}: H = the pedal's `height_mm` (the switch top) + the deck's rise at the switch
    (deck_rise_mm x (y_front - y) / board depth, y_front = board_rect[3]; 0 on a flat deck), H_t = H + topper_mm when the
    key is in `toppers`. An unknown height gives (None, None)."""
    out = {}
    rise = 0.0
    for p in pts:
        h = (cat_pedals.get(p["cid"]) or {}).get("height_mm")
        if h is None:
            out[p["key"]] = (None, None)
            continue
        if deck_rise_mm and board_rect and board_rect[3] > board_rect[1]:
            rise = deck_rise_mm * (board_rect[3] - p["y"]) / (board_rect[3] - board_rect[1])
        else:
            rise = 0.0
        out[p["key"]] = (h + rise, h + rise + (topper_mm if p["key"] in toppers else 0.0))
    return out


def shadow_map(pts, h, cfg):
    """{key: (shadow_mm, shadowed_by key or None)} for a plain {key: height or None} map. A switch q on ANOTHER pedal with
    |x_q - x_s| <= foot_width/2 and 0 < y_q - y_s <= foot_length (y grows toward the front) shades s by
    H(q) - H(s) - tan(pitch) x (y_q - y_s) when that is positive; the largest wins. Unknown heights are skipped."""
    tan = math.tan(math.radians(cfg["foot_pitch_deg"]))
    half, length = cfg["foot_width_mm"] / 2, cfg["foot_length_mm"]
    out = {}
    for s in pts:
        best, by = 0.0, None
        hs = h.get(s["key"])
        if hs is not None:
            for q in pts:
                hq = h.get(q["key"])
                dy = q["y"] - s["y"]
                if hq is None or q["cid"] == s["cid"] or not 0 < dy <= length or abs(q["x"] - s["x"]) > half:
                    continue
                v = hq - hs - tan * dy
                if v > best + 1e-12:
                    best, by = v, q["key"]
        out[s["key"]] = (best, by)
    return out


def shadows(pts, heights, cfg, toppers=True):
    """`shadow_map` on the heights of `switch_heights`: with `toppers` True the topper heights H_t count (the owner's
    toppers), False the plain H. {key: (shadow_mm, shadowed_by)}."""
    return shadow_map(pts, {k: v[1 if toppers else 0] for k, v in heights.items()}, cfg)


def reach_cost(pts, shadow, prio):
    """Sum over switches of priority(type) x shadow (mm); `shadow` = a `shadow_map` result."""
    return sum(prio.get(p["type"], 0.0) * shadow[p["key"]][0] for p in pts)


def suggest_toppers(pts, prs, prio, comfort_mm, bonus_mm, existing=(), max_toppers="default", min_gain=None, types=TOPPER_TYPES,
                    heights=None, shadow_cfg=None, reach_weight=0.0):
    """Greedy topper suggestions (pure; post-layout, never during the search). `max_toppers` default MAX_TOPPERS (None =
    no cap), `min_gain` default TOPPER_MIN_GAIN, both read when called (one source with `topper_settings`).

    `pts` = points (key, type, y; with cid and x too when `heights` is given), `prs` = pairs (a, b, a_type, b_type, plain
    distance_mm, optional step_mm = the pair's height step), `existing` = keys that already have a topper (they count towards
    `max_toppers`). The objective is crowding + `reach_weight` x reach (reach = sum of priority x shadow, `reach_cost`); the
    reach part needs `heights` ({key: (H, H_t)}, `switch_heights`: only the plain H is read, a topper adds `bonus_mm`) and
    `shadow_cfg` (foot keys of HEIGHT_DEFAULTS), without them or with weight 0 it is the crowding alone. Each step tries a topper
    on every switch that is in at least one crowded pair (d_eff < comfort) or, with reach, is shadowed, whose type is in `types`
    (None = any), and takes the largest objective reduction (the candidate's own pairs plus the change of every shadow); ties: the
    switch in more crowded pairs, then the higher type priority, then nearer the front (larger y), then the larger shadow removed.
    Stops at the cap, when no objective is left, or when the best gain < min_gain x the objective before suggesting (fixed at the
    start). Returns {"before": objective with `existing`, "after": objective with all, "crowding_before", "crowding_after",
    "reach_before", "reach_after" (mm-weighted), "suggestions": [{key, type, gain (objective), crowding_gain, shadow_removed_mm
    (plain sum over all switches, negative when it shades others), crowding_after}]}."""
    max_toppers = MAX_TOPPERS if max_toppers == "default" else max_toppers
    min_gain = TOPPER_MIN_GAIN if min_gain is None else min_gain
    have = set(existing)
    info = {p["key"]: p for p in pts}
    own = {}   # switch key -> [(pair, pair priority)]
    for r in prs:
        w = pair_priority(prio, r["a_type"], r["b_type"])
        own.setdefault(r["a"], []).append((r, w))
        own.setdefault(r["b"], []).append((r, w))
    use_reach = bool(heights) and shadow_cfg is not None and reach_weight > 0

    def pair_dist(r, toppers):
        return pair_distance(r["distance_mm"], (r["a"] in toppers) + (r["b"] in toppers), bonus_mm, r.get("step_mm", 0.0))

    def pair_crowding(r, w, toppers):
        return crowding(pair_dist(r, toppers), w, comfort_mm)

    def shadow_of(toppers):
        h = {k: (None if v[0] is None else v[0] + (bonus_mm if k in toppers else 0.0)) for k, v in heights.items()}
        return shadow_map(pts, h, shadow_cfg)

    def reach_of(sh):
        return reach_weight * reach_cost(pts, sh, prio)

    crowd = crowd0 = sum(pair_crowding(r, pair_priority(prio, r["a_type"], r["b_type"]), have) for r in prs)
    sh_now = shadow_of(have) if use_reach else None
    reach = reach0 = reach_of(sh_now) if use_reach else 0.0
    before = crowd + reach
    objective = before
    out = []
    limit = None if max_toppers is None else max(0, max_toppers - len(have))
    while before > 0 and (limit is None or len(out) < limit):
        best = None
        for k in list(own) + ([k for k in info if k not in own] if use_reach else []):
            if k in have or (types is not None and info[k]["type"] not in types):
                continue
            mine = own.get(k, [])
            n = sum(1 for r, _ in mine if pair_dist(r, have) < comfort_mm)
            if not n and not (use_reach and sh_now[k][0] > 0):
                continue
            with_k = have | {k}
            cgain = sum(pair_crowding(r, w, have) - pair_crowding(r, w, with_k) for r, w in mine)
            rgain, removed = 0.0, 0.0
            if use_reach:
                sh_k = shadow_of(with_k)
                rgain = reach_of(sh_now) - reach_of(sh_k)
                removed = sum(sh_now[q][0] - sh_k[q][0] for q in sh_now)
            gain = cgain + rgain
            key = (round(gain, 9), n, prio.get(info[k]["type"], 0.0), info[k]["y"], round(removed, 9))
            if best is None or key > best[0]:
                best = (key, k, gain, cgain, removed)
        if best is None or best[2] < min_gain * before or best[2] <= 1e-9:
            break
        _, k, gain, cgain, removed = best
        have.add(k)
        crowd -= cgain
        objective -= gain
        if use_reach:
            sh_now = shadow_of(have)
            reach = reach_of(sh_now)
        out.append({"key": k, "type": info[k]["type"], "gain": gain, "crowding_gain": cgain, "shadow_removed_mm": removed,
                    "crowding_after": crowd})
    return {"before": before, "after": objective, "crowding_before": crowd0, "crowding_after": crowd,
            "reach_before": reach0, "reach_after": reach, "suggestions": out}


def pair_text(r):
    """'86.2 mm apart (effective with toppers, 76.2 mm plain)' (also 'with a height step' / 'with toppers and a height step')
    or '76.2 mm apart' for a checked pair."""
    step = r.get("step_mm") or 0.0
    if r.get("toppers") or step > 1e-9:
        what = " and ".join((["toppers"] if r.get("toppers") else []) + (["height step"] if step > 1e-9 else []))
        return f"{r['effective_mm']:.1f} mm apart (effective with {what}, {r['distance_mm']:.1f} mm plain)"
    return f"{r['distance_mm']:.1f} mm apart"


def pair_priority(prio, type_a, type_b):
    """A pair weighs the larger priority of its two switches (a pair with a bypass switch counts fully)."""
    return max(prio.get(type_a, 0.0), prio.get(type_b, 0.0))


# --- geometry -----------------------------------------------------------------------------------
def points(placed, fs_data):
    """Canvas positions (mm) of the footswitches of the placed pedals: [{key, cid, id, label, type, x, y}]."""
    out = []
    for cid, it in placed.items():
        for f in fs_data.get(cid) or []:
            x, y = design.jack_point(it, f["x"], f["y"])
            out.append({"key": f"{cid}.{f['id']}", "cid": cid, "id": f["id"], "label": f["label"],
                        "type": f["type"], "x": x, "y": y})
    return out


def pairs(pts):
    """Every pair of footswitches on different pedals, closest first: [{a, b, a_type, b_type, distance_mm, points}]."""
    out = []
    for i, p in enumerate(pts):
        for q in pts[i + 1:]:
            if p["cid"] == q["cid"]:
                continue
            out.append({"a": p["key"], "b": q["key"], "a_type": p["type"], "b_type": q["type"],
                        "distance_mm": math.hypot(p["x"] - q["x"], p["y"] - q["y"]),
                        "points": ((p["x"], p["y"]), (q["x"], q["y"]))})
    out.sort(key=lambda r: (r["distance_mm"], r["a"], r["b"]))
    return out


# --- project check (called from build.validate) -------------------------------------------------
def check(ctx, cat_pedals, fs_data):
    """Footswitch findings for one project, appended to ctx['errors'] / ctx['warnings'].

    Fills ctx: footswitch_setup {pedal id: ok|none|missing|no playground_title}, footswitch_fixes [(id, command)],
    footswitch_points (each with `topper`, `suggested` flags), footswitch_pairs (sorted by EFFECTIVE distance
    `effective_mm` = distance_mm + topper bonus per topper; each with `distance_mm` (plain), `toppers` (0..2),
    `crowding` (effective), `crowding_plain`, `too_close` (effective < min_distance_mm), `too_close_plain`),
    footswitch_settings (min_distance_mm, comfort_mm, crowding = the sum with toppers, crowding_plain = without,
    toppers, topper_bonus_mm, max_toppers, topper_min_gain, layout), footswitch_suggestions (`suggest_toppers`
    result, None without a layout). Missing data and pairs closer than an optional minimum (on the effective
    distance) are warnings unless validation.require_footswitches / strict_footswitches are set; topper problems:
    see `topper_settings`.
    Run after jacks.check (it uses ctx['layout']).
    """
    project, errors, warnings = ctx["project"], ctx["errors"], ctx["warnings"]
    val = project.get("validation", {})
    data_sink = errors if val.get("require_footswitches") else warnings
    dist_sink = errors if val.get("strict_footswitches") else warnings
    fs_data = usable(fs_data)
    chain = ctx["chain"]
    limit, comfort, problems, notes = spacing_settings(project)
    errors += problems
    warnings += notes
    tset, tproblems, tnotes = topper_settings(project, {f"{c}.{f['id']}" for c in chain for f in fs_data.get(c, [])},
                                              {c for c in chain if c not in fs_data})
    errors += tproblems
    warnings += tnotes
    hset, hproblems = height_settings(project)
    errors += hproblems
    ctx.update(footswitch_setup={}, footswitch_fixes=[], footswitch_points=[], footswitch_pairs=[],
               footswitch_suggestions=None,
               footswitch_settings={"min_distance_mm": limit, "comfort_mm": comfort, "crowding": None, "layout": False,
                                    "crowding_plain": None, "toppers": tset["toppers"], "topper_bonus_mm": tset["bonus_mm"],
                                    "max_toppers": tset["max_toppers"], "topper_min_gain": tset["min_gain"],
                                    **hset, "reach": None, "reach_plain": None, "heights_missing": []})

    missing = []
    for cid in chain:
        if not cat_pedals[cid].get("playground_title"):
            ctx["footswitch_setup"][cid] = "no playground_title"
            missing.append(cid)
        elif cid not in fs_data:
            ctx["footswitch_setup"][cid] = "missing"
            ctx["footswitch_fixes"].append((cid, f"{COMMAND} {cid} --footswitches"))
            missing.append(cid)
        else:
            ctx["footswitch_setup"][cid] = "ok" if fs_data[cid] else "none"
    if missing:
        data_sink.append(f"footswitches: no footswitch data for {len(missing)} of {len(chain)} pedals "
                         f"({', '.join(missing)}) -> run: {COMMAND} --list-missing {ctx['key']} --only footswitches")

    layout = ctx.get("layout")
    if not layout:
        return
    pts = points(layout["placed"], fs_data)
    prs = pairs(pts)
    prio = priorities(project)
    ctx["footswitch_points"] = pts
    have, bonus = set(tset["toppers"]), tset["bonus_mm"]
    heights_on = hset["heights"]
    hts = switch_heights(pts, cat_pedals, have, bonus, layout.get("board_rect"), hset["deck_rise_mm"]) if heights_on else {}
    y_front = (layout.get("board_rect") or (None,) * 4)[3]
    sh_t = shadows(pts, hts, hset, True) if heights_on else {}
    sh_p = shadows(pts, hts, hset, False) if heights_on else {}
    for p in pts:
        k = p["key"]
        p["topper"] = k in have
        p["height_mm"], p["height_t_mm"] = hts.get(k, (None, None))
        p["shadow_mm"], p["shadow_by"] = sh_t.get(k, (0.0, None))
        p["shadow_plain_mm"] = sh_p.get(k, (0.0, None))[0]
        p["depth_mm"] = None if y_front is None else y_front - p["y"]
    if heights_on:
        miss = sorted({p["cid"] for p in pts if p["height_mm"] is None})
        if miss:
            ctx["footswitch_settings"]["heights_missing"] = miss
            warnings.append(f"footswitches: height unknown for {len(miss)} of {len({p['cid'] for p in pts})} pedals "
                            f"({', '.join(miss)}): height step and shadow skipped for them")
    for r in prs:
        prr = pair_priority(prio, r["a_type"], r["b_type"])
        r["toppers"] = (r["a"] in have) + (r["b"] in have)
        r["step_mm"] = step_mm(hts[r["a"]][0], hts[r["b"]][0], hset["height_gain"], hset["height_cap_mm"]) if heights_on else 0.0
        r["effective_mm"] = pair_distance(r["distance_mm"], r["toppers"], bonus, r["step_mm"])
        r["crowding_plain"] = crowding(r["distance_mm"] + r["step_mm"], prr, comfort)
        r["crowding"] = crowding(r["effective_mm"], prr, comfort)
        r["too_close"] = limit is not None and r["effective_mm"] < limit - 1e-6
        r["too_close_plain"] = limit is not None and r["distance_mm"] + r["step_mm"] < limit - 1e-6
        if r["too_close"]:
            dist_sink.append(f"footswitch: {r['a']} and {r['b']} are {pair_text(r)} (min {limit:g} mm)")
    prs.sort(key=lambda r: (r["effective_mm"], r["a"], r["b"]))
    ctx["footswitch_pairs"] = prs
    ctx["footswitch_settings"].update(crowding=sum(r["crowding"] for r in prs),
                                      crowding_plain=sum(r["crowding_plain"] for r in prs), layout=True,
                                      reach=reach_cost(pts, sh_t, prio) if heights_on else 0.0,
                                      reach_plain=reach_cost(pts, sh_p, prio) if heights_on else 0.0)
    cap_mm = hset["max_shadow_mm"]
    if heights_on and cap_mm is not None:
        for p in pts:
            if p["shadow_mm"] > cap_mm + 1e-6:
                dist_sink.append(f"footswitch: {p['key']} is shadowed by {p['shadow_by']} ({p['shadow_mm']:.1f} mm, max {cap_mm:g})")
    sug = suggest_toppers(pts, prs, prio, comfort, bonus, have, tset["max_toppers"], tset["min_gain"],
                          heights=hts if heights_on else None, shadow_cfg=hset if heights_on else None,
                          reach_weight=hset["reach_weight"])
    ctx["footswitch_suggestions"] = sug
    chosen = {s["key"] for s in sug["suggestions"]}
    for p in pts:
        p["suggested"] = p["key"] in chosen
