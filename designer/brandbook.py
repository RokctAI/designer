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

"""Brand manual (CI manual) renderer: a DesignSystem in, a PDF out.

Composes a multi-page A4 vector PDF programmatically from a design
system — each page is built as an SVG :class:`~designer.svg.Document`
and the list is handed to :func:`designer.render.render_pdf`, so the
book itself goes through the same rendering path as every deliverable.

Pages:
  1. Cover — brand name on a primary-color field.
  2. Logo (only when a logo is supplied) — the mark centered inside a
     clear-space guide, with a minimum-size note.
  3. Color — one swatch row per token with name, role, HEX, RGB and
     CMYK values, plus the WCAG contrast table the system guarantees.
  4. Typography — the font stack and the type scale at actual size.
  5. Usage — bleed/grid/minimum-size production specs.

The book is set in the system's own fonts and colors, on an 8pt-style
layout grid, so the manual demonstrates the identity it documents.
"""

from __future__ import annotations

from pathlib import Path

from designer.color import RGB, contrast_ratio
from designer.fonts import measure
from designer.render import render_pdf
from designer.svg import Document, Shape
from designer.tokens import ColorToken, DesignSystem

# A4 portrait at the engine's 96 px/inch reference (same as a4-poster).
PAGE_W, PAGE_H = 794.0, 1123.0
GRID = 8.0                    # 8pt-style layout grid
MARGIN = 8 * GRID             # 64px page margin
CONTENT_W = PAGE_W - 2 * MARGIN


class BrandbookError(ValueError):
    pass


# ------------------------------------------------------------- palette


def _token(system: DesignSystem, *names: str) -> ColorToken | None:
    """First token matching any of ``names`` by name, then by role."""
    by_name = {t.name.lower(): t for t in system.colors}
    for name in names:
        tok = by_name.get(name.lower())
        if tok is not None:
            return tok
    for name in names:
        for tok in system.colors:
            if tok.role == name:
                return tok
    return None


def _hex_of(system: DesignSystem, *names: str, default: str) -> str:
    tok = _token(system, *names)
    return tok.hex if tok is not None else default


def _cmyk_formatter(system: DesignSystem):
    """(rgb -> (c,m,y,k) in 0..1, label) — ICC-managed through the
    system's press profile when one is set and usable, else the naive
    conversion labeled as an uncoated approximation."""
    if system.icc_profile:
        try:
            from PIL import Image, ImageCms

            profile = ImageCms.getOpenProfile(str(system.icc_profile))
            transform = ImageCms.buildTransformFromOpenProfiles(
                ImageCms.createProfile("sRGB"), profile, "RGB", "CMYK",
                renderingIntent=ImageCms.Intent.RELATIVE_COLORIMETRIC,
            )
            desc = (ImageCms.getProfileDescription(profile) or "").strip()

            def managed(rgb: RGB) -> tuple[float, float, float, float]:
                pixel = Image.new("RGB", (1, 1), rgb)
                c, m, y, k = ImageCms.applyTransform(pixel, transform).getpixel((0, 0))
                return (c / 255, m / 255, y / 255, k / 255)

            return managed, f"CMYK managed via {desc or 'ICC profile'}"
        except Exception:
            pass  # fall through to the naive path, honestly labeled
    from designer.rules.print_rules import rgb_to_cmyk

    return rgb_to_cmyk, "CMYK uncoated approx. (no ICC profile set)"


# ------------------------------------------------------------ page kit


class _Page:
    """One brandbook page: a Document plus a running layout cursor."""

    def __init__(self, style: "_Style", footer: str = ""):
        self.style = style
        self.doc = Document(width=PAGE_W, height=PAGE_H)
        self.rect(0, 0, PAGE_W, PAGE_H, style.paper)
        self.y = MARGIN
        if footer:
            self.text(MARGIN, PAGE_H - MARGIN / 2, footer, size=10,
                      fill=style.muted)

    def rect(self, x: float, y: float, w: float, h: float, fill: str,
             stroke: str | None = None, stroke_width: float = 1.0) -> Shape:
        attrs = {"x": f"{x:g}", "y": f"{y:g}", "width": f"{w:g}",
                 "height": f"{h:g}", "fill": fill}
        if stroke:
            attrs["stroke"] = stroke
            attrs["stroke-width"] = f"{stroke_width:g}"
        shape = Shape("rect", attrs)
        self.doc.shapes.append(shape)
        return shape

    def text(self, x: float, y: float, content: str, size: float = 12,
             fill: str | None = None, bold: bool = False,
             anchor: str = "start") -> Shape:
        attrs = {
            "x": f"{x:g}", "y": f"{y:g}", "font-size": f"{size:g}",
            "fill": fill or self.style.text,
            "font-family": self.style.family,
        }
        if bold:
            attrs["font-weight"] = "bold"
        if anchor != "start":
            attrs["text-anchor"] = anchor
        shape = Shape("text", attrs, text=content)
        self.doc.shapes.append(shape)
        return shape

    def heading(self, title: str) -> None:
        self.rect(MARGIN, self.y, 6 * GRID, GRID / 2, self.style.accent)
        self.y += 5 * GRID
        self.text(MARGIN, self.y, title, size=32, fill=self.style.ink, bold=True)
        self.y += 6 * GRID


