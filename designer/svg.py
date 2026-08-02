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
class Document:
    width: float
    height: float
    shapes: list[Shape] = field(default_factory=list)
    source: str | None = None  # original file path, if any

    def background_color(self) -> str | None:
        """Best guess at the canvas background: the first shape that
        covers (almost) the whole canvas, else None."""
        canvas = self.width * self.height
        for shape in self.shapes:
            area = _shape_area(shape, self.width, self.height)
            if area is not None and area >= 0.9 * canvas and shape.fill:
                return shape.fill
        return None


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
        pts = _path_points(d)
        if len(pts) >= 3:
            return abs(_shoelace(pts))
    return None


def _path_points(d: str) -> list[tuple[float, float]]:
    """Absolute-coordinate vertices of a path (M/L/C endpoints only) —
    enough for area estimates on the paths this package emits."""
    nums = [float(n) for n in re.findall(r"-?\d+(?:\.\d+)?(?:e-?\d+)?", d)]
    pts = list(zip(nums[0::2], nums[1::2]))
    return pts


def _shoelace(pts: list[tuple[float, float]]) -> float:
    area = 0.0
    n = len(pts)
    for i in range(n):
        x1, y1 = pts[i]
        x2, y2 = pts[(i + 1) % n]
        area += x1 * y2 - x2 * y1
    return area / 2.0


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

    def walk(element: ET.Element, inherited: dict[str, str]) -> None:
        style = dict(inherited)
        for prop in _STYLE_PROPS:
            if element.get(prop) is not None:
                style[prop] = element.get(prop)  # type: ignore[assignment]
        if element.get("style"):
            style.update(_parse_style_attr(element.get("style")))  # type: ignore[arg-type]

        tag = _strip_ns(element.tag)
        if tag in ("g", "svg"):
            for child in element:
                walk(child, style)
            return
        if tag in ("defs", "metadata", "title", "desc", "style", "script"):
            return
        if tag in (
            "path",
            "rect",
            "circle",
            "ellipse",
            "line",
            "polygon",
            "polyline",
            "text",
        ):
            attrs: dict[str, str] = {}
            for key, value in element.attrib.items():
                key = _strip_ns(key)
                if key != "style":
                    attrs[key] = value
            # Inherited/style-attr values win only where the element
            # didn't set its own presentation attribute.
            for prop, value in style.items():
                attrs.setdefault(prop, value)
            text_content = "".join(element.itertext()).strip() if tag == "text" else ""
            doc.shapes.append(Shape(tag=tag, attrs=attrs, text=text_content))

    walk(root, {})
    return doc


# ------------------------------------------------------------ serializing


def serialize(doc: Document, pretty: bool = True) -> str:
    lines = [
        '<svg xmlns="{ns}" viewBox="0 0 {w:g} {h:g}" width="{w:g}" height="{h:g}">'.format(
            ns=SVG_NS, w=doc.width, h=doc.height
        )
    ]
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
