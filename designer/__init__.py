"""designer — a design-system compliance engine.

Takes AI-generated (or human-made) designs as raster images or SVG,
converts rasters to clean vector artwork, and enforces a declarative
design system: brand palette, typography scale, spacing grid, stroke
widths and accessibility contrast — with automatic fixes and a
compliance score.
"""

__version__ = "0.1.0"

from designer.tokens import DesignSystem, load_system
from designer.engine import ComplianceEngine
from designer.report import Finding, Report, Severity

__all__ = [
    "DesignSystem",
    "load_system",
    "ComplianceEngine",
    "Finding",
    "Report",
    "Severity",
    "__version__",
]
