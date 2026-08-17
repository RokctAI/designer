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

"""Typography compliance: font whitelist and modular type scale."""

from __future__ import annotations

import math

from designer.report import Finding, Severity
from designer.rules.base import Rule
from designer.svg import Document
from designer.tokens import DesignSystem


def _first_family(font_family: str) -> str:
    return font_family.split(",")[0].strip().strip("'\"")


class FontRule(Rule):
    id = "type.font"
    description = "Text must use a design-system font"

    def run(self, doc: Document, system: DesignSystem, autofix: bool) -> list[Finding]:
        findings: list[Finding] = []
        allowed = {f.lower() for f in system.fonts}
        primary = system.fonts[0] if system.fonts else "sans-serif"
        for i, shape in enumerate(doc.shapes):
            if shape.tag != "text":
                continue
            family = shape.get("font-family")
            if family is None:
                finding = Finding(
                    rule=self.id,
                    severity=Severity.WARNING,
                    message="text has no font-family; renderer default is not brand-controlled",
                    shape_index=i,
                )
                if autofix:
                    shape.set("font-family", primary)
                    finding.fixed = True
                    finding.fix_description = f"set font-family to '{primary}'"
                findings.append(finding)
                continue
            if _first_family(family).lower() in allowed:
                continue
            finding = Finding(
                rule=self.id,
                severity=Severity.ERROR,
                message=f"font-family '{family}' is not in the system font list {system.fonts}",
                shape_index=i,
            )
            if autofix:
                shape.set("font-family", primary)
                finding.fixed = True
                finding.fix_description = f"replaced with primary font '{primary}'"
            findings.append(finding)
        return findings


class TypeScaleRule(Rule):
    id = "type.scale"
    description = "Font sizes must come from the modular type scale"

    def run(self, doc: Document, system: DesignSystem, autofix: bool) -> list[Finding]:
        findings: list[Finding] = []
        scale = system.type_scale
        if not scale:
            return findings
        for i, shape in enumerate(doc.shapes):
            if shape.tag != "text":
                continue
            size = shape.numeric("font-size")
            if size is None:
                continue
            if any(math.isclose(size, s) for s in scale):
                continue
            nearest = min(scale, key=lambda s: abs(s - size))
            finding = Finding(
                rule=self.id,
                severity=Severity.WARNING,
                message=(
                    f"font-size {size:g} is off the type scale "
                    f"{[f'{s:g}' for s in scale]} (nearest: {nearest:g})"
                ),
                shape_index=i,
            )
            if autofix:
                shape.set("font-size", f"{nearest:g}")
                finding.fixed = True
                finding.fix_description = f"font-size {size:g} -> {nearest:g}"
            findings.append(finding)
        return findings
