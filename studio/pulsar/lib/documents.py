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

"""Document Request scope logic — pure functions, no frappe, no engine.

Two selection mechanisms, one at a time. Without an ``artifacts`` list
the compiler regenerates the whole suite (its output pruning depends on
that) and ``document_scope`` decides which of the written files the
request records as its deliverables. With an ``artifacts`` list the
engine compiles selectively — exactly the named artifacts plus the
compliance log, nothing pruned — and the request records everything the
engine wrote.
"""

from __future__ import annotations

from typing import Mapping, Sequence

SCOPES = ("Full Suite", "Plan Chapters", "Pitch Deck", "Financial Model",
          "Briefs")

# The tender-returnable company profile: the artifact stem callers name
# in a selection, and the compiled file whose presence in a request's
# deliverables unlocks the branded A4 render.
BUSINESS_PROFILE_STEM = "business_profile"
BUSINESS_PROFILE_FILENAME = "business_profile.md"

# Scopes that require render=True regardless of the request's checkbox.
RENDER_SCOPES = ("Pitch Deck", "Financial Model")

PITCH_DECK_SUFFIX = ".pptx"
FINANCIAL_MODEL_SUFFIX = ".xlsx"


def parse_artifacts(text: str | None) -> list[str]:
    """A request's artifact selection field -> ordered unique stems.

    Accepts commas and/or newlines (the shapes ``check --for`` accepts);
    empty or absent means no selection — the full-suite default. Name
    validation is the engine's: unknown stems raise its
    UnknownArtifactError, which lists every valid artifact.
    """
    if not text:
        return []
    stems: list[str] = []
    for chunk in str(text).replace("\n", ",").split(","):
        stem = chunk.strip()
        if stem and stem not in stems:
            stems.append(stem)
    return stems


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