class _Style:
    """Book styling pulled from the system's own tokens."""

    def __init__(self, system: DesignSystem):
        self.family = system.fonts[0] if system.fonts else "sans-serif"
        self.paper = _hex_of(system, "paper", "surface", "background",
                             default="#ffffff")
        self.surface = _hex_of(system, "surface", "paper", default="#f3f4f6")
        self.ink = _hex_of(system, "ink", "text", default="#111827")
        self.text = _hex_of(system, "text", "ink", default="#374151")
        self.muted = _hex_of(system, "neutral-500", "neutral-300",
                             default="#6b7280")
        self.primary = _hex_of(system, "primary", "accent", default="#1a56db")
        self.accent = _hex_of(system, "accent", "primary", default="#1a56db")
        self.on_primary = _hex_of(system, "on-primary", "paper",
                                  default="#ffffff")


# ---------------------------------------------------------------- pages


def _cover_page(system: DesignSystem, style: _Style) -> Document:
    page = _Page(style)
    page.text(MARGIN, 22 * GRID, "Brand manual", size=16, fill=style.muted)
    page.text(MARGIN, 28 * GRID, system.name, size=48, fill=style.ink, bold=True)

    # Primary color field: the identity's core color as the cover motif.
    field_y = 44 * GRID
    page.rect(0, field_y, PAGE_W, PAGE_H - field_y, style.primary)
    page.rect(0, field_y - GRID, PAGE_W, GRID, style.accent)
    page.text(MARGIN, field_y + 8 * GRID, "Primary", size=14, fill=style.on_primary)
    page.text(MARGIN, field_y + 12 * GRID, style.primary.upper(), size=24,
              fill=style.on_primary, bold=True)
    return page.doc


def _logo_shapes(logo: Path) -> Document | None:
    """Parse an SVG logo into a Document; None for raster inputs."""
    if logo.suffix.lower() != ".svg":
        return None
    from designer.svg import parse_svg

    return parse_svg(logo)


def _logo_page(system: DesignSystem, style: _Style, logo: Path) -> Document:
    page = _Page(style, footer=f"{system.name} — logo")
    page.heading("Logo")

    # Centered reproduction inside a clear-space guide. The guide box
    # marks the exclusion zone: nothing else may enter it. Clear space
    # is 25% of the logo's drawn height on every side.
    box_w = 40 * GRID
    logo_doc = _logo_shapes(logo)
    if logo_doc is not None and logo_doc.width and logo_doc.height:
        from designer.transform import affine_document

        scale = min(box_w / logo_doc.width, box_w / logo_doc.height)
        drawn_w = logo_doc.width * scale
        drawn_h = logo_doc.height * scale
        x = (PAGE_W - drawn_w) / 2
        y = page.y + 8 * GRID
        affine_document(logo_doc, scale, x, y)
        clear = drawn_h * 0.25
        page.rect(x - clear, y - clear, drawn_w + 2 * clear, drawn_h + 2 * clear,
                  "none", stroke=style.muted, stroke_width=1)
        page.doc.defs.extend(logo_doc.defs)
        page.doc.shapes.extend(logo_doc.shapes)
        for warning in logo_doc.warnings:
            if warning not in page.doc.warnings:
                page.doc.warnings.append(warning)
    else:
        # Raster logo: embed as an image at a fixed reproduction size.
        drawn_w = drawn_h = box_w
        x = (PAGE_W - drawn_w) / 2
        y = page.y + 8 * GRID
        clear = drawn_h * 0.25
        page.rect(x - clear, y - clear, drawn_w + 2 * clear, drawn_h + 2 * clear,
                  "none", stroke=style.muted, stroke_width=1)
        page.doc.shapes.append(Shape("image", {
            "x": f"{x:g}", "y": f"{y:g}", "width": f"{drawn_w:g}",
            "height": f"{drawn_h:g}", "href": str(logo.resolve()),
        }))

    page.y = y + drawn_h + clear + 8 * GRID
    page.text(PAGE_W / 2, page.y, "Clear space: keep 25% of the logo height "
              "free on every side.", size=12, anchor="middle")
    page.y += 3 * GRID
    min_px = max(system.min_element_size * 6, 24)
    page.text(PAGE_W / 2, page.y,
              f"Minimum size: never reproduce below {min_px:g} px on screen "
              f"or {min_px * 25.4 / 96:.0f} mm in print.",
              size=12, anchor="middle")
    return page.doc


