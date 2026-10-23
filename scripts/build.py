#!/usr/bin/env python3
"""Validate projects against the shared catalog and generate their docs.

    uv run scripts/build.py              # every project
    uv run scripts/build.py guitar-gig   # one project

Per project: projects/<name>/README.md and diagram.mmd. Plus the root README.md.
Exit status is 1 if any project has validation errors.
"""
import argparse
import sys

import footswitches
import jacks
import power
import routing
from power import volt_range
from common import (IN_MM, ROOT, effective_quantity, fmt_mm, load_cable_types, load_catalog, load_json, pedal_name, project_dirs,
                    proposal_inputs_sha1)

PEDAL_REQUIRED = [
    ("owned",), ("instruments",), ("brand",), ("name",), ("digital",), ("clocked_noise",), ("buffered_bypass",),
    ("power_consumption", "current_ma"), ("power_consumption", "min_voltage_v"),
    ("power_consumption", "max_voltage_v"), ("power_consumption", "needs_isolated_output"),
    ("power_consumption", "polarity"),
]
BOARD_REQUIRED = ["brand", "model", "width_in", "height_in"]


def unknown(v):
    return v is None or v == "" or v == []


def dig(d, path):
    for k in path:
        d = d.get(k) if isinstance(d, dict) else None
    return d


