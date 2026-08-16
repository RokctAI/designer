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

import pytest
import yaml

from designer.color import contrast_ratio, parse_color
from designer.engine import ComplianceEngine
from designer.palette import derive_system, palette_summary
from designer.report import Severity
from designer.svg import Document, Shape
from designer.tokens import load_system, system_from_dict

SEED_SETS = [
    ["#0F4C81", "#F5A623"],                # mid blue + light orange
    ["#101014", "#1a1a2e"],                # very dark, low-chroma seeds
    ["#fefae0", "#faedcd"],                # very light seeds
    ["#808080", "#7f7f80"],                # near-achromatic seeds
    ["#0F4C81", "#F5A623", "#2E8B57"],     # three seeds
]


def _hex(data, token):
    return data["color"]["tokens"][token]["hex"]


def _rgb(data, token):
    return parse_color(_hex(data, token))


def test_seed_count_and_hex_validation():
    with pytest.raises(ValueError):
        derive_system(["#0F4C81"])
    with pytest.raises(ValueError):
        derive_system(["#0F4C81", "#F5A623", "#2E8B57", "#ffffff"])
    with pytest.raises(ValueError):
        derive_system(["#0F4C81", "not-a-color"])


def test_seed_roles_two_vs_three():
    two = derive_system(["#0F4C81", "#F5A623"])
    assert _hex(two, "primary") == "#0f4c81"
    assert _hex(two, "accent") == "#f5a623"
    assert "secondary" not in two["color"]["tokens"]

    three = derive_system(["#0F4C81", "#F5A623", "#2E8B57"])
    assert three["color"]["tokens"]["secondary"] == {"hex": "#2e8b57", "role": "secondary"}
    assert three["color"]["max_colors"] == len(three["color"]["tokens"])


def test_deterministic():
    for seeds in SEED_SETS:
        assert derive_system(seeds) == derive_system(seeds)


@pytest.mark.parametrize("seeds", SEED_SETS)
def test_wcag_guarantees(seeds):
    data = derive_system(seeds)
    minimum = data["accessibility"]["min_contrast_text"]
    assert contrast_ratio(_rgb(data, "text"), _rgb(data, "surface")) >= minimum
    assert contrast_ratio(_rgb(data, "text"), _rgb(data, "paper")) >= minimum
    assert contrast_ratio(_rgb(data, "ink"), _rgb(data, "surface")) >= minimum
    assert contrast_ratio(_rgb(data, "on-primary"), _rgb(data, "primary")) >= minimum


@pytest.mark.parametrize("seeds", SEED_SETS)
def test_valid_system_with_expected_roles(seeds):
    data = derive_system(seeds)
    system = system_from_dict(data)
    roles = {t.role for t in system.colors}
    assert {"primary", "accent", "ink", "text", "surface"} <= roles
    # Neutral scale present: 4 fixed lightness steps of the primary hue.
    names = [t.name for t in system.colors]
    assert [n for n in names if n.startswith("neutral-")] == [
        "neutral-800", "neutral-500", "neutral-300", "neutral-100",
    ]
    assert system.max_colors == len(system.colors)
    assert data["print"]["bleed"] == pytest.approx(3 / 25.4 * 300, abs=0.05)


def test_overrides_deep_merge_last():
    overrides = {
        "name": "Client X",
        "color": {"tokens": {"ink": {"hex": "#000000", "role": "ink"}}, "max_colors": 4},
        "typography": {"fonts": ["Söhne", "sans-serif"]},
    }
    data = derive_system(["#0F4C81", "#F5A623"], overrides=overrides)
    assert data["name"] == "Client X"
    assert _hex(data, "ink") == "#000000"
    assert data["color"]["max_colors"] == 4
    assert data["typography"]["fonts"] == ["Söhne", "sans-serif"]
    # Sibling derived values survive the merge.
    assert _hex(data, "primary") == "#0f4c81"
    assert data["typography"]["scale"] == derive_system(["#0F4C81", "#F5A623"])["typography"]["scale"]
    assert data["layout"]["grid"] == 8


def _swatch_doc(system):
    """An on-grid, on-token document exercising surface, text and accent."""
    body_size = next(s for s in system.type_scale if s >= 14)
    by_role = {}
    for t in system.colors:
        by_role.setdefault(t.role, t)
    return Document(
        width=320,
        height=320,
        shapes=[
            Shape("rect", {"x": "0", "y": "0", "width": "320", "height": "320",
                           "fill": by_role["surface"].hex}),
            Shape("rect", {"x": "24", "y": "240", "width": "48", "height": "48",
                           "fill": by_role["accent"].hex}),
            Shape("text", {"x": "24", "y": "48", "fill": by_role["text"].hex,
                           "font-family": system.fonts[0],
                           "font-size": f"{body_size:g}"},
                  text="Palette"),
        ],
    )


@pytest.mark.parametrize("seeds", SEED_SETS)
def test_yaml_round_trip_passes_own_audit(tmp_path, seeds):
    data = derive_system(seeds, name="Round trip")
    path = tmp_path / "system.yaml"
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")

    system = load_system(path)
    assert system.name == "Round trip"
    assert {t.name: t.hex for t in system.colors} == {
        name: spec["hex"] for name, spec in data["color"]["tokens"].items()
    }

    report = ComplianceEngine(system).audit(_swatch_doc(system))
    problems = [f for f in report.findings if f.severity in (Severity.ERROR, Severity.WARNING)]
    assert not problems, [f.message for f in problems]


def test_cli_palette_smoke(tmp_path, capsys):
    from designer.cli import main

    out = tmp_path / "client.yaml"
    code = main(["palette", "#0F4C81", "#F5A623", "--name", "client-x", "-o", str(out)])
    assert code == 0
    stdout = capsys.readouterr().out
    assert "#0f4c81" in stdout
    assert "primary" in stdout and ":1" in stdout  # roles + contrast ratios shown
    system = load_system(out)
    assert system.name == "client-x"

    assert main(["palette", "#0F4C81"]) == 2  # too few seeds

    code = main(["palette", "#0F4C81", "#F5A623", "--json"])
    assert code == 0
    import json

    parsed = json.loads(capsys.readouterr().out)
    assert parsed["color"]["tokens"]["accent"]["hex"] == "#f5a623"


def test_summary_lists_every_token():
    data = derive_system(["#0F4C81", "#F5A623", "#2E8B57"])
    summary = palette_summary(data)
    for name, spec in data["color"]["tokens"].items():
        assert name in summary
        assert spec["hex"] in summary


def test_public_export():
    import designer

    assert designer.derive_system is derive_system
