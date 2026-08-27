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

"""A minimal fake of the ``startupos`` pip package, faithful to the
documented API surface the bridge touches (the real engine is not
installed in this repo's test environment). Selective generation
mirrors the real semantics of PR #275: ``compile_instance(only=[...])``
writes exactly the requested artifacts plus the compliance log for a
business instance and never prunes; unknown or empty selections raise
``UnknownArtifactError`` listing the valid stems;
``missing_for_artifacts`` reports per-artifact unanswered questions and
ungated evidence."""

from __future__ import annotations

import os
import sys
import types


class FakeStartupOSError(Exception):
    pass


class FakeUnknownArtifactError(FakeStartupOSError):
    pass


# stem -> the markdown file the template writes (a slice of the real
# business suite), and the binaries derived from selected sources.
ARTIFACTS = {
    "01_executive_summary": "01_executive_summary.md",
    "business_profile": "business_profile.md",
    "investor_pitch_deck": "investor_pitch_deck.md",
    "07_financial_model": "07_financial_model.md",
}
COMPLIANCE_LOG = "compliance_log"
BINARIES = {
    "investor_pitch_deck.md": "investor_pitch_deck.pptx",
    "07_financial_model.md": "financial_model.xlsx",
}

# The engine's merged renderer namespace: real answers verbatim, the
# engine's honest markers for everything unanswered or unverified.
VALUES = {
    "trading_name": "Acme",
    "company_name": "Acme",
    "core_value_proposition": "Compliance-grade documents on demand",
    "vision_statement": "Every venture bankable in a week",
    "primary_products": "Document automation platform",
    "customer_segments": "Tender teams and founders",
    "target_sectors": "Not yet provided",
    "head_office": "Polokwane, Limpopo",
    "executive_team": "N. Dlamini - Managing Director\nS. van Wyk - CTO",
    "reg_number": "2014/123456/07",
    "tax_number": "Pending — tax reference not verified — add Tax_Pin.pdf",
    "pricing_tiers": "Not yet provided",
}

GAPS = {
    "business_profile": {
        "unanswered": {"pricing_tiers": "Pricing Tiers"},
        "evidence": {
            "tax_number": "tax reference not verified — add Tax_Pin.pdf"},
    },
}


def _resolve_selection(names, instance_type):
    valid = set(ARTIFACTS)
    if instance_type == "business":
        valid.add(COMPLIANCE_LOG)
    listed = ", ".join(sorted(valid))
    stems = []
    for raw in names:
        stem = str(raw).strip().replace("\\", "/")
        if stem.endswith(".md"):
            stem = stem[: -len(".md")]
        stem = stem.rsplit("/", 1)[-1]
        if stem not in valid:
            raise FakeUnknownArtifactError(
                f"Unknown {instance_type} artifact {str(raw).strip()!r}. "
                f"Valid artifacts: {listed}")
        if stem not in stems:
            stems.append(stem)
    if not stems:
        raise FakeUnknownArtifactError(
            f"Empty artifact selection. Name at least one of: {listed} — "
            "or omit the selection to compile the full suite.")
    return stems


class FakeResult:
    def __init__(self, out_dir, written):
        self.written = written
        self.output_dir = out_dir
        self.warnings = ["07_financial_model.md: unresolved placeholder"]
        self.missing_fields = {"pricing_tiers": "Pricing Tiers"}
        self.completeness = 62.5
        self.compliance_status = 0


def install_fake_startupos(monkeypatch, tmp_path, fail=False):
    """Inject the fake package via sys.modules. Returns (workspace
    path, calls dict recording every engine invocation)."""
    ws = tmp_path / "StartupOS"
    calls = {}

    pkg = types.ModuleType("startupos")
    pkg.__version__ = "0.0-test"

    errors = types.ModuleType("startupos.errors")
    errors.StartupOSError = FakeStartupOSError
    errors.UnknownArtifactError = FakeUnknownArtifactError

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
                         compliance_root=None, quiet=False, render=False,
                         only=None):
        if fail:
            raise FakeStartupOSError("Missing template folder")
        calls["compile"] = {"type": instance_type, "name": instance_name,
                            "root": workspace_root, "render": render,
                            "compliance_root": compliance_root,
                            "only": list(only) if only is not None else None}
        if only is None:
            markdown = list(ARTIFACTS.values())
        else:
            stems = _resolve_selection(only, instance_type)
            markdown = [ARTIFACTS[s] for s in ARTIFACTS if s in stems]
        written = list(markdown)
        if instance_type == "business":
            written.append("compliance_log.md")
        if render and instance_type == "business":
            written.extend(BINARIES[source] for source in markdown
                           if source in BINARIES)
        return FakeResult(str(ws / "out"), written)

    def load_instance_data(instance_type, instance_name, workspace_root=None,
                           compliance_root=None, quiet=True):
        if fail:
            raise FakeStartupOSError("No questions.md")
        calls["load"] = {"type": instance_type, "name": instance_name}
        return types.SimpleNamespace(
            out_dir=str(ws / "out"),
            instance_type=instance_type,
            instance_name=instance_name,
            jurisdiction=types.SimpleNamespace(code="ZA"),
            values=dict(VALUES),
        )

    def missing_for_artifacts(data, names):
        stems = _resolve_selection(names, data.instance_type)
        return {stem: {
            "unanswered": dict(GAPS.get(stem, {}).get("unanswered", {})),
            "evidence": dict(GAPS.get(stem, {}).get("evidence", {})),
        } for stem in stems}

    compiler.compile_instance = compile_instance
    compiler.load_instance_data = load_instance_data
    compiler.missing_for_artifacts = missing_for_artifacts

    branding = types.ModuleType("startupos.branding")
    branding.export_briefs = lambda data: (
        ["briefs/poster.json", "briefs/flyer.json"],
        ["poster brief skipped - answer 'Pricing Tiers' in questions.md"],
    )

    parser = types.ModuleType("startupos.parser")

    def parse_questions_md(filepath):
        return types.SimpleNamespace(
            answers={"trading_name": "Acme"},
            pending={"pricing_tiers": "[TODO]"},
            labels={"trading_name": "Trading Name",
                    "pricing_tiers": "Pricing Tiers"},
            answered_count=1, total_count=2)

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