# ---------------------------------------------------------------------------
# validation
# ---------------------------------------------------------------------------
def validate(pdir, cat_pedals, cat_supplies, jacks_data=None, items=None, footswitch_data=None, project=None, route=True):
    """Return a context dict (project data, derived power/rule info, errors, warnings).

    `items`: a parsed layout (design.parse_canvas) checked instead of the project's playground_design.json, so a
    candidate layout can be scored without writing a file. `project`: a project dict used instead of the folder's
    project.json (e.g. with a proposal's power wiring). `route=False` skips the cable router (plug clearance of
    signal and power jacks falls back to the fixed boxes): for callers that only need the data findings."""
    project = load_json(pdir / "project.json") if project is None else project
    errors, warnings = [], []
    ctx = {"dir": pdir, "key": pdir.name, "project": project, "errors": errors, "warnings": warnings}
    no_unknown = project.get("validation", {}).get("no_unknown", True)
    ctx["no_unknown"] = no_unknown

    def need(label, value):
        if unknown(value):
            (errors if no_unknown else warnings).append(f"unknown: {label}")

    for key in ("name", "instrument"):
        need(f"project {key}", project.get(key))
    board = project.get("board") or {}
    for key in BOARD_REQUIRED:
        need(f"board.{key}", board.get(key))

    chain = project.get("signal_chain", [])
    ctx["chain"] = chain
    pos = {pid: i for i, pid in enumerate(chain)}
    if not chain:
        need("signal_chain (empty)", None)
    if len(set(chain)) != len(chain):
        errors.append("chain: duplicate pedal in signal_chain")
    for pid in chain:
        if pid not in cat_pedals:
            errors.append(f"chain: pedal '{pid}' is not in catalog/pedals.json")
    chain = [pid for pid in chain if pid in cat_pedals]
    ctx["chain"] = chain
    pos = {pid: i for i, pid in enumerate(chain)}
    pedals = {pid: cat_pedals[pid] for pid in chain}
    ctx["pedals"] = pedals

    # unknown values + instrument fit
    for pid, p in pedals.items():
        for path in PEDAL_REQUIRED:
            need(f"{pid}.{'.'.join(path)}", dig(p, path))
        if project.get("instrument") and p.get("instruments") and project["instrument"] not in p["instruments"]:
            warnings.append(f"instrument: {pid} is tagged {p['instruments']} but the project is for {project['instrument']}")

    # ----- ordering rules -------------------------------------------------
    rules = [{**r, "pedal": pid, "origin": "catalog"} for pid in chain for r in pedals[pid].get("dependencies", [])]
    all_catalog_ids = {r["id"] for p in cat_pedals.values() for r in p.get("dependencies", [])}
    rules += [{**r, "origin": "project"} for r in project.get("rules", [])]
    ids = [r["id"] for r in rules]
    for dup in {i for i in ids if ids.count(i) > 1}:
        errors.append(f"rules: duplicate rule id '{dup}'")
    overrides = project.get("rule_overrides", {})
    for oid in overrides:
        if oid not in ids and oid not in all_catalog_ids:
            errors.append(f"rule_overrides: unknown rule id '{oid}'")
    active, disabled, skipped = [], [], []
    for r in rules:
        ov = overrides.get(r["id"], {})
        if r["pedal"] not in cat_pedals:
            errors.append(f"rules: {r['id']} names unknown pedal '{r['pedal']}'")
        elif r["pedal"] not in pos:
            skipped.append(r)
        elif ov.get("disable"):
            disabled.append(r)
        else:
            active.append({**r, "strength": ov.get("strength", r["strength"]), "priority": ov.get("priority", r.get("priority", 0))})
    ctx.update(active_rules=active, disabled_rules=disabled, skipped_rules=skipped)

    # Every rule expands into pairwise "a must come before b" constraints with a priority.
    # Contradicting pairs are settled by priority (higher wins, the loser is reported as
    # overridden); equal priorities contradict each other and fail the build.
    constraints, early = [], []

    def add(a, b, r):
        constraints.append({"a": a, "b": b, "id": r["id"], "priority": r["priority"], "strength": r["strength"]})

    for r in active:
        pid, kind = r["pedal"], r["type"]
        if kind in ("after", "before"):
            for other in r["pedals"]:
                if other not in cat_pedals:
                    errors.append(f"rules: {r['id']} refers to unknown pedal '{other}'")
                elif other in pos and other != pid:
                    add(other, pid, r) if kind == "after" else add(pid, other, r)
        elif kind in ("after_group", "before_group"):
            members = [o for o in chain if o != pid and r["group"] in pedals[o].get("tags", [])]
            if not members:
                warnings.append(f"rules: {r['id']}: no on-board pedal has tag '{r['group']}'")
            for o in members:
                add(o, pid, r) if kind == "after_group" else add(pid, o, r)
        elif kind == "no_buffered_before":
            for o in chain:
                b = pedals[o].get("buffered_bypass")
                if o != pid and b is True:
                    add(pid, o, r)
                elif o != pid and b is None and pos[o] < pos[pid]:
                    warnings.append(f"order: {r['id']}: '{o}' ahead of {pid} has unknown bypass type")
        elif kind == "position":
            for o in chain:
                if o != pid:
                    add(pid, o, r) if r["value"] == "first" else add(o, pid, r)
        elif kind == "as_early_as_possible":
            early.append(r)
        else:
            errors.append(f"rules: {r['id']}: unknown rule type '{kind}'")

    sections = project.get("sections") or {}
    ctx["sections"] = sections
    if sections:
        sec_rule = {"id": "sections", "priority": sections.get("priority", -10), "strength": sections.get("strength", "required")}
        seen = {}
        for s in sections.get("order", []):
            for o in s["pedals"]:
                if o not in cat_pedals:
                    errors.append(f"sections: '{s['name']}' names unknown pedal '{o}'")
                elif o in seen:
                    errors.append(f"sections: '{o}' is in both '{seen[o]}' and '{s['name']}'")
                seen[o] = s["name"]
        order = [[o for o in s["pedals"] if o in pos] for s in sections.get("order", [])]
        for i, earlier in enumerate(order):
            for later in order[i + 1:]:
                for a in earlier:
                    for b in later:
                        add(a, b, sec_rule)

    by_pair = {}
    for c in constraints:
        by_pair.setdefault(frozenset((c["a"], c["b"])), []).append(c)
    kept, overridden = [], {}
    for pair, cs in by_pair.items():
        x, y = sorted(pair)
        fwd = [c for c in cs if (c["a"], c["b"]) == (x, y)]
        rev = [c for c in cs if (c["a"], c["b"]) == (y, x)]
        if fwd and rev:
            mf, mr = max(c["priority"] for c in fwd), max(c["priority"] for c in rev)
            if mf == mr:
                errors.append(f"rules: {x} and {y} are ordered both ways at priority {mf}: "
                              f"{sorted({c['id'] for c in fwd})} vs {sorted({c['id'] for c in rev})}")
                kept += cs
                continue
            win, lose = (fwd, rev) if mf > mr else (rev, fwd)
            top = max(win, key=lambda c: c["priority"])
            for c in lose:
                overridden.setdefault((top["id"], c["id"]), []).append(f"{c['a']} before {c['b']}")
            kept += win
        else:
            kept += cs
    ctx["overrides"] = [{"winner": w, "loser": l, "pairs": ps} for (w, l), ps in overridden.items()]

    broken = {}
    for c in kept:
        if pos[c["a"]] > pos[c["b"]]:
            broken.setdefault((c["id"], c["strength"]), []).append(f"{c['a']} before {c['b']}")
    for (rid, strength), ps in broken.items():
        (errors if strength == "required" else warnings).append(f"order ({strength}): {rid}: needs {'; '.join(ps)}")

    for r in early:
        pid, me = r["pedal"], pos[r["pedal"]]
        preds = {o for rr in active if rr["pedal"] == pid and rr["type"] == "after" for o in rr["pedals"] if o in pos}
        extra = [o for o in chain[:me] if o not in preds]
        if extra:
            (errors if r["strength"] == "required" else warnings).append(
                f"order ({r['strength']}): {r['id']}: {pid} could be earlier: {', '.join(extra)} come first but are not required to")

    # ----- power ----------------------------------------------------------
    policy = project.get("power_policy", {})
    sensitive, pol_strength, _ = power.policy_settings(project)
    ctx["supplies"] = []
    powered, instances, run_v = {}, {}, {}
    for inst in project.get("power", {}).get("supplies", []):
        sup = cat_supplies.get(inst["supply"])
        if sup is None:
            errors.append(f"power: {inst['id']}: unknown supply '{inst['supply']}'")
            continue
        instances[inst["supply"]] = instances.get(inst["supply"], 0) + 1
        for key in ("brand", "model", "quantity"):
            need(f"supply {sup['id']}.{key}", sup.get(key))
        outputs_def = sup.get("outputs")
        need(f"supply {sup['id']}.outputs", outputs_def)
        by_port = {o["port"]: o for o in (outputs_def or [])}
        rows = []
        for out in inst.get("outputs", []):
            oid = f"{inst['id']}_{out['port']}"
            odef = by_port.get(out["port"])
            row = {"id": oid, "port": out["port"], "voltage_v": out["voltage_v"], "pedals": out.get("pedals", []),
                   "note": out.get("note"), "load": 0, "limit": None, "def": odef}
            rows.append(row)
            if odef is None:
                if outputs_def:
                    errors.append(f"{oid}: {sup['id']} has no port '{out['port']}'")
                continue
            for o in odef.get("options", []):
                need(f"supply {sup['id']}.{out['port']} option", o.get("max_ma"))
            limit = next((o["max_ma"] for o in odef["options"] if o["voltage_v"] == out["voltage_v"]), None)
            if limit is None:
                errors.append(f"{oid}: {out['voltage_v']}V not available on {sup['id']} {out['port']}")
                continue
            row["limit"] = limit
            row["polarity"] = odef.get("polarity") or sup.get("polarity")
            need(f"supply {sup['id']}.polarity", row["polarity"])
            if row["polarity"] is not None and row["polarity"] not in routing.POLARITIES:
                errors.append(f"{oid}: {sup['id']} has unknown polarity '{row['polarity']}' ({', '.join(routing.POLARITIES)})")
                row["polarity"] = None
            for pid in row["pedals"]:
                if pid not in pedals:
                    errors.append(f"power: {oid} feeds '{pid}' which is not in the signal chain")
                    continue
                if pid in powered:
                    errors.append(f"power: '{pid}' is on both {powered[pid]} and {oid}")
                powered[pid] = oid
                run_v[pid] = out["voltage_v"]
            errs, warns, row["load"] = power.output_findings(oid, row["pedals"], out["voltage_v"], limit, row["polarity"],
                                                             pedals, sensitive, pol_strength, odef.get("isolated"))
            errors += errs
            warnings += warns
        ctx["supplies"].append({"inst": inst, "sup": sup, "rows": rows})
    for pid in chain:
        if pid not in powered:
            errors.append(f"power: '{pid}' has no power output")
    # 18V-capable pedals should share 18V outputs instead of spreading over several
    if policy.get("group_18v", True):
        warnings += power.merge_18v_findings([r for s in ctx["supplies"] for r in s["rows"]], pedals)
    for sid, n in instances.items():
        q = cat_supplies[sid].get("quantity")
        if q is not None and n > q:
            errors.append(f"power: project uses {n} x {sid} but you own {q}")
    ctx["instances"] = instances
    ctx["feeds"] = {pid: oid for pid, oid in powered.items()}
    ctx["run_v"] = run_v
    cable_types = load_cable_types()
    jacks.check(ctx, cat_pedals, cat_supplies, jacks.read_file()["jacks"] if jacks_data is None else jacks_data,
                cable_types=cable_types, defer=True, items=items)
    if route:
        routing.route_project(ctx, cat_pedals, cable_types=cable_types)
    else:
        jacks.report_fixed_box(ctx)
    footswitches.check(ctx, cat_pedals, footswitches.read_file()["footswitches"] if footswitch_data is None else footswitch_data)
    return ctx


