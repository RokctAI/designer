# Copyright (c) 2026 ROKCT INTELLIGENCE (PTY) LTD
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

"""Palette derivation: 2-3 seed brand colors in, a full design system out.

Given a primary and an accent (and optionally a support color), derive
everything else a system needs — ink, paper, surfaces, guaranteed-
contrast text colors, a neutral scale — working in OKLCH so lightness
steps look even to a human. The result is a plain dict in the same
schema as the system YAML, so ``system_from_dict`` / ``load_system``
accept it unchanged, and an ``overrides`` mapping deep-merges last so
any derived value can be replaced.
"""

from __future__ import annotations

import math

from designer.color import (
    RGB,
    contrast_ratio,
    oklab_to_rgb,
    parse_color,
    rgb_to_oklab,
    to_hex,
)
from designer.tokens import DesignSystem

# Derivation constants (OKLCH). Fixed values keep the output deterministic.
_INK_L = 0.24          # near-black, tinted toward the primary hue
_INK_MAX_C = 0.03
_PAPER_L = 0.985       # near-white page color
_PAPER_C = 0.005
_SURFACE_L = 0.955     # slightly deeper tinted panel color
_SURFACE_C = 0.012
_TEXT_L = 0.35         # starting point; lightness adjusts until WCAG passes
_NEUTRAL_STEPS = (("neutral-800", 0.35), ("neutral-500", 0.55),
                  ("neutral-300", 0.75), ("neutral-100", 0.92))
_NEUTRAL_MAX_C = 0.035

# 3 mm of bleed expressed in px at 300 dpi.
_BLEED_3MM_300DPI = round(3 / 25.4 * 300, 1)


def _to_lch(rgb: RGB) -> tuple[float, float, float]:
    L, a, b = rgb_to_oklab(rgb)
    return L, math.hypot(a, b), math.atan2(b, a)


def _from_lch(L: float, C: float, h: float) -> RGB:
    return oklab_to_rgb((L, C * math.cos(h), C * math.sin(h)))


def _ensure_contrast(rgb: RGB, background: RGB, minimum: float) -> RGB:
    """Adjust ``rgb``'s lightness (hue/chroma held) until it reaches the
    required WCAG contrast against ``background``. Any background admits
    at least ~4.5:1 against pure black or pure white, so this always
    terminates with a passing color."""
    if contrast_ratio(rgb, background) >= minimum:
        return rgb
    L, C, h = _to_lch(rgb)
    darken = contrast_ratio((0, 0, 0), background) >= contrast_ratio(
        (255, 255, 255), background
    )
    step = -0.01 if darken else 0.01
    for chroma in (C, C / 2, 0.0):
        candidate_l = L
        while 0.0 <= candidate_l <= 1.0:
            candidate = _from_lch(candidate_l, chroma, h)
            if contrast_ratio(candidate, background) >= minimum:
                return candidate
            candidate_l += step
    return (0, 0, 0) if darken else (255, 255, 255)


def _parse_seed(value: str, position: int) -> RGB:
    rgb = parse_color(value) if isinstance(value, str) else None
    if rgb is None:
        raise ValueError(
            f"Seed {position} ({value!r}) is not a valid color; expected hex like '#0F4C81'"
        )
    return rgb


def _deep_merge(base: dict, override: dict) -> dict:
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            _deep_merge(base[key], value)
        else:
            base[key] = value
    return base


