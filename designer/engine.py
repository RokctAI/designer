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

"""Compliance engine: orchestrates audit and auto-fix over a document.

Rule order matters and is deliberate:
  palette snap -> color cap -> noise removal -> stroke/grid/typography
  -> contrast last, so contrast is measured against final colors.
"""

from __future__ import annotations

from pathlib import Path

from designer.formats import FormatSpec, get_format
from designer.report import Report
from designer.rules import DEFAULT_RULES, Rule
from designer.rules.format_rules import CanvasFormatRule, MinTextSizeRule, SafeMarginRule
from designer.rules.print_rules import BleedRule, InkCoverageRule, PrintStrokeRule
from designer.svg import Document, parse_svg
from designer.tokens import DesignSystem
from designer.vectorize import VectorizeOptions, vectorize_file

RASTER_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif", ".tiff", ".tif"}


class ComplianceEngine:
    def __init__(
        self,
        system: DesignSystem,
        rules: list[Rule] | None = None,
        format: FormatSpec | str | None = None,
    ):
        self.system = system
        if isinstance(format, str):
            format = get_format(format, extra=system.formats)
        self.format = format
        base = rules if rules is not None else list(DEFAULT_RULES)
        if format is not None:
            # Canvas rescale runs first so every later rule (grid, type
            # scale...) operates in final coordinates; margin/legibility
            # run last, after typography has settled.
            base = [
                CanvasFormatRule(format),
                *base,
                SafeMarginRule(format),
                MinTextSizeRule(format),
            ]
            if format.category == "print":
                base += [
                    PrintStrokeRule(format),
                    BleedRule(format),
                    InkCoverageRule(format),
                ]
        self.rules = base

    def audit(self, doc: Document) -> Report:
        """Check only — the document is not modified."""
        return self._run(doc, autofix=False)

    def comply(self, doc: Document) -> Report:
        """Check and repair in place. Findings the rules could resolve
        are marked fixed; whatever remains needs a human decision."""
        return self._run(doc, autofix=True)

    def _run(self, doc: Document, autofix: bool) -> Report:
        report = Report(
            system_name=self.system.name,
            target=doc.source or "<in-memory document>",
        )
        # Vendor dielines are cut geometry, not artwork: rules must
        # neither audit nor fix them. They ride on top of the paint
        # order, so they re-enter at the end.
        from designer.svg import is_dieline

        dielines = [s for s in doc.shapes if is_dieline(s)]
        if dielines:
            doc.shapes = [s for s in doc.shapes if not is_dieline(s)]
        try:
            for rule in self.rules:
                report.findings.extend(rule.run(doc, self.system, autofix))
        finally:
            doc.shapes.extend(dielines)
        return report

    # ------------------------------------------------------- pipelines

    def load(
        self,
        path: str | Path,
        vector_options: VectorizeOptions | None = None,
    ) -> Document:
        """Load any supported design file as a Document. Rasters are
        vectorized first; SVGs are parsed directly."""
        suffix = Path(path).suffix.lower()
        if suffix in RASTER_SUFFIXES:
            return vectorize_file(path, vector_options)
        if suffix == ".svg":
            return parse_svg(path)
        raise ValueError(
            f"Unsupported file type {suffix!r}; expected an SVG or raster image"
        )
