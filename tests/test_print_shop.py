import base64
import io

import pytest
from PIL import Image

from designer.cli import main
from designer.formats import get_format
from designer.hotfolder import process_folder
from designer.impose import impose_pdf, plan
from designer.preflight import preflight_pdf
from designer.production import Job, job_ticket, proof
from designer.render import render_pdf
from designer.svg import Document, Shape


def _card():
    return Document(width=336, height=192, shapes=[
        Shape("rect", {"x": "-12", "y": "-12", "width": "360", "height": "216", "fill": "#e5007e"}),
        Shape("circle", {"cx": "60", "cy": "96", "r": "40", "fill": "#00a3e0"}),
    ])


def _good_pdf(tmp_path):
    return render_pdf(_card(), tmp_path / "card.pdf", cmyk=True,
                      format=get_format("business-card"), bleed=11.34, marks=True)


def _bad_pdf(tmp_path):
    buf = io.BytesIO()
    Image.new("RGB", (100, 60), "#3366cc").save(buf, "PNG")
    href = "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()
    doc = Document(width=336, height=192, shapes=[
        Shape("image", {"x": "0", "y": "0", "width": "336", "height": "192", "href": href}),
        Shape("text", {"x": "10", "y": "50", "font-size": "20", "fill": "#123456",
                       "font-family": "DejaVu Sans"}, text="Hi"),
    ])
    return render_pdf(doc, tmp_path / "bad.pdf", embed_fonts=False)


def test_preflight_passes_engine_output(tmp_path):
    report = preflight_pdf(_good_pdf(tmp_path))
    assert not report.blocked and report.open_count == 0


def test_preflight_catches_client_pdf_problems(tmp_path):
    report = preflight_pdf(_bad_pdf(tmp_path))
    rules = {f.rule for f in report.findings}
    assert report.blocked
    assert {"preflight.fonts", "preflight.image_ppi", "preflight.rgb", "preflight.bleed"} <= rules


def test_plan_picks_best_fit_and_counts_sheets():
    layout = plan((90, 50), "SRA3", bleed_mm=3)
    assert layout.per_sheet >= 21
    assert layout.sheets_for(500) == -(-500 // layout.per_sheet)
    assert 0 < layout.usage < 1


def test_impose_writes_sheet(tmp_path):
    out = tmp_path / "sheet.pdf"
    layout = impose_pdf(_good_pdf(tmp_path), out, sheet="SRA3")
    from pypdf import PdfReader

    page = PdfReader(str(out)).pages[0]
    assert round(float(page.mediabox.width) / (72 / 25.4)) in (320, 450)
    assert page.get_contents().get_data().count(b"/Item Do") == layout.per_sheet


def test_impose_rejects_item_bigger_than_sheet(tmp_path):
    with pytest.raises(ValueError):
        impose_pdf(_good_pdf(tmp_path), tmp_path / "x.pdf", sheet=(60, 40))


def test_ticket_and_proof(tmp_path):
    job = Job(job_no="J-1", client="Acme", quantity=500, stock="350gsm")
    t = job_ticket(_card(), tmp_path / "t.pdf", job)
    p = proof([_card(), _card()], tmp_path / "p.pdf", job, approve_url="https://x/review/abc")
    from pypdf import PdfReader

    assert len(PdfReader(str(p)).pages) == 2
    assert t.stat().st_size > 1000
    # Proofs are raster-only artwork: no vector copy of the design leaks out.
    assert not preflight_pdf(p).blocked


def test_hotfolder_sorts_pass_and_fail(tmp_path):
    inbox, outbox = tmp_path / "in", tmp_path / "out"
    inbox.mkdir()
    _good_pdf(tmp_path).rename(inbox / "good.pdf")
    _bad_pdf(tmp_path).rename(inbox / "bad.pdf")
    results = {r.source: r for r in process_folder(inbox, outbox, sheet="SRA3")}
    assert results["good.pdf"].passed and not results["bad.pdf"].passed
    assert (inbox / "done" / "good.pdf").exists() and (inbox / "failed" / "bad.pdf").exists()
    assert (outbox / "good.imposed.pdf").exists() and (outbox / "bad.preflight.txt").exists()


def test_cli_preflight_exit_codes(tmp_path):
    assert main(["preflight", str(_good_pdf(tmp_path))]) == 0
    assert main(["preflight", str(_bad_pdf(tmp_path))]) == 1
