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
    """(min_distance_mm or None, comfort_mm, [problems]) from project `footswitches`."""
    cfg = project.get("footswitches") or {}
    problems = []
    num = lambda v: isinstance(v, (int, float)) and not isinstance(v, bool) and v > 0
    lim = cfg.get("min_distance_mm")
    if lim is not None and not num(lim):
        problems.append(f"footswitches.min_distance_mm must be a positive number (mm) or null (no minimum), got {lim!r}")
        lim = None
    comfort = cfg.get("comfort_mm", COMFORT_MM)
    if not num(comfort):
        problems.append(f"footswitches.comfort_mm must be a positive number (mm), got {comfort!r}")
        comfort = COMFORT_MM
    return (None if lim is None else float(lim)), float(comfort), problems


def crowding(distance_mm, priority, comfort_mm):
    """Crowding of one pair (mm): priority x max(0, comfort - d)^2 / comfort."""
    gap = max(0.0, comfort_mm - distance_mm)
    return priority * gap * gap / comfort_mm


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
    footswitch_points, footswitch_pairs (closest first, with crowding and too_close), footswitch_settings
    (min_distance_mm, comfort_mm, crowding = the sum). Missing data and pairs closer than an optional minimum are
    warnings unless validation.require_footswitches / strict_footswitches are set.
    Run after jacks.check (it uses ctx['layout']).
    """
    project, errors, warnings = ctx["project"], ctx["errors"], ctx["warnings"]
    val = project.get("validation", {})
    data_sink = errors if val.get("require_footswitches") else warnings
    dist_sink = errors if val.get("strict_footswitches") else warnings
    fs_data = usable(fs_data)
    chain = ctx["chain"]
    limit, comfort, problems = spacing_settings(project)
    errors += problems
    ctx.update(footswitch_setup={}, footswitch_fixes=[], footswitch_points=[], footswitch_pairs=[],
               footswitch_settings={"min_distance_mm": limit, "comfort_mm": comfort, "crowding": None, "layout": False})

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
    for r in prs:
        r["crowding"] = crowding(r["distance_mm"], pair_priority(prio, r["a_type"], r["b_type"]), comfort)
        r["too_close"] = limit is not None and r["distance_mm"] < limit - 1e-6
        if r["too_close"]:
            dist_sink.append(f"footswitch: {r['a']} and {r['b']} are {r['distance_mm']:.1f} mm apart "
                             f"(min {limit:g} mm)")
    ctx["footswitch_pairs"] = prs
    ctx["footswitch_settings"].update(crowding=sum(r["crowding"] for r in prs), layout=True)

