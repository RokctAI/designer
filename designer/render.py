"""Output: rasterize a Document to PNG, or write it as vector PDF.

A design system that can only emit SVG cannot deliver a newspaper page
or a social export, so both paths are implemented directly on the
document model — no cairo, no headless browser, no external binaries.

* PNG  — supersampled Pillow rasterization (even-odd fills, gradients,
  embedded images, real font rendering).
* PDF  — vector output with embedded TrueType fonts, axial/radial
  shadings and Flate-compressed images, at a chosen DPI, optionally
  converted to CMYK for press.
"""

from __future__ import annotations

import base64
import io
import re
import zlib
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

from designer.color import RGB, parse_color
from designer.fonts import first_family, is_bold, resolve_font_file, resolve_with_fallback
from designer.path import path_subpaths
from designer.svg import Document, GradientDef, Shape

# 96 CSS px per inch is the reference the whole engine works in.
CSS_DPI = 96.0


class RenderError(ValueError):
    pass


# ------------------------------------------------------------ resources


def _decode_href(href: str, base_dir: Path | None) -> Image.Image | None:
    """Load an <image> href: data URI or a local file next to the doc."""
    if not href:
        return None
    if href.startswith("data:"):
        match = re.match(r"data:image/[\w.+-]+;base64,(.*)", href, re.DOTALL)
        if not match:
            return None
        try:
            raw = base64.b64decode(match.group(1))
        except Exception:
            return None
        try:
            return Image.open(io.BytesIO(raw)).convert("RGBA")
        except Exception:
            return None
    candidate = Path(href)
    if not candidate.is_absolute() and base_dir is not None:
        candidate = base_dir / href
    if candidate.exists():
        try:
            return Image.open(candidate).convert("RGBA")
        except Exception:
            return None
    return None


def _fit_slice(img: Image.Image, w: int, h: int) -> Image.Image:
    """Center-crop to fill a box (SVG 'xMidYMid slice')."""
    if w <= 0 or h <= 0:
        return img
    scale = max(w / img.width, h / img.height)
    new = img.resize(
        (max(1, round(img.width * scale)), max(1, round(img.height * scale))),
        Image.LANCZOS,
    )
    left = (new.width - w) // 2
    top = (new.height - h) // 2
    return new.crop((left, top, left + w, top + h))


def _shape_polygons(shape: Shape, scale: float) -> list[list[tuple[float, float]]]:
    """Flatten any fillable shape to polygon rings in device space."""
    rings: list[list[tuple[float, float]]] = []
    if shape.tag == "path":
        d = shape.attrs.get("d")
        if not d:
            return []
        try:
            rings = path_subpaths(d, curve_samples=12)
        except ValueError:
            return []
    elif shape.tag == "rect":
        x, y = shape.numeric("x") or 0.0, shape.numeric("y") or 0.0
        w, h = shape.numeric("width"), shape.numeric("height")
        if w is None or h is None:
            return []
        rings = [[(x, y), (x + w, y), (x + w, y + h), (x, y + h)]]
    elif shape.tag in ("circle", "ellipse"):
        cx, cy = shape.numeric("cx") or 0.0, shape.numeric("cy") or 0.0
        if shape.tag == "circle":
            rx = ry = shape.numeric("r") or 0.0
        else:
            rx, ry = shape.numeric("rx") or 0.0, shape.numeric("ry") or 0.0
        steps = 64
        rings = [
            [
                (
                    cx + rx * np.cos(2 * np.pi * i / steps),
                    cy + ry * np.sin(2 * np.pi * i / steps),
                )
                for i in range(steps)
            ]
        ]
    elif shape.tag in ("polygon", "polyline"):
        nums = [float(n) for n in re.findall(r"-?\d+(?:\.\d+)?", shape.attrs.get("points", ""))]
        rings = [list(zip(nums[0::2], nums[1::2]))]
    return [[(px * scale, py * scale) for px, py in ring] for ring in rings if len(ring) >= 3]


def _even_odd_mask(size: tuple[int, int], rings: list[list[tuple[float, float]]]) -> Image.Image:
    """Even-odd fill mask: XOR of the individual subpath masks, which is
    exactly the even-odd rule and gives correct holes."""
    mask = Image.new("L", size, 0)
    accum = np.zeros((size[1], size[0]), dtype=bool)
    for ring in rings:
        layer = Image.new("L", size, 0)
        ImageDraw.Draw(layer).polygon(ring, fill=255)
        accum ^= np.asarray(layer, dtype=np.uint8) > 127
    mask.putdata(np.where(accum, 255, 0).astype(np.uint8).flatten().tolist())
    return mask


