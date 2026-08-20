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

"""Document Request scope logic — pure functions, no frappe, no engine.

The StartupOS compiler always regenerates the whole suite (its output
pruning depends on that); ``document_scope`` decides which of the
written files the request records as its deliverables, and whether the
binary artifacts must be rendered at all.
"""

from __future__ import annotations

from typing import Mapping, Sequence

SCOPES = ("Full Suite", "Plan Chapters", "Pitch Deck", "Financial Model",
          "Briefs")

# Scopes that require render=True regardless of the request's checkbox.
RENDER_SCOPES = ("Pitch Deck", "Financial Model")

PITCH_DECK_SUFFIX = ".pptx"
FINANCIAL_MODEL_SUFFIX = ".xlsx"


def needs_render(scope: str, render_binaries: bool) -> bool:
    """Briefs never compile; deck/model scopes always render; Full
    Suite / Plan Chapters render only when the checkbox asks."""
    if scope == "Briefs":
        return False
    if scope in RENDER_SCOPES:
        return True
    return bool(render_binaries) and scope == "Full Suite"


def select_outputs(scope: str, written: Sequence[str]) -> list[str]:
    """Which of the compiler's written files this request delivers.

    Unknown scopes raise ValueError — the Select field and this list
    must never drift apart silently.
    """
    if scope not in SCOPES:
        raise ValueError(f"Unknown document_scope: {scope!r}")
    if scope == "Full Suite":
        return list(written)
    if scope == "Plan Chapters":
        return [w for w in written if w.endswith(".md")]
    if scope == "Pitch Deck":
        return [w for w in written if w.endswith(PITCH_DECK_SUFFIX)]
    if scope == "Financial Model":
        return [w for w in written if w.endswith(FINANCIAL_MODEL_SUFFIX)]
    return []  # Briefs: outputs come from export_briefs, not the compiler


def format_warnings(warnings: Sequence[str],
                    missing_fields: Mapping[str, str]) -> str:
    """One honest text block for the request: the engine's warnings
    verbatim, then every unanswered question by its human label."""
    lines = [str(w) for w in warnings]
    if missing_fields:
        labels = ", ".join(missing_fields[k] for k in sorted(missing_fields))
        lines.append(f"Unanswered questions ({len(missing_fields)}): {labels}")
    return "\n".join(lines)
