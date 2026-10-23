"""Jack data: catalog/jacks.json (loading, saving, validation) and the helpers the build and the app share.

catalog/jacks.json holds, per catalog id (pedals and power supplies), a list of jacks:

    {"id": "out", "label": "Output", "function": "output", "x": 1.0, "y": 0.5, "facing": "right"}

x, y are fractions (0..1) of the Pedal Playground image (origin top-left, unrotated pedal);
`facing` is the side the plug enters from. Only these numbers and labels are stored, never an image.
"""
import json
import math
import os
import re
from pathlib import Path

import design
from common import JACKS_FILE, dumps_per_line, pedal_name

FUNCTIONS = ("input", "output", "power", "power_out", "other")
FACINGS = ("left", "right", "top", "down")
KEY_ORDER = ("id", "label", "function", "x", "y", "facing", "default")
DOC = ("Jack positions per catalog id (pedals and power supplies). Written ONLY by scripts/pedal_editor.py. x,y are fractions (0..1) of the Pedal Playground image, origin top-left, in the UNROTATED pedal, and mark the OUTER EDGE of the physical jack (where the plug starts): the cable clearance zone begins there. facing = the side the plug enters from (left/right/top/down). function: input|output|power|power_out|other. 'default': true picks the jack when several share a function. No image is stored.")
COMMAND = "uv run scripts/pedal_editor.py"


# --- file ---------------------------------------------------------------------------------------
def read_file(path=JACKS_FILE):
    """The whole file as a dict {"_doc", "jacks"}; a fresh one if it does not exist."""
    p = Path(path)
    if not p.exists():
        return {"_doc": DOC, "jacks": {}}
    data = json.loads(p.read_text())
    data.setdefault("_doc", DOC)
    data.setdefault("jacks", {})
    return data


def dumps(data):
    """Compact, diff-friendly JSON: one jack per line, catalog ids sorted."""
    return dumps_per_line(data.get("_doc", DOC), "jacks", data["jacks"], KEY_ORDER)


def normalize(jack):
    """Round x/y for storage; keep only known keys (plus `default` when true)."""
    out = {k: jack[k] for k in ("id", "label", "function", "facing")}
    out["x"], out["y"] = round(float(jack["x"]), 4), round(float(jack["y"]), 4)
    if jack.get("default"):
        out["default"] = True
    return {k: out[k] for k in KEY_ORDER if k in out}


def save_jacks(catalog_id, jack_list, path=JACKS_FILE):
    """Replace one catalog id's jacks (None or [] removes it). Re-reads the file first, so other ids are never lost."""
    data = read_file(path)
    if jack_list:
        data["jacks"][catalog_id] = [normalize(j) for j in jack_list]
    else:
        data["jacks"].pop(catalog_id, None)
    tmp = Path(str(path) + ".tmp")
    tmp.write_text(dumps(data))
    os.replace(tmp, path)


# --- small helpers (shared by the app and the build) --------------------------------------------
def slugify(label):
    s = re.sub(r"[^a-z0-9]+", "_", (label or "").lower()).strip("_")
    return s or "jack"


def unique_id(existing_ids, label):
    base, n, cand = slugify(label), 2, slugify(label)
    while cand in set(existing_ids):
        cand, n = f"{base}_{n}", n + 1
    return cand


def guess_facing(fx, fy):
    """The side nearest to the point: a good first guess for which way the plug enters."""
    dist = {"left": fx, "right": 1 - fx, "top": fy, "down": 1 - fy}
    return min(FACINGS, key=lambda k: (dist[k], FACINGS.index(k)))


def usable(jacks_data):
    """Only well-formed jacks (the rest are reported by validate_jacks_file), so a hand-edited file can't crash a build."""
    def ok(j):
        return (all(k in j for k in ("id", "label", "function", "x", "y", "facing")) and j["facing"] in FACINGS
                and isinstance(j["x"], (int, float)) and isinstance(j["y"], (int, float)))
    return {cid: [j for j in js if isinstance(j, dict) and ok(j)] for cid, js in (jacks_data or {}).items() if isinstance(js, list)}


