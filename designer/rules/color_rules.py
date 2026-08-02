"""Palette compliance: every color must be a brand token, and the total
number of distinct colors must stay within the system's cap."""

from __future__ import annotations

from designer.color import nearest_color, parse_color, to_hex
from designer.report import Finding, Severity
from designer.rules.base import Rule
from designer.svg import Document, shape_area
from designer.tokens import DesignSystem

_PAINT_PROPS = ("fill", "stroke")


class PaletteRule(Rule):
    id = "color.palette"
    description = "Every fill and stroke must use a design-system color token"

    def run(self, doc: Document, system: DesignSystem, autofix: bool) -> list[Finding]:
        findings: list[Finding] = []
        tokens = system.token_rgbs()
        token_set = set(tokens)
        for i, shape in enumerate(doc.shapes):
            for prop in _PAINT_PROPS:
                raw = shape.get(prop)
                rgb = parse_color(raw) if raw else None
                if rgb is None or rgb in token_set:
                    continue
                idx, dist = nearest_color(rgb, tokens)
                token = system.colors[idx]
                severity = (
                    Severity.WARNING
                    if dist <= system.snap_warning_distance
                    else Severity.ERROR
                )
                finding = Finding(
                    rule=self.id,
                    severity=severity,
                    message=(
                        f"{prop} {to_hex(rgb)} is not a brand token "
                        f"(nearest: {token.name} {token.hex}, distance {dist:.3f})"
                    ),
                    shape_index=i,
                )
                if autofix:
                    shape.set(prop, token.hex)
                    finding.fixed = True
                    finding.fix_description = f"snapped {prop} to token '{token.name}' ({token.hex})"
                findings.append(finding)
        return findings


class MaxColorsRule(Rule):
    id = "color.max"
    description = "Total distinct colors must not exceed the system cap"

    def run(self, doc: Document, system: DesignSystem, autofix: bool) -> list[Finding]:
        usage: dict[tuple, float] = {}
        for shape in doc.shapes:
            for prop in _PAINT_PROPS:
                rgb = parse_color(shape.get(prop) or "")
                if rgb is None:
                    continue
                area = shape_area(shape, doc) or 1.0
                usage[rgb] = usage.get(rgb, 0.0) + area

        if len(usage) <= system.max_colors:
            return []

        ranked = sorted(usage, key=lambda c: -usage[c])
        keep = ranked[: system.max_colors]
        drop = ranked[system.max_colors :]
        finding = Finding(
            rule=self.id,
            severity=Severity.ERROR,
            message=(
                f"{len(usage)} distinct colors used; system allows {system.max_colors} "
                f"(over: {', '.join(to_hex(c) for c in drop)})"
            ),
        )
        if autofix:
            remap: dict[tuple, tuple] = {}
            for c in drop:
                idx, _ = nearest_color(c, keep)
                remap[c] = keep[idx]
            for shape in doc.shapes:
                for prop in _PAINT_PROPS:
                    rgb = parse_color(shape.get(prop) or "")
                    if rgb in remap:
                        shape.set(prop, to_hex(remap[rgb]))
            finding.fixed = True
            finding.fix_description = (
                "merged least-used colors into their nearest kept color: "
                + ", ".join(f"{to_hex(c)} -> {to_hex(t)}" for c, t in remap.items())
            )
        return [finding]
