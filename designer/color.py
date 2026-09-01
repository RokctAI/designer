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

"""Color math: parsing, sRGB <-> OKLab, perceptual distance, WCAG contrast.

All perceptual operations (nearest brand token, palette merging) run in
OKLab so "closest color" matches what a human designer would pick, not
what raw RGB distance says.
"""

from __future__ import annotations

import math
import re
from typing import Iterable, Sequence

RGB = tuple[int, int, int]

_HEX_RE = re.compile(r"^#?([0-9a-fA-F]{3}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})$")

# Subset of CSS named colors that show up in real SVG output.
NAMED_COLORS: dict[str, str] = {
    "black": "#000000",
    "white": "#ffffff",
    "red": "#ff0000",
    "green": "#008000",
    "blue": "#0000ff",
    "yellow": "#ffff00",
    "orange": "#ffa500",
    "purple": "#800080",
    "gray": "#808080",
    "grey": "#808080",
    "silver": "#c0c0c0",
    "maroon": "#800000",
    "navy": "#000080",
    "teal": "#008080",
    "aqua": "#00ffff",
    "cyan": "#00ffff",
    "fuchsia": "#ff00ff",
    "magenta": "#ff00ff",
    "lime": "#00ff00",
    "olive": "#808000",
    "pink": "#ffc0cb",
    "brown": "#a52a2a",
}


def parse_color(value: str) -> RGB | None:
    """Parse a CSS color into (r, g, b) 0-255. Returns None for
    unpaintable values ("none", "transparent", url refs, gradients)."""
    if value is None:
        return None
    value = value.strip().lower()
    if value in ("", "none", "transparent", "currentcolor", "inherit"):
        return None
    if value.startswith("url("):
        return None
    if value in NAMED_COLORS:
        value = NAMED_COLORS[value]
    m = _HEX_RE.match(value)
    if m:
        h = m.group(1)
        if len(h) == 3:
            h = "".join(c * 2 for c in h)
        return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))
    m = re.match(r"rgba?\(([^)]+)\)", value)
    if m:
        parts = [p.strip() for p in re.split(r"[,\s/]+", m.group(1)) if p.strip()]
        if len(parts) >= 3:
            channels = []
            for p in parts[:3]:
                if p.endswith("%"):
                    channels.append(round(float(p[:-1]) * 2.55))
                else:
                    channels.append(round(float(p)))
            return tuple(max(0, min(255, c)) for c in channels)  # type: ignore[return-value]
    return None


def to_hex(rgb: RGB) -> str:
    return "#{:02x}{:02x}{:02x}".format(*rgb)


def _srgb_to_linear(c: float) -> float:
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def _linear_to_srgb(c: float) -> float:
    return 12.92 * c if c <= 0.0031308 else 1.055 * (c ** (1 / 2.4)) - 0.055


def rgb_to_oklab(rgb: RGB) -> tuple[float, float, float]:
    """sRGB (0-255) to OKLab (Björn Ottosson's transform)."""
    r = _srgb_to_linear(rgb[0] / 255.0)
    g = _srgb_to_linear(rgb[1] / 255.0)
    b = _srgb_to_linear(rgb[2] / 255.0)

    l = 0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b
    m = 0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b
    s = 0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b

    l_, m_, s_ = (v ** (1 / 3) if v > 0 else 0.0 for v in (l, m, s))

    return (
        0.2104542553 * l_ + 0.7936177850 * m_ - 0.0040720468 * s_,
        1.9779984951 * l_ - 2.4285922050 * m_ + 0.4505937099 * s_,
        0.0259040371 * l_ + 0.7827717662 * m_ - 0.8086757660 * s_,
    )


def oklab_to_rgb(lab: tuple[float, float, float]) -> RGB:
    L, a, b = lab
    l_ = L + 0.3963377774 * a + 0.2158037573 * b
    m_ = L - 0.1055613458 * a - 0.0638541728 * b
    s_ = L - 0.0894841775 * a - 1.2914855480 * b

    l, m, s = l_ ** 3, m_ ** 3, s_ ** 3

    r = +4.0767416621 * l - 3.3077115913 * m + 0.2309699292 * s
    g = -1.2684380046 * l + 2.6097574011 * m - 0.3413193965 * s
    bb = -0.0041960863 * l - 0.7034186147 * m + 1.7076147010 * s

    out = []
    for c in (r, g, bb):
        c = _linear_to_srgb(max(0.0, min(1.0, c)))
        out.append(max(0, min(255, round(c * 255))))
    return tuple(out)  # type: ignore[return-value]


def delta_e(a: RGB, b: RGB) -> float:
    """Perceptual distance between two sRGB colors (Euclidean in OKLab).

    Rough scale: < 0.02 nearly indistinguishable, > 0.15 clearly
    different colors."""
    la, lb = rgb_to_oklab(a), rgb_to_oklab(b)
    return math.dist(la, lb)


def nearest_color(target: RGB, candidates: Sequence[RGB]) -> tuple[int, float]:
    """Index of the perceptually nearest candidate and its distance."""
    if not candidates:
        raise ValueError("candidates must be non-empty")
    tl = rgb_to_oklab(target)
    best_i, best_d = 0, float("inf")
    for i, c in enumerate(candidates):
        d = math.dist(tl, rgb_to_oklab(c))
        if d < best_d:
            best_i, best_d = i, d
    return best_i, best_d


def relative_luminance(rgb: RGB) -> float:
    r = _srgb_to_linear(rgb[0] / 255.0)
    g = _srgb_to_linear(rgb[1] / 255.0)
    b = _srgb_to_linear(rgb[2] / 255.0)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast_ratio(a: RGB, b: RGB) -> float:
    """WCAG 2.x contrast ratio, in [1, 21]."""
    la, lb = relative_luminance(a), relative_luminance(b)
    lighter, darker = max(la, lb), min(la, lb)
    return (lighter + 0.05) / (darker + 0.05)


def best_contrast_color(background: RGB, candidates: Iterable[RGB]) -> RGB:
    """Candidate with the highest WCAG contrast against ``background``."""
    return max(candidates, key=lambda c: contrast_ratio(c, background))
