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

"""Trace fidelity: anti-aliased / JPEG-soft edges trace as clean shapes,
and what can't be traced cleanly fails the report instead of passing."""

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

from designer.cli import main
from designer.engine import ComplianceEngine
from designer.path import parse_path
from designer.report import BLOCKED_SCORE_CAP, Finding, Report, Severity
from designer.tokens import load_system
from designer.vectorize import (
    VectorizeOptions,
    _clamped_handle,
    smooth_staircase,
    trace_mask,
    vectorize_file,
)


def _soft_logo(path, blur=1.0):
    img = Image.new("RGB", (400, 200), (255, 255, 255))
    d = ImageDraw.Draw(img)
    d.ellipse((20, 20, 180, 180), fill=(4, 157, 217))
    d.rounded_rectangle((220, 30, 380, 170), 20, fill=(142, 31, 117))
    img.filter(ImageFilter.GaussianBlur(blur)).save(path)
    return path


def test_antialias_rim_is_not_traced_as_halo_layers(tmp_path):
    doc = vectorize_file(_soft_logo(tmp_path / "soft.png"), VectorizeOptions(extract_text=False))
    fills = {s.get("fill") for s in doc.shapes if s.tag == "path"}
    # Background + two inks; no pale blend layers outlining each shape.
    assert len(fills) <= 3


def test_staircase_is_smoothed_but_square_corners_kept():
    m = np.zeros((40, 40), bool)
    m[5:30, 5:30] = True
    loop = trace_mask(m)[0]
    assert (5, 5) in smooth_staircase(loop)  # 25px runs both sides: a corner

    stairs = [(i // 2 + (i % 2), i // 2) for i in range(40)]  # 45-degree pixel steps
    stairs += [(20, 20 + k) for k in range(1, 20)] + [(20 - k, 39) for k in range(1, 20)]
    smoothed = smooth_staircase(stairs)
    # Interior diagonal points land on the x == y line, not on the steps.
    for x, y in smoothed[5:15]:
        assert abs(x - y) < 0.75


def test_curve_handle_is_clamped_to_its_segment():
    assert _clamped_handle((0, 0), (30, 0), 3.0) == (3.0, 0.0)
    assert _clamped_handle((0, 0), (1, 0), 3.0) == (1, 0)


def test_traced_curves_stay_inside_their_points(tmp_path):
    doc = vectorize_file(_soft_logo(tmp_path / "soft.png"), VectorizeOptions(extract_text=False))
    for shape in doc.shapes:
        if shape.tag != "path":
            continue
        for cmd, args in parse_path(shape.get("d")):
            for x, y in zip(args[0::2], args[1::2]):
                assert -2 <= x <= 402 and -2 <= y <= 202


def test_open_blocker_fails_the_report():
    report = Report("s", "t", [Finding("r", Severity.ERROR, "m", blocking=True)])
    assert report.blocked
    assert report.score <= BLOCKED_SCORE_CAP
    report.findings[0].fixed = True
    assert not report.blocked


def test_script_lettering_left_as_raster_blocks(tmp_path):
    # Thin, blurred two-ink lettering: dense enough that the hybrid pass
    # embeds it, but flat artwork, so the result must not pass.
    img = Image.new("RGB", (400, 200), (255, 255, 255))
    d = ImageDraw.Draw(img)
    d.rectangle((20, 20, 380, 90), fill=(4, 157, 217))
    rng = np.random.default_rng(3)
    for _ in range(400):
        x, y = rng.integers(40, 360), rng.integers(120, 180)
        d.line((x, y, x + rng.integers(-6, 6), y + rng.integers(-8, 8)), fill=(142, 31, 117), width=1)
    path = tmp_path / "script.png"
    img.filter(ImageFilter.GaussianBlur(0.6)).save(path)

    doc = vectorize_file(path, VectorizeOptions(extract_text=False))
    if any(s.tag == "image" for s in doc.shapes):
        assert doc.blockers
        report = ComplianceEngine(load_system(None)).audit(doc)
        assert report.blocked


def test_render_fails_when_brand_font_missing(tmp_path):
    svg = tmp_path / "t.svg"
    svg.write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" width="200" height="60">'
        '<text x="10" y="40" font-size="24" font-family="NoSuchBrandFont">Hi</text></svg>'
    )
    out = tmp_path / "t.png"
    assert main(["render", str(svg), "-o", str(out)]) == 1
    assert main(["render", str(svg), "-o", str(out), "--allow-font-substitute"]) == 0


def test_soft_source_warns_and_very_soft_blocks(tmp_path):
    sharp = vectorize_file(_soft_logo(tmp_path / "a.png", blur=0.0), VectorizeOptions(extract_text=False))
    assert not any("soft" in w for w in sharp.warnings) and not sharp.blockers

    soft = vectorize_file(_soft_logo(tmp_path / "b.png", blur=3.0), VectorizeOptions(extract_text=False))
    very = vectorize_file(_soft_logo(tmp_path / "c.png", blur=6.0), VectorizeOptions(extract_text=False))
    assert any("soft" in w for w in soft.warnings) or any("soft" in b for b in soft.blockers)
    assert any("too soft" in b for b in very.blockers)
