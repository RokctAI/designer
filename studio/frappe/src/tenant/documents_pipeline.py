# Copyright (c) 2026 RokctAI
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
"""Background pipeline for Document Requests — the executive's side of
the studio, mirroring ``pipeline.py``'s conventions for Design Requests.

Runs on the ``long`` queue. Drives the StartupOS engine through
``startupos_bridge`` only: place the attached questions.md at its
canonical path, compile the document suite (or export briefs), record
the produced files and the engine's honest warnings — missing answers
included, verbatim — on the request.
"""

from __future__ import annotations

import os

import frappe

from . import startupos_bridge
from .lib import documents as documents_lib
from .lib import gating
from .lib import profile as profile_lib


def _fail(req, message: str):
    req.db_set("status", "Failed")
    req.db_set("error_message", (message or "")[:500])
    frappe.db.commit()


def _file_disk_path(file_url: str) -> str:
    fname = frappe.db.get_value("File", {"file_url": file_url}, "name")
    if not fname:
        frappe.throw(f"No File record for {file_url}")
    return frappe.get_doc("File", fname).get_full_path()


def _place_questions(req):
    """Copy the attached questions.md to the workspace's canonical
    ``instances/business/<name>/questions.md``. The request's file is
    the source of truth when both exist."""
    with open(_file_disk_path(req.questions_file), encoding="utf-8") as fh:
        content = fh.read()
    return startupos_bridge.write_questions(
        req.business_name, content,
        workspace_root=req.workspace_root or None)


def _record_outputs(req, rows: list[dict], warnings: str,
                    completeness: float | None):
    req.set("outputs", [])
    for row in rows:
        req.append("outputs", row)
    req.warnings = warnings[:2000] if warnings else ""
    if completeness is not None:
        req.completeness = float(completeness)
    req.flags.ignore_permissions = True
    req.save()


def _kind(relative_path: str) -> str:
    if relative_path.endswith(documents_lib.PITCH_DECK_SUFFIX):
        return "deck"
    if relative_path.endswith(documents_lib.FINANCIAL_MODEL_SUFFIX):
        return "model"
    return "document"


# ------------------------------------------------------ request pipeline

def process_document_request(name: str):
    req = frappe.get_doc("Document Request", name)
    if req.status not in ("Queued", "Processing"):
        return
    req.db_set("status", "Processing")
    frappe.db.commit()

    scope = req.document_scope or "Full Suite"
    try:
        if req.questions_file:
            _place_questions(req)
        if scope == "Briefs":
            produced = _process_briefs(req)
        else:
            produced = _process_compile(req, scope)
    except (startupos_bridge.StartupOSBridgeError,
            profile_lib.ProfileRenderError) as exc:
        _fail(req, str(exc))
        return
    except Exception as exc:
        frappe.log_error(frappe.get_traceback(),
                         f"studio documents pipeline failed: {name}")
        _fail(req, str(exc))
        return

    if gating.request_outcome(produced) == "Failed":
        _fail(req, req.error_message or "No documents could be produced")
    else:
        req.db_set("status", "Ready")
        req.db_set("error_message", "")
        frappe.db.commit()


def _process_compile(req, scope: str) -> int:
    """Compile and record the request's deliverables. The engine's
    warnings and unanswered questions land on the request verbatim — an
    incomplete profile still compiles (documents carry the gaps); only
    zero recorded outputs fails the request.

    Without an artifact selection the whole suite compiles and the
    scope decides the recorded slice (unchanged behaviour). With one,
    the engine compiles selectively — exactly the named artifacts plus
    the compliance log, nothing pruned — and every written file is
    recorded."""
    artifacts = documents_lib.parse_artifacts(
        getattr(req, "artifacts", None))
    result = startupos_bridge.compile_documents(
        req.business_name,
        workspace_root=req.workspace_root or None,
        compliance_root=req.compliance_root or None,
        render=documents_lib.needs_render(scope, bool(req.render_binaries)),
        only=artifacts or None,
    )
    if artifacts:
        selected = list(result["written"])
    else:
        selected = documents_lib.select_outputs(scope, result["written"])
    rows = [{"file_path": rel, "kind": _kind(rel)} for rel in selected]

    warnings = list(result["warnings"])
    if getattr(req, "render_profile", 0):
        if documents_lib.BUSINESS_PROFILE_FILENAME in selected:
            rows.extend(_render_branded_profile(req, result["output_dir"]))
        else:
            warnings.append(
                "Render A4 Profile was requested but this request does not "
                f"deliver {documents_lib.BUSINESS_PROFILE_FILENAME}; add "
                f"{documents_lib.BUSINESS_PROFILE_STEM} to the artifact "
                "selection (or use a markdown scope). Nothing was rendered.")

    _record_outputs(
        req, rows,
        documents_lib.format_warnings(warnings, result["missing_fields"]),
        result.get("completeness"),
    )
    if not rows:
        req.db_set("error_message",
                   f"The compiler wrote {len(result['written'])} files but "
                   f"none matched scope {scope!r}")
    return len(rows)


def _render_branded_profile(req, output_dir: str) -> list[dict]:
    """Render the branded A4 company profile (cover + content page)
    beside the engine's artifacts and return their output rows. The
    palette comes from the request's Design System when one is linked,
    else the engine's default system; slot text comes only from real
    compiled answers — the mapping never invents data."""
    values = startupos_bridge.instance_values(
        req.business_name,
        workspace_root=req.workspace_root or None,
        compliance_root=req.compliance_root or None,
    )
    system_dict = None
    if getattr(req, "design_system", None):
        from .lib.engine_dict import engine_dict_from_doc
        system_dict = engine_dict_from_doc(
            frappe.get_doc("Design System", req.design_system))

    pages = profile_lib.render_profile_pages(
        values["values"], system_dict=system_dict,
        pack_dir=getattr(req, "profile_pack_dir", None) or None,
        generated_on=frappe.utils.nowdate(),
    )
    rows = []
    for rel, svg_text in pages.items():
        destination = os.path.join(output_dir, *rel.split("/"))
        os.makedirs(os.path.dirname(destination), exist_ok=True)
        with open(destination, "w", encoding="utf-8") as fh:
            fh.write(svg_text)
        rows.append({"file_path": rel, "kind": "render"})
    return rows


def _process_briefs(req) -> int:
    """Export the design-brief JSONs. Coaching notes (which answers
    unlock which brief) are the warnings — a brief blocked by missing
    answers is skipped by the engine, never invented."""
    result = startupos_bridge.export_briefs(
        req.business_name,
        workspace_root=req.workspace_root or None,
        compliance_root=req.compliance_root or None,
    )
    out_dir = result["output_dir"]
    rows = [{"file_path": os.path.relpath(path, out_dir).replace(os.sep, "/"),
             "kind": "brief"}
            for path in result["briefs"]]
    _record_outputs(req, rows, "\n".join(result["coaching"]), None)
    if not rows:
        req.db_set("error_message",
                   "No brief had its required marketing answers; see "
                   "warnings for the questions that unlock each brief")
    return len(rows)
