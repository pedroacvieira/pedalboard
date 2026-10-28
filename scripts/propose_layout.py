#!/usr/bin/env python3
"""Propose better pedal positions for a project's Pedal Playground layout (never writes playground_design.json).

    uv run scripts/propose_layout.py guitar-gig                         # fix level: small moves, no swaps
    uv run scripts/propose_layout.py guitar-gig --max-change rearrange  # larger moves, swaps, rotations
    uv run scripts/propose_layout.py guitar-gig --score                 # term breakdown of the owner's layout
    options: --max-change fix|rearrange|free  --max-move-mm MM|none  --seed S  --iterations N  --restarts R
             --top N (default 3)  --pin ID ...  --dry-run

The search (scripts/layout.py: simulated annealing + greedy polish on a surrogate score, deterministic for a seed
and iteration budget) yields distinct finalists. Each finalist gets its own power wiring (power.assign: supply
outputs and daisy chains for the shortest DC cable under the power policy) and is checked with the real pipeline
(build.validate with the injected layout: plug clearance, routed cables, footswitch spacing). A finalist becomes a
proposal only if it is not worse than the owner's layout on blocked plugs, plug collisions, routing problems (unroutable, squeezed,
over the stacking or plug limit) and footswitch pairs below the minimum, and better overall (lexicographic: blocked plugs,
blocked mm, plug collisions, routing problems, footswitch pairs, final score = surrogate with the routed signal length and router
penalties).

Output in projects/<name>/proposals/: <n>.json (Pedal Playground "Load from File": the owner's canvas with only the
moved pedals' left/top/rotation changed), <n>.svg (proposal with the owner's positions dashed and arrows), and
meta.json (scores, moved pedals, power wiring, command, seed; read by build.py for the README).
"""
import argparse
import copy
import json
import sys
import time

import boards
import build
import design
import footswitches
import jacks
import layout
import outlines
import power
import routing
import svgdraw
from common import load_cable_types, load_catalog, load_json, project_dirs, proposal_inputs_sha1

META = "meta.json"


def metrics(ctx, model, state, move_factor):
    """Real-pipeline figures of one checked layout + its surrogate score."""
    sig = [c for c in ctx.get("cable_list") or [] if c["kind"] == "signal"]
    pw = [c for c in ctx.get("cable_list") or [] if c["kind"] == "power"]
    status = [c["status"] for c in sig]
    prs = ctx.get("footswitch_pairs") or []
    total, det = model.score(state, detail=True, move_factor=move_factor)
    out = {
        "errors": len(ctx["errors"]), "warnings": len(ctx["warnings"]),
        "blocked": len(ctx["violations"]), "blocked_mm": round(sum(v["depth_mm"] for v in ctx["violations"]), 1),
        "blocked_jacks": sorted({v["jack"] for v in ctx["violations"]}),
        "collisions": len(ctx.get("plug_collisions") or []),
        "unroutable": sum(s.startswith("unroutable") for s in status), "squeezed": sum("squeezed" in s for s in status),
        "overflow": sum("stacking limit" in s or "plug limit" in s for s in status),
        # toppers are a finishing step the search ignores: proposals are compared on the PLAIN distances
        "fs_close": sum(1 for r in prs if r.get("too_close_plain")),
        "fs_closest_mm": round(min(r["distance_mm"] for r in prs), 1) if prs else None,
        "fs_crowding": round((ctx.get("footswitch_settings") or {}).get("crowding_plain") or 0.0, 1),
        "fs_known": det["fs_known"],
        "signal_mm": round(sum(c["min_mm"] for c in sig if c["min_mm"] is not None), 1),
        "signal_routed": sum(1 for c in sig if c["min_mm"] is not None), "signal_cables": len(sig),
        "power_mm": round(sum(c["min_mm"] for c in pw if c["min_mm"] is not None), 1),   # routed power cables only
        "power_unrouted": sum(1 for c in pw if c["min_mm"] is None),                      # (their length is not in power_mm)
        "io_mm": round(det["terms"]["io"][0], 1),
        "surrogate": round(total, 1),
        "terms": {k: round(v[1], 1) for k, v in det["terms"].items()},
    }
    # final score: the surrogate with the routed signal length instead of its obstacle-free estimate, plus router
    # penalties (unroutable 1000, over the stacking limit 50, squeezed 100 per cable)
    w = model.w
    real = out["signal_mm"] + sum(det["signal"].get(c["id"], 0.0) for c in sig if c["min_mm"] is None)
    out["score"] = round(total - det["terms"]["signal"][1] + w["signal"] * real + 1000 * out["unroutable"]
                         + 50 * out["overflow"] + 100 * out["squeezed"], 1)
    return out