_CONTRAST_PAIRS = (
    ("text", "surface"),
    ("text", "paper"),
    ("ink", "surface"),
    ("on-primary", "primary"),
)


def _color_pages(system: DesignSystem, style: _Style) -> list[Document]:
    to_cmyk, cmyk_label = _cmyk_formatter(system)
    footer = f"{system.name} — color"
    pages: list[Document] = []
    page = _Page(style, footer=footer)
    page.heading("Color")
    page.text(MARGIN, page.y, cmyk_label, size=11, fill=style.muted)
    page.y += 5 * GRID

    row_h = 7 * GRID
    swatch_w, swatch_h = 12 * GRID, 5 * GRID
    for token in system.colors:
        if page.y + row_h > PAGE_H - MARGIN - 30 * GRID:
            pages.append(page.doc)
            page = _Page(style, footer=footer)
            page.heading("Color (continued)")
        r, g, b = token.rgb
        c, m, y_, k = to_cmyk(token.rgb)
        page.rect(MARGIN, page.y, swatch_w, swatch_h, token.hex,
                  stroke=style.muted, stroke_width=0.5)
        text_x = MARGIN + swatch_w + 3 * GRID
        page.text(text_x, page.y + 2 * GRID, token.name, size=14,
                  fill=style.ink, bold=True)
        page.text(text_x + 22 * GRID, page.y + 2 * GRID, token.role, size=11,
                  fill=style.muted)
        page.text(text_x, page.y + 5 * GRID,
                  f"HEX {token.hex.upper()}   RGB {r} {g} {b}   "
                  f"CMYK {c * 100:.0f} {m * 100:.0f} {y_ * 100:.0f} {k * 100:.0f}",
                  size=11)
        page.y += row_h

    # Contrast table: the ratios the palette guarantees.
    page.y += 4 * GRID
    page.text(MARGIN, page.y, "Contrast", size=18, fill=style.ink, bold=True)
    page.y += 4 * GRID
    minimum = system.min_contrast_text
    page.text(MARGIN, page.y, f"Body text requires >= {minimum:g}:1 (WCAG AA).",
              size=11, fill=style.muted)
    page.y += 4 * GRID
    for fg_name, bg_name in _CONTRAST_PAIRS:
        fg, bg = _token(system, fg_name), _token(system, bg_name)
        if fg is None or bg is None:
            continue
        ratio = contrast_ratio(fg.rgb, bg.rgb)
        verdict = "pass" if ratio >= minimum else "check"
        page.rect(MARGIN, page.y - 1.75 * GRID, 6 * GRID, 2.5 * GRID, bg.hex,
                  stroke=style.muted, stroke_width=0.5)
        page.text(MARGIN + 3 * GRID, page.y, "Aa", size=12, fill=fg.hex,
                  anchor="middle")
        page.text(MARGIN + 9 * GRID, page.y,
                  f"{fg.name} on {bg.name}", size=12)
        page.text(MARGIN + 34 * GRID, page.y, f"{ratio:.2f}:1", size=12,
                  fill=style.ink, bold=True)
        page.text(MARGIN + 42 * GRID, page.y, verdict, size=12,
                  fill=style.muted)
        page.y += 3.5 * GRID
    pages.append(page.doc)
    return pages


