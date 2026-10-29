#!/usr/bin/env python3
"""Correct the pedalboard holes of a project and mark where cables may go round its edge, on the board's Pedal Playground image.

    uv run scripts/board_editor.py <project>                open the editor on the project's board
    uv run scripts/board_editor.py <project> --image FILE   use a local PNG instead of the cached / downloaded one
    uv run scripts/board_editor.py --list                   every project: board image, derived hole rects, edit boxes, bounds

The holes derived from the image (catalog/boards.json, `uv run scripts/boards.py <project>`) are drawn as blue
outlines. The project's boxes are saved to projects/<name>/board.json (fractions 0..1 of the image, one entry per line)
and applied by the build in file order, a later box winning: `hole` (green) opens a hole where the deck is closed,
`filled` (red) closes one that was derived by mistake. A third type, `edge` (purple), is a LINE SEGMENT along one side of
the board ({"type": "edge", "side": "left" | "right" | "back" | "front", "from": f0, "to": f1}, fractions along that side
of the unrotated image; back = its top edge, front = its bottom edge): the cables may go from under the board round the
board edge only where such a segment lies (and through the holes). The image is fetched on demand into .cache/images/ and
never copied into the repo.

Besides the boxes, board.json holds four BOUNDS (key `bounds`: back, front, left, right; fractions of the unrotated image, back /
front from its top edge, left / right from its left edge; a side that is missing = the image edge): the area where pedals may
sit (cables and under-board supplies are not limited by it). Bounds mode (B): click near a line to select it, drag it (only
along its own axis: back / front follow the mouse's y, left / right its x) or nudge it with the arrow keys along that axis
(Up / Down for back / front, Left / Right for left / right; 0.5 mm, Shift 2 mm); Delete puts the selected line back on the image
edge; Esc deselects. The four lines move independently (at least 10 mm apart from their opposite). In the other modes the
lines are drawn (dashed teal, the area outside shaded) but not selectable.

In the editor: pick the type of the next entry with the buttons in the panel or the keys 1 (hole), 2 (filled), 3 (edge),
shown in the status bar (B: bounds mode, see above); drag on empty space draws a box; in edge mode (a drag starting on a box still draws) you drag a LINE (rubber band)
that snaps to the nearest board side on release (`project_edge`: both ends are projected on the side nearest to the line's
middle and clamped to the board; shorter than 1 mm along the side: rejected); a small margin round the image lets you draw
just outside the border. Click selects an entry (an edge segment within 2 mm of the click), drag a selected one moves it
(an edge segment only along its side); T toggles the selected hole / filled box (with nothing selected it cycles the
type of the next entry); Esc deselects; Delete removes; arrow keys nudge 0.5 mm (Shift 2 mm; an edge
segment moves along its side); [ and ] move the selected entry earlier / later in the order; E shows the effective holes
(derived + boxes); Ctrl+S saves; +/- or the mouse wheel zoom.
"""
import argparse
import json
import os
import sys
from pathlib import Path

import boards
import common
import design
from common import IN_MM, database, load_json, project_dirs

COMMAND = "uv run scripts/board_editor.py"
EDITS_FILE = boards.EDITS_FILE
TYPES = ("hole", "filled", "edge")
SIDES = boards.EDGE_SIDES
MIN_BOX_MM = 1.0           # a box smaller than this on a side (an edge segment: along its side) is a stray click, not a box
HIT_MM = 2.0               # a click this close to an edge segment selects it
DECIMALS = 4
BOUND_SIDES = boards.BOUND_SIDES
BOUNDS_EDGE = boards.BOUNDS_EDGE
MIN_BOUNDS_GAP_MM = 10.0   # a bounds line stays at least this far from its opposite line
BOUNDS_COLOUR = "#00897b"
DOC = ("Corrections of the board holes of this project and the places where cables may go round the board edge. Boxes in "
       "fractions (0..1) of the Pedal Playground board image (unrotated, origin top-left, 4 decimals), applied in order on "
       "the holes derived in catalog/boards.json: type 'filled' closes the area, type 'hole' opens it; a later box wins. "
       "type 'edge' is a line segment along one side of the image (side left|right|back|front, back = the image's top edge, "
       "front = its bottom edge; from < to = fractions along that side: of the height from the top for left / right, of the "
       "width from the left for back / front): cables may go from under the board round the board edge only along such a "
       "segment (and through the holes). 'bounds' = four lines (back, front, left, right; fractions of the same image, back / front "
       "from its top edge, left / right from its left edge; a side that is missing is the image edge): where pedals may sit "
       "(cables and under-board supplies are not limited by it). Written ONLY by scripts/board_editor.py.")


# --- which board, which image (pure) -------------------------------------------------------------
def board_image_for(project_dir, project, db):
    """(image file name, w_mm, h_mm) of the project's board: the `pedalboard` item of its playground_design.json when
    there is one (with an image), else Pedal Playground's database `db` ({"Brand Model": entry}, entry has Image,
    Width and Height in inches) looked up with project["board"]. Raises ValueError when neither knows the board."""
    f = Path(project_dir) / "playground_design.json"
    if f.exists():
        item = next((it for it in design.parse_design(f) if it["kind"] == "pedalboard" and it.get("image")), None)
        if item is not None:
            return item["image"], item["w_mm"], item["h_mm"]
    b = project.get("board") or {}
    entry = db.get(f"{b.get('brand')} {b.get('model')}")
    if not entry or not entry.get("Image"):
        raise ValueError(f"board {b.get('brand')} {b.get('model')} is not in Pedal Playground's database")
    return entry["Image"], entry["Width"] * IN_MM, entry["Height"] * IN_MM


