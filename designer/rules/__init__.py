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

"""Compliance rules. Each rule audits a Document against a DesignSystem
and can optionally repair what it finds."""

from designer.rules.base import Rule
from designer.rules.color_rules import PaletteRule, GradientRule, MaxColorsRule
from designer.rules.geometry_rules import GridSnapRule, MinSizeRule, StrokeWidthRule, TransformRule
from designer.rules.typography_rules import FontRule, TypeScaleRule
from designer.rules.accessibility import ContrastRule
from designer.rules.capability import CapabilityRule
from designer.rules.layout_rules import (
    AlignmentRule,
    BalanceRule,
    CollisionRule,
    RhythmRule,
    WhitespaceRule,
)
from designer.rules.print_rules import BleedRule, InkCoverageRule, PrintStrokeRule
from designer.rules.format_rules import (
    CanvasFormatRule,
    MinTextSizeRule,
    SafeMarginRule,
    TextHierarchyRule,
)

DEFAULT_RULES: list[Rule] = [
    PaletteRule(),
    GradientRule(),
    MaxColorsRule(),
    MinSizeRule(),
    StrokeWidthRule(),
    GridSnapRule(),
    FontRule(),
    TypeScaleRule(),
    ContrastRule(),
    CollisionRule(),
    AlignmentRule(),
    RhythmRule(),
    BalanceRule(),
    WhitespaceRule(),
    TextHierarchyRule(),
    TransformRule(),
    CapabilityRule(),
]

__all__ = [
    "Rule",
    "DEFAULT_RULES",
    "PaletteRule",
    "GradientRule",
    "MaxColorsRule",
    "GridSnapRule",
    "MinSizeRule",
    "StrokeWidthRule",
    "TransformRule",
    "FontRule",
    "TypeScaleRule",
    "ContrastRule",
    "CanvasFormatRule",
    "SafeMarginRule",
    "MinTextSizeRule",
    "TextHierarchyRule",
    "CapabilityRule",
    "CollisionRule",
    "AlignmentRule",
    "RhythmRule",
    "BalanceRule",
    "WhitespaceRule",
    "PrintStrokeRule",
    "BleedRule",
    "InkCoverageRule",
]
