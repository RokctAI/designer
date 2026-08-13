# Copyright (c) 2026 ROKCT INTELLIGENCE (PTY) LTD
# For license information, please see license.txt
"""Design Campaign API: one brief fanned across formats (SAAS_SPEC 5)."""

from __future__ import annotations

import json

import frappe

from .. import engine_bridge, pipeline
from ._common import candidate_rows, require, resolve_design_system


@frappe.whitelist()
def create_campaign(formats, title=None, brief="", design_system=None,
                    master_request=None, customer=None):
    """``formats`` is a JSON list of engine format names. When
    ``master_request`` already has candidates the fan-out is enqueued
    immediately; otherwise the campaign stays Draft until a master is
    linked. Returns {"name"}."""
    require("Design Campaign", "create")
    if isinstance(formats, str):
        formats = json.loads(formats)
    if not formats:
        frappe.throw("At least one target format is required")
    for fmt in formats:
        engine_bridge.validate_format(fmt)

    doc = frappe.get_doc({
        "doctype": "Design Campaign",
        "title": title or (brief or "")[:60] or None,
        "brief": brief,
        "customer": customer,
        "design_system": resolve_design_system(design_system, customer),
        "master_request": master_request,
        "formats": [{"format": fmt} for fmt in formats],
        "status": "Draft",
    })
    doc.insert()

    if master_request and frappe.db.exists(
            "Design Candidate", {"request": master_request}):
        frappe.enqueue(pipeline.process_campaign, queue="long",
                       name=doc.name, job_name=f"design_campaign:{doc.name}")
    return {"name": doc.name}


@frappe.whitelist()
def start_campaign(name):
    """Enqueue the fan-out once a master request with candidates exists."""
    doc = frappe.get_doc("Design Campaign", name)
    require("Design Campaign", "write", doc=doc)
    if not doc.master_request:
        frappe.throw("Link a master_request first")
    frappe.enqueue(pipeline.process_campaign, queue="long",
                   name=doc.name, job_name=f"design_campaign:{doc.name}")
    return {"name": doc.name, "status": doc.status}


@frappe.whitelist()
def get_campaign_status(name):
    """Per-format candidates in the same shape as get_request_status."""
    doc = frappe.get_doc("Design Campaign", name)
    require("Design Campaign", "read", doc=doc)
    formats = []
    for row in doc.formats:
        entry = {"format": row.format, "action": row.action,
                 "candidate": None, "request_status": None}
        if row.candidate:
            cand = frappe.db.get_value(
                "Design Candidate", row.candidate,
                ["name", "score_before", "score_after", "passed",
                 "selected", "compliant_svg", "raw_image"], as_dict=True)
            if cand:
                entry["candidate"] = {
                    "name": cand.name,
                    "score_before": cand.score_before,
                    "score_after": cand.score_after,
                    "passed": cand.passed, "selected": cand.selected,
                    "svg_url": cand.compliant_svg, "raw_url": cand.raw_image,
                }
        if row.derived_request:
            entry["request_status"] = frappe.db.get_value(
                "Design Request", row.derived_request, "status")
            entry["candidates"] = candidate_rows(row.derived_request)
        formats.append(entry)
    return {"status": doc.status, "error_message": doc.error_message,
            "master_request": doc.master_request, "formats": formats}


@frappe.whitelist()
def list_campaigns(page=1, page_size=20):
    require("Design Campaign", "read")
    page, page_size = max(1, int(page)), min(100, max(1, int(page_size)))
    return frappe.get_list(
        "Design Campaign",
        fields=["name", "title", "status", "design_system", "customer",
                "master_request", "creation"],
        order_by="creation desc",
        limit_start=(page - 1) * page_size,
        limit_page_length=page_size,
    )
