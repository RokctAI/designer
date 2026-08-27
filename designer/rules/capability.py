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

"""Capability honesty: everything the pipeline could not see or do is
reported as a finding, never silently swallowed.

Warnings come from the parser (dropped <use>/<clipPath>/CSS/etc.,
flattened <tspan>, stripped unsafe attributes) and the vectorizer
(e.g. OCR unavailable). Render-affecting drops are WARNINGs — a passing
score with one of these attached means "compliant, as far as this audit
could see", and the report says so explicitly.
"""

from __future__ import annotations

from designer.report import Finding, Severity
from designer.rules.base import Rule
from designer.svg import Document
from designer.tokens import DesignSystem

_INFO_MARKERS = ("flattened", "OCR unavailable")


class CapabilityRule(Rule):
    id = "engine.capability"
    description = "Constructs the audit could not evaluate are reported, not hidden"

    def run(self, doc: Document, system: DesignSystem, autofix: bool) -> list[Finding]:
        findings = []
        for warning in doc.warnings:
            severity = (
                Severity.INFO
                if any(marker in warning for marker in _INFO_MARKERS)
                else Severity.WARNING
            )
            findings.append(
                Finding(rule=self.id, severity=severity, message=warning)
            )
        return findings
