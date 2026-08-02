"""Accessibility compliance: WCAG contrast for text.

Contrast is measured against each text element's LOCAL background — the
topmost shape painted beneath the text's anchor point — not a single
document-wide background. White text on a navy panel over a white
canvas is judged against the navy panel.
"""

from __future__ import annotations

from designer.color import RGB, best_contrast_color, contrast_ratio, parse_color, to_hex
from designer.report import Finding, Severity
from designer.rules.base import Rule
from designer.svg import Document, Shape
from designer.tokens import DesignSystem


def _shape_contains(shape: Shape, px: float, py: float) -> bool:
    """Point hit-test. Paths use their flattened bounding box — a
    conservative approximation that is right far more often than a
    whole-document background guess."""
    if shape.tag in ("rect", "image"):
        x, y = shape.numeric("x") or 0.0, shape.numeric("y") or 0.0
        w, h = shape.numeric("width"), shape.numeric("height")
        return w is not None and h is not None and x <= px <= x + w and y <= py <= y + h
    if shape.tag == "circle":
        cx, cy, r = shape.numeric("cx"), shape.numeric("cy"), shape.numeric("r")
        if cx is None or cy is None or r is None:
            return False
        return (px - cx) ** 2 + (py - cy) ** 2 <= r * r
    if shape.tag == "ellipse":
        cx, cy = shape.numeric("cx"), shape.numeric("cy")
        rx, ry = shape.numeric("rx"), shape.numeric("ry")
        if None in (cx, cy, rx, ry) or rx == 0 or ry == 0:
            return False
        return ((px - cx) / rx) ** 2 + ((py - cy) / ry) ** 2 <= 1
    if shape.tag == "path":
        d = shape.attrs.get("d")
        if not d:
            return False
        try:
            from designer.path import path_bounds

            bounds = path_bounds(d)
        except ValueError:
            return False
        if bounds is None:
            return False
        min_x, min_y, max_x, max_y = bounds
        return min_x <= px <= max_x and min_y <= py <= max_y
    return False


def _paint_to_rgb(doc: Document, paint: str | None) -> RGB | None:
    rgb = parse_color(paint) if paint else None
    if rgb is not None:
        return rgb
    grad = doc.gradient_by_ref(paint)
    if grad is not None:
        from designer.rules.color_rules import gradient_mean_color

        return gradient_mean_color(grad)
    return None


def local_background(doc: Document, text_index: int) -> RGB | None:
    """Background color behind a text shape: the topmost shape painted
    before it that contains the text's sample point."""
    text = doc.shapes[text_index]
    x, y = text.numeric("x"), text.numeric("y")
    if x is None or y is None:
        return None
    size = text.numeric("font-size") or 16.0
    # Sample at the visual middle of the first line of glyphs.
    px, py = x + size * 0.5, y - size * 0.35
    for shape in reversed(doc.shapes[:text_index]):
        if shape.tag == "text":
            continue
        if not _shape_contains(shape, px, py):
            continue
        rgb = _paint_to_rgb(doc, shape.get("fill"))
        if rgb is not None:
            return rgb
    return _paint_to_rgb(doc, doc.background_color())


class ContrastRule(Rule):
    id = "a11y.contrast"
    description = "Text must meet WCAG contrast against its local background"

    def run(self, doc: Document, system: DesignSystem, autofix: bool) -> list[Finding]:
        findings: list[Finding] = []
        for i, shape in enumerate(doc.shapes):
            if shape.tag != "text":
                continue
            background = local_background(doc, i)
            if background is None:
                continue  # no measurable background for this text
            fill = parse_color(shape.get("fill") or "#000000")
            if fill is None:
                continue
            size = shape.numeric("font-size") or 16.0
            required = (
                system.min_contrast_large_text
                if size >= system.large_text_size
                else system.min_contrast_text
            )
            ratio = contrast_ratio(fill, background)
            if ratio >= required:
                continue
            finding = Finding(
                rule=self.id,
                severity=Severity.ERROR,
                message=(
                    f"text contrast {ratio:.2f}:1 against its background "
                    f"{to_hex(background)} is below the required {required:g}:1"
                ),
                shape_index=i,
            )
            if autofix:
                replacement = best_contrast_color(background, system.token_rgbs())
                new_ratio = contrast_ratio(replacement, background)
                if new_ratio >= required:
                    token_name = system.token_named(replacement)
                    shape.set("fill", to_hex(replacement))
                    finding.fixed = True
                    finding.fix_description = (
                        f"recolored text to token '{token_name}' ({to_hex(replacement)}), "
                        f"contrast now {new_ratio:.2f}:1"
                    )
                else:
                    finding.fix_description = (
                        "no token in the palette reaches the required contrast "
                        "against this background — needs a palette change"
                    )
            findings.append(finding)
        return findings
