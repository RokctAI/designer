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
from designer.vectorize import ComplexityError
from designer.render import render_pdf, render_png
from designer.template import Item, TemplateData, TemplateError, UnitTooSmall, render as render_template
from designer.report import Finding, Report, Severity

__all__ = [
    "DesignSystem",
    "load_system",
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
