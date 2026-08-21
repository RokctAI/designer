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

"""Branded A4 company profile — pure functions, no frappe.

Maps the StartupOS engine's compiled values onto the company-profile
template pack (``examples/templates/company-profile/``, both pages the
``a4-poster`` preset) and renders each page to SVG with
``designer.template.render``. Honest by construction: only real
answers land on the page — the engine's "Not yet provided" /
"Pending — ..." / "Not applicable" markers, and slots with no sensible
source, are simply left empty (the pack drops empty slots cleanly).
Nothing is invented, no copy is rephrased.
"""

from __future__ import annotations

import os
from typing import Mapping

# Template file -> the name the rendered page takes, relative to the
# instance's output/ folder (beside the engine's own artifacts; the
# engine never prunes in selective mode, so these survive there).
PAGES = (("profile-cover.svg", "branded/profile-cover.svg"),
         ("profile-content.svg", "branded/profile-content.svg"))
CELL_TEMPLATE = "record-cell.svg"

# The engine's own placeholder texts for unanswered questions and
# unverified/inapplicable compliance fields. Honest in a markdown
# document, wrong on a branded page — a value starting with one of
# these never fills a slot.
_ENGINE_MARKERS = ("Not yet provided", "Pending", "Not applicable")

# Slot -> the engine value keys that may fill it, first usable answer
# wins. Multi-line answers contribute their first line (SVG text slots
# do not wrap). Slots with no honest source (email, phone, track
# record metrics) are simply absent.
_SLOT_SOURCES = {
    "business-name": ("trading_name", "company_name"),
    "tagline": ("core_value_proposition",),
    "heading": ("vision_statement", "core_value_proposition"),
    "point-1": ("primary_products",),
    "point-2": ("customer_segments",),
    "point-3": ("target_sectors",),
    "point-4": ("head_office",),
}


class ProfileRenderError(ValueError):
    """A profile render failure with a user-facing message."""


def usable_value(values: Mapping[str, str], key: str) -> str:
    """The first line of a real answer, or "" for absent values and the
    engine's placeholder markers."""
    value = str(values.get(key) or "").strip()
    if not value or value.startswith(_ENGINE_MARKERS):
        return ""
    return value.splitlines()[0].strip()


def profile_fields(values: Mapping[str, str],
                   generated_on: str | None = None) -> dict[str, str]:
    """Template slot -> text, from the engine's merged values.

    Only slots with a usable source appear. The kicker is the document
    name, the date is the compile date the caller passes; registration
    and tax numbers appear only when the compliance record verified
    them (unverified fields carry the engine's "Pending" marker, which
    ``usable_value`` drops).
    """
    fields = {"kicker": "COMPANY PROFILE"}
    for slot, keys in _SLOT_SOURCES.items():
        for key in keys:
            text = usable_value(values, key)
            if text:
                fields[slot] = text
                break

    reg = usable_value(values, "reg_number")
    if reg:
        fields["reg-number"] = f"Reg no. {reg}"
    tax = usable_value(values, "tax_number")
    if tax:
        fields["vat-number"] = f"Tax no. {tax}"
    if generated_on and generated_on.strip():
        fields["date"] = generated_on.strip()

    leads = [line.strip() for line
             in str(values.get("executive_team") or "").splitlines()
             if line.strip() and not line.strip().startswith(_ENGINE_MARKERS)]
    for index, line in enumerate(leads[:3], start=1):
        fields[f"lead-{index}"] = line
    if leads:
        fields["leadership-title"] = "Leadership"
    return fields


def resolve_pack_dir(explicit: str | None = None) -> str:
    """The company-profile pack folder. ``explicit`` wins; otherwise
    the pack is looked up beside the ``designer`` package (a repo
    checkout). Like the StartupOS templates, the pack does not ship in
    the designer-compliance pip wheel — a bench without a checkout must
    pass the path explicitly."""
    if explicit:
        if not os.path.isdir(explicit):
            raise ProfileRenderError(
                f"profile pack dir {explicit} does not exist")
        return explicit
    import designer

    candidate = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(designer.__file__))),
        "examples", "templates", "company-profile")
    if os.path.isdir(candidate):
        return candidate
    raise ProfileRenderError(
        "The company-profile template pack is not on this bench. It does "
        "not ship in the designer-compliance pip wheel — sync "
        "examples/templates/company-profile/ from RokctAI/designer and "
        "pass its path."
    )


def render_profile_pages(values: Mapping[str, str],
                         system_dict: dict | None = None,
                         pack_dir: str | None = None,
                         generated_on: str | None = None) -> dict[str, str]:
    """Render both branded A4 pages. Returns {relative name -> SVG
    text} in :data:`PAGES` order. ``system_dict`` is a Design System's
    engine dict (the brand palette); ``None`` renders with the
    engine's default system."""
    from designer.svg import parse_svg, serialize
    from designer.template import (TemplateData, palette_for_system,
                                   render as render_template)
    from designer.tokens import load_system, system_from_dict

    pack = resolve_pack_dir(pack_dir)
    system = (system_from_dict(system_dict) if system_dict
              else load_system())
    data = TemplateData(fields=profile_fields(values, generated_on),
                        palette=palette_for_system(system))
    cell = parse_svg(os.path.join(pack, CELL_TEMPLATE))

    pages: dict[str, str] = {}
    for template_name, output_name in PAGES:
        template_path = os.path.join(pack, template_name)
        if not os.path.isfile(template_path):
            raise ProfileRenderError(
                f"profile pack is missing {template_name} ({template_path})")
        doc = render_template(parse_svg(template_path), data, system,
                              cell_template=cell)
        pages[output_name] = serialize(doc)
    return pages