# ---------------------------------------------------------------------------
# rendering
# ---------------------------------------------------------------------------
def yn(v):
    return "Unknown" if v is None else ("Yes" if v else "No")


def bypass(p):
    b, sw = p.get("buffered_bypass"), p.get("buffer_switchable")
    if b is None:
        return "Unknown"
    return ("Buffered" if b else "True") + (" (switchable)" if sw else "")


def ma(p):
    v = p["power_consumption"]["current_ma"]
    return "?" if v is None else v


RULE_TEXT = {
    "after": lambda r, n: "must come after " + ", ".join(n(o) for o in r["pedals"]),
    "before": lambda r, n: "must come before " + ", ".join(n(o) for o in r["pedals"]),
    "after_group": lambda r, n: f"must come after all `{r['group']}` pedals",
    "before_group": lambda r, n: f"must come before all `{r['group']}` pedals",
    "no_buffered_before": lambda r, n: "no buffered pedal anywhere before it",
    "position": lambda r, n: f"must be {r['value']} in the chain",
    "as_early_as_possible": lambda r, n: "as early in the chain as possible",
}


def board_text(board):
    if any(unknown(board.get(k)) for k in BOARD_REQUIRED):
        return "*not fully specified*"
    return f"{board['brand']} {board['model']} ({round(board['width_in'] * IN_MM)} x {round(board['height_in'] * IN_MM)} mm)"


def sup_name(sup):
    return f"{sup['brand']} {sup['model'] or '(model unknown)'}"


def inst_label(s):
    return s["inst"].get("label") or f"{sup_name(s['sup'])} #{s['inst']['id']}"


CATEGORY_STYLE = {  # category: (fill, stroke); light fills with dark text read well in light and dark themes
    "tuner": ("#eceff1", "#607d8b"),
    "compressor": ("#b2ebf2", "#00838f"),
    "fuzz / boost": ("#ffccbc", "#d84315"),
    "drive / distortion": ("#ffe082", "#ff8f00"),
    "phase-type": ("#e1bee7", "#8e24aa"),
    "modulation": ("#bbdefb", "#1565c0"),
    "tremolo": ("#c5cae9", "#3949ab"),
    "delay": ("#c8e6c9", "#2e7d32"),
    "eq / boost": ("#f8bbd0", "#ad1457"),
    "other": ("#d7ccc8", "#5d4037"),
}


def category(p):
    tags = set(p.get("tags", []))
    for cat, wanted in (("tuner", {"tuner"}), ("compressor", {"compressor"}), ("delay", {"delay"}), ("tremolo", {"tremolo"}),
                        ("phase-type", {"phaser", "vibe"}), ("modulation", {"chorus", "flanger", "modulation"}),
                        ("eq / boost", {"master", "eq"}), ("fuzz / boost", {"fuzz", "boost"}),
                        ("drive / distortion", {"overdrive", "distortion", "gain"})):
        if tags & wanted:
            return cat
    return "other"


def class_defs(cats):
    lines = []
    for cat in CATEGORY_STYLE:
        if cat in cats:
            fill, stroke = CATEGORY_STYLE[cat]
            lines.append(f"    classDef {cls(cat)} fill:{fill},stroke:{stroke},stroke-width:2px,color:#1b1b1b")
    return lines


def cls(cat):
    return "c_" + "".join(ch if ch.isalnum() else "_" for ch in cat)


def mermaid_signal(ctx):
    """One straight thread, guitar -> pedals -> amp, pedals coloured by category."""
    chain, pedals = ctx["chain"], ctx["pedals"]
    cats = {pid: category(pedals[pid]) for pid in chain}
    bass = ctx["project"].get("instrument") == "bass"
    lines = ["flowchart TB", f'    guitar(["{"Bass" if bass else "Guitar"}"]):::endpoint']
    for i, pid in enumerate(chain, 1):
        lines.append(f'    {pid}["<b>{i}</b> &nbsp;{pedal_name(pedals[pid])}<br/>{cats[pid]}"]:::{cls(cats[pid])}')
    lines.append('    amp(["Amplifier"]):::endpoint')
    nodes = ["guitar", *chain, "amp"]
    lines.append("    " + " --> ".join(nodes))
    lines.append("    classDef endpoint fill:#263238,stroke:#263238,color:#ffffff")
    lines += class_defs(set(cats.values()))
    lines.append("    linkStyle default stroke:#78909c,stroke-width:2px")
    return lines


def mermaid_power(ctx):
    """Only the power wiring: every output of every supply, then the pedals it feeds."""
    pedals = ctx["pedals"]
    lines = ["flowchart LR"]
    cats = set()
    edges = []
    for s in ctx["supplies"]:
        lines.append(f'    subgraph {s["inst"]["id"]}["{inst_label(s)}"]')
        lines.append("        direction TB")
        order = {o["port"]: i for i, o in enumerate((s["sup"].get("outputs") or []))}
        for row in sorted(s["rows"], key=lambda r: order.get(r["port"], 99)):
            klass = "spare" if not row["pedals"] else ("out18" if row["voltage_v"] == 18 else "out9")
            text = f'<b>{row["port"]}</b> · {row["voltage_v"]}V<br/>{row["load"]} / {row["limit"] or "?"} mA'
            if not row["pedals"]:
                text += "<br/>spare"
            lines.append(f'        {row["id"]}["{text}"]:::{klass}')
            prev = row["id"]
            for pid in row["pedals"]:
                if pid in pedals:
                    prev_edge = f"{prev} --> {pid}"
                    edges.append(prev_edge)
                    prev = pid
        lines.append("    end")
    placed = set()
    for s in ctx["supplies"]:
        for row in s["rows"]:
            for pid in row["pedals"]:
                if pid in pedals and pid not in placed:
                    placed.add(pid)
                    cat = category(pedals[pid])
                    cats.add(cat)
                    lines.append(f'    {pid}["{pedal_name(pedals[pid])}<br/>{cat} · {ma(pedals[pid])} mA"]:::{cls(cat)}')
    lines += [f"    {e}" for e in edges]
    lines.append("    classDef out9 fill:#ffffff,stroke:#455a64,stroke-width:2px,color:#1b1b1b")
    lines.append("    classDef out18 fill:#ffffff,stroke:#d84315,stroke-width:3px,color:#1b1b1b")
    lines.append("    classDef spare fill:#fafafa,stroke:#9e9e9e,stroke-dasharray:4 3,color:#757575")
    lines += class_defs(cats)
    for s in ctx["supplies"]:
        lines.append(f"    style {s['inst']['id']} fill:none,stroke:#90a4ae,stroke-dasharray:4 3")
    lines.append("    linkStyle default stroke:#78909c,stroke-width:2px")
    return lines


