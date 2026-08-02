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

_NUM_RE = re.compile(r"-?\d+(?:\.\d+)?(?:e-?\d+)?", re.IGNORECASE)
_TOKEN_RE = re.compile(r"([MmLlHhVvCcSsQqTtAaZz])|(-?\d+(?:\.\d+)?(?:e-?\d+)?)")

# Per absolute command: for each parameter, how to transform it.
# "x"/"y" = position, "lx"/"ly" = length-only, "raw" = untouched.
_CMD_PARAMS = {
    "M": ["x", "y"],
    "L": ["x", "y"],
    "T": ["x", "y"],
    "H": ["x"],
    "V": ["y"],
    "C": ["x", "y", "x", "y", "x", "y"],
    "S": ["x", "y", "x", "y"],
    "Q": ["x", "y", "x", "y"],
    "A": ["lx", "ly", "raw", "raw", "raw", "x", "y"],
}


def _fmt(v: float) -> str:
    return f"{v:.2f}".rstrip("0").rstrip(".")


def transform_path(d: str, s: float, tx: float, ty: float) -> str:
    """Apply uniform scale + translate to path data. Relative commands
    scale but don't translate (translation is carried by the initial
    absolute moveto)."""
    out: list[str] = []
    cmd = ""
    params: list[str] = []
    idx = 0

    def emit_number(value: float, kind: str, absolute: bool) -> str:
        if kind == "raw":
            return _fmt(value)
        scaled = value * s
        if absolute:
            if kind == "x":
                scaled += tx
            elif kind == "y":
                scaled += ty
        return _fmt(scaled)

    for match in _TOKEN_RE.finditer(d):
        if match.group(1):
            cmd = match.group(1)
            out.append(cmd)
            upper = cmd.upper()
            params = _CMD_PARAMS.get(upper, [])
            idx = 0
        else:
            value = float(match.group(2))
            if not params:  # Z or unknown: pass through
                out.append(_fmt(value))
                continue
            kind = params[idx % len(params)]
            out.append(emit_number(value, kind, cmd.isupper()))
            idx += 1
    return " ".join(out)


def _transform_shape(shape: Shape, s: float, tx: float, ty: float) -> None:
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
        shape.attrs["d"] = transform_path(shape.attrs["d"], s, tx, ty)
    if shape.tag in ("polygon", "polyline") and shape.attrs.get("points"):
        nums = [float(n) for n in _NUM_RE.findall(shape.attrs["points"])]
        pts = [
            _fmt(n * s + (tx if i % 2 == 0 else ty))
            for i, n in enumerate(nums)
        ]
        shape.attrs["points"] = " ".join(
            f"{pts[i]},{pts[i + 1]}" for i in range(0, len(pts) - 1, 2)
        )


def affine_document(doc: Document, s: float, tx: float, ty: float) -> None:
    """Scale the whole document by ``s`` then translate by (tx, ty),
    in place. Canvas size is NOT changed — callers set doc.width/height
    to the target themselves."""
    for shape in doc.shapes:
        _transform_shape(shape, s, tx, ty)
    for grad in doc.defs:
        for key in list(grad.coords):
            v = grad.coords[key]
            if key in ("x1", "x2", "cx"):
                grad.coords[key] = v * s + tx
            elif key in ("y1", "y2", "cy"):
                grad.coords[key] = v * s + ty
            else:  # r and any other length
                grad.coords[key] = v * s
