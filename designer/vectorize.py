# Copyright (c) 2026 RokctAI
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.

"""Raster -> vector: trace quantized color layers into clean SVG paths.

Pipeline per color layer:
  1. exact boundary tracing on the pixel grid (closed loops, holes
     handled by the even-odd fill rule),
  2. collinear collapse + Douglas-Peucker simplification,
  3. optional Bezier smoothing with corner preservation, so organic
     shapes come out smooth while logo geometry keeps its edges.

No external tracer (potrace etc.) is required.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from designer.color import RGB, delta_e, to_hex
from designer.gradient import GradientCandidate, detect_gradients
from designer.raster import QuantizedImage, load_image, quantize
from designer.svg import Document, GradientDef, Shape

Point = tuple[float, float]


class ComplexityError(ValueError):
    """Input is too complex to vectorize meaningfully (photographic or
    heavily textured). Raised instead of producing megabytes of noisy
    micro-paths; callers surface the message to the user."""

    def __init__(self, density: float, limit: float, photographic: bool = False):
        self.density = density
        self.limit = limit
        if photographic:
            message = (
                f"this image is {density:.0%} photographic (limit {limit:.0%}) — it is a "
                "photo, not a design. Vectorizing it would produce a huge, meaningless "
                "file. Use it as an image, or pass --force to trace it anyway."
            )
        else:
            message = (
                f"input is too textured to vectorize meaningfully (edge density "
                f"{density:.2f} exceeds {limit:.2f}). Use flatter artwork, reduce "
                "--colors, lower --max-dim, or pass --force to override."
            )
        super().__init__(message)


@dataclass
class VectorizeOptions:
    n_colors: int = 6
    simplify_tolerance: float = 1.0  # px; Douglas-Peucker epsilon
    smooth: bool = True
    corner_angle: float = 60.0  # degrees of turn above which a vertex stays sharp
    max_dim: int | None = 1024  # downscale input so max(w, h) <= this
    # Gradient reconstruction: quantize finer internally, then rebuild
    # banded regions as real SVG gradients instead of posterized layers.
    detect_gradients: bool = True
    gradient_bands: int = 12  # internal quantization depth when detecting
    # OCR text extraction: None = auto (on when tesseract is available).
    # Detected text is re-emitted as editable <text>, never as outlines.
    extract_text: bool | None = None
    min_text_confidence: float = 60.0
    ocr_lang: str = "eng"  # tesseract language(s), e.g. "eng+fra"
    # Hybrid output: embed photographic regions as <image> instead of
    # tracing them, so a poster with a photo in it works properly.
    hybrid: bool = True
    # Complexity guard: refuse inputs that are photographs end to end
    # (after hybrid extraction) rather than emitting noise.
    max_edge_density: float = 0.4
    max_photo_coverage: float = 0.85
    force: bool = False  # override the complexity guard


# ------------------------------------------------------------- tracing


def trace_mask(mask: np.ndarray) -> list[list[Point]]:
    """Trace boundary loops of a boolean mask.

    Every edge between a filled and an empty pixel becomes part of
    exactly one closed loop; outer boundaries wind clockwise (screen
    coords) and holes counter-clockwise, so rendering the loops of one
    layer as a single even-odd path reproduces the mask exactly.
    """
    h, w = mask.shape
    padded = np.zeros((h + 2, w + 2), dtype=bool)
    padded[1:-1, 1:-1] = mask

    top = mask & ~padded[:-2, 1:-1]
    bottom = mask & ~padded[2:, 1:-1]
    left = mask & ~padded[1:-1, :-2]
    right = mask & ~padded[1:-1, 2:]

    edges: dict[Point, list[Point]] = {}

    def add(sx: float, sy: float, ex: float, ey: float) -> None:
        edges.setdefault((sx, sy), []).append((ex, ey))

    ys, xs = np.nonzero(top)
    for y, x in zip(ys.tolist(), xs.tolist()):
        add(x, y, x + 1, y)
    ys, xs = np.nonzero(right)
    for y, x in zip(ys.tolist(), xs.tolist()):
        add(x + 1, y, x + 1, y + 1)
    ys, xs = np.nonzero(bottom)
    for y, x in zip(ys.tolist(), xs.tolist()):
        add(x + 1, y + 1, x, y + 1)
    ys, xs = np.nonzero(left)
    for y, x in zip(ys.tolist(), xs.tolist()):
        add(x, y + 1, x, y)

    loops: list[list[Point]] = []
    while edges:
        start = next(iter(edges))
        loop = [start]
        current = start
        prev_dir: Point | None = None
        while True:
            candidates = edges.get(current)
            if not candidates:
                break  # degenerate; abandon this chain
            nxt = _pick_next(current, candidates, prev_dir)
            candidates.remove(nxt)
            if not candidates:
                del edges[current]
            prev_dir = (nxt[0] - current[0], nxt[1] - current[1])
            current = nxt
            if current == start:
                loops.append(loop)
                break
            loop.append(current)
    return loops


_DIRS = [(1, 0), (0, 1), (-1, 0), (0, -1)]  # R, D, L, U (clockwise, y-down)


def _pick_next(current: Point, candidates: list[Point], prev_dir: Point | None) -> Point:
    if len(candidates) == 1 or prev_dir is None:
        return candidates[0]
    # At a diagonal-touch vertex two edges leave the same point; prefer
    # the sharpest right turn so loops stay simple (never self-cross).
    i = _DIRS.index(prev_dir)
    for preferred in ((i + 1) % 4, i, (i + 3) % 4):
        want = _DIRS[preferred]
        for c in candidates:
            if (c[0] - current[0], c[1] - current[1]) == want:
                return c
    return candidates[0]


# -------------------------------------------------------- simplification


def collapse_collinear(points: list[Point]) -> list[Point]:
    """Remove interior points of straight runs (closed polygon)."""
    if len(points) < 3:
        return points
    out: list[Point] = []
    n = len(points)
    for i in range(n):
        prev_pt, cur, nxt = points[i - 1], points[i], points[(i + 1) % n]
        v1 = (cur[0] - prev_pt[0], cur[1] - prev_pt[1])
        v2 = (nxt[0] - cur[0], nxt[1] - cur[1])
        if v1[0] * v2[1] - v1[1] * v2[0] != 0 or (v1[0] * v2[0] + v1[1] * v2[1]) < 0:
            out.append(cur)
    return out if len(out) >= 3 else points


def _perp_distance(pt: Point, a: Point, b: Point) -> float:
    ax, ay = a
    bx, by = b
    px, py = pt
    dx, dy = bx - ax, by - ay
    length = math.hypot(dx, dy)
    if length == 0:
        return math.hypot(px - ax, py - ay)
    return abs(dx * (ay - py) - dy * (ax - px)) / length


def douglas_peucker(points: list[Point], epsilon: float) -> list[Point]:
    """Iterative Douglas-Peucker on an open polyline."""
    if len(points) < 3 or epsilon <= 0:
        return points
    keep = [False] * len(points)
    keep[0] = keep[-1] = True
    stack = [(0, len(points) - 1)]
    while stack:
        lo, hi = stack.pop()
        if hi <= lo + 1:
            continue
        best_d, best_i = -1.0, -1
        for i in range(lo + 1, hi):
            d = _perp_distance(points[i], points[lo], points[hi])
            if d > best_d:
                best_d, best_i = d, i
        if best_d > epsilon:
            keep[best_i] = True
            stack.append((lo, best_i))
            stack.append((best_i, hi))
    return [p for p, k in zip(points, keep) if k]


def simplify_loop(points: list[Point], epsilon: float) -> list[Point]:
    """Simplify a closed loop: collapse collinear runs, rotate to start
    at a feature point, then Douglas-Peucker both halves."""
    points = collapse_collinear(points)
    if len(points) < 4:
        return points
    cx = sum(p[0] for p in points) / len(points)
    cy = sum(p[1] for p in points) / len(points)
    start = max(range(len(points)), key=lambda i: (points[i][0] - cx) ** 2 + (points[i][1] - cy) ** 2)
    points = points[start:] + points[:start]
    # Split at the vertex farthest from the start so DP endpoints are
    # genuine features of the outline.
    far = max(
        range(1, len(points)),
        key=lambda i: (points[i][0] - points[0][0]) ** 2 + (points[i][1] - points[0][1]) ** 2,
    )
    first = douglas_peucker(points[: far + 1], epsilon)
    second = douglas_peucker(points[far:] + [points[0]], epsilon)
    merged = first[:-1] + second[:-1]
    return merged if len(merged) >= 3 else points


# ------------------------------------------------------------ smoothing


def _turn_angle(prev_pt: Point, cur: Point, nxt: Point) -> float:
    v1 = (cur[0] - prev_pt[0], cur[1] - prev_pt[1])
    v2 = (nxt[0] - cur[0], nxt[1] - cur[1])
    a1 = math.atan2(v1[1], v1[0])
    a2 = math.atan2(v2[1], v2[0])
    diff = abs(a2 - a1)
    if diff > math.pi:
        diff = 2 * math.pi - diff
    return math.degrees(diff)


def loop_to_path(points: list[Point], smooth: bool, corner_angle: float) -> str:
    """Serialize one closed loop as SVG path commands."""
    if not points:
        return ""
    if not smooth or len(points) < 4:
        cmds = [f"M {points[0][0]:g} {points[0][1]:g}"]
        cmds += [f"L {p[0]:g} {p[1]:g}" for p in points[1:]]
        cmds.append("Z")
        return " ".join(cmds)

    n = len(points)
    corners = [
        _turn_angle(points[i - 1], points[i], points[(i + 1) % n]) > corner_angle
        for i in range(n)
    ]
    cmds = [f"M {points[0][0]:.2f} {points[0][1]:.2f}"]
    for i in range(n):
        p0 = points[i - 1]
        p1 = points[i]
        p2 = points[(i + 1) % n]
        p3 = points[(i + 2) % n]
        # Catmull-Rom tangents; a corner vertex contributes a tangent
        # along its own segment so the edge stays sharp.
        if corners[i]:
            c1 = (p1[0] + (p2[0] - p1[0]) / 3, p1[1] + (p2[1] - p1[1]) / 3)
        else:
            c1 = (p1[0] + (p2[0] - p0[0]) / 6, p1[1] + (p2[1] - p0[1]) / 6)
        if corners[(i + 1) % n]:
            c2 = (p2[0] - (p2[0] - p1[0]) / 3, p2[1] - (p2[1] - p1[1]) / 3)
        else:
            c2 = (p2[0] - (p3[0] - p1[0]) / 6, p2[1] - (p3[1] - p1[1]) / 6)
        cmds.append(
            f"C {c1[0]:.2f} {c1[1]:.2f} {c2[0]:.2f} {c2[1]:.2f} {p2[0]:.2f} {p2[1]:.2f}"
        )
    cmds.append("Z")
    return " ".join(cmds)


# ------------------------------------------------------------- assembly


def _merge_flat_groups(
    qimg: QuantizedImage, indices: list[int], target: int
) -> list[list[int]]:
    """Greedily merge flat (non-gradient) layers down to ``target``
    groups by perceptual closeness. Returns index groups; each group's
    representative color is its largest member's."""
    groups = [[i] for i in indices]

    def rep(group: list[int]) -> RGB:
        biggest = max(group, key=lambda i: qimg.coverage[i])
        return qimg.palette[biggest]

    while len(groups) > max(1, target):
        best, best_d = None, float("inf")
        for a in range(len(groups)):
            for b in range(a + 1, len(groups)):
                d = delta_e(rep(groups[a]), rep(groups[b]))
                if d < best_d:
                    best_d, best = d, (a, b)
        a, b = best  # type: ignore[misc]
        groups[a].extend(groups.pop(b))
    return groups


