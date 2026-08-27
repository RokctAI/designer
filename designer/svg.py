# Copyright (c) 2026 ROKCT INTELLIGENCE (PTY) LTD
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

"""Minimal SVG document model: parse, mutate, serialize.

The compliance rules operate on this model, so the same rule fixes a
freshly vectorized raster and a hand-authored SVG alike. Parsing
flattens groups (style inheritance applied); transforms are preserved
verbatim on the shape and flagged by the auditor rather than evaluated.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path

from designer.matrix import (
    IDENTITY,
    Matrix,
    UnsupportedTransform,
    is_identity,
    multiply,
    parse_transform,
)

SVG_NS = "http://www.w3.org/2000/svg"

_STYLE_PROPS = (
    "fill",
    "stroke",
    "stroke-width",
    "font-family",
    "font-size",
    "opacity",
    "fill-opacity",
)


@dataclass
class Shape:
    tag: str  # path | rect | circle | ellipse | line | polygon | polyline | text
    attrs: dict[str, str] = field(default_factory=dict)
    text: str = ""  # text content for <text> elements

    def get(self, prop: str, default: str | None = None) -> str | None:
        return self.attrs.get(prop, default)

    def set(self, prop: str, value: str) -> None:
        self.attrs[prop] = value

    @property
    def fill(self) -> str | None:
        return self.attrs.get("fill")

    @property
    def stroke(self) -> str | None:
        return self.attrs.get("stroke")

    def numeric(self, prop: str) -> float | None:
        raw = self.attrs.get(prop)
        if raw is None:
            return None
        m = re.match(r"^\s*(-?\d+(?:\.\d+)?)", raw)
        return float(m.group(1)) if m else None


@dataclass
class GradientDef:
    """A gradient in <defs>, referenced by shapes as fill="url(#id)".

    ``coords`` uses userSpaceOnUse units: x1/y1/x2/y2 for linear,
    cx/cy/r for radial. ``stops`` are (offset 0..1, css color)."""

    id: str
    kind: str  # "linear" | "radial"
    stops: list[tuple[float, str]] = field(default_factory=list)
    coords: dict[str, float] = field(default_factory=dict)


@dataclass
class Document:
    width: float
    height: float
    shapes: list[Shape] = field(default_factory=list)
    defs: list[GradientDef] = field(default_factory=list)
    # Verbatim <defs> children we preserve but do not analyze
    # (clipPath/mask/filter/pattern/marker), so rendering stays faithful.
    raw_defs: list[str] = field(default_factory=list)
    source: str | None = None  # original file path, if any
    # Fidelity notes: constructs the parser dropped or flattened, and
    # pipeline capability gaps (e.g. OCR unavailable). Surfaced as
    # findings by the engine.capability rule so audits are never
    # silently blind to what they could not see.
    warnings: list[str] = field(default_factory=list)

    def gradient_by_ref(self, paint: str | None) -> GradientDef | None:
        """Resolve a fill/stroke value like "url(#g0)" to its def."""
        if not paint:
            return None
        m = re.match(r"url\(\s*#([^)\s]+)\s*\)", paint.strip())
        if not m:
            return None
        for g in self.defs:
            if g.id == m.group(1):
                return g
        return None

    def background_color(self) -> str | None:
        """Best guess at the canvas background: the first shape that
        covers (almost) the whole canvas, else None."""
        canvas = self.width * self.height
        for shape in self.shapes:
            area = _shape_area(shape, self.width, self.height)
            if area is not None and area >= 0.9 * canvas and shape.fill:
                return shape.fill
        return None


def is_dieline(shape: Shape) -> bool:
    """Vendor dieline geometry (cut/crease contours). Marked in the
    source SVG by an id or class of ``dieline`` on the shape or an
    enclosing group; travels through the pipeline untouched."""
    return shape.attrs.get("data-dieline") == "true"


def _element_marks_dieline(element: ET.Element) -> bool:
    if element.get("id") == "dieline":
        return True
    return "dieline" in (element.get("class") or "").split()


def _shape_area(shape: Shape, doc_w: float, doc_h: float) -> float | None:
    if shape.tag == "rect":
        w, h = shape.numeric("width"), shape.numeric("height")
        if w is not None and h is not None:
            return w * h
    if shape.tag == "circle":
        r = shape.numeric("r")
        if r is not None:
            return 3.14159 * r * r
    if shape.tag == "path":
        d = shape.attrs.get("d", "")
        try:
            from designer.path import path_area

            return path_area(d)
        except ValueError:
            return None
    return None


def shape_area(shape: Shape, doc: Document) -> float | None:
    return _shape_area(shape, doc.width, doc.height)


# ---------------------------------------------------------------- parsing


def _strip_ns(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _parse_style_attr(style: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for part in style.split(";"):
        if ":" in part:
            k, v = part.split(":", 1)
            out[k.strip()] = v.strip()
    return out


def _parse_length(raw: str | None, default: float) -> float:
    if not raw:
        return default
    m = re.match(r"^\s*(-?\d+(?:\.\d+)?)", raw)
    return float(m.group(1)) if m else default


_SHAPE_TAGS = (
    "path", "rect", "circle", "ellipse", "line", "polygon", "polyline",
    "text", "image",
)
# Kept verbatim in <defs> so rendering stays faithful even though the
# audit cannot reason about them.
_PRESERVED_DEF_TAGS = ("clipPath", "mask", "filter", "pattern", "marker")

_CSS_PROPS = _STYLE_PROPS + (
    "text-anchor", "font-weight", "font-style", "stroke-linecap",
    "stroke-linejoin", "stroke-dasharray", "fill-rule",
)

MAX_USE_DEPTH = 6


def parse_svg(path: str | Path) -> Document:
    tree = ET.parse(str(path))
    root = tree.getroot()

    view_box = root.get("viewBox")
    if view_box:
        parts = [float(p) for p in re.split(r"[,\s]+", view_box.strip())]
        width, height = parts[2], parts[3]
    else:
        width = _parse_length(root.get("width"), 100.0)
        height = _parse_length(root.get("height"), 100.0)

    doc = Document(width=width, height=height, source=str(path))

    def warn(message: str) -> None:
        if message not in doc.warnings:
            doc.warnings.append(message)

    # --- pre-pass: stylesheet, id index (for <use>), preserved defs ---
    from designer.css import parse_stylesheet

    css_text = []
    id_index: dict[str, ET.Element] = {}
    for element in root.iter():
        tag = _strip_ns(element.tag)
        if tag == "style":
            css_text.append("".join(element.itertext()))
        element_id = element.get("id")
        if element_id:
            id_index.setdefault(element_id, element)
    sheet = parse_stylesheet("\n".join(css_text))
    for selector in sheet.skipped:
        warn(
            f"CSS selector {selector!r} is not supported — styling it applies "
            "was not evaluated by this audit"
        )

    def resolve_style(element: ET.Element, inherited: dict[str, str]) -> dict[str, str]:
        """Cascade: inherited < stylesheet < presentation attrs < style attr."""
        style = dict(inherited)
        style.update(
            sheet.declarations_for(
                _strip_ns(element.tag), element.get("class"), element.get("id")
            )
        )
        for prop in _CSS_PROPS:
            value = element.get(prop)
            if value is not None:
                style[prop] = value
        if element.get("style"):
            style.update(_parse_style_attr(element.get("style")))
        return style

    def walk(
        element: ET.Element,
        inherited: dict[str, str],
        matrix: Matrix,
        depth: int = 0,
        dieline: bool = False,
    ) -> None:
        tag = _strip_ns(element.tag)
        style = resolve_style(element, inherited)
        dieline = dieline or _element_marks_dieline(element)

        try:
            own_matrix = parse_transform(element.get("transform"))
        except UnsupportedTransform as exc:
            warn(f"<{tag}> transform not understood ({exc}); geometry left unevaluated")
            own_matrix = IDENTITY
        combined = multiply(matrix, own_matrix)

        if tag in ("g", "svg", "a"):
            for child in element:
                walk(child, style, combined, depth, dieline)
            return

        if tag == "defs":
            for child in element:
                child_tag = _strip_ns(child.tag)
                if child_tag in ("linearGradient", "radialGradient"):
                    _parse_gradient(child, doc)
                elif child_tag in _PRESERVED_DEF_TAGS:
                    doc.raw_defs.append(_serialize_element(child))
                    warn(
                        f"<{child_tag}> preserved but not evaluated — shapes using "
                        "it render correctly, but the audit cannot see its effect"
                    )
                elif child_tag in ("symbol", "g", "rect", "circle", "path", "ellipse",
                                   "polygon", "polyline", "line", "text", "image"):
                    pass  # a <use> prototype; instantiated where referenced
                else:
                    warn(f"unsupported <defs> content <{child_tag}> dropped")
            return

        if tag in ("linearGradient", "radialGradient"):
            _parse_gradient(element, doc)
            return

        if tag in _PRESERVED_DEF_TAGS:
            doc.raw_defs.append(_serialize_element(element))
            return

        if tag == "style":
            return  # already folded into the cascade

        if tag == "script":
            warn("<script> element removed")
            return

        if tag == "use":
            href = element.get("href") or element.get("{http://www.w3.org/1999/xlink}href")
            if not href or not href.startswith("#"):
                warn("<use> without a local reference dropped")
                return
            target = id_index.get(href[1:])
            if target is None:
                warn(f"<use> references missing id {href!r}")
                return
            if depth >= MAX_USE_DEPTH:
                warn("<use> nesting too deep; instantiation stopped")
                return
            offset = parse_transform(
                f"translate({_parse_length(element.get('x'), 0.0)} "
                f"{_parse_length(element.get('y'), 0.0)})"
            )
            use_matrix = multiply(combined, offset)
            target_tag = _strip_ns(target.tag)
            if target_tag in ("symbol", "g"):
                for child in target:
                    walk(child, style, use_matrix, depth + 1, dieline)
            else:
                walk(target, style, use_matrix, depth + 1, dieline)
            return

        if tag in ("metadata", "title", "desc", "foreignObject"):
            if tag == "foreignObject":
                warn("<foreignObject> dropped — HTML content is not auditable")
            return

        if tag in _SHAPE_TAGS:
            attrs: dict[str, str] = {}
            for key, value in element.attrib.items():
                key = _strip_ns(key)
                if key in ("style", "transform", "class"):
                    continue
                if not _safe_attr(key, value):
                    warn(f"unsafe attribute {key!r} stripped from <{tag}>")
                    continue
                attrs[key] = value
            for prop, value in style.items():
                if _safe_attr(prop, value):
                    attrs.setdefault(prop, value)

            text_content = ""
            if tag == "text":
                text_content = " ".join("".join(element.itertext()).split())
                if any(_strip_ns(child.tag) == "tspan" for child in element):
                    warn(
                        "multi-span <text> flattened to a single line — "
                        "line breaks and per-span styling were lost"
                    )

            shape = Shape(tag=tag, attrs=attrs, text=text_content)
            if dieline:
                shape.attrs["data-dieline"] = "true"
            _place(shape, combined, doc, warn)
            doc.shapes.append(shape)
            return

        warn(f"unknown element <{tag}> dropped")

    walk(root, {}, IDENTITY)
    _bake_pending(doc)
    return doc


def _place(shape: Shape, matrix: Matrix, doc: Document, warn) -> None:
    """Record the shape's effective matrix. Baking happens after the
    walk so gradient sharing can be accounted for."""
    if not is_identity(matrix):
        shape.attrs["transform"] = _matrix_to_string(matrix)


def _bake_pending(doc: Document) -> None:
    """Bake each shape's transform into its geometry where that is exact.

    Shapes that cannot be represented axis-aligned (rotated rects, text)
    keep their transform attribute, and gradients shared by shapes with
    different transforms are left alone rather than distorted.
    """
    from designer.transform import bake_gradient, bake_shape

    usage: dict[int, list[int]] = {}
    for i, shape in enumerate(doc.shapes):
        for prop in ("fill", "stroke"):
            grad = doc.gradient_by_ref(shape.get(prop))
            if grad is not None:
                usage.setdefault(id(grad), []).append(i)

    for i, shape in enumerate(doc.shapes):
        raw = shape.attrs.get("transform")
        if not raw:
            continue
        try:
            matrix = parse_transform(raw)
        except UnsupportedTransform:
            continue
        if is_identity(matrix):
            del shape.attrs["transform"]
            continue

        grads = [
            doc.gradient_by_ref(shape.get(prop))
            for prop in ("fill", "stroke")
        ]
        grads = [g for g in grads if g is not None]
        if any(len(usage.get(id(g), [])) > 1 for g in grads):
            doc.warnings.append(
                f"shape {i} (<{shape.tag}>) keeps a transform because its gradient "
                "is shared with differently-transformed shapes"
            )
            continue

        snapshot = dict(shape.attrs)
        if bake_shape(shape, matrix):
            del shape.attrs["transform"]
            for g in grads:
                bake_gradient(g, matrix)
        else:
            shape.attrs.clear()
            shape.attrs.update(snapshot)
            doc.warnings.append(
                f"shape {i} (<{shape.tag}>) has a rotated or non-uniform transform "
                "that cannot be baked into its geometry; grid and margin checks on "
                "this shape are approximate"
            )


def _matrix_to_string(m: Matrix) -> str:
    return "matrix({})".format(
        " ".join(f"{v:.6f}".rstrip("0").rstrip(".") or "0" for v in m)
    )


def _serialize_element(element: ET.Element) -> str:
    """Verbatim XML for a preserved def, with namespaces normalized and
    scriptable attributes removed."""
    for node in element.iter():
        node.tag = _strip_ns(node.tag)
        for key in list(node.attrib):
            clean = _strip_ns(key)
            value = node.attrib.pop(key)
            if _safe_attr(clean, value):
                node.attrib[clean] = value
    return ET.tostring(element, encoding="unicode").strip()


_SAFE_HREF = re.compile(r"^\s*(data:image/|https?:|/|\.{0,2}/|[\w.\-]+$)", re.IGNORECASE)


def _safe_attr(key: str, value: str) -> bool:
    """Attribute security policy: no event handlers, no scriptable or
    non-image href targets. Everything the engine writes back out has
    passed through this filter."""
    lowered = key.lower()
    if lowered.startswith("on"):
        return False
    if lowered in ("href", "xlink:href"):
        return bool(_SAFE_HREF.match(value))
    return True


def _parse_gradient(element: ET.Element, doc: Document) -> None:
    tag = _strip_ns(element.tag)
    if tag not in ("linearGradient", "radialGradient"):
        return
    grad = GradientDef(
        id=element.get("id", f"grad{len(doc.defs)}"),
        kind="linear" if tag == "linearGradient" else "radial",
    )
    coord_keys = ("x1", "y1", "x2", "y2") if grad.kind == "linear" else ("cx", "cy", "r")
    for key in coord_keys:
        raw = element.get(key)
        if raw is not None:
            grad.coords[key] = _parse_length(raw, 0.0)
    for stop in element:
        if _strip_ns(stop.tag) != "stop":
            continue
        raw_offset = stop.get("offset", "0")
        offset = (
            float(raw_offset[:-1]) / 100 if raw_offset.endswith("%") else float(raw_offset)
        )
        color = stop.get("stop-color")
        if color is None and stop.get("style"):
            color = _parse_style_attr(stop.get("style")).get("stop-color")
        grad.stops.append((offset, color or "#000000"))
    doc.defs.append(grad)


# ------------------------------------------------------------ serializing


def serialize(doc: Document, pretty: bool = True) -> str:
    lines = [
        '<svg xmlns="{ns}" viewBox="0 0 {w:g} {h:g}" width="{w:g}" height="{h:g}">'.format(
            ns=SVG_NS, w=doc.width, h=doc.height
        )
    ]
    if doc.defs or doc.raw_defs:
        lines.append("  <defs>")
        for raw in doc.raw_defs:
            lines.append("    " + raw)
        for grad in doc.defs:
            tag = "linearGradient" if grad.kind == "linear" else "radialGradient"
            coords = " ".join(f'{k}="{v:.2f}"' for k, v in grad.coords.items())
            lines.append(f'    <{tag} id="{grad.id}" gradientUnits="userSpaceOnUse" {coords}>')
            for offset, color in grad.stops:
                lines.append(f'      <stop offset="{offset:.3f}" stop-color="{color}"/>')
            lines.append(f"    </{tag}>")
        lines.append("  </defs>")
    for shape in doc.shapes:
        attrs = " ".join(
            f'{k}="{_escape(v)}"' for k, v in shape.attrs.items() if v is not None
        )
        if shape.tag == "text":
            lines.append(f"  <text {attrs}>{_escape(shape.text)}</text>")
        else:
            lines.append(f"  <{shape.tag} {attrs}/>")
    lines.append("</svg>")
    joiner = "\n" if pretty else ""
    return joiner.join(lines) + ("\n" if pretty else "")


def _escape(value: str) -> str:
    return (
        value.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def save(doc: Document, path: str | Path) -> None:
    Path(path).write_text(serialize(doc), encoding="utf-8")
