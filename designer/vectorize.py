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
    # Anti-alias cleanup: thin colour layers that only exist as a 1-2px
    # rim between two real shapes (edge blending, JPEG ringing) are
    # absorbed into their neighbours instead of traced as halo outlines.
    absorb_fringes: bool = True
    # Edge denoise: majority-vote passes over the label map, so JPEG
    # noise and stair-steps along a boundary don't become wobbly curves.
    denoise_passes: int = 2
    # Stair-step averaging radius (px) on traced outlines before curve
    # fitting; square corners are preserved. 0 disables.
    edge_smoothing: int = 2


# A real photo spreads over many colours; flat art the hybrid pass
# embedded anyway (thin script with blurred edges) is a few inks plus
# the blends between them. A pixel is "explained" when it lies near a
# straight line between two of the region's dominant colours.
_FLAT_ART_INKS = 3
_FLAT_ART_TOLERANCE = 30.0  # RGB distance from the nearest ink-to-ink blend
_FLAT_ART_SHARE = 0.85


def _is_flat_artwork(labels: np.ndarray, original: np.ndarray, region) -> bool:
    ys = slice(region.y, region.y + region.height)
    xs = slice(region.x, region.x + region.width)
    crop_labels = labels[ys, xs]
    valid = crop_labels >= 0
    if not valid.any():
        return False
    counts = np.bincount(crop_labels[valid])
    inks_idx = np.argsort(counts)[::-1][:_FLAT_ART_INKS]
    pix = original[ys, xs][valid].astype(np.float32)
    inks = [pix[crop_labels[valid] == i].mean(axis=0) for i in inks_idx if counts[i] > 0]
    best = np.full(len(pix), np.inf, dtype=np.float32)
    for j, a in enumerate(inks):
        for b in inks[j:]:
            ab = b - a
            denom = float((ab * ab).sum())
            t = np.zeros(len(pix), np.float32) if denom == 0 else np.clip(
                ((pix - a) @ ab) / denom, 0.0, 1.0
            )
            nearest = a + t[:, None] * ab
            best = np.minimum(best, np.sqrt(((pix - nearest) ** 2).sum(axis=1)))
    share = float((best <= _FLAT_ART_TOLERANCE).mean())
    return share >= _FLAT_ART_SHARE


# ------------------------------------------------------- fringe cleanup

# A layer is a fringe when nearly all of its pixels touch another layer
# (it has no interior) and it is a small share of the image.
_FRINGE_EDGE_RATIO = 0.75
_FRINGE_MAX_COVERAGE = 0.06


def _boundary(labels: np.ndarray) -> np.ndarray:
    edge = np.zeros(labels.shape, dtype=bool)
    edge[:, 1:] |= labels[:, 1:] != labels[:, :-1]
    edge[:, :-1] |= labels[:, :-1] != labels[:, 1:]
    edge[1:, :] |= labels[1:, :] != labels[:-1, :]
    edge[:-1, :] |= labels[:-1, :] != labels[1:, :]
    return edge


def fringe_layers(qimg: QuantizedImage) -> list[int]:
    """Palette indices whose pixels are almost all rim, never body."""
    labels = qimg.labels
    edge = _boundary(labels)
    fringes = []
    for i in range(len(qimg.palette)):
        layer = labels == i
        count = int(layer.sum())
        if count == 0 or qimg.coverage[i] > _FRINGE_MAX_COVERAGE:
            continue
        if float((edge & layer).sum()) / count >= _FRINGE_EDGE_RATIO:
            fringes.append(i)
    return fringes


def absorb_fringe_pixels(
    qimg: QuantizedImage, original: np.ndarray | None = None, max_passes: int = 4
) -> int:
    """Reassign fringe-layer pixels to a neighbouring non-fringe layer,
    so shapes meet edge to edge like a hand trace. With the original
    pixels, each rim pixel joins whichever neighbouring layer its colour
    is closer to, which puts the edge at the blend midpoint (a smooth
    contour); without, the most common neighbour wins.
    Returns the number of pixels reassigned."""
    fringes = fringe_layers(qimg)
    if not fringes:
        return 0
    labels = qimg.labels
    n = len(qimg.palette)
    pending = np.isin(labels, fringes)
    moved = 0
    for _ in range(max_passes):
        if not pending.any():
            break
        votes = np.zeros((n,) + labels.shape, dtype=np.int16)
        solid = (labels >= 0) & ~pending
        for dy, dx in ((0, 1), (0, -1), (1, 0), (-1, 0)):
            src = np.roll(labels, (dy, dx), axis=(0, 1))
            ok = np.roll(solid, (dy, dx), axis=(0, 1))
            if dy == 1:
                ok[0, :] = False
            elif dy == -1:
                ok[-1, :] = False
            if dx == 1:
                ok[:, 0] = False
            elif dx == -1:
                ok[:, -1] = False
            for i in range(n):
                votes[i] += (ok & (src == i)).astype(np.int16)
        has_vote = votes.max(axis=0) > 0
        take = pending & has_vote
        if original is not None:
            pal = np.asarray(qimg.palette, dtype=np.float32)
            pix = original.astype(np.float32)
            dist = np.stack(
                [np.abs(pix - pal[i]).sum(axis=2) for i in range(n)]
            )
            dist[votes == 0] = np.inf
            choice = dist.argmin(axis=0)
        else:
            choice = votes.argmax(axis=0)
        labels[take] = choice[take]
        pending &= ~take
        moved += int(take.sum())
    total = max(1, int((labels >= 0).sum()))
    qimg.coverage = [float((labels == i).sum()) / total for i in range(n)]
    return moved


