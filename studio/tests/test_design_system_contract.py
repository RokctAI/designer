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

"""The canonical design-system contract (docs/DESIGN_SYSTEM_CONTRACT.md):
DocType, canonical document, derivation, YAML files and the Designer
engine must agree, and products must be able to ignore what they don't
understand."""

import json
from pathlib import Path

import pytest
import yaml

from studio_src.lib import engine_dict as lib

designer = pytest.importorskip("designer")
from designer.palette import derive_system  # noqa: E402
from designer.tokens import (ACCENT_ROLES, SURFACE_ROLES, TEXT_ROLES,  # noqa: E402
                             load_system, system_from_dict)

TESTS = Path(__file__).resolve().parent
DOCTYPES = TESTS.parent / "frappe" / "src" / "tenant" / "doctype"
SYSTEMS = TESTS.parent.parent / "designer" / "systems"


def _doctype(snake):
    return json.loads((DOCTYPES / snake / f"{snake}.json").read_text())


def _field(snake, fieldname):
    return next(f for f in _doctype(snake)["fields"]
                if f["fieldname"] == fieldname)


def _persist(system_dict, derived=True):
    """What the DocType stores for a canonical document, as a dict doc."""
    fields = lib.doc_fields_from_engine_dict(system_dict, derived=derived)
    fields["system_name"] = system_dict.get("name", "Test")
    return fields


def _legacy_doc():
    """A Design System saved before print fields and extensions existed."""
    return {
        "system_name": "Legacy",
        "color_tokens": [
            {"token_name": "primary", "hex": "#1a56db", "role": "primary"},
            {"token_name": "muted", "hex": "#6b7280", "role": "muted"},
            {"token_name": "white", "hex": "#ffffff", "role": "surface"},
        ],
        "max_colors": 6, "snap_warning_distance": 0.18,
        "fonts": [{"font_name": "Inter"}],
        "type_scale": "12,16,24", "grid": 8, "min_element_size": 4,
        "stroke_widths": "1,2", "min_contrast_text": 4.5,
        "min_contrast_large_text": 3.0, "large_text_size": 24,
        "gradient_allowed": 1, "gradient_max_stops": 4,
    }


# ------------------------------------------------- schema <-> roles agree

def test_role_select_matches_the_contract():
    options = _field("design_color_token", "role")["options"].split("\n")
    assert tuple(options) == lib.COLOR_ROLES


def test_every_role_an_engine_or_derivation_uses_is_storable():
    stored = set(lib.COLOR_ROLES)
    assert set(SURFACE_ROLES + TEXT_ROLES + ACCENT_ROLES) <= stored
    for seeds in (["#1a56db", "#f59e0b"], ["#1a56db", "#f59e0b", "#10b981"]):
        roles = {t["role"] for t in derive_system(seeds)["color"]["tokens"].values()}
        assert roles <= stored, roles - stored


def test_derived_system_passes_doctype_validation():
    fields = _persist(derive_system(["#1a56db", "#f59e0b", "#10b981"]))
    assert lib.validate_system_fields(fields) == []


def test_unknown_role_is_a_validation_problem():
    doc = _legacy_doc()
    doc["color_tokens"][0]["role"] = "hero"
    assert any("role 'hero'" in p for p in lib.validate_system_fields(doc))


def test_every_core_scalar_field_exists_on_the_doctype():
    names = {f["fieldname"] for f in _doctype("design_system")["fields"]}
    assert set(lib.CORE_SCALAR_FIELDS) <= names


# ------------------------------------------- bootstrap is not lossy any more

def _engine_view(system):
    """Everything the engine enforces, comparable across load paths."""
    return {k: v for k, v in vars(system).items() if k != "name"}


def test_derived_system_survives_persistence_unchanged():
    derived = derive_system(["#1a56db", "#f59e0b", "#10b981"], name="Acme")
    persisted = lib.engine_dict_from_doc(_persist(derived))
    assert persisted["print"] == {"bleed": derived["print"]["bleed"],
                                  "min_stroke": 0.75, "max_ink_coverage": 300}
    assert _engine_view(system_from_dict(persisted)) == \
        _engine_view(system_from_dict(derived))


@pytest.mark.parametrize("path", sorted(SYSTEMS.glob("*.yaml")),
                         ids=lambda p: p.name)
