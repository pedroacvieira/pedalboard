#!/usr/bin/env python3
"""Write a Pedal Playground save file (Load from File) for each project.

    python3 scripts/to_playground.py              # every project
    python3 scripts/to_playground.py guitar-gig

Output: projects/<name>/playground.json. The board goes at the top of the canvas;
the supplies and pedals are laid out below it in signal-chain order, ready to be
dragged into position. Sizes and images come from Pedal Playground's own public
pedal database (cached in .cache/).
"""
import argparse
import json
import sys
from html import escape

from common import ROOT, database, load_catalog, load_json, project_dirs

BOARD_X, BOARD_Y, GAP, ROW_WRAP_PX = 28, 40, 20, 1400


def build(pdir, cat_pedals, cat_supplies, pedal_db, board_db):
    project = load_json(pdir / "project.json")
    board = project["board"]
    board_title = board.get("playground_title") or f"{board['brand']} {board['model']}"
    scale = project.get("playground", {}).get("scale", 45)
    chain = project["signal_chain"]

    titles, problems = [], []
    for inst in project.get("power", {}).get("supplies", []):
        t = cat_supplies[inst["supply"]].get("playground_title")
        if t:
            titles.append(t)
        else:  # supplies are only decoration: skip the ones Pedal Playground does not know
            print(f"  note: {inst['supply']} has no playground_title, left out of the layout")
    for pid in chain:
        t = cat_pedals[pid].get("playground_title")
        (titles if t else problems).append(t or f"pedal {pid} has no playground_title")
    problems += [f"not in the Pedal Playground database: {t}" for t in [*titles, board_title]
                 if t not in pedal_db and t != board_title]
    if board_title not in board_db:
        problems.append(f"board not in the Pedal Playground database: {board_title}")
    if problems:
        sys.exit(f"{pdir.name}: " + "; ".join(problems))

    entry = board_db[board_title]
    if (entry["Width"], entry["Height"]) != (board["width_in"], board["height_in"]):
        print(f"  note: {board_title} is {entry['Width']} x {entry['Height']} in on Pedal Playground, "
              f"project says {board['width_in']} x {board['height_in']}")

    serial = [4_000_000_000]

    def item(kind, title, e, x, y):
        serial[0] += 1
        w, h = e["Width"], e["Height"]
        folder = "pedalboards" if kind == "pedalboard" else "pedals"
        shadow = "" if kind == "pedalboard" else '\t<div class="shadow"></div>'
        return (
            f'<div id="item-{serial[0]}" class="item {kind} undefined" title="{escape(title)}" '
            f'data-width="{w}" data-height="{h}" data-scale="{scale}" '
            f'style="touch-action: none; left: {x}px; top: {y}px;">'
            f'\t<div class="artwork" style="width: {w * scale}px; height: {h * scale}px; '
            f'background-image: url(&quot;public/images/{folder}/{e["Image"]}&quot;);"></div>'
            f'{shadow}\t<div class="actions">\t\t<a class="rotate"></a>\t\t<a class="delete"></a>\t</div></div>'
        )

    parts = [item("pedalboard", board_title, entry, BOARD_X, BOARD_Y),
             f'\n\t\t\t\t<input id="multiplier" type="hidden" value="{scale}">\n\t\t\t']
    x, y, row_h = BOARD_X, BOARD_Y + round(entry["Height"] * scale) + 40, 0
    for title in titles:
        e = pedal_db[title]
        w, h = round(e["Width"] * scale), round(e["Height"] * scale)
        if x + w > ROW_WRAP_PX:
            x, y, row_h = BOARD_X, y + row_h + GAP, 0
        parts.append(item("pedal", title, e, x, y))
        x += w + GAP
        row_h = max(row_h, h)

    out = pdir / "playground.json"
    out.write_text(json.dumps({"source": "pedalplayground.com", "version": "1.0", "canvas": "".join(parts)}))
    print(f"{pdir.name}: wrote {out.relative_to(ROOT)} (1 board + {len(titles)} items)")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("projects", nargs="*", help="project folder names (default: all)")
    args = ap.parse_args()
    cat_pedals, cat_supplies = load_catalog()
    pedal_db, board_db = database("pedals.json"), database("pedalboards.json")
    for pdir in project_dirs(args.projects or None):
        build(pdir, cat_pedals, cat_supplies, pedal_db, board_db)


if __name__ == "__main__":
    main()
