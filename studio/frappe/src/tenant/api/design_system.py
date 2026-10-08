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

# Copyright (c) 2026 ROKCT INTELLIGENCE (PTY) LTD
# For license information, please see license.txt
"""Design System API (SAAS_SPEC section 4 + FRONTEND_SPEC 1.2)."""

from __future__ import annotations

import frappe

from .. import engine_bridge
from ..lib import engine_dict as engine_dict_lib
from ._common import file_disk_path, require


@frappe.whitelist()
def list_design_systems():
    """Systems visible to the session user (DocType permissions apply
    via get_list)."""
    require("Design System", "read")
    return frappe.get_list(
        "Design System",
        fields=["name", "system_name", "brand_name", "customer", "is_default"],
        order_by="modified desc",
    )


@frappe.whitelist()
def get_design_system(name):
    """Full JSON that drives the editor's constrained controls.

    ``system`` is the canonical document (docs/DESIGN_SYSTEM_CONTRACT.md)
    that every product reads; ``fingerprint`` identifies this exact
    definition so a consumer can record what it used. The other keys
    are the editor's original shape, kept for existing callers."""
    doc = frappe.get_doc("Design System", name)
    require("Design System", "read", doc=doc)
    system = engine_dict_lib.engine_dict_from_doc(doc)
    return {
        "name": doc.name,
        "system_name": doc.system_name,
        "brand_name": doc.brand_name,
        "customer": doc.customer,
        "is_default": bool(doc.is_default),
        "seed_colors": [c for c in (doc.seed_color_1, doc.seed_color_2,
                                    doc.seed_color_3) if c],
        "tokens": [{"name": t.token_name, "hex": t.hex, "role": t.role,
                    "derived": bool(t.derived)}
                   for t in (doc.color_tokens or [])],
        "fonts": [{"name": f.font_name, "descriptor": f.descriptor}
                  for f in (doc.fonts or [])],
        "type_scale": doc.type_scale,
        "grid": doc.grid,
        "stroke_widths": doc.stroke_widths,
        "max_colors": doc.max_colors,
        "gradient": {"allowed": bool(doc.gradient_allowed),
                     "max_stops": doc.gradient_max_stops},
        "contrast": {"min_text": doc.min_contrast_text,
                     "min_large_text": doc.min_contrast_large_text,
                     "large_text_size": doc.large_text_size},
        "schema_version": engine_dict_lib.SCHEMA_VERSION,
        "fingerprint": engine_dict_lib.fingerprint(system),
        "modified": str(doc.modified),
        "system": system,
    }


def _parse_system_arg(system) -> dict:
    """A canonical document passed as a dict or JSON string."""
    import json

    if isinstance(system, str):
        try:
            system = json.loads(system)
        except ValueError:
            frappe.throw("system is not valid JSON")
    if not isinstance(system, dict):
        frappe.throw("system must be a design-system document (a JSON object)")
    version = system.get("schema_version", engine_dict_lib.SCHEMA_VERSION)
    if version != engine_dict_lib.SCHEMA_VERSION:
        frappe.throw(f"Unsupported design-system schema_version {version!r}; "
                     f"this site reads version {engine_dict_lib.SCHEMA_VERSION}")
    return system


@frappe.whitelist()
def create_design_system(system, name=None, customer=None):
    """Create a Design System from a canonical document — the same
    mapping a system YAML file holds (import path for YAML/CI fixtures
    and agents). Token rows are stored as hand-made, not derived."""
    require("Design System", "create")
    system = _parse_system_arg(system)
    name = name or system.get("name")
    if not name:
        frappe.throw("Give the Design System a name")
    if frappe.db.exists("Design System", name):
        frappe.throw(f"Design System {name} already exists")
    fields = engine_dict_lib.doc_fields_from_engine_dict(system, derived=False)
    fields.update({"doctype": "Design System", "system_name": name,
                   "customer": customer})
    doc = frappe.get_doc(fields)
    doc.insert()
    return get_design_system(doc.name)


