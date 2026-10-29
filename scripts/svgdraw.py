"""SVG drawing of a board and its signal cables (pure string building, mm everywhere).

`render(ctx, names)` is the whole picture (routing.svg): the board, the dashed routing area, pedals, jacks, plug heads,
cables (one colour each, a dark casing, an S# label), footswitches and a legend table below. The document is sized in
mm (width="..mm" height="..mm", viewBox in mm) so a browser prints it at true scale. Smaller functions draw one thing
each, so later pictures (power, a web UI) can reuse them. No pedal images unless `images` is given.
"""
import base64
import io
from xml.sax.saxutils import escape as _esc

import design
from jacks import default_jack

PALETTE = ["#c62828", "#1565c0", "#2e7d32", "#ef6c00", "#6a1b9a", "#00838f", "#ad1457", "#4e342e", "#827717",
           "#283593", "#558b2f", "#b71c1c", "#0277bd", "#e65100", "#4a148c", "#00695c", "#37474f", "#9e6b00",
           "#880e4f", "#1b5e20"]   # dark enough to read on white, 20 distinct hues
JACK_COLOURS = {"input": "#1565c0", "output": "#2e7d32", "power": "#ef6c00", "power_out": "#ef6c00", "other": "#6a1b9a"}
FOOTSWITCH_STYLE = {"bypass": ("#263238", "#263238"), "boost": ("#e53935", "#263238"), "tap": ("#1e88e5", "#263238"),
                    "function": ("#ffffff", "#263238")}   # footswitch dots: (fill, stroke) per type
INK, CASING, GREY = "#263238", "#1c2428", "#78909c"
POWER_COLOUR = "#6d4c41"   # DC power cables: one neutral (brown) family, thinner than the patch cables
POWER_WIDTH = 1.2          # mm drawn
PAD = 10.0          # white border round the board (mm)
FONT = 2.8          # legend font (mm; >= 2.5 so it reads when printed at 1:1)
CHAR = 0.56         # average glyph width / font size (sans-serif estimate)
ROW = 4.6           # legend table row height
IMAGE_PX = 600      # embedded pedal images: at most this many px on the long side


def esc(s):
    return _esc(str(s), {'"': "&quot;"})


def f1(v):
    return f"{v:.1f}"


def rect(x0, y0, x1, y1, **attrs):
    return f'<rect x="{f1(x0)}" y="{f1(y0)}" width="{f1(x1 - x0)}" height="{f1(y1 - y0)}"{_attrs(attrs)}/>'


def _attrs(attrs):
    return "".join(f' {k.rstrip("_").replace("_", "-")}="{esc(v)}"' for k, v in attrs.items() if v is not None)


def text(x, y, s, size=FONT, anchor="start", fill=INK, halo=False, **attrs):
    extra = {"stroke": "#ffffff", "stroke_width": round(size * 0.35, 2), "paint_order": "stroke", "stroke_linejoin": "round"} if halo else {}
    return (f'<text x="{f1(x)}" y="{f1(y)}" font-size="{size:g}" text-anchor="{anchor}" fill="{fill}"{_attrs({**extra, **attrs})}>'
            f'{esc(s)}</text>')


# --- board, area, pedals ------------------------------------------------------------------------
def board(box):
    return rect(*box, fill="#eceff1", stroke="#90a4ae", stroke_width=1, class_="board")


def holes(rects):
    """The board's holes (slots / cutouts in the deck), a darker fill so the board outline stays readable; one group, so
    rectangles that touch do not show seams. Nothing without holes."""
    if not rects:
        return []
    return ['<g class="holes" opacity="0.3">'] + [rect(*r, fill="#90a4ae", class_="hole") for r in rects] + ["</g>"]


EDGE_COLOUR = "#7e57c2"
EDGE_KEY = "edge crossing: cables may go round the board edge here"


def edge_segments(segments):
    """The owner's edge segments (board.json, type "edge": where cables may go round the board edge, canvas ((x0, y0), (x1, y1),
    side)) as a thick translucent purple line on the board border. Nothing without segments."""
    return [f'<line x1="{f1(a[0])}" y1="{f1(a[1])}" x2="{f1(b[0])}" y2="{f1(b[1])}" stroke="{EDGE_COLOUR}" stroke-opacity="0.6" '
            f'stroke-width="2.4" stroke-linecap="butt" class="edge-segment"/>' for a, b, _ in segments or []]


def routing_area(x0, y0, x1, y1):
    return rect(x0, y0, x1, y1, fill="none", stroke=GREY, stroke_dasharray="4 3", stroke_width=0.8, class_="routing-area")


def wrap(s, width_chars):
    lines, cur = [], ""
    for word in s.split():
        if cur and len(cur) + 1 + len(word) > width_chars:
            lines.append(cur)
            cur = word
        else:
            cur = f"{cur} {word}".strip()
    return lines + ([cur] if cur else [])


def fit_label(s, w, h, fs_max=4.5, fs_min=2.5):
    """(font size, lines): the largest font that fits `s` wrapped into the w x h box; at the smallest font the
    lines are cut with an ellipsis (and the surplus lines dropped)."""
    fs = fs_max
    while fs > fs_min - 1e-9:
        lines = wrap(s, max(1, int(w / (CHAR * fs))))
        if len(lines) * fs * 1.2 <= h and all(len(x) * CHAR * fs <= w for x in lines):
            return fs, lines
        fs -= 0.25
    cols = max(1, int(w / (CHAR * fs_min)))
    lines = wrap(s, cols)[:max(1, int(h / (fs_min * 1.2)))]
    return fs_min, [x if len(x) <= cols else x[:max(cols - 1, 1)] + "…" for x in lines]