# --- coordinates (pure) --------------------------------------------------------------------------
def clamp01(v):
    return min(1.0, max(0.0, v))


def px_to_frac(px, py, zoom, w_mm, h_mm, margin=0.0, clamp=True):
    """Canvas pixel -> (fx, fy) fractions of the image (clamped to 0..1 unless `clamp` is false: a point in the margin
    round the image gives fractions outside 0..1); `zoom` = px per mm, `margin` = px of border around the image."""
    fx, fy = (px - margin) / (zoom * w_mm), (py - margin) / (zoom * h_mm)
    return (clamp01(fx), clamp01(fy)) if clamp else (fx, fy)


def frac_to_px(fx, fy, zoom, w_mm, h_mm, margin=0.0):
    """(fx, fy) fractions of the image -> canvas pixel; the inverse of `px_to_frac` (inside the image)."""
    return margin + fx * zoom * w_mm, margin + fy * zoom * h_mm


# --- boxes (pure) --------------------------------------------------------------------------------
def make_box(type_, x0, y0, x1, y1):
    return {"type": type_, "x0": x0, "y0": y0, "x1": x1, "y1": y1}


def make_edge(side, f, t):
    return {"type": "edge", "side": side, "from": f, "to": t}


def project_edge(x0, y0, x1, y1, w_mm, h_mm):
    """An edge segment from a hand-drawn line (end points as fractions of the image, outside 0..1 allowed): the line snaps to the
    board side nearest to its MIDDLE, both ends are projected on that side and clamped to 0..1 (`from` < `to`). None when
    the result is shorter than MIN_BOX_MM along the side."""
    mx, my = (x0 + x1) / 2, (y0 + y1) / 2
    side = min((abs(mx) * w_mm, "left"), (abs(1 - mx) * w_mm, "right"), (abs(my) * h_mm, "back"), (abs(1 - my) * h_mm, "front"))[1]
    a, b = (y0, y1) if side in ("left", "right") else (x0, x1)
    f, t = sorted((clamp01(a), clamp01(b)))
    length = (t - f) * (h_mm if side in ("left", "right") else w_mm)
    return None if length < MIN_BOX_MM else make_edge(side, f, t)


def normalize_box(x0, y0, x1, y1, type_, w_mm, h_mm):
    """A box from two dragged corners (any order): corners ordered, clamped to 0..1; None when it is smaller than
    MIN_BOX_MM on a side (or the type is unknown). Type "edge": the dragged line (the two points) snapped to a board side
    (`project_edge`)."""
    if type_ == "edge":
        return project_edge(x0, y0, x1, y1, w_mm, h_mm)
    if type_ not in TYPES:
        return None
    x0, x1 = sorted((clamp01(x0), clamp01(x1)))
    y0, y1 = sorted((clamp01(y0), clamp01(y1)))
    if (x1 - x0) * w_mm < MIN_BOX_MM or (y1 - y0) * h_mm < MIN_BOX_MM:
        return None
    return make_box(type_, x0, y0, x1, y1)


def edge_ends(box):
    """The end points ((fx0, fy0), (fx1, fy1)) of an edge segment, fractions of the image."""
    f, t, side = box["from"], box["to"], box["side"]
    return {"left": ((0.0, f), (0.0, t)), "right": ((1.0, f), (1.0, t)), "back": ((f, 0.0), (t, 0.0)), "front": ((f, 1.0), (t, 1.0))}[side]


def hit_box(boxes, fx, fy, w_mm=None, h_mm=None, types=None):
    """Index of the topmost entry (the LAST in the order wins) that contains the point, else None. An edge segment is hit
    within HIT_MM of it (needs the image size `w_mm` x `h_mm`; ignored without). `types`: only entries of these types
    (in edge mode a click on a hole box must not stop the owner from drawing an edge line)."""
    for i in range(len(boxes) - 1, -1, -1):
        b = boxes[i]
        if types is not None and b["type"] not in types:
            continue
        if b["type"] == "edge":
            if w_mm is not None and h_mm is not None:
                (ax, ay), (bx, by) = edge_ends(b)
                (ax, ay, bx, by) = ax * w_mm, ay * h_mm, bx * w_mm, by * h_mm
                px, py = fx * w_mm, fy * h_mm
                cx, cy = min(max(px, min(ax, bx)), max(ax, bx)), min(max(py, min(ay, by)), max(ay, by))   # axis-aligned segment
                if (px - cx) ** 2 + (py - cy) ** 2 <= HIT_MM ** 2:
                    return i
        elif b["x0"] <= fx <= b["x1"] and b["y0"] <= fy <= b["y1"]:
            return i
    return None


