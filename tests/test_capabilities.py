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

"""Tests for the capability build-out: fonts, matrices, layout/print
rules, templates, rendering, hybrid output and rotated-text OCR."""

import base64
import io

import numpy as np
import pytest
from PIL import Image, ImageDraw, ImageFont

from designer.engine import ComplianceEngine
from designer.fonts import fit_size, measure, resolve_font_file, resolve_with_fallback
from designer.formats import FormatSpec
from designer.geometry import point_in_shape, shape_box
from designer.matrix import IDENTITY, apply, is_axis_aligned, multiply, parse_transform
from designer.render import render_pdf, render_png
from designer.svg import Document, Shape, parse_svg
from designer.template import Item, TemplateData, UnitTooSmall, grid_for
from designer.template import render as render_template
from designer.text import ocr_available
from designer.tokens import load_system, system_from_dict
from designer.vectorize import VectorizeOptions, vectorize_file

DEJAVU = "DejaVu Sans"


# ------------------------------------------------------------- fonts


def test_real_metrics_beat_character_estimate():
    m = measure("GRAND OPENING", DEJAVU, 64, bold=True)
    assert m.exact
    # The old 0.55em-per-character estimate was ~25% short.
    assert m.width > 0.55 * 64 * len("GRAND OPENING")
    assert m.height > 0


def test_unresolvable_family_falls_back_and_says_so():
    m = measure("hello", "NotAnInstalledFont", 32)
    assert not m.exact
    path, substituted = resolve_with_fallback("NotAnInstalledFont")
    assert path and substituted


def test_fit_size_picks_largest_that_fits():
    scale = [12, 16, 24, 32, 48, 64]
    big = fit_size("SALE", DEJAVU, 400, 100, scale)
    small = fit_size("SALE", DEJAVU, 40, 100, scale)
    assert big is not None and small is not None and big > small
    assert measure("SALE", DEJAVU, small).width <= 40


# ------------------------------------------------------------ matrices


def test_parse_and_compose_transforms():
    m = parse_transform("translate(10 20) scale(2)")
    assert apply(m, 1, 1) == (12, 22)
    rot = parse_transform("rotate(90)")
    x, y = apply(rot, 1, 0)
    assert abs(x) < 1e-9 and abs(y - 1) < 1e-9
    assert is_axis_aligned(parse_transform("translate(5 5) scale(3 2)"))
    assert not is_axis_aligned(rot)


def test_rotate_about_a_center():
    m = parse_transform("rotate(180 10 10)")
    x, y = apply(m, 10, 0)
    assert abs(x - 10) < 1e-6 and abs(y - 20) < 1e-6


def test_identity_composition():
    m = parse_transform("translate(3 4)")
    assert multiply(IDENTITY, m) == m


# ----------------------------------------------------------- geometry


def test_text_box_uses_font_metrics():
    shape = Shape("text", {"x": "10", "y": "100", "font-size": "40",
                           "font-family": DEJAVU}, text="WIDE HEADLINE")
    box = shape_box(shape)
    assert box is not None
    assert box[2] - box[0] == pytest.approx(measure("WIDE HEADLINE", DEJAVU, 40).width, rel=0.01)


def test_even_odd_point_test_respects_holes():
    donut = Shape("path", {"d": "M 0 0 L 100 0 L 100 100 L 0 100 Z "
                                "M 40 40 L 40 60 L 60 60 L 60 40 Z"})
    assert point_in_shape(donut, 10, 10)     # in the ring
    assert not point_in_shape(donut, 50, 50)  # in the hole


# -------------------------------------------------------- layout rules


