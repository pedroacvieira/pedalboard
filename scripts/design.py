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


def overlap_depth(zone_facing, ov):
    """How far an obstacle reaches into a clearance zone: measured along the facing axis."""
    return ov[0] if zone_facing in ("left", "right") else ov[1]


# --- plug heads (mm) --------------------------------------------------------------------------
SIDES = ("left", "right")


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


def plug_geometry(point, facing, plug, diameter_mm, run_mm, side=None):
    """Footprint and cable lead of a plug in a jack at `point` (all mm, canvas frame).

    plug: catalog/cables.json `plug` block. Right-angle plugs need `side` ('left'/'right' of the facing): the
    cable leaves the head there, `exit_offset_mm` out from the jack face, the plug body reaches
    `body_reach_mm` from the jack axis, then the cable runs `run_mm` straight before it may bend.
    Straight plugs: the cable leaves along the facing at `head_depth_mm`, then runs `run_mm`.
    Returns {"rects": [(part, rect)], "lead": [points from the jack to the exit], "exit": point, "lead_mm": float}
    with parts "head", "barrel" (right-angle body beyond the head, if any) and "cable" (the straight run).
    """
    u = FACING[facing]
    depth, width = float(plug["head_depth_mm"]), float(plug["head_width_mm"])
    d = float(diameter_mm)
    if plug["style"] == "straight":
        v = side_vector(facing, "left")
        rects = [("head", _rect(point, u, 0, depth, v, -width / 2, width / 2)),
                 ("cable", _rect(point, u, depth, depth + run_mm, v, -d / 2, d / 2))]
        ex = (point[0] + u[0] * (depth + run_mm), point[1] + u[1] * (depth + run_mm))
        return {"rects": rects, "lead": [point, ex], "exit": ex, "lead_mm": depth + run_mm}
    if side not in SIDES:
        raise ValueError(f"right-angle plug needs side left/right, got {side!r}")
    s = side_vector(facing, side)
    off = plug.get("exit_offset_mm")
    off = depth / 2 if off is None else float(off)
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
    return {"rects": rects, "lead": [point, bend, ex], "exit": ex, "lead_mm": off + reach + run_mm}


def part_depth(part, facing, side, ov):
    """How far an obstacle reaches into a plug part: along the facing for the head, else along the exit side."""
    if part == "head" or side is None:
        return overlap_depth(facing, ov)
    return overlap_depth("top" if facing in ("left", "right") else "left", ov)
