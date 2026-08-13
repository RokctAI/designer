# Copyright (c) 2026 ROKCT INTELLIGENCE (PTY) LTD
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class DesignCampaign(Document):
    def validate(self):
        if not self.formats:
            frappe.throw("Add at least one target format")
        seen = set()
        for row in self.formats:
            if row.format in seen:
                frappe.throw(f"Duplicate format {row.format}")
            seen.add(row.format)
