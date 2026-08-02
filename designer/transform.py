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

from designer.path import parse_path, serialize_path

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
