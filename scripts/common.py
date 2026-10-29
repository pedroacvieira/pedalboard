"""Shared paths and loaders for the pedalboard scripts."""
import io
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
# Pedal Playground moved (2026-10-29): one catalog file holds the pedals, the boards and the image assets; the old
# /public/data and /app/images URLs answer 200 with an HTML page and are gone.
CATALOG_BASE = "https://pedalplayground.com/catalog/"
CATALOG_URL = CATALOG_BASE + "catalog.json"
CATALOG_CACHE_NAME = "catalog.json"
IMAGE_DIR = CACHE / "images"
IN_MM = 25.4  # Pedal Playground files hold inches/px; everything we compute and show is mm


def load_json(path):
    return json.loads(Path(path).read_text())


def load_catalog():
    """Return (pedals by id, power supplies by id)."""
    pedals = {p["id"]: p for p in load_json(CATALOG / "pedals.json")["pedals"]}
    supplies = {s["id"]: s for s in load_json(CATALOG / "power_supplies.json")["supplies"]}
    return pedals, supplies


TOPPER_KEYS = ("toppers", "topper_bonus_mm", "max_toppers", "topper_min_gain")   # project footswitches settings, not proposal inputs


def proposal_inputs_sha1(pdir):
    """SHA-1 of everything a project's layout proposals depend on: playground_design.json, project.json,
    catalog/cables.json, the catalog entries (pedal, supply, jacks, footswitches) of the project's pedals and
    supplies, the outline entries (catalog/outlines.json) of the images in the design file, the board image's
    catalog/boards.json entry and the project's board.json (holes). Stored by propose_layout.py in proposals/meta.json;
    build.py marks the proposals stale on a change. The project's footswitch topper settings (TOPPER_KEYS) are left out."""
    import hashlib
    pdir = Path(pdir)
    project = load_json(pdir / "project.json")
    # toppers are a finishing step after the layout: they never make proposals stale
    fcfg = {k: v for k, v in (project.get("footswitches") or {}).items() if k not in TOPPER_KEYS}
    project = {k: v for k, v in project.items() if k != "footswitches"}
    if fcfg:
        project["footswitches"] = fcfg
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


def _write_atomic(path, data):
    """Write bytes (or str) to `path` through a `.part` file."""
    tmp = path.with_name(path.name + ".part")
    tmp.write_bytes(data if isinstance(data, bytes) else data.encode())
    os.replace(tmp, path)


def _http_get(url):
    """GET `url`; returns (bytes, content type). Raises RuntimeError naming the URL on any failure."""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "pedalboard-pedal-editor"})
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.read(), (r.headers.get("Content-Type") or "")
    except Exception as e:  # noqa: BLE001  (callers only need the message)
        raise RuntimeError(f"Could not download {url}: {e}") from e


def _parse_catalog(data, source):
    """Parse Pedal Playground's catalog.json bytes; RuntimeError when it is not the expected JSON (e.g. an HTML page)."""
    try:
        doc = json.loads(data)
    except ValueError as e:
        raise RuntimeError(f"{source} is not JSON (an HTML page?): {e}") from e
    if not (isinstance(doc, dict) and isinstance(doc.get("pedals"), list) and isinstance(doc.get("pedalboards"), list)
            and isinstance(doc.get("assets"), dict)):
        raise RuntimeError(f"{source} is not a Pedal Playground catalog (expected pedals, pedalboards, assets)")
    return doc


def catalog_json(refresh=False):
    """Pedal Playground's catalog.json, cached in .cache/catalog.json (downloaded once; `refresh` downloads again).
    A cached file that does not parse is replaced."""
    path = CACHE / CATALOG_CACHE_NAME
    if path.exists() and not refresh:
        try:
            return _parse_catalog(path.read_bytes(), str(path))
        except RuntimeError:
            pass  # damaged cache: download again
    data, _ctype = _http_get(CATALOG_URL)
    doc = _parse_catalog(data, CATALOG_URL)  # never cache what is not the catalog
    CACHE.mkdir(exist_ok=True)
    _write_atomic(path, data)
    return doc


