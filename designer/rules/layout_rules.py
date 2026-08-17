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

"""Layout quality: the measurable half of "taste".

Design judgment as a whole isn't computable, but a large part of what
separates amateur from professional layout is: things line up, gaps come
from a consistent scale, nothing collides, and the composition isn't
lopsided. Those are measurable, and this is where they're enforced.

Collision is auto-fixed (moving text out of an overlap is unambiguous);
alignment nudges near-misses onto a shared edge; rhythm and balance are
reported, because "fixing" them means moving artwork the way only a
human should decide.
"""

from __future__ import annotations

from designer.geometry import Box, box_area, boxes_overlap, overlap_area, shape_box
from designer.report import Finding, Severity
from designer.rules.base import Rule
from designer.svg import Document, Shape
from designer.tokens import DesignSystem


def _laid_out(doc: Document) -> list[tuple[int, Shape, Box]]:
    """Shapes with a usable box, excluding full-bleed backgrounds."""
    out = []
    canvas = doc.width * doc.height
    for i, shape in enumerate(doc.shapes):
        box = shape_box(shape)
        if box is None:
            continue
        if box_area(box) >= 0.9 * canvas:
            continue  # background, not a laid-out element
        out.append((i, shape, box))
    return out


class CollisionRule(Rule):
    """Text must not sit on top of other text, and text must not be
    buried under an opaque shape painted after it."""

    id = "layout.collision"
    description = "Elements must not overlap illegibly"

    def run(self, doc: Document, system: DesignSystem, autofix: bool) -> list[Finding]:
        findings: list[Finding] = []
        items = _laid_out(doc)
        texts = [(i, s, b) for i, s, b in items if s.tag == "text"]

        for idx, (i, shape, box) in enumerate(texts):
            for j, other, other_box in texts[idx + 1 :]:
                if not boxes_overlap(box, other_box, tolerance=1.0):
                    continue
                share = overlap_area(box, other_box) / max(
                    1e-6, min(box_area(box), box_area(other_box))
                )
                finding = Finding(
                    rule=self.id,
                    severity=Severity.ERROR if share > 0.25 else Severity.WARNING,
                    message=(
                        f"text {i} overlaps text {j} ({share:.0%} of the smaller box); "
                        "one of them is unreadable"
                    ),
                    shape_index=i,
                )
                if autofix:
                    moved = _separate_vertically(doc, shape, box, other_box, system)
                    if moved is not None:
                        finding.fixed = True
                        finding.fix_description = f"moved text {i} to y={moved:g}"
                    else:
                        finding.fix_description = (
                            "no clear space to move into — needs a layout decision"
                        )
                findings.append(finding)

        # Text covered by a later, opaque, non-background shape.
        for i, shape, box in texts:
            for j, other, other_box in items:
                if j <= i or other.tag == "text":
                    continue
                if _is_transparent(other):
                    continue
                if overlap_area(box, other_box) / max(1e-6, box_area(box)) < 0.6:
                    continue
                findings.append(
                    Finding(
                        rule=self.id,
                        severity=Severity.ERROR,
                        message=(
                            f"text {i} is painted over by <{other.tag}> {j}, which is "
                            "drawn later and opaque — the text is hidden"
                        ),
                        shape_index=i,
                    )
                )
                break
        return findings


def _is_transparent(shape: Shape) -> bool:
    for prop in ("opacity", "fill-opacity"):
        value = shape.numeric(prop)
        if value is not None and value < 0.9:
            return True
    return (shape.get("fill") or "").strip().lower() in ("none", "transparent")


def _separate_vertically(
    doc: Document, shape: Shape, box: Box, other: Box, system: DesignSystem
) -> float | None:
    """Push the text below the obstruction, on-grid, if it still fits."""
    y = shape.numeric("y")
    if y is None:
        return None
    height = box[3] - box[1]
    target = other[3] + (box[3] - box[1]) * 0.15 + (y - box[1])
    grid = system.grid
    if grid > 0:
        target = round(target / grid) * grid
    if target + (box[3] - y) > doc.height:
        return None
    shape.set("y", f"{target:g}")
    return target


class AlignmentRule(Rule):
    """Edges that nearly line up should line up exactly — near-misses
    are the most recognizable tell of unprofessional layout."""

    id = "layout.alignment"
    description = "Near-aligned edges should share an exact coordinate"

    def run(self, doc: Document, system: DesignSystem, autofix: bool) -> list[Finding]:
        findings: list[Finding] = []
        tol = system.alignment_tolerance
        if tol <= 0:
            return findings
        items = _laid_out(doc)
        if len(items) < 2:
            return findings

        # Cluster left edges (the dominant alignment axis in practice).
        edges = sorted((box[0], i, shape) for i, shape, box in items)
        clusters: list[list[tuple[float, int, Shape]]] = []
        for entry in edges:
            if clusters and abs(entry[0] - clusters[-1][-1][0]) <= tol:
                clusters[-1].append(entry)
            else:
                clusters.append([entry])

        for cluster in clusters:
            if len(cluster) < 2:
                continue
            values = [c[0] for c in cluster]
            if max(values) - min(values) < 1e-6:
                continue  # already exactly aligned
            # Snap to the grid-consistent value inside the cluster.
            target = min(values)
            if system.grid > 0:
                snapped = round(target / system.grid) * system.grid
                if abs(snapped - target) <= tol:
                    target = snapped
            for value, i, shape in cluster:
                if abs(value - target) < 1e-6:
                    continue
                finding = Finding(
                    rule=self.id,
                    severity=Severity.WARNING,
                    message=(
                        f"<{shape.tag}> left edge {value:g} is {abs(value - target):.1f}px "
                        f"off an alignment shared by {len(cluster)} elements ({target:g})"
                    ),
                    shape_index=i,
                )
                if autofix and _shift_x(shape, target - value):
                    finding.fixed = True
                    finding.fix_description = f"aligned left edge to {target:g}"
                findings.append(finding)
        return findings


