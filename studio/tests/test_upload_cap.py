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
