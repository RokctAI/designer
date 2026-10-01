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

"""Print-shop paperwork generated from the artwork itself:

- ``job_ticket``: one A4 page for the press operator — size, stock,
  quantity, colours, fonts, imposition, preflight result and a preview.
- ``proof``: a watermarked, low-resolution client proof with a sign-off
  block. Deliberately raster at screen resolution so a proof can't be
  sent to plate by mistake.
"""

from __future__ import annotations

import base64
import datetime
import io
from dataclasses import dataclass, field
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from designer.color import parse_color
from designer.fonts import first_family, resolve_with_fallback
from designer.render import render_pdf, render_png
from designer.svg import Document, Shape

A4 = (794, 1123)  # px at 96dpi
INK = "#1a1a1a"
MUTED = "#6b6b6b"
FONT = "DejaVu Sans"


@dataclass
class Job:
    """What a job ticket / proof says about the job. Every field optional."""

    job_no: str = ""
    client: str = ""
    title: str = ""
    quantity: int | None = None
    stock: str = ""
    finish: str = ""
    size: str = ""
    due: str = ""
    notes: str = ""
    extra: dict = field(default_factory=dict)


def colours_in(doc: Document) -> list[str]:
    seen: list[str] = []
    for shape in doc.shapes:
        for attr in ("fill", "stroke"):
            rgb = parse_color(shape.get(attr) or "")
            if rgb:
                hx = "#%02x%02x%02x" % rgb
                if hx not in seen:
                    seen.append(hx)
    return seen


def fonts_in(doc: Document) -> list[str]:
    fonts: list[str] = []
    for shape in doc.shapes:
        if shape.tag == "text" and shape.text:
            family = first_family(shape.get("font-family"))
            if family and family not in fonts:
                fonts.append(family)
    return fonts


