#!/usr/bin/env python3
"""Write a Pedal Playground save file (Load from File) from board.json.

The board is placed at the top of the canvas; the pedals and power supplies are
laid out below it in signal-chain order, ready to be dragged into position.
Sizes and images come from Pedal Playground's own public pedal database.
"""
import json
import sys
import urllib.request
from html import escape
from pathlib import Path

HERE = Path(__file__).parent
CACHE = HERE / ".cache"
SITE = "https://pedalplayground.com/public/data/"
BOARD_X, BOARD_Y = 28, 40
GAP = 20
ROW_WRAP_PX = 1400

board = json.loads((HERE / "board.json").read_text())
cfg = json.loads((HERE / "pedalplayground.json").read_text())
scale = cfg["scale"]


def database(name):
    CACHE.mkdir(exist_ok=True)
    path = CACHE / name
    if not path.exists():
        with urllib.request.urlopen(SITE + name, timeout=30) as r:
            path.write_bytes(r.read())
    return {f"{e['Brand']} {e['Name']}": e for e in json.loads(path.read_text())}


pedal_db, board_db = database("pedals.json"), database("pedalboards.json")
missing = [t for t in [*cfg["pedals"].values(), *cfg["power_supplies"].values()] if t not in pedal_db]
if cfg["board"] not in board_db:
    missing.append(cfg["board"])
if missing:
    sys.exit("Not in the Pedal Playground database: " + ", ".join(missing))

_serial = 4_000_000_000


def item(kind, title, entry, x, y):
    global _serial
    _serial += 1
    w, h = entry["Width"], entry["Height"]
    folder = "pedalboards" if kind == "pedalboard" else "pedals"
    shadow = "" if kind == "pedalboard" else '\t<div class="shadow"></div>'
    return (
        f'<div id="item-{_serial}" class="item {kind} undefined" title="{escape(title)}" '
        f'data-width="{w}" data-height="{h}" data-scale="{scale}" '
        f'style="touch-action: none; left: {x}px; top: {y}px;">'
        f'\t<div class="artwork" style="width: {w * scale}px; height: {h * scale}px; '
        f'background-image: url(&quot;public/images/{folder}/{entry["Image"]}&quot;);"></div>'
        f'{shadow}\t<div class="actions">\t\t<a class="rotate"></a>\t\t<a class="delete"></a>\t</div></div>'
    )


parts = [item("pedalboard", cfg["board"], board_db[cfg["board"]], BOARD_X, BOARD_Y)]
parts.append(f'\n\t\t\t\t<input id="multiplier" type="hidden" value="{scale}">\n\t\t\t')

# staging area under the board: power supplies first, then pedals in chain order
b = board_db[cfg["board"]]
x, y, row_h = BOARD_X, BOARD_Y + round(b["Height"] * scale) + 40, 0
titles = [cfg["power_supplies"][p["id"]] for p in board["power_supplies"]]
titles += [cfg["pedals"][pid] for pid in board["signal_chain"]]
for title in titles:
    e = pedal_db[title]
    w, h = round(e["Width"] * scale), round(e["Height"] * scale)
    if x + w > ROW_WRAP_PX:
        x, y, row_h = BOARD_X, y + row_h + GAP, 0
    parts.append(item("pedal", title, e, x, y))
    x += w + GAP
    row_h = max(row_h, h)

out = HERE / "pedalplayground_import.json"
out.write_text(json.dumps({"source": "pedalplayground.com", "version": "1.0", "canvas": "".join(parts)}))
print(f"wrote {out.name}: 1 board + {len(titles)} items")