def _trace_shape(
    mask: np.ndarray, fill: str, options: VectorizeOptions
) -> Shape | None:
    loops = trace_mask(mask)
    subpaths = []
    for loop in loops:
        pts = simplify_loop(loop, options.simplify_tolerance)
        if len(pts) < 3:
            continue
        subpaths.append(loop_to_path(pts, options.smooth, options.corner_angle))
    if not subpaths:
        return None
    return Shape(
        tag="path",
        attrs={"d": " ".join(subpaths), "fill": fill, "fill-rule": "evenodd"},
    )


def vectorize_quantized(
    qimg: QuantizedImage,
    options: VectorizeOptions,
    gradients: list[GradientCandidate] | None = None,
) -> Document:
    gradients = gradients or []
    doc = Document(width=float(qimg.width), height=float(qimg.height))

    consumed = {i for g in gradients for i in g.layer_indices}
    flat_indices = [i for i in range(len(qimg.palette)) if i not in consumed]
    flat_target = max(1, options.n_colors - len(gradients)) if flat_indices else 0
    flat_groups = _merge_flat_groups(qimg, flat_indices, flat_target)

    # One paint entry per flat group / gradient, painted large-to-small.
    entries: list[tuple[float, str, object]] = []
    for group in flat_groups:
        coverage = sum(qimg.coverage[i] for i in group)
        entries.append((coverage, "flat", group))
    for grad in gradients:
        entries.append((grad.coverage, "gradient", grad))
    entries.sort(key=lambda e: -e[0])

    for rank, (coverage, kind, payload) in enumerate(entries):
        if kind == "flat":
            group: list[int] = payload  # type: ignore[assignment]
            biggest = max(group, key=lambda i: qimg.coverage[i])
            color = to_hex(qimg.palette[biggest])
            # The dominant flat layer is the canvas background: a
            # full-bleed rect renders cleanly and gives the auditor an
            # explicit background.
            if rank == 0 and coverage >= 0.25:
                doc.shapes.append(
                    Shape(
                        tag="rect",
                        attrs={
                            "x": "0",
                            "y": "0",
                            "width": f"{qimg.width:g}",
                            "height": f"{qimg.height:g}",
                            "fill": color,
                        },
                    )
                )
                continue
            mask = np.isin(qimg.labels, group)
            shape = _trace_shape(mask, color, options)
            if shape:
                doc.shapes.append(shape)
        else:
            grad: GradientCandidate = payload  # type: ignore[assignment]
            gid = f"grad{len(doc.defs)}"
            doc.defs.append(
                GradientDef(
                    id=gid,
                    kind=grad.kind,
                    stops=[(t, to_hex(c)) for t, c in grad.stops],
                    coords=dict(grad.coords),
                )
            )
            mask = np.isin(qimg.labels, grad.layer_indices)
            shape = _trace_shape(mask, f"url(#{gid})", options)
            if shape:
                doc.shapes.append(shape)
            else:
                doc.defs.pop()
    return doc