def _typography_pages(system: DesignSystem, style: _Style) -> list[Document]:
    footer = f"{system.name} — typography"
    pages: list[Document] = []
    page = _Page(style, footer=footer)
    page.heading("Typography")

    stack = list(system.fonts) or ["sans-serif"]
    page.text(MARGIN, page.y, f"Primary typeface: {stack[0]}", size=14,
              fill=style.ink, bold=True)
    page.y += 3.5 * GRID
    if len(stack) > 1:
        page.text(MARGIN, page.y, f"Fallback stack: {', '.join(stack[1:])}",
                  size=11, fill=style.muted)
        page.y += 3.5 * GRID
    page.y += 3 * GRID
    page.text(MARGIN, page.y, "Type scale (shown at actual size):", size=11,
              fill=style.muted)
    page.y += 3 * GRID

    for size in sorted(system.type_scale):
        sample = f"Aa {size:g}px"
        # A size too wide to show at actual size on A4 (large-format
        # scales) becomes a compact spec line instead.
        fits = measure(sample, style.family, size, bold=True).width <= CONTENT_W
        row = (size * 1.1 if fits else 2.5 * GRID) + GRID
        if page.y + row > PAGE_H - MARGIN - 2 * GRID:
            pages.append(page.doc)
            page = _Page(style, footer=footer)
            page.heading("Typography (continued)")
        page.y += row - GRID
        if fits:
            page.text(MARGIN, page.y, sample, size=size, fill=style.ink,
                      bold=True)
        else:
            page.text(MARGIN, page.y, f"{size:g}px — larger than this page; "
                      "use at large-format sizes only", size=12)
        page.y += GRID
    pages.append(page.doc)
    return pages


def _usage_page(system: DesignSystem, style: _Style) -> Document:
    page = _Page(style, footer=f"{system.name} — usage")
    page.heading("Usage rules")

    bleed_mm = system.bleed * 25.4 / 300.0  # print bleed is px at 300dpi
    specs = [
        ("Bleed", f"{system.bleed:g} px at 300 dpi ({bleed_mm:.1f} mm) past "
                  "the trim on every print deliverable"),
        ("Layout grid", f"{system.grid:g} px baseline grid; align all edges "
                        "to grid multiples"),
        ("Minimum element size", f"{system.min_element_size:g} px — nothing "
                                 "smaller survives reproduction"),
        ("Alignment tolerance", f"{system.alignment_tolerance:g} px — edges "
                                "closer than this must align exactly"),
        ("Stroke widths", ", ".join(f"{w:g} px" for w in system.stroke_widths)
                          + " only"),
        ("Palette budget", f"at most {system.max_colors} colors per "
                           "deliverable"),
        ("Text contrast", f">= {system.min_contrast_text:g}:1 body, "
                          f">= {system.min_contrast_large_text:g}:1 large "
                          f"(from {system.large_text_size:g} px)"),
    ]
    if system.min_print_stroke:
        specs.append(("Minimum print stroke",
                      f"{system.min_print_stroke:g} px — thinner lines break "
                      "up on press"))
    if system.max_ink_coverage:
        specs.append(("Ink coverage",
                      f"total ink at most {system.max_ink_coverage:g}% "
                      "(coated stock)"))

    for label, value in specs:
        page.rect(MARGIN, page.y - 1.5 * GRID, GRID / 2, 2 * GRID, style.accent)
        page.text(MARGIN + 2 * GRID, page.y, label, size=13, fill=style.ink,
                  bold=True)
        page.text(MARGIN + 2 * GRID, page.y + 2.5 * GRID, value, size=11)
        page.y += 7 * GRID
    return page.doc


# ----------------------------------------------------------------- API


def build_brandbook(
    system: DesignSystem, logo: str | Path | None = None
) -> list[Document]:
    """Compose the brand manual as a list of A4 page Documents."""
    if not system.colors:
        raise BrandbookError("the design system defines no color tokens")
    style = _Style(system)
    pages = [_cover_page(system, style)]
    if logo is not None:
        logo_path = Path(logo)
        if not logo_path.exists():
            raise BrandbookError(f"logo file not found: {logo_path}")
        pages.append(_logo_page(system, style, logo_path))
    pages.extend(_color_pages(system, style))
    pages.extend(_typography_pages(system, style))
    pages.append(_usage_page(system, style))
    return pages


def render_brandbook(
    system: DesignSystem,
    path: str | Path,
    logo: str | Path | None = None,
    dpi: float = 300.0,
) -> Path:
    """Render the brand manual straight to a multi-page vector PDF."""
    pages = build_brandbook(system, logo)
    return render_pdf(pages, path, dpi=dpi)
