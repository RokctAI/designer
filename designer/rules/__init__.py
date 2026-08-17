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
