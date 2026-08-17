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

"""Format compliance: canvas size, safe margins, minimum text size and
text hierarchy — the rules that matter for posters, social cards,
banners and print, where a logo pipeline has nothing to say.

These rules are only active when the engine is given a target
FormatSpec; they hold it as instance state (the design system stays
brand-scoped, the format is per-deliverable).
"""

from __future__ import annotations

from designer.formats import FormatSpec
from designer.report import Finding, Severity
from designer.rules.base import Rule
from designer.svg import Document, shape_area
from designer.tokens import DesignSystem
from designer.transform import affine_document


class CanvasFormatRule(Rule):
    """Canvas must match the format exactly; fix rescales the artwork
    (uniform, centered) onto the target canvas. Runs FIRST so every
    later rule (grid, type scale...) sees final coordinates."""

    id = "format.canvas"
    description = "Canvas must match the deliverable format"

    def __init__(self, spec: FormatSpec):
        self.spec = spec

    def run(self, doc: Document, system: DesignSystem, autofix: bool) -> list[Finding]:
        spec = self.spec
        if abs(doc.width - spec.width) < 0.5 and abs(doc.height - spec.height) < 0.5:
            return []
        finding = Finding(
            rule=self.id,
            severity=Severity.ERROR,
            message=(
                f"canvas {doc.width:g}x{doc.height:g} does not match format "
                f"'{spec.name}' ({spec.width:g}x{spec.height:g})"
            ),
        )
        if autofix:
            s = min(spec.width / doc.width, spec.height / doc.height)
            tx = (spec.width - doc.width * s) / 2
            ty = (spec.height - doc.height * s) / 2
            affine_document(doc, s, tx, ty)
            old_w, old_h = doc.width, doc.height
            doc.width, doc.height = spec.width, spec.height
            # A full-bleed background must stay full-bleed after
            # letterboxing, not float centered.
            if doc.shapes and doc.shapes[0].tag == "rect":
                rect = doc.shapes[0]
                w, h = rect.numeric("width"), rect.numeric("height")
                if w is not None and h is not None and w * h >= 0.9 * (old_w * s) * (old_h * s):
                    rect.set("x", "0")
                    rect.set("y", "0")
                    rect.set("width", f"{spec.width:g}")
                    rect.set("height", f"{spec.height:g}")
            finding.fixed = True
            finding.fix_description = (
                f"rescaled by {s:.3f} and centered onto {spec.width:g}x{spec.height:g}"
            )
        return [finding]


# Average glyph advance as a fraction of font-size, for estimating a
# text run's width without font metrics. A slight over-estimate on
# purpose, so margin fixes err toward safety.
_CHAR_WIDTH_EM = 0.55


class SafeMarginRule(Rule):
    """Text must sit inside the format's safe margin. The fix accounts
    for text-anchor and an estimated line width, so a right-aligned or
    long line is pulled fully inside — not just its anchor point."""

    id = "format.margin"
    description = "Text must respect the format's safe margin"

    def __init__(self, spec: FormatSpec):
        self.spec = spec

    def run(self, doc: Document, system: DesignSystem, autofix: bool) -> list[Finding]:
        findings: list[Finding] = []
        margin = self.spec.margin * min(doc.width, doc.height)
        if margin <= 0:
            return findings

        def clamp(value: float, lo: float, hi: float) -> float:
            if lo > hi:  # text wider than the safe area: center it
                return (lo + hi) / 2
            out = min(max(value, lo), hi)
            # Land on the spacing grid inside the safe area, so the
            # grid rule never re-moves what this rule placed.
            grid = system.grid
            if grid > 0 and out != value:
                snapped = round(out / grid) * grid
                if snapped < lo:
                    snapped += grid
                if snapped > hi:
                    snapped -= grid
                if lo <= snapped <= hi:
                    out = snapped
            return out

        for i, shape in enumerate(doc.shapes):
            if shape.tag != "text":
                continue
            x, y = shape.numeric("x"), shape.numeric("y")
            if x is None or y is None:
                continue
            size = shape.numeric("font-size") or 16.0
            est_width = _CHAR_WIDTH_EM * size * len(shape.text or "")
            anchor = (shape.get("text-anchor") or "start").strip()
            # Bounds for the ANCHOR such that the whole estimated line
            # stays inside the safe area.
            if anchor == "end":
                lo_x, hi_x = margin + est_width, doc.width - margin
            elif anchor == "middle":
                lo_x = margin + est_width / 2
                hi_x = doc.width - margin - est_width / 2
            else:
                lo_x, hi_x = margin, doc.width - margin - est_width
            nx = clamp(x, lo_x, hi_x)
            ny = clamp(y, margin, doc.height - margin)
            if nx == x and ny == y:
                continue
            finding = Finding(
                rule=self.id,
                severity=Severity.WARNING,
                message=(
                    f"text at ({x:g}, {y:g}) is inside the {margin:g}px safe "
                    f"margin of format '{self.spec.name}'"
                ),
                shape_index=i,
            )
            if autofix:
                shape.set("x", f"{nx:g}")
                shape.set("y", f"{ny:g}")
                finding.fixed = True
                finding.fix_description = f"moved to ({nx:g}, {ny:g})"
            findings.append(finding)
        return findings


class MinTextSizeRule(Rule):
    """Text below the format's legibility floor is bumped to the
    smallest type-scale step at or above the floor."""

    id = "format.min-text"
    description = "Text must stay legible at the format's viewing size"

    def __init__(self, spec: FormatSpec):
        self.spec = spec

    def run(self, doc: Document, system: DesignSystem, autofix: bool) -> list[Finding]:
        findings: list[Finding] = []
        floor = self.spec.min_text_size
        if floor <= 0:
            return findings
        eligible = [s for s in system.type_scale if s >= floor]
        target = min(eligible) if eligible else floor
        for i, shape in enumerate(doc.shapes):
            if shape.tag != "text":
                continue
            size = shape.numeric("font-size")
            if size is None or size >= floor:
                continue
            finding = Finding(
                rule=self.id,
                severity=Severity.WARNING,
                message=(
                    f"font-size {size:g} is below the {floor:g}px legibility "
                    f"floor of format '{self.spec.name}'"
                ),
                shape_index=i,
            )
            if autofix:
                shape.set("font-size", f"{target:g}")
                finding.fixed = True
                finding.fix_description = f"font-size {size:g} -> {target:g}"
            findings.append(finding)
        return findings


class TextHierarchyRule(Rule):
    """Multi-text deliverables need visual hierarchy: at least two
    distinct type-scale levels. Report-only — picking which line is the
    headline is a judgment the user (or a regeneration) should make."""

    id = "type.hierarchy"
    description = "Multiple text elements should span distinct scale levels"

    def run(self, doc: Document, system: DesignSystem, autofix: bool) -> list[Finding]:
        sizes = {
            shape.numeric("font-size")
            for shape in doc.shapes
            if shape.tag == "text" and shape.numeric("font-size") is not None
        }
        if len([s for s in doc.shapes if s.tag == "text"]) >= 2 and len(sizes) < 2:
            return [
                Finding(
                    rule=self.id,
                    severity=Severity.INFO,
                    message=(
                        "all text elements share one size; consider a headline/"
                        "body split across the type scale for hierarchy"
                    ),
                )
            ]
        return []