def union_outline(rects, eps=1e-6):
    """Closed boundary loops [[(x, y), ...]] of the union of axis-aligned rectangles (x0, y0, x1, y1), collinear
    points merged. Outer loops run clockwise on screen (y down), holes the other way. Coordinates closer than `eps`
    count as equal; rectangles that only touch at a corner give separate loops."""
    rects = [r for r in rects if r[2] - r[0] > eps and r[3] - r[1] > eps]

    def axis(vals):   # sorted distinct values, near-equal ones snapped together
        out = []
        for v in sorted(vals):
            if not out or v - out[-1] > eps:
                out.append(v)
        return out

    xs, ys = axis(v for r in rects for v in (r[0], r[2])), axis(v for r in rects for v in (r[1], r[3]))

    def idx(vs, v):
        return min(range(len(vs)), key=lambda k: abs(vs[k] - v))
    covered = set()
    for r in rects:
        covered |= {(i, j) for i in range(idx(xs, r[0]), idx(xs, r[2])) for j in range(idx(ys, r[1]), idx(ys, r[3]))}
    edges = {}   # start point (grid indices) -> [end points]: clockwise around every covered cell, kept where the neighbour is empty
    for i, j in covered:
        for (di, dj), a, b in (((0, -1), (i, j), (i + 1, j)), ((1, 0), (i + 1, j), (i + 1, j + 1)),
                               ((0, 1), (i + 1, j + 1), (i, j + 1)), ((-1, 0), (i, j + 1), (i, j))):
            if (i + di, j + dj) not in covered:
                edges.setdefault(a, []).append(b)
    loops = []
    while edges:
        start = min(edges)
        pts, cur = [start], start
        heading = None
        while True:
            # at a vertex where two cells only touch by a corner (two ways out) take the right turn (screen, y down),
            # i.e. stay on the cell just walked along: corner-touching cells give separate loops
            outs = edges[cur]
            if heading and len(outs) > 1:
                turn = lambda q: (0 if (q[0] - cur[0], q[1] - cur[1]) == (-heading[1], heading[0]) else
                                  1 if (q[0] - cur[0], q[1] - cur[1]) == heading else 2)
                outs.sort(key=turn, reverse=True)
            nxt = outs.pop()
            heading = (nxt[0] - cur[0], nxt[1] - cur[1])
            if not edges[cur]:
                del edges[cur]
            if nxt == start:
                break
            pts.append(nxt)
            cur = nxt
        keep = [p for k, p in enumerate(pts)
                if not ((pts[k - 1][0] == p[0] == pts[(k + 1) % len(pts)][0]) or (pts[k - 1][1] == p[1] == pts[(k + 1) % len(pts)][1]))]
        loops.append([(xs[i], ys[j]) for i, j in keep])
    return loops


def pedal(item, name, image=None, shapes=None):
    """A pedal: its outline (`shapes`: canvas rectangles, default the box) as one path, Pedal Playground's box as a
    faint dashed rectangle, the image over the outline when given (a data URI), the name centred in it."""
    cx, cy = design.centre(item)
    x0, y0, x1, y1 = design.footprint(item)
    rot = f"rotate({item['rot']:g} {cx:.2f} {cy:.2f})"
    shapes = shapes or [design.footprint(item)]
    out = [f'<g class="pedal" data-id="{esc(item.get("id", ""))}">',
           f'<rect x="{f1(item["left_mm"])}" y="{f1(item["top_mm"])}" width="{f1(item["w_mm"])}" height="{f1(item["h_mm"])}" '
           f'transform="{rot}" fill="none" stroke="#455a64" stroke-width="0.3" stroke-dasharray="2 1.5" opacity="0.45" class="pedal-box"/>']
    # the outline: ONE path along the union boundary of its rectangles (no seams between touching ones)
    d = " ".join("M" + " L".join(f"{f1(x)} {f1(y)}" for x, y in loop) + " Z" for loop in union_outline(shapes))
    out.append(f'<path d="{d}" fill="{"none" if image else "#cfd8dc"}" stroke="#455a64" stroke-width="0.6" '
               f'stroke-linejoin="round" class="pedal-outline"/>')
    if image:
        out.append(f'<image x="{f1(item["left_mm"])}" y="{f1(item["top_mm"])}" width="{f1(item["w_mm"])}" '
                   f'height="{f1(item["h_mm"])}" preserveAspectRatio="none" transform="{rot}" href="{image}" xlink:href="{image}"/>')
    fs, lines = fit_label(name, x1 - x0 - 4, y1 - y0 - 4, fs_max=min(4.5, max(2.5, min(x1 - x0, y1 - y0) / 12)))
    y = cy - (len(lines) - 1) * fs * 1.2 / 2 + fs * 0.35
    out += [text(cx, y + n * fs * 1.2, ln, fs, "middle", halo=bool(image), class_="pedal-name") for n, ln in enumerate(lines)]
    out.append("</g>")
    return "\n".join(out)


def jack_geometry(item, jk):
    """(point, facing) of a jack on the canvas, after the item's rotation."""
    return design.jack_point(item, jk["x"], jk["y"]), design.jack_facing(item, jk["facing"])


