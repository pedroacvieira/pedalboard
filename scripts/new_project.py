#!/usr/bin/env python3
"""Scaffold a new project (projects/<name>/project.json), optionally with its Pedal Playground share link.

    uv run pb new <name> --instrument guitar|bass [--share https://pedalplayground.com/?p=<slug>]

The scaffold leaves the board and power wiring unknown (null) on purpose: with
`no_unknown` on, the build fails until you fill them in.
"""
import argparse
import json
import sys

from common import PROJECTS
from fetch_playground import share_url, slug_of


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("name", help="folder name, e.g. guitar-practice")
    ap.add_argument("--instrument", choices=["guitar", "bass"], required=True)
    ap.add_argument("--share", help="the layout's public Pedal Playground share link (or its slug): uv run pb fetch <name>")
    args = ap.parse_args()
    try:
        share = share_url(slug_of(args.share)) if args.share else None
    except ValueError as e:
        sys.exit(str(e))

    pdir = PROJECTS / args.name
    if pdir.exists():
        sys.exit(f"{pdir} already exists")
    pdir.mkdir(parents=True)
    scaffold = {
        "name": args.name.replace("-", " ").title(),
        "instrument": args.instrument,
        "validation": {"no_unknown": True, "require_jacks": False, "strict_clearance": False,
                       "require_footswitches": False, "strict_footswitches": False, "strict_bounds": False},
        "jacks": {"clearance": {"outward_mm": 6.3, "side_mm": 7}, "power_clearance": {"outward_mm": 5.5, "side_mm": 5.5}, "extra_used": {}, "supplies_layer": "under"},
        "cables": {"type": "ernie_ball_flat_patch_ra", "power_type": "dc_ra_owner_baseline", "overrides": {}},
        "footswitches": {"comfort_mm": 100},
        "layout": {"pins": [], "max_change": "fix"},
        "board": {"brand": None, "model": None, "width_in": None, "height_in": None},
        "playground": {"scale": 45, **({"share": share} if share else {})},
        "signal_chain": [],
        "rule_overrides": {},
        "rules": [],
        "power": {"supplies": []},
    }
    (pdir / "project.json").write_text(json.dumps(scaffold, indent=2) + "\n")
    nxt = f"uv run pb fetch {args.name}, " if share else f"share the layout in Pedal Playground, uv run pb fetch {args.name} --share <link>, "
    print(f"created {pdir / 'project.json'}; fill it in, {nxt}then uv run pb build {args.name}")


if __name__ == "__main__":
    main()
