import pytest

from designer.engine import ComplianceEngine
from designer.formats import all_formats, get_format
from designer.svg import Document, GradientDef, Shape
from designer.tokens import load_system
from designer.transform import transform_path


def test_catalog():
    assert get_format("instagram-post").width == 1080
    assert get_format("logo").margin == 0.0
    with pytest.raises(ValueError, match="Known formats"):
        get_format("nope")
    categories = {f.category for f in all_formats()}
    assert {"brand", "social", "print", "web", "presentation"} <= categories


def test_transform_path_scale_translate():
    d = "M 10 20 L 30 40 C 1 2 3 4 5 6 Z"
    out = transform_path(d, 2.0, 100.0, 10.0)
    assert out == "M 120 50 L 160 90 C 102 14 106 18 110 22 Z"


def test_transform_path_relative_and_arc():
    # Relative commands scale but don't translate; arc flags untouched.
    out = transform_path("m 10 10 l 5 5", 2.0, 100.0, 100.0)
    assert out == "m 20 20 l 10 10"
    out = transform_path("M 0 0 A 5 5 0 0 1 10 10", 2.0, 1.0, 1.0)
    assert out == "M 1 1 A 10 10 0 0 1 21 21"


def poster_doc(w=512, h=512):
    doc = Document(width=w, height=h)
    doc.shapes.append(
        Shape("rect", {"x": "0", "y": "0", "width": f"{w:g}", "height": f"{h:g}",
                       "fill": "#f3f4f6"})
    )
    doc.defs.append(
        GradientDef(id="g0", kind="linear", stops=[(0.0, "#1a56db"), (1.0, "#ffffff")],
                    coords={"x1": 0, "y1": 0, "x2": w, "y2": 0})
    )
    doc.shapes.append(
        Shape("path", {"d": "M 100 100 L 200 100 L 200 200 L 100 200 Z",
                       "fill": "url(#g0)", "fill-rule": "evenodd"})
    )
    doc.shapes.append(
        Shape("text", {"x": "2", "y": "500", "font-size": "10", "fill": "#111827",
                       "font-family": "Inter"}, text="tiny at the edge")
    )
    return doc


def test_canvas_rescale_to_format():
    engine = ComplianceEngine(load_system(), format="instagram-post")
    doc = poster_doc()
    report = engine.comply(doc)
    assert doc.width == 1080 and doc.height == 1080
    # Background stayed full-bleed.
    bg = doc.shapes[0]
    assert bg.numeric("width") == 1080 and bg.numeric("height") == 1080
    # Gradient coords scaled with the artwork.
    assert doc.defs[0].coords["x2"] == pytest.approx(1080, abs=2)
    assert any(f.rule == "format.canvas" and f.fixed for f in report.findings)


def test_margin_and_min_text_enforced():
    engine = ComplianceEngine(load_system(), format="instagram-post")
    doc = poster_doc()
    report = engine.comply(doc)
    spec = get_format("instagram-post")
    margin = spec.margin * 1080
    text = next(s for s in doc.shapes if s.tag == "text")
    assert margin <= text.numeric("x") <= 1080 - margin
    assert margin <= text.numeric("y") <= 1080 - margin
    # 10px scaled ~2.1x is ~21px, still under the 24px floor -> bumped
    # to a type-scale step at/above the floor.
    assert text.numeric("font-size") >= spec.min_text_size
    assert text.numeric("font-size") in load_system().type_scale
    assert any(f.rule == "format.min-text" and f.fixed for f in report.findings)


def test_matching_canvas_needs_no_rescale():
    engine = ComplianceEngine(load_system(), format="logo")
    doc = poster_doc(1024, 1024)
    report = engine.audit(doc)
    assert not any(f.rule == "format.canvas" for f in report.findings)


def test_hierarchy_rule_reports_flat_text():
    engine = ComplianceEngine(load_system())
    doc = Document(width=400, height=400)
    for y in ("100", "200"):
        doc.shapes.append(
            Shape("text", {"x": "40", "y": y, "font-size": "16", "fill": "#111827",
                           "font-family": "Inter"}, text="same size")
        )
    report = engine.audit(doc)
    assert any(f.rule == "type.hierarchy" for f in report.findings)

    doc.shapes[0].set("font-size", "32")
    report = engine.audit(doc)
    assert not any(f.rule == "type.hierarchy" for f in report.findings)


def test_image_shapes_survive_and_snap(tmp_path):
    # Product photos embedded as <image> (retail block ads) must round-trip
    # parsing, grid-snap, and format rescale — the engine treats the pixel
    # content as opaque but owns the geometry.
    from designer.svg import parse_svg, save

    doc = Document(width=200, height=200)
    doc.shapes.append(
        Shape("rect", {"x": "0", "y": "0", "width": "200", "height": "200",
                       "fill": "#f3f4f6"})
    )
    doc.shapes.append(
        Shape("image", {"x": "13", "y": "22", "width": "61", "height": "45",
                        "href": "data:image/png;base64,iVBORw0KGgo="})
    )
    out = tmp_path / "img.svg"
    save(doc, out)
    reparsed = parse_svg(out)
    img = next(s for s in reparsed.shapes if s.tag == "image")
    assert img.attrs["href"].startswith("data:image/png")

    engine = ComplianceEngine(load_system())
    engine.comply(reparsed)
    for attr in ("x", "y", "width", "height"):
        assert img.numeric(attr) % 8 == 0


def test_format_comply_is_idempotent():
    engine = ComplianceEngine(load_system(), format="instagram-post")
    doc = poster_doc()
    engine.comply(doc)
    second = engine.comply(doc)
    assert second.fixed_count == 0
    assert not [f for f in second.findings if not f.fixed]