def _legacy_entries(doc, name):
    """catalog.json -> the legacy list shape [{"Brand", "Name", "Width", "Height", "Image": "<image>.png"}]."""
    key = {"pedals.json": "pedals", "pedalboards.json": "pedalboards"}.get(name)
    if key is None:
        raise RuntimeError(f"Unknown Pedal Playground database {name!r} (pedals.json or pedalboards.json)")
    return [{"Brand": e["brand"], "Name": e["name"], "Width": e["width"], "Height": e["height"],
             "Image": e["image"] + ".png"} for e in doc[key]]


def database(name):
    """Pedal Playground's database (pedals.json / pedalboards.json) keyed by "Brand Name", entries in the legacy shape
    {"Brand", "Name", "Width", "Height", "Image": "<image>.png"}. An existing .cache/<name> (the legacy file) is used
    as is; else it is built from catalog.json and cached under that name. A cached file that is not a JSON list is
    ignored and rebuilt."""
    CACHE.mkdir(exist_ok=True)
    path = CACHE / name
    entries = None
    if path.exists():
        try:
            loaded = json.loads(path.read_text())
            if isinstance(loaded, list):
                entries = loaded
        except ValueError:
            pass
    if entries is None:
        entries = _legacy_entries(catalog_json(), name)
        _write_atomic(path, json.dumps(entries, indent="\t", ensure_ascii=False) + "\n")
    return {f"{e['Brand']} {e['Name']}": e for e in entries}


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


def _to_png(data, source):
    """Image bytes (WebP / PNG / JPEG ...) -> PNG bytes, alpha kept. RuntimeError when the bytes are not an image."""
    from PIL import Image  # lazy: only the image code needs Pillow
    try:
        with Image.open(io.BytesIO(data)) as im:
            im.load()
            if im.mode not in ("RGBA", "RGB", "L", "LA"):
                im = im.convert("RGBA")
            out = io.BytesIO()
            im.save(out, "PNG")
    except Exception as e:  # noqa: BLE001
        raise RuntimeError(f"{source} did not answer an image ({len(data)} bytes, not readable: {e})") from e
    return out.getvalue()


def fetch_image(image_name, refresh=False, kind="pedals"):
    """Pedal Playground pedal image (`kind="pedalboards"`: a board image) as a PNG in .cache/images/<image_name>
    (`image_name` = the legacy name with .png); returns the cached path. The image URL comes from catalog.json's
    assets (a WebP, converted with Pillow, alpha kept); an unknown name (after one refresh of a cached catalog), a
    failed download or a non-image answer raises RuntimeError and nothing is cached."""
    if kind not in ("pedals", "pedalboards"):
        raise ValueError(f"kind must be 'pedals' or 'pedalboards', not {kind!r}")
    IMAGE_DIR.mkdir(parents=True, exist_ok=True)
    path = IMAGE_DIR / image_name
    if path.exists() and not refresh:
        return path
    key = image_name[:-4] if image_name.lower().endswith(".png") else image_name
    cached = (CACHE / CATALOG_CACHE_NAME).exists()
    asset = catalog_json().get("assets", {}).get(kind, {}).get(key)
    if asset is None and cached:
        asset = catalog_json(refresh=True).get("assets", {}).get(kind, {}).get(key)  # the cached copy may be older
    if not asset or not asset.get("img"):
        raise RuntimeError(f"No {kind} image named {key!r} in Pedal Playground's catalog.json ({CATALOG_URL})")
    url = CATALOG_BASE + asset["img"]
    data, ctype = _http_get(url)
    if ctype and not ctype.lower().startswith(("image/", "application/octet-stream", "binary/")):
        raise RuntimeError(f"{url} answered {ctype!r}, not an image")
    _write_atomic(path, _to_png(data, url))
    return path
