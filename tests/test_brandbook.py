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

"""Brand manual renderer tests. PDFs are verified byte-wise (page
counts, decompressed content streams), the same way test_print_pdf
does — no PDF library required."""

import re
import zlib

import pytest

from designer.brandbook import BrandbookError, build_brandbook, render_brandbook
from designer.cli import main as cli_main
from designer.palette import derive_system
from designer.tokens import system_from_dict

SEEDS = ["#0F4C81", "#F5A623"]


def pdf_streams(data: bytes) -> bytes:
    out = b""
    for m in re.finditer(rb"/Length (\d+)[^>]*>>\s*stream\r?\n", data):
        chunk = data[m.end():m.end() + int(m.group(1))]
        try:
            out += zlib.decompress(chunk)
        except zlib.error:
            out += chunk
    return out


@pytest.fixture()
def system():
    return system_from_dict(derive_system(SEEDS, name="Demo Trading"))


@pytest.fixture()
def logo_svg(tmp_path):
    path = tmp_path / "logo.svg"
    path.write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">'
        '<rect x="0" y="0" width="100" height="100" fill="#0f4c81"/>'
        '<circle cx="50" cy="50" r="30" fill="#f5a623"/></svg>'
    )
    return path


def test_page_roster_without_logo(system):
    pages = build_brandbook(system)
    # Cover + color + typography + usage (color/typography may paginate).
    assert len(pages) >= 4
    assert all(p.width == 794.0 and p.height == 1123.0 for p in pages)
    cover_text = " ".join(s.text for s in pages[0].shapes if s.tag == "text")
    assert "Demo Trading" in cover_text and "Brand manual" in cover_text


def test_logo_page_only_when_logo_given(system, logo_svg):
    without = build_brandbook(system)
    with_logo = build_brandbook(system, logo=logo_svg)
    assert len(with_logo) == len(without) + 1
    logo_page = with_logo[1]
    texts = " ".join(s.text for s in logo_page.shapes if s.tag == "text")
    assert "Clear space" in texts and "Minimum size" in texts
    # The logo's own vector shapes were inlined, not rasterized.
    assert any(s.tag == "circle" for s in logo_page.shapes)


def test_missing_logo_is_an_error(system, tmp_path):
    with pytest.raises(BrandbookError, match="not found"):
        build_brandbook(system, logo=tmp_path / "nope.svg")


def test_rendered_pdf_pages_and_palette_values(system, logo_svg, tmp_path):
    out = render_brandbook(system, tmp_path / "book.pdf", logo=logo_svg)
    data = out.read_bytes()
    pages = build_brandbook(system, logo=logo_svg)
    assert data.count(b"/Type /Page ") == len(pages)
    assert f"/Count {len(pages)}".encode() in data
    ops = pdf_streams(data)
    # Every token's hex appears in the PDF text of the color page.
    for token in system.colors:
        assert token.hex.upper().encode() in ops
    # RGB and CMYK triples ride along, with the honesty label.
    assert b"HEX #0F4C81   RGB 15 76 129   CMYK" in ops
    assert b"uncoated approx." in ops
    # Contrast table names the guaranteed pairs.
    assert b"on-primary on primary" in ops
    assert re.search(rb"\d+\.\d\d:1", ops)


def test_typography_page_renders_scale_at_size(system, tmp_path):
    pages = build_brandbook(system)
    type_pages = [
        p for p in pages
        if any(s.text.startswith("Typography") for s in p.shapes if s.tag == "text")
    ]
    assert type_pages
    sizes = {
        s.numeric("font-size")
        for p in type_pages
        for s in p.shapes
        if s.tag == "text" and s.text.startswith("Aa ")
    }
    assert sizes == set(system.type_scale)
    ops = pdf_streams(render_brandbook(system, tmp_path / "t.pdf").read_bytes())
    assert b"Aa 64px" in ops and b"64.000 Tf" in ops


def test_usage_page_prints_system_specs(system, tmp_path):
    ops = pdf_streams(render_brandbook(system, tmp_path / "u.pdf").read_bytes())
    assert b"Usage rules" in ops
    # Derived system bleed; the "(3.0 mm)" tail is PDF-escaped, so match
    # up to the paren.
    assert b"35.4 px at 300 dpi" in ops
    assert b"8 px baseline grid" in ops
    assert b"at most" in ops


def test_cli_brandbook(system, tmp_path, capsys):
    import yaml

    system_yaml = tmp_path / "client.yaml"
    system_yaml.write_text(yaml.safe_dump(derive_system(SEEDS, name="CLI Co")))
    out = tmp_path / "book.pdf"
    assert cli_main(["brandbook", "--system", str(system_yaml),
                     "-o", str(out)]) == 0
    assert out.exists() and out.stat().st_size > 10_000
    assert "pages, A4" in capsys.readouterr().out