def default_jack(jacks, function):
    """The jack used for a function: the only one, or the one flagged `default`; None if absent/ambiguous."""
    same = [j for j in jacks if j.get("function") == function]
    if len(same) == 1:
        return same[0]
    flagged = [j for j in same if j.get("default")]
    return flagged[0] if len(flagged) == 1 else None


def ambiguous(jacks, function):
    same = [j for j in jacks if j.get("function") == function]
    return len(same) > 1 and sum(1 for j in same if j.get("default")) != 1


# --- validation ---------------------------------------------------------------------------------
def validate_jacks_file(data, pedals, supplies):
    """{catalog id: [problems]} for every id with a problem (unknown ids included)."""
    problems = {}
    for cid, jacks in data.get("jacks", {}).items():
        is_supply = cid in supplies
        errs = []
        if cid not in pedals and not is_supply:
            errs.append("not a pedal or supply id in the catalog")
        seen = set()
        for j in jacks:
            tag = j.get("id", "?")
            miss = [k for k in ("id", "label", "function", "x", "y", "facing") if k not in j]
            if miss:
                errs.append(f"jack {tag}: missing {', '.join(miss)}")
                continue
            if tag in seen:
                errs.append(f"duplicate jack id '{tag}'")
            seen.add(tag)
            if j["function"] not in FUNCTIONS:
                errs.append(f"jack {tag}: function '{j['function']}' not in {FUNCTIONS}")
            if j["function"] == "power_out" and not is_supply:
                errs.append(f"jack {tag}: power_out is only for power supplies")
            if j["facing"] not in FACINGS:
                errs.append(f"jack {tag}: facing '{j['facing']}' not in {FACINGS}")
            if not (isinstance(j["x"], (int, float)) and isinstance(j["y"], (int, float)) and 0 <= j["x"] <= 1 and 0 <= j["y"] <= 1):
                errs.append(f"jack {tag}: x,y must be numbers in 0..1")
            if is_supply and j["function"] == "power_out":
                ports = {o["port"] for o in (supplies[cid].get("outputs") or [])}
                if ports and tag not in ports:
                    errs.append(f"jack {tag}: not a port of {cid} ({', '.join(sorted(ports))})")
        for fn in FUNCTIONS:
            if sum(1 for j in jacks if j.get("function") == fn and j.get("default")) > 1:
                errs.append(f"more than one default {fn} jack")
        if errs:
            problems[cid] = errs
    return problems


# --- project check (called from build.validate) -------------------------------------------------
CLEARANCE_DEFAULT = {"outward_mm": 6.3, "side_mm": 7.0}          # audio jacks without a modelled plug
POWER_CLEARANCE_DEFAULT = {"outward_mm": 5.5, "side_mm": 5.5}  # DC jacks without cables.power_type (estimate: 5.5 mm barrel OD)


def _jack_by_id(jacks, jid):
    return next((j for j in jacks if j["id"] == jid), None)


def load_items(pdir):
    """The parsed playground_design.json of a project folder, or None if it has none."""
    path = Path(pdir) / "playground_design.json"
    return design.parse_design(path) if path.exists() else None


def place_chain(items, chain, cat_pedals):
    """({pedal id: first layout item with its playground_title}, {pedal id: number of matches}) for a chain."""
    by_title = {}
    for it in items:
        if it["title"]:
            by_title.setdefault(it["title"], []).append(it)
    placed, count = {}, {}
    for cid in chain:
        found = by_title.get(cat_pedals[cid].get("playground_title") or "", [])
        count[cid] = len(found)
        if found:
            placed[cid] = found[0]
    return placed, count


