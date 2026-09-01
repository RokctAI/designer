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

import numpy as np

from designer.vectorize import (
    VectorizeOptions,
    collapse_collinear,
    douglas_peucker,
    simplify_loop,
    trace_mask,
    vectorize_quantized,
)
from designer.raster import QuantizedImage


def square_mask(size=10, lo=2, hi=8):
    mask = np.zeros((size, size), dtype=bool)
    mask[lo:hi, lo:hi] = True
    return mask


def test_trace_square_single_loop():
    loops = trace_mask(square_mask())
    assert len(loops) == 1
    corners = set(collapse_collinear(loops[0]))
    assert corners == {(2, 2), (8, 2), (8, 8), (2, 8)}


def test_trace_square_with_hole():
    mask = square_mask(12, 2, 10)
    mask[5:7, 5:7] = False
    loops = trace_mask(mask)
    assert len(loops) == 2
    sizes = sorted(len(collapse_collinear(l)) for l in loops)
    assert sizes == [4, 4]


def test_trace_diagonal_touch_two_loops():
    # Two pixels touching only at a corner must stay separate loops.
    mask = np.zeros((4, 4), dtype=bool)
    mask[1, 1] = True
    mask[2, 2] = True
    loops = trace_mask(mask)
    assert len(loops) == 2


def test_edge_conservation():
    # Every boundary edge is used exactly once: total loop points ==
    # total boundary edge count.
    mask = square_mask(12, 2, 10)
    mask[4:6, 4:8] = False
    loops = trace_mask(mask)
    total_pts = sum(len(l) for l in loops)
    padded = np.pad(mask, 1)
    edge_count = int(
        (mask & ~padded[:-2, 1:-1]).sum()
        + (mask & ~padded[2:, 1:-1]).sum()
        + (mask & ~padded[1:-1, :-2]).sum()
        + (mask & ~padded[1:-1, 2:]).sum()
    )
    assert total_pts == edge_count


def test_douglas_peucker_reduces_points():
    pts = [(float(x), 0.1 * (x % 2)) for x in range(20)]
    out = douglas_peucker(pts, epsilon=0.5)
    assert len(out) == 2  # jitter below tolerance collapses to a segment


def test_simplify_loop_keeps_square():
    loops = trace_mask(square_mask())
    pts = simplify_loop(loops[0], epsilon=1.0)
    assert len(pts) == 4


def test_vectorize_quantized_layers():
    labels = np.zeros((16, 16), dtype=np.int32)
    labels[4:12, 4:12] = 1
    total = 16 * 16
    qimg = QuantizedImage(
        width=16,
        height=16,
        palette=[(255, 255, 255), (26, 86, 219)],
        labels=labels,
        coverage=[(total - 64) / total, 64 / total],
    )
    doc = vectorize_quantized(qimg, VectorizeOptions(smooth=False))
    assert doc.width == 16 and doc.height == 16
    tags = [s.tag for s in doc.shapes]
    assert tags[0] == "rect"  # dominant layer becomes background rect
    assert "path" in tags
    path = next(s for s in doc.shapes if s.tag == "path")
    assert path.fill == "#1a56db"
    assert path.attrs["d"].startswith("M") and path.attrs["d"].endswith("Z")
