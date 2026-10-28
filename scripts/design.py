"""Read a Pedal Playground save file and do the jack geometry. Pure: no network, no GUI.

Pedal Playground files hold inches and pixels (`data-width`, `data-height` in inches,
`left`/`top` in px at `data-scale` px per inch). Everything here is converted to mm on
read; all geometry is in mm in the canvas frame (x right, y down).

A jack is stored as fractions (fx, fy) of the pedal image. The site stretches the image
over the pedal's Width x Height box and rotates only the artwork, clockwise, about the
centre of the unrotated box, so a jack's canvas position is:

    (x, y)   = (fx * w, fy * h)                  point inside the unrotated box
    (u, v)   = (x - w/2, y - h/2)                relative to the centre
    (u', v') = rotate (u, v) by 0/90/180/270     0:(u,v) 90:(-v,u) 180:(-u,-v) 270:(v,-u)
    canvas   = (left + w/2 + u', top + h/2 + v')
"""
import json
import math
import re
from html.parser import HTMLParser
from pathlib import Path

from common import IN_MM, px_to_mm

TOL_MM = 0.6  # about one design pixel (0.56 mm at 45 px/in): touching and rounding are not violations

FACING = {"left": (-1, 0), "right": (1, 0), "top": (0, -1), "down": (0, 1)}
FACING_NAME = {v: k for k, v in FACING.items()}


