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

"""Smoke test for the end-to-end agency demo pipeline."""

import importlib.util
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module")
def demo():
    spec = importlib.util.spec_from_file_location(
        "agency_demo", REPO / "examples" / "agency_demo.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_demo_pipeline_end_to_end(demo, tmp_path):
    out = tmp_path / "drop"
    assert demo.main([
        "#0F4C81", "#F5A623",
        "--name", "Demo Trading (Pty) Ltd",
        "--tagline", "Import. Export. Delivered.",
        "--phone", "+27 11 555 0123",
        "--email", "hello@demotrading.co.za",
        "--address", "12 Harbour Rd, Durban",
        "-o", str(out),
    ]) == 0

    expected = {
        "system.yaml": 500,
        "logo.svg": 200,
        "logo.png": 1_000,
        "proofs/card-brand.png": 10_000,
        "proofs/flyer-brand.png": 10_000,
        "proofs/card-inverted.png": 10_000,
        "proofs/flyer-inverted.png": 10_000,
        "proofs/card-midtone.png": 10_000,
        "proofs/flyer-midtone.png": 10_000,
        "press/business-card-90x50.pdf": 100_000,
        "press/z-fold-a4.pdf": 100_000,
        "press/signboard-2000x800.pdf": 100_000,
        "brandbook.pdf": 100_000,
    }
    for rel, floor in expected.items():
        path = out / rel
        assert path.exists(), rel
        assert path.stat().st_size > floor, rel

    # The variations really differ (different palette treatments).
    brand = (out / "proofs/card-brand.png").read_bytes()
    inverted = (out / "proofs/card-inverted.png").read_bytes()
    midtone = (out / "proofs/card-midtone.png").read_bytes()
    assert brand != inverted and brand != midtone and inverted != midtone

    # Press files are multi-page where the deliverable is double-sided.
    card = (out / "press/business-card-90x50.pdf").read_bytes()
    board = (out / "press/signboard-2000x800.pdf").read_bytes()
    zfold = (out / "press/z-fold-a4.pdf").read_bytes()
    assert b"/Count 2" in card and b"/Count 2" in board
    assert b"/Count 1" in zfold
    for pdf in (card, board, zfold):
        assert b"/TrimBox" in pdf  # bleed + marks made it to press output

    # The system YAML round-trips with the custom formats on board.
    from designer.formats import get_format
    from designer.tokens import load_system

    system = load_system(out / "system.yaml")
    assert system.name == "Demo Trading (Pty) Ltd"
    spec = get_format("business-card-90x50", extra=system.formats)
    assert spec.width == pytest.approx(90 * 300 / 25.4, abs=0.5)


def test_demo_is_deterministic(demo, tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    for out in (a, b):
        demo.run(
            ["#0F4C81", "#F5A623"],
            {"business-name": "Det Co", "tagline": "T", "phone": "1",
             "email": "e@x", "address": "A"},
            out,
        )
    assert (a / "proofs/card-brand.png").read_bytes() == \
        (b / "proofs/card-brand.png").read_bytes()
    assert (a / "system.yaml").read_bytes() == (b / "system.yaml").read_bytes()


def test_demo_rejects_wrong_seed_count(demo):
    with pytest.raises(SystemExit):
        demo.main(["#0F4C81", "--name", "X", "-o", "nowhere"])
