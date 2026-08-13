# Copyright (c) 2026 ROKCT INTELLIGENCE (PTY) LTD
# For license information, please see license.txt

import re

import frappe
from frappe.model.document import Document

HEX_RE = re.compile(r"^#[0-9a-fA-F]{6}$")


def _lib_engine_dict():
    """The pure mapping lives in the fragment's lib package
    ({app}.design_studio.lib.engine_dict after composition); this module
    sits at {app}.design_studio.doctype.design_system.design_system, so
    the package root is everything before '.doctype.'."""
    from importlib import import_module

    base = __name__.split(".doctype.")[0]
    return import_module(base + ".lib.engine_dict")


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
