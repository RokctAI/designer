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

"""startupos_bridge against a stubbed ``startupos`` package: the bridge
must call the engine's documented API, surface its honest outputs
(warnings, missing answers, coaching) untouched, and wrap every engine
failure in StartupOSBridgeError."""

from __future__ import annotations

import os
import sys
import types

import pytest

from studio_src import startupos_bridge


class FakeStartupOSError(Exception):
    pass


class FakeResult:
    def __init__(self, out_dir):
        self.written = ["01_executive_summary.md", "compliance_log.md",
                        "investor_pitch_deck.pptx"]
        self.output_dir = out_dir
        self.warnings = ["07_financial_model.md: unresolved placeholder"]
        self.missing_fields = {"pricing_tiers": "Pricing Tiers"}
        self.completeness = 62.5
        self.compliance_status = 0


def _install_fake_startupos(monkeypatch, tmp_path, fail=False):
    """Build a minimal fake of the pip package's surface the bridge
    touches, injected via sys.modules (the real engine is not installed
    in this repo's test environment)."""
    ws = tmp_path / "StartupOS"
    calls = {}

    pkg = types.ModuleType("startupos")
    pkg.__version__ = "0.0-test"

    errors = types.ModuleType("startupos.errors")
    errors.StartupOSError = FakeStartupOSError

    paths = types.ModuleType("startupos.paths")
    paths.resolve_workspace_root = \
        lambda explicit=None, verbose=True: str(explicit or ws)
    paths.instance_dir = lambda root, t, n: os.path.join(
        str(root), "instances", t, n)
    paths.templates_dir = lambda root, t: os.path.join(
        str(root), "templates", t)

    safe_io = types.ModuleType("startupos.safe_io")

    def atomic_write(destination, content):
        os.makedirs(os.path.dirname(destination), exist_ok=True)
        with open(destination, "w", encoding="utf-8") as fh:
            fh.write(content)

    safe_io.atomic_write = atomic_write

    compiler = types.ModuleType("startupos.compiler")

    def compile_instance(instance_type, instance_name, workspace_root=None,
                         compliance_root=None, quiet=False, render=False):
        if fail:
            raise FakeStartupOSError("Missing template folder")
        calls["compile"] = {"type": instance_type, "name": instance_name,
                            "root": workspace_root, "render": render,
                            "compliance_root": compliance_root}
        return FakeResult(str(ws / "out"))

    def load_instance_data(instance_type, instance_name, workspace_root=None,
                           compliance_root=None, quiet=True):
        if fail:
            raise FakeStartupOSError("No questions.md")
        data = types.SimpleNamespace(out_dir=str(ws / "out"))
        calls["load"] = {"type": instance_type, "name": instance_name}
        return data

    compiler.compile_instance = compile_instance
    compiler.load_instance_data = load_instance_data

    branding = types.ModuleType("startupos.branding")
    branding.export_briefs = lambda data: (
        ["briefs/poster.json", "briefs/flyer.json"],
        ["poster brief skipped - answer 'Pricing Tiers' in questions.md"],
    )

    parser = types.ModuleType("startupos.parser")

    def parse_questions_md(filepath):
        profile = types.SimpleNamespace(
            answers={"trading_name": "Acme"},
            pending={"pricing_tiers": "[TODO]"},
            labels={"trading_name": "Trading Name",
                    "pricing_tiers": "Pricing Tiers"},
            answered_count=1, total_count=2)
        return profile

    parser.parse_questions_md = parse_questions_md

    agent_bridge = types.ModuleType("startupos.agent_bridge")

    def auto_provision_profile(instance_type, instance_name,
                               primary_base=None, key_relationships=None,
                               jurisdiction=None, workspace_root=None,
                               seed=None, full=False):
        if fail:
            raise FakeStartupOSError("Unsafe instance name")
        calls["provision"] = {"type": instance_type, "name": instance_name,
                              "seed": seed, "jurisdiction": jurisdiction}
        return str(ws / "instances" / instance_type / instance_name
                   / "questions.md")

    agent_bridge.auto_provision_profile = auto_provision_profile

    for name, module in (("startupos", pkg),
                         ("startupos.errors", errors),
                         ("startupos.paths", paths),
                         ("startupos.safe_io", safe_io),
                         ("startupos.compiler", compiler),
                         ("startupos.branding", branding),
                         ("startupos.parser", parser),
                         ("startupos.agent_bridge", agent_bridge)):
        monkeypatch.setitem(sys.modules, name, module)
        if name != "startupos":
            setattr(pkg, name.split(".")[1], module)
    return ws, calls