def routing_problems(m):
    return m["unroutable"] + m["squeezed"] + m["overflow"]


def rank_key(m):
    return (m["errors"], m["blocked"], m["blocked_mm"], m.get("collisions", 0), routing_problems(m), m["fs_close"], m["score"])


def acceptable(m, owner):
    """Not worse than the owner's layout on errors, blocked plugs, routing and footswitch pairs; better overall."""
    return (m["errors"] <= owner["errors"] and m["blocked"] <= owner["blocked"]
            and m.get("collisions", 0) <= owner.get("collisions", 0)
            and routing_problems(m) <= routing_problems(owner) and m["fs_close"] <= owner["fs_close"]
            and rank_key(m) < rank_key(owner))


def moved_list(model, state):
    out = []
    for n, (st, own) in enumerate(zip(state, model.owner)):
        dx, dy = st[0] - own[0], st[1] - own[1]
        if abs(dx) > 0.01 or abs(dy) > 0.01 or st[2] != own[2]:
            out.append({"pedal": model.ids[n], **({"name": model.names[model.ids[n]]} if n >= model.n_ped else {}), "dx_mm": round(dx, 1), "dy_mm": round(dy, 1),
                        "distance_mm": round((dx * dx + dy * dy) ** 0.5, 1), "rot_from": own[2], "rot_to": st[2]})
    return out


def evaluate(pdir, project, model, state, owner_ctx, cat, move_factor, board_data=None, board_edits=None):
    """(metrics, ctx, wiring) of a candidate: its own power wiring, then build.validate with the injected layout.
    `board_data` / `board_edits`: catalog/boards.json and the project's board.json, read once by the caller."""
    cat_pedals, cat_supplies, jacks_data, fs_data, outl = cat
    items = model.items_for(state)
    lay = jacks.layout_from_items(items, owner_ctx["chain"], owner_ctx["supplies"], cat_pedals, cat_supplies,
                                  project.get("jacks", {}), [], [], outlines=outl, board_data=board_data, board_edits=board_edits)
    insts = [{"id": s["inst"]["id"], "supply": s["sup"]["id"], "label": s["inst"].get("label"), "sup": s["sup"],
              "under": lay["inst_placement"].get(s["inst"]["id"]) != "on_board"} for s in owner_ctx["supplies"]]
    pts, ports = power.measure_points(lay["placed"], lay["inst_item"], insts, jacks.usable(jacks_data), model.p_depth)
    # power cables run under the board: the model's nearest-hole setup (the holes free under the board; the under-board supplies
    # do not move), minus the hole points this candidate's pedals cover
    setup = model.power_setup
    holes = cfg = None
    if setup:
        rects = [r for it in [*lay["placed"].values(), *lay["obstacles"]] for r in design.item_shapes(lay["shapes"], it)]
        holes, cfg = power.usable_holes(setup, rects), setup["cfg"]
    start = {s["inst"]["id"]: s["inst"].get("outputs", []) for s in owner_ctx["supplies"]}
    try:
        wiring = power.assign(owner_ctx["chain"], owner_ctx["pedals"], insts, project, pts, ports,
                              run_v=owner_ctx["run_v"], start=start, holes=holes, cfg=cfg)
        proj = copy.deepcopy(project)
        old = project.get("power", {}).get("supplies", [])
        place = {x["id"]: x["placement"] for x in old if "placement" in x}   # assign drops it: an on-board supply stays one
        proj["power"] = {**proj.get("power", {}), "supplies": [{**x, **({"placement": place[x["id"]]} if x["id"] in place else {})}
                                                               for x in wiring["supplies"]]}
        cab = proj.setdefault("cables", {})
        cab["overrides"] = power.remap_overrides(cab.get("overrides") or {}, old, wiring["supplies"])
    except ValueError as e:   # keep the owner's wiring
        wiring, proj = {"supplies": project.get("power", {}).get("supplies", []), "error": str(e)}, project
    ctx = build.validate(pdir, cat_pedals, cat_supplies, jacks_data, items=items, footswitch_data=fs_data, project=proj,
                         outline_data=outl, board_data=board_data)
    keep = model.wiring
    under = {i["id"]: i["under"] for i in insts}
    model.set_wiring([(ports.get((s["id"], o["port"])), o["pedals"], under.get(s["id"], True), (s["id"], o["port"]),
                       routing.daisy_style(project, o))
                      for s in wiring["supplies"] for o in s["outputs"]])
    m = metrics(ctx, model, state, move_factor)
    model.wiring = keep
    return m, ctx, wiring


