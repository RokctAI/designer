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

"""Regression tests for the adversarial-review fixes: every test here
reproduces a confirmed limitation and proves it is now handled."""

import numpy as np
import pytest
from PIL import Image

from designer.engine import ComplianceEngine
from designer.path import parse_path, path_area, path_subpaths
from designer.svg import Document, Shape, parse_svg, save, serialize
from designer.tokens import load_system
from designer.transform import transform_path
from designer.vectorize import ComplexityError, VectorizeOptions, vectorize_file


# ---------------------------------------------------- contrast (local bg)


def navy_panel_doc():
    """White text on a navy panel over a white canvas — perfectly
    legible; the old rule judged it against the canvas and destroyed it."""
    return Document(
        width=400,
        height=400,
        shapes=[
            Shape("rect", {"x": "0", "y": "0", "width": "400", "height": "400",
                           "fill": "#ffffff"}),
            Shape("rect", {"x": "40", "y": "40", "width": "320", "height": "160",
                           "fill": "#1e3a8a"}),
            Shape("text", {"x": "64", "y": "128", "font-size": "32",
                           "fill": "#ffffff", "font-family": "Inter"},
                  text="Legible"),
        ],
    )


def test_contrast_uses_local_background():
    engine = ComplianceEngine(load_system())
    doc = navy_panel_doc()
    report = engine.comply(doc)
    text = next(s for s in doc.shapes if s.tag == "text")
    # The legible white-on-navy text must NOT be "fixed".
    assert text.attrs["fill"] == "#ffffff"
    assert not any(f.rule == "a11y.contrast" for f in report.findings)


def test_contrast_still_fixes_real_violations_locally():
    engine = ComplianceEngine(load_system())
    doc = navy_panel_doc()
    text = next(s for s in doc.shapes if s.tag == "text")
    text.set("fill", "#1a56db")  # blue on navy: genuinely low contrast
    report = engine.comply(doc)
    from designer.color import contrast_ratio, parse_color

    fixed = parse_color(text.attrs["fill"])
    assert contrast_ratio(fixed, parse_color("#1e3a8a")) >= 3.0  # 32px = large text
    assert any(f.rule == "a11y.contrast" and f.fixed for f in report.findings)


# ------------------------------------------------------------ sanitization


def test_event_handlers_and_unsafe_hrefs_stripped(tmp_path):
    src = tmp_path / "evil.svg"
    src.write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">'
        '<rect x="0" y="0" width="100" height="100" fill="#ffffff" '
        '  onload="alert(document.cookie)" onclick="fetch(String())"/>'
        '<image x="0" y="0" width="10" height="10" href="javascript:alert(1)"/>'
        '<image x="0" y="0" width="10" height="10" href="data:image/png;base64,AAAA"/>'
        "<script>alert(1)</script>"
        "</svg>"
    )
    doc = parse_svg(src)
    out = serialize(doc)
    assert "onload" not in out and "onclick" not in out
    assert "javascript:" not in out
    assert "<script" not in out
    assert "data:image/png" in out  # legitimate embedded image survives
    assert any("unsafe attribute" in w for w in doc.warnings)
    assert any("script" in w for w in doc.warnings)


# ----------------------------------------------------- capability honesty


def test_css_styling_is_resolved_and_audited(tmp_path):
    """CSS-hidden off-system styling used to be invisible to the audit."""
    src = tmp_path / "styled.svg"
    src.write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 200 200">'
        "<style>.brand{fill:#ff0000} .hd{font-family:Papyrus;font-size:19px}</style>"
        '<circle class="brand" cx="50" cy="50" r="12"/>'
        '<text class="hd" x="10" y="150">Headline</text>'
        "</svg>"
    )
    doc = parse_svg(src)
    circle = next(s for s in doc.shapes if s.tag == "circle")
    text = next(s for s in doc.shapes if s.tag == "text")
    assert circle.fill == "#ff0000"
    assert text.attrs["font-family"] == "Papyrus"

    report = ComplianceEngine(load_system()).audit(doc)
    rules = {f.rule for f in report.findings}
    assert "type.font" in rules       # Papyrus caught
    assert "type.scale" in rules      # 19px caught
    assert "color.palette" in rules   # #ff0000 caught


