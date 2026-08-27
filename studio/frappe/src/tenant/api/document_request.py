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
"""Document Request API — the executive persona's entry point: turn an
answered questions.md into the StartupOS document suite."""

from __future__ import annotations

import frappe

from .. import documents_pipeline, startupos_bridge
from ..lib import documents as documents_lib
from ._common import require


@frappe.whitelist()
def create_document_request(business_name, document_scope="Full Suite",
                            questions_file=None, workspace_root=None,
                            compliance_root=None, render_binaries=0,
                            customer=None, title=None, artifacts=None,
                            render_profile=0, design_system=None,
                            profile_pack_dir=None):
    """Create a request. ``questions_file`` is an already-uploaded
    private file URL of the answered questions.md; with one attached
    the request is enqueued immediately, otherwise it stays Draft until
    ``queue_document_request`` (for workspaces that already hold the
    profile). Returns {"name"}.

    ``artifacts`` (comma/newline-separated stems, e.g.
    ``"business_profile"``) switches the engine to selective
    generation: exactly those documents plus the compliance log are
    delivered, nothing else is touched or pruned. Empty/absent keeps
    the full-suite scope behaviour unchanged. ``render_profile=1`` also
    renders the branded A4 company profile (cover + content SVG pages)
    when the request delivers ``business_profile.md``, styled by
    ``design_system`` when one is linked."""
    require("Document Request", "create")
    if document_scope not in documents_lib.SCOPES:
        frappe.throw(f"Unknown document scope: {document_scope}")

    doc = frappe.get_doc({
        "doctype": "Document Request",
        "title": title or (business_name or "")[:60] or None,
        "business_name": business_name,
        "customer": customer,
        "document_scope": document_scope,
        "questions_file": questions_file,
        "workspace_root": workspace_root,
        "compliance_root": compliance_root,
        "render_binaries": 1 if int(render_binaries or 0) else 0,
        "artifacts": artifacts,
        "render_profile": 1 if int(render_profile or 0) else 0,
        "design_system": design_system,
        "profile_pack_dir": profile_pack_dir,
        "status": "Draft",
        "requested_by": frappe.session.user,
    })
    doc.insert()

    if questions_file:
        fname = frappe.db.get_value("File", {"file_url": questions_file},
                                    "name")
        if not fname:
            frappe.throw(f"No File record for {questions_file}")
        fdoc = frappe.get_doc("File", fname)
        fdoc.attached_to_doctype = "Document Request"
        fdoc.attached_to_name = doc.name
        fdoc.is_private = 1
        fdoc.save(ignore_permissions=True)
        doc.db_set("status", "Queued")
        frappe.enqueue(documents_pipeline.process_document_request,
                       queue="long", name=doc.name,
                       job_name=f"document_request:{doc.name}")
    return {"name": doc.name}


@frappe.whitelist()
def queue_document_request(name):
    """Enqueue a Draft request whose questions.md already lives in the
    workspace (or was attached after creation)."""
    doc = frappe.get_doc("Document Request", name)
    require("Document Request", "write", doc=doc)
    if doc.status != "Draft":
        frappe.throw(f"Request is {doc.status}, not Draft")
    doc.db_set("status", "Queued")
    frappe.enqueue(documents_pipeline.process_document_request,
                   queue="long", name=doc.name,
                   job_name=f"document_request:{doc.name}")
    return {"name": doc.name, "status": "Queued"}


@frappe.whitelist()
def get_document_status(name):
    """Status + produced files + the engine's honest warnings."""
    doc = frappe.get_doc("Document Request", name)
    require("Document Request", "read", doc=doc)
    return {
        "status": doc.status,
        "error_message": doc.error_message,
        "warnings": doc.warnings,
        "completeness": doc.completeness,
        "outputs": [{"file_path": row.file_path, "kind": row.kind}
                    for row in (doc.outputs or [])],
    }


@frappe.whitelist()
def get_artifact_gaps(business_name, artifacts, workspace_root=None,
                      compliance_root=None, instance_type="business"):
    """What's missing for the named artifacts, before generating —
    the engine's ``check --for <artifact> --json`` report, verbatim:
    {"instance_type", "instance_name", "jurisdiction",
    "artifacts": {name: {"ready", "unanswered": [{"key", "label"}],
    "evidence": [{"key", "status"}]}}}. Callers prompt for the
    unanswered questions and missing evidence it names, then request
    the artifacts. Writes nothing. Unknown artifact names surface the
    engine's message listing every valid stem."""
    require("Document Request", "read")
    stems = documents_lib.parse_artifacts(artifacts)
    try:
        return startupos_bridge.artifact_gaps(
            business_name, stems,
            workspace_root=workspace_root or None,
            compliance_root=compliance_root or None,
            instance_type=instance_type or "business",
        )
    except startupos_bridge.StartupOSBridgeError as exc:
        frappe.throw(str(exc))


@frappe.whitelist()
def list_document_requests(page=1, page_size=20):
    """Session user's document-request history."""
    require("Document Request", "read")
    page, page_size = max(1, int(page)), min(100, max(1, int(page_size)))
    return frappe.get_all(
        "Document Request",
        filters={"requested_by": frappe.session.user},
        fields=["name", "title", "business_name", "document_scope",
                "status", "customer", "creation"],
        order_by="creation desc",
        limit_start=(page - 1) * page_size,
        limit_page_length=page_size,
    )