@frappe.whitelist()
def update_design_system(name, patch, expected_fingerprint=None):
    """Change a Design System with a JSON merge patch (RFC 7386) over
    its canonical document: maps merge, null removes a key (a token, a
    whole extension namespace), lists and values replace. Examples:
    ``{"color": {"tokens": {"accent": {"hex": "#ff6600"}}}}``,
    ``{"color": {"tokens": {"neutral-100": null}}}``,
    ``{"typography": {"fonts": ["Outfit", "sans-serif"]}}``.

    ``expected_fingerprint`` (optional) rejects the change if someone
    else edited the system since the caller read it. A token whose hex
    is unchanged keeps its ``derived`` flag; edited tokens become
    hand-made. Returns the updated system (get_design_system shape)."""
    doc = frappe.get_doc("Design System", name)
    require("Design System", "write", doc=doc)
    patch = _parse_system_arg(patch)
    current = engine_dict_lib.engine_dict_from_doc(doc)
    if expected_fingerprint and \
            expected_fingerprint != engine_dict_lib.fingerprint(current):
        frappe.throw("This design system changed since you read it; "
                     "reload it and apply the change again")
    patch = {k: v for k, v in patch.items()
             if k not in ("name", "schema_version")}
    merged = engine_dict_lib.merge_patch(current, patch)
    fields = engine_dict_lib.doc_fields_from_engine_dict(merged, derived=False)

    was_derived = {(t.token_name, (t.hex or "").lower())
                   for t in (doc.color_tokens or []) if t.derived}
    for row in fields["color_tokens"]:
        row["derived"] = 1 if (row["token_name"], row["hex"].lower()) \
            in was_derived else 0
    descriptors = {f.font_name: f.descriptor for f in (doc.fonts or [])}
    for row in fields.get("fonts", []):
        row["descriptor"] = descriptors.get(row["font_name"])

    for table in ("color_tokens", "fonts", "extensions"):
        doc.set(table, fields.pop(table, []))
    for field in engine_dict_lib.CORE_SCALAR_FIELDS:
        doc.set(field, fields.get(field))
    doc.save()
    return get_design_system(doc.name)


@frappe.whitelist()
def derive_design_system(seed_colors, name, customer=None):
    """Create a full Design System from 2-3 seed brand colors.

    The engine derives everything else (palette roles, contrast-safe
    ink/surface, scale defaults) deterministically and WCAG-safe; every
    derived token is stored as an ordinary editable row (flagged
    ``derived`` for the UI). Returns the created system's full JSON
    (same shape as get_design_system)."""
    require("Design System", "create")
    if frappe.db.exists("Design System", name):
        frappe.throw(f"Design System {name} already exists")

    try:
        seeds = engine_dict_lib.parse_seed_colors(seed_colors)
    except ValueError as exc:
        frappe.throw(str(exc))

    try:
        from designer.palette import derive_system
    except ImportError:
        frappe.throw(
            "The installed designer-compliance engine does not support "
            "palette derivation yet (designer.palette.derive_system) — "
            "upgrade the engine, or create the Design System manually.")

    try:
        system_dict = derive_system(seeds, name=name)
    except TypeError:
        system_dict = derive_system(seeds)
    fields = engine_dict_lib.doc_fields_from_engine_dict(system_dict, derived=True)
    fields.update({
        "doctype": "Design System",
        "system_name": name,
        "customer": customer,
        "seed_color_1": seeds[0],
        "seed_color_2": seeds[1],
        "seed_color_3": seeds[2] if len(seeds) > 2 else None,
    })
    doc = frappe.get_doc(fields)
    doc.insert()
    return get_design_system(doc.name)


@frappe.whitelist()
def extract_palette(file_url, n=6):
    """Engine palette extraction from an uploaded image — powers
    'import brand colors from your existing logo'. Returns
    [{hex, coverage}]."""
    require("Design System", "create")
    return engine_bridge.extract_palette(file_disk_path(file_url), n=int(n))


@frappe.whitelist()
def list_formats():
    """The engine's deliverable-format catalog, for pickers."""
    return engine_bridge.list_formats()
