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

"""Design System API as an agent or the editor drives it: read the
canonical document, patch it, import one. No Designer internals."""

from __future__ import annotations

import copy
import json
import types
from pathlib import Path

import frappe
import pytest
import yaml

from studio_src.api import design_system as api
from studio_src.lib import engine_dict as lib

DEFAULT_YAML = Path(__file__).resolve().parents[2] / "designer" / "systems" / "default.yaml"

OLD_KEYS = {"name", "system_name", "brand_name", "customer", "tokens", "fonts",
            "type_scale", "grid", "stroke_widths", "max_colors", "gradient",
            "contrast"}


class FakeDoc:
    """Just enough of a frappe Document: attribute fields, child rows
    as namespaces, set/update/save/insert."""

    def __init__(self, store, data):
        self.__dict__["_store"] = store
        for key, value in data.items():
            self.set(key, value)
        for field in ("brand_name", "customer", "is_default", "seed_color_1",
                      "seed_color_2", "seed_color_3", "modified"):
            self.__dict__.setdefault(field, None)

    def __deepcopy__(self, memo):
        clone = FakeDoc.__new__(FakeDoc)
        clone.__dict__.update({k: v if k == "_store" else copy.deepcopy(v, memo)
                               for k, v in self.__dict__.items()})
        return clone

    def set(self, key, value):
        if isinstance(value, list):
            value = [types.SimpleNamespace(**{"derived": 0, "descriptor": None,
                                              **row}) for row in value]
        setattr(self, key, value)

    def update(self, fields):
        for key, value in fields.items():
            self.set(key, value)

    def _check(self):
        problems = lib.validate_system_fields(self)
        if problems:
            frappe.throw("; ".join(problems))

    def save(self):
        self._check()
        self._store[self.name] = self

    def insert(self):
        self.name = self.system_name
        self.save()


@pytest.fixture
def store(monkeypatch):
    store = {}

    def get_doc(arg, name=None):
        if isinstance(arg, dict):
            return FakeDoc(store, {k: v for k, v in arg.items() if k != "doctype"})
        return copy.deepcopy(store[name])   # like a fresh DB read

    monkeypatch.setattr(frappe, "get_doc", get_doc, raising=False)
    monkeypatch.setattr(frappe, "has_permission", lambda *a, **k: True,
                        raising=False)
    monkeypatch.setattr(frappe, "db", types.SimpleNamespace(
        exists=lambda doctype, name: name in store), raising=False)
    return store


def _derived(store):
    from designer.palette import derive_system

    fields = lib.doc_fields_from_engine_dict(
        derive_system(["#1a56db", "#f59e0b"]), derived=True)
    doc = FakeDoc(store, {**fields, "system_name": "Acme", "name": "Acme",
                          "seed_color_1": "#1a56db", "seed_color_2": "#f59e0b"})
    doc.save()
    return doc


def test_get_keeps_the_old_shape_and_adds_the_contract(store):
    pytest.importorskip("designer")
    _derived(store)
    out = api.get_design_system("Acme")
    assert OLD_KEYS <= set(out)
    assert out["system"]["schema_version"] == lib.SCHEMA_VERSION
    assert out["fingerprint"] == lib.fingerprint(out["system"])
    assert out["seed_colors"] == ["#1a56db", "#f59e0b"]
    assert all(t["derived"] for t in out["tokens"])


def test_patch_tokens_fonts_and_print(store):
    pytest.importorskip("designer")
    _derived(store)
    before = api.get_design_system("Acme")
    out = api.update_design_system("Acme", json.dumps({
        "color": {"tokens": {"accent": {"hex": "#ff6600"},
                             "neutral-100": None,
                             "brand-green": {"hex": "#10b981", "role": "secondary"}}},
        "typography": {"fonts": ["Outfit", "sans-serif"]},
        "print": {"bleed": 0},
    }), expected_fingerprint=before["fingerprint"])

    tokens = {t["name"]: t for t in out["tokens"]}
    assert "neutral-100" not in tokens
    assert tokens["accent"]["hex"] == "#ff6600" and not tokens["accent"]["derived"]
    assert tokens["accent"]["role"] == "accent"            # role kept by merge
    assert tokens["primary"]["derived"]                     # untouched stays derived
    assert tokens["brand-green"] == {"name": "brand-green", "hex": "#10b981",
                                     "role": "secondary", "derived": False}
    assert out["system"]["typography"]["fonts"] == ["Outfit", "sans-serif"]
    assert out["system"]["print"]["bleed"] == 0
    assert out["system"]["print"]["max_ink_coverage"] == 300   # other keys kept
    assert out["system"]["extensions"]["designer"] == \
        before["system"]["extensions"]["designer"]
    assert out["fingerprint"] != before["fingerprint"]


def test_stale_fingerprint_is_refused(store):
    pytest.importorskip("designer")
    _derived(store)
    with pytest.raises(frappe.ValidationError, match="changed since"):
        api.update_design_system("Acme", {"layout": {"grid": 4}},
                                 expected_fingerprint="sha256:old")


def test_bad_patch_is_refused_and_nothing_changes(store):
    pytest.importorskip("designer")
    _derived(store)
    before = api.get_design_system("Acme")["fingerprint"]
    with pytest.raises(frappe.ValidationError):
        api.update_design_system("Acme", {"color": {"tokens": {"x": {"hex": "red"}}}})
    with pytest.raises(frappe.ValidationError, match="schema_version"):
        api.update_design_system("Acme", {"schema_version": 2})
    assert api.get_design_system("Acme")["fingerprint"] == before


def test_removing_a_section_falls_back_to_defaults(store):
    pytest.importorskip("designer")
    _derived(store)
    out = api.update_design_system("Acme", {"print": None, "extensions": None})
    assert out["system"]["print"] == {"bleed": 0.0, "min_stroke": 0.0,
                                      "max_ink_coverage": 0.0}
    assert "extensions" not in out["system"]


def test_create_imports_a_yaml_system(store):
    designer = pytest.importorskip("designer")
    data = yaml.safe_load(DEFAULT_YAML.read_text())
    out = api.create_design_system(json.dumps(data), name="From YAML")
    assert out["system_name"] == "From YAML"
    assert not any(t["derived"] for t in out["tokens"])
    engine = designer.system_from_dict(out["system"])
    assert engine.alignment_tolerance == 2.0
    assert [t.name for t in engine.colors] == list(data["color"]["tokens"])
    with pytest.raises(frappe.ValidationError, match="already exists"):
        api.create_design_system(data, name="From YAML")
