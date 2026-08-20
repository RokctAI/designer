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