def jacks(item, jack_list, used):
    """A small symbol at each jack: coloured by function, filled when used, hollow when not; a tick shows the
    side the plug enters from. `used` = set of jack ids of this pedal."""
    out = []
    for jk in jack_list:
        (x, y), facing = jack_geometry(item, jk)
        dx, dy = design.FACING[facing]
        col, on = JACK_COLOURS.get(jk.get("function"), JACK_COLOURS["other"]), jk["id"] in used
        out.append(f'<g class="jack" data-jack="{esc(jk["id"])}" data-used="{int(on)}">'
                   f'<line x1="{f1(x)}" y1="{f1(y)}" x2="{f1(x + dx * 3.4)}" y2="{f1(y + dy * 3.4)}" stroke="{col}" stroke-width="0.7"/>'
                   f'<circle cx="{f1(x)}" cy="{f1(y)}" r="1.4" fill="{col if on else "#ffffff"}" stroke="{col}" stroke-width="0.6"/></g>')
    return out


def down_marker(x, y, class_="plug-down"):
    """The mark of a plug that points down into a hole (at its bend point): a small filled circle with a cross."""
    return (f'<g class="{class_}"><circle cx="{f1(x)}" cy="{f1(y)}" r="1.9" fill="#37474f" fill-opacity="0.85" stroke="#ffffff" '
            f'stroke-width="0.4"/><path d="M{f1(x - 1.0)} {f1(y - 1.0)} L{f1(x + 1.0)} {f1(y + 1.0)} M{f1(x - 1.0)} {f1(y + 1.0)} '
            f'L{f1(x + 1.0)} {f1(y - 1.0)}" stroke="#ffffff" stroke-width="0.5" fill="none"/></g>')


def plug_heads(heads):
    out = [rect(*r, fill="#90a4ae", opacity=0.45, stroke="#37474f", stroke_width=0.3, class_="plug-head")
           for h in heads or [] for _, r in h["rects"]]
    return out + [down_marker(*h["down"]) for h in heads or [] if h.get("down")]


def overflow_cells(grid, cells):
    return [rect(*grid.rect(c), fill="#ff1744", opacity=0.35, class_="overflow") for c in cells or []]


def footswitches(points, pairs):
    out = []
    for pr in (x for x in pairs or [] if x.get("too_close")):
        (ax, ay), (bx, by) = pr["points"]
        out.append(f'<line x1="{f1(ax)}" y1="{f1(ay)}" x2="{f1(bx)}" y2="{f1(by)}" stroke="#d50000" stroke-width="1.2" '
                   f'stroke-dasharray="3 2" class="too-close"/>')
    for fp in points or []:
        fill, stroke = FOOTSWITCH_STYLE.get(fp["type"], ("#ffffff", "#263238"))
        out.append(f'<circle cx="{f1(fp["x"])}" cy="{f1(fp["y"])}" r="3.5" fill="{fill}" stroke="{stroke}" stroke-width="0.8" '
                   f'class="footswitch" data-type="{esc(fp["type"])}"/>')
        if fp.get("topper"):
            out.append(f'<circle cx="{f1(fp["x"])}" cy="{f1(fp["y"])}" r="5.6" fill="none" stroke="#263238" stroke-width="1" '
                       f'class="topper"/>')
        elif fp.get("suggested"):
            out.append(f'<circle cx="{f1(fp["x"])}" cy="{f1(fp["y"])}" r="5.6" fill="none" stroke="#e65100" stroke-width="1" '
                       f'stroke-dasharray="2 1.5" class="topper-suggested"/>')
    return out


# --- cables -------------------------------------------------------------------------------------
def signal_cables(cable_list):
    return [c for c in cable_list or [] if c.get("kind") == "signal"]


def cable_colours(cable_list):
    """{cable id: colour}: one palette colour per signal cable, in order (the drawing and the legend agree)."""
    return {c["id"]: PALETTE[n % len(PALETTE)] for n, c in enumerate(signal_cables(cable_list))}


def points(path):
    return " ".join(f"{x:.1f},{y:.1f}" for x, y in path)


def label_point(path):
    """The middle of the longest segment of the path."""
    a, b = max(zip(path, path[1:]), key=lambda s: (s[0][0] - s[1][0]) ** 2 + (s[0][1] - s[1][1]) ** 2)
    return (a[0] + b[0]) / 2, (a[1] + b[1]) / 2


def cable_path(c, ends=None):
    """(polyline points, unroutable?) of a signal cable: its draw path, else the straight line between its jacks."""
    path = c.get("draw_path") or c.get("path")
    if path and len(path) > 1:
        return path, False
    return ((ends or {}).get(c["id"]) or None), True


