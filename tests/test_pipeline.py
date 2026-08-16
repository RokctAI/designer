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

"""End-to-end: synthetic 'AI-generated' raster -> compliant SVG."""

import subprocess
import sys

import numpy as np
import pytest
from PIL import Image, ImageDraw

from designer.color import parse_color
from designer.engine import ComplianceEngine
from designer.svg import parse_svg
from designer.tokens import load_system
from designer.vectorize import VectorizeOptions


@pytest.fixture()
def fake_ai_poster(tmp_path):
    """A noisy, off-brand raster like an image generator would emit."""
    rng = np.random.default_rng(42)
    img = Image.new("RGB", (256, 256), (243, 243, 247))  # off-brand near-white
    draw = ImageDraw.Draw(img)
    draw.ellipse((60, 60, 196, 196), fill=(35, 90, 210))   # off-brand blue
    draw.rectangle((100, 220, 220, 240), fill=(250, 165, 30))  # off-brand orange
    arr = np.asarray(img, dtype=np.int16)
    noise = rng.integers(-6, 7, arr.shape)  # generator grain
    arr = np.clip(arr + noise, 0, 255).astype(np.uint8)
    path = tmp_path / "poster.png"
    Image.fromarray(arr).save(path)
    return path


def test_raster_to_compliant_svg(fake_ai_poster, tmp_path):
    system = load_system()
    engine = ComplianceEngine(system)
    doc = engine.load(fake_ai_poster, VectorizeOptions(n_colors=4))
    report = engine.comply(doc)

    token_hexes = {t.hex for t in system.colors}
    painted = [s.get("fill") for s in doc.shapes if s.get("fill")]
    assert painted, "expected painted shapes"
    for fill in painted:
        assert fill in token_hexes

    # The circle and banner survived vectorization as paths.
    assert sum(1 for s in doc.shapes if s.tag == "path") >= 2
    assert report.score > 50

    from designer.svg import save

    out = tmp_path / "poster.svg"
    save(doc, out)
    reparsed = parse_svg(out)
    assert len(reparsed.shapes) == len(doc.shapes)
    assert parse_svg(out).background_color() is not None


def test_cli_comply_and_audit(fake_ai_poster, tmp_path):
    out = tmp_path / "out.svg"
    result = subprocess.run(
        [sys.executable, "-m", "designer", "comply", str(fake_ai_poster),
         "-o", str(out), "--colors", "4"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert out.exists()
    assert "Score after fixes" in result.stdout

    audit = subprocess.run(
        [sys.executable, "-m", "designer", "audit", str(out), "--json"],
        capture_output=True,
        text=True,
    )
    assert audit.returncode == 0, audit.stderr
    assert '"score": 100' in audit.stdout


def test_cli_min_score_gate(fake_ai_poster):
    result = subprocess.run(
        [sys.executable, "-m", "designer", "audit", str(fake_ai_poster),
         "--min-score", "100", "--colors", "4"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 1  # raw AI output must not pass a CI gate