def test_bundled_yaml_round_trips_through_the_doctype(path):
    """YAML is an import/export form of the same contract: storing a
    bundled system in the DocType and reading it back gives the engine
    exactly the system the YAML file gives it."""
    data = yaml.safe_load(path.read_text())
    persisted = lib.engine_dict_from_doc(_persist(data, derived=False))
    assert _engine_view(system_from_dict(persisted)) == \
        _engine_view(load_system(path))


# ------------------------------------------------- old systems still load

def test_legacy_doc_gives_the_engine_what_it_did_before():
    data = lib.engine_dict_from_doc(_legacy_doc())
    assert data["schema_version"] == lib.SCHEMA_VERSION
    assert data["print"] == {"bleed": 0.0, "min_stroke": 0.0,
                             "max_ink_coverage": 0.0}
    assert "extensions" not in data and "brand" not in data
    before = {k: v for k, v in data.items()
              if k not in ("schema_version", "print")}
    assert _engine_view(system_from_dict(data)) == \
        _engine_view(system_from_dict(before))


# ------------------------------- extensions: namespaced, never override core

def test_other_products_namespaces_do_not_change_designer():
    base = lib.engine_dict_from_doc(_legacy_doc())
    extended = lib.merge_patch(base, {
        "motion": {"duration_ms": 200},
        "extensions": {"web": {"radius": 12}, "slides": {"layouts": ["a"]}},
    })
    assert _engine_view(system_from_dict(extended)) == \
        _engine_view(system_from_dict(base))


def test_designer_extension_adds_but_never_overrides_core():
    base = lib.engine_dict_from_doc(_legacy_doc())
    extended = lib.merge_patch(base, {"extensions": {"designer": {
        "layout": {"alignment_tolerance": 5, "grid": 999},
        "color": {"tokens": {"evil": {"hex": "#ff0000"}}},
        "print": {"icc_profile": "profiles/press.icc"},
    }}})
    system = system_from_dict(extended)
    assert system.alignment_tolerance == 5
    assert system.icc_profile == "profiles/press.icc"
    assert system.grid == 8.0
    assert [t.name for t in system.colors] == ["primary", "muted", "white"]


def test_extension_rows_round_trip_and_validate():
    doc = _legacy_doc()
    doc["extensions"] = [{"namespace": "web", "data": '{"radius": 12}'}]
    assert lib.validate_system_fields(doc) == []
    assert lib.engine_dict_from_doc(doc)["extensions"] == {"web": {"radius": 12}}

    for bad in ([{"namespace": "Web Builder", "data": "{}"}],
                [{"namespace": "web", "data": "[1]"}],
                [{"namespace": "web", "data": "{"}],
                [{"namespace": "web", "data": "{}"},
                 {"namespace": "web", "data": "{}"}]):
        doc["extensions"] = bad
        assert lib.validate_system_fields(doc), bad


# ------------------------------------- versioning and agent-style editing

def test_fingerprint_is_order_independent_and_tracks_content():
    data = lib.engine_dict_from_doc(_legacy_doc())
    shuffled = json.loads(json.dumps(dict(reversed(list(data.items())))))
    assert lib.fingerprint(shuffled) == lib.fingerprint(data)
    assert lib.fingerprint(data).startswith("sha256:")
    edited = lib.merge_patch(data, {"layout": {"grid": 4}})
    assert lib.fingerprint(edited) != lib.fingerprint(data)


def test_merge_patch_add_change_remove_tokens():
    data = lib.engine_dict_from_doc(_legacy_doc())
    patched = lib.merge_patch(data, {"color": {"tokens": {
        "accent": {"hex": "#f59e0b", "role": "accent"},
        "primary": {"hex": "#0f4c81"},
        "muted": None,
    }}})
    tokens = patched["color"]["tokens"]
    assert list(tokens) == ["primary", "white", "accent"]
    assert tokens["primary"] == {"hex": "#0f4c81", "role": "primary"}
    assert data["color"]["tokens"]["primary"]["hex"] == "#1a56db"  # untouched
    system_from_dict(lib.engine_dict_from_doc(_persist(patched, derived=False)))


def test_canonical_document_is_plain_json():
    derived = derive_system(["#1a56db", "#f59e0b"])
    data = lib.engine_dict_from_doc(_persist(derived))
    assert json.loads(json.dumps(data)) == data
    assert data["extensions"]["designer"]["layout"] == {
        "alignment_tolerance": 2.0, "role_aware_snapping": True}