def majority_smooth(labels: np.ndarray, n: int, passes: int) -> np.ndarray:
    """3x3 majority filter on a label map: each pixel takes the most
    common label in its neighbourhood when that label holds at least 5
    of the 9 cells. Straight runs and corners of real shapes survive;
    single-pixel notches and spurs along a noisy edge do not."""
    for _ in range(passes):
        padded = np.pad(labels, 1, mode="edge")
        h, w = labels.shape
        votes = np.zeros((n,) + labels.shape, dtype=np.int8)
        for dy in range(3):
            for dx in range(3):
                window = padded[dy:dy + h, dx:dx + w]
                for i in range(n):
                    votes[i] += window == i
        best = votes.argmax(axis=0)
        strong = votes.max(axis=0) >= 5
        labels = np.where(strong & (labels >= 0), best, labels)
    return labels


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


def smooth_staircase(points: list[Point], radius: int = 2, min_run: int = 3) -> list[Point]:
    """Average out pixel stair-steps on a unit-step boundary loop.

    Each vertex moves to the mean of its +-``radius`` neighbours, except
    genuine corners: a direction change where the straight runs on both
    sides are at least ``min_run`` px long. Diagonals and curves (short
    alternating runs) come out as smooth lines; square corners stay put.
    """
    n = len(points)
    if radius <= 0 or n < 2 * radius + 3:
        return points
    # Length of the straight run ending at / starting from each vertex.
    def direction(i: int) -> Point:
        a, b = points[i], points[(i + 1) % n]
        return (b[0] - a[0], b[1] - a[1])

    dirs = [direction(i) for i in range(n)]

    def run(start: int, step: int) -> int:
        # Straight-run length from dirs[start], walking by step (capped).
        k = 1
        while k < min_run and dirs[(start + k * step) % n] == dirs[start]:
            k += 1
        return k

    out: list[Point] = []
    for i in range(n):
        corner = dirs[i] != dirs[i - 1] and run(i - 1, -1) >= min_run and run(i, 1) >= min_run
        if corner:
            out.append(points[i])
            continue
        xs = ys = 0.0
        for k in range(-radius, radius + 1):
            px, py = points[(i + k) % n]
            xs += px
            ys += py
        m = 2 * radius + 1
        out.append((xs / m, ys / m))
    return out


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


def _clamped_handle(anchor: Point, offset: Point, limit: float) -> Point:
    length = math.hypot(offset[0], offset[1])
    if length > limit > 0:
        offset = (offset[0] * limit / length, offset[1] * limit / length)
    return (anchor[0] + offset[0], anchor[1] + offset[1])


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
        # Handles are clamped to a third of this segment: next to a much
        # longer neighbour an unclamped Catmull-Rom tangent overshoots
        # and leaves a spike past the segment's ends.
        seg = math.hypot(p2[0] - p1[0], p2[1] - p1[1])
        if corners[i]:
            c1 = (p1[0] + (p2[0] - p1[0]) / 3, p1[1] + (p2[1] - p1[1]) / 3)
        else:
            c1 = _clamped_handle(p1, ((p2[0] - p0[0]) / 6, (p2[1] - p0[1]) / 6), seg / 3)
        if corners[(i + 1) % n]:
            c2 = (p2[0] - (p2[0] - p1[0]) / 3, p2[1] - (p2[1] - p1[1]) / 3)
        else:
            c2 = _clamped_handle(p2, (-(p3[0] - p1[0]) / 6, -(p3[1] - p1[1]) / 6), seg / 3)
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
        if options.smooth and options.edge_smoothing > 0:
            loop = smooth_staircase(loop, options.edge_smoothing)
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
    doc_blockers: list[str] = []
    if options.hybrid:
        from designer.hybrid import extract_photo_regions, photo_coverage

        photo_regions, masked = extract_photo_regions(img, qimg.labels)
        coverage = photo_coverage(photo_regions, qimg.width, qimg.height)
        if coverage > options.max_photo_coverage and not options.force:
            raise ComplexityError(coverage, options.max_photo_coverage, photographic=True)
        if photo_regions:
            raw = np.asarray(img.convert("RGB"), dtype=np.uint8)
            flat_art = [r for r in photo_regions if _is_flat_artwork(qimg.labels, raw, r)]
            if flat_art:
                doc_blockers.append(
                    f"{len(flat_art)} region(s) of flat artwork (likely small or script "
                    "lettering) could not be traced cleanly and were embedded as raster; "
                    "the output is not a clean vector. Supply a higher-resolution source "
                    "or redraw that element"
                )
            qimg.labels = masked
            total = max(1, int((masked >= 0).sum()))
            qimg.coverage = [
                float((masked == i).sum()) / total for i in range(len(qimg.palette))
            ]

    # Edge cleanup runs after photo detection (which reads the raw
    # label noise) and only touches the flat-art pixels left to trace.
    if options.absorb_fringes:
        absorb_fringe_pixels(qimg, np.asarray(img.convert("RGB"), dtype=np.uint8))
    if options.denoise_passes > 0:
        qimg.labels = majority_smooth(qimg.labels, len(qimg.palette), options.denoise_passes)
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
    doc.blockers.extend(doc_blockers)

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