def vectorize_file(path: str | Path, options: VectorizeOptions | None = None) -> Document:
    options = options or VectorizeOptions()
    img = load_image(path, max_dim=options.max_dim)

    spans = []
    ocr_note = None
    want_text = options.extract_text
    if want_text is None:
        from designer.text import ocr_available

        want_text = ocr_available()
    if want_text:
        from designer.text import extract_text

        img, spans = extract_text(img, options.min_text_confidence, lang=options.ocr_lang)
    elif options.extract_text is None:
        ocr_note = (
            "OCR unavailable (tesseract not installed): any text in the image "
            "remains as vector outlines instead of editable <text>"
        )

    internal_colors = (
        max(options.n_colors, options.gradient_bands)
        if options.detect_gradients
        else options.n_colors
    )
    qimg = quantize(img, n_colors=internal_colors)

    photo_regions = []
    if options.hybrid:
        from designer.hybrid import extract_photo_regions, photo_coverage

        photo_regions, masked = extract_photo_regions(img, qimg.labels)
        coverage = photo_coverage(photo_regions, qimg.width, qimg.height)
        if coverage > options.max_photo_coverage and not options.force:
            raise ComplexityError(coverage, options.max_photo_coverage, photographic=True)
        if photo_regions:
            qimg.labels = masked
            total = max(1, int((masked >= 0).sum()))
            qimg.coverage = [
                float((masked == i).sum()) / total for i in range(len(qimg.palette))
            ]

    labels = qimg.labels
    flat = labels >= 0
    if flat.sum() > 0:
        transitions = int(((labels[:, 1:] != labels[:, :-1]) & flat[:, 1:]).sum()) + int(
            ((labels[1:, :] != labels[:-1, :]) & flat[1:, :]).sum()
        )
        density = transitions / max(1, int(flat.sum()))
        if density > options.max_edge_density and not options.force:
            raise ComplexityError(density, options.max_edge_density)

    original = np.asarray(img.convert("RGB"), dtype=np.uint8)
    gradients = (
        detect_gradients(qimg, original=original) if options.detect_gradients else []
    )
    doc = vectorize_quantized(qimg, options, gradients)

    # Photos sit above the traced background, below any text.
    for region in photo_regions:
        doc.shapes.append(
            Shape(
                tag="image",
                attrs={
                    "x": f"{region.x:g}",
                    "y": f"{region.y:g}",
                    "width": f"{region.width:g}",
                    "height": f"{region.height:g}",
                    "href": region.href,
                    "preserveAspectRatio": "xMidYMid slice",
                },
            )
        )
    if photo_regions:
        doc.warnings.append(
            f"{len(photo_regions)} photographic region(s) embedded as raster rather "
            "than vectorized; their content is not audited for brand compliance"
        )
    if ocr_note:
        doc.warnings.append(ocr_note)

    for span in spans:
        attrs = {
            "x": f"{span.x:g}",
            "y": f"{span.y:g}",
            "font-size": f"{span.font_size:g}",
            "fill": to_hex(span.color),
        }
        if abs(getattr(span, "angle", 0.0)) > 0.5:
            attrs["transform"] = (
                f"rotate({span.angle:.2f} {span.x:g} {span.y:g})"
            )
        doc.shapes.append(Shape(tag="text", attrs=attrs, text=span.text))
    doc.source = str(path)
    return doc
