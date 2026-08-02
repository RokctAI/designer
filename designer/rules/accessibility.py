"""Accessibility compliance: WCAG contrast for text."""

from __future__ import annotations

from designer.color import best_contrast_color, contrast_ratio, parse_color, to_hex
from designer.report import Finding, Severity
from designer.rules.base import Rule
from designer.svg import Document
from designer.tokens import DesignSystem


class ContrastRule(Rule):
    id = "a11y.contrast"
    description = "Text must meet WCAG contrast against the canvas background"

    def run(self, doc: Document, system: DesignSystem, autofix: bool) -> list[Finding]:
        findings: list[Finding] = []
        bg_raw = doc.background_color()
        background = parse_color(bg_raw) if bg_raw else None
        if background is None:
            return findings  # no reliable background to measure against

        for i, shape in enumerate(doc.shapes):
            if shape.tag != "text":
                continue
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
                    f"text contrast {ratio:.2f}:1 against background {to_hex(background)} "
                    f"is below the required {required:g}:1"
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