def overlay(model, state, moved):
    """SVG elements: the owner's footprints of the moved pedals (dashed), the new ones highlighted, arrows."""
    out = ['<defs><marker id="arr" viewBox="0 0 6 6" refX="5" refY="3" markerWidth="5" markerHeight="5" orient="auto">'
           '<path d="M0,0 L6,3 L0,6 z" fill="#e65100"/></marker></defs>']
    for mv in moved:
        n = model.index[mv["pedal"]]
        old, new = model.footprint(model.owner[n], n), model.footprint(state[n], n)
        out.append(f'<rect x="{old[0]:.1f}" y="{old[1]:.1f}" width="{old[2] - old[0]:.1f}" height="{old[3] - old[1]:.1f}" '
                   f'fill="none" stroke="#757575" stroke-width="0.8" stroke-dasharray="3 2"/>')
        out.append(f'<rect x="{new[0]:.1f}" y="{new[1]:.1f}" width="{new[2] - new[0]:.1f}" height="{new[3] - new[1]:.1f}" '
                   f'fill="#ffe0b2" opacity="0.35" stroke="#e65100" stroke-width="1.2"/>')
        (ox, oy), (nx, ny) = model.owner[n][:2], state[n][:2]
        if mv["distance_mm"] >= 1:
            out.append(f'<line x1="{ox:.1f}" y1="{oy:.1f}" x2="{nx:.1f}" y2="{ny:.1f}" stroke="#e65100" stroke-width="1" '
                       f'marker-end="url(#arr)"/>')
        rot = f", {mv['rot_from']}->{mv['rot_to']} deg" if mv["rot_from"] != mv["rot_to"] else ""
        out.append(f'<text x="{nx:.1f}" y="{ny + 9:.1f}" font-size="6" text-anchor="middle" fill="#e65100">'
                   f'{mv["name"] + ": " if mv.get("name") else ""}{mv["distance_mm"]:.0f} mm{rot}</text>')
    return out


