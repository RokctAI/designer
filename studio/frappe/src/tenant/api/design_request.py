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
"""Design Request API (SAAS_SPEC section 4 + FRONTEND_SPEC 1.2)."""

from __future__ import annotations

import json

import frappe

from .. import engine_bridge, pipeline
from ..lib import gating
from ._common import (candidate_rows, file_disk_path, require,
                      resolve_design_system, system_dict_for)

# Per-file cap for uploaded artwork; rejected before any engine work.
MAX_UPLOAD_BYTES = 20 * 1024 * 1024


def _require_upload_within_cap(file_url):
    """Reject an oversized uploaded File with a clean user message."""
    size = frappe.db.get_value("File", {"file_url": file_url}, "file_size")
    if size and int(size) > MAX_UPLOAD_BYTES:
        frappe.throw(
            f"File {file_url} is too large ({int(size) // (1024 * 1024)}MB); "
            f"the limit is {MAX_UPLOAD_BYTES // (1024 * 1024)}MB per file")


def _parse_list(value):
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError:
            value = [value]
    return value or []


@frappe.whitelist()
def create_design_request(prompt=None, design_system=None, format="logo",
                          n_candidates=None, min_score=None, provider=None,
                          source_mode="Uploaded Artwork", customer=None,
                          title=None, file_urls=None):
    """Create a request. Generated mode needs a prompt; Uploaded Artwork
    mode takes ``file_urls`` (JSON list of already-uploaded private
    files) — the request is enqueued as soon as it has a source.
    Returns {"name"}.
    """
    require("Design Request", "create")
    engine_bridge.validate_format(format)
    settings = frappe.get_cached_doc("Design Studio Settings")

    if source_mode == "Generated" and not (prompt or "").strip():
        frappe.throw("A prompt is required when source_mode is Generated")

    urls = _parse_list(file_urls)
    for url in urls:
        _require_upload_within_cap(url)

    doc = frappe.get_doc({
        "doctype": "Design Request",
        "title": (title or (prompt or "")[:60] or None),
        "prompt": prompt,
        "customer": customer,
        "source_mode": source_mode,
        "design_system": resolve_design_system(design_system, customer),
        "format": format,
        "n_candidates": gating.clamp_n_candidates(
            n_candidates or settings.default_n_candidates or 3),
        "min_score": float(min_score) if min_score is not None
        else float(settings.default_min_score or 95),
        "max_attempts": int(settings.default_max_attempts or 3),
        "provider": provider or settings.default_provider,
        "n_colors": int(settings.default_n_colors or 6),
        "status": "Draft",
        "requested_by": frappe.session.user,
    })
    doc.insert()

    for url in urls:
        fname = frappe.db.get_value("File", {"file_url": url}, "name")
        if not fname:
            frappe.throw(f"No File record for {url}")
        fdoc = frappe.get_doc("File", fname)
        fdoc.attached_to_doctype = "Design Request"
        fdoc.attached_to_name = doc.name
        fdoc.is_private = 1
        fdoc.save(ignore_permissions=True)

    has_source = (source_mode == "Generated") or bool(urls)
    if has_source:
        doc.db_set("status", "Queued")
        frappe.enqueue(pipeline.process_design_request, queue="long",
                       name=doc.name, job_name=f"design_request:{doc.name}")
    return {"name": doc.name}


@frappe.whitelist()
def queue_design_request(name):
    """Enqueue a Draft request once its artwork has been attached."""
    doc = frappe.get_doc("Design Request", name)
    require("Design Request", "write", doc=doc)
    if doc.status != "Draft":
        frappe.throw(f"Request is {doc.status}, not Draft")
    doc.db_set("status", "Queued")
    frappe.enqueue(pipeline.process_design_request, queue="long",
                   name=doc.name, job_name=f"design_request:{doc.name}")
    return {"name": doc.name, "status": "Queued"}


@frappe.whitelist()
def get_request_status(name):
    doc = frappe.get_doc("Design Request", name)
    require("Design Request", "read", doc=doc)
    return {
        "status": doc.status,
        "error_message": doc.error_message,
        "candidates": candidate_rows(doc.name),
    }


@frappe.whitelist()
def list_requests(page=1, page_size=20):
    """Session user's request history for the studio home."""
    require("Design Request", "read")
    page, page_size = max(1, int(page)), min(100, max(1, int(page_size)))
    return frappe.get_all(
        "Design Request",
        filters={"requested_by": frappe.session.user},
        fields=["name", "title", "status", "format", "source_mode",
                "design_system", "customer", "creation"],
        order_by="creation desc",
        limit_start=(page - 1) * page_size,
        limit_page_length=page_size,
    )


@frappe.whitelist()
def select_candidate(candidate):
    """Mark selected (max one per request); request goes Delivered."""
    cand = frappe.get_doc("Design Candidate", candidate)
    req = frappe.get_doc("Design Request", cand.request)
    require("Design Request", "write", doc=req)
    if not gating.can_transition(req.status, "Delivered"):
        frappe.throw(f"Request {req.name} is {req.status}; only a Ready "
                     "request can be delivered")
    for other in frappe.get_all("Design Candidate",
                                filters={"request": req.name, "selected": 1},
                                pluck="name"):
        frappe.db.set_value("Design Candidate", other, "selected", 0)
    cand.db_set("selected", 1)
    req.db_set("status", "Delivered")
    return {"svg_url": cand.compliant_svg}


