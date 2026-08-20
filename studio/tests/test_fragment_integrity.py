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

"""Fragment-level consistency: every module imports with a stubbed
frappe, every manifest hook resolves to a real function, and the
DocType JSONs follow the composer convention."""

import importlib
import json
from pathlib import Path

import pytest

FRAGMENT = Path(__file__).resolve().parent.parent / "frappe"
MANIFEST = json.loads((FRAGMENT / "manifest.json").read_text())
TENANT_HOOKS = MANIFEST["app_type"]["tenant"]["hooks"]

MODULES = [
    "lib.engine_dict", "lib.tokens", "lib.gating", "lib.campaign",
    "lib.feedback", "lib.documents", "lib.briefs",
    "engine_bridge", "startupos_bridge", "pipeline", "documents_pipeline",
    "tasks",
    "providers", "providers.base", "providers.mock", "providers.stubs",
    "api._common", "api.design_request", "api.design_system",
    "api.design_campaign", "api.design_approval", "api.document_request",
]

EXPECTED_DOCTYPES = [
    "Design System", "Design Color Token", "Design Font",
    "Design Request", "Design Candidate", "Design Candidate Revision",
    "Design Approval", "Design Campaign", "Design Campaign Format",
    "Generation Provider", "Design Print Job", "Design Studio Settings",
    "Document Request", "Document Request Output",
]

GUEST_METHODS = {"get_review", "submit_review"}


@pytest.mark.parametrize("module", MODULES)
def test_module_imports_without_frappe_installed(module):
    importlib.import_module(f"studio_src.{module}")


def test_manifest_shape():
    assert MANIFEST["name"] == "studio"
    # Both personas declared: tenant carries everything, control is the
    # mandatory empty block that lets control-marked shells strip
    # src/tenant/ (composer skips only *declared* persona folders).
    assert set(MANIFEST["app_type"]) == {"tenant", "control"}
    assert MANIFEST["app_type"]["control"] == {}
    tenant = MANIFEST["app_type"]["tenant"]
    assert tenant["dependencies"][0] == "designer-compliance"
    startupos_dep = tenant["dependencies"][1]
    assert startupos_dep.startswith("startupos @ git+https://github.com/"
                                    "RokctAI/The-Rokct-Protocol@")
    assert startupos_dep.endswith("#subdirectory=core/utils/startup_os")
    # Git-pinned (40-hex SHA) until startupos is on PyPI.
    sha = startupos_dep.split("@")[2].split("#")[0]
    assert len(sha) == 40 and all(c in "0123456789abcdef" for c in sha)
    hooks = TENANT_HOOKS
    assert set(hooks) >= {"whitelisted_methods", "fixtures", "scheduler_events"}


def _resolve(dotted_impl_path):
    """'{app_name}.studio.tenant.api.x.y' -> attribute y of module
    studio_src.api.x (the composed-layout equivalent)."""
    prefix = "{app_name}.studio.tenant."
    assert dotted_impl_path.startswith(prefix), dotted_impl_path
    rest = dotted_impl_path[len(prefix):]
    module_path, func_name = rest.rsplit(".", 1)
    module = importlib.import_module(f"studio_src.{module_path}")
    return getattr(module, func_name), func_name


def test_every_whitelisted_method_resolves_and_is_whitelisted():
    methods = TENANT_HOOKS["whitelisted_methods"]
    assert len(methods) >= 20
    for public, impl in methods.items():
        assert public.startswith("{app_name}.api."), public
        func, func_name = _resolve(impl)
        assert callable(func), impl
        assert getattr(func, "_is_whitelisted", False), \
            f"{impl} is not decorated with frappe.whitelist"
        assert public.rsplit(".", 1)[1] == func_name
        if func_name in GUEST_METHODS:
            assert func._allow_guest, f"{impl} must allow guest access"
        else:
            assert not getattr(func, "_allow_guest", False), \
                f"{impl} must NOT allow guest access"


def test_scheduler_events_resolve():
    events = TENANT_HOOKS["scheduler_events"]
    assert set(events) == {"daily", "hourly"}
    assert len(events["daily"]) == 2 and len(events["hourly"]) == 1
    for paths in events.values():
        for dotted in paths:
            func, _ = _resolve(dotted)
            assert callable(func)


def test_fixtures_cover_every_doctype():
    fixtures = TENANT_HOOKS["fixtures"]
    covered = set()
    for entry in fixtures:
        assert entry["dt"] == "DocType"
        for field, op, value in entry["filters"]:
            assert field == "name" and op == "in"
            covered.update(value)
    assert covered == set(EXPECTED_DOCTYPES)


def _doctype_jsons():
    for path in sorted((FRAGMENT / "src" / "tenant" / "doctype").glob("*/*.json")):
        yield path, json.loads(path.read_text())


def test_doctype_folders_follow_convention():
    names = set()
    for path, data in _doctype_jsons():
        snake = data["name"].lower().replace(" ", "_")
        assert path.parent.name == snake
        assert path.stem == snake
        assert (path.parent / "__init__.py").exists()
        assert (path.parent / f"{snake}.py").exists()
        assert data["module"] == "{module_name}"
        names.add(data["name"])
    assert names == set(EXPECTED_DOCTYPES)


