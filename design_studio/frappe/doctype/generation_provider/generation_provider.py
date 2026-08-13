# Copyright (c) 2026 ROKCT INTELLIGENCE (PTY) LTD
# For license information, please see license.txt

import frappe
from frappe.model.document import Document

# Only these types generate today; the rest are defined for later
# (SAAS_SPEC M3) and raise NotImplementedError from their stubs.
IMPLEMENTED_TYPES = ("upload", "mock")


class GenerationProvider(Document):
    def validate(self):
        if self.provider_type == "custom_http" and not self.endpoint:
            frappe.throw("custom_http providers need an endpoint")
        if self.enabled and self.provider_type not in IMPLEMENTED_TYPES:
            frappe.msgprint(
                f"Provider type '{self.provider_type}' is defined but not "
                "implemented yet — requests routed to it will fail until "
                "the AI generation milestone lands.",
                indicator="orange",
            )
