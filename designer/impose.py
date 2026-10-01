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

"""N-up imposition: step one print-ready page (business card, label,
flyer) across a press sheet with crop marks in the gutters, choosing
the sheet orientation and item rotation that fit the most copies.
Works on any single-page PDF with a TrimBox — the engine's own output
or a client's.
"""

from __future__ import annotations

from dataclasses import dataclass, asdict
from pathlib import Path

PT_PER_MM = 72 / 25.4

SHEETS_MM: dict[str, tuple[float, float]] = {
    "SRA3": (320, 450),
    "SRA4": (225, 320),
    "A3": (297, 420),
    "A4": (210, 297),
    "Letter": (215.9, 279.4),
    "Tabloid": (279.4, 431.8),
    "12x18": (304.8, 457.2),
    "13x19": (330.2, 482.6),
}


@dataclass
class Layout:
    sheet: str
    sheet_mm: tuple[float, float]
    item_mm: tuple[float, float]
    cols: int
    rows: int
    rotated: bool
    bleed_mm: float
    gap_mm: float

    @property
    def per_sheet(self) -> int:
        return self.cols * self.rows

    @property
    def usage(self) -> float:
        """Share of the sheet that becomes finished product."""
        w, h = self.item_mm
        return self.per_sheet * w * h / (self.sheet_mm[0] * self.sheet_mm[1])

    def sheets_for(self, quantity: int) -> int:
        return -(-int(quantity) // self.per_sheet) if self.per_sheet else 0

    def to_dict(self) -> dict:
        d = asdict(self)
        d.update(per_sheet=self.per_sheet, usage=round(self.usage, 3))
        return d


def plan(item_mm: tuple[float, float], sheet: str | tuple[float, float] = "SRA3",
         bleed_mm: float = 3.0, gap_mm: float | None = None,
         margin_mm: float = 10.0) -> Layout:
    """Best fit of an item on a sheet. ``gap_mm`` defaults to two bleeds
    (each item keeps its own bleed); the margin keeps clear of the
    press gripper and holds the outer crop marks."""
    name, sheet_mm = (sheet, SHEETS_MM[sheet]) if isinstance(sheet, str) else ("custom", sheet)
    gap = 2 * bleed_mm if gap_mm is None else gap_mm
    best: Layout | None = None
    for sw, sh in (sheet_mm, sheet_mm[::-1]):
        for rotated in (False, True):
            iw, ih = item_mm[::-1] if rotated else item_mm
            cols = int((sw - 2 * margin_mm + gap) // (iw + gap))
            rows = int((sh - 2 * margin_mm + gap) // (ih + gap))
            cand = Layout(name, (sw, sh), tuple(item_mm), max(cols, 0), max(rows, 0),
                          rotated, bleed_mm, gap)
            if best is None or cand.per_sheet > best.per_sheet:
                best = cand
    return best


def impose_pdf(source: str | Path, out: str | Path, sheet: str | tuple[float, float] = "SRA3",
               quantity: int | None = None, gap_mm: float | None = None,
               margin_mm: float = 10.0, marks: bool = True) -> Layout:
    """Write ``out``: the first page of ``source`` stepped across one
    sheet. Returns the Layout (copies per sheet, sheets for
    ``quantity``, sheet usage)."""
    from pypdf import PdfReader, PdfWriter
    from pypdf.generic import (ArrayObject, DecodedStreamObject, DictionaryObject,
                               FloatObject, NameObject, RectangleObject)

    reader = PdfReader(str(source))
    page = reader.pages[0]
    media, trim = page.mediabox, page.trimbox
    outer = page.bleedbox if "/BleedBox" in page else media
    bleed_pt = max(0.0, min(float(trim.left) - float(outer.left),
                            float(trim.bottom) - float(outer.bottom)))
    bleed_box = page.bleedbox if "/BleedBox" in page else RectangleObject(
        [float(trim.left) - bleed_pt, float(trim.bottom) - bleed_pt,
         float(trim.right) + bleed_pt, float(trim.top) + bleed_pt])
    item_mm = (float(trim.width) / PT_PER_MM, float(trim.height) / PT_PER_MM)
    layout = plan(item_mm, sheet, bleed_pt / PT_PER_MM, gap_mm, margin_mm)
    if layout.per_sheet == 0:
        raise ValueError(f"{item_mm[0]:.0f}x{item_mm[1]:.0f}mm does not fit on {layout.sheet}")

    writer = PdfWriter()
    sw, sh = (v * PT_PER_MM for v in layout.sheet_mm)
    sheet_page = writer.add_blank_page(width=sw, height=sh)

    form = DecodedStreamObject()
    contents = page.get_contents()
    form.set_data(contents.get_data() if contents is not None else b"")
    form.update({
        NameObject("/Type"): NameObject("/XObject"),
        NameObject("/Subtype"): NameObject("/Form"),
        NameObject("/BBox"): ArrayObject([FloatObject(float(v)) for v in bleed_box]),
        NameObject("/Resources"): page.get("/Resources", DictionaryObject()).clone(writer),
    })
    form_ref = writer._add_object(form)
    sheet_page[NameObject("/Resources")] = DictionaryObject({
        NameObject("/XObject"): DictionaryObject({NameObject("/Item"): form_ref}),
    })

    tw, th = float(trim.width), float(trim.height)
    cw, ch = (th, tw) if layout.rotated else (tw, th)
    gap = layout.gap_mm * PT_PER_MM
    grid_w = layout.cols * cw + (layout.cols - 1) * gap
    grid_h = layout.rows * ch + (layout.rows - 1) * gap
    x0, y0 = (sw - grid_w) / 2, (sh - grid_h) / 2
    ops: list[str] = []
    xs, ys = [], []
    for r in range(layout.rows):
        for c in range(layout.cols):
            x, y = x0 + c * (cw + gap), y0 + r * (ch + gap)
            xs += [x, x + cw]
            ys += [y, y + ch]
            # Map the source trim's lower-left to (x, y), rotating 90° if needed.
            if layout.rotated:
                m = (0, 1, -1, 0, x + cw + float(trim.bottom), y - float(trim.left))
            else:
                m = (1, 0, 0, 1, x - float(trim.left), y - float(trim.bottom))
            ops.append("q {} {} {} {} {:.3f} {:.3f} cm /Item Do Q".format(*m))
    if marks:
        # Crop marks only in the margin and on the cut lines' extensions,
        # 0.25pt registration, offset clear of the bleed.
        off, ln = layout.bleed_mm * PT_PER_MM + 2, 5 * PT_PER_MM
        ops.append("q 0.25 w 1 1 1 1 K")
        for x in sorted(set(round(v, 2) for v in xs)):
            ops.append(f"{x:.2f} {y0 - off:.2f} m {x:.2f} {y0 - off - ln:.2f} l S")
            ops.append(f"{x:.2f} {y0 + grid_h + off:.2f} m {x:.2f} {y0 + grid_h + off + ln:.2f} l S")
        for y in sorted(set(round(v, 2) for v in ys)):
            ops.append(f"{x0 - off:.2f} {y:.2f} m {x0 - off - ln:.2f} {y:.2f} l S")
            ops.append(f"{x0 + grid_w + off:.2f} {y:.2f} m {x0 + grid_w + off + ln:.2f} {y:.2f} l S")
        ops.append("Q")
    content = DecodedStreamObject()
    content.set_data("\n".join(ops).encode("latin-1", "replace"))
    sheet_page[NameObject("/Contents")] = writer._add_object(content)
    with open(out, "wb") as fh:
        writer.write(fh)
    return layout
