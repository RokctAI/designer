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

"""Company-profile template pack: both pages parse at a4-poster
geometry, restyle from palette roles, render, and audit clean against a
real system YAML (supacharge) and a derived one."""

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
PACK = ROOT / "examples" / "templates" / "company-profile"
SUPACHARGE = ROOT / "designer" / "systems" / "supacharge.yaml"

PAGES = ["profile-cover.svg", "profile-content.svg"]

FIELDS = {
    "business-name": "Demo Trading (Pty) Ltd",
    "tagline": "Import. Export. Delivered.",
    "kicker": "COMPANY PROFILE",
    "date": "August 2026",
    "reg-number": "Reg no. 2014/123456/07",
    "vat-number": "VAT no. 4890123456",
    "heading": "Who we are and what we deliver",
    "point-1": "Established importer-exporter serving three provinces",
    "point-2": "Level 1 B-BBEE contributor, 61% black ownership",
    "point-3": "ISO 9001-certified warehousing and fleet operations",
    "point-4": "Accredited supplier on state and municipal frameworks",
    "leadership-title": "Leadership",
    "lead-1": "N. Dlamini - Managing Director, 18 years in logistics",
    "lead-2": "S. van Wyk - Operations Director, CILT-certified",
    "lead-3": "T. Mokoena - Finance Director, CA(SA)",
    "track-title": "Track record",
    "email": "tenders@demotrading.co.za",
    "phone": "+27 11 555 0123",
}

ITEMS = [
    Item(title="Years trading", price="12", badge="since 2014"),
    Item(title="Contracts delivered", price="240+", badge="on time"),
    Item(title="Largest award", price="R48m", badge="3-year term"),
]


def _derived_system():
    return system_from_dict(derive_system(["#0F4C81", "#F5A623"]))


def _render(name, system, items=()):
    data = TemplateData(fields=dict(FIELDS), items=list(items),
                        palette=palette_for_system(system))
    cell = parse_svg(PACK / "record-cell.svg") if items else None
    return render_template(parse_svg(PACK / name), data, system,
                           cell_template=cell)


def _items_for(name):
    return ITEMS if name == "profile-content.svg" else ()


@pytest.mark.parametrize("name", PAGES)
def test_page_geometry_and_slots(name):
    spec = get_format("a4-poster")
    doc = parse_svg(PACK / name)
    assert doc.width == spec.width and doc.height == spec.height, name
    slots = {s.attrs.get("data-slot") for s in doc.shapes} - {None}
    assert "heading" in slots or "business-name" in slots
    # Fitted slots declare sizes from the default engine scale, so
    # fitting steps through any system's ladder without an override.
    default_scale = load_system().type_scale
    for shape in doc.shapes:
        if shape.attrs.get("data-fit") == "shrink":
            assert shape.numeric("font-size") in default_scale, name
    # Print format: backgrounds extend past the trim into the bleed.
    assert any((s.numeric("x") or 0) < 0 for s in doc.shapes
               if s.tag == "rect"), name


def test_cover_carries_the_registration_block():
    slots = {s.attrs.get("data-slot")
             for s in parse_svg(PACK / "profile-cover.svg").shapes} - {None}
    assert {"logo", "business-name", "tagline", "reg-number",
            "vat-number", "date"} <= slots


def test_content_page_carries_profile_sections():
    doc = parse_svg(PACK / "profile-content.svg")
    slots = {s.attrs.get("data-slot") for s in doc.shapes} - {None}
    assert {"heading", "leadership-title", "lead-1", "lead-2", "lead-3",
            "track-title", "email", "phone"} <= slots
    assert any(s.attrs.get("data-region") == "items" for s in doc.shapes)


@pytest.mark.parametrize("name", PAGES)
def test_page_renders_with_supacharge(name):
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
@pytest.mark.parametrize("name", PAGES)
def test_page_audits_clean(name, system_source):
    system = (load_system(SUPACHARGE) if system_source == "supacharge"
              else _derived_system())
    doc = _render(name, system, items=_items_for(name))
    report = ComplianceEngine(system, format="a4-poster").audit(doc)
    errors = [f for f in report.findings if f.severity.value == "error"]
    assert not errors, [f.message for f in errors]
    assert report.score >= 90, report.to_text()


def test_track_record_cells_take_the_palette():
    system = load_system(SUPACHARGE)
    doc = _render("profile-content.svg", system, items=ITEMS)
    palette = palette_for_system(system)
    # Three cells: each carries a paper card face and an accent strip
    # recolored from the caller's palette, not the baked-in fallbacks.
    assert sum(1 for s in doc.shapes if s.get("fill") == palette[5]) >= 3
    values = {s.text for s in doc.shapes if s.tag == "text"}
    assert "240+" in values and "Contracts delivered" in values


def test_track_record_three_cells_stay_on_grid():
    # The common three-proof-point row flows at the cell's native
    # geometry: every flowed rect lands on the system grid, so the
    # audit carries no grid-snap findings.
    system = load_system(SUPACHARGE)
    doc = _render("profile-content.svg", system, items=ITEMS)
    for shape in doc.shapes:
        if shape.tag != "rect":
            continue
        for attr in ("x", "y", "width", "height"):
            value = shape.numeric(attr)
            assert value is not None and value % 8 == 0, (attr, value)


def test_track_record_rejects_too_many_items():
    system = load_system(SUPACHARGE)
    many = ITEMS * 4
    with pytest.raises(UnitTooSmall):
        _render("profile-content.svg", system, items=many)


def test_cover_renders_png():
    from designer.render import render_png

    system = load_system(SUPACHARGE)
    doc = _render("profile-cover.svg", system)
    image = render_png(doc, None, width=794)
    assert image.size == (794, 1123)
