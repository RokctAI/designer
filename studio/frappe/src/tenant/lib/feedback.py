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

"""Turn an engine report into prompt guidance for regeneration
(SAAS_SPEC section 3, ``build_feedback``). Pure: consumes the report
JSON string and the system dict, returns text.
"""

from __future__ import annotations

import json


def build_feedback(report_json: str, system_dict: dict) -> str:
    """E.g. 'Previous attempt scored 82/100: 9 distinct colors (limit 6);
    low text contrast. Use ONLY these colors: #1a56db, #f59e0b, ...'"""
    try:
        report = json.loads(report_json or "{}")
    except (TypeError, ValueError):
        report = {}

    score = report.get("score")
    findings = report.get("findings", []) or []
    open_msgs = []
    for finding in findings:
        if finding.get("fixed"):
            continue
        msg = finding.get("message") or finding.get("rule") or ""
        if msg:
            open_msgs.append(str(msg))

    parts = []
    if score is not None:
        parts.append(f"Previous attempt scored {score}/100")
    if open_msgs:
        parts.append("; ".join(open_msgs[:5]))

    hexes = []
    tokens = ((system_dict or {}).get("color", {}) or {}).get("tokens", {}) or {}
    for value in tokens.values():
        hexval = value.get("hex") if isinstance(value, dict) else value
        if hexval:
            hexes.append(str(hexval))
    if hexes:
        parts.append("Use ONLY these colors: " + ", ".join(hexes))

    return ". ".join(p for p in parts if p)