def routing_section(ctx):
    """README section: routed signal cables (picture + table) and the power cable list."""
    cables = ctx.get("cable_list") or []
    if not cables:
        return []
    cfg = ctx["routing"]["settings"]
    md = ["", "## Cable routing", "",
          f"Signal cables are routed on the board surface between the pedals: never under the board, never in front of the lowest pedals, "
          f"at most {cfg['edge_margin_mm']:g} mm beyond the back and sides, at most {cfg['max_stack']} cables stacked in one "
          f"{cfg['grid_mm']:g} mm cell (cable width on the board {cfg['diameter_mm']:g} mm). "
          + (f"Plugs are modelled (default cable type `{cfg['type']}`, catalog/cables.json): a right-angle plug's cable leaves the head to the "
             f"left or right of the jack's facing (chosen per end: fewest blocked plugs, then the shortest route), runs "
             f"{cfg['exit_run_mm']:g} mm straight, then is routed; grey boxes in the picture are the plug heads and their cable exits. "
             if cfg.get("type") else "No cable type is set (`cables.type`), so cables leave each jack straight out by the fixed clearance depth. ")
          + "Power cables run under the board and are listed, not routed yet"
          + (f"; their plug at each pedal's power jack is modelled for clearance (`{cfg['power_type']}`, exit side in the Exits column)."
             if cfg.get("power_type") else "."), ""]
    if ctx["routing"].get("grid"):
        md += ["![Cable routing](cables.svg)", ""]
    md += ["Min length = the shortest cable that reaches: measured from a point on each jack's axis half the clearance depth in front "
           "of the jack (half the plug head depth), along the plug's cable exit and the routed path. No slack or rounding is added. "
           "'~' marks a power cable: a right-angle estimate between its jacks (power cables are not routed).", "",
           "| Cable | Kind | From | To | Type | Exits | Tips | Polarity | Under board | Min length (mm) | Status |",
           "|---|---|---|---|---|---|---|---|:-:|--:|---|"]
    for c in cables:
        length = fmt_mm(c["min_mm"]) if c["min_mm"] is not None else (f"~{fmt_mm(c['estimate_mm'])}" if c.get("estimate_mm") is not None else "?")
        exits = f"{c.get('exit_a') or '-'} / {c.get('exit_b') or '-'}" if c.get("type") else "-"
        md.append(f"| {c['id']} | {c['kind']} | {c['from']} | {c['to']} | {c.get('type') or '-'} | {exits} | {c['tip_a']} / {c['tip_b']} | {(c.get('polarity') or '?') if c['kind'] == 'power' else '-'} | "
                  f"{'yes' if c['under_board'] else 'no'} | {length} | {c['status']} |")
    sig = [c for c in cables if c["kind"] == "signal" and c["min_mm"] is not None]
    if sig:
        md += ["", f"Signal cable, minimum: {sum(c['min_mm'] for c in sig):.0f} mm over {len(sig)} cables."]
    return md


def violation_where(v):
    """'3.2 mm into the power zone' or '3.2 mm into the head of the ernie_ball_flat_patch_ra plug, cable exits left'."""
    if not v.get("cable_type"):
        return f"{v['depth_mm']:.1f} mm into the {v.get('zone', 'audio')} zone"
    side = f", cable exits {v['side']}" if v.get("side") else ""
    part = "cable run" if v["part"] == "cable" else v["part"]
    return f"{v['depth_mm']:.1f} mm into the {part} of the {v['cable_type']} plug{side}"


def run_v_cell(ctx, pid):
    rv = ctx["run_v"]
    return f"{rv[pid]}V" if pid in rv else "-"


def jacks_section(ctx):
    """README section: jack data status, blocked cable space, cable lengths (all mm)."""
    md = ["", "## Jacks and cables", ""]
    setup = ctx.get("jack_setup", {})
    if setup:
        ok = sum(1 for v in setup.values() if v == "ok")
        md += [f"Jack data: {ok} of {len(setup)} catalog items set up (pedals and supplies in this project).", ""]
    if ctx.get("jack_fixes"):
        md += ["Missing or incomplete (place the jacks on the pedal image, then rebuild):", "", "```"]
        md += [cmd for _, cmd in ctx["jack_fixes"]] + ["```", ""]
    for note in ctx.get("jack_notes", []):
        md += [f"*{note}.*", ""]
    cables = ctx.get("cables")
    if cables is None:
        return md
    st = ctx["jack_settings"]
    power = ("power jacks: the DC plug head plus its cable exit on the less blocked side" if st.get("power_modelled") else
             f"power jacks: {st['power_outward_mm']:g} mm outward, {st['power_side_mm']:g} mm to each side")
    zone = (f"signal jacks with a cable type: the plug head plus its cable exit on the side the router chose (see Cable routing); "
            f"{power}; other jacks: {st['outward_mm']:g} mm outward, {st['side_mm']:g} mm to each side")
    if ctx["violations"]:
        md += [f"Blocked cable space ({zone}):", ""]
        md += [f"- `{v['jack']}` is blocked by {v['obstacle']}: {violation_where(v)}" for v in ctx["violations"]] + [""]
    else:
        md += [f"No blocked cable space found ({zone}).", ""]
    md += ["Cable lengths: see Cable routing.", ""]
    return md


