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
