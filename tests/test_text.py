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

import numpy as np
import pytest
from PIL import Image, ImageDraw, ImageFont

from designer.color import delta_e
from designer.engine import ComplianceEngine
from designer.text import extract_text, ocr_available
from designer.tokens import load_system
from designer.vectorize import VectorizeOptions, vectorize_file

pytestmark = pytest.mark.skipif(
    not ocr_available(), reason="tesseract not installed"
)

FONT_PATH = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"


def make_text_poster(tmp_path, message="HELLO WORLD"):
    img = Image.new("RGB", (480, 200), (243, 244, 246))
    draw = ImageDraw.Draw(img)
    font = ImageFont.truetype(FONT_PATH, 48)
    draw.text((40, 60), message, font=font, fill=(20, 26, 40))
    path = tmp_path / "poster.png"
    img.save(path)
    return path


def test_extract_text_finds_and_erases(tmp_path):
    path = make_text_poster(tmp_path)
    img = Image.open(path)
    cleaned, spans = extract_text(img)
    assert len(spans) == 1
    span = spans[0]
    assert "HELLO" in span.text.upper()
    assert "WORLD" in span.text.upper()
    # Color close to the ink used to draw it.
    assert delta_e(span.color, (20, 26, 40)) < 0.1
    # Size close to the 48px the text was set in.
    assert 30 <= span.font_size <= 80
    # The glyph pixels are gone: nothing dark remains in the cleaned image.
    arr = np.asarray(cleaned.convert("RGB"), dtype=np.int16)
    assert arr.sum(axis=2).min() > 400  # darkest pixel is nowhere near ink


def test_vectorize_emits_real_text(tmp_path):
    path = make_text_poster(tmp_path)
    doc = vectorize_file(path, VectorizeOptions(extract_text=True))
    texts = [s for s in doc.shapes if s.tag == "text"]
    assert len(texts) == 1
    assert "HELLO" in texts[0].text.upper()
    # No vector-outline ghost of the glyphs: apart from the background
    # rect, no large dark path should remain.
    from designer.color import parse_color
    from designer.svg import shape_area

    for shape in doc.shapes:
        if shape.tag != "path":
            continue
        rgb = parse_color(shape.fill or "")
        if rgb and delta_e(rgb, (20, 26, 40)) < 0.1:
            area = shape_area(shape, doc) or 0
            assert area < 500, "text survived as outlines instead of <text>"


def test_comply_enforces_brand_font_and_scale(tmp_path):
    path = make_text_poster(tmp_path)
    system = load_system()
    engine = ComplianceEngine(system)
    doc = engine.load(path, VectorizeOptions(extract_text=True))
    report = engine.comply(doc)

    text = next(s for s in doc.shapes if s.tag == "text")
    # Hallucinated/unknown source font is irrelevant: the emitted text
    # gets the system's primary font and an on-scale size.
    assert text.attrs["font-family"] == system.fonts[0]
    assert float(text.attrs["font-size"]) in system.type_scale
    assert text.attrs["fill"] in {t.hex for t in system.colors}
    assert any(f.rule == "type.font" and f.fixed for f in report.findings)


def test_no_text_option_keeps_outlines(tmp_path):
    path = make_text_poster(tmp_path)
    doc = vectorize_file(path, VectorizeOptions(extract_text=False))
    assert not any(s.tag == "text" for s in doc.shapes)
