# Copyright (c) 2026 RokctAI
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
