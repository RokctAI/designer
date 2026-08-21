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
