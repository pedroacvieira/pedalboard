"""Shared paths and loaders for the pedalboard scripts."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CATALOG = ROOT / "catalog"
PROJECTS = ROOT / "projects"


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