def _data_uri(img: Image.Image) -> str:
    buf = io.BytesIO()
    img.convert("RGB").save(buf, "PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()


def _fit(doc: Document, box_w: float, box_h: float) -> tuple[float, float]:
    scale = min(box_w / doc.width, box_h / doc.height)
    return doc.width * scale, doc.height * scale


class _Page:
    def __init__(self, size=A4):
        self.w, self.h = size
        self.shapes: list[Shape] = []

    def text(self, x, y, msg, size=12, color=INK, weight="normal", anchor="start"):
        self.shapes.append(Shape("text", {
            "x": f"{x:.1f}", "y": f"{y:.1f}", "font-size": f"{size:g}", "fill": color,
            "font-family": FONT, "font-weight": weight, "text-anchor": anchor}, text=str(msg)))

    def rect(self, x, y, w, h, fill="none", stroke=None, width=1.0):
        attrs = {"x": f"{x:.1f}", "y": f"{y:.1f}", "width": f"{w:.1f}", "height": f"{h:.1f}",
                 "fill": fill}
        if stroke:
            attrs.update({"stroke": stroke, "stroke-width": f"{width:g}"})
        self.shapes.append(Shape("rect", attrs))

    def line(self, x1, y1, x2, y2, color="#d0d0d0", width=1.0):
        self.shapes.append(Shape("line", {"x1": f"{x1:.1f}", "y1": f"{y1:.1f}", "x2": f"{x2:.1f}",
                                          "y2": f"{y2:.1f}", "stroke": color,
                                          "stroke-width": f"{width:g}"}))

    def image(self, x, y, w, h, img: Image.Image):
        self.shapes.append(Shape("image", {"x": f"{x:.1f}", "y": f"{y:.1f}", "width": f"{w:.1f}",
                                           "height": f"{h:.1f}", "href": _data_uri(img)}))

    def doc(self) -> Document:
        return Document(width=self.w, height=self.h, shapes=self.shapes)


def job_ticket(doc: Document, out: str | Path, job: Job | None = None,
               report=None, layout=None) -> Path:
    """One-page A4 job ticket PDF. ``report`` is an audit/preflight
    Report; ``layout`` an impose.Layout."""
    job = job or Job()
    p = _Page()
    m = 48
    p.text(m, 64, "JOB TICKET", 22, weight="bold")
    p.text(p.w - m, 64, job.job_no or datetime.date.today().isoformat(), 14, MUTED, anchor="end")
    p.line(m, 80, p.w - m, 80, INK, 1.5)

    rows = [
        ("Client", job.client), ("Job", job.title or (Path(doc.source).name if doc.source else "")),
        ("Size", job.size or f"{doc.width:g} x {doc.height:g} px"),
        ("Quantity", f"{job.quantity:,}" if job.quantity else ""), ("Stock", job.stock),
        ("Finish", job.finish), ("Due", job.due),
    ]
    if layout is not None:
        rows.append(("Imposition", f"{layout.cols} x {layout.rows} = {layout.per_sheet} up on "
                     f"{layout.sheet}" + (f", {layout.sheets_for(job.quantity)} sheets"
                                          if job.quantity else "")
                     + f", {layout.usage * 100:.0f}% sheet used"))
    rows += [(k, str(v)) for k, v in job.extra.items()]
    y = 112
    for label, value in rows:
        if not value:
            continue
        p.text(m, y, label, 11, MUTED)
        p.text(m + 120, y, value, 12)
        y += 24

    y += 8
    p.text(m, y, "Colours", 11, MUTED)
    x = m + 120
    for hx in colours_in(doc)[:12]:
        p.rect(x, y - 12, 16, 16, fill=hx, stroke="#999999", width=0.5)
        p.text(x + 22, y, hx, 10)
        x += 92
        if x > p.w - m - 80:
            x, y = m + 120, y + 24
    y += 28
    p.text(m, y, "Fonts", 11, MUTED)
    p.text(m + 120, y, ", ".join(fonts_in(doc)) or "none (outlined or no text)", 12)
    y += 32

    if report is not None:
        verdict = "FAILED" if report.blocked else ("PASSED" if not report.open_count else
                                                   "PASSED WITH WARNINGS")
        color = "#c0392b" if report.blocked else ("#d35400" if report.open_count else "#1e8449")
        p.text(m, y, "Preflight", 11, MUTED)
        p.text(m + 120, y, f"{verdict}  ({report.score}/100)", 12, color, weight="bold")
        y += 22
        for f in [f for f in report.findings if not f.fixed][:8]:
            mark = "BLOCKER" if f.blocking else f.severity.value.upper()
            p.text(m + 120, y, f"{mark}: {f.message[:92]}", 9, MUTED)
            y += 16
        y += 12

    if job.notes:
        p.text(m, y, "Notes", 11, MUTED)
        p.text(m + 120, y, job.notes[:100], 11)
        y += 28

    box_top, box_h = max(y, 560), p.h - max(y, 560) - 96
    pw, ph = _fit(doc, p.w - 2 * m, box_h)
    preview = render_png(doc, width=max(1, int(pw * 2)))
    px = (p.w - pw) / 2
    p.rect(px - 1, box_top - 1, pw + 2, ph + 2, stroke="#d0d0d0")
    p.image(px, box_top, pw, ph, preview)

    p.line(m, p.h - 72, p.w - m, p.h - 72)
    p.text(m, p.h - 48, "Operator ________________    Checked ________________    "
           "Date ____________", 10, MUTED)
    render_pdf(p.doc(), out, embed_fonts=True)
    return Path(out)


def _watermark(img: Image.Image, label: str) -> Image.Image:
    img = img.convert("RGBA")
    w, h = img.size
    path, _ = resolve_with_fallback(FONT, bold=True)
    size = max(12, int(min(w, h) / 9))
    try:
        font = ImageFont.truetype(path, size) if path else ImageFont.load_default()
    except OSError:
        font = ImageFont.load_default()
    tile = Image.new("RGBA", (w * 2, h * 2), (0, 0, 0, 0))
    d = ImageDraw.Draw(tile)
    step_y = size * 3
    for i, yy in enumerate(range(0, h * 2, step_y)):
        offset = (i % 2) * size * 3
        for xx in range(-offset, w * 2, int(size * len(label) * 0.75)):
            d.text((xx, yy), label, font=font, fill=(200, 30, 30, 70))
    tile = tile.rotate(30, resample=Image.BICUBIC)
    tile = tile.crop((w // 2, h // 2, w // 2 + w, h // 2 + h))
    return Image.alpha_composite(img, tile).convert("RGB")


def proof(doc: Document | list[Document], out: str | Path, job: Job | None = None,
          approve_url: str = "", proof_dpi: float = 96.0,
          watermark: str = "PROOF - NOT FOR PRINT") -> Path:
    """Client proof PDF: one A4 page per design, watermarked raster at
    ``proof_dpi`` with job details and a sign-off block (and the online
    approval link when given)."""
    job = job or Job()
    docs = doc if isinstance(doc, (list, tuple)) else [doc]
    pages = []
    for n, d in enumerate(docs, 1):
        p = _Page()
        m = 48
        p.text(m, 64, "PROOF FOR APPROVAL", 20, weight="bold")
        p.text(p.w - m, 64, f"{n} of {len(docs)}", 12, MUTED, anchor="end")
        p.line(m, 80, p.w - m, 80, INK, 1.5)
        meta = [v for v in (job.client, job.title, job.job_no,
                            f"Qty {job.quantity:,}" if job.quantity else "", job.stock,
                            datetime.date.today().isoformat()) if v]
        p.text(m, 104, "   ·   ".join(meta), 11, MUTED)
        box_top, box_h = 128, p.h - 128 - 230
        pw, ph = _fit(d, p.w - 2 * m, box_h)
        raster = render_png(d, dpi=proof_dpi)
        p.rect((p.w - pw) / 2 - 1, box_top - 1, pw + 2, ph + 2, stroke="#d0d0d0")
        p.image((p.w - pw) / 2, box_top, pw, ph, _watermark(raster, watermark))
        y = p.h - 200
        p.text(m, y, "Please check spelling, numbers, contact details, colours and layout.", 10, MUTED)
        p.text(m, y + 16, "Colours on screen or office printers differ from the final press "
               "print. Once approved, changes are chargeable.", 10, MUTED)
        p.rect(m, y + 36, 14, 14, stroke=INK)
        p.text(m + 22, y + 48, "Approved as is", 12)
        p.rect(m + 220, y + 36, 14, 14, stroke=INK)
        p.text(m + 242, y + 48, "Approved with changes", 12)
        p.rect(m + 470, y + 36, 14, 14, stroke=INK)
        p.text(m + 492, y + 48, "New proof needed", 12)
        p.text(m, y + 100, "Name ______________________   Signature ______________________"
               "   Date ____________", 11)
        if approve_url:
            p.text(m, y + 140, "Approve online: " + approve_url, 10, "#1f5fbf")
        pages.append(p.doc())
    render_pdf(pages, out, embed_fonts=True)
    return Path(out)
