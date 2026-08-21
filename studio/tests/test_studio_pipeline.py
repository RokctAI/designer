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

"""Candidate creation atomicity: a failure between the candidate insert
and its SVG File save must never let a later commit persist a candidate
row that is missing compliant_svg."""

from __future__ import annotations

import types

import frappe
import pytest

from studio_src import pipeline

RESULT = {"score_before": 42.0, "score_after": 97.5,
          "report_json": "{}", "svg": "<svg/>", "comply_ms": 12}


class FakeDoc:
    def __init__(self, data, env):
        self.__dict__.update(data)
        self._env = env

    def insert(self, **_kw):
        self.name = "CAND-0001"
        self._env["log"].append(f"insert:{self.doctype}")

    def save(self, **_kw):
        if self._env["file_save_fails"] and self.doctype == "File":
            raise RuntimeError("disk full")
        self.file_url = f"/private/files/{self.file_name}"
        self._env["log"].append(f"save:{self.doctype}")

    def db_set(self, field, value):
        self._env["log"].append(f"db_set:{field}")
        setattr(self, field, value)


@pytest.fixture
def env(monkeypatch):
    env = {"log": [], "file_save_fails": False}
    monkeypatch.setattr(frappe, "get_doc",
                        lambda data: FakeDoc(data, env), raising=False)
    monkeypatch.setattr(
        frappe, "db",
        types.SimpleNamespace(commit=lambda: env["log"].append("commit"),
                              rollback=lambda: env["log"].append("rollback")),
        raising=False)
    return env


def _request():
    return types.SimpleNamespace(name="REQ-0001", min_score=90)


def test_candidate_committed_only_with_its_svg(env):
    cand = pipeline._create_candidate(_request(), 1, 1, RESULT)
    log = env["log"]
    assert cand.compliant_svg == "/private/files/CAND-0001.svg"
    # The SVG file exists and compliant_svg is set before anything commits.
    assert log.index("save:File") < log.index("commit")
    assert log.index("db_set:compliant_svg") < log.index("commit")
    assert "rollback" not in log


def test_failed_svg_save_rolls_back_the_candidate(env):
    env["file_save_fails"] = True
    with pytest.raises(RuntimeError, match="disk full"):
        pipeline._create_candidate(_request(), 1, 1, RESULT)
    log = env["log"]
    # The half-built candidate is rolled back, never committed — so the
    # _fail handler's later commit cannot persist it.
    assert "rollback" in log
    assert "commit" not in log
    assert log.index("insert:Design Candidate") < log.index("rollback")
