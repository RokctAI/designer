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

"""Merchant poster templates: layout by code, not by the image model.

Each poster is a slot template (see :mod:`designer.template`) designed
on the A4 poster canvas with one accent color, one type family and a
fixed 8px grid. The merchant's own text, prices and photos fill the
slots; an image model may only fill the ``background`` image slot.
A template marks the slots it cannot go out without as required (the
event poster needs a when and a where, the promo needs a price), so
other posters are never forced to carry details they do not have.
"""

from __future__ import annotations

import importlib.resources

from designer.svg import Document, parse_svg
from designer.template import TemplateError, describe_slots

FORMAT = "a4-poster"

# name -> (label, description, cell template or None)
POSTERS: dict[str, tuple[str, str, str | None]] = {
    "promo": ("Product promo", "One product photo, a headline and its price.", None),
    "event": ("Event or collection day", "Date, time and venue or pickup point.", None),
    "menu": ("Menu or price list", "Several items, each with a photo and a price.", "menu-cell"),
}


def _load(name: str) -> Document:
    ref = importlib.resources.files("designer").joinpath(f"templates/posters/{name}.svg")
    with importlib.resources.as_file(ref) as path:
        return parse_svg(path)


def load_poster(name: str) -> tuple[Document, Document | None]:
    """(template, cell template or None). Unknown names raise
    TemplateError with a message the UI can show."""
    if name not in POSTERS:
        raise TemplateError(f"Unknown poster template {name!r}")
    cell = POSTERS[name][2]
    return _load(name), (_load(cell) if cell else None)


def list_posters() -> list[dict]:
    """Catalog for the frontend: name, label, description, format and
    the slots a form must offer (with which ones are required)."""
    out = []
    for name, (label, description, _cell) in POSTERS.items():
        template, cell = load_poster(name)
        slots = describe_slots(template)
        out.append({
            "name": name,
            "label": label,
            "description": description,
            "format": FORMAT,
            "slots": [s for s in slots if s["kind"] != "items"],
            "items": next(
                ({"required": s["required"],
                  "fields": [c["slot"] for c in describe_slots(cell)]}
                 for s in slots if s["kind"] == "items" and cell is not None),
                None,
            ),
        })
    return out
