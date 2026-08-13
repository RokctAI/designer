"""Deliverable formats: the catalog that takes the engine beyond logos.

A format is what distinguishes a poster from a logomark: exact canvas
size, safe margin, and the minimum text size that stays legible on the
target medium. Compliance against a format is enforced by the rules in
``designer.rules.format_rules`` when a format is passed to the engine.

Sizes are in px at their native/common resolution (small print formats
use 96dpi equivalents; large-format prints are press-native, recorded
in ``dpi``; the SVG is resolution-independent anyway). A design system
can add its own formats (tokens.py parses a ``formats:`` block into
FormatSpecs via ``format_from_dict``) which merge over this catalog.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class FormatSpec:
    name: str
    width: float
    height: float
    category: str  # brand | social | print | web | presentation | app
    margin: float = 0.05  # safe margin as a fraction of the short side
    min_text_size: float = 0.0  # px; 0 = no minimum
    description: str = ""
    # px density the width/height are expressed at. Sets the physical
    # page size of PDF output (and mark/fold geometry); screen formats
    # stay at CSS 96/inch.
    dpi: float = 96.0
    # Bleed override in px (same space as width/height); None = use the
    # design system's print.bleed.
    bleed: float | None = None
    # Fold geometry: panel widths left->right and panel heights
    # top->bottom (px, summing to width/height). Panel boundaries get
    # dashed fold marks on print PDFs when marks are drawn.
    panels: tuple[float, ...] = ()
    panels_y: tuple[float, ...] = ()


def mm_to_px(mm: float, dpi: float) -> float:
    return round(mm * dpi / 25.4, 1)


def format_from_dict(name: str, cfg: dict) -> FormatSpec:
    """Build a FormatSpec from a design-system YAML entry. ``unit: mm``
    expresses width/height/bleed/panels/min_text_size in millimetres,
    converted at the format's dpi; the default is px."""
    if not isinstance(cfg, dict) or "width" not in cfg or "height" not in cfg:
        raise ValueError(f"Custom format {name!r} needs width and height")
    dpi = float(cfg.get("dpi", 96.0))
    unit = str(cfg.get("unit", "px")).lower()
    if unit not in ("px", "mm"):
        raise ValueError(f"Custom format {name!r}: unit must be px or mm")

    def conv(value: float) -> float:
        return mm_to_px(float(value), dpi) if unit == "mm" else float(value)

    return FormatSpec(
        name=name,
        width=conv(cfg["width"]),
        height=conv(cfg["height"]),
        category=str(cfg.get("category", "print")),
        margin=float(cfg.get("margin", 0.05)),
        min_text_size=conv(cfg.get("min_text_size", 0.0)),
        description=str(cfg.get("description", "custom format")),
        dpi=dpi,
        bleed=conv(cfg["bleed"]) if "bleed" in cfg else None,
        panels=tuple(conv(p) for p in cfg.get("panels", []) or []),
        panels_y=tuple(conv(p) for p in cfg.get("panels_y", []) or []),
    )


