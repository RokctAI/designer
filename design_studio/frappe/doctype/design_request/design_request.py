# Copyright (c) 2026 ROKCT INTELLIGENCE (PTY) LTD
# For license information, please see license.txt

import frappe
from frappe.model.document import Document

# Single-direction status machine (SAAS_SPEC 2.2); any state -> Failed.
_ALLOWED = {
    "Draft": ("Queued", "Failed"),
    "Queued": ("Processing", "Failed"),
    "Processing": ("Ready", "Failed"),
    "Ready": ("Delivered", "Failed"),
    "Delivered": ("Failed",),
    "Failed": (),
}


class DesignRequest(Document):
    def before_insert(self):
        if not self.requested_by:
            self.requested_by = frappe.session.user
        if not self.title and self.prompt:
            self.title = self.prompt[:60]

    def validate(self):
        if self.source_mode == "Generated" and not (self.prompt or "").strip():
            frappe.throw("A prompt is required when source_mode is Generated")
        if self.n_candidates and int(self.n_candidates) > 4:
            self.n_candidates = 4
        self._check_status_transition()

    def _check_status_transition(self):
        if self.is_new():
            return
        previous = frappe.db.get_value(self.doctype, self.name, "status")
        if not previous or previous == self.status:
            return
        if self.status not in _ALLOWED.get(previous, ()):
            frappe.throw(
                f"Invalid status transition {previous} -> {self.status}")
