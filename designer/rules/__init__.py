"""Compliance rules. Each rule audits a Document against a DesignSystem
and can optionally repair what it finds."""

from designer.rules.base import Rule
from designer.rules.color_rules import PaletteRule, MaxColorsRule
from designer.rules.geometry_rules import GridSnapRule, MinSizeRule, StrokeWidthRule, TransformRule
from designer.rules.typography_rules import FontRule, TypeScaleRule
from designer.rules.accessibility import ContrastRule

DEFAULT_RULES: list[Rule] = [
    PaletteRule(),
    MaxColorsRule(),
    MinSizeRule(),
    StrokeWidthRule(),
    GridSnapRule(),
    FontRule(),
    TypeScaleRule(),
    ContrastRule(),
    TransformRule(),
]

__all__ = [
    "Rule",
    "DEFAULT_RULES",
    "PaletteRule",
    "MaxColorsRule",
    "GridSnapRule",
    "MinSizeRule",
    "StrokeWidthRule",
    "TransformRule",
    "FontRule",
    "TypeScaleRule",
    "ContrastRule",
]
