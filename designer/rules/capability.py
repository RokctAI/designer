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
