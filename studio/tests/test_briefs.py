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

"""StartupOS expo-schema brief JSONs -> Design Campaign plan: every
known asset_type maps to a real engine format, unknown ones are skipped
with an honest note, and the executive's copy is quoted verbatim."""

import pytest

from studio_src.lib import briefs as lib


def _brief(code, asset_type, headline="One honest sentence"):
    """The expo-brief shape StartupOS branding.export_briefs writes."""
    return {
        "id": f"ACME-BRIEF-{code}",
        "asset_type": asset_type,
        "dimensions_or_aspect": "A1 portrait (594x841mm), 3mm bleed",
        "orientation": "portrait",
        "copy": {"headline": headline, "subcopy": "Support", "cta": None},
        "visual_direction": {"layout": "...", "imagery": {}, "notes": "..."},
        "brand_refs": ["color.tokens"],
        "brand_system": "../brand/system.yaml",
    }


def test_every_startupos_asset_type_maps_to_a_real_engine_format():
    designer = pytest.importorskip("designer")
    from designer import formats
    for asset_type, fmt in lib.ASSET_TYPE_FORMATS.items():
        spec = formats.get_format(fmt)  # raises ValueError if unknown
        assert spec.name == fmt, asset_type


def test_map_brief_known_types():
    assert lib.map_brief(_brief("PO01", "poster"))["format"] == "a1-poster"
    assert lib.map_brief(_brief("PB01", "pullup_banner"))["format"] == \
        "pullup-banner"
    assert lib.map_brief(_brief("FL01", "flyer"))["format"] == "a4-poster"
    assert lib.map_brief(_brief("CP01", "company_profile"))["format"] == \
        "a4-poster"


def test_map_brief_unknown_type_is_none():
    assert lib.map_brief(_brief("XX01", "hologram")) is None
    assert lib.map_brief({"copy": {}}) is None


def test_plan_campaign_orders_formats_and_quotes_copy_verbatim():
    plan = lib.plan_campaign([
        _brief("PO01", "poster", headline="Ship honest software"),
        _brief("PB01", "pullup_banner", headline="What ships"),
    ])
    assert [row["format"] for row in plan["formats"]] == \
        ["a1-poster", "pullup-banner"]
    assert plan["skipped"] == []
    assert plan["brief_text"].splitlines() == [
        "ACME-BRIEF-PO01 -> a1-poster: Ship honest software",
        "ACME-BRIEF-PB01 -> pullup-banner: What ships",
    ]


def test_plan_campaign_skips_unknown_types_with_a_note():
    plan = lib.plan_campaign([
        _brief("PO01", "poster"),
        _brief("HG01", "hologram"),
        {"asset_type": "", "copy": {}},
    ])
    assert [row["format"] for row in plan["formats"]] == ["a1-poster"]
    assert len(plan["skipped"]) == 2
    assert "ACME-BRIEF-HG01" in plan["skipped"][0]
    assert "'hologram'" in plan["skipped"][0]
    assert "company_profile, flyer, poster, pullup_banner" in \
        plan["skipped"][0]
    # A payload with no id is still named by its position.
    assert plan["skipped"][1].startswith("brief #3:")


def test_plan_campaign_all_unknown_yields_no_formats():
    plan = lib.plan_campaign([_brief("HG01", "hologram")])
    assert plan["formats"] == []
    assert len(plan["skipped"]) == 1
