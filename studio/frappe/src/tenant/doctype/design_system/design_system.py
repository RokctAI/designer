# Copyright (c) 2026 ROKCT INTELLIGENCE (PTY) LTD
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

import re

import frappe
from frappe.model.document import Document

HEX_RE = re.compile(r"^#[0-9a-fA-F]{6}$")


def _lib_engine_dict():
    """The pure mapping lives in the fragment's tenant lib package
    ({app}.studio.tenant.lib.engine_dict after composition); the
    composer relocates doctype trees back to the module root, so this
    module sits at {app}.studio.doctype.design_system.design_system and
    the module root is everything before '.doctype.'."""
    from importlib import import_module

    base = __name__.split(".doctype.")[0]
    return import_module(base + ".tenant.lib.engine_dict")


class DesignSystem(Document):
    def validate(self):
        lib = _lib_engine_dict()
        problems = lib.validate_system_fields(self)
        if problems:
            frappe.throw("<br>".join(problems))
        self._enforce_single_default()

    def _enforce_single_default(self):
        """Only one is_default per customer (and one global default)."""
        if not self.is_default:
            return
        filters = {"is_default": 1, "name": ("!=", self.name)}
        filters["customer"] = self.customer or ("is", "not set")
        for other in frappe.get_all("Design System", filters=filters,
                                    pluck="name"):
            frappe.db.set_value("Design System", other, "is_default", 0)

    def as_engine_dict(self) -> dict:
        """Serialize to the engine schema (SAAS_SPEC section 7). Pure
        mapping, no I/O; must round-trip through
        designer.tokens.system_from_dict without error."""
        return _lib_engine_dict().engine_dict_from_doc(self)
