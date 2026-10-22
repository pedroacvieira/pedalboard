#!/usr/bin/env python3
"""Place jacks and footswitches on a pedal's (or a power supply's jacks on its) Pedal Playground image.

    python3 scripts/pedal_editor.py <catalog id>                  open the editor on the jacks
    python3 scripts/pedal_editor.py <catalog id> --footswitches   open it on the footswitches (pedals only)
    python3 scripts/pedal_editor.py --list                        every catalog id with its jack and footswitch counts
    python3 scripts/pedal_editor.py --list-missing [project ...] [--only jacks|footswitches]
                                                                  what is still missing, with the commands
    python3 scripts/pedal_editor.py <catalog id> --image FILE     mark on a local PNG instead of downloading

The image is downloaded on demand into .cache/images/ (git-ignored) and never copied into the repo.
Jacks: mark each one at the OUTER EDGE of the physical socket (where the plug starts), not its centre: the
clearance zone and the cable begin there. Saved to catalog/jacks.json (id / label / function / x / y / facing).
Footswitches: mark the CENTRE of each switch cap and say whether it is a bypass switch (turns the pedal, or one
side of it, on/off) or another switch (preset, toggle...), and whether it is a tap-tempo switch. Saved to catalog/footswitches.json; tick
"This pedal has no footswitch" to record that there is none ([]). x and y are stored as fractions of the image;
the editor shows millimetres (the image is stretched to the pedal's Pedal Playground size, as the site draws it).

In the editor: J / F switch between jacks and footswitches, click empty space to add one, click or drag a
marker to select/move it, arrow keys nudge (0.5 mm, Shift 2 mm), Delete removes, Ctrl+S saves (each file only if
it changed), +/- or the mouse wheel zoom.
"""
import argparse
import difflib
import os
import sys
import urllib.request
from pathlib import Path

import design
import footswitches
import jacks
from common import CACHE, IN_MM, database, load_catalog, project_dirs

IMAGE_URLS = ("https://pedalplayground.com/app/images/pedals/{}", "https://pedalplayground.com/public/images/pedals/{}")
IMAGE_DIR = CACHE / "images"
FUNCTION_COLOURS = {"input": "#1565c0", "output": "#2e7d32", "power": "#ef6c00", "power_out": "#ef6c00", "other": "#6a1b9a"}
FOOTSWITCH_COLOURS = {True: "#c62828", False: "#00838f"}   # bypass / other
COMMAND = jacks.COMMAND
MODES = ("jacks", "footswitches")
SPACING_PREVIEW_MM = 60.0   # dashed circle around a selected switch: diameter = this spacing (preview only)
ALPHA_WIDTH_PX = 256        # resolution of the transparency mask used for the on-body checks


# --- finding things (no GUI) -------------------------------------------------------------------
def find_entity(cid, pedals, supplies):
    if cid in pedals:
        return "pedal", pedals[cid]
    if cid in supplies:
        return "supply", supplies[cid]
    close = difflib.get_close_matches(cid, [*pedals, *supplies], n=4, cutoff=0.5)
    sys.exit(f"'{cid}' is not a pedal or supply id in the catalog." + (f" Did you mean: {', '.join(close)}?" if close else ""))


def database_entry(item, cid):
    title = item.get("playground_title")
    if not title:
        sys.exit(f"{cid} has no playground_title in the catalog, so there is no Pedal Playground image to mark. Set it first.")
    entry = database("pedals.json").get(title)
    if entry is None:
        sys.exit(f"'{title}' ({cid}) is not in Pedal Playground's pedal database. Check playground_title.")
    return entry


def fetch_image(image_name, refresh=False):
    """Download the PNG into .cache/images/ (larger version first); returns the cached path."""
    IMAGE_DIR.mkdir(parents=True, exist_ok=True)
    path = IMAGE_DIR / image_name
    if path.exists() and not refresh:
        return path
    errors = []
    for url in IMAGE_URLS:
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
    sys.exit("Could not download the image:\n  " + "\n  ".join(errors) + "\nUse --image FILE to mark on a local PNG instead.")


def list_rows(pedals, supplies, jacks_data, fs_data):
    """One line per catalog id: jack count, and footswitch count for pedals ('?' unknown, '0' verified none)."""
    rows = []
    for cid in pedals:
        fs = fs_data.get(cid)
        rows.append(f"{cid:28} pedal  {len(jacks_data.get(cid, [])):>2} jack(s)  {'?' if fs is None else len(fs):>2} footswitch(es)")
    for cid in supplies:
        rows.append(f"{cid:28} supply {len(jacks_data.get(cid, [])):>2} jack(s)   - footswitch(es)")
    return rows


