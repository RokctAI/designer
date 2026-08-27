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

"""Design System DocType -> engine schema mapping (SAAS_SPEC section 7).

Pure mapping, no I/O. The output of :func:`engine_dict_from_doc` must
round-trip through ``designer.tokens.system_from_dict`` without error.
"""

from __future__ import annotations

import re
from typing import Any

HEX_RE = re.compile(r"^#[0-9a-fA-F]{6}$")

DEFAULT_TYPE_SCALE = "12,14,16,20,24,32,48,64"
DEFAULT_STROKE_WIDTHS = "1,2,4,8"


def is_valid_hex(value: str) -> bool:
    return bool(HEX_RE.match(value or ""))


def parse_csv_floats(value: str, field_label: str = "value") -> list[float]:
    """Parse a CSV string of numbers ("12, 14,16") into floats.

    Raises ValueError with a user-facing message on garbage input.
    """
    out: list[float] = []
    for part in (value or "").split(","):
        part = part.strip()
        if not part:
            continue
        try:
            out.append(float(part))
        except ValueError:
            raise ValueError(
                f"{field_label} must be a comma-separated list of numbers; "
                f"got {part!r}"
            ) from None
    return out


def _get(doc: Any, key: str, default: Any = None) -> Any:
    """Read a field off a Document, a dict, or any attr-bearing object."""
    if isinstance(doc, dict):
        value = doc.get(key, default)
    else:
        value = getattr(doc, key, default)
    return default if value is None else value


def validate_system_fields(doc: Any) -> list[str]:
    """Return a list of human-readable problems (empty = valid)."""
    problems: list[str] = []
    tokens = _get(doc, "color_tokens", []) or []
    if not tokens:
        problems.append("At least one color token is required")
    for row in tokens:
        hexval = _get(row, "hex", "")
        name = _get(row, "token_name", "?")
        if not is_valid_hex(hexval):
            problems.append(
                f"Color token {name!r}: {hexval!r} is not a 6-digit hex "
                "color like #1a56db"
            )
    for i in (1, 2, 3):
        seed = _get(doc, f"seed_color_{i}", "")
        if seed and not is_valid_hex(str(seed)):
            problems.append(
                f"Seed Color {i}: {seed!r} is not a 6-digit hex color")
    for field, label in (("type_scale", "Type Scale"),
                         ("stroke_widths", "Stroke Widths")):
        try:
            parse_csv_floats(str(_get(doc, field, "") or ""), label)
        except ValueError as exc:
            problems.append(str(exc))
    return problems


def engine_dict_from_doc(doc: Any) -> dict:
    """Serialize a Design System document to the engine schema.

    ``doc`` may be a frappe Document, a plain dict (child tables as
    lists of dicts) or any object exposing the DocType's fieldnames.
    """
    tokens: dict[str, dict] = {}
    for row in _get(doc, "color_tokens", []) or []:
        name = str(_get(row, "token_name", "")).strip()
        if not name:
            continue
        tokens[name] = {
            "hex": str(_get(row, "hex", "")).strip(),
            "role": str(_get(row, "role", "other") or "other"),
        }

    fonts = [str(_get(row, "font_name", "")).strip()
             for row in _get(doc, "fonts", []) or []
             if str(_get(row, "font_name", "")).strip()]

    data: dict = {
        "name": str(_get(doc, "system_name", "Unnamed system")),
        "color": {
            "tokens": tokens,
            "max_colors": int(_get(doc, "max_colors", 6) or 6),
            "snap_warning_distance": float(
                _get(doc, "snap_warning_distance", 0.18) or 0.18),
        },
        "layout": {
            "grid": float(_get(doc, "grid", 8) or 8),
            "min_element_size": float(_get(doc, "min_element_size", 4) or 4),
        },
        "gradient": {
            "allowed": bool(int(_get(doc, "gradient_allowed", 1) or 0)),
            "max_stops": int(_get(doc, "gradient_max_stops", 4) or 4),
        },
        "accessibility": {
            "min_contrast_text": float(_get(doc, "min_contrast_text", 4.5) or 4.5),
            "min_contrast_large_text": float(
                _get(doc, "min_contrast_large_text", 3.0) or 3.0),
            "large_text_size": float(_get(doc, "large_text_size", 24) or 24),
        },
    }

    scale = parse_csv_floats(
        str(_get(doc, "type_scale", DEFAULT_TYPE_SCALE) or DEFAULT_TYPE_SCALE),
        "Type Scale")
    widths = parse_csv_floats(
        str(_get(doc, "stroke_widths", DEFAULT_STROKE_WIDTHS)
            or DEFAULT_STROKE_WIDTHS),
        "Stroke Widths")

    typography: dict = {}
    if fonts:
        typography["fonts"] = fonts
    if scale:
        typography["scale"] = scale
    if typography:
        data["typography"] = typography
    if widths:
        data["stroke"] = {"widths": widths}
    return data