def test_use_element_is_instantiated(tmp_path):
    src = tmp_path / "used.svg"
    src.write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 200 200">'
        '<defs><rect id="proto" width="20" height="20" fill="#1a56db"/></defs>'
        '<use href="#proto" x="100" y="100"/>'
        "</svg>"
    )
    doc = parse_svg(src)
    rect = next(s for s in doc.shapes if s.tag == "rect")
    assert rect.numeric("x") == 100 and rect.numeric("y") == 100
    assert rect.fill == "#1a56db"


def test_preserved_defs_round_trip_and_are_reported(tmp_path):
    src = tmp_path / "clipped.svg"
    src.write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">'
        '<defs><clipPath id="c"><rect width="10" height="10"/></clipPath></defs>'
        '<rect x="0" y="0" width="50" height="50" fill="#111827" clip-path="url(#c)"/>'
        '<text x="10" y="20" font-size="16">Hello <tspan dy="20">World</tspan></text>'
        "</svg>"
    )
    doc = parse_svg(src)
    assert any("clipPath" in d for d in doc.raw_defs)
    out = serialize(doc)
    assert "clipPath" in out  # rendering stays faithful
    joined = " ".join(doc.warnings)
    assert "clipPath" in joined
    assert "flattened" in joined  # tspan
    report = ComplianceEngine(load_system()).audit(doc)
    assert any(f.rule == "engine.capability" for f in report.findings)
    assert report.score < 100


def test_group_transform_is_baked_into_geometry(tmp_path):
    src = tmp_path / "grouped.svg"
    src.write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">'
        '<g transform="translate(10 10)">'
        '<rect x="0" y="0" width="10" height="10" fill="#111827" '
        '  transform="scale(2)"/>'
        "</g></svg>"
    )
    doc = parse_svg(src)
    rect = doc.shapes[0]
    # translate(10 10) scale(2) applied to a 10x10 rect at the origin
    assert rect.numeric("x") == 10 and rect.numeric("y") == 10
    assert rect.numeric("width") == 20 and rect.numeric("height") == 20
    assert "transform" not in rect.attrs


def test_rotated_primitive_keeps_transform_and_warns(tmp_path):
    src = tmp_path / "rotated.svg"
    src.write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">'
        '<rect x="5" y="5" width="30" height="10" fill="#1a56db" '
        '  transform="rotate(30)"/>'
        "</svg>"
    )
    doc = parse_svg(src)
    rect = doc.shapes[0]
    assert "transform" in rect.attrs  # geometry preserved, not distorted
    assert rect.numeric("width") == 30
    assert any("cannot be baked" in w for w in doc.warnings)


# ---------------------------------------------------------- path grammar


def test_parse_fused_arc_flags():
    cmds = parse_path("M 0 0 a5 5 0 0110 10")
    assert cmds[1] == ("a", [5, 5, 0, 0, 1, 10, 10])


def test_parse_compact_decimals():
    cmds = parse_path("M.5.5L10.5.25")
    assert cmds[0] == ("M", [0.5, 0.5])
    assert cmds[1] == ("L", [10.5, 0.25])


def test_parse_malformed_raises():
    with pytest.raises(ValueError):
        parse_path("1 2 3")
    with pytest.raises(ValueError):
        parse_path("M 1 2 L 3")  # missing coordinate


def test_transform_path_preserves_arc_flags_and_compact_syntax():
    out = transform_path("M 0 0 a5 5 0 0110 10", 2.0, 3.0, 4.0)
    cmds = parse_path(out)
    assert cmds[0] == ("M", [3, 4])
    # relative arc: radii and coords scale, rotation + flags untouched
    assert cmds[1] == ("a", [10, 10, 0, 0, 1, 20, 20])

    out2 = transform_path("M.5.5L10.5.25", 2.0, 0.0, 0.0)
    assert parse_path(out2) == [("M", [1, 1]), ("L", [21, 0.5])]


# -------------------------------------------------------------- path area


def test_donut_area_subtracts_hole():
    # 100x100 outer CW, 20x20 inner CCW hole -> 10000 - 400
    d = ("M 0 0 L 100 0 L 100 100 L 0 100 Z "
         "M 40 40 L 40 60 L 60 60 L 60 40 Z")
    assert path_area(d) == pytest.approx(9600, rel=0.01)


