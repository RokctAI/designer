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

from designer.engine import ComplianceEngine
from designer.report import Severity
from designer.svg import Document, Shape
from designer.tokens import load_system, system_from_dict


def test_system_from_dict_matches_yaml_schema():
    system = system_from_dict(
        {
            "name": "Acme",
            "color": {"tokens": {"primary": "#1a56db", "white": "#ffffff"}, "max_colors": 3},
            "layout": {"grid": 4},
        }
    )
    assert system.name == "Acme"
    assert [t.name for t in system.colors] == ["primary", "white"]
    assert system.max_colors == 3
    assert system.grid == 4
    # Unspecified sections keep engine defaults.
    assert system.min_contrast_text == 4.5


def build_doc():
    """A deliberately non-compliant document."""
    return Document(
        width=320,
        height=320,
        shapes=[
            # Background: off-brand near-white.
            Shape("rect", {"x": "0", "y": "0", "width": "320", "height": "320", "fill": "#f2f2f5"}),
            # Off-brand blue, off-grid, off-scale stroke.
            Shape(
                "rect",
                {"x": "13", "y": "22", "width": "101", "height": "58",
                 "fill": "#2255cc", "stroke": "#333333", "stroke-width": "3"},
            ),
            # Tiny speck (AI noise).
            Shape("circle", {"cx": "300", "cy": "300", "r": "1", "fill": "#ff0000"}),
            # Low-contrast text in an off-system font at an off-scale size.
            Shape(
                "text",
                {"x": "40", "y": "200", "fill": "#d8d8d8",
                 "font-family": "Comic Sans MS", "font-size": "17"},
                text="Hello",
            ),
        ],
    )


def test_audit_finds_violations_without_mutating():
    engine = ComplianceEngine(load_system())
    doc = build_doc()
    before = [dict(s.attrs) for s in doc.shapes]
    report = engine.audit(doc)
    assert [dict(s.attrs) for s in doc.shapes] == before  # untouched
    rules_hit = {f.rule for f in report.findings}
    assert "color.palette" in rules_hit
    assert "layout.grid" in rules_hit
    assert "layout.min-size" in rules_hit
    assert "stroke.width" in rules_hit
    assert "type.font" in rules_hit
    assert "type.scale" in rules_hit
    assert "a11y.contrast" in rules_hit
    assert report.score < 100


def test_comply_fixes_and_improves_score():
    engine = ComplianceEngine(load_system())
    doc = build_doc()
    before = engine.audit(doc).score
    report = engine.comply(doc)
    assert report.score > before
    assert report.fixed_count > 0

    system = load_system()
    token_hexes = {t.hex for t in system.colors}
    for shape in doc.shapes:
        for prop in ("fill", "stroke"):
            value = shape.get(prop)
            if value:
                assert value in token_hexes, f"{prop}={value} not snapped to a token"

    # Speck removed.
    assert not any(s.tag == "circle" for s in doc.shapes)

    # Grid: all rect geometry on the 8px grid.
    for shape in doc.shapes:
        if shape.tag == "rect":
            for attr in ("x", "y", "width", "height"):
                assert float(shape.attrs[attr]) % 8 == 0

    # Typography fixed.
    text = next(s for s in doc.shapes if s.tag == "text")
    assert text.attrs["font-family"] == system.fonts[0]
    assert float(text.attrs["font-size"]) in system.type_scale


def test_comply_is_idempotent():
    """A second pass must apply no further fixes. Advisory findings
    (report-only rules like layout balance) legitimately persist — they
    describe judgment calls, not violations the engine can repair."""
    engine = ComplianceEngine(load_system())
    doc = build_doc()
    engine.comply(doc)
    snapshot = [dict(s.attrs) for s in doc.shapes]
    second = engine.comply(doc)
    assert second.fixed_count == 0
    assert [dict(s.attrs) for s in doc.shapes] == snapshot  # nothing moved
    fixable = [
        f for f in second.findings
        if not f.fixed and f.severity is not Severity.INFO
    ]
    assert not fixable


def test_contrast_fix_recolors_text():
    engine = ComplianceEngine(load_system())
    doc = build_doc()
    engine.comply(doc)
    text = next(s for s in doc.shapes if s.tag == "text")
    from designer.color import contrast_ratio, parse_color

    bg = parse_color(doc.background_color())
    assert contrast_ratio(parse_color(text.attrs["fill"]), bg) >= 4.5


def test_max_colors_rule():
    # All fills are legal tokens, but using every token at once busts
    # the per-deliverable color cap (7 tokens, cap of 6).
    system = load_system()
    doc = Document(width=100, height=100)
    palette = [t.hex for t in system.colors]
    assert len(palette) > system.max_colors
    for i, color in enumerate(palette):
        doc.shapes.append(
            Shape("rect", {"x": "0", "y": str(i * 10), "width": str(100 - i), "height": "10", "fill": color})
        )
    engine = ComplianceEngine(system)
    report = engine.comply(doc)
    used = {s.attrs["fill"] for s in doc.shapes}
    assert len(used) <= system.max_colors
    assert any(f.rule == "color.max" and f.fixed for f in report.findings)


def test_severity_weighting():
    engine = ComplianceEngine(load_system())
    report = engine.audit(build_doc())
    assert any(f.severity == Severity.ERROR for f in report.findings)
    assert 0 <= report.score < 100
