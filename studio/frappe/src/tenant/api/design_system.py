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
    """Full JSON that drives the editor's constrained controls."""
    doc = frappe.get_doc("Design System", name)
    require("Design System", "read", doc=doc)
    return {
        "name": doc.name,
        "system_name": doc.system_name,
        "brand_name": doc.brand_name,
        "customer": doc.customer,
        "tokens": [{"name": t.token_name, "hex": t.hex, "role": t.role}
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
    }


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