@frappe.whitelist()
def comply_upload(file_url, design_system=None, n_colors=6, format=None):
    """Free-tier hook: run the engine on an uploaded PNG/SVG — no
    generation, no provider spend. Creates a Ready request with one
    candidate; returns the get_request_status shape."""
    require("Design Request", "create")
    _require_upload_within_cap(file_url)
    system_name = resolve_design_system(design_system)
    if format:
        engine_bridge.validate_format(format)
    settings = frappe.get_cached_doc("Design Studio Settings")

    result = engine_bridge.comply_file(
        file_disk_path(file_url), system_dict_for(system_name),
        n_colors=int(n_colors), max_dim=int(settings.max_dim or 1024),
        format=format)

    req = frappe.get_doc({
        "doctype": "Design Request",
        "title": "Comply upload",
        "source_mode": "Uploaded Artwork",
        "design_system": system_name,
        "format": format or "logo",
        "n_candidates": 1,
        "min_score": float(settings.default_min_score or 95),
        "status": "Draft",
        "requested_by": frappe.session.user,
    })
    req.insert()
    req.db_set("status", "Queued")
    req.db_set("status", "Processing")

    cand = frappe.get_doc({
        "doctype": "Design Candidate",
        "request": req.name,
        "slot": 1,
        "attempt": 1,
        "raw_image": file_url,
        "score_before": result["score_before"],
        "score_after": result["score_after"],
        "report_json": result["report_json"],
        "passed": 1 if gating.candidate_passed(
            result["score_after"], req.min_score) else 0,
        "comply_ms": result.get("comply_ms"),
    })
    cand.insert(ignore_permissions=True)
    svg_file = frappe.get_doc({
        "doctype": "File",
        "file_name": f"{cand.name}.svg",
        "attached_to_doctype": "Design Candidate",
        "attached_to_name": cand.name,
        "is_private": 1,
        "content": result["svg"],
    })
    svg_file.save(ignore_permissions=True)
    cand.db_set("compliant_svg", svg_file.file_url)
    req.db_set("status", "Ready")
    return {
        "name": req.name,
        "status": "Ready",
        "error_message": None,
        "candidates": candidate_rows(req.name),
    }


@frappe.whitelist()
def audit_upload(file_url, design_system=None, n_colors=6):
    """Read-only check of any uploaded asset (SVG or raster)."""
    require("Design Request", "create")
    _require_upload_within_cap(file_url)
    system_name = resolve_design_system(design_system)
    settings = frappe.get_cached_doc("Design Studio Settings")
    return engine_bridge.audit_file(
        file_disk_path(file_url), system_dict_for(system_name),
        n_colors=int(n_colors), max_dim=int(settings.max_dim or 1024))


@frappe.whitelist()
def save_candidate_edit(candidate, svg):
    """Guardrailed editor save (FRONTEND_SPEC 1.2): audit + comply the
    edited SVG, store a Design Candidate Revision, point the candidate's
    compliant_svg at it. Rejects only unparseable SVG."""
    cand = frappe.get_doc("Design Candidate", candidate)
    req = frappe.get_doc("Design Request", cand.request)
    require("Design Request", "write", doc=req)

    try:
        result = engine_bridge.comply_svg_text(
            svg, system_dict_for(req.design_system), format=req.format or None)
    except engine_bridge.EngineError as exc:
        frappe.local.response["http_status_code"] = 417
        frappe.throw(f"SVG could not be parsed: {exc}")

    revision = frappe.get_doc({
        "doctype": "Design Candidate Revision",
        "candidate": cand.name,
        "score": result["score_after"],
        "report_json": result["report_json"],
        "edited_by": frappe.session.user,
    })
    revision.insert(ignore_permissions=True)
    svg_file = frappe.get_doc({
        "doctype": "File",
        "file_name": f"{revision.name}.svg",
        "attached_to_doctype": "Design Candidate Revision",
        "attached_to_name": revision.name,
        "is_private": 1,
        "content": result["svg"],
    })
    svg_file.save(ignore_permissions=True)
    revision.db_set("svg", svg_file.file_url)
    cand.db_set("compliant_svg", svg_file.file_url)
    cand.db_set("score_after", result["score_after"])
    cand.db_set("report_json", result["report_json"])
    cand.db_set("passed", 1 if gating.candidate_passed(
        result["score_after"], req.min_score or 0) else 0)
    return {
        "svg": result["svg"],
        "score": result["score_after"],
        "report_json": result["report_json"],
        "revision": revision.name,
    }


@frappe.whitelist()
def render_deliverable(candidate, format=None, cmyk=1, marks=1):
    """Press-ready vector PDF of a candidate via the engine
    (render_pdf, CMYK). ``marks`` is recorded but printer's marks are
    not drawn yet (engine limitation — see README). Returns
    {"pdf_url"}."""
    cand = frappe.get_doc("Design Candidate", candidate)
    req = frappe.get_doc("Design Request", cand.request)
    require("Design Request", "read", doc=req)
    if not cand.compliant_svg:
        frappe.throw(f"Candidate {cand.name} has no compliant SVG yet")
    if format:
        engine_bridge.validate_format(format)

    with open(file_disk_path(cand.compliant_svg), encoding="utf-8") as fh:
        svg_text = fh.read()

    import os
    import tempfile
    out = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False)
    out.close()
    try:
        engine_bridge.render_candidate_pdf(
            svg_text, out.name, cmyk=bool(int(cmyk)),
            format=format or None,
            system_dict=system_dict_for(req.design_system) if format else None)
        with open(out.name, "rb") as fh:
            pdf_bytes = fh.read()
    finally:
        os.unlink(out.name)

    pdf_file = frappe.get_doc({
        "doctype": "File",
        "file_name": f"{cand.name}-{format or req.format or 'press'}.pdf",
        "attached_to_doctype": "Design Candidate",
        "attached_to_name": cand.name,
        "is_private": 1,
        "content": pdf_bytes,
    })
    pdf_file.save(ignore_permissions=True)
    return {"pdf_url": pdf_file.file_url}
