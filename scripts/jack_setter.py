#!/usr/bin/env python3
"""Place jacks on a pedal's (or power supply's) Pedal Playground image.

    python3 scripts/jack_setter.py <catalog id>          open the app (new jacks, or edit existing ones)
    python3 scripts/jack_setter.py --list-missing [project ...]   what still needs jacks, with the commands
    python3 scripts/jack_setter.py --list                all catalog ids and how many jacks each has
    python3 scripts/jack_setter.py <catalog id> --image FILE      mark on a local PNG instead of downloading

The image is downloaded on demand into .cache/images/ (git-ignored) and never copied into the repo.
Mark each jack at the OUTER EDGE of the physical socket (where the plug starts), not its centre: the clearance
zone and the cable begin at that point. Saving writes only id / label / function / x / y / facing for that
catalog id into catalog/jacks.json, x and y as fractions of the image. The app shows millimetres: the image is stretched to the pedal's
Pedal Playground size, exactly as the site draws it.

In the app: click empty space to add a jack, click or drag a marker to select/move it, arrow keys nudge
(0.5 mm, Shift 2 mm), Delete removes, Ctrl+S saves, +/- or the mouse wheel zoom.
"""
import argparse
import difflib
import os
import sys
import urllib.request
from pathlib import Path

import design
import jacks
from common import CACHE, IN_MM, database, load_catalog, project_dirs

IMAGE_URLS = ("https://pedalplayground.com/app/images/pedals/{}", "https://pedalplayground.com/public/images/pedals/{}")
IMAGE_DIR = CACHE / "images"
FUNCTION_COLOURS = {"input": "#1565c0", "output": "#2e7d32", "power": "#ef6c00", "power_out": "#ef6c00", "other": "#6a1b9a"}


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
            req = urllib.request.Request(url, headers={"User-Agent": "pedalboard-jack-setter"})
            with urllib.request.urlopen(req, timeout=30) as r:
                data = r.read()
            tmp = path.with_suffix(".part")
            tmp.write_bytes(data)
            os.replace(tmp, path)
            return path
        except Exception as e:  # noqa: BLE001  (report every failure, then give up)
            errors.append(f"{url}: {e}")
    sys.exit("Could not download the image:\n  " + "\n  ".join(errors) + "\nUse --image FILE to mark on a local PNG instead.")


def list_ids(pedals, supplies):
    data = jacks.read_file()["jacks"]
    for kind, group in (("pedal", pedals), ("supply", supplies)):
        for cid in group:
            n = len(data.get(cid, []))
            print(f"{cid:28} {kind:6} {n} jack(s)")


def list_missing(names, pedals, supplies):
    import build  # late: build imports jacks, not the other way round

    wanted, in_project = {}, set()
    for pdir in project_dirs(names or None):
        ctx = build.validate(pdir, pedals, supplies)
        in_project.update(ctx["chain"])
        for cid, cmd in ctx["jack_fixes"]:
            wanted.setdefault(cid, (cmd, []))[1].append(pdir.name)
    if not wanted:
        print("Every pedal and supply used by these projects has a jack setup.")
    for cid, (cmd, projs) in wanted.items():
        print(f"{cmd}    # {', '.join(projs)}")
    data = jacks.read_file()["jacks"]
    spare = [cid for cid in pedals if cid not in in_project and not data.get(cid)]
    if spare and not names:
        print("\nNot in any project yet:\n  " + "\n  ".join(f"{COMMAND} {c}" for c in spare))


COMMAND = jacks.COMMAND


