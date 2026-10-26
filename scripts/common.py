"""Shared paths and loaders for the pedalboard scripts."""
import json
import os
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CATALOG = ROOT / "catalog"
PROJECTS = ROOT / "projects"
CACHE = ROOT / ".cache"
JACKS_FILE = CATALOG / "jacks.json"
FOOTSWITCHES_FILE = CATALOG / "footswitches.json"
CABLES_FILE = CATALOG / "cables.json"
SITE = "https://pedalplayground.com/public/data/"
IMAGE_URLS = ("https://pedalplayground.com/app/images/pedals/{}", "https://pedalplayground.com/public/images/pedals/{}")
BOARD_IMAGE_URLS = ("https://pedalplayground.com/public/images/pedalboards/{}", "https://pedalplayground.com/app/images/pedalboards/{}")
IMAGE_DIR = CACHE / "images"
IN_MM = 25.4  # Pedal Playground files hold inches/px; everything we compute and show is mm


def load_json(path):
    return json.loads(Path(path).read_text())


def load_catalog():
    """Return (pedals by id, power supplies by id)."""
    pedals = {p["id"]: p for p in load_json(CATALOG / "pedals.json")["pedals"]}
    supplies = {s["id"]: s for s in load_json(CATALOG / "power_supplies.json")["supplies"]}
    return pedals, supplies


def proposal_inputs_sha1(pdir):
    """SHA-1 of everything a project's layout proposals depend on: playground_design.json, project.json,
    catalog/cables.json, the catalog entries (pedal, supply, jacks, footswitches) of the project's pedals and
    supplies, the outline entries (catalog/outlines.json) of the images in the design file, the board image's
    catalog/boards.json entry and the project's board.json (holes). Stored by propose_layout.py in proposals/meta.json;
    build.py marks the proposals stale on a change."""
    import hashlib
    pdir = Path(pdir)
    project = load_json(pdir / "project.json")
    ids = [str(i) for i in list(project.get("signal_chain", [])) + [s.get("supply") for s in (project.get("power") or {}).get("supplies", [])]
           if i is not None]
    pedals, supplies = load_catalog()
    jacks = load_json(JACKS_FILE).get("jacks", {}) if JACKS_FILE.exists() else {}
    fs = load_json(FOOTSWITCHES_FILE).get("footswitches", {}) if FOOTSWITCHES_FILE.exists() else {}
    data = {"catalog": {i: [pedals.get(i), supplies.get(i), jacks.get(i), fs.get(i)] for i in ids},
            "cables": load_cable_types(), "project": project}
    h = hashlib.sha1(json.dumps(data, sort_keys=True).encode())
    design = pdir / "playground_design.json"
    if design.exists():
        h.update(design.read_bytes())
        import design as design_mod   # late: design imports common
        import outlines
        have = outlines.load()
        images = sorted({i["image"] for i in design_mod.parse_design(design) if i.get("image")})
        h.update(json.dumps({n: have.get(n) for n in images}, sort_keys=True).encode())
        # the board image's holes and transit estimate (catalog/boards.json) and the project's board.json corrections
        import boards
        known = boards.load()
        names = sorted({i["image"] for i in design_mod.parse_design(design) if i.get("kind") == "pedalboard" and i.get("image")})
        h.update(json.dumps({n: known.get(n) for n in names}, sort_keys=True).encode())
    edits = pdir / "board.json"
    if edits.exists():
        h.update(edits.read_bytes())
    return h.hexdigest()


def load_cable_types(path=CABLES_FILE):
    """Signal cable types by id (catalog/cables.json); {} if the file does not exist."""
    p = Path(path)
    return load_json(p).get("cables", {}) if p.exists() else {}


def project_dirs(names=None):
    """Project folders (those holding a project.json), optionally filtered by name."""
    found = {d.name: d for d in sorted(PROJECTS.glob("*/")) if (d / "project.json").exists()}
    if not names:
        return list(found.values())
    missing = [n for n in names if n not in found]
    if missing:
        sys.exit(f"Unknown project(s): {', '.join(missing)}. Available: {', '.join(found) or 'none'}")
    return [found[n] for n in names]


def pedal_name(p):
    return f"{p['brand']} {p['name']}"


def effective_quantity(p):
    """Units owned: explicit `quantity`, else 1 if owned, 0 if not, None if unknown."""
    if "quantity" in p:
        return p["quantity"]
    if p.get("owned") is None:
        return None
    return 1 if p["owned"] else 0


def database(name):
    """Pedal Playground's public database (pedals.json / pedalboards.json), cached in .cache/, keyed by "Brand Name"."""
    CACHE.mkdir(exist_ok=True)
    path = CACHE / name
    if not path.exists():
        with urllib.request.urlopen(SITE + name, timeout=30) as r:
            path.write_bytes(r.read())
    return {f"{e['Brand']} {e['Name']}": e for e in json.loads(path.read_text())}


def px_to_mm(px, scale):
    """Pedal Playground pixels (at `scale` px per inch) -> mm."""
    return px * IN_MM / scale


def fmt_mm(v, digits=0):
    return "?" if v is None else f"{v:.{digits}f}"


def dumps_per_line(doc, key, mapping, key_order):
    """Diff-friendly JSON for catalog/jacks.json and catalog/footswitches.json: {"_doc", key: {id: [items]}}, ids
    sorted, one item per line with its keys in `key_order` (unknown keys after). An empty list stays `[]`."""
    def line(item):
        ordered = {k: item[k] for k in key_order if k in item}
        ordered.update({k: v for k, v in item.items() if k not in ordered})
        return "{" + ", ".join(f"{json.dumps(k)}: {json.dumps(v, ensure_ascii=False)}" for k, v in ordered.items()) + "}"

    ids = sorted(mapping)
    if not ids:
        return "{\n" + f'  "_doc": {json.dumps(doc, ensure_ascii=False)},\n  {json.dumps(key)}: {{}}\n}}\n'
    lines = ["{", f'  "_doc": {json.dumps(doc, ensure_ascii=False)},', f'  {json.dumps(key)}: {{']
    for n, cid in enumerate(ids):
        comma = "," if n < len(ids) - 1 else ""
        items = mapping[cid]
        if not items:
            lines.append(f"    {json.dumps(cid)}: []{comma}")
            continue
        lines.append(f"    {json.dumps(cid)}: [")
        lines += [f"      {line(it)}{',' if i < len(items) - 1 else ''}" for i, it in enumerate(items)]
        lines.append("    ]" + comma)
    lines += ["  }", "}"]
    return "\n".join(lines) + "\n"


def fetch_image(image_name, refresh=False, kind="pedals"):
    """Download a Pedal Playground pedal PNG (`kind="pedalboards"`: a board PNG) into .cache/images/ (larger version
    first); returns the cached path. Raises RuntimeError with every failure when none of the URLs works."""
    IMAGE_DIR.mkdir(parents=True, exist_ok=True)
    path = IMAGE_DIR / image_name
    if path.exists() and not refresh:
        return path
    errors = []
    for url in (BOARD_IMAGE_URLS if kind == "pedalboards" else IMAGE_URLS):
        url = url.format(image_name)
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "pedalboard-pedal-editor"})
            with urllib.request.urlopen(req, timeout=30) as r:
                data = r.read()
            tmp = path.with_suffix(".part")
            tmp.write_bytes(data)
            os.replace(tmp, path)
            return path
        except Exception as e:  # noqa: BLE001  (report every failure, then give up)
            errors.append(f"{url}: {e}")
    raise RuntimeError("Could not download the image:\n  " + "\n  ".join(errors))