def footswitch_section(ctx, cat_pedals):
    """README section: footswitch data status, the minimum spacing and the closest pairs (all mm)."""
    md = ["", "## Footswitches", ""]
    setup, chain = ctx.get("footswitch_setup", {}), ctx["chain"]
    have = [c for c in chain if setup.get(c) in ("ok", "none")]
    none = [c for c in chain if setup.get(c) == "none"]
    md += [f"Footswitch data: {len(have)} of {len(chain)} pedals" + (f" ({len(none)} without a footswitch)" if none else "")
           + " (catalog/footswitches.json).", ""]
    if ctx.get("footswitch_fixes"):
        md += ["Missing (place the switches on the pedal image, then rebuild):", "", "```"]
        md += [cmd for _, cmd in ctx["footswitch_fixes"]] + ["```", ""]
    st = ctx.get("footswitch_settings") or {}
    if not st.get("layout"):
        return md + ["*No playground_design.json: footswitch spacing is not checked.*", ""]
    lim = st.get("min_distance_mm")
    if st.get("mode") == "auto":
        rule = (f"auto = {lim:.1f} mm, the smallest distance between switches of different pedals in playground_design.json "
                f"(the owner's layout is the reference)" if lim is not None else
                "auto: no pair of footswitches is known yet, so there is no limit")
    else:
        rule = f"{lim:g} mm (`footswitches.min_distance_mm`)"
    md += [f"Minimum distance between switches of different pedals (centre to centre): {rule}. "
           "Switches on the same pedal are not checked. Type: bypass (turns the pedal, or one side of it, on and off), tap (tap tempo), "
           "boost (a boost / extra-gain stomp), function (any other switch).", ""]
    prs = ctx.get("footswitch_pairs") or []
    if not prs:
        return md + ["No pair of footswitches on different pedals is known yet.", ""]
    md += [f"Closest pairs ({min(len(prs), footswitches.TOP_PAIRS)} of {len(prs)}):", "",
           "| Switch | Type | Switch | Type | Distance (mm) | Status |", "|---|---|---|---|--:|---|"]
    for r in prs[:footswitches.TOP_PAIRS]:
        md.append(f"| {r['a']} | {r['a_type']} | {r['b']} | {r['b_type']} | {r['distance_mm']:.1f} | "
                  f"{'too close' if r['too_close'] else 'ok'} |")
    close = sum(1 for r in prs if r["too_close"])
    md += ["", f"{close} pair(s) closer than the minimum." if close else "No pair is closer than the minimum.", ""]
    return md


def proposals_section(ctx, cat_pedals):
    """README section from projects/<name>/proposals/meta.json (written by scripts/propose_layout.py; the search
    never runs here): before/after figures, moved pedals, each proposal's power wiring, stale detection."""
    pdir = ctx["dir"]
    meta_path = pdir / "proposals" / "meta.json"
    design_path = pdir / "playground_design.json"
    if not design_path.exists():
        return []
    md = ["", "## Layout proposals", ""]
    if not meta_path.exists():
        return md + [f"None yet: `uv run scripts/propose_layout.py {ctx['key']}` searches for better pedal positions "
                     "(it never changes playground_design.json).", ""]
    meta = load_json(meta_path)
    stale = meta.get("inputs_sha1") != proposal_inputs_sha1(pdir) or meta.get("chain") != ctx["chain"]
    md += [f"Made by `{meta['command']}` (max_change `{meta['max_change']}`, max move "
           f"{'none' if meta.get('max_move_mm') is None else format(meta['max_move_mm'], 'g') + ' mm'}, seed {meta['seed']}, "
           f"{meta['iterations']} iterations x {meta['restarts']} restarts, {meta['runtime_s']:g} s). Each proposal is a Pedal "
           "Playground file (Load from File: the owner's layout with only the moved pedals changed); load it, adjust, save it as "
           "playground_design.json, then build. Approximation: plug sizes are partly estimates and the search scores a simplified "
           "model; every proposal was checked with this build (clearance, routed cables, footswitch spacing).", ""]
    if stale:
        md += ["**Stale:** playground_design.json, project.json or the catalog data of these pedals (jacks, footswitches, "
               "cables, specs) changed since these proposals were made; rerun the command above.", ""]
    props = meta.get("proposals") or []
    if not props:
        return md + [f"No better layout found ({meta.get('finalists', 0)} finalist(s) checked against the owner's layout).", ""]

    def fs(m):
        return "no data" if not m.get("fs_known") else str(m["fs_close"])
    rows = [("Blocked plugs", lambda m: f"{m['blocked']} ({m['blocked_mm']:.1f} mm)"),
            ("Unroutable / squeezed / over the stacking limit", lambda m: f"{m['unroutable']} / {m['squeezed']} / {m['overflow']}"),
            ("Footswitch pairs below the minimum", fs),
            ("Closest footswitch pair (mm)", lambda m: "-" if m.get("fs_closest_mm") is None else f"{m['fs_closest_mm']:.1f}"),
            ("Signal cables, routed minimum (mm)", lambda m: f"{m['signal_mm']:.0f}"),
            ("Power cables, estimate (mm)", lambda m: f"{m['power_mm']:.0f}"),
            ("First input / last output to the board edges (mm)", lambda m: f"{m['io_mm']:.0f}"),
            ("Build errors / warnings", lambda m: f"{m['errors']} / {m['warnings']}"),
            ("Score (lower is better)", lambda m: f"{m['score']:.0f}")]
    owner = meta["owner"]
    md += ["| | Owner's layout | " + " | ".join(f"Proposal {p['n']}" for p in props) + " |",
           "|---|--:|" + "--:|" * len(props)]
    for label, f in rows:
        md.append(f"| {label} | {f(owner)} | " + " | ".join(f(p["metrics"]) for p in props) + " |")
    md.append("")
    nm = lambda pid: pedal_name(cat_pedals[pid]) if pid in cat_pedals else pid
    for p in props:
        m = p["metrics"]
        gone = sorted(set(owner.get("blocked_jacks", [])) - set(m.get("blocked_jacks", [])))
        md += [f"### Proposal {p['n']}", "", f"Pedal Playground file: [proposals/{p['file']}](proposals/{p['file']})"
               + (f"; blocked plugs fixed: {', '.join(f'`{j}`' for j in gone)}" if gone else "") + ".", "",
               f"![Proposal {p['n']}](proposals/{p['svg']})", "",
               "| Pedal | dx (mm) | dy (mm) | Moved (mm) | Rotation |", "|---|--:|--:|--:|---|"]
        for mv in p["moved"]:
            rot = f"{mv['rot_from']} -> {mv['rot_to']} deg" if mv["rot_from"] != mv["rot_to"] else f"{mv['rot_to']} deg"
            md.append(f"| {nm(mv['pedal'])} | {mv['dx_mm']:+.1f} | {mv['dy_mm']:+.1f} | {mv['distance_mm']:.1f} | {rot} |")
        pw = p.get("power") or {}
        md += ["", f"Power wiring for this layout (computed under the power policy; the build keeps using project.json"
               + (f"; {pw['error']}, so the owner's wiring is shown" if pw.get("error") else "") + "):", "",
               "| Supply | Output | Voltage | Daisy chain |", "|---|---|--:|---|"]
        for sup in pw.get("supplies", []):
            for o in sup["outputs"]:
                md.append(f"| {sup.get('label') or sup['id']} | {o['port']} | {o['voltage_v']}V | {', '.join(nm(x) for x in o['pedals'])} |")
        md.append("")
    return md


