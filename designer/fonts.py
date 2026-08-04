"""Font resolution and real glyph metrics.

Every text decision the engine makes — does this headline fit its slot,
does it overflow the safe margin, does it collide with the shape next to
it, how wide is it in the PDF — depends on measuring text properly.
Estimating from character counts is off by ~25% on real strings, which
is the difference between a fix that works and one that only looks like
it did.

Resolution order for a font-family: exact file match, fontconfig
(``fc-match``), then a metric-only fallback that is flagged so callers
can report reduced accuracy.
"""

from __future__ import annotations

import functools
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from PIL import ImageFont

# Fallback advance width per em when no font file can be resolved.
# Deliberately generous so estimates over-reserve space rather than
# letting text overflow silently.
FALLBACK_ADVANCE_EM = 0.58
FALLBACK_ASCENT_EM = 0.80
FALLBACK_DESCENT_EM = 0.20


@dataclass
class TextMetrics:
    width: float
    ascent: float
    descent: float
    exact: bool  # False when derived from the fallback estimate

    @property
    def height(self) -> float:
        return self.ascent + self.descent


def first_family(font_family: str | None) -> str:
    """First family name in a CSS font stack."""
    if not font_family:
        return ""
    return font_family.split(",")[0].strip().strip("'\"")


@functools.lru_cache(maxsize=256)
def resolve_font_file(family: str, bold: bool = False, italic: bool = False) -> str | None:
    """Absolute path to a font file for ``family``, or None.

    fontconfig is authoritative when present; it substitutes a metric
    match for unavailable families, so we verify the returned family is
    a plausible match before trusting it.
    """
    if not family:
        return None
    style_bits = []
    if bold:
        style_bits.append("bold")
    if italic:
        style_bits.append("italic")
    pattern = family + (":" + ":".join(style_bits) if style_bits else "")

    if shutil.which("fc-match"):
        try:
            out = subprocess.run(
                ["fc-match", "-f", "%{file}\t%{family}", pattern],
                capture_output=True,
                text=True,
                timeout=5,
            ).stdout
        except (subprocess.SubprocessError, OSError):
            out = ""
        if "\t" in out:
            path, matched = out.split("\t", 1)
            if path and Path(path).exists():
                if _families_match(family, matched):
                    return path
                return None  # fontconfig substituted an unrelated face
    return None


def _normalize(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", name.lower())


def _families_match(requested: str, matched: str) -> bool:
    req = _normalize(requested)
    if not req:
        return False
    for candidate in matched.split(","):
        cand = _normalize(candidate)
        if not cand:
            continue
        if req == cand or req in cand or cand in req:
            return True
    # Generic CSS families always accept whatever fontconfig chose.
    return req in ("sansserif", "serif", "monospace", "cursive", "fantasy")


@functools.lru_cache(maxsize=512)
def _load(path: str, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(path, size)


def resolve_with_fallback(
    family: str | None, bold: bool = False, italic: bool = False
) -> tuple[str | None, bool]:
    """(font path, substituted?).

    When the requested family is not installed, fall back to a generic
    face of the same class rather than a bitmap default — a substituted
    face still renders at the right size, and the caller is told so it
    can report the metric difference instead of hiding it.
    """
    name = first_family(family)
    path = resolve_font_file(name, bold, italic)
    if path:
        return path, False
    lowered = name.lower()
    if "serif" in lowered and "sans" not in lowered:
        generic = "serif"
    elif "mono" in lowered or "courier" in lowered:
        generic = "monospace"
    else:
        generic = "sans-serif"
    for candidate in (generic, "sans-serif", "DejaVu Sans"):
        path = resolve_font_file(candidate, bold, italic)
        if path:
            return path, True
    return None, True


def measure(
    text: str,
    family: str | None,
    size: float,
    bold: bool = False,
    italic: bool = False,
) -> TextMetrics:
    """Measure a single line of text. Falls back to an estimate (with
    ``exact=False``) when the family cannot be resolved."""
    size = max(1.0, float(size))
    path = resolve_font_file(first_family(family), bold, italic)
    if path:
        try:
            # Measure at a large size and scale, so integer point sizes
            # don't quantize the result for small text.
            ref = 100
            font = _load(path, ref)
            width = font.getlength(text) * size / ref
            ascent, descent = font.getmetrics()
            return TextMetrics(
                width=width,
                ascent=ascent * size / ref,
                descent=descent * size / ref,
                exact=True,
            )
        except OSError:
            pass
    return TextMetrics(
        width=FALLBACK_ADVANCE_EM * size * len(text),
        ascent=FALLBACK_ASCENT_EM * size,
        descent=FALLBACK_DESCENT_EM * size,
        exact=False,
    )


def text_bounds(
    x: float,
    y: float,
    text: str,
    family: str | None,
    size: float,
    anchor: str = "start",
    bold: bool = False,
    italic: bool = False,
) -> tuple[float, float, float, float]:
    """Bounding box (min_x, min_y, max_x, max_y) of a rendered text run,
    given its SVG anchor point (x, y is the baseline start/middle/end)."""
    m = measure(text, family, size, bold, italic)
    if anchor == "middle":
        min_x = x - m.width / 2
    elif anchor == "end":
        min_x = x - m.width
    else:
        min_x = x
    return (min_x, y - m.ascent, min_x + m.width, y + m.descent)


def fit_size(
    text: str,
    family: str | None,
    max_width: float,
    max_height: float,
    scale: list[float],
    bold: bool = False,
    italic: bool = False,
) -> float | None:
    """Largest size from ``scale`` whose rendered text fits the box.
    Returns None when even the smallest step overflows."""
    for size in sorted(scale, reverse=True):
        m = measure(text, family, size, bold, italic)
        if m.width <= max_width and m.height <= max_height:
            return size
    return None


def is_bold(shape_weight: str | None) -> bool:
    if not shape_weight:
        return False
    weight = shape_weight.strip().lower()
    if weight in ("bold", "bolder"):
        return True
    try:
        return int(weight) >= 600
    except ValueError:
        return False