def test_collision_detects_and_moves_overlapping_text():
    doc = Document(width=400, height=400)
    doc.shapes.append(Shape("rect", {"x": "0", "y": "0", "width": "400",
                                     "height": "400", "fill": "#ffffff"}))
    for y in ("100", "104"):  # deliberately stacked on top of each other
        doc.shapes.append(
            Shape("text", {"x": "40", "y": y, "font-size": "32", "fill": "#111827",
                           "font-family": DEJAVU}, text="Overlapping")
        )
    engine = ComplianceEngine(load_system())
    report = engine.audit(doc)
    assert any(f.rule == "layout.collision" for f in report.findings)

    engine.comply(doc)
    boxes = [shape_box(s) for s in doc.shapes if s.tag == "text"]
    assert boxes[0][3] <= boxes[1][1] + 1 or boxes[1][3] <= boxes[0][1] + 1


def test_text_hidden_under_opaque_shape_is_reported():
    doc = Document(width=200, height=200, shapes=[
        Shape("rect", {"x": "0", "y": "0", "width": "200", "height": "200", "fill": "#ffffff"}),
        Shape("text", {"x": "20", "y": "100", "font-size": "24", "fill": "#111827",
                       "font-family": DEJAVU}, text="Hidden"),
        Shape("rect", {"x": "0", "y": "60", "width": "200", "height": "80", "fill": "#1a56db"}),
    ])
    report = ComplianceEngine(load_system()).audit(doc)
    assert any(
        f.rule == "layout.collision" and "painted over" in f.message
        for f in report.findings
    )


def test_alignment_snaps_near_misses():
    doc = Document(width=400, height=400, shapes=[
        Shape("rect", {"x": "0", "y": "0", "width": "400", "height": "400", "fill": "#ffffff"}),
        Shape("rect", {"x": "40", "y": "40", "width": "100", "height": "40", "fill": "#1a56db"}),
        Shape("rect", {"x": "41", "y": "120", "width": "100", "height": "40", "fill": "#1a56db"}),
        Shape("rect", {"x": "39", "y": "200", "width": "100", "height": "40", "fill": "#1a56db"}),
    ])
    engine = ComplianceEngine(load_system())
    assert any(f.rule == "layout.alignment" for f in engine.audit(doc).findings)
    engine.comply(doc)
    lefts = {s.numeric("x") for s in doc.shapes[1:]}
    assert len(lefts) == 1  # all three now share an exact edge


def test_balance_and_whitespace_are_advisory():
    doc = Document(width=400, height=400, shapes=[
        Shape("rect", {"x": "0", "y": "0", "width": "400", "height": "400", "fill": "#ffffff"}),
        Shape("rect", {"x": "300", "y": "300", "width": "90", "height": "90", "fill": "#1a56db"}),
        Shape("rect", {"x": "310", "y": "200", "width": "80", "height": "80", "fill": "#f59e0b"}),
    ])
    report = ComplianceEngine(load_system()).audit(doc)
    balance = [f for f in report.findings if f.rule == "layout.balance"]
    assert balance and balance[0].severity.value == "info"


# --------------------------------------------------------- print rules


def print_system():
    return system_from_dict({
        "name": "Press",
        "color": {"tokens": {"ink": {"hex": "#111827", "role": "ink"},
                             "white": {"hex": "#ffffff", "role": "surface"}}},
        # The brand's stroke scale includes a screen-only hairline that
        # the press cannot hold — exactly the case print.hairline exists
        # for. Newsprint ink limits run lower than coated stock.
        "print": {"bleed": 9, "min_stroke": 0.75, "max_ink_coverage": 200},
        "stroke": {"widths": [0.25, 0.75, 1, 2]},
    })


def test_hairline_stroke_is_fixed_for_print():
    doc = Document(width=336, height=192, shapes=[
        Shape("rect", {"x": "8", "y": "8", "width": "104", "height": "48",
                       "fill": "none", "stroke": "#111827", "stroke-width": "0.25"}),
    ])
    engine = ComplianceEngine(print_system(), format="business-card")
    report = engine.comply(doc)
    assert any(f.rule == "print.hairline" and f.fixed for f in report.findings)
    assert doc.shapes[0].numeric("stroke-width") >= 0.75


