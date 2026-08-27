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

"""Agency template pack: every template parses, matches its format's
trim geometry, restyles from palette roles, and renders."""

from pathlib import Path

import pytest

from designer.formats import get_format, mm_to_px
from designer.palette import derive_system
from designer.svg import parse_svg
from designer.template import (
    AGENCY_PALETTE_ROLES,
    AGENCY_TYPE_SCALE,
    TemplateData,
    palette_for_system,
    render as render_template,
)
from designer.tokens import load_system, system_from_dict

AGENCY = Path(__file__).resolve().parent.parent / "examples" / "templates" / "agency"

# template file -> (trim width, trim height) in px at its press dpi
SIZES = {
    "business-card.svg": (mm_to_px(90, 300), mm_to_px(50, 300)),
    "business-card-back.svg": (mm_to_px(90, 300), mm_to_px(50, 300)),
    "flyer-a5.svg": (mm_to_px(148, 300), mm_to_px(210, 300)),
    "z-fold-a4.svg": (mm_to_px(297, 300), mm_to_px(210, 300)),
    "pullup-banner.svg": (10039, 23622),  # pullup-banner preset px
    "signboard-2000x800.svg": (mm_to_px(2000, 150), mm_to_px(800, 150)),
    "signboard-2000x800-back.svg": (mm_to_px(2000, 150), mm_to_px(800, 150)),
    "corporate-folder-a4.svg": (mm_to_px(445, 300), mm_to_px(385, 300)),
    "pen-barrel.svg": (mm_to_px(70, 300), mm_to_px(15, 300)),
}

FIELDS = {
    "business-name": "Demo Trading (Pty) Ltd",
    "tagline": "Import. Export. Delivered.",
    "phone": "+27 11 555 0123",
    "email": "hello@demotrading.co.za",
    "address": "12 Harbour Rd, Durban",
}


def _system():
    return system_from_dict(derive_system(
        ["#0F4C81", "#F5A623"],
        overrides={"typography": {"scale": AGENCY_TYPE_SCALE}},
    ))


def _data(system):
    return TemplateData(fields=dict(FIELDS), palette=palette_for_system(system))


def test_pen_barrel_format_preset():
    spec = get_format("pen-barrel-70x15")
    assert spec.category == "print" and spec.dpi == 300
    assert spec.width == pytest.approx(70 * 300 / 25.4, abs=0.5)
    assert spec.height == pytest.approx(15 * 300 / 25.4, abs=0.5)
    assert spec.bleed == pytest.approx(2 * 300 / 25.4, abs=0.5)


def test_palette_for_system_follows_role_order():
    system = _system()
    palette = palette_for_system(system)
    assert len(palette) == len(AGENCY_PALETTE_ROLES)
    by_name = {t.name: t.hex for t in system.colors}
    assert palette[0] == by_name["primary"]
    assert palette[1] == by_name["accent"]
    assert palette[2] == by_name["ink"]
    assert palette[3] == by_name["surface"]
    assert palette[4] == by_name["on-primary"]
    assert palette[5] == by_name["paper"]


def test_palette_for_system_fallbacks():
    minimal = system_from_dict({
        "name": "Tiny",
        "color": {"tokens": {
            "brand": {"hex": "#0f4c81", "role": "primary"},
            "text": {"hex": "#111827", "role": "text"},
            "bg": {"hex": "#ffffff", "role": "surface"},
        }},
    })
    palette = palette_for_system(minimal)
    assert palette[0] == "#0f4c81"          # role: primary
    assert palette[1] == "#0f4c81"          # accent falls back to primary
    assert palette[2] == "#111827"          # ink falls back to text
    assert palette[4] == "#ffffff"          # on-primary falls back to surface


@pytest.mark.parametrize("name", sorted(SIZES))
def test_template_trim_geometry_and_slots(name):
    doc = parse_svg(AGENCY / name)
    w, h = SIZES[name]
    assert doc.width == pytest.approx(w, abs=0.5), name
    assert doc.height == pytest.approx(h, abs=0.5), name
    slots = {s.attrs.get("data-slot") for s in doc.shapes} - {None}
    assert "business-name" in slots
    # Fitted slots declare sizes from the agency ladder.
    for shape in doc.shapes:
        if shape.attrs.get("data-fit") == "shrink":
            assert shape.numeric("font-size") in AGENCY_TYPE_SCALE, name
    # Backgrounds bleed past the trim on the pack's print templates.
    assert any((s.numeric("x") or 0) < 0 for s in doc.shapes if s.tag == "rect"), name


