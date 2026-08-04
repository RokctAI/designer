"""Accessibility compliance: WCAG contrast for text.

Contrast is measured against each text element's LOCAL background — the
topmost shape actually painted beneath the glyphs (exact hit test,
sampled at several points across the real text box) — not a single
document-wide background. White text on a navy panel over a white
canvas is judged against the navy panel, and text straddling a panel
edge is judged by its worst-contrast part.
"""

from __future__ import annotations

from designer.color import RGB, best_contrast_color, contrast_ratio, parse_color, to_hex
from designer.report import Finding, Severity
from designer.rules.base import Rule
from designer.svg import Document, Shape
from designer.tokens import DesignSystem


def _shape_contains(shape: Shape, px: float, py: float) -> bool:
    """Exact point hit-test (even-odd for paths)."""
    from designer.geometry import point_in_shape

    return point_in_shape(shape, px, py)


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
    """Worst-case background behind a text run.

    The text box is sampled at several points (real font metrics), and
    the sampled background with the LOWEST contrast against the text is
    returned — so text straddling a panel edge is judged by its worst
    part, not a lucky one.
    """
    from designer.color import contrast_ratio
    from designer.geometry import shape_box

    text = doc.shapes[text_index]
    box = shape_box(text)
    if box is None:
        x, y = text.numeric("x"), text.numeric("y")
        if x is None or y is None:
            return None
        size = text.numeric("font-size") or 16.0
        box = (x, y - size * 0.75, x + size * 0.5, y)

    fill = parse_color(text.get("fill") or "#000000")
    min_x, min_y, max_x, max_y = box
    samples = [
        ((min_x + max_x) / 2, (min_y + max_y) / 2),
        (min_x + (max_x - min_x) * 0.08, (min_y + max_y) / 2),
        (max_x - (max_x - min_x) * 0.08, (min_y + max_y) / 2),
        ((min_x + max_x) / 2, min_y + (max_y - min_y) * 0.2),
        ((min_x + max_x) / 2, max_y - (max_y - min_y) * 0.2),
    ]

    worst: RGB | None = None
    worst_ratio = float("inf")
    fallback = _paint_to_rgb(doc, doc.background_color())
    for px, py in samples:
        found = None
        for shape in reversed(doc.shapes[:text_index]):
            if shape.tag == "text":
                continue
            if not _shape_contains(shape, px, py):
                continue
            rgb = _paint_to_rgb(doc, shape.get("fill"))
            if rgb is not None:
                found = rgb
                break
        if found is None:
            found = fallback
        if found is None:
            continue
        ratio = contrast_ratio(fill, found) if fill else 0.0
        if ratio < worst_ratio:
            worst_ratio, worst = ratio, found
    return worst


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