def test_bleed_extends_full_bleed_background():
    doc = Document(width=336, height=192, shapes=[
        Shape("rect", {"x": "0", "y": "0", "width": "336", "height": "192", "fill": "#ffffff"}),
    ])
    engine = ComplianceEngine(print_system(), format="business-card")
    report = engine.comply(doc)
    assert any(f.rule == "print.bleed" and f.fixed for f in report.findings)
    assert doc.shapes[0].numeric("x") == -9


def test_ink_coverage_flags_heavy_colors():
    # A saturated dark navy is a "rich black" mix: ~210% total ink, over
    # a 200% newsprint limit. Plain near-black (#050505) is not — it
    # separates to almost pure K — and must NOT be flagged.
    from designer.rules.print_rules import total_ink

    assert total_ink((0, 51, 102)) > 200
    assert total_ink((5, 5, 5)) < 200

    doc = Document(width=336, height=192, shapes=[
        Shape("rect", {"x": "0", "y": "0", "width": "336", "height": "192", "fill": "#003366"}),
    ])
    report = ComplianceEngine(print_system(), format="business-card").audit(doc)
    assert any(f.rule == "print.ink" for f in report.findings)

    plain = Document(width=336, height=192, shapes=[
        Shape("rect", {"x": "0", "y": "0", "width": "336", "height": "192", "fill": "#050505"}),
    ])
    plain_report = ComplianceEngine(print_system(), format="business-card").audit(plain)
    assert not any(f.rule == "print.ink" for f in plain_report.findings)


def test_print_rules_do_not_run_for_screen_formats():
    doc = Document(width=1080, height=1080, shapes=[
        Shape("rect", {"x": "0", "y": "0", "width": "1080", "height": "1080", "fill": "#ffffff"}),
    ])
    report = ComplianceEngine(print_system(), format="instagram-post").audit(doc)
    assert not any(f.rule.startswith("print.") for f in report.findings)


# ------------------------------------------------------ role-aware snap


def test_large_areas_snap_to_surface_not_accent():
    system = load_system()
    doc = Document(width=200, height=200, shapes=[
        # A big, slightly-off warm background: nearest overall token is
        # the amber accent, but a background must land on a surface.
        Shape("rect", {"x": "0", "y": "0", "width": "200", "height": "200",
                       "fill": "#f7ead3"}),
    ])
    ComplianceEngine(system).comply(doc)
    fill = doc.shapes[0].attrs["fill"]
    surfaces = {t.hex for t in system.colors if t.role in ("surface", "background", "ink", "text")}
    assert fill in surfaces


# ------------------------------------------------------------ templates


def _photo(color=(200, 120, 60)):
    img = Image.new("RGB", (120, 90), color)
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()


def test_single_template_fills_and_fits(tmp_path):
    template = parse_svg("examples/templates/logo-left.svg")
    data = TemplateData(
        fields={"headline": "A VERY LONG HEADLINE THAT MUST SHRINK",
                "offer": "50% off", "contact": "071 234 5678"},
        palette=["#c0392b", "#fdf2e9"],
        images={"logo": _photo()},
    )
    doc = render_template(template, data, load_system())
    texts = {s.text: s for s in doc.shapes if s.tag == "text"}
    assert "A VERY LONG HEADLINE THAT MUST SHRINK" in texts
    headline = texts["A VERY LONG HEADLINE THAT MUST SHRINK"]
    # Shrunk to fit its declared 400px box.
    assert measure(headline.text, headline.get("font-family"),
                   headline.numeric("font-size")).width <= 400
    # Palette applied and markers stripped.
    assert any(s.attrs.get("fill") == "#c0392b" for s in doc.shapes)
    assert not any(k.startswith("data-") for s in doc.shapes for k in s.attrs)