# --- parsing ----------------------------------------------------------------------------------
class _Items(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.items, self._cur, self._depth = [], None, 0

    def handle_starttag(self, tag, attrs):
        if tag != "div":
            return
        a = dict(attrs)
        classes = (a.get("class") or "").split()
        if self._cur is None and "item" in classes:
            style = a.get("style") or ""
            left = re.search(r"left:\s*(-?[\d.]+)px", style)
            top = re.search(r"top:\s*(-?[\d.]+)px", style)
            rot = next((int(m.group(1)) for c in classes if (m := re.fullmatch(r"rotate-(90|180|270)", c))), 0)
            self._cur = {
                "id": a.get("id"), "kind": "pedalboard" if "pedalboard" in classes else "pedal",
                "title": a.get("title"), "rot": rot, "scale": float(a.get("data-scale") or 45),
                "w_in": float(a.get("data-width") or 0), "h_in": float(a.get("data-height") or 0),
                "left_px": float(left.group(1)) if left else 0.0, "top_px": float(top.group(1)) if top else 0.0,
                "image": None,
            }
            self._depth = 1
        elif self._cur is not None:
            self._depth += 1
            if "artwork" in classes and not self._cur["image"]:
                m = re.search(r"url\(\s*[\"']?([^\"')]+)[\"']?\s*\)", a.get("style") or "")
                if m:
                    self._cur["image"] = m.group(1).rsplit("/", 1)[-1]

    def handle_endtag(self, tag):
        if tag == "div" and self._cur is not None:
            self._depth -= 1
            if self._depth == 0:
                self.items.append(self._cur)
                self._cur = None


def parse_canvas(canvas_html):
    """The `canvas` HTML string of a save file -> list of items in file order, sizes in mm."""
    p = _Items()
    p.feed(canvas_html)
    items = []
    for it in p.items:
        s = it["scale"]
        items.append({**it,
                      "w_mm": it["w_in"] * IN_MM, "h_mm": it["h_in"] * IN_MM,
                      "left_mm": px_to_mm(it["left_px"], s), "top_mm": px_to_mm(it["top_px"], s)})
    return items


def parse_design(path):
    """A Pedal Playground save file -> list of items (pedals, supplies, boards) with mm geometry."""
    return parse_canvas(json.loads(Path(path).read_text())["canvas"])


# --- geometry (mm) ----------------------------------------------------------------------------
def _rotate(u, v, rot):
    return {0: (u, v), 90: (-v, u), 180: (-u, -v), 270: (v, -u)}[rot]


def centre(item):
    return item["left_mm"] + item["w_mm"] / 2, item["top_mm"] + item["h_mm"] / 2


def footprint(item):
    """Axis-aligned (x0, y0, x1, y1) of the pedal on the canvas; w and h swap for 90/270."""
    cx, cy = centre(item)
    w, h = (item["h_mm"], item["w_mm"]) if item["rot"] in (90, 270) else (item["w_mm"], item["h_mm"])
    return (cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2)


def jack_point(item, fx, fy):
    """Canvas position (mm) of a jack at fractions (fx, fy) of the unrotated image."""
    cx, cy = centre(item)
    u, v = fx * item["w_mm"] - item["w_mm"] / 2, fy * item["h_mm"] - item["h_mm"] / 2
    u2, v2 = _rotate(u, v, item["rot"])
    return cx + u2, cy + v2


def outline_rects(item, outlines):
    """Canvas rectangles (x0, y0, x1, y1) of the item's outline (catalog/outlines.json, `outlines` = {image name:
    [[x0, y0, x1, y1] fractions of the unrotated image]}). Two opposite corners of each rectangle go through
    `jack_point`, so 0/90/180/270 are all right. Without an image or an outline: [footprint(item)]."""
    rects = (outlines or {}).get(item.get("image") or "")
    if not rects:
        return [footprint(item)]
    out = []
    for fx0, fy0, fx1, fy1 in rects:
        (xa, ya), (xb, yb) = jack_point(item, fx0, fy0), jack_point(item, fx1, fy1)
        out.append((min(xa, xb), min(ya, yb), max(xa, xb), max(ya, yb)))
    return out


def _rect_minus(r, cut):
    """Fraction rectangle `r` minus `cut`: up to four non-overlapping pieces (empty if `cut` covers all of it)."""
    x0, y0, x1, y1 = r
    cx0, cy0, cx1, cy1 = max(cut[0], x0), max(cut[1], y0), min(cut[2], x1), min(cut[3], y1)
    if cx0 >= cx1 or cy0 >= cy1:
        return [r]
    pieces = [(x0, y0, x1, cy0), (x0, cy1, x1, y1), (x0, cy0, cx0, cy1), (cx1, cy0, x1, cy1)]   # above, below, left, right
    return [p for p in pieces if p[2] - p[0] > 1e-9 and p[3] - p[1] > 1e-9]


def board_holes(board_item, holes, edits=None):
    """The effective holes of a board as canvas rectangles (x0, y0, x1, y1) in mm.

    `holes`: the derived holes of the board image (catalog/boards.json, rectangles in fractions of the unrotated
    image), `edits`: the project's boxes (boards.load_edits: {"type": "hole" | "filled", "x0".."y1"} in fractions of
    the image; "edge" segments are not holes and are ignored here, see `board_edges`), applied in order: "filled" subtracts
    its area from the holes so far, "hole" adds its area (a later box wins where boxes overlap). The result is a list of non-overlapping axis-aligned rectangles, mapped like
    `outline_rects` (0/90/180/270 all right); [] without a board or without holes."""
    if not board_item:
        return []
    rects = [tuple(r) for r in holes or []]
    for b in edits or []:
        if b["type"] == "edge":
            continue
        box = (b["x0"], b["y0"], b["x1"], b["y1"])
        rects = [piece for r in rects for piece in _rect_minus(r, box)]
        if b["type"] == "hole":
            rects.append(box)
    out = []
    for fx0, fy0, fx1, fy1 in rects:
        (xa, ya), (xb, yb) = jack_point(board_item, fx0, fy0), jack_point(board_item, fx1, fy1)
        out.append((min(xa, xb), min(ya, yb), max(xa, xb), max(ya, yb)))
    return out


def board_edges(board_item, edits=None):
    """The edge segments of a board (`edits` as in `board_holes`, only the type "edge": {"side", "from", "to"} along a side of the
    unrotated image) as canvas segments ((x0, y0), (x1, y1), side) in mm, x0 <= x1 and y0 <= y1; `side` is the canvas side of
    the board (left / right / back = top / front = bottom) the segment lies on after the rotation. [] without a board."""
    if not board_item:
        return []
    out = []
    for b in edits or []:
        if b["type"] != "edge":
            continue
        f, t = b["from"], b["to"]
        ends = {"left": ((0, f), (0, t)), "right": ((1, f), (1, t)), "back": ((f, 0), (t, 0)), "front": ((f, 1), (t, 1))}[b["side"]]
        (xa, ya), (xb, yb) = (jack_point(board_item, *q) for q in ends)
        x0, x1, y0, y1 = min(xa, xb), max(xa, xb), min(ya, yb), max(ya, yb)
        fx0, fy0, fx1, fy1 = footprint(board_item)
        mx, my = (x0 + x1) / 2, (y0 + y1) / 2
        side = min((abs(mx - fx0), "left"), (abs(mx - fx1), "right"), (abs(my - fy0), "back"), (abs(my - fy1), "front"))[1]
        out.append(((x0, y0), (x1, y1), side))
    return out


def jack_facing(item, facing):
    """The jack's facing ('left'/'right'/'top'/'down') after the item's rotation."""
    dx, dy = FACING[facing]
    dx, dy = {0: (dx, dy), 90: (-dy, dx), 180: (-dx, -dy), 270: (dy, -dx)}[item["rot"]]
    return FACING_NAME[(dx, dy)]


def clearance_rect(point, facing, outward_mm, side_mm):
    """Axis-aligned zone in front of a jack: `outward_mm` along `facing`, `side_mm` to each side."""
    x, y = point
    dx, dy = FACING[facing]
    if dx:  # left / right
        x0, x1 = sorted((x, x + dx * outward_mm))
        return (x0, y - side_mm, x1, y + side_mm)
    y0, y1 = sorted((y, y + dy * outward_mm))
    return (x - side_mm, y0, x + side_mm, y1)


def stub(point, facing, outward_mm):
    """Where the plug ends: the jack point moved `outward_mm` along its facing."""
    dx, dy = FACING[facing]
    return point[0] + dx * outward_mm, point[1] + dy * outward_mm


def overlap(a, b, tol_mm=TOL_MM):
    """(dx, dy) overlap of two rectangles in mm, or None unless both exceed `tol_mm`."""
    dx = min(a[2], b[2]) - max(a[0], b[0])
    dy = min(a[3], b[3]) - max(a[1], b[1])
    return (dx, dy) if dx > tol_mm and dy > tol_mm else None


def shape_overlap(rect, rects, tol_mm=TOL_MM):
    """The overlap (dx, dy) of `rect` with a shape made of several rects (an outline): the bounding box of its
    intersections with all of them, so a plug reaching across several thin bands of an outline gets its full depth;
    None unless both exceed `tol_mm` (see `overlap`)."""
    rx0, ry0, rx1, ry1 = rect
    lo_x = lo_y = math.inf   # the bounding box of the non-empty intersections
    hi_x = hi_y = -math.inf
    for r in rects:
        # (max(a, b) = b if b > a else a, min(a, b) = b if b < a else a: the builtins' results, without the calls)
        x0, y0, x1, y1 = r[0] if r[0] > rx0 else rx0, r[1] if r[1] > ry0 else ry0, r[2] if r[2] < rx1 else rx1, r[3] if r[3] < ry1 else ry1
        if x1 > x0 and y1 > y0:
            lo_x, lo_y = x0 if x0 < lo_x else lo_x, y0 if y0 < lo_y else lo_y
            hi_x, hi_y = x1 if x1 > hi_x else hi_x, y1 if y1 > hi_y else hi_y
    if lo_x == math.inf:
        return None
    dx, dy = hi_x - lo_x, hi_y - lo_y
    return (dx, dy) if dx > tol_mm and dy > tol_mm else None


def item_shapes(shapes, item):
    """The outline rects of a layout item (`shapes` = layout["shapes"]), its footprint when it has none."""
    return (shapes or {}).get(item["id"]) or [footprint(item)]


def overlap_depth(zone_facing, ov):
    """How far an obstacle reaches into a clearance zone: measured along the facing axis."""
    return ov[0] if zone_facing in ("left", "right") else ov[1]


# --- plug heads (mm) --------------------------------------------------------------------------
SIDES = ("left", "right")
DOWN = "down"                 # a right-angle plug can also point straight down into a board hole (no side)
EXITS = (*SIDES, DOWN)


def side_vector(facing, side):
    """Unit vector to the `side` ('left'/'right') of a jack, seen looking out along its facing from above
    (canvas y down): facing right -> left is up (top), right is down."""
    dx, dy = FACING[facing]
    return (dy, -dx) if side == "left" else (-dy, dx)


def _rect(p, u, a0, a1, v, b0, b1):
    """Axis-aligned rectangle spanned by a0..a1 along unit u and b0..b1 along unit v, from point p."""
    xs = [p[0] + u[0] * a + v[0] * b for a in (a0, a1) for b in (b0, b1)]
    ys = [p[1] + u[1] * a + v[1] * b for a in (a0, a1) for b in (b0, b1)]
    return (min(xs), min(ys), max(xs), max(ys))


def plug_geometry(point, facing, plug, diameter_mm, run_mm, side=None, drop_mm=0.0):
    """Footprint and cable lead of a plug in a jack at `point` (all mm, canvas frame).

    plug: catalog/cables.json `plug` block. Right-angle plugs need `side` ('left'/'right' of the facing): the
    cable leaves the head there, `exit_offset_mm` out from the jack face, the plug body reaches
    `body_reach_mm` from the jack axis, then the cable runs `run_mm` straight before it may bend.
    Straight plugs: the cable leaves along the facing at `head_depth_mm`, then runs `run_mm`.
    side "down" (right-angle plugs only): the cable leaves the head straight down, at the bend point (the point a side exit bends
    at); the footprint on the board is the head alone, `exit` = `lead[-1]` = the bend point (where the routed cable continues
    under the board), `measure_mm` includes `drop_mm` (the cable down through the jack height and the deck) and the option
    has "down": True. `drop_mm` is ignored for the other exits.
    Returns {"rects": [(part, rect)], "lead": [points from the jack to the exit], "exit": point, "lead_mm": float,
    "measure": point, "measure_mm": float} with parts "head", "barrel" (right-angle body beyond the head, if any)
    and "cable" (the straight run). Cable lengths are measured from `measure` (on the jack axis, half the head
    depth in front of the jack); `measure_mm` is the cable from there to the exit.
    """
    u = FACING[facing]
    depth, width = float(plug["head_depth_mm"]), float(plug["head_width_mm"])
    d = float(diameter_mm)
    m = (point[0] + u[0] * depth / 2, point[1] + u[1] * depth / 2)
    if plug["style"] == "straight":
        v = side_vector(facing, "left")
        rects = [("head", _rect(point, u, 0, depth, v, -width / 2, width / 2)),
                 ("cable", _rect(point, u, depth, depth + run_mm, v, -d / 2, d / 2))]
        ex = (point[0] + u[0] * (depth + run_mm), point[1] + u[1] * (depth + run_mm))
        return {"rects": rects, "lead": [point, ex], "exit": ex, "lead_mm": depth + run_mm,
                "measure": m, "measure_mm": depth / 2 + run_mm}
    if side not in EXITS:
        raise ValueError(f"right-angle plug needs side left/right/down, got {side!r}")
    off = plug.get("exit_offset_mm")
    off = depth / 2 if off is None else float(off)
    if side == DOWN:
        bend = (point[0] + u[0] * off, point[1] + u[1] * off)
        head = _rect(point, u, 0, depth, side_vector(facing, "left"), -width / 2, width / 2)
        return {"rects": [("head", head)], "lead": [point, bend], "exit": bend, "lead_mm": off, "measure": m,
                "measure_mm": abs(off - depth / 2) + float(drop_mm), "down": True}
    s = side_vector(facing, side)
    reach = plug.get("body_reach_mm")
    reach = width / 2 if reach is None else max(float(reach), width / 2)
    bw = plug.get("barrel_width_mm")
    bw = d if bw is None else float(bw)
    rects = [("head", _rect(point, u, 0, depth, s, -width / 2, width / 2))]
    if reach > width / 2:
        rects.append(("barrel", _rect(point, u, off - bw / 2, off + bw / 2, s, width / 2, reach)))
    rects.append(("cable", _rect(point, u, off - d / 2, off + d / 2, s, reach, reach + run_mm)))
    bend = (point[0] + u[0] * off, point[1] + u[1] * off)
    ex = (bend[0] + s[0] * (reach + run_mm), bend[1] + s[1] * (reach + run_mm))
    return {"rects": rects, "lead": [point, bend, ex], "exit": ex, "lead_mm": off + reach + run_mm,
            "measure": m, "measure_mm": abs(off - depth / 2) + reach + run_mm}


def part_depth(part, facing, side, ov):
    """How far an obstacle reaches into a plug part: along the facing for the head, else along the exit side."""
    if part == "head" or side is None:
        return overlap_depth(facing, ov)
    return overlap_depth("top" if facing in ("left", "right") else "left", ov)


# --- editing a layout ------------------------------------------------------------------------
ROTATIONS = (0, 90, 180, 270)


def move(item, cx, cy, rot=None, snap=True):
    """A copy of `item` with its centre at (cx, cy) mm and rotation `rot` (None keeps it).

    left/top describe the unrotated box (rotation is about its centre), so left = cx - w/2, top = cy - h/2.
    With `snap` the position is rounded to whole Pedal Playground px (0.56 mm at 45 px/in), as the site stores
    it, and the mm values are recomputed from the rounded px."""
    rot = item["rot"] if rot is None else int(rot) % 360
    if rot not in ROTATIONS:
        raise ValueError(f"rotation must be one of {ROTATIONS}, got {rot}")
    s = item["scale"]
    left_px = (cx - item["w_mm"] / 2) * s / IN_MM
    top_px = (cy - item["h_mm"] / 2) * s / IN_MM
    if snap:
        left_px, top_px = float(round(left_px)), float(round(top_px))
    return {**item, "rot": rot, "left_px": left_px, "top_px": top_px,
            "left_mm": px_to_mm(left_px, s), "top_mm": px_to_mm(top_px, s)}


def _px(v):
    return str(int(v)) if float(v).is_integer() else f"{v:.3f}".rstrip("0").rstrip(".")


_ITEM_TAG = re.compile(r"<div\b[^>]*>")
_ATTR = r'((?<![\w-]){}\s*=\s*")([^"]*)(")'   # not data-id=, x-class=...


def write_canvas(canvas_html, items):
    """The canvas HTML with the position (left/top px) and rotation class of the given items rewritten.

    Items are matched by id; only the start tag of each item div changes (its `style` left/top and the
    `rotate-N` class), every other byte of the canvas is kept, so the result still loads in Pedal Playground.
    Raises KeyError if an item id is not in the canvas."""
    want = {it["id"]: it for it in items}
    done = set()

    def edit(m):
        tag = m.group(0)
        idm = re.search(_ATTR.format("id"), tag)
        clm = re.search(_ATTR.format("class"), tag)
        if not idm or not clm or idm.group(2) not in want or "item" not in clm.group(2).split():
            return tag
        it = want[idm.group(2)]
        done.add(it["id"])
        classes = [c for c in clm.group(2).split() if not re.fullmatch(r"rotate-\d+", c)]
        if it["rot"]:
            classes.append(f"rotate-{it['rot']}")
        tag = re.sub(_ATTR.format("class"), lambda x: x.group(1) + " ".join(classes) + x.group(3), tag, count=1)

        def style(x):
            st = x.group(2)
            for key, val in (("left", it["left_px"]), ("top", it["top_px"])):
                new = f"{key}: {_px(val)}px"
                st, n = re.subn(rf"(?<![\w-]){key}:\s*-?[\d.]+px", new, st, count=1)   # not margin-left:
                if not n:
                    st = st.rstrip()
                    st = (st + ("" if not st or st.endswith(";") else ";") + f" {new};").strip()
            return x.group(1) + st + x.group(3)

        if re.search(_ATTR.format("style"), tag):
            return re.sub(_ATTR.format("style"), style, tag, count=1)
        return tag[:-1] + f' style="left: {_px(it["left_px"])}px; top: {_px(it["top_px"])}px;">'

    out = _ITEM_TAG.sub(edit, canvas_html)
    missing = set(want) - done
    if missing:
        raise KeyError(f"not in the canvas: {', '.join(sorted(missing))}")
    return out
