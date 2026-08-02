"""Palette compliance: every color (flat or gradient stop) must be a
brand token, and the total number of distinct colors must stay within
the system's cap."""

from __future__ import annotations

from designer.color import nearest_color, oklab_to_rgb, parse_color, rgb_to_oklab, to_hex
from designer.report import Finding, Severity
from designer.rules.base import Rule
from designer.svg import Document, GradientDef, shape_area
from designer.tokens import DesignSystem

_PAINT_PROPS = ("fill", "stroke")


def gradient_mean_color(grad: GradientDef) -> tuple | None:
    """Perceptual average of a gradient's stops (for flattening and for
    contrast estimates)."""
    labs = []
    for _, color in grad.stops:
        rgb = parse_color(color)
        if rgb is not None:
            labs.append(rgb_to_oklab(rgb))
    if not labs:
        return None
    mean = tuple(sum(c[i] for c in labs) / len(labs) for i in range(3))
    return oklab_to_rgb(mean)  # type: ignore[arg-type]


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


class GradientRule(Rule):
    id = "color.gradient"
    description = "Gradients must be allowed by the system and use token stops"

    def run(self, doc: Document, system: DesignSystem, autofix: bool) -> list[Finding]:
        findings: list[Finding] = []
        tokens = system.token_rgbs()
        token_set = set(tokens)

        for i, shape in enumerate(doc.shapes):
            for prop in _PAINT_PROPS:
                grad = doc.gradient_by_ref(shape.get(prop))
                if grad is None:
                    continue

                if not system.gradients_allowed:
                    finding = Finding(
                        rule=self.id,
                        severity=Severity.ERROR,
                        message=(
                            f"{prop} uses gradient '{grad.id}' but the design "
                            "system does not allow gradients"
                        ),
                        shape_index=i,
                    )
                    if autofix:
                        mean = gradient_mean_color(grad)
                        idx, _ = nearest_color(mean or (128, 128, 128), tokens)
                        token = system.colors[idx]
                        shape.set(prop, token.hex)
                        self._drop_if_unused(doc, grad)
                        finding.fixed = True
                        finding.fix_description = (
                            f"flattened gradient to token '{token.name}' ({token.hex})"
                        )
                    findings.append(finding)
                    continue

                findings.extend(
                    self._check_stops(doc, i, grad, system, token_set, tokens, autofix)
                )
        return findings

    def _check_stops(self, doc, shape_index, grad, system, token_set, tokens, autofix):
        findings = []
        for si, (offset, color) in enumerate(list(grad.stops)):
            rgb = parse_color(color)
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
                    f"gradient '{grad.id}' stop {si} color {to_hex(rgb)} is not a "
                    f"brand token (nearest: {token.name} {token.hex}, distance {dist:.3f})"
                ),
                shape_index=shape_index,
            )
            if autofix:
                grad.stops[si] = (offset, token.hex)
                finding.fixed = True
                finding.fix_description = f"snapped stop {si} to token '{token.name}'"
            findings.append(finding)

        if len(grad.stops) > system.gradient_max_stops:
            finding = Finding(
                rule=self.id,
                severity=Severity.WARNING,
                message=(
                    f"gradient '{grad.id}' has {len(grad.stops)} stops; system "
                    f"allows {system.gradient_max_stops}"
                ),
                shape_index=shape_index,
            )
            if autofix:
                grad.stops = _thin_stops(grad.stops, system.gradient_max_stops)
                finding.fixed = True
                finding.fix_description = f"reduced to {len(grad.stops)} stops"
            findings.append(finding)
        return findings

    @staticmethod
    def _drop_if_unused(doc: Document, grad: GradientDef) -> None:
        for shape in doc.shapes:
            for prop in _PAINT_PROPS:
                if doc.gradient_by_ref(shape.get(prop)) is grad:
                    return
        doc.defs.remove(grad)


def _thin_stops(stops: list[tuple[float, str]], n: int) -> list[tuple[float, str]]:
    """Keep endpoints plus evenly sampled interior stops."""
    if len(stops) <= n or n < 2:
        return stops
    picks = {0, len(stops) - 1}
    for k in range(1, n - 1):
        picks.add(round(k * (len(stops) - 1) / (n - 1)))
    return [stops[i] for i in sorted(picks)]


class MaxColorsRule(Rule):
    id = "color.max"
    description = "Total distinct colors must not exceed the system cap"

    def run(self, doc: Document, system: DesignSystem, autofix: bool) -> list[Finding]:
        usage: dict[tuple, float] = {}
        stop_owners: dict[tuple, list] = {}  # color -> gradients using it
        for shape in doc.shapes:
            area = shape_area(shape, doc) or 1.0
            for prop in _PAINT_PROPS:
                raw = shape.get(prop)
                grad = doc.gradient_by_ref(raw)
                if grad is not None:
                    for _, stop_color in grad.stops:
                        rgb = parse_color(stop_color)
                        if rgb is None:
                            continue
                        usage[rgb] = usage.get(rgb, 0.0) + area / max(1, len(grad.stops))
                        stop_owners.setdefault(rgb, []).append(grad)
                    continue
                rgb = parse_color(raw or "")
                if rgb is None:
                    continue
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
            for grad in doc.defs:
                grad.stops = [
                    (t, to_hex(remap[rgb]) if (rgb := parse_color(c)) in remap else c)
                    for t, c in grad.stops
                ]
            finding.fixed = True
            finding.fix_description = (
                "merged least-used colors into their nearest kept color: "
                + ", ".join(f"{to_hex(c)} -> {to_hex(t)}" for c, t in remap.items())
            )
        return [finding]