def test_small_unit_drops_logo_and_gives_space_to_headline():
    template = parse_svg("examples/templates/logo-left.svg")
    template.width = 300  # below the logo slot's data-min-unit-width
    data = TemplateData(fields={"headline": "SMALL AD"}, images={"logo": _photo()})
    doc = render_template(template, data, load_system())
    assert not any(s.tag == "image" for s in doc.shapes)  # logo dropped
    assert any(s.text == "SMALL AD" for s in doc.shapes)  # message kept


def test_empty_slots_leave_no_placeholder():
    template = parse_svg("examples/templates/logo-left.svg")
    doc = render_template(template, TemplateData(fields={"headline": "Only this"}),
                          load_system())
    assert [s.text for s in doc.shapes if s.tag == "text"] == ["Only this"]


def test_composite_grid_and_upgrade_error():
    template = parse_svg("examples/templates/blocks.svg")
    cell = parse_svg("examples/templates/blocks-cell.svg")
    system = load_system()
    items = [Item(title=f"P{i}", price="R9.99", image_href=_photo()) for i in range(6)]
    doc = render_template(
        template, TemplateData(fields={"headline": "SPECIALS"}, items=items),
        system, cell_template=cell,
    )
    assert sum(1 for s in doc.shapes if s.tag == "image") == 6

    with pytest.raises(UnitTooSmall) as excinfo:
        render_template(
            template,
            TemplateData(items=[Item(title=f"P{i}", price="R1") for i in range(40)]),
            system, cell_template=cell,
        )
    assert excinfo.value.fitting >= 1
    assert "larger unit" in str(excinfo.value)


def test_grid_prefers_aspect_matching_slots():
    cols, rows, w, h = grid_for(6, 600, 600, 100, 10, target_aspect=1.0)
    assert cols * rows >= 6
    assert w > 0 and h > 0


def test_template_output_is_compliant():
    template = parse_svg("examples/templates/logo-left.svg")
    data = TemplateData(
        fields={"headline": "SALE", "offer": "Half price", "contact": "071 000 0000"},
        palette=["#c0392b", "#fdf2e9"],
    )
    doc = render_template(template, data, load_system())
    engine = ComplianceEngine(load_system())
    report = engine.comply(doc)
    token_hexes = {t.hex for t in load_system().colors}
    for shape in doc.shapes:
        if shape.get("fill") and shape.tag != "image":
            assert shape.attrs["fill"] in token_hexes
    assert report.score > 50


# ------------------------------------------------------------ rendering


def test_render_png_matches_document_colors(tmp_path):
    doc = Document(width=100, height=100, shapes=[
        Shape("rect", {"x": "0", "y": "0", "width": "100", "height": "100", "fill": "#1a56db"}),
    ])
    img = render_png(doc, tmp_path / "flat.png", width=50)
    assert img.size == (50, 50)
    assert img.getpixel((25, 25)) == (26, 86, 219)


def test_render_png_honors_even_odd_holes():
    doc = Document(width=100, height=100, shapes=[
        Shape("rect", {"x": "0", "y": "0", "width": "100", "height": "100", "fill": "#ffffff"}),
        Shape("path", {"d": "M 10 10 L 90 10 L 90 90 L 10 90 Z "
                            "M 40 40 L 40 60 L 60 60 L 60 40 Z",
                       "fill": "#111827", "fill-rule": "evenodd"}),
    ])
    img = render_png(doc, None, supersample=1)
    assert img.getpixel((20, 20)) == (17, 24, 39)     # ring is filled
    assert img.getpixel((50, 50)) == (255, 255, 255)  # hole is not


def test_render_png_draws_gradients(tmp_path):
    from designer.svg import GradientDef

    doc = Document(width=100, height=100)
    doc.defs.append(GradientDef(id="g", kind="linear",
                                stops=[(0.0, "#000000"), (1.0, "#ffffff")],
                                coords={"x1": 0, "y1": 0, "x2": 100, "y2": 0}))
    doc.shapes.append(Shape("rect", {"x": "0", "y": "0", "width": "100",
                                     "height": "100", "fill": "url(#g)"}))
    img = render_png(doc, None, supersample=1)
    left = img.getpixel((5, 50))[0]
    right = img.getpixel((95, 50))[0]
    assert right > left + 100  # ramps dark -> light


