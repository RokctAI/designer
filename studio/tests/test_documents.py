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

"""Document Request scope logic and its status machine (shared with
Design Request via lib.gating)."""

import pytest

from studio_src.lib import documents as lib
from studio_src.lib import gating

WRITTEN = [
    "01_executive_summary.md",
    "annexures/tax_clearance.md",
    "compliance_log.md",
    "investor_pitch_deck.pptx",
    "financial_model.xlsx",
]


# ------------------------------------------------------------ scopes

def test_full_suite_records_everything():
    assert lib.select_outputs("Full Suite", WRITTEN) == WRITTEN


def test_plan_chapters_records_markdown_only():
    assert lib.select_outputs("Plan Chapters", WRITTEN) == [
        "01_executive_summary.md", "annexures/tax_clearance.md",
        "compliance_log.md"]


def test_deck_and_model_scopes_record_their_binary():
    assert lib.select_outputs("Pitch Deck", WRITTEN) == \
        ["investor_pitch_deck.pptx"]
    assert lib.select_outputs("Financial Model", WRITTEN) == \
        ["financial_model.xlsx"]


def test_briefs_scope_records_nothing_from_the_compiler():
    assert lib.select_outputs("Briefs", WRITTEN) == []


def test_unknown_scope_is_loud():
    with pytest.raises(ValueError, match="Unknown document_scope"):
        lib.select_outputs("Everything", WRITTEN)


@pytest.mark.parametrize("scope,checkbox,expected", [
    ("Full Suite", False, False),
    ("Full Suite", True, True),
    ("Plan Chapters", True, False),   # markdown-only deliverable
    ("Pitch Deck", False, True),      # the deliverable IS the binary
    ("Financial Model", False, True),
    ("Briefs", True, False),          # briefs never compile
])
def test_needs_render(scope, checkbox, expected):
    assert lib.needs_render(scope, checkbox) is expected


# ------------------------------------------------ artifact selections

def test_parse_artifacts_absent_or_empty_means_no_selection():
    assert lib.parse_artifacts(None) == []
    assert lib.parse_artifacts("") == []
    assert lib.parse_artifacts(" , \n , ") == []


def test_parse_artifacts_splits_commas_and_newlines_and_dedupes():
    assert lib.parse_artifacts(
        "business_profile, investor_pitch_deck\nbusiness_profile"
    ) == ["business_profile", "investor_pitch_deck"]


def test_parse_artifacts_keeps_stems_verbatim_for_the_engine():
    """No local validation or normalisation — unknown stems must reach
    the engine, whose UnknownArtifactError lists the valid names."""
    assert lib.parse_artifacts("business_profile.md") == \
        ["business_profile.md"]


# ---------------------------------------------------------- warnings

def test_format_warnings_keeps_engine_text_verbatim_and_names_gaps():
    text = lib.format_warnings(
        ["07_financial_model.md: unresolved placeholder"],
        {"pricing_tiers": "Pricing Tiers", "burn_rate": "Burn Rate"},
    )
    assert text.splitlines() == [
        "07_financial_model.md: unresolved placeholder",
        "Unanswered questions (2): Burn Rate, Pricing Tiers",
    ]


def test_format_warnings_empty_inputs_are_silent():
    assert lib.format_warnings([], {}) == ""


# ---------------------------------------------- shared status machine

def test_document_request_uses_the_design_request_machine():
    """The doctype declares the same options string; the transitions are
    the same single-direction machine from lib.gating."""
    assert gating.REQUEST_STATUSES == (
        "Draft", "Queued", "Processing", "Ready", "Delivered", "Failed")
    for current, target in [("Draft", "Queued"), ("Queued", "Processing"),
                            ("Processing", "Ready"), ("Ready", "Delivered")]:
        assert gating.can_transition(current, target)
    for current in gating.REQUEST_STATUSES[:-1]:
        assert gating.can_transition(current, "Failed")
    assert not gating.can_transition("Draft", "Ready")
    assert not gating.can_transition("Failed", "Queued")
    assert not gating.can_transition("Ready", "Processing")


def test_outcome_zero_outputs_fails():
    assert gating.request_outcome(0) == "Failed"
    assert gating.request_outcome(3) == "Ready"
