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

"""Print production checks — only active for print formats.

Screen-correct is not press-correct: hairlines disappear, unbled
backgrounds show white slivers when the trim drifts, and heavy ink
coverage smears on newsprint. These are the checks a prepress operator
would run before a publication goes to plate.
"""

from __future__ import annotations

from designer.color import parse_color
from designer.formats import FormatSpec
from designer.geometry import shape_box
from designer.report import Finding, Severity
from designer.rules.base import Rule
from designer.svg import Document
from designer.tokens import DesignSystem


def rgb_to_cmyk(rgb: tuple[int, int, int]) -> tuple[float, float, float, float]:
    """Naive (non-ICC) RGB->CMYK. Adequate for a total-ink sanity check;
    not a substitute for a color-managed workflow."""
    r, g, b = (c / 255.0 for c in rgb)
    k = 1 - max(r, g, b)
    if k >= 1.0:
        return (0.0, 0.0, 0.0, 1.0)
    c = (1 - r - k) / (1 - k)
    m = (1 - g - k) / (1 - k)
    y = (1 - b - k) / (1 - k)
    return (c, m, y, k)


def total_ink(rgb: tuple[int, int, int]) -> float:
    return sum(rgb_to_cmyk(rgb)) * 100.0


class PrintStrokeRule(Rule):
    """Strokes below the press minimum vanish or break up on paper."""

    id = "print.hairline"
    description = "Strokes must be thick enough for the press to hold"

    def __init__(self, spec: FormatSpec):
        self.spec = spec

    def run(self, doc: Document, system: DesignSystem, autofix: bool) -> list[Finding]:
        floor = system.min_print_stroke
        if floor <= 0 or self.spec.category != "print":
            return []
        findings = []
        for i, shape in enumerate(doc.shapes):
            stroke = shape.get("stroke")
            if not stroke or stroke.strip().lower() == "none":
                continue
            width = shape.numeric("stroke-width")
            width = 1.0 if width is None else width
            if width >= floor:
                continue
            eligible = [w for w in system.stroke_widths if w >= floor]
            target = min(eligible) if eligible else floor
            finding = Finding(
                rule=self.id,
                severity=Severity.ERROR,
                message=(
                    f"stroke-width {width:g} is below the {floor:g}px press minimum "
                    "— hairlines drop out in print"
                ),
                shape_index=i,
            )
            if autofix:
                shape.set("stroke-width", f"{target:g}")
                finding.fixed = True
                finding.fix_description = f"stroke-width {width:g} -> {target:g}"
            findings.append(finding)
        return findings


class BleedRule(Rule):
    """Full-bleed artwork must extend past the trim, or a white sliver
    shows when the cut drifts."""

    id = "print.bleed"
    description = "Edge-touching artwork must extend into the bleed"

    def __init__(self, spec: FormatSpec):
        self.spec = spec

    def run(self, doc: Document, system: DesignSystem, autofix: bool) -> list[Finding]:
        bleed = self.spec.bleed if self.spec.bleed is not None else system.bleed
        if bleed <= 0 or self.spec.category != "print":
            return []
        findings = []
        for i, shape in enumerate(doc.shapes):
            box = shape_box(shape)
            if box is None:
                continue
            touches = (
                abs(box[0]) < 1.0
                or abs(box[1]) < 1.0
                or abs(box[2] - doc.width) < 1.0
                or abs(box[3] - doc.height) < 1.0
            )
            if not touches:
                continue
            extends = (
                box[0] <= -bleed + 1
                and box[1] <= -bleed + 1
                and box[2] >= doc.width + bleed - 1
                and box[3] >= doc.height + bleed - 1
            )
            if extends:
                continue
            finding = Finding(
                rule=self.id,
                severity=Severity.WARNING,
                message=(
                    f"<{shape.tag}> reaches the trim edge but does not extend "
                    f"{bleed:g}px into the bleed"
                ),
                shape_index=i,
            )
            if autofix and shape.tag == "rect":
                shape.set("x", f"{-bleed:g}")
                shape.set("y", f"{-bleed:g}")
                shape.set("width", f"{doc.width + 2 * bleed:g}")
                shape.set("height", f"{doc.height + 2 * bleed:g}")
                finding.fixed = True
                finding.fix_description = f"extended {bleed:g}px past every trim edge"
            findings.append(finding)
        return findings