# --- the app ------------------------------------------------------------------------------------
def make_app(cid, kind, item, entry, image_path):
    """Build the Tkinter window (not yet running its main loop)."""
    import tkinter as tk
    from tkinter import messagebox, ttk

    from PIL import Image, ImageDraw, ImageTk

    MARGIN = 30
    HIT = 10  # px
    w_mm, h_mm = entry["Width"] * IN_MM, entry["Height"] * IN_MM
    ports = [o["port"] for o in (item.get("outputs") or [])] if kind == "supply" else []

    class App(tk.Tk):
        def __init__(self):
            super().__init__()
            self.img = Image.open(image_path).convert("RGBA")
            self.alpha = __import__("numpy").asarray(self.img.getchannel("A").resize((256, round(256 * h_mm / w_mm)), Image.BILINEAR))
            self.jacks = [dict(j) for j in jacks.read_file()["jacks"].get(cid, [])]
            self.sel, self.dirty, self.drag, self._busy = None, False, False, False
            self.zoom = min(680 / h_mm, 860 / w_mm)  # px per mm
            self.photo = None
            self.title(f"{item.get('brand')} {item.get('name') or item.get('model')} ({cid}) - {w_mm:.1f} x {h_mm:.1f} mm")
            self._build_widgets()
            self.protocol("WM_DELETE_WINDOW", self._close)
            self._redraw()
            self._refresh_panel()

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
            note = tk.Label(panel, justify="left", anchor="w", wraplength=300, background="#fff3cd", foreground="#664d03",
                            relief="solid", borderwidth=1, padx=8, pady=6, text=(
                "\u26a0  Put each point on the OUTER EDGE of the physical jack\n"
                "the point where the plug starts, on the face the plug presses against. Not the middle of the socket.\n"
                "The cable clearance zone (pink) and the cable start there, so it must lie outside the pedal."))
            note.pack(fill="x", pady=(0, 8))
            ttk.Label(panel, text="Jacks").pack(anchor="w")
            self.listbox = tk.Listbox(panel, height=9, width=34, exportselection=False)
            self.listbox.pack(fill="x")
            self.listbox.bind("<<ListboxSelect>>", self._on_list_select)

            form = ttk.Frame(panel)
            form.pack(fill="x", pady=6)
            self.v_label, self.v_function, self.v_facing = tk.StringVar(), tk.StringVar(), tk.StringVar()
            self.v_default, self.v_x, self.v_y = tk.BooleanVar(), tk.StringVar(), tk.StringVar()
            self.v_out, self.v_side = tk.StringVar(value=f"{jacks.CLEARANCE_DEFAULT['outward_mm']:g}"), tk.StringVar(value=f"{jacks.CLEARANCE_DEFAULT['side_mm']:g}")
            row = 0
            if kind == "supply":
                ttk.Label(form, text="Port").grid(row=row, column=0, sticky="w")
                self.port_box = ttk.Combobox(form, textvariable=self.v_label, values=ports, width=22)
                self.port_box.grid(row=row, column=1, sticky="ew")
                self.port_box.bind("<<ComboboxSelected>>", lambda e: self._apply_label())
                row += 1
            ttk.Label(form, text="Label").grid(row=row, column=0, sticky="w")
            self.label_entry = ttk.Entry(form, textvariable=self.v_label, width=25)
            self.label_entry.grid(row=row, column=1, sticky="ew")
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
            for text, var, axis in (("x (mm)", self.v_x, "x"), ("y (mm)", self.v_y, "y")):
                ttk.Label(form, text=text).grid(row=row, column=0, sticky="w")
                e = ttk.Entry(form, textvariable=var, width=12)
                e.grid(row=row, column=1, sticky="w")
                e.bind("<Return>", lambda ev, a=axis: self._apply_mm(a))
                e.bind("<FocusOut>", lambda ev, a=axis: self._apply_mm(a))
                row += 1
            self.frac_label = ttk.Label(form, text="")
            self.frac_label.grid(row=row, column=1, sticky="w")
            row += 1
            self.zone_label = tk.Label(form, text="", justify="left", anchor="w", wraplength=290, padx=4)
            self.zone_label.grid(row=row, column=0, columnspan=2, sticky="ew", pady=(4, 0))
            ttk.Separator(panel).pack(fill="x", pady=6)
            prev = ttk.Frame(panel)
            prev.pack(fill="x")
            ttk.Label(prev, text="Clearance preview (mm)  outward").grid(row=0, column=0, sticky="w")
            ttk.Entry(prev, textvariable=self.v_out, width=5).grid(row=0, column=1)
            ttk.Label(prev, text="side").grid(row=0, column=2)
            ttk.Entry(prev, textvariable=self.v_side, width=5).grid(row=0, column=3)
            for v in (self.v_out, self.v_side):
                v.trace_add("write", lambda *a: self._redraw())
            btns = ttk.Frame(panel)
            btns.pack(fill="x", pady=8)
            ttk.Button(btns, text="Delete jack", command=self._delete).pack(side="left")
            ttk.Button(btns, text="Save (Ctrl+S)", command=self._save).pack(side="right")
            ttk.Label(panel, wraplength=290, foreground="#555", text=(
                "Mark the OUTER EDGE of the physical jack: the point where the plug starts, on the face the plug presses against "
                "(not the middle of the socket). The clearance zone and the cable begin there. Then set which side the plug enters from. "
                "Click empty space to add, drag to move, arrow keys to nudge (Shift = 2 mm).")).pack(anchor="w", pady=4)

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
            for key, d in (("Left", (-1, 0)), ("Right", (1, 0)), ("Up", (0, -1)), ("Down", (0, 1))):
                self.bind(f"<{key}>", lambda e, d=d: self._guard(lambda: self._nudge(d, 0.5)))
                self.bind(f"<Shift-{key}>", lambda e, d=d: self._guard(lambda: self._nudge(d, 2.0)))

        def _guard(self, fn):
            if not isinstance(self.focus_get(), (tk.Entry, ttk.Entry, ttk.Combobox)):
                fn()

        # -- is the clearance zone really outside the pedal? (uses the image's transparency) --
        def zone_overlap(self, j):
            """Fraction (0..1) of the jack's clearance zone covering opaque pedal pixels, or None if the preview values are invalid."""
            try:
                outward, side = float(self.v_out.get()), float(self.v_side.get())
            except ValueError:
                return None
            x0, y0, x1, y1 = design.clearance_rect((j["x"] * w_mm, j["y"] * h_mm), j["facing"], outward, side)
            ih, iw = self.alpha.shape
            c0, c1 = max(0, int(x0 / w_mm * iw)), min(iw, int(x1 / w_mm * iw) + 1)
            r0, r1 = max(0, int(y0 / h_mm * ih)), min(ih, int(y1 / h_mm * ih) + 1)
            if c1 <= c0 or r1 <= r0:
                return 0.0  # the whole zone is outside the image
            opaque_mm2 = float((self.alpha[r0:r1, c0:c1] > 128).sum()) * (w_mm / iw) * (h_mm / ih)
            return min(1.0, opaque_mm2 / ((x1 - x0) * (y1 - y0)))  # share of the WHOLE zone, parts beyond the image count as free

        def _refresh_zone(self):
            if self.sel is None:
                self.zone_label.config(text="", background=self.cget("background"))
                return
            frac = self.zone_overlap(self.jacks[self.sel])
            if frac is None:
                self.zone_label.config(text="", background=self.cget("background"))
            elif frac > 0.08:
                self.zone_label.config(background="#f8d7da", foreground="#842029", text=(
                    f"\u26a0 {frac * 100:.0f}% of the clearance zone lies on the pedal body. The point is inside the pedal: "
                    "move it outward to the jack's outer edge."))
            else:
                self.zone_label.config(background="#d1e7dd", foreground="#0f5132", text="\u2713 Clearance zone is outside the pedal body.")

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
            try:
                outward, side = float(self.v_out.get()), float(self.v_side.get())
            except ValueError:
                outward = side = None
            self._refresh_zone()
            for i, j in enumerate(self.jacks):
                px, py = self.to_px(j["x"], j["y"])
                colour = FUNCTION_COLOURS.get(j["function"], "#333")
                selected = i == self.sel
                if selected and outward is not None:
                    zone = design.clearance_rect((j["x"] * w_mm, j["y"] * h_mm), j["facing"], outward, side)
                    c.create_rectangle(MARGIN + zone[0] * self.zoom, MARGIN + zone[1] * self.zoom, MARGIN + zone[2] * self.zoom,
                                       MARGIN + zone[3] * self.zoom, outline="#d81b60", dash=(3, 2), fill="#f8bbd0", stipple="gray25")
                dx, dy = design.FACING[j["facing"]]
                c.create_line(px, py, px + dx * 22, py + dy * 22, arrow="last", fill=colour, width=2)
                r = 7 if selected else 5
                c.create_oval(px - r, py - r, px + r, py + r, outline="#ffd600" if selected else "#000", width=3 if selected else 1, fill=colour)
                c.create_text(px + 10, py - 12, text=j["label"], anchor="w", font=("TkDefaultFont", 9, "bold" if selected else "normal"))

        # -- jacks --
        def _new_jack(self, fx, fy):
            have = {j["function"] for j in self.jacks}
            ids = [j["id"] for j in self.jacks]
            facing = jacks.guess_facing(fx, fy)
            if kind == "supply":
                free = [p for p in ports if p not in ids]
                port = free[0] if free else "port"
                return {"id": port, "label": port, "function": "power_out", "x": fx, "y": fy, "facing": facing}
            for fn, jid, label in (("input", "in", "Input"), ("output", "out", "Output"), ("power", "power", "Power")):
                if fn not in have:
                    return {"id": jid, "label": label, "function": fn, "x": fx, "y": fy, "facing": facing}
            n = len(self.jacks) + 1
            return {"id": jacks.unique_id(ids, f"jack {n}"), "label": f"Jack {n}", "function": "other", "x": fx, "y": fy, "facing": facing}

        def _select(self, i):
            self.sel = i
            self._refresh_panel()
            self._redraw()

        def _on_down(self, e):
            self.canvas.focus_set()
            for i, j in enumerate(self.jacks):
                px, py = self.to_px(j["x"], j["y"])
                if (px - e.x) ** 2 + (py - e.y) ** 2 <= HIT ** 2:
                    self.drag = True
                    return self._select(i)
            fx, fy = self.from_px(e.x, e.y)
            if -0.02 <= fx <= 1.02 and -0.02 <= fy <= 1.02:
                self.jacks.append(self._new_jack(min(1, max(0, fx)), min(1, max(0, fy))))
                self.dirty, self.drag = True, True
                self._select(len(self.jacks) - 1)

        def _on_move(self, e):
            if self.drag and self.sel is not None:
                fx, fy = self.from_px(e.x, e.y)
                j = self.jacks[self.sel]
                j["x"], j["y"] = min(1, max(0, fx)), min(1, max(0, fy))
                self.dirty = True
                self._redraw()
                self._refresh_coords()

        def _on_hover(self, e):
            fx, fy = self.from_px(e.x, e.y)
            if -0.01 <= fx <= 1.01 and -0.01 <= fy <= 1.01:
                self.status.config(text=f"x {fx * w_mm:.1f} mm   y {fy * h_mm:.1f} mm   (fx {fx:.3f}, fy {fy:.3f})   zoom {self.zoom:.2f} px/mm"
                                        + ("   *unsaved*" if self.dirty else ""))

        def _nudge(self, d, step_mm):
            if self.sel is None:
                return
            j = self.jacks[self.sel]
            j["x"] = min(1, max(0, j["x"] + d[0] * step_mm / w_mm))
            j["y"] = min(1, max(0, j["y"] + d[1] * step_mm / h_mm))
            self.dirty = True
            self._redraw()
            self._refresh_coords()

        def _delete(self):
            if self.sel is None:
                return
            del self.jacks[self.sel]
            self.dirty = True
            self.sel = None if not self.jacks else min(self.sel, len(self.jacks) - 1)
            self._refresh_panel()
            self._redraw()

        def _zoom(self, f):
            self.zoom = min(8.0, max(1.0, self.zoom * f))
            self._redraw()

        def _apply(self, key, value):
            if self._busy or self.sel is None:
                return
            if key == "default" and not value:
                self.jacks[self.sel].pop("default", None)
            else:
                self.jacks[self.sel][key] = value
            self.dirty = True
            self._refresh_panel(keep_selection=True)
            self._redraw()

        def _apply_label(self):
            if self._busy or self.sel is None:
                return
            j = self.jacks[self.sel]
            j["label"] = self.v_label.get()
            if kind == "supply":
                j["id"] = self.v_label.get()
            self.dirty = True
            self._refresh_list()
            self._redraw()

        def _apply_mm(self, axis):
            if self._busy or self.sel is None:
                return
            try:
                v = float((self.v_x if axis == "x" else self.v_y).get())
            except ValueError:
                return self._refresh_coords()
            j = self.jacks[self.sel]
            j[axis] = min(1, max(0, v / (w_mm if axis == "x" else h_mm)))
            self.dirty = True
            self._refresh_coords()
            self._redraw()

        # -- panel --
        def _refresh_list(self):
            self.listbox.delete(0, "end")
            for j in self.jacks:
                self.listbox.insert("end", f"{j['label']}  ({j['function']}, {j['facing']}{', default' if j.get('default') else ''})")
            if self.sel is not None:
                self.listbox.selection_set(self.sel)

        def _refresh_coords(self):
            if self.sel is None:
                self.v_x.set("")
                self.v_y.set("")
                self.frac_label.config(text="")
                return
            j = self.jacks[self.sel]
            self._busy = True
            self.v_x.set(f"{j['x'] * w_mm:.1f}")
            self.v_y.set(f"{j['y'] * h_mm:.1f}")
            self.frac_label.config(text=f"fractions: {j['x']:.4f}, {j['y']:.4f}")
            self._busy = False

        def _refresh_panel(self, keep_selection=False):
            self._busy = True
            self._refresh_list()
            if self.sel is None:
                for v in (self.v_label, self.v_function, self.v_facing):
                    v.set("")
                self.v_default.set(False)
            else:
                j = self.jacks[self.sel]
                self.v_label.set(j["label"])
                self.v_function.set(j["function"])
                self.v_facing.set(j["facing"])
                self.v_default.set(bool(j.get("default")))
            self._busy = False
            self._refresh_coords()

        def _on_list_select(self, e):
            sel = self.listbox.curselection()
            if sel and sel[0] != self.sel:
                self._select(sel[0])

        # -- saving --
        def _problems(self):
            msgs, seen = [], set()
            for j in self.jacks:
                if j["id"] in seen:
                    msgs.append(f"two jacks share the id '{j['id']}'")
                seen.add(j["id"])
            for fn in jacks.FUNCTIONS:
                if sum(1 for j in self.jacks if j["function"] == fn and j.get("default")) > 1:
                    msgs.append(f"more than one default {fn} jack")
            return msgs

        def _save(self):
            msgs = self._problems()
            if msgs:
                messagebox.showerror("Cannot save", "\n".join(msgs))
                return False
            jacks.save_jacks(cid, self.jacks)
            self.dirty = False
            self.status.config(text=f"Saved {len(self.jacks)} jack(s) for {cid} to catalog/jacks.json")
            return True

        def _close(self):
            if self.dirty:
                answer = messagebox.askyesnocancel("Unsaved changes", "Save the jacks before closing?")
                if answer is None or (answer and not self._save()):
                    return
            self.destroy()

    return App()


