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

"""Geometric transforms over a Document: uniform scale + translate.

Used by the format rules to rescale artwork onto a target canvas.
Everything the engine emits (and the common subset of hand-authored
SVG) is handled: primitive attributes, path data, gradient defs.
"""

from __future__ import annotations

import re

from designer.svg import Document, Shape

_X_ATTRS = ("x", "cx", "x1", "x2")
_Y_ATTRS = ("y", "cy", "y1", "y2")
_LEN_ATTRS = ("width", "height", "r", "rx", "ry", "font-size", "stroke-width")

from designer.matrix import (
    Matrix,
    apply,
    is_axis_aligned,
    is_identity,
    is_uniform_scale,
    scale_factor,
)
from designer.path import PARAM_COUNTS, parse_path, serialize_path

_NUM_RE = re.compile(r"-?\d+(?:\.\d+)?(?:e-?\d+)?", re.IGNORECASE)

# Per command letter: how each parameter transforms.
# "x"/"y" = position (translate only when absolute), "l" = length-only,
# "raw" = untouched (arc rotation and flags).
_CMD_PARAMS = {
    "M": ["x", "y"],
    "L": ["x", "y"],
    "T": ["x", "y"],
    "H": ["x"],
    "V": ["y"],
    "C": ["x", "y", "x", "y", "x", "y"],
    "S": ["x", "y", "x", "y"],
    "Q": ["x", "y", "x", "y"],
    "A": ["l", "l", "raw", "raw", "raw", "x", "y"],
    "Z": [],
}


def _fmt(v: float) -> str:
    return f"{v:.2f}".rstrip("0").rstrip(".") or "0"


def transform_path(d: str, s: float, tx: float, ty: float) -> str:
    """Apply uniform scale + translate to path data, using the real
    path grammar (fused arc flags and compact decimals decode
    correctly). Relative commands scale but don't translate. Malformed
    data raises ValueError — callers must not ship a half-transformed
    guess."""
    cmds = parse_path(d)
    out = []
    for cmd, params in cmds:
        kinds = _CMD_PARAMS[cmd.upper()]
        absolute = cmd.isupper()
        new_params = []
        for kind, value in zip(kinds, params):
            if kind == "raw":
                new_params.append(value)
                continue
            scaled = value * s
            if absolute:
                if kind == "x":
                    scaled += tx
                elif kind == "y":
                    scaled += ty
            new_params.append(scaled)
        out.append((cmd, new_params))
    return serialize_path(out)


def _transform_shape(shape: Shape, s: float, tx: float, ty: float) -> bool:
    """Returns False when part of the shape could not be transformed."""
    for attr in _X_ATTRS:
        v = shape.numeric(attr)
        if v is not None:
            shape.set(attr, _fmt(v * s + tx))
    for attr in _Y_ATTRS:
        v = shape.numeric(attr)
        if v is not None:
            shape.set(attr, _fmt(v * s + ty))
    for attr in _LEN_ATTRS:
        v = shape.numeric(attr)
        if v is not None:
            shape.set(attr, _fmt(v * s))
    if shape.tag == "path" and shape.attrs.get("d"):
        try:
            shape.attrs["d"] = transform_path(shape.attrs["d"], s, tx, ty)
        except ValueError:
            # Never ship a half-transformed guess; leave the path where
            # it was and let the caller surface the mismatch.
            return False
    if shape.tag in ("polygon", "polyline") and shape.attrs.get("points"):
        nums = [float(n) for n in _NUM_RE.findall(shape.attrs["points"])]
        pts = [
            _fmt(n * s + (tx if i % 2 == 0 else ty))
            for i, n in enumerate(nums)
        ]
        shape.attrs["points"] = " ".join(
            f"{pts[i]},{pts[i + 1]}" for i in range(0, len(pts) - 1, 2)
        )
    return True


