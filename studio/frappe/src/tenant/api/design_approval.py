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
"""Client review links: token-gated, guest-accessible approval flow.

Guests only ever see the opaque token and preview data — never internal
doc names, users, or file paths. The SVG preview is returned inline
(the underlying files are private and not guest-servable).
"""

from __future__ import annotations

import frappe
from frappe.utils import get_datetime, now_datetime

from ..lib import tokens as token_lib
from ._common import file_disk_path, require


@frappe.whitelist()
def create_approval_link(candidate, expires_in_days=None):
    """Create a Design Approval for a candidate and return the share
    token. Authenticated; standard permissions apply."""
    cand = frappe.get_doc("Design Candidate", candidate)
    req = frappe.get_doc("Design Request", cand.request)
    require("Design Approval", "create")
    require("Design Request", "read", doc=req)
    if not cand.compliant_svg:
        frappe.throw(f"Candidate {cand.name} has no compliant SVG to review")

    days = int(expires_in_days) if expires_in_days else int(
        frappe.db.get_single_value(
            "Design Studio Settings", "approval_link_expiry_days")
        or token_lib.DEFAULT_EXPIRY_DAYS)
    doc = frappe.get_doc({
        "doctype": "Design Approval",
        "request": req.name,
        "candidate": cand.name,
        "status": "Pending",
        "expires_on": token_lib.default_expiry(now_datetime(), days),
    })
    doc.insert()  # token generated in the controller's before_insert
    return {"token": doc.token, "expires_on": doc.expires_on,
            "name": doc.name}


def _approval_for_token(token: str):
    """Token -> approval doc, or a guest-safe throw. Never leaks
    whether the token was close, expired vs unknown wording aside."""
    if not token or len(token) < 16:
        frappe.throw("Invalid review link", frappe.PermissionError)
    name = frappe.db.get_value("Design Approval", {"token": token}, "name")
    if not name:
        frappe.throw("This review link is invalid or has been withdrawn",
                     frappe.PermissionError)
    doc = frappe.get_doc("Design Approval", name)
    expires = get_datetime(doc.expires_on) if doc.expires_on else None
    if token_lib.token_expired(expires, now_datetime()):
        frappe.throw("This review link has expired", frappe.PermissionError)
    return doc


@frappe.whitelist(allow_guest=True)
def get_review(token):
    """Guest endpoint: candidate preview for a review token. Exposes no
    internal names."""
    doc = _approval_for_token(token)
    cand = frappe.get_doc("Design Candidate", doc.candidate)
    req = frappe.get_doc("Design Request", cand.request) if cand.request else None

    svg_markup = None
    if cand.compliant_svg:
        with open(file_disk_path(cand.compliant_svg), encoding="utf-8") as fh:
            svg_markup = fh.read()

    return {
        "status": doc.status,
        "client_comment": doc.client_comment,
        "expires_on": doc.expires_on,
        "title": (req.title if req else None) or "Design proposal",
        "format": req.format if req else None,
        "score": cand.score_after,
        "svg": svg_markup,
    }


@frappe.whitelist(allow_guest=True)
def submit_review(token, decision, comment=None):
    """Guest endpoint: record the client's decision. ``decision`` is one
    of Approved / Rejected / Changes Requested."""
    if not token_lib.is_valid_decision(decision):
        frappe.throw("Decision must be one of: "
                     + ", ".join(token_lib.REVIEW_DECISIONS))
    doc = _approval_for_token(token)
    if doc.status != "Pending":
        frappe.throw("This review has already been submitted")

    doc.db_set("status", decision)
    doc.db_set("client_comment", (comment or "")[:1000])
    if decision == "Approved":
        doc.db_set("approved_on", now_datetime())
        # Approval selects the candidate and delivers the request.
        cand = frappe.get_doc("Design Candidate", doc.candidate)
        if cand.request:
            for other in frappe.get_all(
                    "Design Candidate",
                    filters={"request": cand.request, "selected": 1},
                    pluck="name"):
                frappe.db.set_value("Design Candidate", other, "selected", 0)
            cand.db_set("selected", 1)
            req_status = frappe.db.get_value("Design Request", cand.request,
                                             "status")
            if req_status == "Ready":
                frappe.db.set_value("Design Request", cand.request,
                                    "status", "Delivered")
    frappe.db.commit()
    return {"status": doc.status}