def run_app(*args):
    make_app(*args).mainloop()


# --- entry point --------------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("catalog_id", nargs="?", help="pedal or supply id from the catalog")
    ap.add_argument("--list", action="store_true", help="list every catalog id with its jack count")
    ap.add_argument("--list-missing", nargs="*", metavar="PROJECT", help="list items without a complete jack setup, with the commands")
    ap.add_argument("--image", help="mark on this local image file instead of downloading one")
    ap.add_argument("--refresh", action="store_true", help="download the image again")
    args = ap.parse_args()

    pedals, supplies = load_catalog()
    if args.list:
        return list_ids(pedals, supplies)
    if args.list_missing is not None:
        return list_missing(args.list_missing, pedals, supplies)
    if not args.catalog_id:
        ap.error("give a catalog id, or use --list / --list-missing")
    kind, item = find_entity(args.catalog_id, pedals, supplies)
    entry = database_entry(item, args.catalog_id)
    image = Path(args.image) if args.image else fetch_image(entry["Image"], args.refresh)
    if not os.environ.get("DISPLAY") and sys.platform.startswith("linux"):
        sys.exit("No display found (DISPLAY is not set): the jack-setter needs a desktop session.")
    run_app(args.catalog_id, kind, item, entry, image)


if __name__ == "__main__":
    main()