def affine_document(doc: Document, s: float, tx: float, ty: float) -> None:
    """Scale the whole document by ``s`` then translate by (tx, ty),
    in place. Canvas size is NOT changed — callers set doc.width/height
    to the target themselves. Shapes whose geometry cannot be safely
    transformed are left untouched and recorded in doc.warnings."""
    for i, shape in enumerate(doc.shapes):
        if not _transform_shape(shape, s, tx, ty):
            doc.warnings.append(
                f"shape {i} (<{shape.tag}>) has path data this engine could not "
                "transform; it was left at its original scale/position"
            )
    for grad in doc.defs:
        for key in list(grad.coords):
            v = grad.coords[key]
            if key in ("x1", "x2", "cx"):
                grad.coords[key] = v * s + tx
            elif key in ("y1", "y2", "cy"):
                grad.coords[key] = v * s + ty
            else:  # r and any other length
                grad.coords[key] = v * s


# --------------------------------------------------- general affine baking

_LENGTH_ATTRS = ("stroke-width", "font-size")


def transform_path_matrix(d: str, m: Matrix) -> str:
    """Apply an arbitrary affine matrix to path data.

    Affine maps take Beziers to Beziers, so control points transform
    directly. H/V become L under rotation/skew. Elliptical arcs are only
    exact under an axis-aligned uniform matrix; otherwise this raises so
    the caller keeps the transform attribute instead of distorting the
    curve.
    """
    cmds = parse_path(d)
    linear: Matrix = (m[0], m[1], m[2], m[3], 0.0, 0.0)
    axis_uniform = is_axis_aligned(m) and is_uniform_scale(m)
    out: list[tuple[str, list[float]]] = []

    for cmd, params in cmds:
        upper = cmd.upper()
        absolute = cmd.isupper()
        mat = m if absolute else linear

        if upper == "Z":
            out.append((cmd, []))
            continue
        if upper == "A":
            if not axis_uniform:
                raise ValueError("elliptical arc under a rotated/skewed matrix")
            rx, ry, rot, large, sweep, x, y = params
            s = scale_factor(m)
            nx, ny = apply(mat, x, y)
            out.append((cmd, [rx * s, ry * s, rot, large, sweep, nx, ny]))
            continue
        if upper in ("H", "V"):
            if is_axis_aligned(m):
                if upper == "H":
                    nx, _ = apply(mat, params[0], 0.0)
                    out.append((cmd, [nx]))
                else:
                    _, ny = apply(mat, 0.0, params[0])
                    out.append((cmd, [ny]))
                continue
            # Rotation turns a horizontal/vertical run into a diagonal.
            raise ValueError("H/V command under a rotated matrix needs path rewriting")

        coords = []
        for i in range(0, len(params), 2):
            nx, ny = apply(mat, params[i], params[i + 1])
            coords.extend([nx, ny])
        out.append((cmd, coords))
    return serialize_path(out)


