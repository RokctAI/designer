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

"""Preflight for PDFs made elsewhere — the files clients bring to a
print shop. The same gate the engine applies to its own output:
embedded fonts, trim and bleed, image resolution, RGB content and
total ink. Missing fonts block; everything else warns.
"""

from __future__ import annotations

import math
from pathlib import Path

from designer.report import Finding, Report, Severity

PT_PER_MM = 72 / 25.4


def _mat_mul(m, n):
    a, b, c, d, e, f = m
    a2, b2, c2, d2, e2, f2 = n
    return (a * a2 + b * c2, a * b2 + b * d2, c * a2 + d * c2, c * b2 + d * d2,
            e * a2 + f * c2 + e2, e * b2 + f * d2 + f2)


def _resolve(obj):
    return obj.get_object() if hasattr(obj, "get_object") else obj


def _font_embedded(font) -> bool:
    font = _resolve(font)
    subtype = font.get("/Subtype")
    if subtype == "/Type3":
        return True  # glyphs are drawn inside the PDF
    if subtype == "/Type0":
        desc = font.get("/DescendantFonts")
        if not desc:
            return False
        font = _resolve(_resolve(desc)[0])
    fd = font.get("/FontDescriptor")
    if fd is None:
        return False
    fd = _resolve(fd)
    return any(k in fd for k in ("/FontFile", "/FontFile2", "/FontFile3"))


def _is_rgb(cs) -> bool:
    cs = _resolve(cs)
    if cs == "/DeviceRGB":
        return True
    if isinstance(cs, list) and cs and cs[0] == "/ICCBased":
        return int(_resolve(cs[1]).get("/N", 0)) == 3
    return False


class _PageScan:
    def __init__(self, reader, min_ppi: float, max_ink: float):
        self.reader = reader
        self.min_ppi = min_ppi
        self.max_ink = max_ink
        self.fonts_missing: set[str] = set()
        self.low_images: list[float] = []
        self.rgb_images = 0
        self.rgb_vectors = False
        self.heavy_inks: set[tuple] = set()
        self._seen_fonts: set[int] = set()

    def scan(self, content_obj, resources, ctm):
        from pypdf.generic import ContentStream

        resources = _resolve(resources) or {}
        fonts = _resolve(resources.get("/Font")) or {}
        for name, ref in fonts.items():
            key = id(_resolve(ref))
            if key in self._seen_fonts:
                continue
            self._seen_fonts.add(key)
            if not _font_embedded(ref):
                base = str(_resolve(ref).get("/BaseFont", name)).lstrip("/")
                self.fonts_missing.add(base)
        xobjects = _resolve(resources.get("/XObject")) or {}
        try:
            ops = ContentStream(content_obj, self.reader).operations
        except Exception:
            return
        stack = []
        for operands, op in ops:
            if op == b"q":
                stack.append(ctm)
            elif op == b"Q":
                ctm = stack.pop() if stack else ctm
            elif op == b"cm" and len(operands) == 6:
                ctm = _mat_mul(tuple(float(v) for v in operands), ctm)
            elif op in (b"rg", b"RG"):
                vals = [float(v) for v in operands]
                if len(set(vals)) > 1:  # pure greys are harmless
                    self.rgb_vectors = True
            elif op in (b"k", b"K") and len(operands) == 4:
                cmyk = tuple(round(float(v), 3) for v in operands)
                if min(cmyk) >= 0.99:
                    continue  # registration colour (crop/reg marks), meant to hit every plate
                if sum(cmyk) * 100 > self.max_ink:
                    self.heavy_inks.add(cmyk)
            elif op == b"Do" and operands:
                xo = xobjects.get(operands[0])
                if xo is None:
                    continue
                xo = _resolve(xo)
                sub = xo.get("/Subtype")
                if sub == "/Image":
                    width_pt = math.hypot(ctm[0], ctm[1])
                    if width_pt > 0:
                        ppi = float(xo.get("/Width", 0)) / (width_pt / 72)
                        if ppi < self.min_ppi * 0.98:
                            self.low_images.append(ppi)
                    if _is_rgb(xo.get("/ColorSpace")):
                        self.rgb_images += 1
                elif sub == "/Form":
                    m = xo.get("/Matrix")
                    inner = _mat_mul(tuple(float(v) for v in m), ctm) if m else ctm
                    self.scan(xo, xo.get("/Resources", resources), inner)