def _shift_x(shape: Shape, dx: float) -> bool:
    if abs(dx) < 1e-9:
        return True
    if shape.tag in ("rect", "image", "text"):
        x = shape.numeric("x")
        if x is None:
            return False
        shape.set("x", f"{x + dx:g}")
        return True
    if shape.tag in ("circle", "ellipse"):
        cx = shape.numeric("cx")
        if cx is None:
            return False
        shape.set("cx", f"{cx + dx:g}")
        return True
    if shape.tag == "path":
        from designer.transform import transform_path

        d = shape.attrs.get("d")
        if not d:
            return False
        try:
            shape.attrs["d"] = transform_path(d, 1.0, dx, 0.0)
        except ValueError:
            return False
        return True
    return False


class RhythmRule(Rule):
    """Vertical gaps between stacked elements should come from the
    spacing scale, not be arbitrary."""

    id = "layout.rhythm"
    description = "Spacing between stacked elements should follow the grid"

    def run(self, doc: Document, system: DesignSystem, autofix: bool) -> list[Finding]:
        grid = system.grid
        if grid <= 0:
            return []
        items = sorted(_laid_out(doc), key=lambda t: t[2][1])
        gaps: list[tuple[float, int]] = []
        for (i, _, a), (j, _, b) in zip(items, items[1:]):
            gap = b[1] - a[3]
            if gap <= 0:
                continue  # overlapping or nested; collision rule's business
            gaps.append((gap, j))
        off = [(gap, j) for gap, j in gaps if abs(gap - round(gap / grid) * grid) > 1.0]
        if not off or len(gaps) < 2:
            return []
        return [
            Finding(
                rule=self.id,
                severity=Severity.INFO,
                message=(
                    f"{len(off)} of {len(gaps)} vertical gaps are off the {grid:g}px "
                    f"spacing scale (e.g. {off[0][0]:.1f}px) — inconsistent rhythm"
                ),
                shape_index=off[0][1],
            )
        ]


class BalanceRule(Rule):
    """Visual weight should not pile up on one side of the canvas."""

    id = "layout.balance"
    description = "Composition should not be visually lopsided"

    def run(self, doc: Document, system: DesignSystem, autofix: bool) -> list[Finding]:
        items = _laid_out(doc)
        if len(items) < 2:
            return []
        total = sum(box_area(box) for _, _, box in items)
        if total <= 0:
            return []
        cx = sum(box_area(box) * (box[0] + box[2]) / 2 for _, _, box in items) / total
        cy = sum(box_area(box) * (box[1] + box[3]) / 2 for _, _, box in items) / total
        dx = (cx - doc.width / 2) / doc.width
        dy = (cy - doc.height / 2) / doc.height
        findings = []
        if abs(dx) > 0.25 or abs(dy) > 0.25:
            side = "right" if dx > 0 else "left"
            vertical = "bottom" if dy > 0 else "top"
            axis = side if abs(dx) >= abs(dy) else vertical
            findings.append(
                Finding(
                    rule=self.id,
                    severity=Severity.INFO,
                    message=(
                        f"visual weight sits {max(abs(dx), abs(dy)):.0%} off-center "
                        f"toward the {axis}; consider rebalancing or committing to an "
                        "intentional asymmetric layout"
                    ),
                )
            )
        return findings


class WhitespaceRule(Rule):
    """Wall-to-wall content reads as cramped; a deliverable needs room
    to breathe."""

    id = "layout.whitespace"
    description = "Layouts need a minimum share of empty space"

    min_ratio = 0.15

    def run(self, doc: Document, system: DesignSystem, autofix: bool) -> list[Finding]:
        items = _laid_out(doc)
        if not items:
            return []
        canvas = doc.width * doc.height
        # Union approximated by clipped sum; good enough to catch "packed".
        covered = min(canvas, sum(box_area(box) for _, _, box in items))
        free = 1.0 - covered / canvas
        if free >= self.min_ratio:
            return []
        return [
            Finding(
                rule=self.id,
                severity=Severity.INFO,
                message=(
                    f"only {free:.0%} of the canvas is empty (target ≥"
                    f"{self.min_ratio:.0%}); the layout is crowded"
                ),
            )
        ]