def test_curved_area_samples_beziers():
    # Full circle of radius 50 from two arcs: area ~ pi * 2500
    d = "M 0 50 A 50 50 0 1 1 100 50 A 50 50 0 1 1 0 50 Z"
    assert path_area(d, curve_samples=16) == pytest.approx(3.14159 * 2500, rel=0.02)


def test_relative_and_shorthand_commands_flatten():
    subs = path_subpaths("m 10 10 h 20 v 20 h -20 z")
    assert len(subs) == 1
    assert (30.0, 30.0) in subs[0]


# -------------------------------------------------------- complexity guard


def test_photographic_input_rejected(tmp_path):
    rng = np.random.default_rng(1)
    noise = rng.integers(0, 256, (256, 256, 3), dtype=np.uint8)
    p = tmp_path / "photo.png"
    Image.fromarray(noise).save(p)
    with pytest.raises(ComplexityError):
        vectorize_file(p, VectorizeOptions(extract_text=False))
    # force overrides the guard
    doc = vectorize_file(p, VectorizeOptions(extract_text=False, force=True))
    assert doc.shapes


def test_flat_artwork_passes_guard():
    doc = vectorize_file("examples/ai_logo.png", VectorizeOptions(extract_text=False))
    assert doc.shapes  # no ComplexityError


# ------------------------------------------------- gradients (review cases)


def _vec(tmp_path, name, arr):
    p = tmp_path / f"{name}.png"
    Image.fromarray(arr).save(p)
    return vectorize_file(p, VectorizeOptions(extract_text=False))


def test_diagonal_gradient_detected(tmp_path):
    yy, xx = np.mgrid[0:256, 0:256]
    t = ((xx + yy) / 510.0)[..., None]
    arr = (np.array([26, 86, 219]) * (1 - t) + np.array([255, 255, 255]) * t).astype(np.uint8)
    doc = _vec(tmp_path, "diag", arr)
    assert len(doc.defs) == 1 and doc.defs[0].kind == "linear"


def test_subtle_gradient_detected(tmp_path):
    yy, xx = np.mgrid[0:256, 0:256]
    t = (xx / 255.0)[..., None]
    arr = (np.array([30, 58, 138]) * (1 - t) + np.array([59, 130, 246]) * t).astype(np.uint8)
    doc = _vec(tmp_path, "subtle", arr)
    assert len(doc.defs) == 1


def test_flat_stripes_not_fused_into_gradient(tmp_path):
    arr = np.zeros((256, 256, 3), np.uint8)
    blues = [(26, 86, 219), (38, 99, 225), (52, 112, 230), (66, 125, 236), (80, 138, 241)]
    for i, c in enumerate(blues):
        arr[:, i * 51 : (i + 1) * 52] = c
    doc = _vec(tmp_path, "stripes", arr)
    assert doc.defs == []  # deliberate flat color-blocking stays flat


# --------------------------------------------------- margin anchor-awareness


def test_margin_respects_text_anchor_and_width():
    engine = ComplianceEngine(load_system(), format="instagram-post")
    doc = Document(width=1080, height=1080)
    doc.shapes.append(
        Shape("rect", {"x": "0", "y": "0", "width": "1080", "height": "1080",
                       "fill": "#f3f4f6"})
    )
    # End-anchored short text hugging the left edge: the LINE extends
    # left of the anchor, so the anchor must move right by ~the width.
    doc.shapes.append(
        Shape("text", {"x": "60", "y": "540", "font-size": "32",
                       "text-anchor": "end", "fill": "#111827",
                       "font-family": "Inter"}, text="PROMO")
    )
    # Start-anchored long line near the right edge must be pulled left.
    doc.shapes.append(
        Shape("text", {"x": "1000", "y": "600", "font-size": "32",
                       "fill": "#111827", "font-family": "Inter"},
              text="GRAND OPENING SALE")
    )
    engine.comply(doc)
    margin = 0.05 * 1080
    end_text = doc.shapes[1]
    est_end = 0.55 * 32 * len("PROMO")
    assert end_text.numeric("x") >= margin + est_end - 8  # grid slack
    start_text = doc.shapes[2]
    est_start = 0.55 * 32 * len("GRAND OPENING SALE")
    assert start_text.numeric("x") + est_start <= 1080 - margin + 8


# ----------------------------------------------- warnings survive round trip