def preflight_pdf(path: str | Path, min_ppi: float = 300.0, max_ink: float = 300.0,
                  min_bleed_mm: float = 3.0) -> Report:
    """Check a client PDF for press. Returns a Report; ``report.blocked``
    is True when it must not go to plate as-is."""
    from pypdf import PdfReader

    path = Path(path)
    report = Report(system_name="preflight", target=path.name)
    add = report.findings.append
    try:
        reader = PdfReader(str(path))
        pages = list(reader.pages)
    except Exception as exc:
        add(Finding(rule="preflight.read", severity=Severity.ERROR, blocking=True,
                    message=f"cannot read PDF ({exc})"))
        return report
    if reader.is_encrypted:
        add(Finding(rule="preflight.read", severity=Severity.ERROR, blocking=True,
                    message="PDF is password-protected; ask the client for an open file"))
        return report

    scan = _PageScan(reader, min_ppi, max_ink)
    sizes = set()
    for n, page in enumerate(pages, 1):
        media = page.mediabox
        sizes.add((round(float(page.trimbox.width) / PT_PER_MM),
                   round(float(page.trimbox.height) / PT_PER_MM)))
        if "/TrimBox" not in page:
            add(Finding(rule="preflight.bleed", severity=Severity.WARNING,
                        message=f"page {n}: no trim box, so bleed can't be verified — "
                        "export with 'use document bleed' and crop marks"))
        else:
            trim = page.trimbox
            bleed = min(float(trim.left) - float(media.left),
                        float(media.right) - float(trim.right),
                        float(trim.bottom) - float(media.bottom),
                        float(media.top) - float(trim.top)) / PT_PER_MM
            if bleed < min_bleed_mm - 0.1:
                add(Finding(rule="preflight.bleed", severity=Severity.WARNING,
                            message=f"page {n}: {max(bleed, 0):.1f}mm bleed, needs "
                            f"{min_bleed_mm:g}mm — background colour may show a white edge"))
        contents = page.get_contents()
        if contents is not None:
            scan.scan(contents, page.get("/Resources"), (1, 0, 0, 1, 0, 0))

    for font in sorted(scan.fonts_missing):
        add(Finding(rule="preflight.fonts", severity=Severity.ERROR, blocking=True,
                    message=f"font '{font}' is not embedded — text will reflow or "
                    "substitute at the RIP. Re-export with fonts embedded or outlined"))
    if scan.low_images:
        worst = min(scan.low_images)
        add(Finding(rule="preflight.image_ppi", severity=Severity.WARNING,
                    message=f"{len(scan.low_images)} image(s) below {min_ppi:.0f} ppi "
                    f"(lowest {worst:.0f} ppi) — will print soft"))
    if scan.rgb_images:
        add(Finding(rule="preflight.rgb", severity=Severity.WARNING,
                    message=f"{scan.rgb_images} RGB image(s) — colours will shift when "
                    "converted to CMYK; convert with the press ICC profile"))
    if scan.rgb_vectors:
        add(Finding(rule="preflight.rgb", severity=Severity.WARNING,
                    message="RGB vector colours — convert to CMYK before plate"))
    for cmyk in sorted(scan.heavy_inks):
        c, m, y, k = (v * 100 for v in cmyk)
        add(Finding(rule="preflight.ink", severity=Severity.WARNING,
                    message=f"C{c:.0f} M{m:.0f} Y{y:.0f} K{k:.0f} = {c + m + y + k:.0f}% "
                    f"total ink, over the {max_ink:g}% limit — will smear"))
    if len(sizes) > 1:
        add(Finding(rule="preflight.pages", severity=Severity.INFO,
                    message=f"mixed page sizes: {', '.join(f'{w}x{h}mm' for w, h in sorted(sizes))}"))
    return report
