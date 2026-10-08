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

"""Design System DocType <-> canonical design-system document.

The canonical document is the product-neutral contract described in
``docs/DESIGN_SYSTEM_CONTRACT.md``: the same mapping the system YAML
files hold, versioned by ``schema_version``. Designer, StartupOS and
any future product read it and ignore what they don't understand;
product-only settings live under ``extensions.<product>``.

Pure mapping, no I/O. The output of :func:`engine_dict_from_doc` must
round-trip through ``designer.tokens.system_from_dict`` without error.
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
from typing import Any

HEX_RE = re.compile(r"^#[0-9a-fA-F]{6}$")
NAMESPACE_RE = re.compile(r"^[a-z][a-z0-9_-]{0,39}$")

DEFAULT_TYPE_SCALE = "12,14,16,20,24,32,48,64"
DEFAULT_STROKE_WIDTHS = "1,2,4,8"

# Version of the canonical document's shape. Bump only for a change an
# existing reader would misread; adding an optional section is not one.
SCHEMA_VERSION = 1

# What a color is FOR. Must match the Design Color Token "role" Select
# options; "muted" is a legacy option no reader assigns meaning to.
COLOR_ROLES = ("primary", "secondary", "accent", "ink", "text",
               "surface", "background", "muted", "other")

# Scalar DocType fields the canonical document carries. A document that
# omits one means "use the default", which an empty field also means.
CORE_SCALAR_FIELDS = ("max_colors", "snap_warning_distance", "type_scale",
                      "grid", "min_element_size", "stroke_widths",
                      "gradient_allowed", "gradient_max_stops",
                      "min_contrast_text", "min_contrast_large_text",
                      "large_text_size", "print_bleed", "print_min_stroke",
                      "print_max_ink_coverage", "brand_name")

# Settings the Designer engine reads that are not part of the core
# contract. On import they are kept under extensions.designer (which
# the engine reads back) instead of being dropped.
DESIGNER_ONLY_PATHS = (("layout", "alignment_tolerance"),
                       ("layout", "role_aware_snapping"),
                       ("print", "icc_profile"),
                       ("formats",))


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
        role = _get(row, "role", "other") or "other"
        if role not in COLOR_ROLES:
            problems.append(
                f"Color token {name!r}: role {role!r} is not one of "
                + ", ".join(COLOR_ROLES))
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
    seen: set[str] = set()
    for row in _get(doc, "extensions", []) or []:
        namespace = str(_get(row, "namespace", "") or "")
        if not NAMESPACE_RE.match(namespace):
            problems.append(
                f"Extension namespace {namespace!r} must be a lowercase "
                "product name like 'designer' or 'web'")
        elif namespace in seen:
            problems.append(f"Extension namespace {namespace!r} is repeated")
        seen.add(namespace)
        try:
            _extension_data(row)
        except ValueError as exc:
            problems.append(f"Extension {namespace!r}: {exc}")
    return problems


def _extension_data(row: Any) -> dict:
    """An extension row's data as a dict (stored as a JSON field)."""
    data = _get(row, "data", None)
    if data in (None, ""):
        return {}
    if isinstance(data, str):
        try:
            data = json.loads(data)
        except ValueError:
            raise ValueError("data is not valid JSON") from None
    if not isinstance(data, dict):
        raise ValueError("data must be a JSON object")
    return data


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
        "schema_version": SCHEMA_VERSION,
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
        # 0 = no requirement / unchecked, which is also what a system
        # without these fields meant before they existed.
        "print": {
            "bleed": float(_get(doc, "print_bleed", 0) or 0),
            "min_stroke": float(_get(doc, "print_min_stroke", 0) or 0),
            "max_ink_coverage": float(
                _get(doc, "print_max_ink_coverage", 0) or 0),
        },
    }
    brand_name = str(_get(doc, "brand_name", "") or "").strip()
    if brand_name:
        data["brand"] = {"name": brand_name}

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
    extensions = {str(_get(row, "namespace")): _extension_data(row)
                  for row in _get(doc, "extensions", []) or []
                  if _get(row, "namespace")}
    if extensions:
        data["extensions"] = extensions
    return data


def fingerprint(system: dict) -> str:
    """Content identity of a canonical document: equal documents give
    equal fingerprints whatever their key order. A consumer records it
    to know exactly which definition it used."""
    body = json.dumps(system, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, default=str)
    return "sha256:" + hashlib.sha256(body.encode("utf-8")).hexdigest()


def merge_patch(target: dict, patch: dict) -> dict:
    """RFC 7386 JSON merge patch: maps merge, ``None`` removes a key,
    anything else (lists included) replaces. Returns a new dict."""
    result = copy.deepcopy(target) if isinstance(target, dict) else {}
    for key, value in (patch or {}).items():
        if value is None:
            result.pop(key, None)
        elif isinstance(value, dict):
            result[key] = merge_patch(result.get(key, {}), value)
        else:
            result[key] = copy.deepcopy(value)
    return result


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
    ordinary, editable rows, and by create/update_design_system to
    import a canonical document. Designer-only settings outside the
    core fields go to ``extensions.designer`` rather than being lost."""
    data = _with_designer_settings_in_extension(data or {})
    color = data.get("color", {}) or {}
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
    print_cfg = data.get("print", {}) or {}
    for key, field in (("bleed", "print_bleed"),
                       ("min_stroke", "print_min_stroke"),
                       ("max_ink_coverage", "print_max_ink_coverage")):
        if print_cfg.get(key) is not None:
            fields[field] = float(print_cfg[key])
    brand = data.get("brand", {}) or {}
    if brand.get("name"):
        fields["brand_name"] = str(brand["name"])
    extensions = data.get("extensions", {}) or {}
    if extensions:
        fields["extensions"] = [
            {"namespace": str(ns), "data": json.dumps(value, sort_keys=True)}
            for ns, value in extensions.items()]
    return fields


def _with_designer_settings_in_extension(data: dict) -> dict:
    """Move DESIGNER_ONLY_PATHS into extensions.designer. A value the
    document already sets in extensions.designer wins over the legacy
    location."""
    data = copy.deepcopy(data)
    moved: dict = {}
    for path in DESIGNER_ONLY_PATHS:
        parent = data
        for key in path[:-1]:
            parent = parent.get(key) if isinstance(parent, dict) else None
        if not isinstance(parent, dict) or path[-1] not in parent:
            continue
        value = parent.pop(path[-1])
        node = moved
        for key in path[:-1]:
            node = node.setdefault(key, {})
        node[path[-1]] = value
    if moved:
        extensions = data.setdefault("extensions", {}) or {}
        data["extensions"] = extensions
        extensions["designer"] = merge_patch(moved,
                                             extensions.get("designer") or {})
    return data


def _fmt_num(value) -> str:
    num = float(value)
    return str(int(num)) if num == int(num) else str(num)