def cables(cable_list, colours, diameter=3.5, ends=None):
    """Cable shapes. Per routed cable: a red halo when over the stacking/plug limit, a dark casing, the colour
    line (dashed when squeezed through a too narrow gap), white dashes where cables are stacked. An unroutable
    cable is a dotted grey line between its jacks (`ends` = {cable id: [point a, point b]})."""
    out = []
    for c in signal_cables(cable_list):
        path, missing = cable_path(c, ends)
        if not path:
            continue
        pts, st = points(path), c.get("status") or ""
        if missing:
            out.append(f'<polyline points="{pts}" fill="none" stroke="#757575" stroke-width="1" stroke-dasharray="0.1 2.2" '
                       f'stroke-linecap="round" class="cable-missing" data-id="{c["id"]}"/>')
            continue
        join = 'fill="none" stroke-linejoin="round" stroke-linecap="round"'
        parts = c.get("stretches") if any(x["layer"] == "under" for x in c.get("stretches") or []) else None
        for stretch in parts or [{"layer": "top", "points": path}]:
            pts = points(stretch["points"])
            if stretch["layer"] == "under":   # under the board: lighter, dashed, no casing
                out.append(f'<polyline points="{pts}" {join} stroke="{colours[c["id"]]}" stroke-opacity="0.55" '
                           f'stroke-width="{max(diameter - 0.9, 0.8):g}" stroke-dasharray="4 2.4" class="cable-under" data-id="{c["id"]}"/>')
                continue
            if "over the" in st:
                out.append(f'<polyline points="{pts}" {join} stroke="#ff1744" stroke-opacity="0.55" stroke-width="{diameter + 2.4:g}" class="halo"/>')
            out.append(f'<polyline points="{pts}" {join} stroke="{CASING}" stroke-width="{diameter:g}" class="casing"/>')
            dash = ' stroke-dasharray="3 1.6"' if "squeezed" in st else ""
            out.append(f'<polyline points="{pts}" {join} stroke="{colours[c["id"]]}" stroke-width="{max(diameter - 0.9, 0.8):g}"{dash} '
                       f'class="cable" data-id="{c["id"]}"/>')
        for x, y in c.get("hole_points") or []:   # where the cable passes through the deck
            out.append(f'<circle cx="{f1(x)}" cy="{f1(y)}" r="{diameter * 0.9:.1f}" fill="#ffffff" fill-opacity="0.6" stroke="{CASING}" '
                       f'stroke-width="0.6" class="hole-pass" data-id="{c["id"]}"/>')
        for x, y in c.get("edge_points") or []:   # where the cable goes round the board edge
            out.append(rect(x - diameter * 0.9, y - diameter * 0.9, x + diameter * 0.9, y + diameter * 0.9, fill="#ffffff", fill_opacity=0.6,
                            stroke=CASING, stroke_width=0.6, class_="edge-pass", data_id=c["id"]))
        for run in c.get("stacked_runs") or ([] if not c.get("stacked_with") else [path]):   # only where it is stacked
            out.append(f'<polyline points="{points(run)}" {join} stroke="#ffffff" stroke-width="0.6" stroke-dasharray="2.4 2.4" '
                       f'class="stacked"/>')
    return out


def power_cable_list(cable_list):
    return [c for c in cable_list or [] if c.get("kind") == "power" and c.get("stretches")]


def power_cables(cable_list):
    """Routed DC power cables: a thin brown line on top of the board, light and dashed under it, a small ring where the
    cable passes through a hole and a small square where it goes over a board edge."""
    out = []
    for c in power_cable_list(cable_list):
        join = 'fill="none" stroke-linejoin="round" stroke-linecap="round"'
        for st in c["stretches"]:
            if st["layer"] == "under":
                out.append(f'<polyline points="{points(st["points"])}" {join} stroke="{POWER_COLOUR}" stroke-opacity="0.55" '
                           f'stroke-width="{POWER_WIDTH:g}" stroke-dasharray="3 2" class="power-under" data-id="{c["id"]}"/>')
            else:
                out.append(f'<polyline points="{points(st["points"])}" {join} stroke="{POWER_COLOUR}" stroke-width="{POWER_WIDTH:g}" '
                           f'class="power-cable" data-id="{c["id"]}"/>')
        for x, y in c.get("hole_points") or []:
            out.append(f'<circle cx="{f1(x)}" cy="{f1(y)}" r="2.0" fill="#ffffff" fill-opacity="0.6" stroke="{POWER_COLOUR}" '
                       f'stroke-width="0.5" class="power-hole" data-id="{c["id"]}"/>')
        for x, y in c.get("edge_points") or []:
            out.append(rect(x - 1.8, y - 1.8, x + 1.8, y + 1.8, fill="#ffffff", fill_opacity=0.6, stroke=POWER_COLOUR, stroke_width=0.5,
                            class_="power-edge", data_id=c["id"]))
    return out


def power_labels(cable_list):
    """The leg's id (P# for a one-leg cable, P#.n for a leg of a daisy chain) next to the pedal end of each routed power leg."""
    out = []
    for c in power_cable_list(cable_list):
        x, y = c.get("end_point") or c["draw_path"][-1]
        out.append(text(x + 1.5, y - 1.5, c["id"], 2.6, "start", POWER_COLOUR, True, font_weight="bold",
                        class_="power-label"))
    return out


def cable_labels(cable_list, colours, ends=None):
    out = []
    for c in signal_cables(cable_list):
        path, _ = cable_path(c, ends)
        if path:
            x, y = label_point(path)
            out.append(text(x, y + 1.05, c["id"], 3.0, "middle", colours[c["id"]], True, font_weight="bold", class_="cable-label"))
    return out


# --- legend -------------------------------------------------------------------------------------
def short_status(status):
    """'routed' -> '', 'routed, squeezed (gap ...)' -> 'squeezed', 'unroutable: ...' -> 'unroutable'."""
    s = (status or "").replace("routed, ", "", 1) if (status or "").startswith("routed, ") else (status or "")
    return "" if s == "routed" else s.replace(":", "(").split("(")[0].strip()


def swatch(x, y, colour, w=7.0, d=2.4):
    return (f'<line x1="{f1(x)}" y1="{f1(y)}" x2="{f1(x + w)}" y2="{f1(y)}" stroke="{CASING}" stroke-width="{d:g}" stroke-linecap="round"/>'
            f'<line x1="{f1(x)}" y1="{f1(y)}" x2="{f1(x + w)}" y2="{f1(y)}" stroke="{colour}" stroke-width="{d - 0.8:g}" stroke-linecap="round"/>')


