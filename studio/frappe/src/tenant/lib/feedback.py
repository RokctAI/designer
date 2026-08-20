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
