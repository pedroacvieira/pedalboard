#!/usr/bin/env python3
"""Scaffold a new project: python3 scripts/new_project.py <name> --instrument guitar|bass

The scaffold leaves the board and power wiring unknown (null) on purpose: with
`no_unknown` on, the build fails until you fill them in.
"""
import argparse
import json
import sys

from common import PROJECTS


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("name", help="folder name, e.g. guitar-practice")
    ap.add_argument("--instrument", choices=["guitar", "bass"], required=True)
    args = ap.parse_args()

    pdir = PROJECTS / args.name
    if pdir.exists():
        sys.exit(f"{pdir} already exists")
    pdir.mkdir(parents=True)
    scaffold = {
        "name": args.name.replace("-", " ").title(),
        "instrument": args.instrument,
        "validation": {"no_unknown": True, "require_jacks": False, "strict_clearance": False},
        "jacks": {"clearance": {"outward_mm": 6.3, "side_mm": 7}, "extra_used": {}, "supplies_layer": "under", "slack_mm": 50},
        "board": {"brand": None, "model": None, "width_in": None, "height_in": None},
        "playground": {"scale": 45},
        "signal_chain": [],
        "rule_overrides": {},
        "rules": [],
        "power": {"supplies": []},
    }
    (pdir / "project.json").write_text(json.dumps(scaffold, indent=2) + "\n")
    print(f"created {pdir / 'project.json'}; fill it in, then run scripts/build.py {args.name}")


if __name__ == "__main__":
    main()
