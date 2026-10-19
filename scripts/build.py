#!/usr/bin/env python3
"""Validate data/pedals.json + data/board.json; regenerate output/pedalboard.mmd and README.md."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA, OUT = ROOT / "data", ROOT / "output"
pedals = {p["id"]: p for p in json.loads((DATA / "pedals.json").read_text())["pedals"]}
board = json.loads((DATA / "board.json").read_text())

errors, warnings = [], []
chain = board["signal_chain"]
pos = {pid: i for i, pid in enumerate(chain)}

# --- signal chain ---------------------------------------------------------
for pid in chain:
    if pid not in pedals:
        errors.append(f"chain: unknown pedal '{pid}'")
unused = [pid for pid in pedals if pid not in pos]  # catalog entries not in the plan
for pid, p in pedals.items():
    if p["on_board"] != (pid in pos):
        errors.append(f"flags: '{pid}' has on_board={p['on_board']} but {'is' if pid in pos else 'is not'} in signal_chain")
if len(set(chain)) != len(chain):
    errors.append("chain: duplicate pedal in signal_chain")

# --- ordering rules -------------------------------------------------------
def violated(pid, r, msg):
    (errors if r["strength"] == "required" else warnings).append(f"order ({r['strength']}): {pid}: {msg}")


for pid in chain:
    if pid not in pedals:
        continue
    for r in pedals[pid]["dependencies"]:
        kind, me = r["type"], pos[pid]
        if kind in ("after", "before"):
            for other in r["pedals"]:
                if other not in pedals:
                    errors.append(f"rules: {pid} refers to unknown pedal '{other}'")
                elif other in pos and (pos[other] > me if kind == "after" else pos[other] < me):
                    violated(pid, r, f"must come {kind} {other}")
        elif kind in ("after_group", "before_group"):
            members = [o for o in chain if o != pid and r["group"] in pedals[o]["tags"]]
            if not members:
                warnings.append(f"rules: {pid}: no on-board pedal has tag '{r['group']}'")
            for other in members:
                if pos[other] > me if kind == "after_group" else pos[other] < me:
                    violated(pid, r, f"must come {kind.split('_')[0]} {other} (tag '{r['group']}')")
        elif kind == "no_buffered_before":
            for other in chain[:me]:
                if pedals[other]["buffered_bypass"] is True:
                    violated(pid, r, f"buffered pedal '{other}' comes before it")
                elif pedals[other]["buffered_bypass"] is None:
                    warnings.append(f"order: {pid}: '{other}' ahead of it has unknown bypass type")
        elif kind == "position":
            if r["value"] == "last" and me != len(chain) - 1:
                violated(pid, r, "must be last in the chain")
            if r["value"] == "first" and me != 0:
                violated(pid, r, "must be first in the chain")
        elif kind == "as_early_as_possible":
            preds = {o for rr in pedals[pid]["dependencies"] if rr["type"] == "after" for o in rr["pedals"] if o in pos}
            extra = [o for o in chain[:me] if o not in preds]
            if extra:
                violated(pid, r, f"could be earlier: {', '.join(extra)} come first but are not required to")
        else:
            errors.append(f"rules: {pid}: unknown rule type '{kind}'")

# --- power ----------------------------------------------------------------
powered = {}
for psu in board["power_supplies"]:
    for out in psu["outputs"]:
        v = out["voltage_v"]
        limit = board["output_limits_ma"][out["type"]].get(str(v))
        if limit is None:
            errors.append(f"{out['id']}: {v}V not available on a {out['type']} output")
            continue
        load = 0
        for pid in out["pedals"]:
            p = pedals[pid]
            if pid in powered:
                errors.append(f"power: '{pid}' is on both {powered[pid]} and {out['id']}")
            powered[pid] = out["id"]
            pc = p["power_consumption"]
            if v not in pc["allowed_voltages_v"]:
                errors.append(f"{out['id']}: {pid} does not accept {v}V (allowed {pc['allowed_voltages_v']})")
            if pc["needs_isolated_output"] and len(out["pedals"]) > 1:
                errors.append(f"{out['id']}: {pid} needs an isolated output but shares it")
            if pc["current_ma"] is None:
                errors.append(f"{out['id']}: {pid} has unknown current_ma")
                continue
            load += pc["current_ma"]
        out["_load"], out["_limit"] = load, limit
        if len(out["pedals"]) > 1:
            for pid in out["pedals"]:
                if pedals[pid]["digital"] is True:
                    errors.append(f"{out['id']}: digital pedal '{pid}' shares an output with {[o for o in out['pedals'] if o != pid]}")
                elif pedals[pid]["digital"] is None:
                    warnings.append(f"{out['id']}: '{pid}' shares an output but its digital status is unknown")
        if load > limit:
            errors.append(f"{out['id']}: {load} mA exceeds {limit} mA limit")
        elif load > 0.8 * limit:
            warnings.append(f"{out['id']}: {load} mA is over 80% of {limit} mA")
for pid in chain:
    if pid not in powered:
        errors.append(f"power: '{pid}' has no power output")

# --- mermaid --------------------------------------------------------------
def label(pid):
    p = pedals[pid]
    return f"{p['brand']} {p['name']}<br/>{p['power_consumption']['current_ma']} mA"

lines = ["flowchart TB", '    guitar(["' + board["input"] + '"])', '    amp(["' + board["output"] + '"])']
for pid in chain:
    lines.append(f'    {pid}["{label(pid)}"]')

links = [("guitar", chain[0])] + list(zip(chain, chain[1:])) + [(chain[-1], "amp")]
for a, b in links:
    lines.append(f"    {a} --> {b}")
n_signal = len(links)

power_edges = 0
for psu in board["power_supplies"]:
    lines.append(f'    subgraph {psu["id"]}["{psu["label"]}"]')
    for out in psu["outputs"]:
        used = out["_load"]
        text = f'{out["id"].split("_", 1)[1].upper()} · {out["voltage_v"]}V<br/>{used}/{out["_limit"]} mA'
        if not out["pedals"]:
            text += "<br/>spare"
        lines.append(f'        {out["id"]}["{text}"]')
    lines.append("    end")
    for out in psu["outputs"]:
        if not out["pedals"]:
            continue
        lines.append(f'    {out["id"]} -.-> {out["pedals"][0]}')
        power_edges += 1
        for a, b in zip(out["pedals"], out["pedals"][1:]):
            lines.append(f"    {a} -.->|daisy| {b}")
            power_edges += 1

power_idx = ",".join(str(i) for i in range(n_signal, n_signal + power_edges))
lines.append(f"    linkStyle {power_idx} stroke:#c0392b,stroke-width:1.5px,color:#c0392b")
for psu in board["power_supplies"]:
    lines.append(f"    style {psu['id']} fill:none,stroke:#c0392b,stroke-dasharray:4 3")

(OUT / "pedalboard.mmd").write_text("\n".join(lines) + "\n")

# --- README ---------------------------------------------------------------
def nm(pid):
    return f"{pedals[pid]['brand']} {pedals[pid]['name']}"


def yn(v):
    return "Unknown" if v is None else ("Yes" if v else "No")


def bypass(p):
    b, sw = p["buffered_bypass"], p["buffer_switchable"]
    if b is None:
        return "Unknown"
    return ("Buffered" if b else "True") + (" (switchable)" if sw else "")


def power(p):
    pc = p["power_consumption"]
    ma = "?" if pc["current_ma"] is None else pc["current_ma"]
    return f"{pc['voltage_v']}V, {ma} mA"


def short(psu):
    return psu["label"].split(" (")[0]


def code(out):
    return out["id"].split("_", 1)[1].upper()


feeds = {}  # pedal id -> "Ojai R30 #1 · F2"
for psu in board["power_supplies"]:
    for out in psu["outputs"]:
        for pid in out["pedals"]:
            feeds[pid] = f"{short(psu)} · {code(out)}"

RULE_TEXT = {
    "after": lambda r: "must come after " + ", ".join(nm(o) for o in r["pedals"]),
    "before": lambda r: "must come before " + ", ".join(nm(o) for o in r["pedals"]),
    "after_group": lambda r: f"must come after all `{r['group']}` pedals",
    "before_group": lambda r: f"must come before all `{r['group']}` pedals",
    "no_buffered_before": lambda r: "no buffered pedal anywhere before it",
    "position": lambda r: f"must be {r['value']} in the chain",
    "as_early_as_possible": lambda r: "as early in the chain as possible",
}

md = [
    "# Pedalboard plan",
    "",
    "> Generated by `scripts/build.py` from `data/pedals.json` and `data/board.json`. Edit those files, not this one.",
    "",
    "- `python3 scripts/build.py` validates the plan (ordering rules, output limits, digital pedals not sharing power) and regenerates this file and `output/pedalboard.mmd`.",
    "- `python3 scripts/to_playground.py` writes `output/pedalplayground_import.json`, a layout you can load into [Pedal Playground](https://pedalplayground.com/) (\"Load from File\").",
    "",
    "## Signal chain",
    "",
    "```mermaid",
    *lines,
    "```",
    "",
    "| # | Pedal | Owned | Power | Bypass | Digital | Powered from |",
    "|--:|---|:-:|---|---|:-:|---|",
]
for i, pid in enumerate(chain, 1):
    p = pedals[pid]
    md.append(f"| {i} | {nm(pid)} | {yn(p['owned'])} | {power(p)} | {bypass(p)} | {yn(p['digital'])} | {feeds[pid]} |")

to_buy = [nm(pid) for pid in chain if not pedals[pid]["owned"]]
md += ["", f"**To buy:** {', '.join(to_buy) or 'nothing'}", "", "### Ordering rules", ""]
for pid in chain:
    for r in pedals[pid]["dependencies"]:
        tag = "" if r["strength"] == "required" else " *(preferred)*"
        md.append(f"- **{nm(pid)}** {RULE_TEXT[r['type']](r)}{tag}: {r['reason']}")

md += ["", "### Notes per pedal", ""]
for pid in chain:
    md.append(f"- **{nm(pid)}**: {pedals[pid]['comments']}")

md += ["", "### Not on the board", "", "| Pedal | Owned | Power | Bypass | Digital |", "|---|:-:|---|---|:-:|"]
for pid in unused:
    p = pedals[pid]
    md.append(f"| {nm(pid)} | {yn(p['owned'])} | {power(p)} | {bypass(p)} | {yn(p['digital'])} |")

md += [
    "",
    "## Powering",
    "",
    "Two Strymon Ojai R30 supplies, five isolated outputs each. Per unit, three outputs are fixed 9V / 500 mA (`F1`-`F3`) and two are switchable (`SW_A`, `SW_B`): 9V / 500 mA, 12V / 375 mA or 18V / 250 mA. "
    "Draw figures are the worst-case values in `data/pedals.json`. A **digital** pedal (including one with a digital processor in an analog path) always has an output to itself; the build fails if one is daisy-chained.",
    "",
]
grand = 0
for psu in board["power_supplies"]:
    total = sum(o["_load"] for o in psu["outputs"])
    grand += total
    md += [f"### {psu['label']}", "", "| Output | Voltage | Pedal | Draw (mA) | Output total |", "|---|--:|---|--:|--:|"]
    for out in psu["outputs"]:
        head = f"**{code(out)}** ({out['type']})"
        total_cell = f"{out['_load']} / {out['_limit']} mA"
        if not out["pedals"]:
            md.append(f"| {head} | {out['voltage_v']}V | *spare* | 0 | {total_cell} |")
            continue
        for k, pid in enumerate(out["pedals"]):
            first = k == 0
            md.append(
                f"| {head if first else ''} | {out['voltage_v']}V{'' if first else ''} | {nm(pid)} | "
                f"{pedals[pid]['power_consumption']['current_ma']} | {total_cell if first else ''} |"
            )
    md += [f"| | | **{short(psu)} total** | | **{total} mA** |", ""]
md += [f"**Both supplies combined:** {grand} mA", ""]

(ROOT / "README.md").write_text("\n".join(md) + "\n")

# --- report ---------------------------------------------------------------
for psu in board["power_supplies"]:
    print(psu["label"])
    for out in psu["outputs"]:
        print(f"  {out['id']:10} {out['voltage_v']:>2}V  {out['_load']:>3}/{out['_limit']} mA  {', '.join(out['pedals']) or '(spare)'}")
to_buy = [pid for pid in chain if not pedals[pid]["owned"]]
print(f"plan: {len(chain)} pedals, to buy: {', '.join(to_buy) or 'none'}")
if unused:
    print(f"not in plan: {', '.join(unused)}")
for w in warnings:
    print("WARN ", w)
for e in errors:
    print("ERROR", e)
print("OK" if not errors else f"{len(errors)} error(s)")
sys.exit(1 if errors else 0)
