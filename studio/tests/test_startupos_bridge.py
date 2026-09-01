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

"""startupos_bridge against a stubbed ``startupos`` package (the fake
in ``_fake_startupos``, faithful to the real API surface): the bridge
must call the engine's documented API, surface its honest outputs
(warnings, missing answers, coaching, gap reports) untouched, and wrap
every engine failure in StartupOSBridgeError."""

from __future__ import annotations

import os
import sys

import pytest

from _fake_startupos import install_fake_startupos
from studio_src import startupos_bridge


def test_missing_engine_raises_bridge_error(monkeypatch):
    """Without the pip package every entry point fails with the
    install hint, not an ImportError."""
    monkeypatch.setitem(sys.modules, "startupos", None)
    with pytest.raises(startupos_bridge.StartupOSBridgeError,
                       match="not installed"):
        startupos_bridge.compile_documents("Acme")


def test_provision_profile_passes_seed_answers(monkeypatch, tmp_path):
    ws, calls = install_fake_startupos(monkeypatch, tmp_path)
    path = startupos_bridge.provision_profile(
        "Acme", answers={"trading_name": "Acme (Pty) Ltd"},
        jurisdiction="ZA")
    assert path.endswith(os.path.join("Acme", "questions.md"))
    assert calls["provision"]["seed"] == {"trading_name": "Acme (Pty) Ltd"}
    assert calls["provision"]["jurisdiction"] == "ZA"
    assert calls["provision"]["type"] == "business"


def test_compile_documents_surfaces_honest_gaps(monkeypatch, tmp_path):
    ws, calls = install_fake_startupos(monkeypatch, tmp_path)
    result = startupos_bridge.compile_documents(
        "Acme", workspace_root=str(ws), render=True)
    assert calls["compile"]["render"] is True
    assert "investor_pitch_deck.pptx" in result["written"]
    assert result["missing_fields"] == {"pricing_tiers": "Pricing Tiers"}
    assert result["warnings"] == \
        ["07_financial_model.md: unresolved placeholder"]
    assert result["completeness"] == 62.5


def test_compile_documents_wraps_engine_errors(monkeypatch, tmp_path):
    install_fake_startupos(monkeypatch, tmp_path, fail=True)
    with pytest.raises(startupos_bridge.StartupOSBridgeError,
                       match="Missing template folder"):
        startupos_bridge.compile_documents("Acme")


# ------------------------------------------------- selective generation

def test_compile_default_passes_no_selection(monkeypatch, tmp_path):
    """No ``only`` -> the engine sees only=None: the full-suite
    behaviour (pruning included) is entirely the engine's."""
    ws, calls = install_fake_startupos(monkeypatch, tmp_path)
    result = startupos_bridge.compile_documents("Acme")
    assert calls["compile"]["only"] is None
    assert "01_executive_summary.md" in result["written"]
    assert "business_profile.md" in result["written"]
    assert "compliance_log.md" in result["written"]


def test_compile_selection_passes_through_verbatim(monkeypatch, tmp_path):
    """only=[...] reaches compile_instance and the engine's written
    list — exactly the requested artifacts plus the compliance log,
    nothing pruned — comes back untouched."""
    ws, calls = install_fake_startupos(monkeypatch, tmp_path)
    result = startupos_bridge.compile_documents(
        "Acme", only=["business_profile"])
    assert calls["compile"]["only"] == ["business_profile"]
    assert result["written"] == ["business_profile.md", "compliance_log.md"]


def test_compile_selection_renders_only_selected_binaries(monkeypatch,
                                                          tmp_path):
    ws, _ = install_fake_startupos(monkeypatch, tmp_path)
    result = startupos_bridge.compile_documents(
        "Acme", only=["business_profile", "investor_pitch_deck"],
        render=True)
    assert result["written"] == [
        "business_profile.md", "investor_pitch_deck.md",
        "compliance_log.md", "investor_pitch_deck.pptx"]


def test_compile_unknown_artifact_surfaces_engine_message(monkeypatch,
                                                          tmp_path):
    install_fake_startupos(monkeypatch, tmp_path)
    with pytest.raises(startupos_bridge.StartupOSBridgeError,
                       match=r"Unknown business artifact 'tender_pack'"
                             r".*Valid artifacts:"):
        startupos_bridge.compile_documents("Acme", only=["tender_pack"])


def test_compile_empty_selection_is_loud(monkeypatch, tmp_path):
    install_fake_startupos(monkeypatch, tmp_path)
    with pytest.raises(startupos_bridge.StartupOSBridgeError,
                       match="Empty artifact selection"):
        startupos_bridge.compile_documents("Acme", only=[])