def move_box(box, dfx, dfy):
    """The entry moved by (dfx, dfy) fractions, keeping its size and staying inside the image; an edge segment moves
    along its side only (dfy for left / right, dfx for back / front)."""
    if box["type"] == "edge":
        d = dfy if box["side"] in ("left", "right") else dfx
        n = box["to"] - box["from"]
        f = min(1.0 - n, max(0.0, box["from"] + d))
        return {**box, "from": f, "to": f + n}
    w, h = box["x1"] - box["x0"], box["y1"] - box["y0"]
    x0 = min(1.0 - w, max(0.0, box["x0"] + dfx))
    y0 = min(1.0 - h, max(0.0, box["y0"] + dfy))
    return {**box, "x0": x0, "y0": y0, "x1": x0 + w, "y1": y0 + h}


def nudge_box(box, dx_mm, dy_mm, w_mm, h_mm):
    """The entry moved by (dx_mm, dy_mm) millimetres, clamped to the image (an edge segment along its side)."""
    return move_box(box, dx_mm / w_mm, dy_mm / h_mm)


def toggle_type(box):
    """hole <-> filled; an edge segment has no other type and stays."""
    if box["type"] == "edge":
        return box
    return {**box, "type": "filled" if box["type"] == "hole" else "hole"}


def next_type(type_):
    """The default type after T: hole -> filled -> edge -> hole."""
    return TYPES[(TYPES.index(type_) + 1) % len(TYPES)] if type_ in TYPES else TYPES[0]


def reorder(boxes, i, delta):
    """(new list, new index): box `i` moved `delta` places (clamped to the list); the order is the priority."""
    j = min(len(boxes) - 1, max(0, i + delta))
    out = list(boxes)
    out.insert(j, out.pop(i))
    return out, j


def box_size_mm(box, w_mm, h_mm):
    return (box["x1"] - box["x0"]) * w_mm, (box["y1"] - box["y0"]) * h_mm


def list_rows(boxes, w_mm, h_mm):
    """One line per entry in order: '1  hole    12.0 x 5.5 mm'; an edge segment: '3  edge    left 0.20-0.45 (25.0 mm)'."""
    rows = []
    for i, b in enumerate(boxes, 1):
        if b["type"] == "edge":
            length = (b["to"] - b["from"]) * (h_mm if b["side"] in ("left", "right") else w_mm)
            rows.append(f"{i:>2}  edge    {b['side']} {b['from']:.2f}-{b['to']:.2f} ({length:.1f} mm)")
            continue
        w, h = box_size_mm(b, w_mm, h_mm)
        rows.append(f"{i:>2}  {b['type']:<6}  {w:.1f} x {h:.1f} mm")
    return rows


def effective_holes(derived, boxes, w_mm, h_mm):
    """The holes the build will use, as rectangles (x0, y0, x1, y1) in mm on the unrotated image (derived holes in
    fractions, then the boxes, `design.board_holes`)."""
    item = {"left_mm": 0.0, "top_mm": 0.0, "w_mm": w_mm, "h_mm": h_mm, "rot": 0}
    return design.board_holes(item, derived, boxes)


# --- bounds (pure) -------------------------------------------------------------------------------
def full_bounds(bounds=None):
    """All four sides as a new dict; a missing side = the image edge."""
    return {side: (bounds or {}).get(side, BOUNDS_EDGE[side]) for side in BOUND_SIDES}


def _horizontal(side):
    return side in ("back", "front")      # back / front are horizontal lines (a y position), left / right vertical (an x position)


def bound_lines(bounds, w_mm, h_mm):
    """Per side the line across the whole unrotated image in mm: {side: ((x0, y0), (x1, y1))} (back / front horizontal at
    their y, left / right vertical at their x)."""
    b = full_bounds(bounds)
    return {side: (((0.0, b[side] * h_mm), (w_mm, b[side] * h_mm)) if _horizontal(side)
                   else ((b[side] * w_mm, 0.0), (b[side] * w_mm, h_mm))) for side in BOUND_SIDES}


def hit_bound(bounds, fx, fy, w_mm, h_mm, tol_mm=HIT_MM):
    """The side whose line is nearest to the point (fractions of the image) within `tol_mm`, else None; back / front count the
    vertical distance, left / right the horizontal one."""
    b = full_bounds(bounds)
    best = None
    for side in BOUND_SIDES:
        d = abs(fy - b[side]) * h_mm if _horizontal(side) else abs(fx - b[side]) * w_mm
        if d <= tol_mm and (best is None or d < best[0]):
            best = (d, side)
    return None if best is None else best[1]


def move_bound(bounds, side, f, w_mm, h_mm):
    """New bounds with ONLY `side` set to the fraction `f`, clamped to 0..1 and to at least MIN_BOUNDS_GAP_MM from the opposite line."""
    b = full_bounds(bounds)
    size = h_mm if _horizontal(side) else w_mm
    gap = MIN_BOUNDS_GAP_MM / size
    lo, hi = {"back": (0.0, b["front"] - gap), "front": (b["back"] + gap, 1.0),
              "left": (0.0, b["right"] - gap), "right": (b["left"] + gap, 1.0)}[side]
    b[side] = min(hi, max(lo, f))
    return b


def nudge_bound(bounds, side, d_mm, w_mm, h_mm):
    """New bounds with `side` moved by `d_mm` along its own axis (down for back / front, right for left / right), same clamping."""
    b = full_bounds(bounds)
    return move_bound(b, side, b[side] + d_mm / (h_mm if _horizontal(side) else w_mm), w_mm, h_mm)


