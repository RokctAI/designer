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

"""Affine transforms: parse SVG transform lists and bake them into
geometry.

Previously transforms were carried along as opaque strings and merely
flagged, so every geometry rule (grid, margins, overlap) reasoned about
coordinates that were not where the shape actually rendered. Baking
turns third-party SVG into the same flat coordinate space the engine
emits, which is what makes auditing other people's files meaningful.

Matrices are (a, b, c, d, e, f) in SVG order:
    x' = a·x + c·y + e
    y' = b·x + d·y + f
"""

from __future__ import annotations

import math
import re

Matrix = tuple[float, float, float, float, float, float]

IDENTITY: Matrix = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)

_FUNC_RE = re.compile(r"([a-zA-Z]+)\s*\(([^)]*)\)")
_NUM_RE = re.compile(r"[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?")


class UnsupportedTransform(ValueError):
    """The transform list contains something we will not silently
    approximate (e.g. an unknown function)."""


def parse_transform(value: str | None) -> Matrix:
    """Parse an SVG transform list into a single matrix. Functions apply
    left-to-right, so the leftmost is outermost."""
    if not value or not value.strip():
        return IDENTITY
    result = IDENTITY
    consumed = 0
    for match in _FUNC_RE.finditer(value):
        consumed += len(match.group(0))
        name = match.group(1).lower()
        args = [float(n) for n in _NUM_RE.findall(match.group(2))]
        result = multiply(result, _function_matrix(name, args))
    # Anything left over (other than separators) means we misread it.
    leftover = _FUNC_RE.sub("", value).strip(" ,\t\n\r")
    if leftover:
        raise UnsupportedTransform(f"unparsed transform content: {leftover!r}")
    return result


def _function_matrix(name: str, args: list[float]) -> Matrix:
    if name == "matrix" and len(args) == 6:
        return (args[0], args[1], args[2], args[3], args[4], args[5])
    if name == "translate" and len(args) in (1, 2):
        tx = args[0]
        ty = args[1] if len(args) > 1 else 0.0
        return (1.0, 0.0, 0.0, 1.0, tx, ty)
    if name == "scale" and len(args) in (1, 2):
        sx = args[0]
        sy = args[1] if len(args) > 1 else args[0]
        return (sx, 0.0, 0.0, sy, 0.0, 0.0)
    if name == "rotate" and len(args) in (1, 3):
        angle = math.radians(args[0])
        cos_a, sin_a = math.cos(angle), math.sin(angle)
        rot: Matrix = (cos_a, sin_a, -sin_a, cos_a, 0.0, 0.0)
        if len(args) == 3:
            cx, cy = args[1], args[2]
            return multiply(
                multiply((1.0, 0.0, 0.0, 1.0, cx, cy), rot),
                (1.0, 0.0, 0.0, 1.0, -cx, -cy),
            )
        return rot
    if name == "skewx" and len(args) == 1:
        return (1.0, 0.0, math.tan(math.radians(args[0])), 1.0, 0.0, 0.0)
    if name == "skewy" and len(args) == 1:
        return (1.0, math.tan(math.radians(args[0])), 0.0, 1.0, 0.0, 0.0)
    raise UnsupportedTransform(f"unsupported transform function {name}({args})")


def multiply(m1: Matrix, m2: Matrix) -> Matrix:
    a1, b1, c1, d1, e1, f1 = m1
    a2, b2, c2, d2, e2, f2 = m2
    return (
        a1 * a2 + c1 * b2,
        b1 * a2 + d1 * b2,
        a1 * c2 + c1 * d2,
        b1 * c2 + d1 * d2,
        a1 * e2 + c1 * f2 + e1,
        b1 * e2 + d1 * f2 + f1,
    )


def apply(m: Matrix, x: float, y: float) -> tuple[float, float]:
    a, b, c, d, e, f = m
    return (a * x + c * y + e, b * x + d * y + f)


def is_identity(m: Matrix, tol: float = 1e-9) -> bool:
    return all(abs(v - i) <= tol for v, i in zip(m, IDENTITY))


def is_axis_aligned(m: Matrix, tol: float = 1e-6) -> bool:
    """True when the matrix has no rotation or skew, so axis-aligned
    primitives (rect, circle, text) stay axis-aligned under it."""
    _, b, c, _, _, _ = m
    return abs(b) <= tol and abs(c) <= tol


def is_uniform_scale(m: Matrix, tol: float = 1e-6) -> bool:
    a, b, c, d, _, _ = m
    sx = math.hypot(a, b)
    sy = math.hypot(c, d)
    return abs(sx - sy) <= tol * max(1.0, sx)


def scale_factor(m: Matrix) -> float:
    """Average linear scale — used for lengths (stroke width, radii,
    font size) under a uniform or near-uniform matrix."""
    a, b, c, d, _, _ = m
    return (math.hypot(a, b) + math.hypot(c, d)) / 2.0


def decompose_rotation(m: Matrix) -> float:
    """Rotation in degrees (0 for axis-aligned matrices)."""
    a, b, _, _, _, _ = m
    return math.degrees(math.atan2(b, a))
