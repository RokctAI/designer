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

"""Campaign fan-out: aspect_waste and derive-vs-regenerate planning."""

import pytest

from studio_src.lib import campaign as lib


def test_same_aspect_is_zero_waste():
    assert lib.aspect_waste(1024, 1024, 1080, 1080) == pytest.approx(0.0)
    assert lib.aspect_waste(800, 450, 1600, 900) == pytest.approx(0.0)


def test_square_master_onto_banner_wastes_most_of_the_canvas():
    # 1024x1024 master onto a 1584x396 LinkedIn banner: scaled master is
    # 396x396, so 75% of the canvas is empty.
    assert lib.aspect_waste(1024, 1024, 1584, 396) == pytest.approx(0.75)


def test_square_master_onto_story():
    # 1024 square onto 1080x1920 story: fills 1080/1920 of the height.
    assert lib.aspect_waste(1024, 1024, 1080, 1920) == pytest.approx(1 - 1080 / 1920)


def test_fanout_action_threshold():
    assert lib.fanout_action(1024, 1024, 1080, 1080) == "derive"
    assert lib.fanout_action(1024, 1024, 1584, 396) == "regenerate"
    # Exactly at threshold derives (spec: waste <= threshold).
    assert lib.fanout_action(1024, 1024, 1024, 1024 / 0.65,
                             threshold=0.35) == "derive"


def test_plan_fanout():
    plan = lib.plan_fanout((1024, 1024), [
        {"format": "instagram-post", "width": 1080, "height": 1080},
        {"format": "instagram-story", "width": 1080, "height": 1920},
        {"format": "linkedin-banner", "width": 1584, "height": 396},
    ])
    actions = {p["format"]: p["action"] for p in plan}
    assert actions["instagram-post"] == "derive"
    assert actions["instagram-story"] == "regenerate"
    assert actions["linkedin-banner"] == "regenerate"
    assert [p["format"] for p in plan] == [
        "instagram-post", "instagram-story", "linkedin-banner"]


def test_bad_dimensions_raise():
    with pytest.raises(ValueError):
        lib.aspect_waste(0, 100, 100, 100)
    with pytest.raises(ValueError):
        lib.aspect_waste(100, 100, 100, -1)


def test_matches_engine_format_catalog():
    formats = pytest.importorskip("designer.formats")
    ig = formats.get_format("instagram-post")
    assert lib.fanout_action(1024, 1024, ig.width, ig.height) == "derive"
    banner = formats.get_format("linkedin-banner")
    assert lib.fanout_action(1024, 1024, banner.width, banner.height) == "regenerate"