def reset_bound(bounds, side):
    """New bounds with `side` back on the image edge."""
    b = full_bounds(bounds)
    b[side] = BOUNDS_EDGE[side]
    return b


def bound_rows(bounds, w_mm, h_mm):
    """One line per side, its distance from the image edge it belongs to: 'back   12.5 mm from the top edge' (back from the
    top, front from the bottom, left from the left, right from the right edge)."""
    b = full_bounds(bounds)
    rows = []
    for side in BOUND_SIDES:
        size = h_mm if _horizontal(side) else w_mm
        d = (b[side] if side in ("back", "left") else 1.0 - b[side]) * size
        edge = {"back": "top", "front": "bottom", "left": "left", "right": "right"}[side]
        rows.append(f"{side:<5} {d:>5.1f} mm from the {edge} edge")
    return rows


def bounds_set(bounds):
    """The sides that differ from the image edge, in the order back, front, left, right."""
    b = full_bounds(bounds)
    return [side for side in BOUND_SIDES if round(b[side], DECIMALS) != BOUNDS_EDGE[side]]


# --- the file (pure) -----------------------------------------------------------------------------
def dumps_edits(boxes, bounds=None):
    """board.json text: a `_doc`, the `bounds` (only the sides that differ from the image edge; no key when none does), then
    one entry per line with 4 decimals (like catalog/outlines.json)."""
    lines = []
    for b in boxes:
        if b["type"] == "edge":
            lines.append(f'    {{"type": "edge", "side": {json.dumps(b["side"])}, "from": {round(b["from"], DECIMALS)}, "to": {round(b["to"], DECIMALS)}}}')
            continue
        v = [round(b[k], DECIMALS) for k in ("x0", "y0", "x1", "y1")]
        lines.append(f'    {{"type": {json.dumps(b["type"])}, "x0": {v[0]}, "y0": {v[1]}, "x1": {v[2]}, "y1": {v[3]}}}')
    body = "[\n" + ",\n".join(lines) + "\n  ]" if lines else "[]"
    full = full_bounds(bounds)
    sides = bounds_set(full)
    bounds_line = ('  "bounds": {' + ", ".join(f'"{side}": {round(full[side], DECIMALS)}' for side in sides) + "},\n") if sides else ""
    return "{\n" + f'  "_doc": {json.dumps(DOC, ensure_ascii=False)},\n{bounds_line}  "boxes": {body}\n' + "}\n"


def save_edits(project_dir, boxes, bounds=None):
    """Write projects/<name>/board.json atomically (.tmp + os.replace); returns the path."""
    path = Path(project_dir) / EDITS_FILE
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(dumps_edits(boxes, bounds))
    os.replace(tmp, path)
    return path


def project_rows(names, db, boards_data):
    """Lines for --list: project, board image, derived hole count (? without a boards.json entry), edit boxes (hole / filled),
    edge segments, bounds (the sides that differ from the image edge)."""
    rows = []
    for pdir in project_dirs(names or None):
        project = load_json(pdir / "project.json")
        try:
            image = board_image_for(pdir, project, db)[0]
        except ValueError:
            rows.append(f"{pdir.name:<16} ?  (board not in Pedal Playground's database)")
            continue
        entry = boards_data.get(image)
        holes = "?" if entry is None else str(len(entry["holes"]))
        edits = boards.load_edits(pdir)
        n_edge = sum(1 for b in edits if b["type"] == "edge")
        set_ = bounds_set(boards.load_bounds(pdir))
        rows.append(f"{pdir.name:<16} {image:<28} hole rects {holes:>2}   edit boxes {len(edits) - n_edge}   edge segments {n_edge}"
                    f"   {'bounds set: ' + ', '.join(set_) if set_ else 'no bounds'}")
    return rows


