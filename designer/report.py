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

"""Findings, scoring and report output for compliance runs."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import Enum


class Severity(str, Enum):
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


_WEIGHTS = {Severity.ERROR: 5.0, Severity.WARNING: 2.0, Severity.INFO: 0.5}


@dataclass
class Finding:
    rule: str
    severity: Severity
    message: str
    shape_index: int | None = None  # index into Document.shapes, if applicable
    fixed: bool = False
    fix_description: str | None = None

    def to_dict(self) -> dict:
        return {
            "rule": self.rule,
            "severity": self.severity.value,
            "message": self.message,
            "shape_index": self.shape_index,
            "fixed": self.fixed,
            "fix": self.fix_description,
        }


@dataclass
class Report:
    system_name: str
    target: str
    findings: list[Finding] = field(default_factory=list)

    @property
    def score(self) -> float:
        """Compliance score out of 100. Fixed findings don't count
        against the score — they've been resolved."""
        penalty = sum(
            _WEIGHTS[f.severity] for f in self.findings if not f.fixed
        )
        return max(0.0, round(100.0 - penalty, 1))

    @property
    def fixed_count(self) -> int:
        return sum(1 for f in self.findings if f.fixed)

    @property
    def open_count(self) -> int:
        return sum(1 for f in self.findings if not f.fixed)

    def to_json(self) -> str:
        return json.dumps(
            {
                "system": self.system_name,
                "target": self.target,
                "score": self.score,
                "fixed": self.fixed_count,
                "open": self.open_count,
                "findings": [f.to_dict() for f in self.findings],
            },
            indent=2,
        )

    def to_text(self) -> str:
        lines = [
            f"Design system : {self.system_name}",
            f"Target        : {self.target}",
            f"Compliance    : {self.score}/100"
            + (f"  ({self.fixed_count} auto-fixed, {self.open_count} open)" if self.findings else "  (clean)"),
        ]
        if self.findings:
            lines.append("")
        for f in self.findings:
            mark = "FIXED" if f.fixed else f.severity.value.upper()
            loc = f" [shape {f.shape_index}]" if f.shape_index is not None else ""
            lines.append(f"  {mark:7s} {f.rule}{loc}: {f.message}")
            if f.fixed and f.fix_description:
                lines.append(f"          -> {f.fix_description}")
        return "\n".join(lines)
