"""Test harness for the design_studio fragment.

Frappe is not installed (and cannot be) in this repo, so a minimal
``frappe`` stub is injected into sys.modules before any fragment module
is imported. The fragment's ``frappe/src`` tree is registered as the
importable package ``design_studio_src`` — the same shape it has after
the composer copies it to ``{app_name}/design_studio/``.
"""

from __future__ import annotations

import importlib.util
import sys
import types
from datetime import datetime, timedelta
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parent
FRAGMENT_DIR = TESTS_DIR.parent            # design_studio/
REPO_ROOT = FRAGMENT_DIR.parent            # repo root (has designer/)
SRC_DIR = FRAGMENT_DIR / "frappe" / "src"

# `import designer` must work no matter how pytest was invoked.
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def _install_frappe_stub():
    if getattr(sys.modules.get("frappe"), "_design_studio_stub", False):
        return sys.modules["frappe"]

    frappe = types.ModuleType("frappe")
    frappe._design_studio_stub = True

    def whitelist(allow_guest=False, **_kw):
        def deco(fn):
            fn._is_whitelisted = True
            fn._allow_guest = allow_guest
            return fn
        return deco

    class _ValidationError(Exception):
        pass

    class _PermissionError(Exception):
        pass

    def throw(msg, exc=_ValidationError):
        raise exc(msg)

    frappe.whitelist = whitelist
    frappe.ValidationError = _ValidationError
    frappe.PermissionError = _PermissionError
    frappe.throw = throw
    frappe.log_error = lambda *a, **k: None
    frappe.get_traceback = lambda: "stub traceback"
    frappe.msgprint = lambda *a, **k: None
    frappe.session = types.SimpleNamespace(user="test@example.com")
    frappe.local = types.SimpleNamespace(response={})
    frappe.db = types.SimpleNamespace()
    frappe.conf = {}

    utils = types.ModuleType("frappe.utils")
    utils.now_datetime = lambda: datetime(2026, 1, 1, 12, 0, 0)
    utils.get_datetime = lambda value: value
    utils.nowdate = lambda: "2026-01-01"
    utils.add_days = lambda d, days: d + timedelta(days=days)

    def add_to_date(d, years=0, months=0, days=0, hours=0, minutes=0, seconds=0):
        return d + timedelta(days=days + 365 * years + 30 * months,
                             hours=hours, minutes=minutes, seconds=seconds)

    utils.add_to_date = add_to_date

    model = types.ModuleType("frappe.model")
    document = types.ModuleType("frappe.model.document")

    class Document:
        def __init__(self, *args, **kwargs):
            for key, value in kwargs.items():
                setattr(self, key, value)

    document.Document = Document
    model.document = document
    frappe.utils = utils
    frappe.model = model

    sys.modules["frappe"] = frappe
    sys.modules["frappe.utils"] = utils
    sys.modules["frappe.model"] = model
    sys.modules["frappe.model.document"] = document
    return frappe


def _register_src_package():
    name = "design_studio_src"
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(
        name, SRC_DIR / "__init__.py",
        submodule_search_locations=[str(SRC_DIR)])
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


_install_frappe_stub()
_register_src_package()
