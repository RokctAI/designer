"""Compliance rules. Each rule audits a Document against a DesignSystem
and can optionally repair what it finds."""

from designer.rules.base import Rule
from designer.rules.color_rules import PaletteRule, GradientRule, MaxColorsRule
from designer.rules.geometry_rules import GridSnapRule, MinSizeRule, StrokeWidthRule, TransformRule
from designer.rules.typography_rules import FontRule, TypeScaleRule
from designer.rules.accessibility import ContrastRule
from designer.rules.capability import CapabilityRule
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
]