# --------------------------------------------------------- gap reports

def test_artifact_gaps_matches_the_cli_json_shape(monkeypatch, tmp_path):
    """The bridge's report is byte-for-byte the payload the engine CLI
    prints for ``check --for business_profile --json``."""
    install_fake_startupos(monkeypatch, tmp_path)
    report = startupos_bridge.artifact_gaps("Acme", ["business_profile"])
    assert report == {
        "instance_type": "business",
        "instance_name": "Acme",
        "jurisdiction": "ZA",
        "artifacts": {
            "business_profile": {
                "ready": False,
                "unanswered": [
                    {"key": "pricing_tiers", "label": "Pricing Tiers"}],
                "evidence": [
                    {"key": "tax_number",
                     "status": "tax reference not verified — "
                               "add Tax_Pin.pdf"}],
            },
        },
    }


def test_artifact_gaps_ready_artifact(monkeypatch, tmp_path):
    install_fake_startupos(monkeypatch, tmp_path)
    report = startupos_bridge.artifact_gaps("Acme", ["01_executive_summary"])
    entry = report["artifacts"]["01_executive_summary"]
    assert entry == {"ready": True, "unanswered": [], "evidence": []}


def test_artifact_gaps_unknown_artifact_surfaces_engine_message(
        monkeypatch, tmp_path):
    install_fake_startupos(monkeypatch, tmp_path)
    with pytest.raises(startupos_bridge.StartupOSBridgeError,
                       match="Unknown business artifact"):
        startupos_bridge.artifact_gaps("Acme", ["nope"])


# ------------------------------------------------------ instance values

def test_instance_values_returns_string_namespace(monkeypatch, tmp_path):
    ws, calls = install_fake_startupos(monkeypatch, tmp_path)
    result = startupos_bridge.instance_values("Acme")
    assert calls["load"] == {"type": "business", "name": "Acme"}
    assert result["values"]["trading_name"] == "Acme"
    # The engine's honest markers come through verbatim.
    assert result["values"]["tax_number"].startswith("Pending")
    assert result["output_dir"] == str(ws / "out")


# ------------------------------------------------------- existing seams

def test_parse_questions_returns_pending_map(monkeypatch, tmp_path):
    install_fake_startupos(monkeypatch, tmp_path)
    parsed = startupos_bridge.parse_questions("questions.md")
    assert parsed["answers"] == {"trading_name": "Acme"}
    assert parsed["pending"] == {"pricing_tiers": "[TODO]"}
    assert parsed["labels"]["pricing_tiers"] == "Pricing Tiers"
    assert (parsed["answered_count"], parsed["total_count"]) == (1, 2)


def test_export_briefs_returns_absolute_paths_and_coaching(monkeypatch,
                                                           tmp_path):
    ws, _ = install_fake_startupos(monkeypatch, tmp_path)
    result = startupos_bridge.export_briefs("Acme")
    assert result["briefs"] == [
        os.path.join(str(ws / "out"), "briefs", "poster.json"),
        os.path.join(str(ws / "out"), "briefs", "flyer.json"),
    ]
    assert result["coaching"][0].startswith("poster brief skipped")


def test_write_questions_places_file_at_canonical_path(monkeypatch,
                                                       tmp_path):
    ws, _ = install_fake_startupos(monkeypatch, tmp_path)
    path = startupos_bridge.write_questions("Acme", "# Questions\n")
    assert path == os.path.join(
        str(ws), "instances", "business", "Acme", "questions.md")
    with open(path, encoding="utf-8") as fh:
        assert fh.read() == "# Questions\n"


def test_bootstrap_workspace_syncs_local_templates(monkeypatch, tmp_path):
    ws, _ = install_fake_startupos(monkeypatch, tmp_path)
    templates = tmp_path / "checkout"
    (templates / "business").mkdir(parents=True)
    (templates / "business" / "01_plan.md").write_text("x")
    (templates / "life").mkdir()
    result = startupos_bridge.bootstrap_workspace(
        str(ws), templates_dir=str(templates))
    assert result["synced"] == ["business", "life"]
    assert (ws / "templates" / "business" / "01_plan.md").is_file()
    assert (ws / "instances" / "business").is_dir()
    assert (ws / "instances" / "life").is_dir()


def test_bootstrap_workspace_without_templates_names_the_fix(monkeypatch,
                                                             tmp_path):
    ws, _ = install_fake_startupos(monkeypatch, tmp_path)
    with pytest.raises(startupos_bridge.StartupOSBridgeError,
                       match="do not ship in the startupos pip wheel"):
        startupos_bridge.bootstrap_workspace(str(ws))