@pytest.mark.parametrize("name", sorted(SIZES))
def test_template_renders_with_derived_palette(name):
    system = _system()
    doc = render_template(parse_svg(AGENCY / name), _data(system), system)
    fills = {s.get("fill") for s in doc.shapes}
    palette = palette_for_system(system)
    assert palette[0] in fills                      # primary applied
    texts = {s.text for s in doc.shapes if s.tag == "text"}
    assert FIELDS["business-name"] in texts
    # Marker attributes never leak into output.
    assert not any(k.startswith("data-") for s in doc.shapes for k in s.attrs)
    # No fitted slot overflowed its box at these content lengths.
    assert not any(s.get("data-overflow") for s in doc.shapes)


def test_zfold_content_respects_panel_geometry():
    spec = get_format("z-fold-a4")
    system = _system()
    doc = render_template(parse_svg(AGENCY / "z-fold-a4.svg"), _data(system), system)
    fold1, fold2 = spec.panels[0], spec.panels[0] + spec.panels[1]
    for shape in doc.shapes:
        if shape.tag != "text":
            continue
        x = shape.numeric("x") or 0
        # Contact block lives on the fold-in panel, cover text on panel 1,
        # message on panel 2 — no text baseline starts within 80px of a fold.
        assert abs(x - fold1) > 80 and abs(x - fold2) > 80


def test_folder_covers_clear_spine_and_pocket():
    spec = get_format("corporate-folder-a4")
    doc = parse_svg(AGENCY / "corporate-folder-a4.svg")
    spine_x0, spine_x1 = spec.panels[0], spec.panels[0] + spec.panels[1]
    pocket_y = spec.panels_y[0]
    for shape in doc.shapes:
        if shape.tag != "text":
            continue
        x, y = shape.numeric("x") or 0, shape.numeric("y") or 0
        assert not (spine_x0 <= x <= spine_x1)  # nothing typeset on the spine
        assert y < pocket_y                     # nothing typeset on the pocket


def test_card_front_and_back_make_press_pdf(tmp_path):
    import re
    import zlib

    from designer.render import render_pdf
    from designer.tokens import DesignSystem

    system = _system()
    data = _data(system)
    front = render_template(parse_svg(AGENCY / "business-card.svg"), data, system)
    back = render_template(parse_svg(AGENCY / "business-card-back.svg"), data, system)
    from designer.formats import format_from_dict

    spec = format_from_dict("business-card-90x50", {
        "unit": "mm", "dpi": 300, "width": 90, "height": 50,
        "bleed": 3, "category": "print",
    })
    out = render_pdf([front, back], tmp_path / "card.pdf", cmyk=True,
                     format=spec, bleed=spec.bleed, marks=True)
    pdf = out.read_bytes()
    assert pdf.count(b"/Type /Page ") == 2
    assert b"/TrimBox" in pdf
    streams = b""
    for m in re.finditer(rb"/Length (\d+)[^>]*>>\s*stream\r?\n", pdf):
        chunk = pdf[m.end():m.end() + int(m.group(1))]
        try:
            streams += zlib.decompress(chunk)
        except zlib.error:
            streams += chunk
    assert b"Demo Trading" in streams
    assert b"1 1 1 1 K" in streams  # registration-color marks


def test_templates_render_under_default_system_too():
    # The pack must not require the agency scale to function — the
    # default system just fits text to its own (smaller) ladder.
    system = load_system()
    doc = render_template(
        parse_svg(AGENCY / "business-card.svg"),
        TemplateData(fields=dict(FIELDS),
                     palette=["#1a56db", "#f59e0b", "#111827",
                              "#f3f4f6", "#ffffff", "#ffffff"]),
        system,
    )
    name = next(s for s in doc.shapes if s.text == FIELDS["business-name"])
    assert name.numeric("font-size") in system.type_scale