def _gradient_array(
    grad: GradientDef, size: tuple[int, int], scale: float
) -> np.ndarray:
    """Per-pixel RGB for a gradient across the whole canvas."""
    w, h = size
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float64)
    if grad.kind == "linear":
        x1 = grad.coords.get("x1", 0.0) * scale
        y1 = grad.coords.get("y1", 0.0) * scale
        x2 = grad.coords.get("x2", float(w)) * scale
        y2 = grad.coords.get("y2", 0.0) * scale
        dx, dy = x2 - x1, y2 - y1
        denom = dx * dx + dy * dy
        t = ((xx - x1) * dx + (yy - y1) * dy) / denom if denom else np.zeros_like(xx)
    else:
        cx = grad.coords.get("cx", w / 2) * scale
        cy = grad.coords.get("cy", h / 2) * scale
        r = max(1e-6, grad.coords.get("r", max(w, h) / 2) * scale)
        t = np.hypot(xx - cx, yy - cy) / r
    t = np.clip(t, 0.0, 1.0)

    stops = sorted(grad.stops, key=lambda s: s[0]) or [(0.0, "#000000"), (1.0, "#000000")]
    offsets = np.array([s[0] for s in stops])
    colors = np.array([parse_color(s[1]) or (0, 0, 0) for s in stops], dtype=np.float64)
    out = np.zeros((h, w, 3), dtype=np.float64)
    for channel in range(3):
        out[..., channel] = np.interp(t, offsets, colors[:, channel])
    return out.astype(np.uint8)


# ------------------------------------------------------------------ PNG


def render_png(
    doc: Document,
    path: str | Path | None = None,
    width: int | None = None,
    dpi: float | None = None,
    supersample: int = 2,
    background: str = "#ffffff",
) -> Image.Image:
    """Rasterize a Document. ``width`` (px) or ``dpi`` set the output
    size; the default is the document's own pixel size."""
    if width and dpi:
        raise RenderError("give width or dpi, not both")
    if width:
        scale = width / doc.width
    elif dpi:
        scale = dpi / CSS_DPI
    else:
        scale = 1.0

    ss = max(1, int(supersample))
    dev_scale = scale * ss
    size = (max(1, round(doc.width * dev_scale)), max(1, round(doc.height * dev_scale)))

    bg = parse_color(background) or (255, 255, 255)
    canvas = Image.new("RGB", size, bg)
    base_dir = Path(doc.source).parent if doc.source else None

    for shape in doc.shapes:
        _draw_shape(canvas, shape, doc, dev_scale, base_dir)

    if ss > 1:
        canvas = canvas.resize(
            (max(1, round(doc.width * scale)), max(1, round(doc.height * scale))),
            Image.LANCZOS,
        )
    if path:
        canvas.save(str(path))
    return canvas


def _draw_shape(
    canvas: Image.Image, shape: Shape, doc: Document, scale: float, base_dir: Path | None
) -> None:
    size = canvas.size

    if shape.tag == "image":
        href = shape.get("href") or shape.get("xlink:href")
        img = _decode_href(href or "", base_dir)
        if img is None:
            return
        x, y = shape.numeric("x") or 0.0, shape.numeric("y") or 0.0
        w, h = shape.numeric("width"), shape.numeric("height")
        if w is None or h is None:
            return
        box = (round(w * scale), round(h * scale))
        fitted = _fit_slice(img, box[0], box[1])
        canvas.paste(fitted, (round(x * scale), round(y * scale)), fitted)
        return

    if shape.tag == "text":
        _draw_text(canvas, shape, scale, doc)
        return

    fill = shape.get("fill")
    if fill and fill.strip().lower() not in ("none", "transparent"):
        rings = _shape_polygons(shape, scale)
        if rings:
            mask = _even_odd_mask(size, rings)
            grad = doc.gradient_by_ref(fill)
            if grad is not None:
                paint = Image.fromarray(_gradient_array(grad, size, scale))
            else:
                rgb = parse_color(fill)
                if rgb is None:
                    return
                paint = Image.new("RGB", size, rgb)
            canvas.paste(paint, (0, 0), mask)

    stroke = shape.get("stroke")
    if stroke and stroke.strip().lower() not in ("none", "transparent"):
        rgb = parse_color(stroke)
        if rgb is None:
            return
        width = (shape.numeric("stroke-width") or 1.0) * scale
        draw = ImageDraw.Draw(canvas)
        for ring in _shape_polygons(shape, scale):
            draw.line(list(ring) + [ring[0]], fill=rgb, width=max(1, round(width)))


