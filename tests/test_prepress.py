import base64
import io

from PIL import Image

from designer.engine import ComplianceEngine
from designer.formats import get_format
from designer.render import render_pdf
from designer.svg import Document, Shape
from designer.tokens import load_system
from tests.test_print_pdf import pdf_streams


def _doc(*shapes):
    return Document(width=336, height=192, shapes=list(shapes))


def _engine():
    return ComplianceEngine(load_system(None), format="business-card")


def test_rich_black_small_text_warned_and_fixed():
    text = Shape("text", {"x": "10", "y": "50", "font-size": "12", "fill": "#0a0f14"}, text="Hi")
    doc = _doc(text)
    found = [f for f in _engine().audit(doc).findings if f.rule == "print.rich_black"]
    assert found
    _engine().comply(doc)  # palette snap may also run; either way no rich black remains
    assert not [f for f in _engine().audit(doc).findings if f.rule == "print.rich_black"]


def test_large_rich_black_and_pure_black_pass():
    big = Shape("text", {"x": "10", "y": "80", "font-size": "60", "fill": "#0a0f14"}, text="Hi")
    pure = Shape("text", {"x": "10", "y": "150", "font-size": "10", "fill": "#000000"}, text="x")
    found = [f for f in _engine().audit(_doc(big, pure)).findings if f.rule == "print.rich_black"]
    assert not found


def _png(w, h):
    buf = io.BytesIO()
    Image.new("RGB", (w, h), "#808080").save(buf, "PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()


def test_low_res_image_warned():
    # 336px card at 96dpi = 3.5in; a 336px image across it is 96 ppi.
    low = Shape("image", {"x": "0", "y": "0", "width": "336", "height": "192", "href": _png(336, 192)})
    found = [f for f in _engine().audit(_doc(low)).findings if f.rule == "print.image_ppi"]
    assert found and "96 ppi" in found[0].message
    ok = Shape("image", {"x": "0", "y": "0", "width": "336", "height": "192", "href": _png(1050, 600)})
    assert not [f for f in _engine().audit(_doc(ok)).findings if f.rule == "print.image_ppi"]


def test_black_overprints_in_cmyk_pdf(tmp_path):
    doc = _doc(Shape("rect", {"x": "0", "y": "0", "width": "50", "height": "50", "fill": "#000000"}),
               Shape("rect", {"x": "60", "y": "0", "width": "50", "height": "50", "fill": "#ff0000"}))
    out = render_pdf(doc, tmp_path / "a.pdf", cmyk=True, format=get_format("business-card"))
    data = out.read_bytes()
    ops = pdf_streams(data)
    assert b"/op true" in data and b"/GSop1 gs" in ops and b"/GSop0 gs" in ops
    off = render_pdf(doc, tmp_path / "b.pdf", cmyk=True, overprint_black=False)
    assert b"/GSop1" not in off.read_bytes()