def layout_from_items(items, chain, insts, cat_pedals, cat_supplies, jset, warnings, clear_sink):
    """Which layout item is which chain pedal / supply instance, the board and the obstacles.

    Returns {"board", "placed" {pedal id: item}, "obstacles" [items], "inst_item" {supply instance id: item}};
    placement problems go to `warnings` / `clear_sink` (missing chain pedal)."""
    supplies_layer = jset.get("supplies_layer", "under")
    placed, count = place_chain(items, chain, cat_pedals)
    for cid in chain:
        if not count[cid]:
            clear_sink.append(f"layout: {cid} is in the signal chain but not in playground_design.json")
        elif count[cid] > 1:
            warnings.append(f"layout: {cid} appears {count[cid]} times in playground_design.json (using the first)")
    by_title = {}
    for it in items:
        if it["title"]:
            by_title.setdefault(it["title"], []).append(it)
    inst_item, supply_titles = {}, set()
    by_supply = {}
    for s in insts:
        by_supply.setdefault(s["sup"]["id"], []).append(s)
    for sid, group in by_supply.items():
        title = cat_supplies[sid].get("playground_title")
        if title:
            supply_titles.add(title)
        found = sorted(by_title.get(title or "", []), key=lambda i: (i["left_mm"], i["top_mm"]))
        explicit = jset.get("supply_items", {})
        for n, s in enumerate(group):
            want = explicit.get(s["inst"]["id"])
            match = next((i for i in found if i["id"] == want), None) if want else (found[n] if n < len(found) else None)
            if match is None:
                warnings.append(f"layout: supply {s['inst']['id']} ({sid}) is not in playground_design.json")
            else:
                inst_item[s["inst"]["id"]] = match
    pedal_items = [i for i in items if i["kind"] == "pedal"]
    obstacles = [i for i in pedal_items if (i["title"] not in supply_titles or supplies_layer == "on_board")]
    boards = [i for i in items if i["kind"] == "pedalboard"]
    return {"board": boards[0] if boards else None, "placed": placed, "obstacles": obstacles, "inst_item": inst_item}


