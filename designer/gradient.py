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

"""Gradient reconstruction: detect banded gradients in quantized layers
and rebuild them as real SVG gradients.

Generators output smooth gradients; quantization turns them into stacks
of adjacent color bands. Instead of emitting those bands as posterized
flat paths, this module finds chains of adjacent layers whose colors
progress along a line in OKLab space, decides whether the chain is
linear or radial from the bands' spatial arrangement, and produces one
merged shape filled with a fitted SVG gradient whose stops can then be
token-snapped by the compliance rules.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

from designer.color import RGB, rgb_to_oklab
from designer.raster import QuantizedImage


@dataclass
class GradientCandidate:
    """A detected gradient: which layers it consumes and how to draw it."""

    layer_indices: list[int]
    kind: str  # "linear" | "radial"
    stops: list[tuple[float, RGB]] = field(default_factory=list)
    coords: dict[str, float] = field(default_factory=dict)
    coverage: float = 0.0


@dataclass
class GradientOptions:
    min_bands: int = 3          # fewer adjacent bands is just an edge halo
    max_color_step: float = 0.16  # OKLab distance between neighbouring bands
    line_tolerance: float = 0.05  # max OKLab residual from the fitted color line
    min_band_coverage: float = 0.01  # bands thinner than this are AA halos, not gradients
    min_total_coverage: float = 0.04  # ignore tiny gradient patches
    # A real gradient spans a visible color range end to end; noisy
    # splits of one flat color do not.
    min_color_span: float = 0.08
    # Smoothness: the lightness jump measured right at a band boundary
    # must stay below this fraction of the bands' lightness step, else
    # the bands are flat blocks (true gradients measure ~0.05; hard
    # stripes ~0.5-1.0 even after quantization merges neighbours).
    max_boundary_jump: float = 0.3
    radial_center_spread: float = 0.2  # centroid spread / extent below which it's radial


def detect_gradients(
    qimg: QuantizedImage,
    options: GradientOptions | None = None,
    original: np.ndarray | None = None,
) -> list[GradientCandidate]:
    """``original`` is the (h, w, 3) uint8 RGB image before
    quantization. When provided, candidate chains must also pass a
    smoothness test: a true gradient varies continuously across band
    boundaries, while deliberate flat color-blocking jumps — so flat
    stripe layouts are not fused into fake gradients."""
    options = options or GradientOptions()
    n = len(qimg.palette)
    if n < options.min_bands:
        return []

    adjacency = _adjacency(qimg.labels, n)
    labs = [np.array(rgb_to_oklab(c)) for c in qimg.palette]

    # Candidate edges: touching layers, perceptually close, both thick
    # enough to be genuine gradient bands.
    edges: dict[int, set[int]] = {i: set() for i in range(n)}
    for i, j in adjacency:
        if qimg.coverage[i] < options.min_band_coverage:
            continue
        if qimg.coverage[j] < options.min_band_coverage:
            continue
        if float(np.linalg.norm(labs[i] - labs[j])) <= options.max_color_step:
            edges[i].add(j)
            edges[j].add(i)

    candidates: list[GradientCandidate] = []
    used: set[int] = set()
    for component in _components(edges):
        members = [v for v in component if v not in used]
        if len(members) < options.min_bands:
            continue
        chain = _order_by_color(members, labs, adjacency, options)
        if chain is None:
            continue
        if original is not None and not _is_smooth(
            chain, qimg.labels, original, labs, options.max_boundary_jump
        ):
            continue
        cand = _fit(chain, qimg, options)
        if cand is None:
            continue
        if cand.coverage < options.min_total_coverage:
            continue
        used.update(chain)
        candidates.append(cand)
    return candidates


# ------------------------------------------------------------- topology


def _adjacency(labels: np.ndarray, n: int) -> set[tuple[int, int]]:
    pairs: set[tuple[int, int]] = set()
    for a, b in (
        (labels[:, :-1], labels[:, 1:]),
        (labels[:-1, :], labels[1:, :]),
    ):
        mask = (a != b) & (a >= 0) & (b >= 0)
        if not mask.any():
            continue
        stacked = np.stack([a[mask], b[mask]])
        uniq, counts = np.unique(stacked, axis=1, return_counts=True)
        for (i, j), count in zip(uniq.T.tolist(), counts.tolist()):
            if count >= 8:  # require a real shared border, not corner touches
                pairs.add((min(i, j), max(i, j)))
    return pairs


def _components(edges: dict[int, set[int]]) -> list[set[int]]:
    components: list[set[int]] = []
    visited: set[int] = set()
    for start in edges:
        if start in visited or not edges[start]:
            continue
        seen = {start}
        stack = [start]
        while stack:
            for v in edges[stack.pop()]:
                if v not in seen:
                    seen.add(v)
                    stack.append(v)
        visited.update(seen)
        components.append(seen)
    return components


def _order_by_color(
    members: list[int],
    labs: list[np.ndarray],
    adjacency: set[tuple[int, int]],
    options: GradientOptions,
) -> list[int] | None:
    """Order a component's bands into a color ramp, or reject it.

    Quantized gradient bands interleave noisily, so the touch graph is
    not a clean path. The color axis is: take the two most-distant band
    colors, project everything onto that line. It's a genuine gradient
    if every band sits near the line (collinear ramp) and consecutive
    bands in ramp order actually touch spatially."""
    a_idx, b_idx = max(
        ((i, j) for i in members for j in members if i < j),
        key=lambda p: float(np.linalg.norm(labs[p[0]] - labs[p[1]])),
    )
    axis = labs[b_idx] - labs[a_idx]
    span = float(np.linalg.norm(axis))
    if span < options.min_color_span:
        return None
    axis = axis / span

    # Curvature allowance: sRGB-interpolated ramps bow slightly in
    # OKLab, so tolerance scales with the ramp's length.
    tol = max(options.line_tolerance, 0.18 * span)
    ordered = []
    for idx in members:
        v = labs[idx] - labs[a_idx]
        t = float(v @ axis)
        if float(np.linalg.norm(v - t * axis)) > tol:
            return None
        ordered.append((t, idx))
    ordered.sort()
    chain = [idx for _, idx in ordered]

    for i, j in zip(chain, chain[1:]):
        if (min(i, j), max(i, j)) not in adjacency:
            return None
    return chain


_LINEAR_LUT = None


def _oklab_l_map(rgb: np.ndarray) -> np.ndarray:
    """Vectorized OKLab lightness for an (h, w, 3) uint8 array."""
    global _LINEAR_LUT
    if _LINEAR_LUT is None:
        c = np.arange(256) / 255.0
        _LINEAR_LUT = np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)
    lin = _LINEAR_LUT[rgb]
    r, g, b = lin[..., 0], lin[..., 1], lin[..., 2]
    l = np.cbrt(0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b)
    m = np.cbrt(0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b)
    s = np.cbrt(0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b)
    return 0.2104542553 * l + 0.7936177850 * m - 0.0040720468 * s


def _is_smooth(
    chain: list[int],
    labels: np.ndarray,
    original: np.ndarray,
    labs: list[np.ndarray],
    max_jump_ratio: float = 0.3,
) -> bool:
    """True gradients vary continuously: the lightness difference right
    at a band boundary is tiny compared to the bands' mean color step.
    Flat color blocks jump the full step at the boundary."""
    L = _oklab_l_map(original)
    ratios = []
    for a, b in zip(chain, chain[1:]):
        # Compare each boundary's lightness jump against the two bands'
        # own lightness step; hue-only pairs carry no signal to test.
        step_l = abs(float(labs[a][0]) - float(labs[b][0]))
        if step_l < 0.005:
            continue
        pair_jumps = []
        for la, lb, La, Lb in (
            (labels[:, :-1], labels[:, 1:], L[:, :-1], L[:, 1:]),
            (labels[:-1, :], labels[1:, :], L[:-1, :], L[1:, :]),
        ):
            mask = ((la == a) & (lb == b)) | ((la == b) & (lb == a))
            if mask.any():
                pair_jumps.append(float(np.abs(La[mask] - Lb[mask]).mean()))
        if pair_jumps:
            ratios.append(float(np.mean(pair_jumps)) / step_l)
    if not ratios:
        return True
    return float(np.mean(ratios)) < max_jump_ratio


# -------------------------------------------------------------- fitting


def _fit(
    chain: list[int], qimg: QuantizedImage, options: GradientOptions
) -> GradientCandidate | None:
    centroids = []
    for idx in chain:
        ys, xs = np.nonzero(qimg.labels == idx)
        if len(xs) == 0:
            return None
        centroids.append((float(xs.mean()), float(ys.mean())))
    union = np.isin(qimg.labels, chain)
    ys, xs = np.nonzero(union)
    coverage = float(union.sum()) / (qimg.width * qimg.height)

    extent = max(xs.max() - xs.min(), ys.max() - ys.min(), 1)
    cx = sum(c[0] for c in centroids) / len(centroids)
    cy = sum(c[1] for c in centroids) / len(centroids)
    spread = max(math.hypot(c[0] - cx, c[1] - cy) for c in centroids)

    if spread / extent < options.radial_center_spread:
        return _fit_radial(chain, qimg, centroids, xs, ys, coverage)
    return _fit_linear(chain, qimg, centroids, xs, ys, coverage)


def _fit_linear(
    chain: list[int],
    qimg: QuantizedImage,
    centroids: list[tuple[float, float]],
    xs: np.ndarray,
    ys: np.ndarray,
    coverage: float,
) -> GradientCandidate | None:
    x0, y0 = centroids[0]
    x1, y1 = centroids[-1]
    ux, uy = x1 - x0, y1 - y0
    norm = math.hypot(ux, uy)
    if norm < 1e-6:
        return None
    ux, uy = ux / norm, uy / norm

    proj = xs * ux + ys * uy
    pmin, pmax = float(proj.min()), float(proj.max())
    if pmax - pmin < 1e-6:
        return None

    # Anchor the axis line through the union centroid.
    mx, my = float(xs.mean()), float(ys.mean())
    mproj = mx * ux + my * uy
    start = (mx + (pmin - mproj) * ux, my + (pmin - mproj) * uy)
    end = (mx + (pmax - mproj) * ux, my + (pmax - mproj) * uy)

    stops: list[tuple[float, RGB]] = []
    for idx, (bx, by) in zip(chain, centroids):
        t = (bx * ux + by * uy - pmin) / (pmax - pmin)
        stops.append((min(1.0, max(0.0, t)), qimg.palette[idx]))
    stops.sort(key=lambda s: s[0])
    stops[0] = (0.0, stops[0][1])
    stops[-1] = (1.0, stops[-1][1])

    return GradientCandidate(
        layer_indices=list(chain),
        kind="linear",
        stops=stops,
        coords={"x1": start[0], "y1": start[1], "x2": end[0], "y2": end[1]},
        coverage=coverage,
    )


def _fit_radial(
    chain: list[int],
    qimg: QuantizedImage,
    centroids: list[tuple[float, float]],
    xs: np.ndarray,
    ys: np.ndarray,
    coverage: float,
) -> GradientCandidate | None:
    # Innermost band = smallest spatial extent; it holds the center.
    extents = []
    for idx in chain:
        bys, bxs = np.nonzero(qimg.labels == idx)
        extents.append(max(bxs.max() - bxs.min(), bys.max() - bys.min()))
    inner_pos = int(np.argmin(extents))
    cx, cy = centroids[inner_pos]

    radius = float(np.hypot(xs - cx, ys - cy).max())
    if radius < 1e-6:
        return None

    # Order stops from the inner band outward.
    ordered = chain if inner_pos == 0 else list(reversed(chain))
    stops: list[tuple[float, RGB]] = []
    for idx in ordered:
        bys, bxs = np.nonzero(qimg.labels == idx)
        t = float(np.hypot(bxs - cx, bys - cy).mean()) / radius
        stops.append((min(1.0, max(0.0, t)), qimg.palette[idx]))
    stops.sort(key=lambda s: s[0])
    stops[0] = (0.0, stops[0][1])
    stops[-1] = (1.0, stops[-1][1])

    return GradientCandidate(
        layer_indices=list(chain),
        kind="radial",
        stops=stops,
        coords={"cx": cx, "cy": cy, "r": radius},
        coverage=coverage,
    )
