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

"""Engine bridge: engine-level failures surface as EngineError with the
engine's user-facing message — never as raw PIL tracebacks."""

from __future__ import annotations

import pytest

from studio_src import engine_bridge

SYSTEM = {
    "name": "T",
    "color": {"tokens": {"primary": "#1a56db", "accent": "#f59e0b",
                         "white": "#ffffff"}},
}


def test_unreadable_image_becomes_engine_error(tmp_path):
    p = tmp_path / "empty.png"
    p.write_bytes(b"")
    with pytest.raises(engine_bridge.EngineError, match="empty.png"):
        engine_bridge.comply_file(str(p), SYSTEM)


def test_truncated_image_becomes_engine_error(tmp_path):
    pytest.importorskip("PIL")
    import numpy as np
    from PIL import Image

    whole_path = tmp_path / "whole.png"
    arr = np.full((64, 64, 3), (243, 244, 246), np.uint8)
    arr[16:48, 16:48] = (26, 86, 219)
    Image.fromarray(arr).save(whole_path)
    p = tmp_path / "truncated.png"
    p.write_bytes(whole_path.read_bytes()[: whole_path.stat().st_size // 2])
    with pytest.raises(engine_bridge.EngineError, match="truncated.png"):
        engine_bridge.audit_file(str(p), SYSTEM)
