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

"""The documents pipeline end to end against the faithful engine fake:
an artifact selection delivers exactly the requested documents plus the
compliance log, the optional branded A4 render adds its two SVG pages,
the full-suite default is unchanged, and unknown artifact names fail
the request with the engine's own message."""

from __future__ import annotations

import os
import types

import frappe

from _fake_startupos import install_fake_startupos
from studio_src import documents_pipeline


class FakeRequest:
    def __init__(self, **kw):
        self.name = "DOC-00001"
        self.status = "Queued"
        self.document_scope = "Full Suite"
        self.questions_file = None
        self.workspace_root = None
        self.compliance_root = None
        self.render_binaries = 0
        self.artifacts = None
        self.render_profile = 0
        self.design_system = None
        self.profile_pack_dir = None
        self.business_name = "Acme"
        self.error_message = ""
        self.warnings = ""
        self.completeness = None
        self.outputs = []
        self.flags = types.SimpleNamespace(ignore_permissions=False)
        self.__dict__.update(kw)

    def db_set(self, field, value):
        setattr(self, field, value)

    def set(self, field, value):
        setattr(self, field, list(value))

    def append(self, field, row):
        getattr(self, field).append(dict(row))

    def save(self, **_kw):
        pass


def _run(monkeypatch, tmp_path, **request_fields):
    ws, calls = install_fake_startupos(monkeypatch, tmp_path)
    req = FakeRequest(workspace_root=str(ws), **request_fields)
    monkeypatch.setattr(frappe, "get_doc",
                        lambda doctype, name=None: req, raising=False)
    monkeypatch.setattr(frappe, "db",
                        types.SimpleNamespace(commit=lambda: None),
                        raising=False)
    documents_pipeline.process_document_request(req.name)
    return req, calls


def _paths(req):
    return [row["file_path"] for row in req.outputs]


def test_selection_delivers_exactly_requested_plus_compliance_log(
        monkeypatch, tmp_path):
    req, calls = _run(monkeypatch, tmp_path, artifacts="business_profile")
    assert calls["compile"]["only"] == ["business_profile"]
    assert req.status == "Ready"
    assert _paths(req) == ["business_profile.md", "compliance_log.md"]
    assert all(row["kind"] == "document" for row in req.outputs)


def test_selection_with_profile_render_adds_the_branded_pages(
        monkeypatch, tmp_path):
    req, _ = _run(monkeypatch, tmp_path, artifacts="business_profile",
                  render_profile=1)
    assert req.status == "Ready"
    assert _paths(req) == [
        "business_profile.md", "compliance_log.md",
        "branded/profile-cover.svg", "branded/profile-content.svg"]
    assert [r["kind"] for r in req.outputs[-2:]] == ["render", "render"]
    # The pages exist on disk beside the engine's artifacts, populated
    # from the compiled answers.
    cover = os.path.join(tmp_path, "StartupOS", "out",
                         "branded", "profile-cover.svg")
    with open(cover, encoding="utf-8") as fh:
        text = fh.read()
    assert "Acme" in text and "Pending" not in text


def test_profile_render_without_business_profile_warns_and_skips(
        monkeypatch, tmp_path):
    req, _ = _run(monkeypatch, tmp_path, artifacts="01_executive_summary",
                  render_profile=1)
    assert req.status == "Ready"
    assert _paths(req) == ["01_executive_summary.md", "compliance_log.md"]
    assert "Render A4 Profile was requested" in req.warnings


def test_full_suite_default_is_unchanged(monkeypatch, tmp_path):
    req, calls = _run(monkeypatch, tmp_path, document_scope="Plan Chapters")
    assert calls["compile"]["only"] is None
    assert req.status == "Ready"
    # The scope still slices the full compile: markdown only.
    assert _paths(req) == [
        "01_executive_summary.md", "business_profile.md",
        "investor_pitch_deck.md", "07_financial_model.md",
        "compliance_log.md"]


def test_unknown_artifact_fails_with_the_engine_message(monkeypatch,
                                                        tmp_path):
    req, _ = _run(monkeypatch, tmp_path, artifacts="tender_pack")
    assert req.status == "Failed"
    assert "Unknown business artifact 'tender_pack'" in req.error_message
    assert "Valid artifacts:" in req.error_message


def test_api_gap_report_is_the_bridge_report_verbatim(monkeypatch,
                                                      tmp_path):
    from studio_src import startupos_bridge
    from studio_src.api import document_request as api

    install_fake_startupos(monkeypatch, tmp_path)
    monkeypatch.setattr(frappe, "has_permission",
                        lambda *a, **kw: True, raising=False)
    via_api = api.get_artifact_gaps("Acme", "business_profile")
    direct = startupos_bridge.artifact_gaps("Acme", ["business_profile"])
    assert via_api == direct
    assert via_api["artifacts"]["business_profile"]["ready"] is False
