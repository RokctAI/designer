# Copyright (c) 2026 ROKCT INTELLIGENCE (PTY) LTD
# For license information, please see license.txt
"""Shared helpers for the design_studio API modules. Not whitelisted."""

from __future__ import annotations

import frappe


def require(doctype: str, ptype: str = "read", doc=None):
    if not frappe.has_permission(doctype, ptype, doc=doc):
        frappe.throw("Not permitted", frappe.PermissionError)


def resolve_design_system(design_system: str | None,
                          customer: str | None = None) -> str:
    """Explicit choice, else the customer's default system, else the
    global default, else the only/first system."""
    if design_system:
        if not frappe.db.exists("Design System", design_system):
            frappe.throw(f"Design System {design_system} not found")
        return design_system
    if customer:
        name = frappe.db.get_value(
            "Design System", {"customer": customer, "is_default": 1}, "name")
        if name:
            return name
    name = frappe.db.get_value("Design System", {"is_default": 1}, "name")
    if not name:
        name = frappe.db.get_value("Design System", {}, "name")
    if not name:
        frappe.throw("No Design System exists yet — create one first")
    return name


def system_dict_for(design_system: str) -> dict:
    from ..lib.engine_dict import engine_dict_from_doc

    return engine_dict_from_doc(frappe.get_doc("Design System", design_system))


def file_disk_path(file_url: str) -> str:
    name = frappe.db.get_value("File", {"file_url": file_url}, "name")
    if not name:
        frappe.throw(f"No File record for {file_url}")
    return frappe.get_doc("File", name).get_full_path()


def candidate_rows(request_name: str) -> list[dict]:
    """The exact candidate shape get_request_status promises
    (SAAS_SPEC section 4)."""
    rows = frappe.get_all(
        "Design Candidate",
        filters={"request": request_name},
        fields=["name", "slot", "attempt", "score_before", "score_after",
                "passed", "selected", "compliant_svg", "raw_image"],
        order_by="slot asc, attempt asc",
    )
    return [{
        "name": r.name, "slot": r.slot, "attempt": r.attempt,
        "score_before": r.score_before, "score_after": r.score_after,
        "passed": r.passed, "selected": r.selected,
        "svg_url": r.compliant_svg, "raw_url": r.raw_image,
    } for r in rows]