def bake_shape(shape: Shape, m: Matrix) -> bool:
    """Bake an affine matrix into a shape's geometry, in place.

    Returns False when the shape cannot be represented in the target
    space without distortion (e.g. a rotated <rect>); the caller must
    then keep the transform attribute so rendering stays correct.
    """
    if is_identity(m):
        return True

    axis = is_axis_aligned(m)
    uniform = is_uniform_scale(m)
    factor = scale_factor(m)

    def scale_lengths() -> None:
        for attr in _LENGTH_ATTRS:
            value = shape.numeric(attr)
            if value is not None:
                shape.set(attr, _fmt(value * factor))

    if shape.tag == "path":
        d = shape.attrs.get("d")
        if not d:
            return True
        try:
            shape.attrs["d"] = transform_path_matrix(d, m)
        except ValueError:
            return False
        if uniform:
            scale_lengths()
            return True
        return True

    if shape.tag in ("polygon", "polyline"):
        raw = shape.attrs.get("points", "")
        nums = [float(n) for n in _NUM_RE.findall(raw)]
        pts = []
        for i in range(0, len(nums) - 1, 2):
            nx, ny = apply(m, nums[i], nums[i + 1])
            pts.append(f"{_fmt(nx)},{_fmt(ny)}")
        shape.attrs["points"] = " ".join(pts)
        if uniform:
            scale_lengths()
        return True

    if shape.tag == "line":
        x1, y1 = shape.numeric("x1") or 0.0, shape.numeric("y1") or 0.0
        x2, y2 = shape.numeric("x2") or 0.0, shape.numeric("y2") or 0.0
        nx1, ny1 = apply(m, x1, y1)
        nx2, ny2 = apply(m, x2, y2)
        shape.set("x1", _fmt(nx1)); shape.set("y1", _fmt(ny1))
        shape.set("x2", _fmt(nx2)); shape.set("y2", _fmt(ny2))
        if uniform:
            scale_lengths()
        return True

    # Axis-aligned primitives survive only under axis-aligned matrices.
    if not axis:
        return False

    if shape.tag in ("rect", "image"):
        x, y = shape.numeric("x") or 0.0, shape.numeric("y") or 0.0
        w, h = shape.numeric("width"), shape.numeric("height")
        if w is None or h is None:
            return False
        x2, y2 = x + w, y + h
        nx1, ny1 = apply(m, x, y)
        nx2, ny2 = apply(m, x2, y2)
        shape.set("x", _fmt(min(nx1, nx2)))
        shape.set("y", _fmt(min(ny1, ny2)))
        shape.set("width", _fmt(abs(nx2 - nx1)))
        shape.set("height", _fmt(abs(ny2 - ny1)))
        for attr in ("rx", "ry"):
            value = shape.numeric(attr)
            if value is not None:
                shape.set(attr, _fmt(value * factor))
        if uniform:
            scale_lengths()
        return True

    if shape.tag == "circle":
        if not uniform:
            return False
        cx, cy = shape.numeric("cx") or 0.0, shape.numeric("cy") or 0.0
        r = shape.numeric("r")
        if r is None:
            return False
        ncx, ncy = apply(m, cx, cy)
        shape.set("cx", _fmt(ncx)); shape.set("cy", _fmt(ncy))
        shape.set("r", _fmt(r * factor))
        scale_lengths()
        return True

    if shape.tag == "ellipse":
        cx, cy = shape.numeric("cx") or 0.0, shape.numeric("cy") or 0.0
        rx, ry = shape.numeric("rx"), shape.numeric("ry")
        if rx is None or ry is None:
            return False
        ncx, ncy = apply(m, cx, cy)
        shape.set("cx", _fmt(ncx)); shape.set("cy", _fmt(ncy))
        shape.set("rx", _fmt(rx * abs(m[0])))
        shape.set("ry", _fmt(ry * abs(m[3])))
        if uniform:
            scale_lengths()
        return True

    if shape.tag == "text":
        if not uniform:
            return False  # non-uniform scaling would distort glyphs
        x, y = shape.numeric("x") or 0.0, shape.numeric("y") or 0.0
        nx, ny = apply(m, x, y)
        shape.set("x", _fmt(nx)); shape.set("y", _fmt(ny))
        scale_lengths()
        return True

    return False


def bake_gradient(grad, m: Matrix) -> None:
    """Transform a gradient's userSpaceOnUse coordinates."""
    coords = grad.coords
    if grad.kind == "linear":
        if {"x1", "y1"} <= coords.keys():
            coords["x1"], coords["y1"] = apply(m, coords["x1"], coords["y1"])
        if {"x2", "y2"} <= coords.keys():
            coords["x2"], coords["y2"] = apply(m, coords["x2"], coords["y2"])
    else:
        if {"cx", "cy"} <= coords.keys():
            coords["cx"], coords["cy"] = apply(m, coords["cx"], coords["cy"])
        if "r" in coords:
            coords["r"] = coords["r"] * scale_factor(m)
