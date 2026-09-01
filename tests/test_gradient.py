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

import numpy as np
import pytest
from PIL import Image

from designer.color import delta_e, parse_color
from designer.engine import ComplianceEngine
from designer.svg import Document, GradientDef, Shape
from designer.tokens import load_system, system_from_dict
from designer.vectorize import VectorizeOptions, vectorize_file


def make_linear_gradient_png(tmp_path, start=(26, 86, 219), end=(255, 255, 255)):
    w, h = 256, 256
    t = np.linspace(0, 1, w)[None, :, None]
    arr = (np.array(start) * (1 - t) + np.array(end) * t).astype(np.uint8)
    arr = np.repeat(arr, h, axis=0)
    path = tmp_path / "linear.png"
    Image.fromarray(arr).save(path)
    return path


def make_radial_glow_png(tmp_path, inner=(245, 158, 11), outer=(17, 24, 39)):
    size = 256
    yy, xx = np.mgrid[0:size, 0:size]
    r = np.hypot(xx - size / 2, yy - size / 2) / (size / 2)
    r = np.clip(r, 0, 1)[..., None]
    arr = (np.array(inner) * (1 - r) + np.array(outer) * r).astype(np.uint8)
    path = tmp_path / "radial.png"
    Image.fromarray(arr).save(path)
    return path


def test_linear_gradient_reconstructed(tmp_path):
    path = make_linear_gradient_png(tmp_path)
    doc = vectorize_file(path, VectorizeOptions(extract_text=False))
    assert len(doc.defs) == 1
    grad = doc.defs[0]
    assert grad.kind == "linear"
    assert len(grad.stops) >= 3
    # End colors approximate the true endpoints (direction of the
    # traced chain is arbitrary; the axis coords flip with it).
    ends = {0: parse_color(grad.stops[0][1]), 1: parse_color(grad.stops[-1][1])}
    d_forward = delta_e(ends[0], (26, 86, 219)) + delta_e(ends[1], (255, 255, 255))
    d_reverse = delta_e(ends[0], (255, 255, 255)) + delta_e(ends[1], (26, 86, 219))
    assert min(d_forward, d_reverse) < 0.24
    # Axis is horizontal: x varies, y roughly constant.
    assert abs(grad.coords["x2"] - grad.coords["x1"]) > 100
    assert abs(grad.coords["y2"] - grad.coords["y1"]) < 40
    # A shape actually references it.
    assert any((s.fill or "").startswith("url(#") for s in doc.shapes)


def test_radial_gradient_reconstructed(tmp_path):
    path = make_radial_glow_png(tmp_path)
    doc = vectorize_file(path, VectorizeOptions(extract_text=False))
    assert len(doc.defs) >= 1
    grad = doc.defs[0]
    assert grad.kind == "radial"
    assert abs(grad.coords["cx"] - 128) < 30
    assert abs(grad.coords["cy"] - 128) < 30
    # Inner stop is the warm color, outer is the dark color.
    assert delta_e(parse_color(grad.stops[0][1]), (245, 158, 11)) < 0.15
    assert delta_e(parse_color(grad.stops[-1][1]), (17, 24, 39)) < 0.15


def test_flat_image_produces_no_gradients(tmp_path):
    arr = np.full((128, 128, 3), (243, 244, 246), dtype=np.uint8)
    arr[32:96, 32:96] = (26, 86, 219)
    path = tmp_path / "flat.png"
    Image.fromarray(arr).save(path)
    doc = vectorize_file(path, VectorizeOptions(extract_text=False))
    assert doc.defs == []


def test_no_gradients_option_falls_back_to_flat(tmp_path):
    path = make_linear_gradient_png(tmp_path)
    doc = vectorize_file(
        path, VectorizeOptions(extract_text=False, detect_gradients=False)
    )
    assert doc.defs == []


def gradient_doc(stops):
    doc = Document(width=200, height=200)
    doc.defs.append(
        GradientDef(
            id="g0",
            kind="linear",
            stops=stops,
            coords={"x1": 0, "y1": 0, "x2": 200, "y2": 0},
        )
    )
    doc.shapes.append(
        Shape("rect", {"x": "0", "y": "0", "width": "200", "height": "200",
                       "fill": "url(#g0)"})
    )
    return doc


def test_gradient_rule_snaps_stops_to_tokens():
    engine = ComplianceEngine(load_system())
    doc = gradient_doc([(0.0, "#2255cc"), (1.0, "#f2f2f5")])
    report = engine.comply(doc)
    system = load_system()
    token_hexes = {t.hex for t in system.colors}
    for _, color in doc.defs[0].stops:
        assert color in token_hexes
    assert any(f.rule == "color.gradient" and f.fixed for f in report.findings)


def test_gradient_rule_flattens_when_disallowed():
    system = system_from_dict(
        {
            "name": "NoGrad",
            "color": {"tokens": {"primary": "#1a56db", "white": "#ffffff"}},
            "gradient": {"allowed": False},
        }
    )
    engine = ComplianceEngine(system)
    doc = gradient_doc([(0.0, "#1a56db"), (1.0, "#ffffff")])
    report = engine.comply(doc)
    assert doc.defs == []  # def removed
    fill = doc.shapes[0].fill
    assert fill in {"#1a56db", "#ffffff"}
    assert any(
        f.rule == "color.gradient" and f.fixed and "flattened" in (f.fix_description or "")
        for f in report.findings
    )


def test_gradient_stop_thinning():
    stops = [(i / 5, "#1a56db") for i in range(6)]
    doc = gradient_doc(stops)
    engine = ComplianceEngine(load_system())  # max_stops = 4
    engine.comply(doc)
    grad = doc.defs[0]
    assert len(grad.stops) == 4
    assert grad.stops[0][0] == 0.0 and grad.stops[-1][0] == 1.0


def test_gradient_svg_round_trip(tmp_path):
    from designer.svg import parse_svg, save

    path = make_linear_gradient_png(tmp_path)
    doc = vectorize_file(path, VectorizeOptions(extract_text=False))
    out = tmp_path / "grad.svg"
    save(doc, out)
    reparsed = parse_svg(out)
    assert len(reparsed.defs) == len(doc.defs)
    assert reparsed.defs[0].kind == doc.defs[0].kind
    assert len(reparsed.defs[0].stops) == len(doc.defs[0].stops)
    assert reparsed.gradient_by_ref("url(#grad0)") is reparsed.defs[0]


def test_comply_pipeline_on_gradient_image(tmp_path):
    path = make_linear_gradient_png(tmp_path, start=(30, 90, 200), end=(250, 250, 252))
    engine = ComplianceEngine(load_system())
    doc = engine.load(path, VectorizeOptions(extract_text=False))
    report = engine.comply(doc)
    token_hexes = {t.hex for t in load_system().colors}
    for grad in doc.defs:
        for _, color in grad.stops:
            assert color in token_hexes
    assert report.score > 50