def test_doctype_permissions_and_flags():
    child_tables = {"Design Color Token", "Design Font",
                    "Design Campaign Format", "Document Request Output"}
    for _, data in _doctype_jsons():
        if data["name"] in child_tables:
            assert data.get("istable") == 1
        else:
            roles = {p["role"] for p in data["permissions"]}
            assert "System Manager" in roles, data["name"]
        if data["name"] == "Design Studio Settings":
            assert data.get("issingle") == 1


def test_doctype_links_stay_inside_known_doctypes():
    known = set(EXPECTED_DOCTYPES) | {
        "Customer", "User", "Sales Order", "Sales Invoice"}
    for _, data in _doctype_jsons():
        for field in data["fields"]:
            if field["fieldtype"] in ("Link", "Table"):
                assert field["options"] in known, \
                    f"{data['name']}.{field['fieldname']} -> {field['options']}"


def test_key_spec_fields_present():
    fields = {}
    for _, data in _doctype_jsons():
        fields[data["name"]] = {f["fieldname"]: f for f in data["fields"]}

    req = fields["Design Request"]
    assert req["source_mode"]["default"] == "Uploaded Artwork"
    assert req["n_candidates"]["default"] == "3"
    assert "sales_order" in req and "sales_invoice" in req
    assert "Draft" in req["status"]["options"]

    system = fields["Design System"]
    assert {"seed_color_1", "seed_color_2", "seed_color_3"} <= set(system)
    assert system["customer"]["options"] == "Customer"

    token = fields["Design Approval"]["token"]
    assert token.get("unique") == 1 and token.get("read_only") == 1

    cand = fields["Design Candidate"]
    assert cand["revision_of"]["options"] == "Design Candidate"

    provider = fields["Generation Provider"]["provider_type"]
    assert provider["options"].split("\n") == \
        ["upload", "mock", "openai", "stability", "custom_http"]

    job = fields["Design Print Job"]
    assert {"press_pdf", "vendor_name", "final_size", "sides",
            "material_finish", "sales_order", "sales_invoice"} <= set(job)
    assert "Proof Approved" in job["status"]["options"]

    settings = fields["Design Studio Settings"]
    assert "keep_raw_days" in settings

    docreq = fields["Document Request"]
    assert docreq["business_name"]["reqd"] == 1
    assert docreq["document_scope"]["options"].split("\n") == [
        "Full Suite", "Plan Chapters", "Pitch Deck", "Financial Model",
        "Briefs"]
    assert docreq["status"]["options"] == req["status"]["options"], \
        "Document Request must share Design Request's status machine"
    assert docreq["outputs"]["options"] == "Document Request Output"
    assert {"questions_file", "workspace_root", "compliance_root",
            "render_binaries", "warnings", "completeness"} <= set(docreq)


def test_no_lingering_design_studio_references():
    """The fragment renamed to studio/ — the old module identity must
    not survive anywhere in the tree (composer hooks would break)."""
    old = "design" + "_studio"
    fragment_root = Path(__file__).resolve().parent.parent
    offenders = []
    for path in sorted(fragment_root.rglob("*")):
        if path.suffix not in (".py", ".json", ".md"):
            continue
        if "__pycache__" in path.parts or path.name == Path(__file__).name:
            continue
        text = path.read_text(encoding="utf-8")
        # The Design Studio Settings doctype keeps its name, so its
        # snake_case folder/file identity legitimately remains.
        text = text.replace(old + "_settings", "")
        if old in text:
            offenders.append(str(path.relative_to(fragment_root)))
    assert not offenders, offenders


def test_provider_registry():
    from studio_src.providers import ProviderError, get_provider

    class Doc:
        style_suffix = "flat vector"

    Doc.provider_type = "mock"
    png = get_provider(Doc()).generate("a blue logo", "128x128")
    assert png[:8] == b"\x89PNG\r\n\x1a\n"

    Doc.provider_type = "upload"
    with pytest.raises(ProviderError):
        get_provider(Doc()).generate("x", "512x512")

    for stub in ("openai", "stability", "custom_http"):
        Doc.provider_type = stub
        with pytest.raises(NotImplementedError):
            get_provider(Doc()).generate("x", "512x512")

    Doc.provider_type = "nope"
    with pytest.raises(ProviderError):
        get_provider(Doc())


def test_provider_style_suffix_is_appended():
    from studio_src.providers.base import BaseProvider

    class Doc:
        provider_type = "mock"
        style_suffix = "flat vector illustration"

    provider = BaseProvider(Doc())
    assert provider.full_prompt("a fox logo") == \
        "a fox logo, flat vector illustration"
    assert provider.full_prompt("") == "flat vector illustration"


def test_mock_provider_output_survives_the_real_engine():
    designer = pytest.importorskip("designer")
    import tempfile
    from pathlib import Path as P

    from studio_src.providers.mock import MockProvider

    class Doc:
        provider_type = "mock"
        style_suffix = ""

    png = MockProvider(Doc()).generate("logo", "256x256")
    with tempfile.TemporaryDirectory() as tmp:
        path = P(tmp) / "mock.png"
        path.write_bytes(png)
        system = designer.system_from_dict({
            "name": "T",
            "color": {"tokens": {"primary": "#1a56db", "accent": "#f59e0b",
                                 "white": "#ffffff"}},
        })
        engine = designer.ComplianceEngine(system)
        doc = engine.load(str(path))
        report = engine.comply(doc)
        assert report.score > 0
        from designer.svg import serialize
        assert "<svg" in serialize(doc)
