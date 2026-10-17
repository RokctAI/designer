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

"""Merchant poster templates: code places the merchant's own content,
required slots are per template, and the accent/font limits are opt-in."""

import pytest

from designer.engine import ComplianceEngine
from designer.posters import FORMAT, list_posters, load_poster
from designer.svg import Document, Shape
from designer.template import (
    Item,
    TemplateData,
    TemplateError,
    palette_for_system,
    render,
)
from designer.tokens import system_from_dict

SYSTEM = {
    "name": "Merchant",
    "color": {"tokens": {
        "primary": {"hex": "#c2410c", "role": "primary"},
        "accent": {"hex": "#eab308", "role": "accent"},
        "ink": {"hex": "#1c1917", "role": "ink"},
        "surface": {"hex": "#fafaf9", "role": "surface"},
    }},
}
PIXEL = ("data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAIAAACQd1Pe"
         "AAAADElEQVR4nGP4z8AAAAMBAQDJ/pLvAAAAAElFTkSuQmCC")


def _system(**layout):
    return system_from_dict({**SYSTEM, "layout": layout})


def _render(name, data, system=None):
    system = system or _system()
    template, cell = load_poster(name)
    data.palette = palette_for_system(system)
    return render(template, data, system, cell_template=cell)


def test_catalog_lists_required_slots_per_template():
    posters = {p["name"]: p for p in list_posters()}
    assert set(posters) == {"promo", "event", "menu"}
    required = {n: {s["slot"] for s in p["slots"] if s["required"]} for n, p in posters.items()}
    assert required["event"] == {"headline", "when", "where", "business"}
    assert required["promo"] == {"headline", "photo", "price", "business"}
    # Not every poster has a time and place: only the event one asks.
    assert "where" not in {s["slot"] for s in posters["promo"]["slots"]}
    assert posters["menu"]["items"] == {"required": True, "fields": ["photo", "title", "price"]}
    assert all(p["format"] == FORMAT for p in posters.values())


def test_missing_required_slot_is_refused_with_its_label():
    with pytest.raises(TemplateError, match="Venue or pickup point is required"):
        _render("event", TemplateData(fields={"headline": "Market", "when": "Sat 10:00",
                                              "business": "Juvo"}))


def test_menu_needs_at_least_one_item():
    with pytest.raises(TemplateError, match="Menu items is required"):
        _render("menu", TemplateData(fields={"headline": "Menu", "business": "Juvo"}))


def test_merchant_text_and_prices_are_placed_verbatim():
    doc = _render("menu", TemplateData(
        fields={"headline": "Today's menu", "business": "Juvo Kitchen"},
        items=[Item(title="Kota", price="R35", image_href=PIXEL),
               Item(title="Chips", price="R20")]))
    texts = [s.text for s in doc.shapes if s.tag == "text"]
    for value in ("Today's menu", "Juvo Kitchen", "Kota", "R35", "Chips", "R20"):
        assert value in texts
    # Optional slots left empty leave nothing behind.
    assert "Details" not in texts
    assert not any(k.startswith("data-") for s in doc.shapes for k in s.attrs)


def test_poster_complies_cleanly():
    system = _system(max_accents=1, max_font_families=2)
    doc = _render("promo", TemplateData(
        fields={"headline": "Braai Pack", "price": "R199", "business": "Juvo"},
        images={"photo": PIXEL}), system)
    report = ComplianceEngine(system, format=FORMAT).comply(doc)
    assert not [f for f in report.findings if f.rule in ("color.accents", "type.families")]


def _busy_doc():
    shapes = [Shape("rect", {"x": "0", "y": "0", "width": "100", "height": "100", "fill": c})
              for c in ("#c2410c", "#eab308")]
    shapes += [Shape("text", {"x": "0", "y": "20", "font-size": "16", "font-family": f}, text="Hi")
               for f in ("Inter", "Georgia", "Courier")]
    return Document(width=400, height=400, shapes=shapes)


def test_accent_and_family_limits_are_off_by_default():
    report = ComplianceEngine(_system()).audit(_busy_doc())
    assert not [f for f in report.findings if f.rule in ("color.accents", "type.families")]


def test_accent_and_family_limits_fix_when_enabled():
    system = system_from_dict({**SYSTEM, "typography": {"fonts": ["Inter", "Georgia", "Courier"]},
                               "layout": {"max_accents": 1, "max_font_families": 2}})
    doc = _busy_doc()
    report = ComplianceEngine(system).comply(doc)
    rules = {f.rule for f in report.findings if f.fixed}
    assert {"color.accents", "type.families"} <= rules
    fills = {s.get("fill").lower() for s in doc.shapes if s.tag == "rect"}
    assert len(fills & {"#c2410c", "#eab308"}) == 1
    assert len({s.get("font-family") for s in doc.shapes if s.tag == "text"}) == 2