# --- the window ----------------------------------------------------------------------------------
def make_app(project_dir, image_path, image_name, w_mm, h_mm, derived):
    """Build the Tkinter window (not yet running its main loop). `derived`: derived hole rectangles (fractions) or
    None when boards.json has no entry for the image."""
    import tkinter as tk
    from tkinter import messagebox, ttk

    from PIL import Image, ImageDraw, ImageTk

    MARGIN = 40            # px round the image, so a line can be drawn just outside the border
    COLOURS = {"hole": "#1b9e3f", "filled": "#d62728", "edge": "#7e57c2"}
    pdir = Path(project_dir)

    class App(tk.Tk):
        def __init__(self):
            super().__init__()
            self.img = Image.open(image_path).convert("RGBA")
            self.boxes = [dict(b) for b in boards.load_edits(pdir)]
            self.saved = [dict(b) for b in self.boxes]
            self.bounds = boards.load_bounds(pdir)
            self.saved_bounds = dict(self.bounds)
            self.bsel = None          # the selected bounds line (a side), bounds mode only
            self.sel, self.default_type, self.show_effective = None, "hole", False   # default_type "bounds" = bounds mode
            self.drag = None          # ("draw" | "move" | "bound", fx, fy) while the button is down
            self.zoom = min(860 / w_mm, 520 / h_mm)  # px per mm
            self.photo, self._busy = None, False
            self.title(f"{pdir.name}: {image_name} - {w_mm:.1f} x {h_mm:.1f} mm")
            self._build_widgets()
            self.protocol("WM_DELETE_WINDOW", self._close)
            self._refresh()

        @property
        def dirty(self):
            return self.boxes != self.saved or self.bounds != self.saved_bounds

        @property
        def bounds_mode(self):
            return self.default_type == "bounds"

        # -- layout --
        def _build_widgets(self):
            left = ttk.Frame(self)
            left.pack(side="left", fill="both", expand=True)
            self.canvas = tk.Canvas(left, background="#f4f4f4", highlightthickness=0, width=900, height=580)
            hbar = ttk.Scrollbar(left, orient="horizontal", command=self.canvas.xview)
            vbar = ttk.Scrollbar(left, orient="vertical", command=self.canvas.yview)
            self.canvas.configure(xscrollcommand=hbar.set, yscrollcommand=vbar.set)
            self.status = ttk.Label(left, text="", anchor="w")
            self.status.pack(side="bottom", fill="x")
            hbar.pack(side="bottom", fill="x")
            vbar.pack(side="right", fill="y")
            self.canvas.pack(side="left", fill="both", expand=True)

            panel = ttk.Frame(self, padding=8)
            panel.pack(side="right", fill="y")
            ttk.Label(panel, text="New entry type").pack(anchor="w")
            self.type_var = tk.StringVar(value=self.default_type)
            kinds = ttk.Frame(panel)
            kinds.pack(fill="x", pady=(0, 8))
            for n, (t, label) in enumerate((("hole", "Hole box"), ("filled", "Filled box"), ("edge", "Edge line"),
                                              ("bounds", "Bounds")), 1):
                ttk.Radiobutton(kinds, text=f"{label} ({'B' if t == 'bounds' else n})", value=t, variable=self.type_var,
                                command=lambda: self._set_type(self.type_var.get())).pack(anchor="w")
            ttk.Label(panel, text="Entries in order (a later one wins)").pack(anchor="w")
            self.listbox = tk.Listbox(panel, height=14, width=30, exportselection=False, font=("TkFixedFont", 9))
            self.listbox.pack(fill="x")
            self.listbox.bind("<<ListboxSelect>>", self._on_list_select)
            self.bounds_label = ttk.Label(panel, justify="left", font=("TkFixedFont", 9))
            self.bounds_label.pack(anchor="w", pady=(6, 0))
            btns = ttk.Frame(panel)
            btns.pack(fill="x", pady=6)
            ttk.Button(btns, text="Delete", command=self._delete).pack(side="left")
            ttk.Button(btns, text="Save (Ctrl+S)", command=self._save).pack(side="right")
            legend = ttk.Frame(panel)
            legend.pack(fill="x", pady=(6, 0))
            for text, colour in (("derived hole", "#1f77b4"), ("hole box", COLOURS["hole"]),
                                 ("filled box", COLOURS["filled"]), ("edge segment: cables may go round the board edge here", COLOURS["edge"]),
                                 ("bounds: pedals may sit inside the 4 lines (B)", BOUNDS_COLOUR),
                                 ("effective (E)", "#ff7f0e")):
                row = ttk.Frame(legend)
                row.pack(anchor="w")
                tk.Label(row, width=2, background=colour).pack(side="left", padx=(0, 6))
                ttk.Label(row, text=text).pack(side="left")
            if derived is None:
                tk.Label(panel, justify="left", anchor="w", wraplength=250, background="#fff3cd", foreground="#664d03",
                         relief="solid", borderwidth=1, padx=6, pady=4,
                         text="No derived holes for this image yet: run uv run scripts/boards.py <project>.").pack(fill="x", pady=8)
            ttk.Label(panel, wraplength=250, foreground="#555", justify="left", text=(
                "Drag on empty space: new box (edge type: drag a line, it snaps to the nearest board side). Click: select. "
                "Drag a selected entry: move (an edge segment along its side). 1 / 2 / 3 or the buttons above: type of the next entry "
                "(in edge mode a drag starting on a box still draws a line). T: toggle the selected box hole / filled. "
                "Esc: deselect. Delete: remove. "
                "Bounds mode (B): click near a line, drag it or use the arrows along its own axis (back / front: Up / Down, "
                "left / right: Left / Right); Delete puts it back on the image edge; Esc: deselect. "
                "Arrows: nudge 0.5 mm (Shift 2). [ ]: order. E: effective holes. +/- or wheel: zoom.")).pack(anchor="w", pady=8)

            c = self.canvas
            c.bind("<Button-1>", self._on_down)
            c.bind("<B1-Motion>", self._on_move)
            c.bind("<ButtonRelease-1>", self._on_up)
            c.bind("<Motion>", self._on_hover)
            c.bind("<MouseWheel>", lambda e: self._zoom(1.1 if e.delta > 0 else 1 / 1.1))
            c.bind("<Button-4>", lambda e: self._zoom(1.1))
            c.bind("<Button-5>", lambda e: self._zoom(1 / 1.1))
            self.bind("<Control-s>", lambda e: self._save())
            self.bind("<Delete>", lambda e: self._guard(self._delete))
            self.bind("<plus>", lambda e: self._guard(lambda: self._zoom(1.15)))
            self.bind("<equal>", lambda e: self._guard(lambda: self._zoom(1.15)))
            self.bind("<minus>", lambda e: self._guard(lambda: self._zoom(1 / 1.15)))
            for key in ("b", "B"):
                self.bind(f"<Key-{key}>", lambda e: self._guard(lambda: self._set_type("bounds")))
            for key in ("t", "T"):
                self.bind(f"<Key-{key}>", lambda e: self._guard(self._toggle_type))
            for n, t in enumerate(TYPES, 1):
                self.bind(f"<Key-{n}>", lambda e, t=t: self._guard(lambda: self._set_type(t)))
            self.bind("<Escape>", lambda e: self._deselect())
            for key in ("e", "E"):
                self.bind(f"<Key-{key}>", lambda e: self._guard(self._toggle_effective))
            self.bind("<bracketleft>", lambda e: self._guard(lambda: self._reorder(-1)))
            self.bind("<bracketright>", lambda e: self._guard(lambda: self._reorder(1)))
            for key, d in (("Left", (-1, 0)), ("Right", (1, 0)), ("Up", (0, -1)), ("Down", (0, 1))):
                self.bind(f"<{key}>", lambda e, d=d: self._guard(lambda: self._nudge(d, 0.5)))
                self.bind(f"<Shift-{key}>", lambda e, d=d: self._guard(lambda: self._nudge(d, 2.0)))

        def _guard(self, fn):
            if not isinstance(self.focus_get(), (tk.Entry, ttk.Entry, tk.Listbox)):
                fn()

        # -- drawing --
        def _px(self, fx, fy):
            return frac_to_px(fx, fy, self.zoom, w_mm, h_mm, MARGIN)

        def _frac(self, event, clamp=True):
            return px_to_frac(self.canvas.canvasx(event.x), self.canvas.canvasy(event.y), self.zoom, w_mm, h_mm, MARGIN, clamp)

        def _redraw(self):
            wp, hp = round(w_mm * self.zoom), round(h_mm * self.zoom)
            base = Image.new("RGBA", (wp, hp), "#ffffff")
            d = ImageDraw.Draw(base)
            for gy in range(0, hp, 12):          # checkerboard: the transparent slots show through
                for gx in range(0, wp, 12):
                    if (gx // 12 + gy // 12) % 2:
                        d.rectangle([gx, gy, gx + 11, gy + 11], fill="#d9d9d9")
            base.alpha_composite(self.img.resize((wp, hp), Image.LANCZOS))
            if bounds_set(self.bounds):          # the area outside the bounds, lightly shaded
                shade = Image.new("RGBA", (wp, hp), (0, 0, 0, 70))
                ImageDraw.Draw(shade).rectangle([round(self.bounds["left"] * wp), round(self.bounds["back"] * hp),
                                                 round(self.bounds["right"] * wp) - 1, round(self.bounds["front"] * hp) - 1],
                                                fill=(0, 0, 0, 0))
                base.alpha_composite(shade)
            self.photo = ImageTk.PhotoImage(base)
            c = self.canvas
            c.delete("all")
            c.create_image(MARGIN, MARGIN, image=self.photo, anchor="nw")
            c.create_rectangle(MARGIN, MARGIN, MARGIN + wp, MARGIN + hp, outline="#888")
            c.configure(scrollregion=(0, 0, wp + 2 * MARGIN, hp + 2 * MARGIN))
            for mm in range(0, int(max(w_mm, h_mm)) + 1, 10):   # ruler ticks every 10 mm
                long = mm % 50 == 0
                if mm <= w_mm:
                    c.create_line(MARGIN + mm * self.zoom, MARGIN - (8 if long else 4), MARGIN + mm * self.zoom, MARGIN, fill="#555")
                    if long:
                        c.create_text(MARGIN + mm * self.zoom, MARGIN - 16, text=str(mm), font=("TkDefaultFont", 7), fill="#555")
                if mm <= h_mm:
                    c.create_line(MARGIN - (8 if long else 4), MARGIN + mm * self.zoom, MARGIN, MARGIN + mm * self.zoom, fill="#555")
                    if long:
                        c.create_text(MARGIN - 16, MARGIN + mm * self.zoom, text=str(mm), font=("TkDefaultFont", 7), fill="#555", angle=90)
            for r in derived or []:
                (xa, ya), (xb, yb) = self._px(r[0], r[1]), self._px(r[2], r[3])
                c.create_rectangle(xa, ya, xb, yb, outline="#1f77b4", width=2)
            for i, b in enumerate(self.boxes):
                colour = COLOURS[b["type"]]
                if b["type"] == "edge":   # a thick line on the border (selected: thicker, with a dark dashed line on it)
                    (xa, ya), (xb, yb) = (self._px(*q) for q in edge_ends(b))
                    c.create_line(xa, ya, xb, yb, fill=colour, width=9 if i == self.sel else 6, capstyle="butt")
                    c.create_text(xa + 4, ya + 4, text=str(i + 1), anchor="nw", fill=colour, font=("TkDefaultFont", 8, "bold"))
                    if i == self.sel:
                        c.create_line(xa, ya, xb, yb, fill="#000", dash=(4, 3), width=1)
                    continue
                (xa, ya), (xb, yb) = self._px(b["x0"], b["y0"]), self._px(b["x1"], b["y1"])
                c.create_rectangle(xa, ya, xb, yb, outline=colour, fill=colour, stipple="gray25",
                                   width=3 if i == self.sel else 1)
                c.create_text(xa + 3, ya + 2, text=str(i + 1), anchor="nw", fill=colour, font=("TkDefaultFont", 8, "bold"))
                if i == self.sel:
                    c.create_rectangle(xa - 2, ya - 2, xb + 2, yb + 2, outline="#000", dash=(4, 3))
            for side, ((xa, ya), (xb, yb)) in bound_lines(self.bounds, w_mm, h_mm).items():
                (xa, ya), (xb, yb) = (MARGIN + xa * self.zoom, MARGIN + ya * self.zoom), (MARGIN + xb * self.zoom, MARGIN + yb * self.zoom)
                c.create_line(xa, ya, xb, yb, fill=BOUNDS_COLOUR, dash=(8, 4), width=4 if side == self.bsel else 2)
                label = dict(zip(BOUND_SIDES, (dict(x=xa + 4, y=ya - 3, anchor="sw"), dict(x=xa + 4, y=ya + 3, anchor="nw"),
                                               dict(x=xa - 3, y=ya + 4, anchor="ne"), dict(x=xa + 3, y=ya + 4, anchor="nw"))))[side]
                c.create_text(label["x"], label["y"], text=side, anchor=label["anchor"], fill=BOUNDS_COLOUR,
                              font=("TkDefaultFont", 8, "bold"))
            if self.show_effective:
                for x0, y0, x1, y1 in effective_holes(derived or [], self.boxes, w_mm, h_mm):
                    c.create_rectangle(MARGIN + x0 * self.zoom, MARGIN + y0 * self.zoom, MARGIN + x1 * self.zoom,
                                       MARGIN + y1 * self.zoom, outline="#ff7f0e", width=2, dash=(6, 3))

        def _refresh(self):
            self._redraw()
            self._fill_list()
            self.bounds_label.config(text="Bounds\n" + "\n".join(bound_rows(self.bounds, w_mm, h_mm)))
            self._status()

        def _fill_list(self):
            self._busy = True
            self.listbox.delete(0, "end")
            for row in list_rows(self.boxes, w_mm, h_mm):
                self.listbox.insert("end", row)
            if self.sel is not None:
                self.listbox.selection_set(self.sel)
                self.listbox.see(self.sel)
            self._busy = False

        def _status(self, cursor=None):
            where = "" if cursor is None else f"x {cursor[0] * w_mm:.1f} mm  y {cursor[1] * h_mm:.1f} mm   "
            effective = "  |  effective holes shown" if self.show_effective else ""
            if self.bounds_mode:
                mode = "bounds mode (B)" + ("" if self.bsel is None else
                                            f": {bound_rows(self.bounds, w_mm, h_mm)[BOUND_SIDES.index(self.bsel)]} selected")
            else:
                mode = f"new: {self.default_type} (T)"
            self.status.config(text=f"{where}{mode}{effective}"
                                    f"  |  {len(self.boxes)} box(es){'  |  UNSAVED' if self.dirty else ''}")

        # -- mouse --
        def _on_down(self, event):
            self.canvas.focus_set()
            fx, fy = self._frac(event)
            if self.bounds_mode:          # only the four lines are selectable; dragging on empty space draws nothing
                self.bsel = hit_bound(self.bounds, fx, fy, w_mm, h_mm)
                self.drag = None if self.bsel is None else ("bound", fx, fy)
                self._refresh()
                return
            i = hit_box(self.boxes, fx, fy, w_mm, h_mm, types=("edge",) if self.default_type == "edge" else None)
            if i is not None and i == self.sel:
                self.drag = ("move", fx, fy)
            elif i is not None:
                self.sel = i
                self.drag = None
                self._refresh()
            else:
                self.sel = None
                self.drag = ("draw", *self._frac(event, clamp=self.default_type != "edge"))
                self._refresh()

        def _on_move(self, event):
            if not self.drag:
                return
            fx, fy = self._frac(event, clamp=not (self.drag[0] == "draw" and self.default_type == "edge"))
            self._status(self._frac(event))
            mode, x0, y0 = self.drag
            if mode == "bound":          # the line follows the mouse along its own axis only
                self.bounds = move_bound(self.bounds, self.bsel, fy if self.bsel in ("back", "front") else fx, w_mm, h_mm)
                self._redraw()
                self.bounds_label.config(text="Bounds\n" + "\n".join(bound_rows(self.bounds, w_mm, h_mm)))
                return
            if mode == "move":
                self.boxes[self.sel] = move_box(self.boxes[self.sel], fx - x0, fy - y0)
                self.drag = ("move", fx, fy)
                self._redraw()
                return
            self.canvas.delete("rubber")
            (xa, ya), (xb, yb) = self._px(x0, y0), self._px(fx, fy)
            if self.default_type == "edge":   # a rubber-band line; on release it snaps to the nearest board side
                self.canvas.create_line(xa, ya, xb, yb, fill=COLOURS["edge"], dash=(4, 3), width=3, tags="rubber")
            else:
                self.canvas.create_rectangle(xa, ya, xb, yb, outline=COLOURS[self.default_type], dash=(4, 3), width=2, tags="rubber")

        def _on_up(self, event):
            drag, self.drag = self.drag, None
            if not drag or drag[0] != "draw":
                self._refresh()
                return
            fx, fy = self._frac(event, clamp=self.default_type != "edge")
            box = normalize_box(drag[1], drag[2], fx, fy, self.default_type, w_mm, h_mm)
            if box is not None:
                self.boxes.append(box)
                self.sel = len(self.boxes) - 1
            elif self.default_type == "edge":
                self._refresh()
                self.status.config(text="Edge segment too short (less than 1 mm along the side): not added.")
                return
            self._refresh()

        def _on_hover(self, event):
            self._status(self._frac(event))

        def _on_list_select(self, event):
            if self._busy or self.bounds_mode:
                return
            picked = self.listbox.curselection()
            if picked:
                self.sel = picked[0]
                self._redraw()
                self.canvas.focus_set()

        # -- actions --
        def _zoom(self, f):
            self.zoom = min(12.0, max(1.0, self.zoom * f))
            self._redraw()

        def _set_type(self, type_):
            """The type of the next drawn entry (radio buttons, keys 1 / 2 / 3) or "bounds" (B): bounds mode; no box and no
            bounds line stays selected."""
            self.default_type, self.sel, self.bsel = type_, None, None
            self.type_var.set(type_)
            self._refresh()

        def _deselect(self):
            self.sel, self.bsel = None, None
            self._refresh()

        def _toggle_type(self):
            if self.bounds_mode:
                return
            if self.sel is None or self.boxes[self.sel]["type"] == "edge":
                self.default_type = next_type(self.default_type)
                self.type_var.set(self.default_type)
            else:
                self.boxes[self.sel] = toggle_type(self.boxes[self.sel])
            self._refresh()

        def _toggle_effective(self):
            self.show_effective = not self.show_effective
            self._refresh()

        def _delete(self):
            if self.bounds_mode:          # puts the selected line back on the image edge
                if self.bsel is not None:
                    self.bounds = reset_bound(self.bounds, self.bsel)
                    self._refresh()
                return
            if self.sel is None:
                return
            del self.boxes[self.sel]
            self.sel = None
            self._refresh()

        def _nudge(self, d, step_mm):
            if self.bounds_mode:          # only along the line's own axis: Up / Down for back / front, Left / Right for left / right
                if self.bsel is not None and (d[1] != 0) == (self.bsel in ("back", "front")):
                    self.bounds = nudge_bound(self.bounds, self.bsel, d[0] * step_mm + d[1] * step_mm, w_mm, h_mm)
                    self._refresh()
                return
            if self.sel is None:
                return
            self.boxes[self.sel] = nudge_box(self.boxes[self.sel], d[0] * step_mm, d[1] * step_mm, w_mm, h_mm)
            self._refresh()

        def _reorder(self, delta):
            if self.sel is None:
                return
            self.boxes, self.sel = reorder(self.boxes, self.sel, delta)
            self._refresh()

        def _save(self):
            if not self.dirty and (pdir / EDITS_FILE).exists():
                self.status.config(text=f"No changes: {EDITS_FILE} is up to date.")
                return True
            try:
                path = save_edits(pdir, self.boxes, self.bounds)
            except OSError as e:
                messagebox.showerror("Save failed", str(e))
                return False
            self.saved = [dict(b) for b in self.boxes]
            self.saved_bounds = dict(self.bounds)
            self._status()
            self.status.config(text=f"Saved {path} ({len(self.boxes)} box(es)). Run uv run scripts/build.py to apply.")
            return True

        def _close(self):
            if self.dirty:
                answer = messagebox.askyesnocancel("Unsaved changes", "Save before closing?")
                if answer is None or (answer and not self._save()):
                    return
            self.destroy()

    return App()


def run_app(*args, **kw):
    make_app(*args, **kw).mainloop()


# --- entry point ---------------------------------------------------------------------------------
def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("project", nargs="?", help="project folder name")
    ap.add_argument("--list", action="store_true", help="every project with its board image, derived holes and edit boxes")
    ap.add_argument("--image", help="use this local PNG as the board image")
    args = ap.parse_args(argv)

    db = database("pedalboards.json")
    known = boards.load()
    if args.list:
        print("\n".join(project_rows(None, db, known)))
        return
    if not args.project:
        ap.error("give a project name, or use --list")
    pdir = project_dirs([args.project])[0]
    try:
        name, w_mm, h_mm = board_image_for(pdir, load_json(pdir / "project.json"), db)
    except ValueError as e:
        sys.exit(f"{args.project}: {e}")
    derived = known[name]["holes"] if name in known else None
    if derived is None:
        print(f"No derived holes for {name}: run  uv run scripts/boards.py {args.project}  to derive them "
              "(the editor opens without that overlay).", file=sys.stderr)
    image = Path(args.image) if args.image else common.fetch_image(name, kind="pedalboards")
    if not os.environ.get("DISPLAY") and sys.platform.startswith("linux"):
        sys.exit("No display found (DISPLAY is not set): the board editor needs a desktop session.")
    run_app(pdir, image, name, w_mm, h_mm, derived)


if __name__ == "__main__":
    main()
