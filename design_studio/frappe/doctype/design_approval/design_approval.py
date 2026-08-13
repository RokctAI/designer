# Copyright (c) 2026 ROKCT INTELLIGENCE (PTY) LTD
# For license information, please see license.txt

import secrets

import frappe
from frappe.model.document import Document


class DesignApproval(Document):
    def before_insert(self):
        # Server-side, cryptographically random, URL-safe. This token is
        # the only handle guests ever see.
        if not self.token:
            self.token = secrets.token_urlsafe(32)

    def validate(self):
        if not self.request and not self.campaign:
            frappe.throw("Link the approval to a Design Request or a "
                         "Design Campaign")