def check(ctx, cat_pedals, cat_supplies, jacks_data, cable_types=None, defer=False, items=None):
    """Jack findings for one project, appended to ctx['errors'] / ctx['warnings'].

    Fills ctx: jack_fixes [(catalog id, command)], jack_notes, jack_setup {id: status}, violations,
    cables {"signal": [...], "power": [...]} (None without a design file), jack_settings.
    Missing jack data and blocked clearance are warnings unless the project sets
    validation.require_jacks / validation.strict_clearance.
    Every used jack gets the fixed clearance box here. With `defer` the results wait in ctx['fixed_box'] and
    routing.route_project reports them (report_fixed_box) for the jacks it did not check with a plug model, so
    each jack is checked exactly once by whichever model actually ran. `cable_types`: catalog/cables.json (loaded
    if None) for the plug depth used to measure cable lengths. `items`: a parsed layout (design.parse_canvas) to
    check instead of the project's playground_design.json (a candidate layout, scored without writing a file).
    """
    project, errors, warnings = ctx["project"], ctx["errors"], ctx["warnings"]
    jacks_data = usable(jacks_data)
    val = project.get("validation", {})
    jset = project.get("jacks", {})
    outward = float(jset.get("clearance", {}).get("outward_mm", CLEARANCE_DEFAULT["outward_mm"]))
    side = float(jset.get("clearance", {}).get("side_mm", CLEARANCE_DEFAULT["side_mm"]))
    p_out = float(jset.get("power_clearance", {}).get("outward_mm", POWER_CLEARANCE_DEFAULT["outward_mm"]))
    p_side = float(jset.get("power_clearance", {}).get("side_mm", POWER_CLEARANCE_DEFAULT["side_mm"]))
    power_modelled = bool((project.get("cables") or {}).get("power_type"))
    extra_used = jset.get("extra_used", {})
    supplies_layer = jset.get("supplies_layer", "under")
    jack_sink = errors if val.get("require_jacks") else warnings
    clear_sink = errors if val.get("strict_clearance") else warnings
    ctx.update(jack_fixes=[], jack_notes=[], jack_setup={}, violations=[], cables=None, layout=None, layout_source=None, fixed_box=[],
               jack_settings={"outward_mm": outward, "side_mm": side, "power_outward_mm": p_out, "power_side_mm": p_side,
                              "power_modelled": power_modelled, "supplies_layer": supplies_layer})

    chain = ctx["chain"]
    insts = ctx.get("supplies", [])
    used_ports = {}  # supply catalog id -> ports in use
    for s in insts:
        used_ports.setdefault(s["sup"]["id"], set()).update(r["port"] for r in s["rows"] if r["pedals"])

    # 1) which catalog items have a usable jack setup?
    def need_jacks(cid, is_supply):
        have = jacks_data.get(cid) or []
        name = pedal_name(cat_pedals[cid]) if cid in cat_pedals else f"{cat_supplies[cid]['brand']} {cat_supplies[cid]['model']}"
        item = cat_pedals.get(cid) or cat_supplies.get(cid)
        cmd = f"{COMMAND} {cid}"
        if not item.get("playground_title"):
            jack_sink.append(f"jacks: {cid} ({name}) has no playground_title, so there is no image to mark jacks on")
            ctx["jack_setup"][cid] = "no playground_title"
            return
        if not have:
            jack_sink.append(f"jacks: unknown jack setup for {cid} ({name}) -> run: {cmd}")
            ctx["jack_setup"][cid] = "missing"
            ctx["jack_fixes"].append((cid, cmd))
            return
        missing = []
        if is_supply:
            missing = [f"port {p}" for p in sorted(used_ports[cid]) if not (_jack_by_id(have, p) or {}).get("function") == "power_out"]
        else:
            for fn in ("input", "output", "power"):
                if default_jack(have, fn) is None:
                    missing.append(f"{fn} (ambiguous: set a default)" if ambiguous(have, fn) else fn)
            for jid in extra_used.get(cid, []):
                if _jack_by_id(have, jid) is None:
                    errors.append(f"jacks.extra_used: {cid} has no jack '{jid}'")
        if missing:
            jack_sink.append(f"jacks: incomplete jack setup for {cid} ({name}): missing {', '.join(missing)} -> run: {cmd}")
            ctx["jack_setup"][cid] = "incomplete"
            ctx["jack_fixes"].append((cid, cmd))
        else:
            ctx["jack_setup"][cid] = "ok"

    for cid in chain:
        need_jacks(cid, False)
    for sid in used_ports:
        need_jacks(sid, True)

    # 2) the hand-made layout (or the injected candidate)
    if items is None:
        items = load_items(ctx["dir"])
        ctx["layout_source"] = "file" if items is not None else None
    else:
        ctx["layout_source"] = "injected"
    if items is None:
        ctx["jack_notes"].append("no playground_design.json: cable lengths and clearance are not checked")
        return
    lay = layout_from_items(items, chain, insts, cat_pedals, cat_supplies, jset, warnings, clear_sink)
    placed, inst_item, obstacles = lay["placed"], lay["inst_item"], lay["obstacles"]
    # what the cable router needs: the parsed layout, which item is which pedal, and the jack data used here
    ctx["layout"] = {**lay, "jacks": jacks_data, "outward_mm": outward}

    # 3) fixed clearance box in front of every used jack: power jacks (and on-board supply ports) the small
    #    `power_clearance` box, the rest the audio `clearance` box. Jacks that routing.route_project checks with a
    #    plug model (signal cables with a type, power jacks with cables.power_type) drop theirs (report_fixed_box).
    from routing import cable_type_id  # late import: routing imports jacks lazily too
    owners = []  # (label, item, jack)
    for cid, it in placed.items():
        have = jacks_data.get(cid) or []
        ids = [(default_jack(have, fn) or {}).get("id") for fn in ("input", "output", "power")]
        ids += list(extra_used.get(cid, []))
        for jid in dict.fromkeys(i for i in ids if i):
            jk = _jack_by_id(have, jid)
            if jk:
                owners.append((cid, it, jk))
    if supplies_layer == "on_board":
        for s in insts:
            it = inst_item.get(s["inst"]["id"])
            for port in sorted({r["port"] for r in s["rows"] if r["pedals"]}):
                jk = _jack_by_id(jacks_data.get(s["sup"]["id"]) or [], port)
                if it and jk:
                    owners.append((f"{s['inst']['id']}", it, jk))
    for cid, it, jk in owners:
        pt = design.jack_point(it, jk["x"], jk["y"])
        facing = design.jack_facing(it, jk["facing"])
        is_power = jk["function"] in ("power", "power_out")
        out_mm, side_mm = (p_out, p_side) if is_power else (outward, side)
        zone = design.clearance_rect(pt, facing, out_mm, side_mm)
        for ob in obstacles:
            if ob["id"] == it["id"]:
                continue
            ov = design.overlap(zone, design.footprint(ob))
            if ov:
                depth = design.overlap_depth(facing, ov)
                ctx["fixed_box"].append((f"{cid}.{jk['id']}",
                    {"jack": f"{cid}.{jk['id']}", "obstacle": ob["title"], "depth_mm": depth, "zone": "power" if is_power else "audio"},
                    f"clearance: {cid}.{jk['id']} ({jk['label']}, facing {facing}) is blocked by {ob['title']}: "
                    f"it reaches {depth:.1f} mm into the {out_mm:g} mm {'power' if is_power else 'audio'} zone"))
    if not defer:
        report_fixed_box(ctx)

    # 4) cable lengths between jacks
    #    Lengths are measured from a point on the jack axis half the clearance depth in front of the jack (half
    #    the plug head depth with a cable type, else half the fixed box): min_mm is a right-angle path between
    #    those points (no obstacles; routing.route_project measures signal cables around the pedals).
    if cable_types is None:
        from common import load_cable_types
        cable_types = load_cable_types()

    def depth(kind, cable_id=None):
        tid = (project.get("cables") or {}).get("power_type") if kind == "power" else cable_type_id(project, cable_id)
        if tid in cable_types:
            return float(cable_types[tid]["plug"]["head_depth_mm"])
        return p_out if kind == "power" else outward

    def endpoint(item, jack, depth_mm):
        pt = design.jack_point(item, jack["x"], jack["y"])
        facing = design.jack_facing(item, jack["facing"])
        return pt, design.stub(pt, facing, depth_mm / 2)

    def cable(a, b):
        if a is None or b is None:
            return {"direct_mm": None, "min_mm": None}
        (pa, ma), (pb, mb) = a, b
        return {"direct_mm": math.hypot(pa[0] - pb[0], pa[1] - pb[1]),
                "min_mm": abs(ma[0] - mb[0]) + abs(ma[1] - mb[1])}

    def pedal_end(cid, fn, depth_mm):
        jk = default_jack(jacks_data.get(cid) or [], fn)
        return endpoint(placed[cid], jk, depth_mm) if jk and cid in placed else None

    signal, power = [], []
    def jack_name(cid, fn, fallback):
        jk = default_jack(jacks_data.get(cid) or [], fn)
        return f"{cid}.{jk['id'] if jk else fallback}"

    for n, (a, b) in enumerate(zip(chain, chain[1:]), 1):
        d = depth("signal", f"S{n}")
        signal.append({"from": jack_name(a, "output", "out"), "to": jack_name(b, "input", "in"),
                       **cable(pedal_end(a, "output", d), pedal_end(b, "input", d))})
    p_depth = depth("power")
    for s in insts:
        it = inst_item.get(s["inst"]["id"])
        for row in s["rows"]:
            if not row["pedals"]:
                continue
            jk = _jack_by_id(jacks_data.get(s["sup"]["id"]) or [], row["port"])
            prev = endpoint(it, jk, p_depth) if it and jk else None
            prev_name = f"{s['inst']['id']}.{row['port']}"
            for pid in row["pedals"]:
                here = pedal_end(pid, "power", p_depth)
                to_name = jack_name(pid, "power", "power")
                power.append({"output": row["id"], "from": prev_name, "to": to_name, **cable(prev, here)})
                prev, prev_name = here, to_name
    ctx["cables"] = {"signal": signal, "power": power}


def report_fixed_box(ctx, plug_checked=()):
    """Report the fixed-box clearance results that jacks.check kept in ctx['fixed_box'], except for the jacks in
    `plug_checked` ("<id>.<jack id>"), which were checked with a plug model instead."""
    sink = ctx["errors"] if ctx["project"].get("validation", {}).get("strict_clearance") else ctx["warnings"]
    skip = set(plug_checked)
    for key, violation, message in ctx.get("fixed_box") or []:
        if key not in skip:
            ctx["violations"].append(violation)
            sink.append(message)
    ctx["fixed_box"] = []