def print_score(model, owner_ctx):
    total, det = model.score(model.owner, detail=True)
    print(f"Surrogate score of the owner's layout: {total:.1f} (lower is better; weights: project layout.weights)")
    print(f"  {'term':14} {'raw':>10} {'weighted':>10}")
    units = {"clearance": "mm", "routing_area": "exits", "signal": "mm", "power": "mm", "footswitch": "mm", "io": "mm",
             "flow": "mm", "access": "mm x w", "rotation": "pedals", "move": "mm", "touch": "mm"}
    for k, (raw, wt) in det["terms"].items():
        print(f"  {k:14} {raw:>10.1f} {wt:>10.1f}  {units.get(k, '')}")
    _, real = model.score(model.owner, margin=0, detail=True)
    print(f"Blocked plugs (no margin, as the build): {len(real['blocked'])}")
    for b in real["blocked"]:
        print(f"  {b['jack']} by {b['obstacle']}: {b['depth_mm']:.1f} mm into the {b['part']} (exit {b['side'] or '-'})")
    print(f"Plug collisions (no margin, as the build): {len(real['collisions'])}")
    for c in real["collisions"]:
        print(f"  {c['jack']} with {c['with']}: {c['depth_mm']:.1f} mm")
    print(f"Clearance raw = penetration of the plug parts grown by the {model.cfg['clearance_margin_mm']:g} mm margin "
          f"({real['terms']['clearance'][0]:.1f} mm without the margin)")
    if not model.fs_known:
        print("Footswitch term: 0 (no footswitch data for these pedals yet)")
    else:
        lim = "none" if model.fs_limit is None else f"{model.fs_limit:g} mm"
        print(f"Footswitch crowding {det['terms']['footswitch'][0]:.1f} (comfort {model.fs_comfort:g} mm); "
              f"minimum {lim}, pairs closer: {len(det['fs_close'])}")
    print(f"Build check of the owner's layout: {len(owner_ctx['violations'])} blocked plug(s), "
          f"{len(owner_ctx.get('plug_collisions') or [])} plug collision(s), {len(owner_ctx['errors'])} error(s), {len(owner_ctx['warnings'])} warning(s)")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("project")
    ap.add_argument("--score", action="store_true", help="print the term breakdown of the owner's layout and exit")
    ap.add_argument("--max-change", choices=list(layout.LEVELS), default=None)
    ap.add_argument("--max-move-mm", default=None, help="hard limit per pedal (mm) or 'none'; default: the level's")
    ap.add_argument("--seed", type=int, default=None)
    ap.add_argument("--iterations", type=int, default=None, help="annealing iterations per restart")
    ap.add_argument("--restarts", type=int, default=None)
    ap.add_argument("--top", type=int, default=None, help="proposals to write (default 3)")
    ap.add_argument("--pin", nargs="*", default=[], help="pedals that must not move")
    ap.add_argument("--dry-run", action="store_true", help="search and report, write nothing")
    args = ap.parse_args(argv)

    (pdir,) = project_dirs([args.project])
    if not (pdir / "playground_design.json").exists():
        sys.exit(f"{pdir.name} has no playground_design.json: make a layout in Pedal Playground first "
                 f"(scripts/to_playground.py gives a starting file), save it there, then rerun")
    t0 = time.monotonic()
    cat_pedals, cat_supplies = load_catalog()
    jacks_data, fs_data = jacks.read_file()["jacks"], footswitches.read_file()["footswitches"]
    outl = outlines.load()   # read once: the owner's layout, the model and every finalist use it
    board_data, board_edits = boards.load(), boards.load_edits(pdir)   # likewise (catalog/boards.json, the project's board.json)
    cat = (cat_pedals, cat_supplies, jacks_data, fs_data, outl)
    project = load_json(pdir / "project.json")
    if args.pin:
        project.setdefault("layout", {})["pins"] = sorted(set(project.get("layout", {}).get("pins", [])) | set(args.pin))
    design_doc = load_json(pdir / "playground_design.json")
    items = design.parse_canvas(design_doc["canvas"])
    cable_types = load_cable_types()
    owner_ctx = build.validate(pdir, cat_pedals, cat_supplies, jacks_data, footswitch_data=fs_data, project=project,
                               outline_data=outl, board_data=board_data)
    try:
        model = layout.Model(project, items, cat_pedals, cat_supplies, jacks_data, fs_data, cable_types, outlines=outl,
                             board_data=board_data, board_edits=board_edits)
    except ValueError as e:
        sys.exit(f"{pdir.name}: {e}")
    if args.score:
        print_score(model, owner_ctx)
        return 0

    cfg = model.cfg
    level = args.max_change or cfg.get("max_change", "fix")
    mm = cfg.get("max_move_mm", "level") if args.max_move_mm is None else (None if args.max_move_mm == "none" else float(args.max_move_mm))
    seed = cfg["search"]["seed"] if args.seed is None else args.seed
    iterations = args.iterations or cfg["search"].get("iterations")
    restarts = args.restarts or cfg["search"].get("restarts")
    top = args.top or cfg["search"].get("top", 3)
    lv = layout.level_settings(model, level, mm)
    print(f"== {pdir.name}: max_change {level}, max move {lv['max_move_mm'] if lv['max_move_mm'] is not None else 'none'} mm, "
          f"seed {seed}, {iterations or lv['iterations']} iterations x {restarts or lv['restarts']} restarts")
    found = layout.search(model, level, seed=seed, iterations=iterations, restarts=restarts, max_move_mm=mm,
                          time_limit_s=cfg["search"].get("time_limit_s"), log=print)
    mf = lv["move_factor"]
    # the owner's layout is compared with its own computed wiring, as every finalist: a proposal must win on positions
    owner_m, _, owner_wiring = evaluate(pdir, project, model, model.owner, owner_ctx, cat, mf, board_data, board_edits)
    finals = []
    for _, state in found:
        moved = moved_list(model, state)
        if not moved:
            continue
        m, ctx, wiring = evaluate(pdir, project, model, state, owner_ctx, cat, mf, board_data, board_edits)
        finals.append({"state": state, "metrics": m, "ctx": ctx, "wiring": wiring, "moved": moved, "ok": acceptable(m, owner_m)})
    finals.sort(key=lambda f: rank_key(f["metrics"]))
    chosen = [f for f in finals if f["ok"]][:top]
    runtime = time.monotonic() - t0

    cmd = ["uv run scripts/propose_layout.py", pdir.name, "--max-change", level, "--seed", str(seed)]
    for flag, val in (("--max-move-mm", args.max_move_mm), ("--iterations", args.iterations), ("--restarts", args.restarts),
                      ("--top", args.top)):
        if val is not None:
            cmd += [flag, str(val)]
    if args.pin:
        cmd += ["--pin", *args.pin]
    meta = {"_doc": "Generated by scripts/propose_layout.py; read by scripts/build.py (README 'Layout proposals'). Do not edit.",
            "command": " ".join(cmd), "max_change": level, "max_move_mm": lv["max_move_mm"], "seed": seed,
            "iterations": iterations or lv["iterations"], "restarts": restarts or lv["restarts"],
            "inputs_sha1": proposal_inputs_sha1(pdir), "chain": owner_ctx["chain"], "runtime_s": round(runtime, 1),
            "finalists": len(finals), "owner": owner_m,
            "owner_power": {"supplies": owner_wiring["supplies"], "length_mm": round(owner_wiring.get("length_mm", 0), 1),
                            "error": owner_wiring.get("error")}, "proposals": []}
    for n, f in enumerate(chosen, 1):
        meta["proposals"].append({"n": n, "file": f"{n}.json", "svg": f"{n}.svg", "metrics": f["metrics"], "moved": f["moved"],
                                  "power": {"supplies": f["wiring"]["supplies"], "length_mm": round(f["wiring"].get("length_mm", 0), 1),
                                            "warnings": f["wiring"].get("warnings", []), "error": f["wiring"].get("error")}})

    report(pdir, meta, owner_m)
    if args.dry_run:
        print("(dry run: nothing written)")
        return 0
    out = pdir / "proposals"
    out.mkdir(exist_ok=True)
    for old in list(out.glob("*.json")) + list(out.glob("*.svg")):
        old.unlink()
    names = {pid: cat_pedals[pid]["name"] for pid in owner_ctx["chain"]}
    for f, pm in zip(chosen, meta["proposals"]):
        items_new = model.items_for(f["state"])
        moved_ids = {model.mitem[mv["pedal"]]["id"] for mv in f["moved"]}
        canvas = design.write_canvas(design_doc["canvas"], [i for i in items_new if i["id"] in moved_ids])
        (out / pm["file"]).write_text(json.dumps({**design_doc, "canvas": canvas}))
        picture = svgdraw.render(f["ctx"], names, overlay=overlay(model, f["state"], f["moved"]),
                              legend="orange: moved pedals (dashed grey: the owner's position, arrow: the move)")
        if picture:
            (out / pm["svg"]).write_text(picture)
    (out / META).write_text(json.dumps(meta, indent=1) + "\n")
    print(f"wrote {len(chosen)} proposal(s) to {out.relative_to(pdir.parent.parent)}/ ; run scripts/build.py {pdir.name} for the README")
    return 0