def _draw_text(
    canvas: Image.Image, shape: Shape, scale: float, doc: Document | None = None
) -> None:
    from PIL import ImageFont

    if not shape.text:
        return
    rgb = parse_color(shape.get("fill") or "#000000") or (0, 0, 0)
    size = (shape.numeric("font-size") or 16.0) * scale
    family = first_family(shape.get("font-family"))
    path, substituted = resolve_with_fallback(family, bold=is_bold(shape.get("font-weight")))
    if substituted and doc is not None and family:
        note = (
            f"font {family!r} is not installed; rendered with a substitute — "
            "line widths and spacing will differ from the design"
        )
        if note not in doc.warnings:
            doc.warnings.append(note)
    try:
        font = ImageFont.truetype(path, max(1, round(size))) if path else ImageFont.load_default()
    except OSError:
        font = ImageFont.load_default()
    anchor_map = {"start": "ls", "middle": "ms", "end": "rs"}
    anchor = anchor_map.get((shape.get("text-anchor") or "start").strip(), "ls")
    x = (shape.numeric("x") or 0.0) * scale
    y = (shape.numeric("y") or 0.0) * scale
    draw = ImageDraw.Draw(canvas)
    try:
        draw.text((x, y), shape.text, font=font, fill=rgb, anchor=anchor)
    except ValueError:  # bitmap fallback font has no anchor support
        draw.text((x, y), shape.text, font=font, fill=rgb)


# ------------------------------------------------------------------ PDF


@dataclass
class _PdfFont:
    name: str
    path: str
    obj: int = 0


def _pdf_escape(text: str) -> bytes:
    encoded = text.encode("cp1252", errors="replace")
    out = bytearray()
    for byte in encoded:
        if byte in (0x28, 0x29, 0x5C):  # ( ) \
            out += b"\\" + bytes([byte])
        elif byte < 32 or byte > 126:
            out += f"\\{byte:03o}".encode("ascii")
        else:
            out.append(byte)
    return bytes(out)


def render_pdf(
    doc: Document,
    path: str | Path,
    dpi: float = 300.0,
    cmyk: bool = False,
    embed_fonts: bool = True,
    format: "object | None" = None,
    bleed: float = 0.0,
    marks: bool = False,
    icc_profile: str | Path | None = None,
) -> Path:
    """Write a vector PDF.

    Geometry stays vector at any DPI. The page's physical size comes
    from the document's px density: ``format.dpi`` when a format is
    given, else CSS px at 96/inch.

    ``cmyk`` converts colors to CMYK. With ``icc_profile`` (a press
    CMYK ICC profile) the conversion is color-managed through the
    profile, which is also embedded as the PDF's output intent — a
    press PDF with output intent, not a validated PDF/X file. Without
    a profile the conversion is naive and reported as unmanaged:
    adequate for a first proof, not for plates.

    With ``bleed`` (px past trim) the page grows to trim + bleed and a
    /TrimBox records the finished size. ``marks`` adds a slug area and
    draws crop marks, registration marks and a job slug line outside
    the bleed — in registration color (all separations) when ``cmyk``.
    """
    writer = _PdfWriter(
        doc, cmyk=cmyk, embed_fonts=embed_fonts,
        format=format, bleed=bleed, marks=marks, icc_profile=icc_profile,
    )
    data = writer.build(dpi)
    out = Path(path)
    out.write_bytes(data)
    return out