def project_readme(ctx, cat_pedals):
    pr, chain, pedals = ctx["project"], ctx["chain"], ctx["pedals"]
    nm = lambda pid: pedal_name(cat_pedals[pid]) if pid in cat_pedals else pid
    feed_label = {}
    for s in ctx["supplies"]:
        for row in s["rows"]:
            for pid in row["pedals"]:
                feed_label[pid] = f"{inst_label(s).split(' (')[0]} · {row['port']}"
    status = "OK" if not ctx["errors"] else f"{len(ctx['errors'])} error(s)"
    md = [
        f"# {pr.get('name') or ctx['key']}",
        "",
        "> Generated by `scripts/build.py` from `catalog/` and this folder's `project.json`. Edit those, not this file.",
        "",
        f"- **Instrument:** {pr.get('instrument') or 'unknown'}",
        f"- **Board:** {board_text(pr.get('board') or {})}",
        f"- **Validation:** {status}, {len(ctx['warnings'])} warning(s)" + (" (`no_unknown` on)" if ctx["no_unknown"] else ""),
        "",
    ]
    if ctx["errors"] or ctx["warnings"]:
        md += ["<details><summary>Validation messages</summary>", ""]
        md += [f"- ERROR {m}" for m in ctx["errors"]] + [f"- WARN {m}" for m in ctx["warnings"]]
        md += ["", "</details>", ""]
    md += ["## Signal chain", "", "```mermaid", *mermaid_signal(ctx), "```", "",
           "| # | Pedal | Owned | Accepts | Runs at | Draw | Bypass | Digital | Powered from |", "|--:|---|:-:|---|---|--:|---|:-:|---|"]
    for i, pid in enumerate(chain, 1):
        p = pedals[pid]
        md.append(f"| {i} | {pedal_name(p)} | {yn(p.get('owned'))} | {volt_range(p['power_consumption'])} | {run_v_cell(ctx, pid)} | {ma(p)} mA | {bypass(p)} | {yn(p.get('digital'))} | {feed_label.get(pid, '-')} |")
    to_buy = [pedal_name(pedals[pid]) for pid in chain if pedals[pid].get("owned") is False]
    md += ["", f"**To buy:** {', '.join(to_buy) or 'nothing'}", "", "### Ordering rules", ""]
    for r in ctx["active_rules"]:
        tag = "" if r["strength"] == "required" else " *(preferred)*"
        prio = f" (priority {r['priority']})" if r.get("priority") else ""
        md.append(f"- **{nm(r['pedal'])}** {RULE_TEXT[r['type']](r, nm)}{tag}{prio}: {r['reason']} `[{r['origin']}]`")
    for r in ctx["disabled_rules"]:
        md.append(f"- ~~{nm(r['pedal'])} {RULE_TEXT[r['type']](r, nm)}~~ (disabled in this project): {r['reason']}")
    if ctx.get("sections", {}).get("order"):
        md += ["", "### Section order", "", "Pedals in an earlier section come before pedals in a later one (priority "
               f"{ctx['sections'].get('priority', -10)}); pedals not listed are only bound by the rules above.", ""]
        md += [f"{i}. **{s['name']}**: " + ", ".join(nm(o) for o in s["pedals"]) for i, s in enumerate(ctx["sections"]["order"], 1)]
    if ctx.get("overrides"):
        md += ["", "### Overridden by priority", ""]
        md += [f"- `{o['winner']}` overrides `{o['loser']}` for: " + "; ".join(o["pairs"]) for o in ctx["overrides"]]
    md += ["", "### Notes per pedal", ""]
    md += [f"- **{pedal_name(pedals[pid])}**: {pedals[pid].get('comments', '')}" for pid in chain]

    md += ["", "## Powering", ""]
    if not ctx["supplies"]:
        md += ["No power supplies assigned yet.", ""]
    else:
        md += ["Every output and the pedals daisy-chained on it, grouped for power (not in signal order); colors are the effect categories, a red border marks an 18V output.", "",
               "```mermaid", *mermaid_power(ctx), "```", ""]
        md += ["Draw figures are the worst-case values in `catalog/pedals.json`. Pedals are daisy-chained by **effect type**, not by chain order: time-based/clocked effects (BBD or digital) never share an output with compressors or gain pedals, a **digital** pedal (including one with a digital processor in an analog path) always has an output to itself, and 18V-capable pedals share 18V outputs. The build checks all three (policy in `project.json`: `power_policy`).", ""]
    grand = 0
    for s in ctx["supplies"]:
        total = sum(r["load"] for r in s["rows"])
        grand += total
        md += [f"### {inst_label(s)}", "", "| Output | Voltage | Pedal | Draw (mA) | Output total |", "|---|--:|---|--:|--:|"]
        for row in s["rows"]:
            odef = row["def"]
            kind = "switchable" if odef and len(odef.get("options", [])) > 1 else "fixed"
            head = f"**{row['port']}** ({kind})"
            cell = f"{row['load']} / {row['limit'] or '?'} mA"
            if not row["pedals"]:
                md.append(f"| {head} | {row['voltage_v']}V | *spare* | 0 | {cell} |")
                continue
            for k, pid in enumerate(row["pedals"]):
                md.append(f"| {head if k == 0 else ''} | {row['voltage_v']}V | {nm(pid)} | "
                          f"{ma(cat_pedals[pid]) if pid in cat_pedals else '?'} | {cell if k == 0 else ''} |")
        md += [f"| | | **{inst_label(s).split(' (')[0]} total** | | **{total} mA** |", ""]
    if ctx["supplies"]:
        md += [f"**All supplies combined:** {grand} mA", ""]
    md += jacks_section(ctx)
    md += routing_section(ctx)
    md += footswitch_section(ctx, cat_pedals)
    md += proposals_section(ctx, cat_pedals)
    return "\n".join(md) + "\n"