def test_missing_engine_raises_bridge_error(monkeypatch):
    """Without the pip package every entry point fails with the
    install hint, not an ImportError."""
    monkeypatch.setitem(sys.modules, "startupos", None)
    with pytest.raises(startupos_bridge.StartupOSBridgeError,
                       match="not installed"):
        startupos_bridge.compile_documents("Acme")


def test_provision_profile_passes_seed_answers(monkeypatch, tmp_path):
    ws, calls = _install_fake_startupos(monkeypatch, tmp_path)
    path = startupos_bridge.provision_profile(
        "Acme", answers={"trading_name": "Acme (Pty) Ltd"},
        jurisdiction="ZA")
    assert path.endswith(os.path.join("Acme", "questions.md"))
    assert calls["provision"]["seed"] == {"trading_name": "Acme (Pty) Ltd"}
    assert calls["provision"]["jurisdiction"] == "ZA"
    assert calls["provision"]["type"] == "business"


def test_compile_documents_surfaces_honest_gaps(monkeypatch, tmp_path):
    ws, calls = _install_fake_startupos(monkeypatch, tmp_path)
    result = startupos_bridge.compile_documents(
        "Acme", workspace_root=str(ws), render=True)
    assert calls["compile"]["render"] is True
    assert result["written"][-1] == "investor_pitch_deck.pptx"
    assert result["missing_fields"] == {"pricing_tiers": "Pricing Tiers"}
    assert result["warnings"] == \
        ["07_financial_model.md: unresolved placeholder"]
    assert result["completeness"] == 62.5


def test_compile_documents_wraps_engine_errors(monkeypatch, tmp_path):
    _install_fake_startupos(monkeypatch, tmp_path, fail=True)
    with pytest.raises(startupos_bridge.StartupOSBridgeError,
                       match="Missing template folder"):
        startupos_bridge.compile_documents("Acme")


def test_parse_questions_returns_pending_map(monkeypatch, tmp_path):
    _install_fake_startupos(monkeypatch, tmp_path)
    parsed = startupos_bridge.parse_questions("questions.md")
    assert parsed["answers"] == {"trading_name": "Acme"}
    assert parsed["pending"] == {"pricing_tiers": "[TODO]"}
    assert parsed["labels"]["pricing_tiers"] == "Pricing Tiers"
    assert (parsed["answered_count"], parsed["total_count"]) == (1, 2)


def test_export_briefs_returns_absolute_paths_and_coaching(monkeypatch,
                                                           tmp_path):
    ws, _ = _install_fake_startupos(monkeypatch, tmp_path)
    result = startupos_bridge.export_briefs("Acme")
    assert result["briefs"] == [
        os.path.join(str(ws / "out"), "briefs", "poster.json"),
        os.path.join(str(ws / "out"), "briefs", "flyer.json"),
    ]
    assert result["coaching"][0].startswith("poster brief skipped")


def test_write_questions_places_file_at_canonical_path(monkeypatch,
                                                       tmp_path):
    ws, _ = _install_fake_startupos(monkeypatch, tmp_path)
    path = startupos_bridge.write_questions("Acme", "# Questions\n")
    assert path == os.path.join(
        str(ws), "instances", "business", "Acme", "questions.md")
    with open(path, encoding="utf-8") as fh:
        assert fh.read() == "# Questions\n"


def test_bootstrap_workspace_syncs_local_templates(monkeypatch, tmp_path):
    ws, _ = _install_fake_startupos(monkeypatch, tmp_path)
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
    ws, _ = _install_fake_startupos(monkeypatch, tmp_path)
    with pytest.raises(startupos_bridge.StartupOSBridgeError,
                       match="do not ship in the startupos pip wheel"):
        startupos_bridge.bootstrap_workspace(str(ws))
