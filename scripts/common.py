"""Shared paths and loaders for the pedalboard scripts."""
import json
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CATALOG = ROOT / "catalog"
PROJECTS = ROOT / "projects"
CACHE = ROOT / ".cache"
JACKS_FILE = CATALOG / "jacks.json"
SITE = "https://pedalplayground.com/public/data/"
IN_MM = 25.4  # Pedal Playground files hold inches/px; everything we compute and show is mm


def load_json(path):
    return json.loads(Path(path).read_text())


def load_catalog():
    """Return (pedals by id, power supplies by id)."""
    pedals = {p["id"]: p for p in load_json(CATALOG / "pedals.json")["pedals"]}
    supplies = {s["id"]: s for s in load_json(CATALOG / "power_supplies.json")["supplies"]}
    return pedals, supplies


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


def load_jacks():
    """catalog/jacks.json -> {catalog id: [jack dicts]} (empty if the file does not exist yet)."""
    if not JACKS_FILE.exists():
        return {}
    return load_json(JACKS_FILE).get("jacks", {})


def px_to_mm(px, scale):
    """Pedal Playground pixels (at `scale` px per inch) -> mm."""
    return px * IN_MM / scale


def fmt_mm(v, digits=0):
    return "?" if v is None else f"{v:.{digits}f}"