KNOWN_LIMITS = [
    "Guitar to first pedal and last pedal to amp cables are not modelled (the guitar and amp positions are not in the layout).",
    "Pedal footprints are the image bounding boxes, so rounded corners count as occupied. Signal and power plugs are modelled from catalog/cables.json (Ernie Ball flat patch plugs and right-angle DC plugs; several head dimensions are estimates, see the `verified` lists there); extra and guitar/amp jacks keep a fixed clearance zone (6.3 mm outward, 7 mm to each side by default), power jacks without `cables.power_type` the smaller `jacks.power_clearance` zone.",
    "Extra jacks (Exp, Tap, Thru, Stereo, XLR ...) are in the catalog for a complete description only; add one to a project's `jacks.extra_used` when it is actually plugged in, so its cable space is checked.",
    "Jack points were placed by hand: re-check any pedal whose zone shows more than a few percent on the pedal body in the pedal editor (the PolyTune 3 was marked before the edge-of-jack guidance).",
]
DATA_TO_VERIFY = [
    "Power specs re-checked on 2026-10-21; still retailer-only or unpublished: Sun Face current (1 mA unverified), Full-Drive 2 and Mini Ego current, E-Lady, Danelectro 3699 and Carbon Copy figures, and the maximum voltage of most 9V pedals (their 9V is a rating, not an explicit limit).",
    "PastFX Reticon: the 50 mA draw and isolated-supply need come from search snippets of the maker's pages.",
    "Browne Protein V3 current: 130 mA planned (manual says under 100 mA, a Q&A line says 130 mA, retailers about 30 mA). The price in the catalog is for the V4.",
    "Version assumptions: Retrovibe is priced and measured as the mk.4; the layout uses the Mini Beano Boost and the PolyTune 3 Mini Noir while the catalog entries are the Beano Boost and PolyTune 3.",
    "The third Ojai R30 for the practice board is not bought (see Shopping list); the Harley Benton ISO-5 Pro has no Pedal Playground entry, so it never appears in a layout.",
]


def open_issues(ctxs, jacks_data):
    """README section: what is still open, computed from the data where possible."""
    md = ["", "## Open issues", ""]
    for c in ctxs:
        items = []
        for cid, cmd in c.get("jack_fixes", []):
            items.append(f"Jacks not set up for `{cid}`: `{cmd}`")
        for v in c.get("violations", []):
            items.append(f"Blocked cable space: `{v['jack']}` is blocked by {v['obstacle']} ({violation_where(v)}); move one of the pedals apart")
        for note in c.get("jack_notes", []):
            items.append(note[0].upper() + note[1:])
        if c.get("footswitch_fixes"):
            items.append(f"Footswitches not placed for {len(c['footswitch_fixes'])} pedal(s): "
                         f"`{footswitches.COMMAND} --list-missing {c['key']} --only footswitches`")
        for r in c.get("footswitch_pairs") or []:
            if r["too_close"]:
                items.append(f"Footswitches too close: `{r['a']}` and `{r['b']}` are {r['distance_mm']:.1f} mm apart "
                             f"(min {c['footswitch_settings']['min_distance_mm']:.1f} mm)")
        if items:
            md += [f"### {c['project'].get('name') or c['key']}", ""] + [f"- {i}" for i in items] + [""]
    md += ["### Known limitations", ""] + [f"- {i}" for i in KNOWN_LIMITS]
    md += ["", "### Data to verify", ""] + [f"- {i}" for i in DATA_TO_VERIFY]
    return md


