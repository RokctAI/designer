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

import frappe
from frappe.model.document import Document

# Same single-direction machine as Design Request; any state -> Failed.
_ALLOWED = {
    "Draft": ("Queued", "Failed"),
    "Queued": ("Processing", "Failed"),
    "Processing": ("Ready", "Failed"),
    "Ready": ("Delivered", "Failed"),
    "Delivered": ("Failed",),
    "Failed": (),
}

_SCOPES = ("Full Suite", "Plan Chapters", "Pitch Deck", "Financial Model",
           "Briefs")


class DocumentRequest(Document):
    def before_insert(self):
        if not self.requested_by:
            self.requested_by = frappe.session.user
        if not self.title and self.business_name:
            self.title = self.business_name[:60]

    def validate(self):
        if not (self.business_name or "").strip():
            frappe.throw("A business name is required")
        if self.document_scope not in _SCOPES:
            frappe.throw(f"Unknown document scope: {self.document_scope}")
        # One selection mechanism at a time: an artifacts list replaces
        # the scope's slicing, so any other scope would be silently
        # ignored — refuse loudly instead.
        if (getattr(self, "artifacts", None) or "").strip() and \
                self.document_scope != "Full Suite":
            frappe.throw(
                "An artifact selection replaces the document scope; keep "
                "document_scope as Full Suite (the default) when naming "
                "artifacts")
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
