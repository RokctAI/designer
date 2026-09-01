# Copyright (c) 2026 ROKCT INTELLIGENCE (PTY) LTD
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as published
# by the Free Software Foundation, version 3.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with this program. If not, see <https://www.gnu.org/licenses/>.

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
from designer.raster import InvalidImageError
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
    "InvalidImageError",
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
