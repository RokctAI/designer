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

"""Design System <-> engine schema round-trip (SAAS_SPEC section 7)."""

import pytest

from studio_src.lib import engine_dict as lib


def sample_doc():
    return {
        "system_name": "Acme Brand",
        "color_tokens": [
            {"token_name": "primary", "hex": "#1a56db", "role": "primary"},
            {"token_name": "accent", "hex": "#f59e0b", "role": "accent"},
            {"token_name": "ink", "hex": "#111827", "role": "ink"},
            {"token_name": "white", "hex": "#ffffff", "role": "surface"},
        ],
        "max_colors": 6,
        "snap_warning_distance": 0.18,
        "fonts": [{"font_name": "Inter"}, {"font_name": "Helvetica Neue"}],
        "type_scale": "12,14,16,20,24,32,48,64",
        "grid": 8,
        "min_element_size": 4,
        "stroke_widths": "1,2,4,8",
        "min_contrast_text": 4.5,
        "min_contrast_large_text": 3.0,
        "large_text_size": 24,
        "gradient_allowed": 1,
        "gradient_max_stops": 4,
    }


def test_engine_dict_shape():
    data = lib.engine_dict_from_doc(sample_doc())
    assert data["name"] == "Acme Brand"
    assert data["color"]["tokens"]["primary"] == {"hex": "#1a56db",
                                                  "role": "primary"}
    assert data["color"]["max_colors"] == 6
    assert data["typography"]["fonts"] == ["Inter", "Helvetica Neue"]
    assert data["typography"]["scale"] == [12, 14, 16, 20, 24, 32, 48, 64]
    assert data["layout"]["grid"] == 8.0
    assert data["stroke"]["widths"] == [1, 2, 4, 8]
    assert data["gradient"] == {"allowed": True, "max_stops": 4}
    assert data["accessibility"]["min_contrast_text"] == 4.5


def test_round_trips_through_real_engine():
    designer = pytest.importorskip("designer")
    system = designer.system_from_dict(lib.engine_dict_from_doc(sample_doc()))
    assert system.name == "Acme Brand"
    assert [t.name for t in system.colors] == ["primary", "accent", "ink", "white"]
    assert system.colors[0].hex == "#1a56db"
    assert system.colors[0].role == "primary"
    assert system.fonts == ["Inter", "Helvetica Neue"]
    assert system.max_colors == 6
    assert system.grid == 8.0
    assert system.stroke_widths == [1, 2, 4, 8]
    assert system.gradients_allowed is True
    assert system.gradient_max_stops == 4


def test_gradient_ban_round_trips():
    doc = sample_doc()
    doc["gradient_allowed"] = 0
    designer = pytest.importorskip("designer")
    system = designer.system_from_dict(lib.engine_dict_from_doc(doc))
    assert system.gradients_allowed is False


def test_validate_catches_bad_hex_and_empty_tokens():
    doc = sample_doc()
    doc["color_tokens"][0]["hex"] = "blue"
    problems = lib.validate_system_fields(doc)
    assert any("primary" in p for p in problems)

    assert lib.validate_system_fields({"color_tokens": []})


def test_validate_catches_bad_csv_and_seeds():
    doc = sample_doc()
    doc["type_scale"] = "12,banana"
    assert any("Type Scale" in p for p in lib.validate_system_fields(doc))

    doc = sample_doc()
    doc["seed_color_1"] = "nope"
    assert any("Seed Color 1" in p for p in lib.validate_system_fields(doc))


def test_parse_csv_floats():
    assert lib.parse_csv_floats(" 1, 2.5 ,4,") == [1.0, 2.5, 4.0]
    with pytest.raises(ValueError):
        lib.parse_csv_floats("1,x", "Widths")


def test_parse_seed_colors():
    assert lib.parse_seed_colors('["#1A56DB", "#f59e0b"]') == \
        ["#1a56db", "#f59e0b"]
    assert lib.parse_seed_colors("#1a56db,#f59e0b,#111827") == \
        ["#1a56db", "#f59e0b", "#111827"]
    with pytest.raises(ValueError):
        lib.parse_seed_colors(["#1a56db"])          # too few
    with pytest.raises(ValueError):
        lib.parse_seed_colors(["#1a56db"] * 4)      # too many
    with pytest.raises(ValueError):
        lib.parse_seed_colors(["#1a56db", "red"])   # not hex


def test_doc_fields_inverse_mapping():
    original = lib.engine_dict_from_doc(sample_doc())
    fields = lib.doc_fields_from_engine_dict(original, derived=True)
    assert all(row["derived"] == 1 for row in fields["color_tokens"])
    assert fields["type_scale"] == "12,14,16,20,24,32,48,64"
    assert fields["stroke_widths"] == "1,2,4,8"
    # And it survives the forward mapping again (true round trip).
    fields["system_name"] = "Acme Brand"
    assert lib.engine_dict_from_doc(fields) == original


def test_derive_system_output_is_persistable_if_engine_has_it():
    palette = pytest.importorskip("designer.palette")
    designer = pytest.importorskip("designer")
    system_dict = palette.derive_system(["#1a56db", "#f59e0b"])
    # Engine accepts its own derivation...
    designer.system_from_dict(system_dict)
    # ...and the fragment can persist it as editable DocType rows that
    # round-trip back through the engine.
    fields = lib.doc_fields_from_engine_dict(system_dict)
    fields["system_name"] = "Derived"
    designer.system_from_dict(lib.engine_dict_from_doc(fields))
