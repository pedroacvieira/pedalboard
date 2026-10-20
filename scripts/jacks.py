"""Jack data: catalog/jacks.json (loading, saving, validation) and the helpers the build and the app share.

catalog/jacks.json holds, per catalog id (pedals and power supplies), a list of jacks:

    {"id": "out", "label": "Output", "function": "output", "x": 1.0, "y": 0.5, "facing": "right"}

x, y are fractions (0..1) of the Pedal Playground image (origin top-left, unrotated pedal);
`facing` is the side the plug enters from. Only these numbers and labels are stored, never an image.
"""
import json
import os
import re
from pathlib import Path

from common import JACKS_FILE

FUNCTIONS = ("input", "output", "power", "power_out", "other")
FACINGS = ("left", "right", "top", "down")
KEY_ORDER = ("id", "label", "function", "x", "y", "facing", "default")
DOC = ("Jack positions per catalog id (pedals and power supplies). Written ONLY by scripts/jack_setter.py. "
       "x,y are fractions (0..1) of the Pedal Playground image, origin top-left, in the UNROTATED pedal. "
       "facing = the side the plug enters from (left/right/top/down). function: input|output|power|power_out|other. "
       "'default': true picks the jack when several share a function. No image is stored.")
COMMAND = "python3 scripts/jack_setter.py"


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


def _jack_line(j):
    ordered = {k: j[k] for k in KEY_ORDER if k in j}
    ordered.update({k: v for k, v in j.items() if k not in ordered})
    return "{" + ", ".join(f"{json.dumps(k)}: {json.dumps(v, ensure_ascii=False)}" for k, v in ordered.items()) + "}"


def dumps(data):
    """Compact, diff-friendly JSON: one jack per line, catalog ids sorted."""
    lines = ["{", f'  "_doc": {json.dumps(data.get("_doc", DOC), ensure_ascii=False)},', '  "jacks": {']
    ids = sorted(data["jacks"])
    for n, cid in enumerate(ids):
        lines.append(f"    {json.dumps(cid)}: [")
        js = data["jacks"][cid]
        lines += [f"      {_jack_line(j)}{',' if i < len(js) - 1 else ''}" for i, j in enumerate(js)]
        lines.append("    ]" + ("," if n < len(ids) - 1 else ""))
    lines += ["  }", "}"]
    return "\n".join(lines) + "\n"


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
