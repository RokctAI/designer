"""Template rendering: slot-marked SVG + captured data -> finished design.

This is the deterministic path — no image generation, no model call.
A designer authors an SVG once with slot markers; the renderer fills it
with captured content, fits text to its box using real font metrics,
drops size-inappropriate slots, flows repeated items into a grid, and
hands the result to the compliance engine. Sub-second, same output every
time, which is what makes on-the-spot use viable.

Slot markers (plain attributes, so templates stay valid SVG):
  data-slot="headline"        fill this element from the data
  data-token="advertiser-1"   fill color comes from the caller's palette
  data-fit="shrink"           step down the type scale until the text fits
  data-optional="true"        may be dropped (see data-min-unit-width)
  data-min-unit-width="400"   drop this slot below this canvas width
  data-freed-to="headline"    give the dropped slot's box to another slot
  data-region="items"         flow repeated item cells into this rectangle
  data-min-cell="140"         refuse to render cells smaller than this
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field

from designer.fonts import fit_size, is_bold, measure
from designer.svg import Document, Shape
from designer.tokens import DesignSystem


class TemplateError(ValueError):
    """The template cannot render this content — always with a message
    the UI can show the user directly."""


class UnitTooSmall(TemplateError):
    """Too many items for the target size. Carries the numbers the UI
    needs to offer an upgrade."""

    def __init__(self, item_count: int, fitting: int, cell: float, min_cell: float):
        self.item_count = item_count
        self.fitting = fitting
        self.cell = cell
        self.min_cell = min_cell
        super().__init__(
            f"{item_count} items do not fit this size: cells would be "
            f"{cell:.0f}px, below the {min_cell:.0f}px legibility floor. "
            f"This size holds about {fitting}. Use a larger unit or fewer items."
        )


@dataclass
class Item:
    """One cell of a composite (multi-product) design."""

    title: str = ""
    price: str = ""
    badge: str = ""
    image_href: str | None = None


@dataclass
class TemplateData:
    """Everything a render needs besides the template itself."""

    fields: dict[str, str] = field(default_factory=dict)
    items: list[Item] = field(default_factory=list)
    # Ordered palette: data-token="advertiser-1" takes palette[0].
    palette: list[str] = field(default_factory=list)
    images: dict[str, str] = field(default_factory=dict)  # slot -> href


def _slot(shape: Shape) -> str | None:
    return shape.attrs.get("data-slot")


def _flag(shape: Shape, name: str) -> bool:
    return str(shape.attrs.get(name, "")).lower() in ("true", "1", "yes")


def _num(shape: Shape, name: str) -> float | None:
    raw = shape.attrs.get(name)
    if raw is None:
        return None
    try:
        return float(raw)
    except ValueError:
        return None


def _box(shape: Shape) -> tuple[float, float, float, float] | None:
    x, y = shape.numeric("x"), shape.numeric("y")
    w, h = shape.numeric("width"), shape.numeric("height")
    if None in (x, y, w, h):
        return None
    return (x, y, w, h)


def render(
    template: Document,
    data: TemplateData,
    system: DesignSystem,
    cell_template: Document | None = None,
) -> Document:
    """Fill a template. Returns a new Document; the template is not
    modified, so one template serves many renders."""
    doc = copy.deepcopy(template)

    _apply_palette(doc, data.palette)
    freed = _drop_optional_slots(doc)
    _grow_beneficiaries(doc, freed)
    _fill_images(doc, data)
    _fill_text(doc, data, system)

    region = _find_region(doc)
    if region is not None:
        if cell_template is None:
            raise TemplateError(
                "this template has an items region but no cell template was provided"
            )
        _flow_items(doc, region, cell_template, data, system)
    elif data.items:
        raise TemplateError("items were supplied but this template has no items region")

    # Marker attributes are authoring metadata, not output.
    for shape in doc.shapes:
        for key in list(shape.attrs):
            if key.startswith("data-"):
                del shape.attrs[key]
    return doc


# ------------------------------------------------------------- palette


def _apply_palette(doc: Document, palette: list[str]) -> None:
    """`data-token="advertiser-N"` fills take the caller's Nth color.
    Colors from any source (extracted, hand-picked, publication default)
    still face the compliance pass afterwards, so contrast is enforced
    regardless of where they came from."""
    for shape in doc.shapes:
        token = shape.attrs.get("data-token")
        if not token:
            continue
        if token.startswith("advertiser-"):
            try:
                index = int(token.split("-", 1)[1]) - 1
            except ValueError:
                continue
            if 0 <= index < len(palette):
                shape.set("fill", palette[index])
        # Unresolvable tokens keep the template's own fill.


# ------------------------------------------------------- optional slots


def _drop_optional_slots(doc: Document) -> dict[str, tuple[float, float, float, float]]:
    """Remove slots that don't belong at this size, returning the boxes
    they freed keyed by their declared beneficiary.

    This is the "small ads lose the logo, not the message" rule: below a
    declared width the logo is dropped outright rather than squeezing
    the text that actually sells."""
    freed: dict[str, tuple[float, float, float, float]] = {}
    survivors = []
    for shape in doc.shapes:
        min_width = _num(shape, "data-min-unit-width")
        if _flag(shape, "data-optional") and min_width is not None and doc.width < min_width:
            beneficiary = shape.attrs.get("data-freed-to")
            box = _box(shape)
            if beneficiary and box:
                freed[beneficiary] = box
            continue
        survivors.append(shape)
    doc.shapes = survivors
    return freed


def _grow_beneficiaries(doc: Document, freed: dict) -> None:
    """Extend a slot's box to absorb a dropped neighbour's rectangle."""
    for shape in doc.shapes:
        slot = _slot(shape)
        if slot not in freed:
            continue
        gained = freed[slot]
        gx, gy, gw, gh = gained
        if shape.tag == "text":
            # Text keeps its anchor; only its fitting width grows.
            width = _num(shape, "data-fit-width")
            existing = width if width is not None else 0.0
            shape.set("data-fit-width", f"{max(existing, gx + gw - (shape.numeric('x') or 0)):g}")
            continue
        box = _box(shape)
        if box is None:
            continue
        x, y, w, h = box
        nx, ny = min(x, gx), min(y, gy)
        shape.set("x", f"{nx:g}")
        shape.set("y", f"{ny:g}")
        shape.set("width", f"{max(x + w, gx + gw) - nx:g}")
        shape.set("height", f"{max(y + h, gy + gh) - ny:g}")


# ---------------------------------------------------------- filling


def _fill_images(doc: Document, data: TemplateData) -> None:
    survivors = []
    for shape in doc.shapes:
        slot = _slot(shape)
        if shape.tag == "image" and slot:
            href = data.images.get(slot)
            if not href:
                continue  # nothing captured for this slot: leave it out
            shape.set("href", href)
            shape.set("preserveAspectRatio", "xMidYMid slice")  # center-crop
        survivors.append(shape)
    doc.shapes = survivors


def _fill_text(doc: Document, data: TemplateData, system: DesignSystem) -> None:
    survivors = []
    for shape in doc.shapes:
        slot = _slot(shape)
        if shape.tag != "text" or not slot:
            survivors.append(shape)
            continue
        value = (data.fields.get(slot) or "").strip()
        if not value:
            continue  # empty slots leave no placeholder behind
        shape.text = value
        _fit_text(shape, system)
        survivors.append(shape)
    doc.shapes = survivors


def _fit_text(shape: Shape, system: DesignSystem) -> None:
    """Step down the type scale until the line fits its declared box.

    Uses real glyph metrics — estimating from character counts is off by
    ~25%, which is the difference between fitting and overflowing.
    """
    if shape.attrs.get("data-fit") != "shrink":
        return
    max_width = _num(shape, "data-fit-width")
    if max_width is None:
        return
    max_height = _num(shape, "data-fit-height") or float("inf")
    family = shape.get("font-family")
    bold = is_bold(shape.get("font-weight"))
    current = shape.numeric("font-size") or 16.0
    scale = [s for s in system.type_scale if s <= current] or [current]
    size = fit_size(shape.text, family, max_width, max_height, scale, bold=bold)
    if size is None:
        # Even the smallest step overflows: keep it and let the caller
        # decide (the compliance report will carry the overflow).
        size = min(scale)
        shape.set("data-overflow", "true")
    shape.set("font-size", f"{size:g}")


# ------------------------------------------------------ composite grid


def _find_region(doc: Document) -> Shape | None:
    for shape in doc.shapes:
        if shape.attrs.get("data-region") == "items":
            return shape
    return None


def grid_for(
    count: int,
    width: float,
    height: float,
    min_cell: float,
    gutter: float,
    target_aspect: float = 1.0,
):
    """Column/row split that best fills the region for ``count`` items.

    Slots whose shape matches the cell template's aspect are preferred:
    cells keep their proportions when drawn, so a mismatched slot leaves
    visible gaps in the block.
    """
    if count <= 0:
        return 0, 0, 0.0, 0.0
    best = None
    max_cols = max(1, int((width + gutter) // max(1.0, min_cell + gutter)))
    for cols in range(1, min(count, max_cols) + 1):
        rows = -(-count // cols)  # ceil
        cell_w = (width - gutter * (cols - 1)) / cols
        cell_h = (height - gutter * (rows - 1)) / rows
        if cell_w <= 0 or cell_h <= 0:
            continue
        # Drawn size after preserving the template's aspect.
        drawn = min(cell_w / target_aspect, cell_h)
        fill = (drawn * target_aspect * drawn) / max(1e-6, cell_w * cell_h)
        score = (round(min(cell_w, cell_h), 1), round(fill, 3))
        if best is None or score > best[0]:
            best = (score, cols, rows, cell_w, cell_h)
    if best is None:
        return 0, 0, 0.0, 0.0
    _, cols, rows, cell_w, cell_h = best
    return cols, rows, cell_w, cell_h


def _flow_items(
    doc: Document,
    region: Shape,
    cell_template: Document,
    data: TemplateData,
    system: DesignSystem,
) -> None:
    box = _box(region)
    if box is None:
        raise TemplateError("items region must declare x/y/width/height")
    rx, ry, rw, rh = box
    min_cell = _num(region, "data-min-cell") or 100.0
    gutter = _num(region, "data-gutter") or max(4.0, system.grid)
    count = len(data.items)

    doc.shapes = [s for s in doc.shapes if s is not region]
    if count == 0:
        return

    aspect = (
        cell_template.width / cell_template.height
        if cell_template.height
        else 1.0
    )
    cols, rows, cell_w, cell_h = grid_for(count, rw, rh, min_cell, gutter, aspect)
    if cols == 0 or min(cell_w, cell_h) < min_cell:
        fitting = _max_fitting(rw, rh, min_cell, gutter)
        raise UnitTooSmall(count, fitting, min(cell_w, cell_h) if cols else 0.0, min_cell)

    for index, item in enumerate(data.items):
        col, row = index % cols, index // cols
        # Center a short final row so the block reads as deliberate.
        in_row = min(cols, count - row * cols)
        row_width = in_row * cell_w + (in_row - 1) * gutter
        offset = (rw - row_width) / 2 if in_row < cols else 0.0
        ox = rx + offset + col * (cell_w + gutter)
        oy = ry + row * (cell_h + gutter)
        doc.shapes.extend(_render_cell(cell_template, item, ox, oy, cell_w, cell_h, system))


def _max_fitting(width: float, height: float, min_cell: float, gutter: float) -> int:
    cols = max(1, int((width + gutter) // (min_cell + gutter)))
    rows = max(1, int((height + gutter) // (min_cell + gutter)))
    return cols * rows


def _render_cell(
    cell_template: Document,
    item: Item,
    ox: float,
    oy: float,
    cw: float,
    ch: float,
    system: DesignSystem,
) -> list[Shape]:
    """Instantiate the cell template into one grid position."""
    from designer.transform import affine_document

    cell = copy.deepcopy(cell_template)
    scale = min(cw / cell.width, ch / cell.height) if cell.width and cell.height else 1.0
    # Center the drawn cell in its slot so partial rows and aspect
    # mismatches read as deliberate spacing, not sloppy alignment.
    dx = ox + (cw - cell.width * scale) / 2
    dy = oy + (ch - cell.height * scale) / 2
    affine_document(cell, scale, dx, dy)
    cell.width, cell.height = cw, ch

    fields = {"title": item.title, "price": item.price, "badge": item.badge}
    images = {"photo": item.image_href} if item.image_href else {}

    survivors: list[Shape] = []
    for shape in cell.shapes:
        slot = _slot(shape)
        if slot in fields:
            value = (fields[slot] or "").strip()
            if not value:
                continue
            if shape.tag == "text":
                shape.text = value
                _fit_text(shape, system)
            survivors.append(shape)
            continue
        if slot == "photo":
            if not images.get("photo"):
                continue
            shape.set("href", images["photo"])
            shape.set("preserveAspectRatio", "xMidYMid slice")
            survivors.append(shape)
            continue
        if slot == "badge-shape" and not (item.badge or "").strip():
            continue  # no badge, no badge backing shape
        survivors.append(shape)
    return survivors