def missing_lines(names, pedals, supplies, only=None, jacks_data=None, fs_data=None):
    """Lines for --list-missing: the editor command per catalog id with missing data (and the projects that need
    it), for jacks and/or footswitches (`only`). Without project names, catalog pedals in no project follow."""
    import build  # late: build imports jacks, not the other way round

    jacks_data = jacks.read_file()["jacks"] if jacks_data is None else jacks_data
    fs_data = footswitches.read_file()["footswitches"] if fs_data is None else fs_data
    kinds = [only] if only else list(MODES)
    wanted, in_project = {k: {} for k in kinds}, set()
    for pdir in project_dirs(names or None):
        ctx = build.validate(pdir, pedals, supplies, jacks_data, footswitch_data=fs_data)
        in_project.update(ctx["chain"])
        for kind in kinds:
            for cid, cmd in ctx["jack_fixes" if kind == "jacks" else "footswitch_fixes"]:
                wanted[kind].setdefault(cid, (cmd, []))[1].append(pdir.name)
    lines = []
    for kind in kinds:
        if len(kinds) > 1:
            lines.append(f"# {kind}")
        if not wanted[kind]:
            lines.append(f"Every {'pedal and supply' if kind == 'jacks' else 'pedal'} used by these projects has "
                         f"{'a jack setup' if kind == 'jacks' else 'footswitch data'}.")
        lines += [f"{cmd}    # {', '.join(projs)}" for cid, (cmd, projs) in wanted[kind].items()]
        if not names:
            spare = [cid for cid in pedals if cid not in in_project
                     and (not jacks_data.get(cid) if kind == "jacks" else cid not in fs_data)]
            suffix = "" if kind == "jacks" else " --footswitches"
            if spare:
                lines += ["", "Not in any project yet:"] + [f"  {COMMAND} {c}{suffix}" for c in spare]
        if len(kinds) > 1:
            lines.append("")
    return lines


# --- editing helpers (pure, tested) -------------------------------------------------------------
def new_jack(existing, fx, fy, kind, ports=()):
    """The jack a click adds: a supply's next free port, else the first missing input/output/power, else 'other'."""
    have = {j["function"] for j in existing}
    ids = [j["id"] for j in existing]
    facing = jacks.guess_facing(fx, fy)
    if kind == "supply":
        free = [p for p in ports if p not in ids]
        port = free[0] if free else "port"
        return {"id": port, "label": port, "function": "power_out", "x": fx, "y": fy, "facing": facing}
    for fn, jid, label in (("input", "in", "Input"), ("output", "out", "Output"), ("power", "power", "Power")):
        if fn not in have:
            return {"id": jid, "label": label, "function": fn, "x": fx, "y": fy, "facing": facing}
    n = len(existing) + 1
    return {"id": jacks.unique_id(ids, f"jack {n}"), "label": f"Jack {n}", "function": "other", "x": fx, "y": fy, "facing": facing}


def jack_problems(jack_list):
    """Why a jack list cannot be saved (duplicate ids, several defaults per function); [] if it can."""
    msgs, seen = [], set()
    for j in jack_list:
        if j["id"] in seen:
            msgs.append(f"two jacks share the id '{j['id']}'")
        seen.add(j["id"])
    for fn in jacks.FUNCTIONS:
        if sum(1 for j in jack_list if j["function"] == fn and j.get("default")) > 1:
            msgs.append(f"more than one default {fn} jack")
    return msgs


def new_footswitch(existing, fx, fy):
    """The switch a click adds: the first is the bypass switch; later ones are 'Switch n', not bypass (tick it)."""
    ids = [f["id"] for f in existing]
    if not existing:
        return {"id": "bypass", "label": "Bypass", "x": fx, "y": fy, "bypass": True}
    n = len(existing) + 1
    return {"id": jacks.unique_id(ids, f"switch {n}"), "label": f"Switch {n}", "x": fx, "y": fy, "bypass": False}


def footswitch_problems(fs_list, no_footswitch=False):
    """Why a footswitch list cannot be saved; [] if it can."""
    msgs, seen = [], set()
    for f in fs_list:
        if f["id"] in seen:
            msgs.append(f"two footswitches share the id '{f['id']}'")
        seen.add(f["id"])
        if not str(f.get("label", "")).strip():
            msgs.append(f"footswitch '{f['id']}' has no label")
    if fs_list and no_footswitch:
        msgs.append("'This pedal has no footswitch' is ticked but switches are placed")
    return msgs


def switch_kind(fs):
    """'bypass', 'tap', 'bypass, tap' or 'other': how the editor lists a switch."""
    kinds = [k for k in ("bypass", "tap") if fs.get(k)]
    return ", ".join(kinds) or "other"


def footswitch_payload(fs_list, no_footswitch):
    """What to store: the switches, [] when 'no footswitch' is ticked, None (unknown: remove the id) otherwise."""
    if fs_list:
        return fs_list
    return [] if no_footswitch else None


def alpha_mask(image, w_mm, h_mm, width=ALPHA_WIDTH_PX):
    """The image's transparency as a small 'L' image with the pedal's aspect ratio (Pillow only, no numpy)."""
    from PIL import Image
    return image.convert("RGBA").getchannel("A").resize((width, max(1, round(width * h_mm / w_mm))), Image.BILINEAR)


def opaque_fraction(alpha, rect_mm, w_mm, h_mm):
    """Share (0..1) of a rectangle (mm, image frame) that covers opaque pedal pixels (alpha > 128). Parts beyond the
    image count as free."""
    x0, y0, x1, y1 = rect_mm
    iw, ih = alpha.size
    c0, c1 = max(0, int(x0 / w_mm * iw)), min(iw, int(x1 / w_mm * iw) + 1)
    r0, r1 = max(0, int(y0 / h_mm * ih)), min(ih, int(y1 / h_mm * ih) + 1)
    if c1 <= c0 or r1 <= r0 or x1 <= x0 or y1 <= y0:
        return 0.0
    opaque = alpha.crop((c0, r0, c1, r1)).point(lambda a: 255 if a > 128 else 0).histogram()[255]
    return min(1.0, opaque * (w_mm / iw) * (h_mm / ih) / ((x1 - x0) * (y1 - y0)))


