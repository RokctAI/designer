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

"""Upload size cap: oversized artwork is rejected with a clean message
before any engine work runs."""

from __future__ import annotations

import types

import frappe
import pytest

from studio_src.api import design_request as api


def _stub_file_size(monkeypatch, size):
    def get_value(doctype, filters, fieldname):
        assert doctype == "File"
        assert fieldname == "file_size"
        return size

    monkeypatch.setattr(frappe, "db",
                        types.SimpleNamespace(get_value=get_value),
                        raising=False)


def test_cap_is_20mb():
    assert api.MAX_UPLOAD_BYTES == 20 * 1024 * 1024


def test_oversized_upload_rejected(monkeypatch):
    _stub_file_size(monkeypatch, api.MAX_UPLOAD_BYTES + 1)
    with pytest.raises(frappe.ValidationError, match="too large"):
        api._require_upload_within_cap("/private/files/big.png")


def test_upload_at_cap_allowed(monkeypatch):
    _stub_file_size(monkeypatch, api.MAX_UPLOAD_BYTES)
    api._require_upload_within_cap("/private/files/ok.png")


def test_unknown_size_allowed(monkeypatch):
    # A File row without file_size (older uploads) must not be rejected.
    _stub_file_size(monkeypatch, None)
    api._require_upload_within_cap("/private/files/legacy.png")


def test_audit_upload_rejects_before_engine_runs(monkeypatch):
    _stub_file_size(monkeypatch, api.MAX_UPLOAD_BYTES * 2)
    monkeypatch.setattr(frappe, "has_permission",
                        lambda *a, **k: True, raising=False)
    engine_calls = []
    monkeypatch.setattr(api.engine_bridge, "audit_file",
                        lambda *a, **k: engine_calls.append(1))
    with pytest.raises(frappe.ValidationError, match="too large"):
        api.audit_upload("/private/files/big.png", design_system="Sys")
    assert not engine_calls
