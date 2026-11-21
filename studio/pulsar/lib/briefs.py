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

"""StartupOS brief -> Design Campaign mapping — pure functions.

A StartupOS ``briefs`` export writes expo-schema JSONs (id, asset_type,
dimensions_or_aspect, copy{headline, subcopy, cta, ...},
visual_direction, brand_system). This module turns a batch of those
payloads into a campaign plan: one engine format per known asset_type,
plus an honest skip note for every payload it cannot place. The copy is
the executive's verbatim words — it is summarised into the campaign
brief, never rephrased.
"""

from __future__ import annotations

from typing import Mapping, Sequence

# StartupOS asset_type -> designer.formats name. a4-poster is the
# engine's own "A4 portrait poster/flyer" canvas — the closest print
# format to the A5 flyer brief until an a5-flyer format exists. The
# company_profile returnable targets the same A4 portrait preset; its
# visual layout comes from examples/templates/company-profile/.
ASSET_TYPE_FORMATS = {
    "poster": "a1-poster",
    "pullup_banner": "pullup-banner",
    "flyer": "a4-poster",
    "company_profile": "a4-poster",
}


def map_brief(brief: Mapping) -> dict | None:
    """One payload -> {"format", "brief_id", "asset_type", "headline"},
    or None when the asset_type has no engine format."""
    asset_type = str(brief.get("asset_type") or "").strip()
    fmt = ASSET_TYPE_FORMATS.get(asset_type)
    if not fmt:
        return None
    copy = brief.get("copy") or {}
    return {
        "format": fmt,
        "brief_id": brief.get("id"),
        "asset_type": asset_type,
        "headline": (copy.get("headline") or "").strip(),
    }


def plan_campaign(briefs: Sequence[Mapping]) -> dict:
    """A batch of payloads -> {"formats", "brief_text", "skipped"}.

    ``formats`` feed Design Campaign Format rows (input order, one per
    brief); ``skipped`` names every payload left out and why;
    ``brief_text`` summarises the verbatim headlines per format for the
    campaign's brief field.
    """
    formats: list[dict] = []
    skipped: list[str] = []
    lines: list[str] = []
    for index, brief in enumerate(briefs):
        mapped = map_brief(brief)
        if mapped is None:
            ident = brief.get("id") or f"brief #{index + 1}"
            asset_type = brief.get("asset_type") or "(missing)"
            known = ", ".join(sorted(ASSET_TYPE_FORMATS))
            skipped.append(f"{ident}: no engine format for asset_type "
                           f"{asset_type!r} (known: {known})")
            continue
        formats.append(mapped)
        label = mapped["brief_id"] or mapped["asset_type"]
        line = f"{label} -> {mapped['format']}"
        if mapped["headline"]:
            line += f": {mapped['headline']}"
        lines.append(line)
    return {"formats": formats, "brief_text": "\n".join(lines),
            "skipped": skipped}
