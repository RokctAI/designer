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

"""Raster analysis: load an image, reduce it to flat color layers.

AI image generators output noisy, banded rasters. This module reduces
them to a small set of flat colors (adaptive median-cut + perceptual
merge in OKLab) producing a label map the vectorizer can trace.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image

from designer.color import RGB, delta_e

# Palette entries closer than this (OKLab) are the same color banded by
# the generator — merge them.
MERGE_DISTANCE = 0.04

# Alpha below this is treated as "not part of the artwork".
ALPHA_THRESHOLD = 128


@dataclass
class QuantizedImage:
    """A raster reduced to flat color layers."""

    width: int
    height: int
    palette: list[RGB]  # index -> color
    labels: np.ndarray  # (h, w) int array of palette indices, -1 = transparent
    coverage: list[float]  # fraction of opaque pixels per palette entry

    def layer_mask(self, index: int) -> np.ndarray:
        return self.labels == index


def load_image(path: str | Path, max_dim: int | None = 1024) -> Image.Image:
    """Load an image, optionally downscaling so max(w, h) <= max_dim.

    Downscaling both denoises generator output and keeps pure-Python
    tracing fast; the SVG viewBox keeps everything resolution-independent.
    """
    img = Image.open(str(path)).convert("RGBA")
    if max_dim and max(img.size) > max_dim:
        scale = max_dim / max(img.size)
        new_size = (max(1, round(img.width * scale)), max(1, round(img.height * scale)))
        img = img.resize(new_size, Image.LANCZOS)
    return img


def quantize(img: Image.Image, n_colors: int = 6) -> QuantizedImage:
    """Reduce an image to at most ``n_colors`` flat layers."""
    if img.mode != "RGBA":
        img = img.convert("RGBA")
    rgba = np.asarray(img, dtype=np.uint8)
    alpha = rgba[..., 3]
    opaque = alpha >= ALPHA_THRESHOLD

    # Over-quantize first (median-cut spends entries splitting noisy
    # dominant colors, which would starve small-but-distinct regions),
    # then merge perceptually until we're within budget. K-means
    # refinement tightens cluster centers against generator noise.
    rgb_img = img.convert("RGB")
    overshoot = min(64, max(2, n_colors) * 4)
    quantized = rgb_img.quantize(colors=overshoot, method=Image.MEDIANCUT, kmeans=overshoot)
    labels = np.asarray(quantized, dtype=np.int32)
    raw_palette = quantized.getpalette()
    palette: list[RGB] = [
        tuple(raw_palette[i * 3 : i * 3 + 3]) for i in range(int(labels.max()) + 1)
    ]

    # Merge perceptually identical palette entries (generator banding),
    # then keep merging the least-distinct pair until within budget.
    remap = _merge_palette(palette, labels)
    palette = remap["palette"]
    labels = remap["labels"]
    palette, labels = _reduce_to_n(palette, labels, max(2, n_colors))

    labels = np.where(opaque, labels, -1)

    total_opaque = max(int(opaque.sum()), 1)
    coverage = [
        float((labels == i).sum()) / total_opaque for i in range(len(palette))
    ]

    # Drop empty entries (can appear after masking transparency).
    keep = [i for i, c in enumerate(coverage) if c > 0]
    index_map = {old: new for new, old in enumerate(keep)}
    new_labels = np.full_like(labels, -1)
    for old, new in index_map.items():
        new_labels[labels == old] = new

    return QuantizedImage(
        width=img.width,
        height=img.height,
        palette=[palette[i] for i in keep],
        labels=new_labels,
        coverage=[coverage[i] for i in keep],
    )


def _merge_palette(palette: list[RGB], labels: np.ndarray) -> dict:
    """Union perceptually-near palette entries; larger entry wins."""
    counts = np.bincount(labels.flatten(), minlength=len(palette))
    order = np.argsort(-counts)  # biggest first
    canonical: list[int] = []
    mapping: dict[int, int] = {}
    for idx in order:
        idx = int(idx)
        if counts[idx] == 0:
            # Unused entry: fold into the largest canonical color (order
            # is biggest-first, so canonical[0] always exists here).
            mapping[idx] = canonical[0] if canonical else idx
            if not canonical:
                canonical.append(idx)
            continue
        for c in canonical:
            if delta_e(palette[idx], palette[c]) < MERGE_DISTANCE:
                mapping[idx] = c
                break
        else:
            canonical.append(idx)
            mapping[idx] = idx

    new_palette = [palette[c] for c in canonical]
    canon_pos = {c: i for i, c in enumerate(canonical)}
    lut = np.array([canon_pos[mapping[i]] for i in range(len(palette))], dtype=np.int32)
    return {"palette": new_palette, "labels": lut[labels]}


def _reduce_to_n(
    palette: list[RGB], labels: np.ndarray, n: int
) -> tuple[list[RGB], np.ndarray]:
    """Merge the perceptually closest pair of palette entries until at
    most ``n`` remain. Keeping merges pairwise-closest (rather than
    dropping the smallest entry) preserves small accent regions whose
    color is genuinely distinct."""
    palette = list(palette)
    labels = labels.copy()
    while len(palette) > n:
        best: tuple[int, int] | None = None
        best_d = float("inf")
        for i in range(len(palette)):
            for j in range(i + 1, len(palette)):
                d = delta_e(palette[i], palette[j])
                if d < best_d:
                    best_d, best = d, (i, j)
        assert best is not None
        i, j = best
        counts = np.bincount(labels.flatten(), minlength=len(palette))
        # The bigger entry keeps its color; the smaller folds into it.
        keep, fold = (i, j) if counts[i] >= counts[j] else (j, i)
        labels[labels == fold] = keep
        lut = np.array(
            [k - (1 if k > fold else 0) for k in range(len(palette))], dtype=np.int32
        )
        labels = lut[labels]
        palette.pop(fold)
    return palette, labels


def palette_report(qimg: QuantizedImage) -> list[tuple[RGB, float]]:
    """(color, coverage) pairs, largest coverage first."""
    pairs = list(zip(qimg.palette, qimg.coverage))
    pairs.sort(key=lambda p: -p[1])
    return pairs