_FORMATS: dict[str, FormatSpec] = {
    spec.name: spec
    for spec in [
        # Brand
        FormatSpec("logo", 1024, 1024, "brand", margin=0.0,
                   description="Square logomark master"),
        FormatSpec("icon", 512, 512, "brand", margin=0.0,
                   description="App/product icon master"),
        # Social
        FormatSpec("instagram-post", 1080, 1080, "social", min_text_size=24,
                   description="Instagram square post"),
        FormatSpec("instagram-story", 1080, 1920, "social", margin=0.08, min_text_size=28,
                   description="Instagram/WhatsApp story, 9:16"),
        FormatSpec("x-post", 1600, 900, "social", min_text_size=24,
                   description="X/Twitter landscape post"),
        FormatSpec("facebook-cover", 1640, 856, "social", margin=0.08, min_text_size=24,
                   description="Facebook page cover"),
        FormatSpec("linkedin-banner", 1584, 396, "social", margin=0.08, min_text_size=20,
                   description="LinkedIn profile banner"),
        FormatSpec("youtube-thumbnail", 1280, 720, "social", min_text_size=32,
                   description="YouTube thumbnail (large text reads at small size)"),
        # Print (96dpi equivalents)
        FormatSpec("a4-poster", 794, 1123, "print", min_text_size=12,
                   description="A4 portrait poster/flyer"),
        FormatSpec("a3-poster", 1123, 1587, "print", min_text_size=14,
                   description="A3 portrait poster"),
        FormatSpec("business-card", 336, 192, "print", margin=0.08, min_text_size=7,
                   description="EU business card 85x54mm"),
        # Large-format print at press-native 300dpi (mm x 300 / 25.4). Bleed is
        # not part of the canvas: the trim size is here, the bleed allowance
        # comes from the design system's print.bleed (px in this same 300dpi
        # space) and is checked/imposed by the print rules and the renderer.
        FormatSpec("a1-poster", 7016, 9933, "print", min_text_size=44, dpi=300,
                   description="A1 portrait poster 594x841mm at 300dpi"),
        FormatSpec("pullup-banner", 10039, 23622, "print", min_text_size=71, dpi=300,
                   description="Pull-up banner 850x2000mm at 300dpi (min text ~6mm; "
                               "cassette needs extra bottom bleed at imposition)"),
        # Large-format board: grand-format printers RIP at 100-150dpi,
        # and the viewing distance forgives it. 2000x800mm at 150dpi.
        FormatSpec("signboard-2000x800", mm_to_px(2000, 150), mm_to_px(800, 150),
                   "print", min_text_size=mm_to_px(25, 150), dpi=150,
                   description="Signboard 2000x800mm at 150dpi (min text ~25mm "
                               "for roadside legibility)"),
        # A4 landscape z-fold: three panels per side; the fold-in panel
        # is 2mm narrower so it nests without buckling (100/99/98mm).
        FormatSpec("z-fold-a4", mm_to_px(297, 300), mm_to_px(210, 300),
                   "print", margin=0.06, min_text_size=mm_to_px(2.5, 300), dpi=300,
                   panels=(mm_to_px(100, 300), mm_to_px(99, 300), mm_to_px(98, 300)),
                   description="A4 landscape z-fold, 3 panels 100/99/98mm "
                               "(fold-in panel narrower)"),
        # A4 presentation folder: two 220mm covers around a 5mm capacity
        # spine; the bottom 80mm strip folds up into the pocket.
        FormatSpec("corporate-folder-a4", mm_to_px(445, 300), mm_to_px(385, 300),
                   "print", margin=0.03, min_text_size=mm_to_px(2.5, 300), dpi=300,
                   panels=(mm_to_px(220, 300), mm_to_px(5, 300), mm_to_px(220, 300)),
                   panels_y=(mm_to_px(305, 300), mm_to_px(80, 300)),
                   description="A4 folder 445x385mm flat: 220mm covers, 5mm "
                               "capacity spine, 80mm glued pocket panel"),
        # Web
        FormatSpec("web-leaderboard", 728, 90, "web", margin=0.06, min_text_size=12,
                   description="Leaderboard display ad"),
        FormatSpec("web-mpu", 300, 250, "web", margin=0.06, min_text_size=12,
                   description="Medium rectangle display ad"),
        FormatSpec("og-image", 1200, 630, "web", min_text_size=24,
                   description="Open Graph / link preview image"),
        # Presentation
        FormatSpec("slide-16x9", 1920, 1080, "presentation", min_text_size=18,
                   description="Presentation slide, 16:9"),
        # App renditions produced by the Supacharge pipeline
        # (agent repo, lms/team/scripts/tutor_images.py). Photographic, no
        # text and full-bleed by design, so no margin or text minimum.
        FormatSpec("tutor-card", 1080, 1440, "app", margin=0.0,
                   description="Tutor discovery card render, 3:4 full-bleed photo"),
        FormatSpec("tutor-avatar", 512, 512, "app", margin=0.0,
                   description="Tutor profile/detail avatar render"),
        FormatSpec("tutor-avatar-small", 168, 168, "app", margin=0.0,
                   description="Session speaker bubble avatar render (56pt at 3x)"),
        FormatSpec("onboarding-slide", 1080, 1920, "app", margin=0.0,
                   description="Onboarding slide scene render, 9:16"),
        FormatSpec("onboarding-card", 1080, 1350, "app", margin=0.0,
                   description="Onboarding card scene render, 4:5"),
    ]
}


def get_format(name: str, extra: "list[FormatSpec] | tuple" = ()) -> FormatSpec:
    """Look up a format; ``extra`` (e.g. a design system's custom
    formats) is merged over the built-in catalog."""
    catalog = dict(_FORMATS)
    for spec in extra:
        catalog[spec.name] = spec
    try:
        return catalog[name]
    except KeyError:
        known = ", ".join(sorted(catalog))
        raise ValueError(f"Unknown format {name!r}. Known formats: {known}") from None


def all_formats(extra: "list[FormatSpec] | tuple" = ()) -> list[FormatSpec]:
    catalog = dict(_FORMATS)
    for spec in extra:
        catalog[spec.name] = spec
    return sorted(catalog.values(), key=lambda f: (f.category, f.name))
