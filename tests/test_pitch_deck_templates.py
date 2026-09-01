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

"""Pitch-deck template pack: every slide parses at slide-16x9 geometry,
restyles from palette roles, renders, and audits clean against a real
system YAML (supacharge) and a derived one."""

from pathlib import Path

import pytest

from designer.engine import ComplianceEngine
from designer.formats import get_format
from designer.palette import derive_system
from designer.svg import parse_svg
from designer.template import (
    Item,
    TemplateData,
    UnitTooSmall,
    palette_for_system,
    render as render_template,
)
from designer.tokens import load_system, system_from_dict

ROOT = Path(__file__).resolve().parent.parent
DECK = ROOT / "examples" / "templates" / "pitch-deck"
SUPACHARGE = ROOT / "designer" / "systems" / "supacharge.yaml"

SLIDES = ["slide-title.svg", "slide-content.svg", "slide-data.svg",
          "slide-closing.svg"]

FIELDS = {
    "business-name": "Demo Ventures (Pty) Ltd",
    "tagline": "The pitch in one honest sentence",
    "date": "August 2026",
    "kicker": "TRACTION",
    "heading": "Growth is compounding month over month",
    "point-1": "12 000 active customers across three provinces",
    "point-2": "Net revenue retention of 128% over two quarters",
    "point-3": "CAC payback in under five months",
    "point-4": "Supply side now onboarding at 40 partners a week",
    "footnote": "Figures from internal analytics, July 2026.",
    "email": "founders@demoventures.example",
    "phone": "+27 11 555 0123",
}

ITEMS = [
    Item(title="Active customers", price="12k", badge="+38% QoQ"),
    Item(title="ARR", price="R14.2m", badge="+61% YoY"),
    Item(title="NRR", price="128%", badge="two quarters"),
    Item(title="CAC payback", price="4.7 mo", badge="improving"),
]


def _derived_system():
    return system_from_dict(derive_system(["#0F4C81", "#F5A623"]))


def _render(name, system, items=()):
    data = TemplateData(fields=dict(FIELDS), items=list(items),
                        palette=palette_for_system(system))
    cell = parse_svg(DECK / "stat-cell.svg") if items else None
    return render_template(parse_svg(DECK / name), data, system,
                           cell_template=cell)


def _items_for(name):
    return ITEMS if name == "slide-data.svg" else ()


@pytest.mark.parametrize("name", SLIDES)
def test_slide_geometry_and_slots(name):
    spec = get_format("slide-16x9")
    doc = parse_svg(DECK / name)
    assert doc.width == spec.width and doc.height == spec.height, name
    slots = {s.attrs.get("data-slot") for s in doc.shapes} - {None}
    assert "heading" in slots or "business-name" in slots
    # Fitted slots declare sizes from the default engine scale, so
    # fitting steps through any system's ladder without an override.
    default_scale = load_system().type_scale
    for shape in doc.shapes:
        if shape.attrs.get("data-fit") == "shrink":
            assert shape.numeric("font-size") in default_scale, name
    # Screen format: backgrounds cover the canvas exactly, no bleed.
    assert not any((s.numeric("x") or 0) < 0 for s in doc.shapes), name


@pytest.mark.parametrize("name", SLIDES)
def test_slide_renders_with_supacharge(name):
    system = load_system(SUPACHARGE)
    doc = _render(name, system, items=_items_for(name))
    palette = palette_for_system(system)
    fills = {s.get("fill") for s in doc.shapes}
    assert palette[1] in fills                      # accent applied
    texts = {s.text for s in doc.shapes if s.tag == "text"}
    assert FIELDS["heading"] in texts or FIELDS["business-name"] in texts
    # Marker attributes never leak into output.
    assert not any(k.startswith("data-") for s in doc.shapes for k in s.attrs)
    # No fitted slot overflowed its box at these content lengths.
    assert not any(s.get("data-overflow") for s in doc.shapes)


@pytest.mark.parametrize("system_source", ["supacharge", "derived"])
@pytest.mark.parametrize("name", SLIDES)
def test_slide_audits_clean(name, system_source):
    system = (load_system(SUPACHARGE) if system_source == "supacharge"
              else _derived_system())
    doc = _render(name, system, items=_items_for(name))
    report = ComplianceEngine(system, format="slide-16x9").audit(doc)
    errors = [f for f in report.findings if f.severity.value == "error"]
    assert not errors, [f.message for f in errors]
    assert report.score >= 90, report.to_text()


def test_data_slide_cells_take_the_palette():
    system = load_system(SUPACHARGE)
    doc = _render("slide-data.svg", system, items=ITEMS)
    palette = palette_for_system(system)
    # Four cells: each carries a paper card face and an accent strip
    # recolored from the caller's palette, not the baked-in fallbacks.
    assert sum(1 for s in doc.shapes if s.get("fill") == palette[5]) >= 4
    values = {s.text for s in doc.shapes if s.tag == "text"}
    assert "R14.2m" in values and "ARR" in values


def test_data_slide_four_stats_stay_on_grid():
    # The common four-metric slide flows at the cell's native geometry:
    # every flowed rect lands on the system grid, so the audit carries
    # no grid-snap findings.
    system = load_system(SUPACHARGE)
    doc = _render("slide-data.svg", system, items=ITEMS)
    for shape in doc.shapes:
        if shape.tag != "rect":
            continue
        for attr in ("x", "y", "width", "height"):
            value = shape.numeric(attr)
            assert value is not None and value % 8 == 0, (attr, value)


def test_data_slide_rejects_too_many_stats():
    system = load_system(SUPACHARGE)
    many = ITEMS * 4
    with pytest.raises(UnitTooSmall):
        _render("slide-data.svg", system, items=many)


def test_title_slide_renders_png():
    from designer.render import render_png

    system = load_system(SUPACHARGE)
    doc = _render("slide-title.svg", system)
    image = render_png(doc, None, width=960)
    assert image.size == (960, 540)