def test_ocr_unavailable_is_reported(monkeypatch, tmp_path):
    import designer.text as text_mod

    monkeypatch.setattr(text_mod, "ocr_available", lambda: False)
    arr = np.full((64, 64, 3), (243, 244, 246), np.uint8)
    arr[16:48, 16:48] = (26, 86, 219)
    p = tmp_path / "flat.png"
    Image.fromarray(arr).save(p)
    doc = vectorize_file(p)  # extract_text=None -> auto -> unavailable
    assert any("OCR unavailable" in w for w in doc.warnings)
    report = ComplianceEngine(load_system()).audit(doc)
    assert any(f.rule == "engine.capability" for f in report.findings)


# ------------------------------------------------- unreadable image inputs


def _flat_png(tmp_path, name="art.png", size=64):
    arr = np.full((size, size, 3), (243, 244, 246), np.uint8)
    arr[size // 4: size // 2, size // 4: size // 2] = (26, 86, 219)
    p = tmp_path / name
    Image.fromarray(arr).save(p)
    return p


def test_zero_byte_file_raises_invalid_image(tmp_path):
    from designer.raster import InvalidImageError, load_image

    p = tmp_path / "empty.png"
    p.write_bytes(b"")
    with pytest.raises(InvalidImageError, match="empty.png"):
        load_image(p)


def test_non_image_file_raises_invalid_image(tmp_path):
    from designer.raster import InvalidImageError, load_image

    p = tmp_path / "not_an_image.png"
    p.write_text("hello, I am not a PNG")
    with pytest.raises(InvalidImageError, match="not_an_image.png"):
        load_image(p)


def test_truncated_png_raises_invalid_image(tmp_path):
    from designer.raster import InvalidImageError, load_image

    whole = _flat_png(tmp_path).read_bytes()
    p = tmp_path / "truncated.png"
    p.write_bytes(whole[: len(whole) // 2])
    with pytest.raises(InvalidImageError, match="truncated.png"):
        load_image(p)


def test_invalid_image_surfaces_through_vectorize_file(tmp_path):
    from designer.raster import InvalidImageError

    p = tmp_path / "empty.png"
    p.write_bytes(b"")
    with pytest.raises(InvalidImageError):
        vectorize_file(p)


def test_cli_reports_invalid_image_cleanly(tmp_path, capsys):
    from designer.cli import main as cli_main

    p = tmp_path / "empty.png"
    p.write_bytes(b"")
    code = cli_main(["vectorize", str(p), "-o", str(tmp_path / "out.svg")])
    captured = capsys.readouterr()
    assert code == 2
    assert "error:" in captured.err
    assert "empty.png" in captured.err


def test_decompression_bomb_raises_invalid_image(tmp_path, monkeypatch):
    from PIL import Image as PILImage

    from designer.raster import InvalidImageError, load_image

    p = _flat_png(tmp_path, size=64)
    monkeypatch.setattr(PILImage, "MAX_IMAGE_PIXELS", 10)
    with pytest.raises(InvalidImageError, match="too large"):
        load_image(p)


# --------------------------------------- load_image downscales before RGBA


def test_load_image_output_unchanged_by_resize_order(tmp_path):
    """Downscale-then-convert must give the same pixels the old
    convert-then-downscale order produced, for RGB and palette inputs."""
    from designer.raster import load_image

    rng = np.random.default_rng(7)
    arr = rng.integers(0, 255, (200, 300, 3), np.uint8)
    p = tmp_path / "rgb.png"
    Image.fromarray(arr).save(p)
    got = load_image(p, max_dim=128)
    ref = Image.open(p).convert("RGBA")
    scale = 128 / 300
    ref = ref.resize((128, max(1, round(200 * scale))), Image.LANCZOS)
    assert got.mode == "RGBA"
    assert np.array_equal(np.asarray(got), np.asarray(ref))

    pal = Image.fromarray(arr).convert("P", palette=Image.ADAPTIVE, colors=16)
    p2 = tmp_path / "pal.png"
    pal.save(p2, transparency=3)
    got2 = load_image(p2, max_dim=None)
    ref2 = Image.open(p2).convert("RGBA")
    assert got2.mode == "RGBA"
    assert np.array_equal(np.asarray(got2), np.asarray(ref2))