def test_render_pdf_is_structurally_valid(tmp_path):
    doc = parse_svg("examples/ai_poster.compliant.svg")
    out = render_pdf(doc, tmp_path / "out.pdf")
    data = out.read_bytes()
    assert data.startswith(b"%PDF-")
    assert data.rstrip().endswith(b"%%EOF")
    assert b"/Type /Catalog" in data
    assert b"xref" in data
    assert b"FontFile2" in data      # font embedded, not just referenced
    assert b"ShadingType" in data    # gradient preserved as vector


def test_render_pdf_cmyk_option(tmp_path):
    doc = Document(width=100, height=100, shapes=[
        Shape("rect", {"x": "0", "y": "0", "width": "100", "height": "100", "fill": "#1a56db"}),
    ])
    out = render_pdf(doc, tmp_path / "cmyk.pdf", cmyk=True)
    data = out.read_bytes()
    assert data.startswith(b"%PDF-")
    assert out.stat().st_size > 400


# --------------------------------------------------------------- hybrid


def test_photo_region_is_embedded_not_traced(tmp_path):
    rng = np.random.default_rng(5)
    arr = np.full((400, 400, 3), (243, 244, 246), np.uint8)
    arr[20:120, 20:380] = (26, 86, 219)
    arr[180:340, 80:320] = rng.integers(0, 256, (160, 240, 3), dtype=np.uint8)
    path = tmp_path / "mixed.png"
    Image.fromarray(arr).save(path)

    doc = vectorize_file(path, VectorizeOptions(extract_text=False))
    images = [s for s in doc.shapes if s.tag == "image"]
    assert len(images) == 1
    assert images[0].attrs["href"].startswith("data:image/png;base64,")
    assert any(s.tag == "path" for s in doc.shapes)  # flat art still traced
    assert any("photographic region" in w for w in doc.warnings)


def test_hybrid_can_be_disabled(tmp_path):
    arr = np.full((200, 200, 3), (243, 244, 246), np.uint8)
    arr[50:150, 50:150] = (26, 86, 219)
    path = tmp_path / "flat.png"
    Image.fromarray(arr).save(path)
    doc = vectorize_file(path, VectorizeOptions(extract_text=False, hybrid=False))
    assert not any(s.tag == "image" for s in doc.shapes)


# ---------------------------------------------------------- rotated OCR


@pytest.mark.skipif(not ocr_available(), reason="tesseract not installed")
def test_tilted_headline_is_read_and_erased():
    font_path = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
    img = Image.new("RGB", (600, 400), (243, 244, 246))
    ImageDraw.Draw(img).text((40, 40), "STRAIGHT LINE",
                             font=ImageFont.truetype(font_path, 44), fill=(20, 26, 40))
    tilt = Image.new("RGB", (500, 120), (243, 244, 246))
    ImageDraw.Draw(tilt).text((10, 20), "TILTED SALE",
                              font=ImageFont.truetype(font_path, 48), fill=(200, 30, 40))
    img.paste(tilt.rotate(-15, expand=True, fillcolor=(243, 244, 246)), (30, 180))

    from designer.text import extract_text

    cleaned, spans = extract_text(img)
    texts = {s.text.upper() for s in spans}
    assert "STRAIGHT LINE" in texts
    assert "TILTED SALE" in texts
    tilted = next(s for s in spans if s.text.upper() == "TILTED SALE")
    assert abs(tilted.angle) > 5  # detected as rotated, not upright
    upright = next(s for s in spans if s.text.upper() == "STRAIGHT LINE")
    assert abs(upright.angle) < 1
    # Both runs erased: no ink left anywhere.
    arr = np.asarray(cleaned.convert("RGB"), dtype=np.int16)
    assert arr.sum(axis=2).min() > 400