def legend_table(rows, x, y, width):
    """One row per signal cable: swatch, S#, from -> to, min length, short status. `rows` = dicts with id, colour,
    route (text), length (text), status (text). Rows flow into as many columns as fit `width`.
    Returns (lines, height)."""
    if not rows:
        return [], 0.0
    w_id = 8.0
    w_route = max(len(r["route"]) for r in rows) * CHAR * FONT + 3
    w_len = max(len(r["length"]) for r in rows) * CHAR * FONT + 3
    w_st = max(len(r["status"]) for r in rows) * CHAR * FONT
    cw = 9.0 + w_id + w_route + w_len + w_st + 8
    ncols = max(1, min(len(rows), int(width // cw)))
    per = -(-len(rows) // ncols)
    out = []
    for n, r in enumerate(rows):
        cx, cy = x + (n // per) * cw, y + (n % per) * ROW + ROW / 2
        out.append(f'<g class="legend-row" data-id="{esc(r["id"])}">{swatch(cx, cy, r["colour"])}'
                   + text(cx + 9, cy + FONT * 0.35, r["id"], FONT, fill=r["colour"], font_weight="bold")
                   + text(cx + 9 + w_id, cy + FONT * 0.35, r["route"])
                   + text(cx + 9 + w_id + w_route + w_len, cy + FONT * 0.35, r["length"], anchor="end", class_="length")
                   + text(cx + 9 + w_id + w_route + w_len + 2, cy + FONT * 0.35, r["status"], fill=r.get("status_fill", "#b71c1c"))
                   + "</g>")
    return out, per * ROW


def key_entries(ctx, cable_list, max_stack):
    """(sample kind, text) for the key line: the symbols this picture uses."""
    r = ctx.get("routing") or {}
    layout_holes = (ctx.get("layout") or {}).get("holes")
    st = [c.get("status") or "" for c in signal_cables(cable_list)]
    e = [("jack_used", "used jack (colour: input blue, output green, power orange, other purple)"),
         ("jack_free", "unused jack (the tick points to the side the plug enters from)"),
         ("head", "plug head and its cable exit"), ("area", "routing area"),
         ("box", "dashed: Pedal Playground box")]
    if any(h.get("down") for h in r.get("heads") or []):
        e.insert(3, ("down", "plug points down into a hole"))
    if layout_holes:
        e.append(("hole", "Board hole"))
    if (ctx.get("layout") or {}).get("edge_segments"):
        e.append(("edge", EDGE_KEY))
    if any(c.get("under_board") for c in signal_cables(cable_list)):
        e += [("under", "dashed light: cable under the board")]
        if any(c.get("holes_used") for c in signal_cables(cable_list)):
            e.append(("pass", "ring: pass through a hole"))
        if any(c.get("edges_used") for c in signal_cables(cable_list)):
            e.append(("pass_edge", "square: pass over the board edge"))
    if any("squeezed" in s for s in st):
        e.append(("squeezed", "dashed: squeezed through a gap narrower than the cable"))
    power = power_cable_list(cable_list)
    if power:
        e.append(("power", "brown: DC power cable (P#, or P#.n for the legs of a daisy chain: one label per leg), thinner than the patch cables"))
        if any(any(x["layer"] == "under" for x in c["stretches"]) for c in power):
            e.append(("power_under", "dashed light brown: power cable under the board"))
        if any(c.get("hole_points") for c in power):
            e.append(("power_hole", "ring: power cable through a hole"))
        if any(c.get("edge_points") for c in power):
            e.append(("power_edge", "square: power cable over the board edge"))
    if any(c.get("stacked_with") for c in signal_cables(cable_list)):
        e.append(("stacked", "white dashes: cables stacked on top of each other"))
    if any("over the" in s for s in st):
        e.append(("over", f"red halo: over the stacking limit ({max_stack}) or the plug limit"))
    if r.get("overflow"):
        e.append(("overflow", f"red area: more than {max_stack} stacked cables"))
    if any(c.get("path") is None for c in signal_cables(cable_list)):
        e.append(("missing", "dotted grey: not routed"))
    for t, (fill, stroke) in FOOTSWITCH_STYLE.items():
        if any(p["type"] == t for p in ctx.get("footswitch_points") or []):
            e.append((f"fs:{t}", f"{t} footswitch"))
    if any(p.get("topper") for p in ctx.get("footswitch_points") or []):
        e.append(("topper", "solid ring: topper on the footswitch"))
    if any(p.get("suggested") for p in ctx.get("footswitch_points") or []):
        e.append(("topper_suggested", "dashed orange ring: suggested topper"))
    if any(p.get("too_close") for p in ctx.get("footswitch_pairs") or []):
        e.append(("close", "footswitches closer than the minimum"))
    return e


def key_sample(kind, x, y):
    """Sample symbol of `kind` centred on (x + 4, y); returns svg."""
    cx = x + 4
    if kind in ("jack_used", "jack_free"):
        col = JACK_COLOURS["input"]
        return (f'<line x1="{f1(cx - 2.5)}" y1="{f1(y)}" x2="{f1(cx + 1)}" y2="{f1(y)}" stroke="{col}" stroke-width="0.7"/>'
                f'<circle cx="{f1(cx)}" cy="{f1(y)}" r="1.4" fill="{col if kind == "jack_used" else "#ffffff"}" stroke="{col}" stroke-width="0.6"/>')
    if kind == "head":
        return rect(x, y - 2, x + 8, y + 2, fill="#90a4ae", opacity=0.45, stroke="#37474f", stroke_width=0.3)
    if kind == "down":
        return down_marker(cx, y, "key-down")
    if kind == "area":
        return rect(x, y - 2, x + 8, y + 2, fill="none", stroke=GREY, stroke_dasharray="4 3", stroke_width=0.8)
    if kind == "box":
        return rect(x, y - 2, x + 8, y + 2, fill="none", stroke="#455a64", stroke_width=0.3, stroke_dasharray="2 1.5", opacity=0.45)
    if kind == "hole":
        return rect(x, y - 2, x + 8, y + 2, fill="#90a4ae", opacity=0.3)
    if kind == "edge":
        return f'<line x1="{f1(x)}" y1="{f1(y)}" x2="{f1(x + 8)}" y2="{f1(y)}" stroke="{EDGE_COLOUR}" stroke-opacity="0.6" stroke-width="2.4"/>'
    if kind == "supply":
        return rect(x, y - 2, x + 8, y + 2, fill=SUPPLY_COLOUR, fill_opacity=0.22, stroke=SUPPLY_COLOUR, stroke_width=0.6,
                    stroke_dasharray="3 1.5")
    if kind == "overflow":
        return rect(x, y - 2, x + 8, y + 2, fill="#ff1744", opacity=0.35)
    if kind.startswith("fs:"):
        fill, stroke = FOOTSWITCH_STYLE[kind[3:]]
        return f'<circle cx="{f1(cx)}" cy="{f1(y)}" r="2.2" fill="{fill}" stroke="{stroke}" stroke-width="0.6"/>'
    if kind == "topper":
        return f'<circle cx="{f1(cx)}" cy="{f1(y)}" r="3.2" fill="none" stroke="#263238" stroke-width="0.8"/>'
    if kind == "topper_suggested":
        return (f'<circle cx="{f1(cx)}" cy="{f1(y)}" r="3.2" fill="none" stroke="#e65100" stroke-width="0.8" '
                f'stroke-dasharray="1.6 1.2"/>')
    if kind == "close":
        return f'<line x1="{f1(x)}" y1="{f1(y)}" x2="{f1(x + 8)}" y2="{f1(y)}" stroke="#d50000" stroke-width="1.2" stroke-dasharray="3 2"/>'
    if kind == "missing":
        return f'<line x1="{f1(x)}" y1="{f1(y)}" x2="{f1(x + 8)}" y2="{f1(y)}" stroke="#757575" stroke-width="1" stroke-dasharray="0.1 2.2" stroke-linecap="round"/>'
    line = f'x1="{f1(x)}" y1="{f1(y)}" x2="{f1(x + 8)}" y2="{f1(y)}" stroke-linecap="round"'
    base = swatch(x, y, "#78909c", 8.0).replace('stroke-linecap="round"', 'stroke-linecap="butt"')
    if kind == "squeezed":
        return (f'<line {line} stroke="{CASING}" stroke-width="2.4"/><line {line} stroke="#78909c" stroke-width="1.6" stroke-dasharray="2 1.2"/>')
    if kind == "under":
        return f'<line {line} stroke="#78909c" stroke-opacity="0.55" stroke-width="1.6" stroke-dasharray="4 2.4"/>'
    if kind == "power":
        return f'<line {line} stroke="{POWER_COLOUR}" stroke-width="{POWER_WIDTH:g}"/>'
    if kind == "power_under":
        return f'<line {line} stroke="{POWER_COLOUR}" stroke-opacity="0.55" stroke-width="{POWER_WIDTH:g}" stroke-dasharray="3 2"/>'
    if kind == "power_hole":
        return f'<circle cx="{f1(cx)}" cy="{f1(y)}" r="2.0" fill="#ffffff" fill-opacity="0.6" stroke="{POWER_COLOUR}" stroke-width="0.5"/>'
    if kind == "power_edge":
        return rect(cx - 1.8, y - 1.8, cx + 1.8, y + 1.8, fill="#ffffff", fill_opacity=0.6, stroke=POWER_COLOUR, stroke_width=0.5)
    if kind == "pass":
        return f'<circle cx="{f1(cx)}" cy="{f1(y)}" r="2.2" fill="#ffffff" fill-opacity="0.6" stroke="{CASING}" stroke-width="0.6"/>'
    if kind == "pass_edge":
        return rect(cx - 2.0, y - 2.0, cx + 2.0, y + 2.0, fill="#ffffff", fill_opacity=0.6, stroke=CASING, stroke_width=0.6)
    if kind == "stacked":
        return base + f'<line {line} stroke="#ffffff" stroke-width="0.6" stroke-dasharray="1.6 1.6"/>'
    if kind == "over":
        return f'<line {line} stroke="#ff1744" stroke-opacity="0.55" stroke-width="4.8"/>' + base
    return ""


def key_block(entries, x, y, width, extra=None):
    """The key: the samples flow left to right over several lines. Returns (lines, height)."""
    out, cx, cy = [], x, y + ROW / 2
    for kind, label in entries:
        w = 10 + len(label) * CHAR * FONT + 6
        if cx > x and cx + w > x + width:
            cx, cy = x, cy + ROW
        out.append(key_sample(kind, cx, cy) + text(cx + 10, cy + FONT * 0.35, label))
        cx += w
    cy += ROW
    if extra:
        out.append(text(x, cy + FONT * 0.35, extra))
        cy += ROW
    return out, cy - y


def document(view_box, body):
    """The svg document, sized in mm like its viewBox (a browser prints it at true scale)."""
    x0, y0, w, h = view_box
    return (f'<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" viewBox="{x0:.1f} {y0:.1f} {w:.1f} {h:.1f}" width="{w:.1f}mm" '
            f'height="{h:.1f}mm" font-family="sans-serif">\n' + rect(x0, y0, x0 + w, y0 + h, fill="#ffffff") + "\n"
            + "\n".join(body) + "\n</svg>\n")


# --- the whole picture --------------------------------------------------------------------------
def image_uri(path):
    """A PNG data URI of the image file, downscaled to IMAGE_PX on the long side; None if it cannot be read."""
    from PIL import Image
    try:
        with Image.open(path) as im:
            im = im.convert("RGBA")
            im.thumbnail((IMAGE_PX, IMAGE_PX))
            buf = io.BytesIO()
            im.save(buf, "PNG", optimize=True)
    except OSError:
        return None
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()


def used_jacks(ctx, cid):
    """Ids of the jacks of pedal `cid` the project uses: the default input, output and power jack, and extra_used."""
    have = ((ctx.get("layout") or {}).get("jacks") or {}).get(cid) or []
    ids = {(default_jack(have, fn) or {}).get("id") for fn in ("input", "output", "power")}
    ids |= set((((ctx.get("project") or {}).get("jacks") or {}).get("extra_used") or {}).get(cid, []))
    return {i for i in ids if i}


def jack_ends(layout, cable_list):
    """{cable id: [point a, point b]}: the jack positions of the signal cables (for the unroutable ones)."""
    def where(key):
        cid, _, jid = key.partition(".")
        it = layout["placed"].get(cid)
        jk = next((j for j in (layout.get("jacks") or {}).get(cid, []) if j["id"] == jid), None)
        return jack_geometry(it, jk)[0] if it and jk else None
    out = {}
    for c in signal_cables(cable_list):
        a, b = where(c["from"]), where(c["to"])
        if a and b:
            out[c["id"]] = [a, b]
    return out


def render(ctx, names, overlay=None, legend=None, images=None):
    """The picture of the board, pedals, jacks, plug heads, signal cables and footswitches with its legend (an SVG
    string, or None without a routing grid / layout). `overlay`: extra SVG elements drawn on top, `legend`: an extra
    sentence under the key, `images`: {catalog id: PNG path} drawn under each placed pedal's outline."""
    r = ctx.get("routing") or {}
    grid, layout = r.get("grid"), ctx.get("layout")
    if not grid or not layout:
        return None
    cfg = r.get("settings") or {}
    diameter, max_stack = cfg.get("diameter_mm", 3.5), cfg.get("max_stack", 2)
    bx = design.footprint(layout["board"])
    ax0, ay0, ax1 = grid.x0, grid.y0, grid.x0 + grid.nx * grid.cell
    left, right = min(bx[0], ax0) - PAD, max(bx[2], ax1) + PAD
    top = ay0 - PAD
    placed = layout["placed"]
    cid_of = {it["id"]: cid for cid, it in placed.items()}
    uris = {}
    for cid, path in (images or {}).items():
        uris[cid] = image_uri(path)
    cable_list = ctx.get("cable_list") or []
    colours, ends = cable_colours(cable_list), jack_ends(layout, cable_list)

    body = [board(bx)] + holes(layout.get("holes")) + edge_segments(layout.get("edge_segments")) + [routing_area(ax0, ay0, ax1, r.get("front_y") or bx[3])]
    for o in layout["obstacles"]:
        cid = cid_of.get(o["id"])
        body.append(pedal(o, names.get(cid, cid) if cid else o.get("title", ""), uris.get(cid), (layout.get("shapes") or {}).get(o["id"])))
    body += overflow_cells(grid, r.get("overflow"))
    body += plug_heads(r.get("heads"))
    body += cables(cable_list, colours, diameter, ends)
    body += power_cables(cable_list)
    jd = layout.get("jacks") or {}
    for cid, it in placed.items():
        body += jacks(it, jd.get(cid) or [], used_jacks(ctx, cid))
    body += footswitches(ctx.get("footswitch_points"), ctx.get("footswitch_pairs"))
    body += list(overlay or [])
    body += cable_labels(cable_list, colours, ends)
    body += power_labels(cable_list)

    width, y = right - left, bx[3] + 8
    key, kh = key_block(key_entries(ctx, cable_list, max_stack), left + PAD, y, width - 2 * PAD, legend)
    body += key
    y += kh + 3
    rows = [{"id": c["id"], "colour": colours[c["id"]], "length": "-" if c.get("min_mm") is None else f"{c['min_mm']:.0f} mm",
             "route": " -> ".join(_end_name(c[k], names) for k in ("from", "to")), "status": short_status(c.get("status"))}
            for c in signal_cables(cable_list)]
    table, th = legend_table(rows, left + PAD, y, width - 2 * PAD)
    body += table
    height = y + th + PAD - top
    return document((left, top, width, height), body)


SUPPLY_COLOUR = "#e53935"   # power.svg: supply silhouettes, translucent so the board, holes and cables show through


def supply(item, label, shapes=None, on_board=False):
    """A power supply's silhouette (its outline, default the box) in translucent red, its label centred: under the
    board it is drawn dashed (it hangs below the deck), on the board solid."""
    cx, cy = design.centre(item)
    x0, y0, x1, y1 = design.footprint(item)
    d = " ".join("M" + " L".join(f"{f1(x)} {f1(y)}" for x, y in loop) + " Z"
                 for loop in union_outline(shapes or [design.footprint(item)]))
    dash = "" if on_board else ' stroke-dasharray="3 1.5"'
    fs, lines = fit_label(label, x1 - x0 - 4, y1 - y0 - 4)
    y = cy - (len(lines) - 1) * fs * 1.2 / 2 + fs * 0.35
    return "\n".join([f'<g class="supply" data-id="{esc(item.get("id", ""))}">',
                      f'<path d="{d}" fill="{SUPPLY_COLOUR}" fill-opacity="0.22" stroke="{SUPPLY_COLOUR}" stroke-width="0.6"{dash} '
                      f'stroke-linejoin="round" class="supply-outline"/>']
                     + [text(cx, y + n * fs * 1.2, ln, fs, "middle", "#b71c1c", True, class_="supply-name") for n, ln in enumerate(lines)]
                     + ["</g>"])


def render_power(ctx, names):
    """power.svg: the power wiring alone. The board and its holes, the pedals as faint outlines, every power supply as a
    translucent red silhouette (dashed when it hangs under the board), the power jacks and supply ports, the DC plug
    heads, the routed power cables (under the board dashed, hole / edge passes marked) and a table of the power cables.
    None without a routing grid / layout or without routed power cables."""
    r = ctx.get("routing") or {}
    grid, layout = r.get("grid"), ctx.get("layout")
    cable_list = ctx.get("cable_list") or []
    power = power_cable_list(cable_list)
    if not grid or not layout or not power:
        return None
    bx = design.footprint(layout["board"])
    ax0, ay0, ax1 = grid.x0, grid.y0, grid.x0 + grid.nx * grid.cell
    left, right, top = min(bx[0], ax0) - PAD, max(bx[2], ax1) + PAD, ay0 - PAD
    shapes = layout.get("shapes") or {}
    placed, inst_item = layout["placed"], layout.get("inst_item") or {}
    supply_ids = {it["id"] for it in inst_item.values()}
    cid_of = {it["id"]: cid for cid, it in placed.items()}
    labels = {s["inst"]["id"]: s["inst"].get("label") or s["inst"]["id"] for s in ctx.get("supplies") or []}
    placement = layout.get("inst_placement") or {}

    body = [board(bx)] + holes(layout.get("holes")) + edge_segments(layout.get("edge_segments"))
    body.append('<g class="pedals-faint" opacity="0.45">')
    for o in layout["obstacles"]:
        if o["id"] not in supply_ids:
            cid = cid_of.get(o["id"])
            body.append(pedal(o, names.get(cid, cid) if cid else o.get("title", ""), None, shapes.get(o["id"])))
    body.append("</g>")
    for iid, it in inst_item.items():
        body.append(supply(it, labels.get(iid, iid), shapes.get(it["id"]), placement.get(iid) == "on_board"))
    power_ids = {c["id"] for c in power}
    body += plug_heads([h for h in r.get("heads") or [] if h.get("cable") in power_ids])
    body += power_cables(cable_list)
    jd = layout.get("jacks") or {}
    for cid, it in placed.items():
        body += jacks(it, [j for j in jd.get(cid) or [] if j.get("function") == "power"], used_jacks(ctx, cid))
    for s in ctx.get("supplies") or []:
        it = inst_item.get(s["inst"]["id"])
        if it:
            used = {row["port"] for row in s["rows"] if row["pedals"]}
            body += jacks(it, [j for j in jd.get(s["sup"]["id"]) or [] if j.get("function") == "power_out"], used)
    body += power_labels(cable_list)

    width, y = right - left, bx[3] + 8
    entries = [("supply", "power supply (dashed: under the board)"), ("jack_used", "used power jack / supply port"),
               ("head", "DC plug head")] + ([("down", "plug points down into a hole")] if any(h.get("down") for h in r.get("heads") or []) else []) \
              + ([("hole", "Board hole")] if layout.get("holes") else [])
    entries += [("edge", EDGE_KEY)] if layout.get("edge_segments") else []
    entries += [e for e in key_entries(ctx, cable_list, 2) if e[0].startswith("power")]
    key, kh = key_block(entries, left + PAD, y, width - 2 * PAD)
    body += key
    y += kh + 3

    by_id = {c["id"]: c for c in cable_list}
    all_names = {**names, **labels}

    def route(legs):
        holes, edges = sum(c.get("holes_used") or 0 for c in legs), sum(c.get("edges_used") or 0 for c in legs)
        parts = [f"{holes} hole{'s' if holes != 1 else ''}"] if holes else []
        parts += [f"{edges} edge{'s' if edges != 1 else ''}"] if edges else []
        return ", ".join(parts) or "on top"
    rows = []
    for cab in ctx.get("power_cable_summary") or []:
        legs = [by_id[i] for i in cab["legs"] if i in by_id]
        if not any(c.get("stretches") for c in legs):
            continue
        port_cid, _, port_jack = cab["from"].partition(".")
        pedals = [all_names.get(t.partition(".")[0], t.partition(".")[0]) for t in cab["to"]]
        part = sum(c["min_mm"] for c in legs if c.get("min_mm") is not None)   # the routed legs of a cable with unrouted ones
        gone = sum(1 for c in legs if c.get("min_mm") is None)
        rows.append({"id": cab["id"], "colour": POWER_COLOUR,
                     "length": (f"{cab['min_mm']:.0f} mm" if cab["min_mm"] is not None else
                                f">= {part:.0f} mm, {gone} leg{'s' if gone != 1 else ''} unrouted" if gone < len(legs) else "-"),
                     "route": f"{cab['style']}: " + " -> ".join([f"{all_names.get(port_cid, port_cid)} {port_jack}".strip(), *pedals]),
                     **({"status": route(legs), "status_fill": INK} if cab["status"].startswith("routed")
                        else {"status": short_status(cab["status"])})})
    table, th = legend_table(rows, left + PAD, y, width - 2 * PAD)
    body += table
    return document((left, top, width, y + th + PAD - top), body)


def _end_name(key, names):
    cid, _, jid = key.partition(".")
    return f"{names.get(cid, cid)} {jid}".strip()