class _PdfWriter:
    def __init__(
        self,
        doc: Document,
        cmyk: bool = False,
        embed_fonts: bool = True,
        format: "object | None" = None,
        bleed: float = 0.0,
        marks: bool = False,
        icc_profile: str | Path | None = None,
    ):
        self.doc = doc
        self.cmyk = cmyk
        self.embed_fonts = embed_fonts
        self.format = format
        self.bleed = max(0.0, float(bleed))
        self.marks = marks
        self._icc = None            # ImageCms transform, when managed
        self._icc_cache: dict[RGB, tuple[float, float, float, float]] = {}
        self.icc_bytes: bytes | None = None
        self.icc_desc = ""
        if cmyk:
            self._init_icc(icc_profile)
        # px density of the document; sets physical size and mark sizes.
        self.px_dpi = float(getattr(format, "dpi", 0) or CSS_DPI)
        # Slug: room outside the bleed for marks and the job line.
        self.slug = self._mm(10.0) if marks else 0.0
        self.offset = self.bleed + self.slug
        self.objects: list[bytes] = []
        self.fonts: dict[str, _PdfFont] = {}
        self.images: dict[int, tuple[str, bytes, int, int, str]] = {}
        self.shadings: list[tuple[str, GradientDef]] = []
        self.base_dir = Path(doc.source).parent if doc.source else None

    def _mm(self, mm: float) -> float:
        return mm * self.px_dpi / 25.4

    # -- color management ------------------------------------------------

    def _init_icc(self, icc_profile: str | Path | None) -> None:
        """Build one RGB->CMYK transform through the press profile; on
        any failure fall back to naive conversion and say so."""

        def warn(message: str) -> None:
            if message not in self.doc.warnings:
                self.doc.warnings.append(message)

        if not icc_profile:
            warn(
                "CMYK color is unmanaged (naive RGB->CMYK conversion) — "
                "set print.icc_profile to a press CMYK ICC profile for "
                "color-managed output"
            )
            return
        try:
            from PIL import ImageCms

            profile = ImageCms.getOpenProfile(str(icc_profile))
            self._icc = ImageCms.buildTransformFromOpenProfiles(
                ImageCms.createProfile("sRGB"), profile, "RGB", "CMYK",
                renderingIntent=ImageCms.Intent.RELATIVE_COLORIMETRIC,
            )
            self.icc_bytes = Path(icc_profile).read_bytes()
            self.icc_desc = (ImageCms.getProfileDescription(profile) or "").strip()
        except Exception as exc:
            self._icc = None
            self.icc_bytes = None
            warn(
                f"ICC profile {icc_profile!s} could not be used ({exc}); "
                "CMYK color is unmanaged (naive RGB->CMYK conversion)"
            )

    def _to_cmyk(self, rgb: RGB) -> tuple[float, float, float, float]:
        if self._icc is None:
            from designer.rules.print_rules import rgb_to_cmyk

            return rgb_to_cmyk(rgb)
        cached = self._icc_cache.get(rgb)
        if cached is None:
            from PIL import ImageCms

            pixel = Image.new("RGB", (1, 1), rgb)
            c, m, y, k = ImageCms.applyTransform(pixel, self._icc).getpixel((0, 0))
            cached = (c / 255, m / 255, y / 255, k / 255)
            self._icc_cache[rgb] = cached
        return cached

    def _cmyk_op(self, rgb: RGB) -> str:
        c, m, y, k = self._to_cmyk(rgb)
        return f"{c:.4f} {m:.4f} {y:.4f} {k:.4f}"

    # -- object plumbing -------------------------------------------------

    def _add(self, body: bytes) -> int:
        self.objects.append(body)
        return len(self.objects)  # 1-based object numbers

    def _reserve(self) -> int:
        self.objects.append(b"")
        return len(self.objects)

    def _set(self, number: int, body: bytes) -> None:
        self.objects[number - 1] = body

    # -- painting --------------------------------------------------------

    def _fill_op(self, rgb: RGB) -> str:
        if self.cmyk:
            return f"{self._cmyk_op(rgb)} k"
        return f"{rgb[0] / 255:.4f} {rgb[1] / 255:.4f} {rgb[2] / 255:.4f} rg"

    def _stroke_op(self, rgb: RGB) -> str:
        if self.cmyk:
            return f"{self._cmyk_op(rgb)} K"
        return f"{rgb[0] / 255:.4f} {rgb[1] / 255:.4f} {rgb[2] / 255:.4f} RG"

    def _path_ops(self, shape: Shape) -> str:
        rings = _shape_polygons(shape, 1.0)
        parts = []
        for ring in rings:
            parts.append(f"{ring[0][0]:.3f} {ring[0][1]:.3f} m")
            for px, py in ring[1:]:
                parts.append(f"{px:.3f} {py:.3f} l")
            parts.append("h")
        return "\n".join(parts)

    def _content(self) -> str:
        doc = self.doc
        ops = [
            "q",
            # PDF's origin is bottom-left; flip so document coordinates
            # (y down from the top-left) map directly, shifted in by the
            # bleed + slug offset so (0,0) is the trim's top-left corner.
            f"1 0 0 -1 {self.offset:.3f} {self.offset + doc.height:.3f} cm",
        ]
        if self.marks:
            # Artwork may not paint over the marks: clip it to the bleed box.
            ops += [
                "q",
                f"{-self.bleed:.3f} {-self.bleed:.3f} "
                f"{doc.width + 2 * self.bleed:.3f} {doc.height + 2 * self.bleed:.3f} re",
                "W n",
            ]

        for index, shape in enumerate(doc.shapes):
            if shape.tag == "image":
                ops.extend(self._image_ops(index, shape))
                continue
            if shape.tag == "text":
                ops.extend(self._text_ops(shape))
                continue

            path_ops = self._path_ops(shape)
            if not path_ops:
                continue
            fill = shape.get("fill")
            grad = doc.gradient_by_ref(fill)
            has_fill = bool(fill) and fill.strip().lower() not in ("none", "transparent")
            stroke = shape.get("stroke")
            has_stroke = bool(stroke) and stroke.strip().lower() not in ("none", "transparent")

            if grad is not None:
                name = f"Sh{len(self.shadings)}"
                self.shadings.append((name, grad))
                ops += ["q", path_ops, "W n", f"/{name} sh", "Q"]
            elif has_fill:
                rgb = parse_color(fill)
                if rgb:
                    ops += [self._fill_op(rgb), path_ops, "f*"]
            if has_stroke:
                rgb = parse_color(stroke)
                if rgb:
                    width = shape.numeric("stroke-width") or 1.0
                    ops += [self._stroke_op(rgb), f"{width:.3f} w", path_ops, "S"]
        if self.marks:
            ops.append("Q")  # end the bleed clip
            ops.extend(self._marks_ops())
        ops.append("Q")
        return "\n".join(ops)

    # -- printer's marks -------------------------------------------------

    def _marks_ops(self) -> list[str]:
        """Crop marks at the trim corners, registration marks at the edge
        midpoints and a job slug line, all outside the bleed."""
        doc, b, mm = self.doc, self.bleed, self._mm
        w, h = doc.width, doc.height
        reg_stroke = "1 1 1 1 K" if self.cmyk else "0 0 0 RG"
        reg_fill = "1 1 1 1 k" if self.cmyk else "0 0 0 rg"
        lw = max(0.25 * self.px_dpi / 72.0, 0.2)  # 0.25pt hairline
        ops = ["q", reg_stroke, f"{lw:.3f} w"]

        def line(x1: float, y1: float, x2: float, y2: float) -> None:
            ops.append(f"{x1:.3f} {y1:.3f} m {x2:.3f} {y2:.3f} l S")

        # Crop marks: two per trim corner, starting past the bleed so
        # they never touch bled artwork.
        gap, length = b + mm(1.0), mm(4.0)
        for cx, cy, dx, dy in ((0, 0, -1, -1), (w, 0, 1, -1), (0, h, -1, 1), (w, h, 1, 1)):
            line(cx + dx * gap, cy, cx + dx * (gap + length), cy)
            line(cx, cy + dy * gap, cx, cy + dy * (gap + length))

        # Registration marks: crosshair + circle at each edge midpoint.
        off, radius, cross = b + mm(4.0), mm(1.5), mm(2.5)
        for cx, cy in ((w / 2, -off), (w / 2, h + off), (-off, h / 2), (w + off, h / 2)):
            line(cx - cross, cy, cx + cross, cy)
            line(cx, cy - cross, cx, cy + cross)
            steps = 24
            ring = [
                (cx + radius * np.cos(2 * np.pi * i / steps),
                 cy + radius * np.sin(2 * np.pi * i / steps))
                for i in range(steps)
            ]
            ops.append(f"{ring[0][0]:.3f} {ring[0][1]:.3f} m")
            for px, py in ring[1:]:
                ops.append(f"{px:.3f} {py:.3f} l")
            ops.append("h S")
        ops.append("Q")

        ops.extend(self._slug_ops(reg_fill))
        return ops

    def _slug_ops(self, reg_fill: str) -> list[str]:
        """Job slug line: filename, date, colorspace — bottom-left slug."""
        import datetime

        doc = self.doc
        name = Path(doc.source).name if doc.source else "untitled"
        text = (
            f"{name}  |  {datetime.date.today().isoformat()}  |  "
            f"{self._colorspace_label()}"
        )
        family = first_family("sans-serif") or "sans-serif"
        key = f"{family}:r"
        if key not in self.fonts:
            path, _ = resolve_with_fallback(family, bold=False)
            if not path:
                return []
            self.fonts[key] = _PdfFont(name=f"F{len(self.fonts)}", path=path)
        font = self.fonts[key]
        size = self._mm(2.5)
        y = doc.height + self.bleed + self._mm(8.8)
        return [
            "q",
            "BT",
            reg_fill,
            f"/{font.name} {size:.3f} Tf",
            f"1 0 0 -1 0 {y:.3f} Tm",
            f"({_pdf_escape(text).decode('latin-1')}) Tj",
            "ET",
            "Q",
        ]

    def _colorspace_label(self) -> str:
        if not self.cmyk:
            return "RGB"
        if self._icc is not None:
            return f"CMYK ({self.icc_desc or 'ICC managed'})"
        return "CMYK (unmanaged)"

    def _image_ops(self, index: int, shape: Shape) -> list[str]:
        href = shape.get("href") or shape.get("xlink:href") or ""
        img = _decode_href(href, self.base_dir)
        if img is None:
            return []
        x, y = shape.numeric("x") or 0.0, shape.numeric("y") or 0.0
        w, h = shape.numeric("width"), shape.numeric("height")
        if w is None or h is None:
            return []
        fitted = _fit_slice(img.convert("RGB"), max(1, round(w)), max(1, round(h)))
        space = "/DeviceRGB"
        if self.cmyk and self._icc is not None:
            from PIL import ImageCms

            fitted = ImageCms.applyTransform(fitted, self._icc)
            space = "/DeviceCMYK"
        raw = zlib.compress(fitted.tobytes())
        name = f"Im{index}"
        self.images[index] = (name, raw, fitted.width, fitted.height, space)
        # Images draw in a y-down space, so flip back inside the cm.
        return [
            "q",
            f"{w:.3f} 0 0 {-h:.3f} {x:.3f} {y + h:.3f} cm",
            f"/{name} Do",
            "Q",
        ]

    def _text_ops(self, shape: Shape) -> list[str]:
        if not shape.text:
            return []
        family = first_family(shape.get("font-family")) or "sans-serif"
        bold = is_bold(shape.get("font-weight"))
        key = f"{family}:{'b' if bold else 'r'}"
        if key not in self.fonts:
            path, substituted = resolve_with_fallback(family, bold=bold)
            if not path:
                return []
            if substituted:
                note = (
                    f"font {family!r} is not installed; the PDF embeds a substitute — "
                    "text will not match the intended typeface"
                )
                if note not in self.doc.warnings:
                    self.doc.warnings.append(note)
            self.fonts[key] = _PdfFont(name=f"F{len(self.fonts)}", path=path)
        font = self.fonts[key]

        size = shape.numeric("font-size") or 16.0
        x = shape.numeric("x") or 0.0
        y = shape.numeric("y") or 0.0
        anchor = (shape.get("text-anchor") or "start").strip()
        if anchor in ("middle", "end"):
            from designer.fonts import measure

            width = measure(shape.text, family, size, bold=bold).width
            x -= width / 2 if anchor == "middle" else width
        rgb = parse_color(shape.get("fill") or "#000000") or (0, 0, 0)
        # The content stream is y-flipped; counter-flip the text matrix
        # so glyphs render upright at the document baseline.
        return [
            "q",
            "BT",
            self._fill_op(rgb),
            f"/{font.name} {size:.3f} Tf",
            f"1 0 0 -1 {x:.3f} {y:.3f} Tm",
            f"({_pdf_escape(shape.text).decode('latin-1')}) Tj",
            "ET",
            "Q",
        ]

    # -- font embedding --------------------------------------------------

    def _font_object(self, font: _PdfFont) -> int:
        from PIL import ImageFont

        try:
            pil = ImageFont.truetype(font.path, 1000)
        except OSError:
            pil = None

        widths = []
        for code in range(32, 256):
            char = bytes([code]).decode("cp1252", errors="replace")
            try:
                widths.append(int(round(pil.getlength(char)))) if pil else widths.append(500)
            except Exception:
                widths.append(500)
        ascent, descent = (pil.getmetrics() if pil else (800, 200))

        descriptor_obj = self._reserve()
        file_obj = 0
        if self.embed_fonts:
            raw = Path(font.path).read_bytes()
            compressed = zlib.compress(raw)
            file_obj = self._add(
                b"<< /Length %d /Filter /FlateDecode /Length1 %d >>\nstream\n"
                % (len(compressed), len(raw))
                + compressed
                + b"\nendstream"
            )
        base_name = re.sub(r"[^A-Za-z0-9]", "", Path(font.path).stem) or "Embedded"
        descriptor = (
            f"<< /Type /FontDescriptor /FontName /{base_name} /Flags 32 "
            f"/FontBBox [-200 {-descent} 1200 {ascent}] /ItalicAngle 0 "
            f"/Ascent {ascent} /Descent {-descent} /CapHeight {int(ascent * 0.7)} "
            f"/StemV 80"
        )
        if file_obj:
            descriptor += f" /FontFile2 {file_obj} 0 R"
        descriptor += " >>"
        self._set(descriptor_obj, descriptor.encode("latin-1"))

        widths_str = " ".join(str(w) for w in widths)
        font_dict = (
            f"<< /Type /Font /Subtype /TrueType /BaseFont /{base_name} "
            f"/FirstChar 32 /LastChar 255 /Widths [{widths_str}] "
            f"/FontDescriptor {descriptor_obj} 0 R /Encoding /WinAnsiEncoding >>"
        )
        return self._add(font_dict.encode("latin-1"))

    def _shading_object(self, grad: GradientDef) -> int:
        stops = sorted(grad.stops, key=lambda s: s[0]) or [(0.0, "#000000"), (1.0, "#000000")]
        colors = [parse_color(c) or (0, 0, 0) for _, c in stops]

        def color_str(rgb: RGB) -> str:
            if self.cmyk:
                return " ".join(f"{v:.4f}" for v in self._to_cmyk(rgb))
            return " ".join(f"{v / 255:.4f}" for v in rgb)

        # Stitch pairwise linear ramps so multi-stop gradients are exact.
        functions = []
        for (o1, _), (o2, _), c1, c2 in zip(stops, stops[1:], colors, colors[1:]):
            functions.append(
                self._add(
                    (
                        f"<< /FunctionType 2 /Domain [0 1] /C0 [{color_str(c1)}] "
                        f"/C1 [{color_str(c2)}] /N 1 >>"
                    ).encode("latin-1")
                )
            )
        if not functions:
            functions = [
                self._add(
                    (
                        f"<< /FunctionType 2 /Domain [0 1] /C0 [{color_str(colors[0])}] "
                        f"/C1 [{color_str(colors[0])}] /N 1 >>"
                    ).encode("latin-1")
                )
            ]
            bounds, encode = [], "0 1"
        else:
            bounds = [f"{s[0]:.4f}" for s in stops[1:-1]]
            encode = " ".join("0 1" for _ in functions)

        stitch = self._add(
            (
                f"<< /FunctionType 3 /Domain [0 1] "
                f"/Functions [{' '.join(f'{f} 0 R' for f in functions)}] "
                f"/Bounds [{' '.join(bounds)}] /Encode [{encode}] >>"
            ).encode("latin-1")
        )

        space = "/DeviceCMYK" if self.cmyk else "/DeviceRGB"
        height = self.doc.height
        # The `sh` operator fires inside the y-flipped content CTM, so
        # shading coords are document coords used as-is.
        if grad.kind == "linear":
            x1 = grad.coords.get("x1", 0.0)
            y1 = grad.coords.get("y1", 0.0)
            x2 = grad.coords.get("x2", self.doc.width)
            y2 = grad.coords.get("y2", 0.0)
            body = (
                f"<< /ShadingType 2 /ColorSpace {space} "
                f"/Coords [{x1:.3f} {y1:.3f} {x2:.3f} {y2:.3f}] "
                f"/Function {stitch} 0 R /Extend [true true] >>"
            )
        else:
            cx = grad.coords.get("cx", self.doc.width / 2)
            cy = grad.coords.get("cy", height / 2)
            r = grad.coords.get("r", max(self.doc.width, height) / 2)
            body = (
                f"<< /ShadingType 3 /ColorSpace {space} "
                f"/Coords [{cx:.3f} {cy:.3f} 0 {cx:.3f} {cy:.3f} {r:.3f}] "
                f"/Function {stitch} 0 R /Extend [true true] >>"
            )
        return self._add(body.encode("latin-1"))

    # -- assembly --------------------------------------------------------

    def build(self, dpi: float) -> bytes:
        content = self._content()  # populates fonts/images/shadings

        font_refs = []
        for font in self.fonts.values():
            font.obj = self._font_object(font)
            font_refs.append(f"/{font.name} {font.obj} 0 R")

        image_refs = []
        for _, (name, raw, w, h, space) in self.images.items():
            obj = self._add(
                b"<< /Type /XObject /Subtype /Image /Width %d /Height %d "
                b"/ColorSpace %s /BitsPerComponent 8 /Filter /FlateDecode "
                b"/Length %d >>\nstream\n" % (w, h, space.encode("latin-1"), len(raw))
                + raw
                + b"\nendstream"
            )
            image_refs.append(f"/{name} {obj} 0 R")

        shading_refs = []
        for name, grad in self.shadings:
            obj = self._shading_object(grad)
            shading_refs.append(f"/{name} {obj} 0 R")

        stream = zlib.compress(content.encode("latin-1", errors="replace"))
        content_obj = self._add(
            b"<< /Length %d /Filter /FlateDecode >>\nstream\n" % len(stream)
            + stream
            + b"\nendstream"
        )

        resources = "<< "
        if font_refs:
            resources += f"/Font << {' '.join(font_refs)} >> "
        if image_refs:
            resources += f"/XObject << {' '.join(image_refs)} >> "
        if shading_refs:
            resources += f"/Shading << {' '.join(shading_refs)} >> "
        resources += ">>"

        # Document px -> PDF points (72/inch) at the document's density.
        pt_scale = 72.0 / self.px_dpi
        page_w = (self.doc.width + 2 * self.offset) * pt_scale
        page_h = (self.doc.height + 2 * self.offset) * pt_scale

        boxes = f"/MediaBox [0 0 {page_w:.3f} {page_h:.3f}] "
        if self.offset > 0:
            trim = self.offset * pt_scale
            boxes += (
                f"/TrimBox [{trim:.3f} {trim:.3f} "
                f"{page_w - trim:.3f} {page_h - trim:.3f}] "
            )
            edge = self.slug * pt_scale
            boxes += (
                f"/BleedBox [{edge:.3f} {edge:.3f} "
                f"{page_w - edge:.3f} {page_h - edge:.3f}] "
            )

        pages_obj = self._reserve()
        page_obj = self._add(
            (
                f"<< /Type /Page /Parent {pages_obj} 0 R "
                f"{boxes}"
                f"/Resources {resources} /Contents {content_obj} 0 R "
                f"/UserUnit 1 >>"
            ).encode("latin-1")
        )
        self._set(
            pages_obj,
            f"<< /Type /Pages /Kids [{page_obj} 0 R] /Count 1 >>".encode("latin-1"),
        )
        # Output intent: the press profile travels with the file so the
        # RIP knows what the CMYK numbers mean.
        intents = ""
        if self.cmyk and self.icc_bytes:
            compressed = zlib.compress(self.icc_bytes)
            icc_obj = self._add(
                b"<< /N 4 /Filter /FlateDecode /Length %d >>\nstream\n"
                % len(compressed)
                + compressed
                + b"\nendstream"
            )
            label = _pdf_escape(self.icc_desc or "CMYK output profile").decode("latin-1")
            intent_obj = self._add(
                (
                    f"<< /Type /OutputIntent /S /GTS_PDFX "
                    f"/OutputConditionIdentifier ({label}) /Info ({label}) "
                    f"/DestOutputProfile {icc_obj} 0 R >>"
                ).encode("latin-1")
            )
            intents = f" /OutputIntents [{intent_obj} 0 R]"
        catalog = self._add(
            f"<< /Type /Catalog /Pages {pages_obj} 0 R{intents} >>".encode("latin-1")
        )

        # Content coordinates are in px; scale the whole page down to pt.
        scaled = f"{pt_scale:.6f} 0 0 {pt_scale:.6f} 0 0 cm\n" + content
        stream = zlib.compress(scaled.encode("latin-1", errors="replace"))
        self._set(
            content_obj,
            b"<< /Length %d /Filter /FlateDecode >>\nstream\n" % len(stream)
            + stream
            + b"\nendstream",
        )

        out = bytearray(b"%PDF-1.7\n%\xe2\xe3\xcf\xd3\n")
        offsets = [0]
        for number, body in enumerate(self.objects, start=1):
            offsets.append(len(out))
            out += f"{number} 0 obj\n".encode("latin-1") + body + b"\nendobj\n"
        xref_at = len(out)
        count = len(self.objects) + 1
        out += f"xref\n0 {count}\n".encode("latin-1")
        out += b"0000000000 65535 f \n"
        for offset in offsets[1:]:
            out += f"{offset:010d} 00000 n \n".encode("latin-1")
        out += (
            f"trailer\n<< /Size {count} /Root {catalog} 0 R >>\n"
            f"startxref\n{xref_at}\n%%EOF\n"
        ).encode("latin-1")
        return bytes(out)
