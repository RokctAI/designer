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

"""The branded A4 company profile mapping and render (lib.profile):
slot text comes only from real compiled answers — the engine's honest
markers never land on a branded page — and both a4-poster pages render
with the real designer machinery and the in-repo template pack."""

from __future__ import annotations

import pytest

from _fake_startupos import VALUES
from studio_src.lib import profile as lib


# ------------------------------------------------------------ mapping

def test_profile_fields_maps_only_real_answers():
    fields = lib.profile_fields(VALUES, generated_on="2026-08-21")
    assert fields["kicker"] == "COMPANY PROFILE"
    assert fields["business-name"] == "Acme"
    assert fields["tagline"] == "Compliance-grade documents on demand"
    assert fields["heading"] == "Every venture bankable in a week"
    assert fields["reg-number"] == "Reg no. 2014/123456/07"
    assert fields["date"] == "2026-08-21"
    # target_sectors is "Not yet provided" -> point-3 vanishes; the
    # pending tax number never lands on a branded page.
    assert "point-3" not in fields
    assert "vat-number" not in fields


def test_profile_fields_leadership_from_executive_team_lines():
    fields = lib.profile_fields(VALUES)
    assert fields["leadership-title"] == "Leadership"
    assert fields["lead-1"] == "N. Dlamini - Managing Director"
    assert fields["lead-2"] == "S. van Wyk - CTO"
    assert "lead-3" not in fields
    assert "date" not in fields


def test_profile_fields_empty_values_yield_only_the_kicker():
    assert lib.profile_fields({}) == {"kicker": "COMPANY PROFILE"}


def test_usable_value_drops_engine_markers_and_takes_first_line():
    assert lib.usable_value({"k": "Not yet provided"}, "k") == ""
    assert lib.usable_value({"k": "Pending — add Tax_Pin.pdf"}, "k") == ""
    assert lib.usable_value({"k": "Not applicable"}, "k") == ""
    assert lib.usable_value({"k": "line one\nline two"}, "k") == "line one"
    assert lib.usable_value({}, "k") == ""


# ------------------------------------------------------------- render

def test_render_profile_pages_produces_both_a4_pages():
    pages = lib.render_profile_pages(VALUES, generated_on="2026-08-21")
    assert list(pages) == ["branded/profile-cover.svg",
                           "branded/profile-content.svg"]
    cover = pages["branded/profile-cover.svg"]
    assert cover.startswith("<svg") and 'width="794"' in cover
    assert "Acme" in cover
    assert "Reg no. 2014/123456/07" in cover
    # Authoring markers never leak into output.
    assert "data-slot" not in cover
    content = pages["branded/profile-content.svg"]
    assert "N. Dlamini - Managing Director" in content
    # The pending marker never lands on a branded page.
    assert "Pending" not in cover and "Pending" not in content
    assert "Not yet provided" not in content


def test_render_profile_pages_takes_a_design_system_palette():
    from designer.palette import derive_system

    system_dict = derive_system(["#0F4C81", "#F5A623"])
    pages = lib.render_profile_pages(VALUES, system_dict=system_dict)
    primary = system_dict["color"]["tokens"]["primary"]["hex"]
    assert primary.lower() in pages["branded/profile-cover.svg"].lower()


def test_missing_pack_dir_names_the_fix(tmp_path):
    with pytest.raises(lib.ProfileRenderError, match="does not exist"):
        lib.render_profile_pages(VALUES, pack_dir=str(tmp_path / "nope"))


def test_default_pack_dir_resolves_to_the_repo_checkout():
    pack = lib.resolve_pack_dir()
    assert pack.endswith("company-profile")
