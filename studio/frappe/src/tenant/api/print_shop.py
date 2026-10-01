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
"""Print-shop API for the Next.js studio: construction guides, client
PDF preflight, imposition, job tickets, client proofs (with email
sign-off) and the hot folder. Every engine call goes through
engine_bridge; every output is a private File the frontend downloads.
"""

from __future__ import annotations

import json
import os
import tempfile

import frappe

from .. import engine_bridge
from ..lib import tokens as token_lib
from ._common import file_disk_path, require, system_dict_for

DEFAULT_REVIEW_PATH = "/studio/review/{token}"


def _save_file(data: bytes, file_name: str, doctype: str, name: str) -> str:
    f = frappe.get_doc({
        "doctype": "File",
        "file_name": file_name,
        "attached_to_doctype": doctype,
        "attached_to_name": name,
        "is_private": 1,
        "content": data,
    })
    f.save(ignore_permissions=True)
    return f.file_url


def _tmp(suffix: str) -> str:
    fh = tempfile.NamedTemporaryFile(suffix=suffix, delete=False)
    fh.close()
    return fh.name


def _read_and_unlink(path: str) -> bytes:
    try:
        with open(path, "rb") as fh:
            return fh.read()
    finally:
        os.unlink(path)


def _engine_call(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except engine_bridge.EngineError as exc:
        frappe.throw(str(exc))


def _candidate_svg(candidate):
    cand = frappe.get_doc("Design Candidate", candidate)
    req = frappe.get_doc("Design Request", cand.request) if cand.request else None
    if req is not None:
        require("Design Request", "read", doc=req)
    if not cand.compliant_svg:
        frappe.throw(f"Candidate {cand.name} has no compliant SVG yet")
    with open(file_disk_path(cand.compliant_svg), encoding="utf-8") as fh:
        return cand, req, fh.read()


# -- construction guides -------------------------------------------------


@frappe.whitelist()
def get_construction(candidate):
    """Construction guides for a candidate (informational, never
    scored): notes, ⚠ warnings, geometry and an overlay SVG the
    frontend can toggle on top of the preview."""
    _, _, svg = _candidate_svg(candidate)
    return _engine_call(engine_bridge.construction, svg)


# -- client PDF preflight and imposition -------------------------------

MAX_CLIENT_PDF_BYTES = 100 * 1024 * 1024


def _client_pdf(file_url=None, file_data=None, filename=None) -> tuple[str, str]:
    """(disk path, file_url) for a client PDF given either an existing
    File url or base64 ``file_data`` uploaded straight from Next.js."""
    if file_url:
        return file_disk_path(file_url), file_url
    if not file_data:
        frappe.throw("Give file_url or file_data")
    import base64

    if "," in file_data[:100]:
        file_data = file_data.split(",", 1)[1]  # data: URI prefix
    raw = base64.b64decode(file_data)
    if len(raw) > MAX_CLIENT_PDF_BYTES:
        frappe.throw("PDF is larger than 100MB")
    if not raw.startswith(b"%PDF"):
        frappe.throw("That file is not a PDF")
    f = frappe.get_doc({"doctype": "File", "file_name": filename or "client.pdf",
                        "is_private": 1, "content": raw})
    f.save()
    return f.get_full_path(), f.file_url


@frappe.whitelist()
def preflight_upload(file_url=None, min_ppi=300, max_ink=300, bleed_mm=3,
                     file_data=None, filename=None):
    """Preflight a client PDF (an existing File url, or base64
    ``file_data`` + ``filename``). Returns the report plus the stored
    ``file_url`` (``blocked`` means it must not go to plate as-is)."""
    require("File", "create" if file_data else "read")
    path, url = _client_pdf(file_url, file_data, filename)
    report = _engine_call(engine_bridge.preflight_pdf, path,
                          min_ppi=float(min_ppi), max_ink=float(max_ink),
                          min_bleed_mm=float(bleed_mm))
    report["file_url"] = url
    return report


@frappe.whitelist()
def list_sheets():
    """Press sheet sizes (mm) the imposer knows."""
    return engine_bridge.list_sheets()


def _sheet_arg(sheet):
    if isinstance(sheet, str) and sheet.startswith("["):
        sheet = json.loads(sheet)
    if isinstance(sheet, (list, tuple)):
        return (float(sheet[0]), float(sheet[1]))
    return sheet or "SRA3"


@frappe.whitelist()
def impose_upload(file_url=None, sheet="SRA3", quantity=None, gap_mm=None, margin_mm=10,
                  file_data=None, filename=None):
    """N-up a one-page client PDF onto a press sheet. Returns
    {pdf_url, layout}."""
    require("File", "create" if file_data else "read")
    path, file_url = _client_pdf(file_url, file_data, filename)
    out = _tmp(".pdf")
    layout = _engine_call(
        engine_bridge.impose, path, out, sheet=_sheet_arg(sheet),
        quantity=int(quantity) if quantity else None,
        gap_mm=float(gap_mm) if gap_mm not in (None, "") else None,
        margin_mm=float(margin_mm))
    name = frappe.db.get_value("File", {"file_url": file_url}, "name")
    url = _save_file(_read_and_unlink(out), "imposed.pdf", "File", name)
    return {"pdf_url": url, "layout": layout}


# -- print jobs: press PDF + imposition + job ticket ------------------------


def _job_dict(job_doc, extra=None) -> dict:
    data = {
        "job_no": job_doc.name,
        "client": job_doc.customer or "",
        "quantity": job_doc.get("quantity"),
        "stock": job_doc.get("stock") or "",
        "finish": job_doc.material_finish or "",
        "size": job_doc.final_size or "",
        "due": str(job_doc.get("due_date") or ""),
        "Sides": job_doc.sides or "",
        "Vendor": job_doc.vendor_name or "",
    }
    data.update(extra or {})
    return data


PRINT_JOB_FIELDS = ["name", "candidate", "request", "customer", "vendor_name", "final_size",
                    "sides", "material_finish", "status", "quantity", "stock", "due_date",
                    "sheet", "press_pdf", "imposed_pdf", "ticket_pdf", "layout_json",
                    "sales_order", "sales_invoice", "modified"]


@frappe.whitelist()
def list_print_jobs(status=None, limit=50):
    """Print jobs for the board, newest first."""
    require("Design Print Job", "read")
    filters = {"status": status} if status else {}
    return frappe.get_all("Design Print Job", filters=filters, fields=PRINT_JOB_FIELDS,
                          order_by="modified desc", limit_page_length=int(limit))


@frappe.whitelist()
def get_print_job(print_job):
    """One print job with its files and imposition layout."""
    job = frappe.get_doc("Design Print Job", print_job)
    require("Design Print Job", "read", doc=job)
    data = {f: job.get(f) for f in PRINT_JOB_FIELDS}
    data["layout"] = json.loads(job.layout_json) if job.get("layout_json") else None
    return data


@frappe.whitelist()
def update_print_job(print_job, values):
    """Set the production fields the board edits (quantity, stock, due
    date, sheet, size, sides, finish, vendor, status)."""
    job = frappe.get_doc("Design Print Job", print_job)
    require("Design Print Job", "write", doc=job)
    if isinstance(values, str):
        values = json.loads(values)
    editable = {"quantity", "stock", "due_date", "sheet", "final_size", "sides",
                "material_finish", "vendor_name", "status"}
    for key, value in (values or {}).items():
        if key in editable:
            job.set(key, value)
    job.save()
    return get_print_job(job.name)


@frappe.whitelist()
def prepare_print_job(print_job, sheet=None, quantity=None, format=None):
    """Make a Design Print Job press-ready in one call: CMYK press PDF
    (bleed, marks, colour strip, black overprint), n-up imposition on
    ``sheet``, and the A4 job ticket. Stores the files on the job and
    returns their URLs, the layout and the audit result."""
    job = frappe.get_doc("Design Print Job", print_job)
    require("Design Print Job", "write", doc=job)
    cand, req, svg = _candidate_svg(job.candidate)
    format = format or (req.format if req else None) or None
    system_dict = system_dict_for(req.design_system) if req else None
    if quantity:
        job.quantity = int(quantity)
    if sheet:
        job.sheet = sheet

    press = _tmp(".pdf")
    _engine_call(engine_bridge.render_candidate_pdf, svg, press, cmyk=True,
                 format=format, system_dict=system_dict, marks=True)
    press_bytes = _read_and_unlink(press)
    job.press_pdf = _save_file(press_bytes, f"{job.name}-press.pdf",
                               "Design Print Job", job.name)

    layout = None
    if job.get("sheet"):
        src, out = _tmp(".pdf"), _tmp(".pdf")
        with open(src, "wb") as fh:
            fh.write(press_bytes)
        try:
            layout = _engine_call(engine_bridge.impose, src, out,
                                  sheet=_sheet_arg(job.sheet),
                                  quantity=job.get("quantity"))
        finally:
            os.unlink(src)
        job.imposed_pdf = _save_file(_read_and_unlink(out), f"{job.name}-imposed.pdf",
                                     "Design Print Job", job.name)
        job.layout_json = json.dumps(layout)

    ticket = _tmp(".pdf")
    _engine_call(engine_bridge.job_ticket, svg, ticket, _job_dict(job),
                 system_dict=system_dict, format=format, layout=layout)
    job.ticket_pdf = _save_file(_read_and_unlink(ticket), f"{job.name}-ticket.pdf",
                                "Design Print Job", job.name)
    job.save()
    return {"press_pdf": job.press_pdf, "imposed_pdf": job.get("imposed_pdf"),
            "ticket_pdf": job.ticket_pdf, "layout": layout}


# -- client proofs and email sign-off ---------------------------------------


def review_url(token: str) -> str:
    """Public Next.js review page for an approval token."""
    template = frappe.db.get_single_value(
        "Design Studio Settings", "review_url_template") or DEFAULT_REVIEW_PATH
    path = template.format(token=token)
    if path.startswith("http"):
        return path
    from frappe.utils import get_url

    return get_url(path)


def _proof_for_approval(approval, job_extra=None) -> str:
    cand, req, svg = _candidate_svg(approval.candidate)
    job = {"job_no": approval.name, "title": (req.title if req else "") or "Design proof",
           "client": (req.get("customer") if req else "") or ""}
    job.update(job_extra or {})
    out = _tmp(".pdf")
    _engine_call(engine_bridge.proof, [svg], out, job, approve_url=review_url(approval.token))
    url = _save_file(_read_and_unlink(out), f"{approval.name}-proof.pdf",
                     "Design Approval", approval.name)
    approval.db_set("proof_pdf", url)
    return url


@frappe.whitelist()
def create_proof(approval, quantity=None, stock=None):
    """Watermarked low-res proof PDF for a Design Approval, carrying its
    online review link. Returns {proof_url, review_url}."""
    doc = frappe.get_doc("Design Approval", approval)
    require("Design Approval", "write", doc=doc)
    url = _proof_for_approval(doc, {"quantity": quantity, "stock": stock or ""})
    return {"proof_url": url, "review_url": review_url(doc.token)}


@frappe.whitelist()
def send_proof(approval, recipients, subject=None, message=None, quantity=None, stock=None):
    """Email the client their proof (PDF attached) with the review link
    to approve, reject or request changes online. ``recipients`` is a
    comma-separated string or list."""
    doc = frappe.get_doc("Design Approval", approval)
    require("Design Approval", "write", doc=doc)
    if doc.status != "Pending":
        frappe.throw("This review has already been answered")
    if isinstance(recipients, str):
        recipients = [r.strip() for r in recipients.split(",") if r.strip()]
    if not recipients:
        frappe.throw("Give at least one recipient email")

    url = _proof_for_approval(doc, {"quantity": quantity, "stock": stock or ""})
    link = review_url(doc.token)
    title = frappe.db.get_value("Design Request", doc.request, "title") if doc.request else ""
    file_doc = frappe.get_doc("File", {"file_url": url})
    frappe.sendmail(
        recipients=recipients,
        subject=subject or f"Proof for approval: {title or doc.name}",
        message=token_lib.proof_email_html(message, link, title),
        attachments=[{"fname": file_doc.file_name, "fcontent": file_doc.get_content()}],
        reference_doctype="Design Approval",
        reference_name=doc.name,
    )
    doc.db_set("client_email", ", ".join(recipients))
    doc.db_set("sent_on", frappe.utils.now_datetime())
    return {"proof_url": url, "review_url": link, "sent_to": recipients}


# -- hot folder ---------------------------------------------------------------


def _hot_folder_settings():
    get = lambda f: frappe.db.get_single_value("Design Studio Settings", f)  # noqa: E731
    return {
        "enabled": bool(get("hot_folder_enabled")),
        "inbox": get("hot_folder_inbox"),
        "outbox": get("hot_folder_outbox"),
        "sheet": get("hot_folder_sheet"),
        "format": get("hot_folder_format"),
        "design_system": get("hot_folder_design_system"),
    }


def run_hot_folder_pass(force=False):
    """One pass over the configured inbox. Scheduler entry point."""
    cfg = _hot_folder_settings()
    if not (cfg["enabled"] or force) or not cfg["inbox"] or not cfg["outbox"]:
        return []
    system_dict = system_dict_for(cfg["design_system"]) if cfg["design_system"] else None
    results = engine_bridge.process_hot_folder(
        cfg["inbox"], cfg["outbox"], system_dict=system_dict,
        format=cfg["format"], sheet=cfg["sheet"])
    if results:
        frappe.db.set_single_value("Design Studio Settings", "hot_folder_last_run",
                                   json.dumps(results)[:100000])
        frappe.db.commit()
    return results


@frappe.whitelist()
def save_hot_folder_settings(values):
    """Update the hot-folder settings from the Next.js settings page."""
    require("Design Studio Settings", "write")
    if isinstance(values, str):
        values = json.loads(values)
    doc = frappe.get_single("Design Studio Settings")
    mapping = {"enabled": "hot_folder_enabled", "inbox": "hot_folder_inbox",
               "outbox": "hot_folder_outbox", "sheet": "hot_folder_sheet",
               "format": "hot_folder_format", "design_system": "hot_folder_design_system"}
    for key, field in mapping.items():
        if key in (values or {}):
            doc.set(field, values[key])
    doc.save()
    return get_hot_folder_status()


@frappe.whitelist()
def run_hot_folder():
    """Run a hot-folder pass now (System Manager)."""
    require("Design Studio Settings", "write")
    return run_hot_folder_pass(force=True)


@frappe.whitelist()
def get_hot_folder_status():
    """Settings plus the last pass's per-file results."""
    require("Design Studio Settings", "read")
    cfg = _hot_folder_settings()
    last = frappe.db.get_single_value("Design Studio Settings", "hot_folder_last_run")
    cfg["last_run"] = json.loads(last) if last else []
    return cfg


# -- CLI parity: preview PNG, multi-page PDF, brand manual -------------------


@frappe.whitelist()
def render_preview(candidate, width=1024, construction=0, background="#ffffff"):
    """PNG of a candidate (download / "Download all" zip). With
    ``construction`` the guides are drawn on top. Returns {png_url}."""
    cand, _, svg = _candidate_svg(candidate)
    out = _tmp(".png")
    _engine_call(engine_bridge.render_candidate_png, svg, out, width=int(width),
                 construction=bool(int(construction)), background=background)
    suffix = "-construction" if int(construction) else ""
    return {"png_url": _save_file(_read_and_unlink(out), f"{cand.name}{suffix}.png",
                                  "Design Candidate", cand.name)}


@frappe.whitelist()
def render_pages(candidates, format=None, cmyk=1, marks=1):
    """One multi-page press PDF from several candidates in order (front
    and back of a card, panels of a fold). ``candidates`` is a list or
    JSON list of names. Returns {pdf_url}."""
    if isinstance(candidates, str):
        candidates = json.loads(candidates)
    if not candidates:
        frappe.throw("Give at least one candidate")
    svgs, first, req = [], None, None
    for name in candidates:
        cand, r, svg = _candidate_svg(name)
        first, req = first or cand, req or r
        svgs.append(svg)
    format = format or (req.format if req else None) or None
    out = _tmp(".pdf")
    _engine_call(engine_bridge.render_pages_pdf, svgs, out, cmyk=bool(int(cmyk)),
                 format=format, system_dict=system_dict_for(req.design_system) if req else None,
                 marks=bool(int(marks)))
    return {"pdf_url": _save_file(_read_and_unlink(out), f"{first.name}-pages.pdf",
                                  "Design Candidate", first.name)}


@frappe.whitelist()
def brandbook(design_system, logo_file_url=None):
    """The design system as an A4 brand manual PDF, optionally with the
    logo on its own page. Returns {pdf_url}."""
    doc = frappe.get_doc("Design System", design_system)
    require("Design System", "read", doc=doc)
    out = _tmp(".pdf")
    _engine_call(engine_bridge.brandbook_pdf, system_dict_for(design_system), out,
                 logo_path=file_disk_path(logo_file_url) if logo_file_url else None)
    return {"pdf_url": _save_file(_read_and_unlink(out), f"{doc.name}-brandbook.pdf",
                                  "Design System", doc.name)}
