# Copyright (c) 2026 ROKCT INTELLIGENCE (PTY) LTD
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as published
# by the Free Software Foundation, version 3.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with this program. If not, see <https://www.gnu.org/licenses/>.
"""Construction overlay: show the geometry a logo was (or wasn't) built on.

Draws the guides a designer would draw over a mark: the bounding box and
centre lines, horizontal and vertical alignment lines that several
shapes share (baseline, cap height, x-height, stems), and best-fit
circles on the curved edges, with the ratios between circle sizes
(1:1, golden, 1:2, ...). Informational only: nothing here scores or
fails a design, it shows which rules the design follows.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

from designer.geometry import is_background, shape_box
from designer.path import path_subpaths
from designer.svg import Document, Shape

Point = tuple[float, float]

# Ratios a construction grid is usually built on.
NAMED_RATIOS = {
    "1:1": 1.0,
    "golden (1:1.618)": (1 + 5 ** 0.5) / 2,
    "1:2": 2.0,
    "2:3": 1.5,
    "1:√2": 2 ** 0.5,
    "3:4": 4 / 3,
}
_RATIO_TOLERANCE = 0.03
_ALIGN_TOLERANCE = 0.01  # of the artwork's larger side
_ARC_WINDOW = 9  # sampled points per circle-fit window
_ARC_MAX_RESIDUAL = 0.02  # RMS fit error, as a share of the radius
_ARC_MIN_SWEEP = math.radians(90)


@dataclass
class Circle:
    cx: float
    cy: float
    r: float
    sweep: float  # radians of edge this circle follows


@dataclass
class Construction:
    box: tuple[float, float, float, float]  # x0, y0, x1, y1 of the artwork
    horizontals: list[tuple[float, int]] = field(default_factory=list)  # (y, shapes sharing)
    verticals: list[tuple[float, int]] = field(default_factory=list)
    circles: list[Circle] = field(default_factory=list)
    ratios: list[tuple[int, int, str]] = field(default_factory=list)  # circle i, j, ratio name

    def to_text(self) -> str:
        x0, y0, x1, y1 = self.box
        lines = [
            f"Artwork box : {x1 - x0:.1f} x {y1 - y0:.1f}  (centre {(x0 + x1) / 2:.1f}, {(y0 + y1) / 2:.1f})",
            f"Horizontal alignment lines : {len(self.horizontals)}",
        ]
        lines += [f"  y={y:.1f}  shared by {n} edges" for y, n in self.horizontals]
        lines.append(f"Vertical alignment lines   : {len(self.verticals)}")
        lines += [f"  x={x:.1f}  shared by {n} edges" for x, n in self.verticals]
        lines.append(f"Construction circles       : {len(self.circles)}")
        lines += [
            f"  C{i + 1}: centre ({c.cx:.1f}, {c.cy:.1f}) r={c.r:.1f}  follows {math.degrees(c.sweep):.0f}° of edge"
            for i, c in enumerate(self.circles)
        ]
        if self.ratios:
            lines.append("Circle size ratios:")
            lines += [f"  C{i + 1} : C{j + 1} = {name}" for i, j, name in self.ratios]
        else:
            lines.append("Circle size ratios: none on a standard ratio")
        return "\n".join(lines)


def _outlines(doc: Document) -> list[list[Point]]:
    out: list[list[Point]] = []
    for shape in doc.shapes:
        if is_background(shape, doc):
            continue
        if shape.tag == "path" and shape.get("d"):
            try:
                out += [p for p in path_subpaths(shape.get("d"), curve_samples=12) if len(p) >= 3]
            except ValueError:
                continue
        elif shape.tag in ("circle", "ellipse"):
            try:
                cx, cy = float(shape.get("cx") or 0), float(shape.get("cy") or 0)
                rx = float(shape.get("r") or shape.get("rx") or 0)
                ry = float(shape.get("r") or shape.get("ry") or 0)
            except ValueError:
                continue
            if rx > 0 and ry > 0:
                out.append([(cx + rx * math.cos(t * math.pi / 32),
                             cy + ry * math.sin(t * math.pi / 32)) for t in range(64)])
        else:
            box = shape_box(shape)
            if box is not None:
                x0, y0, x1, y1 = box
                out.append([(x0, y0), (x1, y0), (x1, y1), (x0, y1)])
    return out


def _cluster(values: list[float], tol: float) -> list[tuple[float, int]]:
    """Group near-equal coordinates; keep groups shared by 2+ edges."""
    groups: list[list[float]] = []
    for v in sorted(values):
        if groups and v - groups[-1][-1] <= tol:
            groups[-1].append(v)
        else:
            groups.append([v])
    return [(sum(g) / len(g), len(g)) for g in groups if len(g) >= 2]


def _fit_circle(pts: np.ndarray) -> tuple[float, float, float, float] | None:
    """Least-squares (Kasa) circle fit; returns cx, cy, r, rms error."""
    x, y = pts[:, 0], pts[:, 1]
    a = np.column_stack([x, y, np.ones(len(x))])
    b = x * x + y * y
    try:
        sol, *_ = np.linalg.lstsq(a, b, rcond=None)
    except np.linalg.LinAlgError:
        return None
    cx, cy = sol[0] / 2, sol[1] / 2
    r2 = sol[2] + cx * cx + cy * cy
    if r2 <= 0:
        return None
    r = math.sqrt(r2)
    rms = float(np.sqrt(np.mean((np.hypot(x - cx, y - cy) - r) ** 2)))
    return cx, cy, r, rms


def _resample(points: list[Point], step: float) -> np.ndarray:
    pts = np.asarray(points + [points[0]], dtype=float)
    seg = np.hypot(*np.diff(pts, axis=0).T)
    total = float(seg.sum())
    if total == 0:
        return pts[:1]
    cum = np.concatenate([[0], np.cumsum(seg)])
    t = np.arange(0, total, step)
    return np.column_stack([np.interp(t, cum, pts[:, 0]), np.interp(t, cum, pts[:, 1])])


def _arcs(points: list[Point], min_r: float, max_r: float, step: float) -> list[Circle]:
    """Grow circle fits along an outline; keep runs that sweep 60+ degrees."""
    pts = _resample(points, step)
    n = len(pts)
    found: list[Circle] = []
    i = 0
    while i + _ARC_WINDOW <= n:
        fit = _fit_circle(pts[i:i + _ARC_WINDOW])
        if fit is None or fit[3] > _ARC_MAX_RESIDUAL * fit[2] or not min_r <= fit[2] <= max_r:
            i += 1
            continue
        j = i + _ARC_WINDOW
        best = fit
        while j < n:
            nxt = _fit_circle(pts[i:j + 1])
            if nxt is None or nxt[3] > _ARC_MAX_RESIDUAL * nxt[2]:
                break
            best, j = nxt, j + 1
        cx, cy, r, _ = best
        sweep = (j - i) * step / r
        if sweep >= _ARC_MIN_SWEEP:
            found.append(Circle(cx, cy, r, min(sweep, 2 * math.pi)))
        i = j
    return found


def _merge_circles(circles: list[Circle], tol: float) -> list[Circle]:
    merged: list[Circle] = []
    for c in sorted(circles, key=lambda c: -c.sweep):
        for m in merged:
            if math.hypot(c.cx - m.cx, c.cy - m.cy) <= tol and abs(c.r - m.r) <= tol:
                m.sweep = min(2 * math.pi, m.sweep + c.sweep)
                break
        else:
            merged.append(Circle(c.cx, c.cy, c.r, c.sweep))
    return sorted(merged, key=lambda c: -c.r)


def construct(doc: Document, max_circles: int = 6) -> Construction:
    outlines = _outlines(doc)
    if not outlines:
        return Construction(box=(0.0, 0.0, doc.width, doc.height))
    allpts = np.concatenate([np.asarray(o) for o in outlines])
    x0, y0 = allpts.min(axis=0)
    x1, y1 = allpts.max(axis=0)
    size = max(x1 - x0, y1 - y0, 1.0)
    tol = size * _ALIGN_TOLERANCE

    tops, bottoms, lefts, rights = [], [], [], []
    for o in outlines:
        a = np.asarray(o)
        (lx, ty), (rx, by) = a.min(axis=0), a.max(axis=0)
        if max(rx - lx, by - ty) < size * 0.02:
            continue  # specks don't define a grid
        tops.append(ty)
        bottoms.append(by)
        lefts.append(lx)
        rights.append(rx)
    result = Construction(box=(float(x0), float(y0), float(x1), float(y1)))
    result.horizontals = _cluster(tops + bottoms, tol)
    result.verticals = _cluster(lefts + rights, tol)

    step = size / 200
    circles: list[Circle] = []
    for o in outlines:
        circles += _arcs(o, min_r=size * 0.03, max_r=size * 1.5, step=step)
    result.circles = _merge_circles(circles, tol * 2)[:max_circles]

    for i, a in enumerate(result.circles):
        for j in range(i + 1, len(result.circles)):
            b = result.circles[j]
            ratio = max(a.r, b.r) / min(a.r, b.r)
            for name, target in NAMED_RATIOS.items():
                if abs(ratio - target) / target <= _RATIO_TOLERANCE:
                    result.ratios.append((i, j, name))
                    break
    return result


GUIDE = "#e5007e"  # construction magenta: reads over most brand palettes
CIRCLE = "#00a3e0"


def overlay(doc: Document, con: Construction) -> Document:
    """A copy of ``doc`` with the construction drawn on top."""
    size = max(doc.width, doc.height)
    hair = f"{max(size / 800, 0.5):.2f}"
    dash = f"{size / 150:.1f} {size / 200:.1f}"
    shapes = list(doc.shapes)
    x0, y0, x1, y1 = con.box

    def line(xa, ya, xb, yb, color=GUIDE, dashed=False):
        attrs = {"x1": f"{xa:.2f}", "y1": f"{ya:.2f}", "x2": f"{xb:.2f}", "y2": f"{yb:.2f}",
                 "stroke": color, "stroke-width": hair, "fill": "none"}
        if dashed:
            attrs["stroke-dasharray"] = dash
        shapes.append(Shape("line", attrs))

    shapes.append(Shape("rect", {"x": f"{x0:.2f}", "y": f"{y0:.2f}", "width": f"{x1 - x0:.2f}",
                                 "height": f"{y1 - y0:.2f}", "fill": "none", "stroke": GUIDE,
                                 "stroke-width": hair}))
    line((x0 + x1) / 2, 0, (x0 + x1) / 2, doc.height, dashed=True)
    line(0, (y0 + y1) / 2, doc.width, (y0 + y1) / 2, dashed=True)
    for y, _ in con.horizontals:
        line(0, y, doc.width, y)
    for x, _ in con.verticals:
        line(x, 0, x, doc.height)
    for i, c in enumerate(con.circles):
        shapes.append(Shape("circle", {"cx": f"{c.cx:.2f}", "cy": f"{c.cy:.2f}", "r": f"{c.r:.2f}",
                                       "fill": "none", "stroke": CIRCLE, "stroke-width": hair}))
        shapes.append(Shape("circle", {"cx": f"{c.cx:.2f}", "cy": f"{c.cy:.2f}",
                                       "r": f"{float(hair) * 2:.2f}", "fill": CIRCLE}))
    return Document(width=doc.width, height=doc.height, shapes=shapes, defs=list(doc.defs),
                    raw_defs=list(doc.raw_defs), source=doc.source)


def with_construction(doc: Document, on: bool = True) -> Document:
    """The SDK switch: ``doc`` with its construction overlay when ``on``,
    else ``doc`` untouched. Informational only, never changes a score."""
    return overlay(doc, construct(doc)) if on else doc