def on_body(alpha, fx, fy):
    """True if the image is opaque (alpha > 128) at fractions (fx, fy): a footswitch centre must be on the pedal."""
    iw, ih = alpha.size
    px, py = min(iw - 1, max(0, int(fx * iw))), min(ih - 1, max(0, int(fy * ih)))
    if not (0 <= fx <= 1 and 0 <= fy <= 1):
        return False
    return alpha.getpixel((px, py)) > 128


# --- the app ------------------------------------------------------------------------------------
def make_app(cid, kind, item, entry, image_path, start_mode="jacks"):
    """Build the Tkinter window (not yet running its main loop)."""
    import tkinter as tk
    from tkinter import messagebox, ttk

    from PIL import Image, ImageDraw, ImageTk

    MARGIN = 30
    HIT = 10  # px
    w_mm, h_mm = entry["Width"] * IN_MM, entry["Height"] * IN_MM
    ports = [o["port"] for o in (item.get("outputs") or [])] if kind == "supply" else []
    fs_stored = footswitches.read_file()["footswitches"].get(cid) if kind == "pedal" else None

    class App(tk.Tk):
        def __init__(self):
            super().__init__()
            self.img = Image.open(image_path).convert("RGBA")
            self.alpha = alpha_mask(self.img, w_mm, h_mm)
            self.lists = {"jacks": [dict(j) for j in jacks.read_file()["jacks"].get(cid, [])],
                          "footswitches": [dict(f) for f in (fs_stored or [])]}
            self.dirty = {"jacks": False, "footswitches": False}
            self.mode = start_mode if kind == "pedal" else "jacks"
            self.sel, self.drag, self._busy = None, False, False
            self.zoom = min(680 / h_mm, 860 / w_mm)  # px per mm
            self.photo = None
            self.title(f"{item.get('brand')} {item.get('name') or item.get('model')} ({cid}) - {w_mm:.1f} x {h_mm:.1f} mm")
            self._build_widgets()
            self.v_none.set(fs_stored == [])
            self.protocol("WM_DELETE_WINDOW", self._close)
            self._set_mode(self.mode)

        @property
        def items(self):
            return self.lists[self.mode]

        def _mark(self):
            self.dirty[self.mode] = True

        # -- layout --
        def _build_widgets(self):
            left = ttk.Frame(self)
            left.pack(side="left", fill="both", expand=True)
            self.canvas = tk.Canvas(left, background="#f4f4f4", highlightthickness=0)
            self.canvas.pack(fill="both", expand=True)
            self.status = ttk.Label(left, text="", anchor="w")
            self.status.pack(fill="x")
            panel = ttk.Frame(self, padding=8)
            panel.pack(side="right", fill="y")

            modes = ttk.Frame(panel)
            modes.pack(fill="x", pady=(0, 6))
            self.v_mode = tk.StringVar(value=self.mode)
            ttk.Radiobutton(modes, text="Jacks (J)", value="jacks", variable=self.v_mode,
                            command=lambda: self._set_mode(self.v_mode.get())).pack(side="left")
            ttk.Radiobutton(modes, text="Footswitches (F)", value="footswitches", variable=self.v_mode,
                            command=lambda: self._set_mode(self.v_mode.get()),
                            state="normal" if kind == "pedal" else "disabled").pack(side="left")

            self.list_title = ttk.Label(panel, text="Jacks")
            self.list_title.pack(anchor="w")
            self.listbox = tk.Listbox(panel, height=9, width=34, exportselection=False)
            self.listbox.pack(fill="x")
            self.listbox.bind("<<ListboxSelect>>", self._on_list_select)
            self.mode_frames = {"jacks": ttk.Frame(panel), "footswitches": ttk.Frame(panel)}
            self._build_jack_form(self.mode_frames["jacks"])
            self._build_footswitch_form(self.mode_frames["footswitches"])
            self.btns = ttk.Frame(panel)
            ttk.Button(self.btns, text="Delete", command=self._delete).pack(side="left")
            ttk.Button(self.btns, text="Save (Ctrl+S)", command=self._save).pack(side="right")
            self.help = ttk.Label(panel, wraplength=290, foreground="#555")

            c = self.canvas
            c.bind("<Button-1>", self._on_down)
            c.bind("<B1-Motion>", self._on_move)
            c.bind("<ButtonRelease-1>", lambda e: setattr(self, "drag", False))
            c.bind("<Motion>", self._on_hover)
            c.bind("<MouseWheel>", lambda e: self._zoom(1.1 if e.delta > 0 else 1 / 1.1))
            c.bind("<Button-4>", lambda e: self._zoom(1.1))
            c.bind("<Button-5>", lambda e: self._zoom(1 / 1.1))
            self.bind("<Control-s>", lambda e: self._save())
            self.bind("<Delete>", lambda e: self._guard(self._delete))
            self.bind("<plus>", lambda e: self._guard(lambda: self._zoom(1.15)))
            self.bind("<equal>", lambda e: self._guard(lambda: self._zoom(1.15)))
            self.bind("<minus>", lambda e: self._guard(lambda: self._zoom(1 / 1.15)))
            for key in ("j", "J"):
                self.bind(f"<Key-{key}>", lambda e: self._guard(lambda: self._set_mode("jacks")))
            for key in ("f", "F"):
                self.bind(f"<Key-{key}>", lambda e: self._guard(lambda: self._set_mode("footswitches")))
            for key, d in (("Left", (-1, 0)), ("Right", (1, 0)), ("Up", (0, -1)), ("Down", (0, 1))):
                self.bind(f"<{key}>", lambda e, d=d: self._guard(lambda: self._nudge(d, 0.5)))
                self.bind(f"<Shift-{key}>", lambda e, d=d: self._guard(lambda: self._nudge(d, 2.0)))

        def _coord_rows(self, form, row, vx, vy):
            for text, var, axis in (("x (mm)", vx, "x"), ("y (mm)", vy, "y")):
                ttk.Label(form, text=text).grid(row=row, column=0, sticky="w")
                e = ttk.Entry(form, textvariable=var, width=12)
                e.grid(row=row, column=1, sticky="w")
                e.bind("<Return>", lambda ev, a=axis: self._apply_mm(a))
                e.bind("<FocusOut>", lambda ev, a=axis: self._apply_mm(a))
                row += 1
            return row

        def _build_jack_form(self, frame):
            tk.Label(frame, justify="left", anchor="w", wraplength=300, background="#fff3cd", foreground="#664d03",
                     relief="solid", borderwidth=1, padx=8, pady=6, text=(
                "⚠  Put each point on the OUTER EDGE of the physical jack\n"
                "the point where the plug starts, on the face the plug presses against. Not the middle of the socket.\n"
                "The cable clearance zone (pink) and the cable start there, so it must lie outside the pedal.")).pack(fill="x", pady=(6, 0))
            form = ttk.Frame(frame)
            form.pack(fill="x", pady=6)
            self.v_label, self.v_function, self.v_facing = tk.StringVar(), tk.StringVar(), tk.StringVar()
            self.v_default, self.v_x, self.v_y = tk.BooleanVar(), tk.StringVar(), tk.StringVar()
            self.v_out = tk.StringVar(value=f"{jacks.CLEARANCE_DEFAULT['outward_mm']:g}")
            self.v_side = tk.StringVar(value=f"{jacks.CLEARANCE_DEFAULT['side_mm']:g}")
            row = 0
            if kind == "supply":
                ttk.Label(form, text="Port").grid(row=row, column=0, sticky="w")
                self.port_box = ttk.Combobox(form, textvariable=self.v_label, values=ports, width=22)
                self.port_box.grid(row=row, column=1, sticky="ew")
                self.port_box.bind("<<ComboboxSelected>>", lambda e: self._apply_label())
                row += 1
            ttk.Label(form, text="Label").grid(row=row, column=0, sticky="w")
            ttk.Entry(form, textvariable=self.v_label, width=25).grid(row=row, column=1, sticky="ew")
            self.v_label.trace_add("write", lambda *a: self._apply_label())
            row += 1
            ttk.Label(form, text="Function").grid(row=row, column=0, sticky="w")
            funcs = [f for f in jacks.FUNCTIONS if kind == "supply" or f != "power_out"]
            self.func_box = ttk.Combobox(form, textvariable=self.v_function, values=funcs, state="readonly", width=22)
            self.func_box.grid(row=row, column=1, sticky="ew")
            self.func_box.bind("<<ComboboxSelected>>", lambda e: self._apply("function", self.v_function.get()))
            row += 1
            ttk.Label(form, text="Plug enters from").grid(row=row, column=0, sticky="w")
            faces = ttk.Frame(form)
            faces.grid(row=row, column=1, sticky="w")
            for name, arrow in (("left", "← left"), ("top", "↑ top"), ("down", "↓ down"), ("right", "→ right")):
                ttk.Radiobutton(faces, text=arrow, value=name, variable=self.v_facing, command=lambda: self._apply("facing", self.v_facing.get())).pack(side="left")
            row += 1
            ttk.Checkbutton(form, text="default for its function", variable=self.v_default, command=lambda: self._apply("default", self.v_default.get())).grid(row=row, column=1, sticky="w")
            row += 1
            row = self._coord_rows(form, row, self.v_x, self.v_y)
            self.frac_label = ttk.Label(form, text="")
            self.frac_label.grid(row=row, column=1, sticky="w")
            row += 1
            self.zone_label = tk.Label(form, text="", justify="left", anchor="w", wraplength=290, padx=4)
            self.zone_label.grid(row=row, column=0, columnspan=2, sticky="ew", pady=(4, 0))
            ttk.Separator(frame).pack(fill="x", pady=6)
            prev = ttk.Frame(frame)
            prev.pack(fill="x")
            ttk.Label(prev, text="Clearance preview (mm)  outward").grid(row=0, column=0, sticky="w")
            ttk.Entry(prev, textvariable=self.v_out, width=5).grid(row=0, column=1)
            ttk.Label(prev, text="side").grid(row=0, column=2)
            ttk.Entry(prev, textvariable=self.v_side, width=5).grid(row=0, column=3)
            for v in (self.v_out, self.v_side):
                v.trace_add("write", lambda *a: self._redraw())

        def _build_footswitch_form(self, frame):
            tk.Label(frame, justify="left", anchor="w", wraplength=300, background="#e3f2fd", foreground="#0d47a1",
                     relief="solid", borderwidth=1, padx=8, pady=6, text=(
                "Put each point on the CENTRE of the switch cap. Record every switch (bypass, tap, preset, toggle...). "
                "Tick 'bypass' for switches that turn the pedal (or one side of it) on and off, 'tap tempo' for tap switches.")).pack(fill="x", pady=(6, 0))
            form = ttk.Frame(frame)
            form.pack(fill="x", pady=6)
            self.v_fs_label, self.v_bypass, self.v_tap = tk.StringVar(), tk.BooleanVar(), tk.BooleanVar()
            self.v_fs_x, self.v_fs_y = tk.StringVar(), tk.StringVar()
            self.v_none, self.v_spacing = tk.BooleanVar(), tk.StringVar(value=f"{SPACING_PREVIEW_MM:g}")
            ttk.Label(form, text="Label").grid(row=0, column=0, sticky="w")
            ttk.Entry(form, textvariable=self.v_fs_label, width=25).grid(row=0, column=1, sticky="ew")
            self.v_fs_label.trace_add("write", lambda *a: self._apply_label())
            ttk.Checkbutton(form, text="bypass switch (turns the pedal on/off)", variable=self.v_bypass,
                            command=lambda: self._apply("bypass", self.v_bypass.get())).grid(row=1, column=1, sticky="w")
            ttk.Checkbutton(form, text="tap tempo", variable=self.v_tap,
                            command=lambda: self._apply("tap", self.v_tap.get())).grid(row=2, column=1, sticky="w")
            row = self._coord_rows(form, 3, self.v_fs_x, self.v_fs_y)
            self.fs_frac_label = ttk.Label(form, text="")
            self.fs_frac_label.grid(row=row, column=1, sticky="w")
            self.body_label = tk.Label(form, text="", justify="left", anchor="w", wraplength=290, padx=4)
            self.body_label.grid(row=row + 1, column=0, columnspan=2, sticky="ew", pady=(4, 0))
            ttk.Separator(frame).pack(fill="x", pady=6)
            self.none_box = ttk.Checkbutton(frame, text="This pedal has no footswitch", variable=self.v_none, command=self._toggle_none)
            self.none_box.pack(anchor="w")
            prev = ttk.Frame(frame)
            prev.pack(fill="x", pady=(6, 0))
            ttk.Label(prev, text="Spacing preview (mm, dashed circle diameter)").grid(row=0, column=0, sticky="w")
            ttk.Entry(prev, textvariable=self.v_spacing, width=5).grid(row=0, column=1)
            self.v_spacing.trace_add("write", lambda *a: self._redraw())

        def _guard(self, fn):
            if not isinstance(self.focus_get(), (tk.Entry, ttk.Entry, ttk.Combobox, tk.Listbox)):  # arrows move the list there
                fn()

        # -- modes --
        def _set_mode(self, mode):
            if mode == "footswitches" and kind != "pedal":
                self.status.config(text="Power supplies have no footswitches.")
                mode = "jacks"
            if self.sel is not None:
                self._apply_mm("x")
                self._apply_mm("y")
            self.mode, self.sel = mode, None
            self.v_mode.set(mode)
            for m, f in self.mode_frames.items():
                f.pack_forget()
            self.btns.pack_forget()
            self.help.pack_forget()
            self.mode_frames[mode].pack(fill="x")
            self.btns.pack(fill="x", pady=8)
            self.help.config(text=(
                "Mark the OUTER EDGE of the physical jack: the point where the plug starts, on the face the plug presses against "
                "(not the middle of the socket). The clearance zone and the cable begin there. Then set which side the plug enters from. "
                if mode == "jacks" else
                "Mark the CENTRE of each switch cap. The dashed circle previews the spacing to another pedal's switch. ")
                + "Click empty space to add, drag to move, arrow keys to nudge (Shift = 2 mm). J / F switch mode.")
            self.help.pack(anchor="w", pady=4)
            self.list_title.config(text="Jacks" if mode == "jacks" else "Footswitches")
            self._refresh_panel()
            self._redraw()

        def _toggle_none(self):
            if self.lists["footswitches"]:
                self.v_none.set(False)
                messagebox.showinfo("Footswitches placed", "Delete the placed switches first.")
                return
            self.dirty["footswitches"] = True
            self._refresh_none()

        def _refresh_none(self):
            has = bool(self.lists["footswitches"])
            if has:
                self.v_none.set(False)
            self.none_box.config(state="disabled" if has else "normal")

        # -- on-body checks (the image's transparency) --
        def zone_overlap(self, j):
            """Fraction (0..1) of the jack's clearance zone covering opaque pedal pixels, or None if the preview values are invalid."""
            try:
                outward, side = float(self.v_out.get()), float(self.v_side.get())
            except ValueError:
                return None
            rect = design.clearance_rect((j["x"] * w_mm, j["y"] * h_mm), j["facing"], outward, side)
            return opaque_fraction(self.alpha, rect, w_mm, h_mm)

        def _refresh_zone(self):
            plain = {"text": "", "background": self.cget("background")}
            if self.mode == "footswitches":
                if self.sel is None:
                    return self.body_label.config(**plain)
                f = self.items[self.sel]
                if on_body(self.alpha, f["x"], f["y"]):
                    return self.body_label.config(background="#d1e7dd", foreground="#0f5132", text="✓ The switch centre is on the pedal body.")
                return self.body_label.config(background="#f8d7da", foreground="#842029",
                                              text="⚠ The switch centre is not on the pedal body (transparent pixel): move it onto the switch.")
            if self.sel is None:
                return self.zone_label.config(**plain)
            frac = self.zone_overlap(self.items[self.sel])
            if frac is None:
                self.zone_label.config(**plain)
            elif frac > 0.08:
                self.zone_label.config(background="#f8d7da", foreground="#842029", text=(
                    f"⚠ {frac * 100:.0f}% of the clearance zone lies on the pedal body. The point is inside the pedal: "
                    "move it outward to the jack's outer edge."))
            else:
                self.zone_label.config(background="#d1e7dd", foreground="#0f5132", text="✓ Clearance zone is outside the pedal body.")

        # -- coordinates --
        def to_px(self, fx, fy):
            return MARGIN + fx * w_mm * self.zoom, MARGIN + fy * h_mm * self.zoom

        def from_px(self, px, py):
            return (px - MARGIN) / (w_mm * self.zoom), (py - MARGIN) / (h_mm * self.zoom)

        # -- drawing --
        def _redraw(self):
            if self._busy:
                return
            wp, hp = round(w_mm * self.zoom), round(h_mm * self.zoom)
            base = Image.new("RGBA", (wp, hp), "#ffffff")
            d = ImageDraw.Draw(base)
            for gy in range(0, hp, 12):
                for gx in range(0, wp, 12):
                    if (gx // 12 + gy // 12) % 2:
                        d.rectangle([gx, gy, gx + 11, gy + 11], fill="#d9d9d9")
            base.alpha_composite(self.img.resize((wp, hp), Image.LANCZOS))
            self.photo = ImageTk.PhotoImage(base)
            c = self.canvas
            c.delete("all")
            c.config(width=wp + 2 * MARGIN, height=hp + 2 * MARGIN)
            c.create_image(MARGIN, MARGIN, image=self.photo, anchor="nw")
            c.create_rectangle(MARGIN, MARGIN, MARGIN + wp, MARGIN + hp, outline="#888")
            for mm in range(0, int(max(w_mm, h_mm)) + 1, 10):  # ruler ticks every 10 mm
                long = mm % 50 == 0
                if mm <= w_mm:
                    c.create_line(MARGIN + mm * self.zoom, MARGIN - (8 if long else 4), MARGIN + mm * self.zoom, MARGIN, fill="#555")
                    if long:
                        c.create_text(MARGIN + mm * self.zoom, MARGIN - 16, text=str(mm), font=("TkDefaultFont", 7), fill="#555")
                if mm <= h_mm:
                    c.create_line(MARGIN - (8 if long else 4), MARGIN + mm * self.zoom, MARGIN, MARGIN + mm * self.zoom, fill="#555")
                    if long:
                        c.create_text(MARGIN - 18, MARGIN + mm * self.zoom, text=str(mm), font=("TkDefaultFont", 7), fill="#555")
            c.create_line(MARGIN, MARGIN + hp + 16, MARGIN + 10 * self.zoom, MARGIN + hp + 16, width=3)
            c.create_text(MARGIN + 10 * self.zoom + 8, MARGIN + hp + 16, text="10 mm", anchor="w", font=("TkDefaultFont", 8))
            self._refresh_zone()
            # the other mode first, dimmed; then the active one
            for mode in sorted(MODES, key=lambda m: m == self.mode):
                active = mode == self.mode
                draw = self._draw_jack if mode == "jacks" else self._draw_footswitch
                for i, it in enumerate(self.lists[mode]):
                    draw(it, active, active and i == self.sel)

        def _draw_jack(self, j, active, selected):
            c = self.canvas
            px, py = self.to_px(j["x"], j["y"])
            colour = FUNCTION_COLOURS.get(j["function"], "#333") if active else "#9e9e9e"
            if selected:
                try:
                    outward, side = float(self.v_out.get()), float(self.v_side.get())
                    zone = design.clearance_rect((j["x"] * w_mm, j["y"] * h_mm), j["facing"], outward, side)
                    c.create_rectangle(MARGIN + zone[0] * self.zoom, MARGIN + zone[1] * self.zoom, MARGIN + zone[2] * self.zoom,
                                       MARGIN + zone[3] * self.zoom, outline="#d81b60", dash=(3, 2), fill="#f8bbd0", stipple="gray25")
                except ValueError:
                    pass
            dx, dy = design.FACING[j["facing"]]
            c.create_line(px, py, px + dx * 22, py + dy * 22, arrow="last", fill=colour, width=2 if active else 1)
            r = 7 if selected else 5
            c.create_oval(px - r, py - r, px + r, py + r, outline="#ffd600" if selected else ("#000" if active else "#9e9e9e"),
                          width=3 if selected else 1, fill=colour)
            if active:
                c.create_text(px + 10, py - 12, text=j["label"], anchor="w", font=("TkDefaultFont", 9, "bold" if selected else "normal"))

        def _draw_footswitch(self, f, active, selected):
            c = self.canvas
            px, py = self.to_px(f["x"], f["y"])
            colour = FOOTSWITCH_COLOURS[bool(f.get("bypass"))] if active else "#9e9e9e"
            if selected:
                try:
                    rad = float(self.v_spacing.get()) / 2 * self.zoom
                    c.create_oval(px - rad, py - rad, px + rad, py + rad, outline="#c62828", dash=(4, 3))
                except ValueError:
                    pass
            r = 8 if selected else 6
            c.create_oval(px - r, py - r, px + r, py + r, fill=colour, outline="#ffd600" if selected else ("#000" if active else "#9e9e9e"),
                          width=3 if selected else 1)
            c.create_line(px - r - 4, py, px + r + 4, py, fill="#000" if active else "#9e9e9e")
            c.create_line(px, py - r - 4, px, py + r + 4, fill="#000" if active else "#9e9e9e")
            if active:
                c.create_text(px + 12, py - 12, text=f"{f['label']} ({switch_kind(f)})", anchor="w",
                              font=("TkDefaultFont", 9, "bold" if selected else "normal"))

        # -- items --
        def _select(self, i):
            self.sel = i
            self._refresh_panel()
            self._redraw()

        def _on_down(self, e):
            self.canvas.focus_set()
            for i, it in enumerate(self.items):
                px, py = self.to_px(it["x"], it["y"])
                if (px - e.x) ** 2 + (py - e.y) ** 2 <= HIT ** 2:
                    self.drag = True
                    return self._select(i)
            fx, fy = self.from_px(e.x, e.y)
            if -0.02 <= fx <= 1.02 and -0.02 <= fy <= 1.02:
                fx, fy = min(1, max(0, fx)), min(1, max(0, fy))
                if self.mode == "jacks":
                    self.items.append(new_jack(self.items, fx, fy, kind, ports))
                else:
                    self.items.append(new_footswitch(self.items, fx, fy))
                    self._refresh_none()
                self._mark()
                self.drag = True
                self._select(len(self.items) - 1)

        def _on_move(self, e):
            if self.drag and self.sel is not None:
                fx, fy = self.from_px(e.x, e.y)
                it = self.items[self.sel]
                it["x"], it["y"] = min(1, max(0, fx)), min(1, max(0, fy))
                self._mark()
                self._redraw()
                self._refresh_coords()

        def _on_hover(self, e):
            fx, fy = self.from_px(e.x, e.y)
            if -0.01 <= fx <= 1.01 and -0.01 <= fy <= 1.01:
                unsaved = [m for m in MODES if self.dirty[m]]
                self.status.config(text=f"[{self.mode}]  x {fx * w_mm:.1f} mm   y {fy * h_mm:.1f} mm   (fx {fx:.3f}, fy {fy:.3f})   "
                                        f"zoom {self.zoom:.2f} px/mm" + (f"   *unsaved: {', '.join(unsaved)}*" if unsaved else ""))

        def _nudge(self, d, step_mm):
            if self.sel is None:
                return
            it = self.items[self.sel]
            it["x"] = min(1, max(0, it["x"] + d[0] * step_mm / w_mm))
            it["y"] = min(1, max(0, it["y"] + d[1] * step_mm / h_mm))
            self._mark()
            self._redraw()
            self._refresh_coords()

        def _delete(self):
            if self.sel is None:
                return
            del self.items[self.sel]
            self._mark()
            self.sel = None if not self.items else min(self.sel, len(self.items) - 1)
            if self.mode == "footswitches":
                self._refresh_none()
            self._refresh_panel()
            self._redraw()

        def _zoom(self, f):
            self.zoom = min(8.0, max(1.0, self.zoom * f))
            self._redraw()

        def _apply(self, key, value):
            if self._busy or self.sel is None:
                return
            if key in ("default", "tap") and not value:   # optional flags are stored only when true
                self.items[self.sel].pop("default", None)
            else:
                self.items[self.sel][key] = value
            self._mark()
            self._refresh_panel()
            self._redraw()

        def _apply_label(self):
            if self._busy or self.sel is None:
                return
            it = self.items[self.sel]
            if self.mode == "jacks":
                it["label"] = self.v_label.get()
                if kind == "supply":
                    it["id"] = self.v_label.get()
            else:
                it["label"] = self.v_fs_label.get()
            self._mark()
            self._refresh_list()
            self._redraw()

        def _coord_vars(self):
            return (self.v_x, self.v_y) if self.mode == "jacks" else (self.v_fs_x, self.v_fs_y)

        def _apply_mm(self, axis):
            if self._busy or self.sel is None:
                return
            vx, vy = self._coord_vars()
            try:
                v = float((vx if axis == "x" else vy).get())
            except ValueError:
                return self._refresh_coords()
            it = self.items[self.sel]
            new = min(1, max(0, v / (w_mm if axis == "x" else h_mm)))
            if abs(new * (w_mm if axis == "x" else h_mm) - it[axis] * (w_mm if axis == "x" else h_mm)) >= 0.05:
                it[axis] = new   # ignore the display rounding (0.1 mm) so a plain focus change is not an edit
                self._mark()
            self._refresh_coords()
            self._redraw()

        # -- panel --
        def _refresh_list(self):
            self.listbox.delete(0, "end")
            for it in self.items:
                if self.mode == "jacks":
                    self.listbox.insert("end", f"{it['label']}  ({it['function']}, {it['facing']}{', default' if it.get('default') else ''})")
                else:
                    self.listbox.insert("end", f"{it['label']}  ({switch_kind(it)})")
            if self.sel is not None:
                self.listbox.selection_set(self.sel)

        def _refresh_coords(self):
            vx, vy = self._coord_vars()
            frac = self.frac_label if self.mode == "jacks" else self.fs_frac_label
            self._busy = True
            if self.sel is None:
                vx.set("")
                vy.set("")
                frac.config(text="")
            else:
                it = self.items[self.sel]
                vx.set(f"{it['x'] * w_mm:.1f}")
                vy.set(f"{it['y'] * h_mm:.1f}")
                frac.config(text=f"fractions: {it['x']:.4f}, {it['y']:.4f}")
            self._busy = False

        def _refresh_panel(self):
            self._busy = True
            self._refresh_list()
            it = self.items[self.sel] if self.sel is not None else None
            if self.mode == "jacks":
                self.v_label.set(it["label"] if it else "")
                self.v_function.set(it["function"] if it else "")
                self.v_facing.set(it["facing"] if it else "")
                self.v_default.set(bool(it and it.get("default")))
            else:
                self.v_fs_label.set(it["label"] if it else "")
                self.v_bypass.set(bool(it and it.get("bypass")))
                self.v_tap.set(bool(it and it.get("tap")))
                self._refresh_none()
            self._busy = False
            self._refresh_coords()

        def _on_list_select(self, e):
            sel = self.listbox.curselection()
            if sel and sel[0] != self.sel:
                self._select(sel[0])

        # -- saving --
        def _save(self):
            if self.sel is not None:  # apply a value typed into x/y (mm) that Return/FocusOut has not applied yet
                self._apply_mm("x")
                self._apply_mm("y")
            msgs = jack_problems(self.lists["jacks"]) if self.dirty["jacks"] else []
            if self.dirty["footswitches"]:
                msgs += footswitch_problems(self.lists["footswitches"], self.v_none.get())
            if msgs:
                messagebox.showerror("Cannot save", "\n".join(msgs))
                return False
            done = []
            if self.dirty["jacks"]:
                jacks.save_jacks(cid, self.lists["jacks"])
                done.append(f"{len(self.lists['jacks'])} jack(s) to catalog/jacks.json")
            if self.dirty["footswitches"]:
                payload = footswitch_payload(self.lists["footswitches"], self.v_none.get())
                footswitches.save_footswitches(cid, payload)
                done.append("footswitches: " + ("unknown (removed)" if payload is None else
                                                "none" if not payload else f"{len(payload)}") + " to catalog/footswitches.json")
            self.dirty = {m: False for m in MODES}
            self.status.config(text=f"Saved {'; '.join(done)} for {cid}" if done else "Nothing to save")
            return True

        def _close(self):
            if any(self.dirty.values()):
                answer = messagebox.askyesnocancel("Unsaved changes", "Save before closing?")
                if answer is None or (answer and not self._save()):
                    return
            self.destroy()

    return App()


def run_app(*args, **kw):
    make_app(*args, **kw).mainloop()


# --- entry point --------------------------------------------------------------------------------
def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("catalog_id", nargs="?", help="pedal or supply id from the catalog")
    ap.add_argument("--footswitches", action="store_true", help="open the editor on the footswitches (pedals only)")
    ap.add_argument("--list", action="store_true", help="list every catalog id with its jack and footswitch counts")
    ap.add_argument("--list-missing", nargs="*", metavar="PROJECT", help="list items with missing data, with the commands")
    ap.add_argument("--only", choices=MODES, help="with --list-missing: only jacks or only footswitches")
    ap.add_argument("--image", help="mark on this local image file instead of downloading one")
    ap.add_argument("--refresh", action="store_true", help="download the image again")
    args = ap.parse_args(argv)

    if args.only and args.list_missing is None:
        ap.error("--only goes with --list-missing")
    pedals, supplies = load_catalog()
    if args.list:
        print("\n".join(list_rows(pedals, supplies, jacks.read_file()["jacks"], footswitches.read_file()["footswitches"])))
        return
    if args.list_missing is not None:
        print("\n".join(missing_lines(args.list_missing, pedals, supplies, args.only)))
        return
    if not args.catalog_id:
        ap.error("give a catalog id, or use --list / --list-missing")
    kind, item = find_entity(args.catalog_id, pedals, supplies)
    if args.footswitches and kind != "pedal":
        sys.exit(f"{args.catalog_id} is a power supply: supplies have no footswitches.")
    entry = database_entry(item, args.catalog_id)
    image = Path(args.image) if args.image else fetch_image(entry["Image"], args.refresh)
    if not os.environ.get("DISPLAY") and sys.platform.startswith("linux"):
        sys.exit("No display found (DISPLAY is not set): the pedal editor needs a desktop session.")
    run_app(args.catalog_id, kind, item, entry, image, start_mode="footswitches" if args.footswitches else "jacks")


if __name__ == "__main__":
    main()
