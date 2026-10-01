from designer.cli import main
from designer.construct import construct, with_construction
from designer.svg import parse_svg

SVG = """<svg xmlns="http://www.w3.org/2000/svg" width="200" height="100" viewBox="0 0 200 100">
<circle cx="50" cy="50" r="40" fill="#123456"/>
<circle cx="170" cy="50" r="20" fill="#123456"/>
</svg>"""


def _doc(tmp_path):
    f = tmp_path / "a.svg"
    f.write_text(SVG)
    return parse_svg(f)


def test_finds_circles_and_ratio(tmp_path):
    con = construct(_doc(tmp_path))
    radii = sorted(round(c.r) for c in con.circles)
    assert any(abs(r - 40) <= 2 for r in radii)
    assert any(abs(r - 20) <= 2 for r in radii)
    assert any(name == "1:2" for *_, name in con.ratios)


def test_toggle_off_leaves_doc_untouched(tmp_path):
    doc = _doc(tmp_path)
    assert with_construction(doc, False) is doc
    assert len(with_construction(doc, True).shapes) > len(doc.shapes)


def test_cli_flag_default_off(tmp_path):
    src = tmp_path / "a.svg"
    src.write_text(SVG)
    off, on = tmp_path / "off.svg", tmp_path / "on.svg"
    assert main(["render", str(src), "-o", str(off)]) == 0
    assert main(["render", str(src), "-o", str(on), "--construction"]) == 0
    assert "#e5007e" not in off.read_text().lower()
    assert "#e5007e" in on.read_text().lower()


def test_off_centre_artwork_is_warned(tmp_path):
    f = tmp_path / "b.svg"
    f.write_text(SVG.replace('cx="170"', 'cx="190"').replace('cx="50"', 'cx="140"'))
    con = construct(parse_svg(f))
    warns = con.warnings(200, 100)
    assert any("canvas centre" in w for w in warns)
    assert not any("canvas centre" in w for w in construct(_doc(tmp_path)).warnings(200, 100))