def parse_seed_colors(value) -> list[str]:
    """Normalize a seed-colors argument (list, JSON string, or CSV) to
    2-3 validated hex strings. Raises ValueError otherwise."""
    import json

    if isinstance(value, str):
        stripped = value.strip()
        if stripped.startswith("["):
            try:
                value = json.loads(stripped)
            except ValueError:
                raise ValueError("seed_colors is not valid JSON") from None
        else:
            value = [p for p in stripped.split(",") if p.strip()]
    seeds = [str(v).strip() for v in (value or []) if str(v).strip()]
    if not 2 <= len(seeds) <= 3:
        raise ValueError("Give 2 or 3 seed colors, e.g. "
                         '["#1a56db", "#f59e0b"]')
    for seed in seeds:
        if not is_valid_hex(seed):
            raise ValueError(f"{seed!r} is not a 6-digit hex color like #1a56db")
    return [s.lower() for s in seeds]


def doc_fields_from_engine_dict(data: dict, derived: bool = True) -> dict:
    """Inverse of :func:`engine_dict_from_doc`: engine schema dict ->
    Design System DocType field values (child tables as lists of dicts).
    Used by derive_design_system to persist an engine-derived system as
    ordinary, editable rows."""
    color = (data or {}).get("color", {}) or {}
    tokens = color.get("tokens", {}) or {}
    rows = []
    for name, value in tokens.items():
        if isinstance(value, dict):
            hexval, role = value.get("hex"), value.get("role", "other")
        else:
            hexval, role = value, "other"
        rows.append({"token_name": str(name), "hex": str(hexval),
                     "role": str(role or "other"),
                     "derived": 1 if derived else 0})

    typography = data.get("typography", {}) or {}
    layout = data.get("layout", {}) or {}
    stroke = data.get("stroke", {}) or {}
    gradient = data.get("gradient", {}) or {}
    a11y = data.get("accessibility", {}) or {}

    fields: dict = {"color_tokens": rows}
    if color.get("max_colors") is not None:
        fields["max_colors"] = int(color["max_colors"])
    if color.get("snap_warning_distance") is not None:
        fields["snap_warning_distance"] = float(color["snap_warning_distance"])
    if typography.get("fonts"):
        fields["fonts"] = [{"font_name": str(f)} for f in typography["fonts"]]
    if typography.get("scale"):
        fields["type_scale"] = ",".join(
            _fmt_num(s) for s in typography["scale"])
    if layout.get("grid") is not None:
        fields["grid"] = float(layout["grid"])
    if layout.get("min_element_size") is not None:
        fields["min_element_size"] = float(layout["min_element_size"])
    if stroke.get("widths"):
        fields["stroke_widths"] = ",".join(
            _fmt_num(w) for w in stroke["widths"])
    if gradient.get("allowed") is not None:
        fields["gradient_allowed"] = 1 if gradient["allowed"] else 0
    if gradient.get("max_stops") is not None:
        fields["gradient_max_stops"] = int(gradient["max_stops"])
    if a11y.get("min_contrast_text") is not None:
        fields["min_contrast_text"] = float(a11y["min_contrast_text"])
    if a11y.get("min_contrast_large_text") is not None:
        fields["min_contrast_large_text"] = float(a11y["min_contrast_large_text"])
    if a11y.get("large_text_size") is not None:
        fields["large_text_size"] = float(a11y["large_text_size"])
    return fields


def _fmt_num(value) -> str:
    num = float(value)
    return str(int(num)) if num == int(num) else str(num)