class InkCoverageRule(Rule):
    """Total ink over the press limit smears and offsets, especially on
    newsprint."""

    id = "print.ink"
    description = "Total ink coverage must stay within the press limit"

    def __init__(self, spec: FormatSpec):
        self.spec = spec

    def run(self, doc: Document, system: DesignSystem, autofix: bool) -> list[Finding]:
        limit = system.max_ink_coverage
        if limit <= 0 or self.spec.category != "print":
            return []
        findings = []
        seen: set[tuple] = set()
        for i, shape in enumerate(doc.shapes):
            for prop in ("fill", "stroke"):
                rgb = parse_color(shape.get(prop) or "")
                if rgb is None or rgb in seen:
                    continue
                ink = total_ink(rgb)
                if ink <= limit:
                    continue
                seen.add(rgb)
                findings.append(
                    Finding(
                        rule=self.id,
                        severity=Severity.WARNING,
                        message=(
                            f"{prop} {shape.get(prop)} needs {ink:.0f}% total ink, over "
                            f"the {limit:g}% press limit — it will smear on press. "
                            "Lighten the color or ask the printer for a higher limit."
                        ),
                        shape_index=i,
                    )
                )
        return findings


class RichBlackRule(Rule):
    """Fine black detail must be single-ink black. Rich black (K plus
    C/M/Y) on small text or thin strokes blurs and haloes when the
    plates mis-register; 100% K also overprints cleanly."""

    id = "print.rich_black"
    description = "Small text and thin lines in black must use 100% K only"
    SMALL_TEXT_PX = 24.0
    THIN_STROKE_PX = 3.0

    def __init__(self, spec: FormatSpec):
        self.spec = spec

    def run(self, doc: Document, system: DesignSystem, autofix: bool) -> list[Finding]:
        if self.spec.category != "print":
            return []
        findings = []
        for i, shape in enumerate(doc.shapes):
            checks = []
            if shape.tag == "text":
                if (shape.numeric("font-size") or 16.0) < self.SMALL_TEXT_PX:
                    checks.append("fill")
            stroke_w = shape.numeric("stroke-width")
            if (stroke_w if stroke_w is not None else 1.0) < self.THIN_STROKE_PX:
                checks.append("stroke")
            for prop in checks:
                rgb = parse_color(shape.get(prop) or "")
                if rgb is None:
                    continue
                c, m, y, k = rgb_to_cmyk(rgb)
                if k < 0.9 or c + m + y < 0.05:
                    continue
                finding = Finding(
                    rule=self.id,
                    severity=Severity.WARNING,
                    message=(
                        f"{prop} {shape.get(prop)} is a rich black on fine detail "
                        f"(C{c * 100:.0f} M{m * 100:.0f} Y{y * 100:.0f} K{k * 100:.0f}) "
                        "— it blurs if plates mis-register. Use 100% K (#000000)."
                    ),
                    shape_index=i,
                )
                if autofix:
                    shape.set(prop, "#000000")
                    finding.fixed = True
                    finding.fix_description = f"{prop} -> #000000 (100% K)"
                findings.append(finding)
        return findings


class ImageResolutionRule(Rule):
    """Placed photos below the press resolution print soft or pixelated."""

    id = "print.image_ppi"
    description = "Placed raster images must reach the press resolution"
    MIN_PPI = 300.0  # offset/digital standard; large formats use their own dpi

    def __init__(self, spec: FormatSpec):
        self.spec = spec

    def run(self, doc: Document, system: DesignSystem, autofix: bool) -> list[Finding]:
        if self.spec.category != "print":
            return []
        from pathlib import Path

        from designer.render import _decode_href

        target = self.MIN_PPI if self.spec.dpi <= 96 else min(self.MIN_PPI, self.spec.dpi)
        base_dir = Path(doc.source).parent if doc.source else None
        findings = []
        for i, shape in enumerate(doc.shapes):
            if shape.tag != "image":
                continue
            href = shape.get("href") or shape.get("xlink:href") or ""
            img = _decode_href(href, base_dir)
            w = shape.numeric("width")
            if img is None or not w:
                continue
            inches = w / self.spec.dpi
            ppi = img.width / inches
            if ppi >= target * 0.98:
                continue
            findings.append(Finding(
                rule=self.id,
                severity=Severity.WARNING,
                message=(
                    f"image is {ppi:.0f} ppi at print size, below {target:.0f} ppi "
                    f"— it will print soft. Supply a {img.width * target / ppi:.0f}px-wide "
                    "original or place it smaller."
                ),
                shape_index=i,
            ))
        return findings
