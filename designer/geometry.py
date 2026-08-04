"""Shape geometry: bounding boxes and hit tests shared by the rules.

Text boxes use real font metrics, so overlap, margin and hierarchy
checks reason about where glyphs actually land rather than about an
anchor point.
"""

from __future__ import annotations

from designer.fonts import first_family, is_bold, text_bounds
from designer.path import path_subpaths
from designer.svg import Document, Shape

Box = tuple[float, float, float, float]  # min_x, min_y, max_x, max_y


def shape_box(shape: Shape) -> Box | None:
    """Axis-aligned bounding box in user space, or None when unknown
    (e.g. a shape that kept an unbaked rotation)."""
    if shape.attrs.get("transform"):
        return None  # geometry is not in document space; don't guess

    if shape.tag in ("rect", "image"):
        x, y = shape.numeric("x") or 0.0, shape.numeric("y") or 0.0
        w, h = shape.numeric("width"), shape.numeric("height")
        if w is None or h is None:
            return None
        return (x, y, x + w, y + h)

    if shape.tag == "circle":
        cx, cy, r = shape.numeric("cx"), shape.numeric("cy"), shape.numeric("r")
        if None in (cx, cy, r):
            return None
        return (cx - r, cy - r, cx + r, cy + r)

    if shape.tag == "ellipse":
        cx, cy = shape.numeric("cx"), shape.numeric("cy")
        rx, ry = shape.numeric("rx"), shape.numeric("ry")
        if None in (cx, cy, rx, ry):
            return None
        return (cx - rx, cy - ry, cx + rx, cy + ry)

    if shape.tag == "line":
        x1, y1 = shape.numeric("x1"), shape.numeric("y1")
        x2, y2 = shape.numeric("x2"), shape.numeric("y2")
        if None in (x1, y1, x2, y2):
            return None
        return (min(x1, x2), min(y1, y2), max(x1, x2), max(y1, y2))

    if shape.tag in ("polygon", "polyline"):
        import re

        nums = [float(n) for n in re.findall(r"-?\d+(?:\.\d+)?", shape.attrs.get("points", ""))]
        xs, ys = nums[0::2], nums[1::2]
        if not xs or not ys:
            return None
        return (min(xs), min(ys), max(xs), max(ys))

    if shape.tag == "path":
        d = shape.attrs.get("d")
        if not d:
            return None
        try:
            subs = path_subpaths(d, curve_samples=6)
        except ValueError:
            return None
        xs = [p[0] for sub in subs for p in sub]
        ys = [p[1] for sub in subs for p in sub]
        if not xs:
            return None
        return (min(xs), min(ys), max(xs), max(ys))

    if shape.tag == "text":
        x, y = shape.numeric("x"), shape.numeric("y")
        if x is None or y is None or not shape.text:
            return None
        return text_bounds(
            x,
            y,
            shape.text,
            shape.get("font-family"),
            shape.numeric("font-size") or 16.0,
            anchor=(shape.get("text-anchor") or "start").strip(),
            bold=is_bold(shape.get("font-weight")),
        )
    return None


def boxes_overlap(a: Box, b: Box, tolerance: float = 0.0) -> bool:
    return not (
        a[2] - tolerance <= b[0]
        or b[2] - tolerance <= a[0]
        or a[3] - tolerance <= b[1]
        or b[3] - tolerance <= a[1]
    )


def overlap_area(a: Box, b: Box) -> float:
    w = min(a[2], b[2]) - max(a[0], b[0])
    h = min(a[3], b[3]) - max(a[1], b[1])
    return max(0.0, w) * max(0.0, h)


def box_area(b: Box) -> float:
    return max(0.0, b[2] - b[0]) * max(0.0, b[3] - b[1])


def point_in_shape(shape: Shape, px: float, py: float) -> bool:
    """Exact hit test for paths (even-odd over flattened subpaths) and
    analytic tests for primitives."""
    if shape.tag == "path":
        d = shape.attrs.get("d")
        if not d:
            return False
        try:
            subs = path_subpaths(d, curve_samples=8)
        except ValueError:
            return False
        crossings = 0
        for sub in subs:
            crossings += _ray_crossings(sub, px, py)
        return crossings % 2 == 1

    if shape.tag == "circle":
        cx, cy, r = shape.numeric("cx"), shape.numeric("cy"), shape.numeric("r")
        if None in (cx, cy, r):
            return False
        return (px - cx) ** 2 + (py - cy) ** 2 <= r * r

    if shape.tag == "ellipse":
        cx, cy = shape.numeric("cx"), shape.numeric("cy")
        rx, ry = shape.numeric("rx"), shape.numeric("ry")
        if None in (cx, cy, rx, ry) or rx == 0 or ry == 0:
            return False
        return ((px - cx) / rx) ** 2 + ((py - cy) / ry) ** 2 <= 1

    if shape.tag in ("polygon",):
        import re

        nums = [float(n) for n in re.findall(r"-?\d+(?:\.\d+)?", shape.attrs.get("points", ""))]
        pts = list(zip(nums[0::2], nums[1::2]))
        return _ray_crossings(pts, px, py) % 2 == 1

    box = shape_box(shape)
    if box is None:
        return False
    return box[0] <= px <= box[2] and box[1] <= py <= box[3]


def _ray_crossings(points: list[tuple[float, float]], px: float, py: float) -> int:
    """Crossings of a rightward ray from (px, py) over a closed ring."""
    crossings = 0
    n = len(points)
    for i in range(n):
        x1, y1 = points[i]
        x2, y2 = points[(i + 1) % n]
        if (y1 > py) != (y2 > py):
            t = (py - y1) / (y2 - y1)
            if px < x1 + t * (x2 - x1):
                crossings += 1
    return crossings


def is_background(shape: Shape, doc: Document) -> bool:
    box = shape_box(shape)
    if box is None:
        return False
    return box_area(box) >= 0.9 * doc.width * doc.height
