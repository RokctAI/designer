"""Geometry compliance: spacing grid, minimum element size, stroke
widths, and unevaluated transforms."""

from __future__ import annotations

import math

from designer.report import Finding, Severity
from designer.rules.base import Rule
from designer.svg import Document, shape_area
from designer.tokens import DesignSystem

# Attributes that live on the spacing grid, per primitive.
_GRID_ATTRS = {
    "rect": ("x", "y", "width", "height"),
    "circle": ("cx", "cy", "r"),
    "ellipse": ("cx", "cy", "rx", "ry"),
    "line": ("x1", "y1", "x2", "y2"),
    "text": ("x", "y"),
}


class GridSnapRule(Rule):
    id = "layout.grid"
    description = "Primitive geometry must sit on the spacing grid"

    def run(self, doc: Document, system: DesignSystem, autofix: bool) -> list[Finding]:
        findings: list[Finding] = []
        grid = system.grid
        if grid <= 0:
            return findings
        for i, shape in enumerate(doc.shapes):
            attrs = _GRID_ATTRS.get(shape.tag)
            if not attrs:
                continue
            off = []
            for attr in attrs:
                value = shape.numeric(attr)
                if value is None:
                    continue
                snapped = round(value / grid) * grid
                if abs(snapped - value) > 1e-6:
                    off.append((attr, value, snapped))
            if not off:
                continue
            finding = Finding(
                rule=self.id,
                severity=Severity.WARNING,
                message=(
                    f"<{shape.tag}> off the {grid:g}px grid: "
                    + ", ".join(f"{a}={v:g}" for a, v, _ in off)
                ),
                shape_index=i,
            )
            if autofix:
                for attr, _, snapped in off:
                    shape.set(attr, f"{snapped:g}")
                finding.fixed = True
                finding.fix_description = ", ".join(
                    f"{a}: {v:g} -> {s:g}" for a, v, s in off
                )
            findings.append(finding)
        return findings


class MinSizeRule(Rule):
    id = "layout.min-size"
    description = "Elements below the minimum size are noise and are removed"

    def run(self, doc: Document, system: DesignSystem, autofix: bool) -> list[Finding]:
        findings: list[Finding] = []
        min_area = system.min_element_size ** 2
        to_remove: list[int] = []
        for i, shape in enumerate(doc.shapes):
            if shape.tag == "text":
                continue
            area = shape_area(shape, doc)
            if area is None or area >= min_area:
                continue
            finding = Finding(
                rule=self.id,
                severity=Severity.INFO,
                message=(
                    f"<{shape.tag}> area {area:.1f}px² is below the "
                    f"{system.min_element_size:g}px minimum element size (speck/noise)"
                ),
                shape_index=i,
            )
            if autofix:
                to_remove.append(i)
                finding.fixed = True
                finding.fix_description = "removed"
            findings.append(finding)
        for i in reversed(to_remove):
            del doc.shapes[i]
        return findings


class StrokeWidthRule(Rule):
    id = "stroke.width"
    description = "Stroke widths must come from the system's stroke scale"

    def run(self, doc: Document, system: DesignSystem, autofix: bool) -> list[Finding]:
        findings: list[Finding] = []
        allowed = system.stroke_widths
        if not allowed:
            return findings
        for i, shape in enumerate(doc.shapes):
            if not shape.get("stroke") or shape.get("stroke") == "none":
                continue
            width = shape.numeric("stroke-width")
            if width is None:
                width = 1.0  # SVG default
            if any(math.isclose(width, w) for w in allowed):
                continue
            nearest = min(allowed, key=lambda w: abs(w - width))
            finding = Finding(
                rule=self.id,
                severity=Severity.WARNING,
                message=(
                    f"stroke-width {width:g} not in scale "
                    f"{[f'{w:g}' for w in allowed]} (nearest: {nearest:g})"
                ),
                shape_index=i,
            )
            if autofix:
                shape.set("stroke-width", f"{nearest:g}")
                finding.fixed = True
                finding.fix_description = f"stroke-width {width:g} -> {nearest:g}"
            findings.append(finding)
        return findings


class TransformRule(Rule):
    id = "geometry.transform"
    description = "Transforms are opaque to auditing and should be baked in"

    def run(self, doc: Document, system: DesignSystem, autofix: bool) -> list[Finding]:
        findings = []
        for i, shape in enumerate(doc.shapes):
            if shape.get("transform"):
                findings.append(
                    Finding(
                        rule=self.id,
                        severity=Severity.INFO,
                        message=(
                            f"<{shape.tag}> carries transform="
                            f"'{shape.get('transform')}' which the auditor cannot "
                            "evaluate; grid checks on this shape may be inaccurate"
                        ),
                        shape_index=i,
                    )
                )
        return findings