def derive_system(
    seeds: list[str], name: str = "Derived palette", overrides: dict | None = None
) -> dict:
    """Derive a complete design-system dict from 2-3 seed brand colors.

    Seed 1 becomes the primary, seed 2 the accent, and an optional seed
    3 a secondary/support color. Everything else — ink, paper, surface,
    WCAG-passing text colors, a neutral scale, typography, layout and
    print defaults — is derived deterministically. ``overrides`` deep-
    merges over the result, so any derived value can be replaced. The
    returned dict is valid input to ``system_from_dict`` and, dumped as
    YAML, to ``load_system``.
    """
    if not isinstance(seeds, (list, tuple)) or not 2 <= len(seeds) <= 3:
        raise ValueError("derive_system needs 2 or 3 seed colors (primary, accent[, secondary])")
    rgbs = [_parse_seed(s, i + 1) for i, s in enumerate(seeds)]
    primary, accent = rgbs[0], rgbs[1]
    p_l, p_c, p_h = _to_lch(primary)

    defaults = DesignSystem()  # engine defaults for everything non-color
    min_text = defaults.min_contrast_text

    ink = _from_lch(_INK_L, min(p_c, _INK_MAX_C), p_h)
    paper = _from_lch(_PAPER_L, _PAPER_C, p_h)
    surface = _from_lch(_SURFACE_L, _SURFACE_C, p_h)
    ink = _ensure_contrast(ink, surface, min_text)

    # Body text must pass on both light backgrounds; passing on the
    # darker surface implies passing on the lighter paper for dark text,
    # but both are enforced explicitly.
    text = _from_lch(_TEXT_L, min(p_c * 0.4, _NEUTRAL_MAX_C), p_h)
    text = _ensure_contrast(text, surface, min_text)
    text = _ensure_contrast(text, paper, min_text)
    on_primary = _ensure_contrast(paper, primary, min_text)

    tokens: dict[str, dict] = {
        "primary": {"hex": to_hex(primary), "role": "primary"},
        "accent": {"hex": to_hex(accent), "role": "accent"},
    }
    if len(rgbs) == 3:
        tokens["secondary"] = {"hex": to_hex(rgbs[2]), "role": "secondary"}
    tokens["ink"] = {"hex": to_hex(ink), "role": "ink"}
    tokens["text"] = {"hex": to_hex(text), "role": "text"}
    tokens["on-primary"] = {"hex": to_hex(on_primary), "role": "text"}
    tokens["surface"] = {"hex": to_hex(surface), "role": "surface"}
    tokens["paper"] = {"hex": to_hex(paper), "role": "surface"}
    neutral_c = min(p_c * 0.3, _NEUTRAL_MAX_C)
    for step_name, step_l in _NEUTRAL_STEPS:
        tokens[step_name] = {"hex": to_hex(_from_lch(step_l, neutral_c, p_h)), "role": "other"}

    data: dict = {
        "name": name,
        "color": {
            "tokens": tokens,
            "max_colors": len(tokens),
            "snap_warning_distance": defaults.snap_warning_distance,
        },
        "gradient": {
            "allowed": defaults.gradients_allowed,
            "max_stops": defaults.gradient_max_stops,
        },
        "typography": {
            "fonts": list(defaults.fonts),
            "scale": list(defaults.type_scale),
        },
        "layout": {
            "grid": defaults.grid,
            "min_element_size": defaults.min_element_size,
            "alignment_tolerance": defaults.alignment_tolerance,
            "role_aware_snapping": defaults.role_aware_snapping,
        },
        "stroke": {"widths": list(defaults.stroke_widths)},
        "print": {
            "bleed": _BLEED_3MM_300DPI,
            "min_stroke": 0.75,
            "max_ink_coverage": 300,
        },
        "accessibility": {
            "min_contrast_text": defaults.min_contrast_text,
            "min_contrast_large_text": defaults.min_contrast_large_text,
            "large_text_size": defaults.large_text_size,
        },
    }
    if overrides:
        _deep_merge(data, overrides)
    return data


def palette_summary(data: dict) -> str:
    """Readable swatch summary of a derived system: hex + role per token
    plus the WCAG contrast ratios the derivation guarantees."""
    tokens = data["color"]["tokens"]
    lines = [f"Design system: {data['name']}", "", "Swatches:"]
    for token_name, spec in tokens.items():
        lines.append(f"  {token_name:16s} {spec['hex']}  ({spec['role']})")

    def _rgb(token: str) -> RGB | None:
        spec = tokens.get(token)
        return parse_color(spec["hex"]) if spec else None

    pairs = [
        ("text", "surface"),
        ("text", "paper"),
        ("ink", "surface"),
        ("on-primary", "primary"),
    ]
    checks = []
    for fg, bg in pairs:
        fg_rgb, bg_rgb = _rgb(fg), _rgb(bg)
        if fg_rgb is not None and bg_rgb is not None:
            checks.append(f"  {fg} on {bg:10s} {contrast_ratio(fg_rgb, bg_rgb):.2f}:1")
    if checks:
        minimum = data.get("accessibility", {}).get("min_contrast_text", 4.5)
        lines += ["", f"Contrast (required >= {minimum:g}:1):"] + checks
    return "\n".join(lines)