def root_readme(ctxs, cat_pedals, cat_supplies, jacks_data):
    md = [
        "# Pedalboard planner",
        "",
        "> Generated by `scripts/build.py`. Edit `catalog/` and `projects/*/project.json`, not this file.",
        "",
        "One shared catalog of pedals and power supplies, plus one folder per pedalboard (a *project*).",
        "",
        "```",
        "catalog/pedals.json           everything that is part of a pedal (specs, bypass, digital, tags, intrinsic rules)",
        "catalog/power_supplies.json   supply models: outputs, voltages, current limits, how many you own",
        "catalog/jacks.json           jack positions per pedal/supply (fractions of the Pedal Playground image, mm in reports)",
        "catalog/footswitches.json    footswitch positions per pedal ([] = no footswitch; spacing checked on the layout)",
        "projects/<name>/project.json  everything that can change: board, chain order, project rules, power wiring",
        "projects/<name>/README.md     generated plan, signal-chain and power diagrams, power summary",
        "projects/<name>/playground.json   generated Pedal Playground layout (scripts/to_playground.py)",
        "```",
        "",
        "```",
        "uv sync                                      once: .venv with the dependencies (pyproject.toml, uv.lock)",
        "uv run scripts/build.py [project...]        validate + regenerate docs",
        "uv run scripts/to_playground.py [project...] write projects/<name>/playground.json",
        "uv run scripts/new_project.py <name> --instrument guitar|bass",
        "uv run scripts/pedal_editor.py <catalog id> [--footswitches]   place a pedal's jacks / footswitches on its image (--list-missing [--only jacks|footswitches] shows what is left)",
        "uv run scripts/propose_layout.py <project> [--max-change fix|rearrange|free]   layout proposals (projects/<name>/proposals/, shown in the README)",
        "uv run pytest tests                       geometry and jack-check tests",
        "```",
        "",
        "Footswitches: switches of different pedals must be at least `footswitches.min_distance_mm` apart (default \"auto\" = the smallest distance in the owner's playground_design.json). Missing footswitch data and pairs that are too close are warnings unless `validation.require_footswitches` / `validation.strict_footswitches` are set.",
        "",
        "Every project has `validation.no_unknown` on by default: any missing (`null`) value for a pedal, supply or board the project uses fails the build until you fill it in.",
        "",
        "Jacks: pedals with no jack setup, and cable space blocked in `playground_design.json`, are warnings by default; set `validation.require_jacks` / `validation.strict_clearance` to make them errors. "
        "Signal jacks are checked against the plug head of the project's patch cable type (`cables.type`, catalog/cables.json) on the exit side the router chose, "
        "power jacks against the DC plug type (`cables.power_type`) on the less blocked side (or the small `jacks.power_clearance` zone without one); "
        "other jacks use the fixed zone `jacks.clearance.outward_mm` / `side_mm` (default 6.3 / 7 mm). All cable figures are in mm.",
        "",
        "## Projects",
        "",
        "| Project | Instrument | Board | Pedals | Supplies | Status |",
        "|---|---|---|--:|---|---|",
    ]
    usage, sup_usage = {}, {}
    for c in ctxs:
        pr = c["project"]
        for pid in c["chain"]:
            usage.setdefault(pid, []).append(c["key"])
        for sid, n in c["instances"].items():
            sup_usage.setdefault(sid, []).append((c["key"], n))
        sups = ", ".join(f"{n} x {sup_name(cat_supplies[s])}" for s, n in c["instances"].items()) or "none yet"
        status = "OK" if not c["errors"] else f"**{len(c['errors'])} error(s)**"
        md.append(f"| [{pr.get('name') or c['key']}](projects/{c['key']}/README.md) | {pr.get('instrument') or '?'} | "
                  f"{board_text(pr.get('board') or {})} | {len(c['chain'])} | {sups} | {status}, {len(c['warnings'])} warning(s) |")
    if not ctxs:
        md.append("| *(none yet)* | | | | | |")

    md += open_issues(ctxs, jacks_data)

    # shared gear
    shared, global_warn = [], []
    for pid, users in usage.items():
        q = effective_quantity(cat_pedals[pid])
        if len(users) > 1 and (q is None or q < len(users)):
            shared.append(f"- **{pedal_name(cat_pedals[pid])}** is in {', '.join(users)} but you own {'an unknown number' if q is None else q}")
    for sid, uses in sup_usage.items():
        q, total = cat_supplies[sid].get("quantity"), sum(n for _, n in uses)
        if len(uses) > 1 and (q is None or total > q):
            shared.append(f"- **{sup_name(cat_supplies[sid])}**: projects use {total} units ({', '.join(f'{k}: {n}' for k, n in uses)}) but you own {q if q is not None else 'an unknown number'}")
    md += ["", "## Shared gear", ""]
    md += shared or ["No pedal or supply is claimed by more than one project beyond what you own."]
    global_warn += [s[2:] for s in shared]

    # shopping
    buy, unknown_owned, total_price, no_price = [], [], 0, 0
    for pid, users in usage.items():
        p = cat_pedals[pid]
        q = effective_quantity(p)
        if q is None:
            unknown_owned.append(f"{pedal_name(p)} ({', '.join(users)})")
            continue
        need = max(0, len(users) - q)
        if need:
            price = p.get("price_eur")
            total_price += (price or 0) * need
            no_price += price is None
            buy.append(f"| {pedal_name(p)} | {need} | {', '.join(users)} | {'-' if price is None else f'{price} EUR'} |")
    def price_cell(price):
        return "-" if price is None else f"{price} EUR"

    for sid, uses in sup_usage.items():
        q, units = cat_supplies[sid].get("quantity"), sum(n for _, n in uses)
        if q is not None and units > q:
            need, price = units - q, cat_supplies[sid].get("price_eur")
            total_price += (price or 0) * need
            no_price += price is None
            buy.append(f"| {sup_name(cat_supplies[sid])} (power supply) | {need} | {', '.join(k for k, _ in uses)} | {price_cell(price)} |")
    for c in ctxs:
        b = c["project"].get("board") or {}
        if b.get("owned") is False:
            total_price += b.get("price_eur") or 0
            no_price += b.get("price_eur") is None
            buy.append(f"| {b.get('brand')} {b.get('model')} (board) | 1 | {c['key']} | {price_cell(b.get('price_eur'))} |")
    md += ["", "## Shopping list", ""]
    if buy:
        md += ["| Pedal | Units | Needed by | Price |", "|---|--:|---|--:|", *buy, "",
               f"**Known total:** {total_price} EUR" + (f" ({no_price} item(s) without a `price_eur`)" if no_price else "")]
    else:
        md += ["Nothing to buy for the current projects."]
    if unknown_owned:
        md += ["", "**Ownership unknown (fill in `owned`):** " + "; ".join(unknown_owned)]

    # catalog not placed anywhere
    free = [pedal_name(p) for pid, p in cat_pedals.items() if pid not in usage]
    md += ["", "## Catalog pedals not in any project", "", ", ".join(free) or "None.", ""]
    return "\n".join(md) + "\n", global_warn


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("projects", nargs="*", help="project folder names (default: all)")
    args = ap.parse_args()

    cat_pedals, cat_supplies = load_catalog()
    jacks_file = jacks.read_file()
    fs_file = footswitches.read_file()
    ctxs = []
    for pdir in project_dirs(args.projects or None):
        ctx = validate(pdir, cat_pedals, cat_supplies, jacks_file["jacks"], footswitch_data=fs_file["footswitches"])
        (pdir / "README.md").write_text(project_readme(ctx, cat_pedals))
        (pdir / "signal-chain.mmd").write_text("\n".join(mermaid_signal(ctx)) + "\n")
        (pdir / "power.mmd").write_text("\n".join(mermaid_power(ctx)) + "\n")
        picture = routing.svg(ctx, {pid: cat_pedals[pid]["name"] for pid in ctx["chain"]})
        if picture:
            (pdir / "cables.svg").write_text(picture)
        else:
            (pdir / "cables.svg").unlink(missing_ok=True)
        (pdir / "diagram.mmd").unlink(missing_ok=True)
        ctxs.append(ctx)
    if args.projects:  # keep the root index complete when building a subset
        ctxs = [validate(d, cat_pedals, cat_supplies, jacks_file["jacks"], footswitch_data=fs_file["footswitches"])
                for d in project_dirs()]
    text, global_warn = root_readme(ctxs, cat_pedals, cat_supplies, jacks_file["jacks"])
    (ROOT / "README.md").write_text(text)

    bad = False
    for c in ctxs:
        if args.projects and c["key"] not in args.projects:
            continue
        print(f"== {c['key']}: {len(c['chain'])} pedals")
        for s in c["supplies"]:
            print(f"  {inst_label(s)}")
            for r in s["rows"]:
                print(f"    {r['id']:12} {r['voltage_v']:>2}V {r['load']:>4}/{r['limit'] or '?'} mA  {', '.join(r['pedals']) or '(spare)'}")
        for m in c["warnings"]:
            print("  WARN ", m)
        for m in c["errors"]:
            print("  ERROR", m)
        if c.get("jack_fixes"):
            print("  to fix jacks:")
            for _, cmd in c["jack_fixes"]:
                print("    ", cmd)
        bad |= bool(c["errors"])
    for m in global_warn:
        print("WARN  shared:", m)
    for cid, msgs in jacks.validate_jacks_file(jacks_file, cat_pedals, cat_supplies).items():
        for m in msgs:
            print(f"WARN  catalog/jacks.json {cid}: {m}")
    for cid, msgs in footswitches.validate_file(fs_file, cat_pedals, cat_supplies).items():
        for m in msgs:
            print(f"WARN  catalog/footswitches.json {cid}: {m}")
    print("OK" if not bad else "FAILED")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
