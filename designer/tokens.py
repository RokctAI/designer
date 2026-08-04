"""Design system definition: the declarative standard everything must meet.

A design system is a YAML file of tokens (colors, typography, spacing,
strokes) plus constraints (max palette size, contrast minimums). The
compliance engine never hard-codes taste — it enforces whatever system
you load, so each brand ships its own YAML.
"""

from __future__ import annotations

import importlib.resources
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from designer.color import RGB, parse_color, to_hex


# Roles describe what a color is FOR, so snapping can respect intent:
# a large background area should land on a surface color, body text on
# ink, a small emphasis shape on an accent.
SURFACE_ROLES = ("surface", "background")
TEXT_ROLES = ("ink", "text")
ACCENT_ROLES = ("accent", "primary", "secondary")


@dataclass
class ColorToken:
    name: str
    rgb: RGB
    role: str = "other"

    @property
    def hex(self) -> str:
        return to_hex(self.rgb)


@dataclass
class DesignSystem:
    name: str = "Unnamed system"
    colors: list[ColorToken] = field(default_factory=list)
    max_colors: int = 6
    # Snap threshold: if a color is farther than this (OKLab distance)
    # from every token, snapping is reported as an aggressive change.
    snap_warning_distance: float = 0.18

    gradients_allowed: bool = True
    gradient_max_stops: int = 4

    # Print production (only enforced when the target format is print)
    bleed: float = 0.0            # px of bleed beyond the trim edge
    min_print_stroke: float = 0.0  # thinnest line the press can hold
    max_ink_coverage: float = 0.0  # total CMYK ink %, 0 = unchecked

    # Layout quality
    alignment_tolerance: float = 2.0  # px; edges closer than this should align
    role_aware_snapping: bool = True

    fonts: list[str] = field(default_factory=lambda: ["Inter", "sans-serif"])
    type_scale: list[float] = field(default_factory=lambda: [12, 14, 16, 20, 24, 32, 48, 64])

    grid: float = 8.0
    min_element_size: float = 4.0

    stroke_widths: list[float] = field(default_factory=lambda: [1, 2, 4, 8])

    min_contrast_text: float = 4.5
    min_contrast_large_text: float = 3.0
    large_text_size: float = 24.0

    def token_rgbs(self) -> list[RGB]:
        return [t.rgb for t in self.colors]

    def tokens_for_role(self, roles: tuple[str, ...]) -> list[ColorToken]:
        """Tokens carrying any of ``roles`` (empty list if none do)."""
        return [t for t in self.colors if t.role in roles]

    def token_named(self, rgb: RGB) -> str | None:
        for t in self.colors:
            if t.rgb == rgb:
                return t.name
        return None


def _parse_system(data: dict) -> DesignSystem:
    system = DesignSystem(name=data.get("name", "Unnamed system"))

    color_cfg = data.get("color", {}) or {}
    tokens = color_cfg.get("tokens", {}) or {}
    for name, value in tokens.items():
        # A token is either "name: #hex" or "name: {hex: ..., role: ...}".
        role = "other"
        if isinstance(value, dict):
            role = str(value.get("role", "other"))
            value = value.get("hex")
        rgb = parse_color(str(value))
        if rgb is None:
            raise ValueError(f"Color token {name!r} has unparseable value {value!r}")
        # An unroled token named like a role adopts it, so existing
        # systems get sensible behavior without being rewritten.
        if role == "other":
            lowered = name.lower()
            for candidate in SURFACE_ROLES + TEXT_ROLES + ACCENT_ROLES:
                if candidate in lowered:
                    role = candidate
                    break
        system.colors.append(ColorToken(name=name, rgb=rgb, role=role))
    system.max_colors = int(color_cfg.get("max_colors", system.max_colors))
    system.snap_warning_distance = float(
        color_cfg.get("snap_warning_distance", system.snap_warning_distance)
    )

    gradient_cfg = data.get("gradient", {}) or {}
    system.gradients_allowed = bool(gradient_cfg.get("allowed", system.gradients_allowed))
    system.gradient_max_stops = int(gradient_cfg.get("max_stops", system.gradient_max_stops))

    print_cfg = data.get("print", {}) or {}
    system.bleed = float(print_cfg.get("bleed", system.bleed))
    system.min_print_stroke = float(
        print_cfg.get("min_stroke", system.min_print_stroke)
    )
    system.max_ink_coverage = float(
        print_cfg.get("max_ink_coverage", system.max_ink_coverage)
    )

    type_cfg = data.get("typography", {}) or {}
    if "fonts" in type_cfg:
        system.fonts = [str(f) for f in type_cfg["fonts"]]
    if "scale" in type_cfg:
        system.type_scale = sorted(float(s) for s in type_cfg["scale"])

    layout_cfg = data.get("layout", {}) or {}
    system.grid = float(layout_cfg.get("grid", system.grid))
    system.min_element_size = float(
        layout_cfg.get("min_element_size", system.min_element_size)
    )
    system.alignment_tolerance = float(
        layout_cfg.get("alignment_tolerance", system.alignment_tolerance)
    )
    system.role_aware_snapping = bool(
        layout_cfg.get("role_aware_snapping", system.role_aware_snapping)
    )

    stroke_cfg = data.get("stroke", {}) or {}
    if "widths" in stroke_cfg:
        system.stroke_widths = sorted(float(w) for w in stroke_cfg["widths"])

    a11y_cfg = data.get("accessibility", {}) or {}
    system.min_contrast_text = float(
        a11y_cfg.get("min_contrast_text", system.min_contrast_text)
    )
    system.min_contrast_large_text = float(
        a11y_cfg.get("min_contrast_large_text", system.min_contrast_large_text)
    )
    system.large_text_size = float(
        a11y_cfg.get("large_text_size", system.large_text_size)
    )

    if not system.colors:
        raise ValueError("Design system must define at least one color token")
    return system


def system_from_dict(data: dict) -> DesignSystem:
    """Build a DesignSystem from an already-parsed mapping — same schema
    as the YAML file. This is the integration point for backends that
    store the design system in a database (e.g. a Frappe DocType) and
    serialize it to a dict at run time."""
    return _parse_system(data)


def load_system(path: str | Path | None = None) -> DesignSystem:
    """Load a design system YAML. With no path, loads the bundled default."""
    if path is None:
        ref = importlib.resources.files("designer").joinpath("systems/default.yaml")
        data = yaml.safe_load(ref.read_text(encoding="utf-8"))
    else:
        data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("Design system file must be a YAML mapping")
    return _parse_system(data)
