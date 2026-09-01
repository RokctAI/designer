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

"""build_feedback: engine report -> regeneration prompt guidance."""

import json

from studio_src.lib.feedback import build_feedback

SYSTEM = {
    "color": {"tokens": {
        "primary": {"hex": "#1a56db", "role": "primary"},
        "accent": {"hex": "#f59e0b", "role": "accent"},
    }},
}

REPORT = json.dumps({
    "system": "Acme", "target": "x.png", "score": 82.0,
    "fixed": 3, "open": 2,
    "findings": [
        {"rule": "color.palette", "severity": "error",
         "message": "9 distinct colors (limit 6)", "fixed": False, "fix": None},
        {"rule": "a11y.contrast", "severity": "warning",
         "message": "low text contrast", "fixed": False, "fix": None},
        {"rule": "layout.grid", "severity": "info",
         "message": "already resolved", "fixed": True, "fix": "snapped"},
    ],
})


def test_feedback_mentions_score_open_findings_and_palette():
    text = build_feedback(REPORT, SYSTEM)
    assert "82.0/100" in text
    assert "9 distinct colors" in text
    assert "low text contrast" in text
    assert "already resolved" not in text  # fixed findings are excluded
    assert "#1a56db" in text and "#f59e0b" in text
    assert "Use ONLY these colors" in text


def test_feedback_survives_garbage_report():
    assert "#1a56db" in build_feedback("not json", SYSTEM)
    assert build_feedback(None, {}) == ""


def test_feedback_with_real_engine_report_shape():
    import pytest
    designer = pytest.importorskip("designer")
    from designer.report import Finding, Report, Severity

    report = Report(system_name="Acme", target="t.png", findings=[
        Finding(rule="color.palette", severity=Severity.ERROR,
                message="too many colors"),
    ])
    text = build_feedback(report.to_json(), SYSTEM)
    assert "too many colors" in text