def unrouted(m):
    """' (+2 not routed)': the power cables whose length is not in `power_mm`."""
    return f" (+{m['power_unrouted']} not routed)" if m.get("power_unrouted") else ""


def report(pdir, meta, owner):
    def line(label, m):
        fs = ("no footswitch data" if not m["fs_known"] else
              f"crowding {m['fs_crowding']:.0f}, closest {m['fs_closest_mm']} mm, {m['fs_close']} below the minimum")
        return (f"  {label:9} blocked {m['blocked']} ({m['blocked_mm']:.1f} mm) {m['blocked_jacks']}; plug collisions "
                f"{m.get('collisions', 0)}; routing problems "
                f"{routing_problems(m)}; signal {m['signal_mm']:.0f} mm ({m['signal_routed']}/{m['signal_cables']} routed); "
                f"power {m['power_mm']:.0f} mm routed{unrouted(m)}; footswitch term {m['terms']['footswitch']:.0f} ({fs}); score {m['score']:.1f}")
    print(line("owner", owner))
    if not meta["proposals"]:
        print(f"  no better layout found ({meta['finalists']} finalist(s) checked)")
    for p in meta["proposals"]:
        print(line(f"#{p['n']}", p["metrics"]))
        for mv in p["moved"]:
            rot = f", rotation {mv['rot_from']} -> {mv['rot_to']}" if mv["rot_from"] != mv["rot_to"] else ""
            print(f"      {mv['pedal']:16} dx {mv['dx_mm']:+6.1f}  dy {mv['dy_mm']:+6.1f}  = {mv['distance_mm']:5.1f} mm{rot}")
        gone = sorted(set(owner["blocked_jacks"]) - set(p["metrics"]["blocked_jacks"]))
        if gone:
            print(f"      findings gone: {', '.join(gone)}")
    print(f"  runtime {meta['runtime_s']:.1f} s")


if __name__ == "__main__":
    sys.exit(main())
