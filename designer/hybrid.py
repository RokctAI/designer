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

"""Hybrid raster/vector: keep photographs as photographs.

Tracing a photograph produces megabytes of meaningless micro-paths. But
refusing every image containing a photo is equally wrong, because a real
poster is usually flat graphics *around* a photographic element. This
module finds the photographic regions, hands them back as embedded
rasters, and lets the vectorizer trace only the flat artwork — which is
what a designer would do by hand.

Detection is local edge density: photographic and textured areas produce
many color transitions per pixel, flat design areas produce few.
"""

from __future__ import annotations

import base64
import io
from dataclasses import dataclass

import numpy as np
from PIL import Image


@dataclass
class PhotoRegion:
    """A rectangle to embed as a raster instead of tracing."""

    x: int
    y: int
    width: int
    height: int
    href: str  # data URI

    @property
    def area(self) -> int:
        return self.width * self.height


@dataclass
class HybridOptions:
    tile: int = 32              # analysis tile size in px
    tile_density: float = 0.35  # transitions/px above which a tile is photographic
    min_region_tiles: int = 4   # ignore isolated noisy tiles
    pad: int = 2                # px of bleed around an embedded region


def photographic_tiles(labels: np.ndarray, options: HybridOptions) -> np.ndarray:
    """Boolean grid marking tiles whose local detail is photographic."""
    h, w = labels.shape
    tile = options.tile
    rows, cols = -(-h // tile), -(-w // tile)
    grid = np.zeros((rows, cols), dtype=bool)
    for r in range(rows):
        for c in range(cols):
            block = labels[r * tile : (r + 1) * tile, c * tile : (c + 1) * tile]
            if block.size < 16:
                continue
            transitions = int((block[:, 1:] != block[:, :-1]).sum()) + int(
                (block[1:, :] != block[:-1, :]).sum()
            )
            grid[r, c] = transitions / block.size > options.tile_density
    return grid


def _components(grid: np.ndarray) -> list[list[tuple[int, int]]]:
    """4-connected components of True tiles."""
    seen = np.zeros_like(grid, dtype=bool)
    out: list[list[tuple[int, int]]] = []
    rows, cols = grid.shape
    for r in range(rows):
        for c in range(cols):
            if not grid[r, c] or seen[r, c]:
                continue
            stack = [(r, c)]
            seen[r, c] = True
            group = []
            while stack:
                cr, cc = stack.pop()
                group.append((cr, cc))
                for dr, dc in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                    nr, nc = cr + dr, cc + dc
                    if 0 <= nr < rows and 0 <= nc < cols and grid[nr, nc] and not seen[nr, nc]:
                        seen[nr, nc] = True
                        stack.append((nr, nc))
            out.append(group)
    return out


def extract_photo_regions(
    img: Image.Image, labels: np.ndarray, options: HybridOptions | None = None
) -> tuple[list[PhotoRegion], np.ndarray]:
    """Find photographic regions.

    Returns the regions (with their pixels encoded as PNG data URIs) and
    a copy of ``labels`` with those pixels masked out (-1) so the
    vectorizer skips them.
    """
    options = options or HybridOptions()
    grid = photographic_tiles(labels, options)
    if not grid.any():
        return [], labels

    tile = options.tile
    h, w = labels.shape
    regions: list[PhotoRegion] = []
    masked = labels.copy()

    for group in _components(grid):
        if len(group) < options.min_region_tiles:
            continue
        rows = [g[0] for g in group]
        cols = [g[1] for g in group]
        x0 = max(0, min(cols) * tile - options.pad)
        y0 = max(0, min(rows) * tile - options.pad)
        x1 = min(w, (max(cols) + 1) * tile + options.pad)
        y1 = min(h, (max(rows) + 1) * tile + options.pad)
        if x1 <= x0 or y1 <= y0:
            continue
        crop = img.convert("RGB").crop((x0, y0, x1, y1))
        buffer = io.BytesIO()
        crop.save(buffer, format="PNG", optimize=True)
        href = "data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode("ascii")
        regions.append(
            PhotoRegion(x=x0, y=y0, width=x1 - x0, height=y1 - y0, href=href)
        )
        masked[y0:y1, x0:x1] = -1

    return regions, masked


def photo_coverage(regions: list[PhotoRegion], width: int, height: int) -> float:
    if width <= 0 or height <= 0:
        return 0.0
    return min(1.0, sum(r.area for r in regions) / float(width * height))
