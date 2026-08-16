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

"""designer — a design-system compliance engine.

Takes AI-generated (or human-made) designs as raster images or SVG,
converts rasters to clean vector artwork, and enforces a declarative
design system: brand palette, typography scale, spacing grid, stroke
widths and accessibility contrast — with automatic fixes and a
compliance score.
"""

__version__ = "0.1.0"

from designer.tokens import DesignSystem, load_system, system_from_dict
from designer.engine import ComplianceEngine
from designer.palette import derive_system
from designer.vectorize import ComplexityError
from designer.render import render_pdf, render_png
from designer.template import Item, TemplateData, TemplateError, UnitTooSmall, render as render_template
from designer.report import Finding, Report, Severity

__all__ = [
    "DesignSystem",
    "load_system",
    "derive_system",
    "ComplianceEngine",
    "ComplexityError",
    "render_png",
    "render_pdf",
    "render_template",
    "TemplateData",
    "TemplateError",
    "UnitTooSmall",
    "Item",
    "Finding",
    "Report",
    "Severity",
    "__version__",
]
