"""Deliverable formats: the catalog that takes the engine beyond logos.

A format is what distinguishes a poster from a logomark: exact canvas
size, safe margin, and the minimum text size that stays legible on the
target medium. Compliance against a format is enforced by the rules in
``designer.rules.format_rules`` when a format is passed to the engine.

Sizes are in px at their native/common resolution (small print formats
use 96dpi equivalents; large-format expo prints are press-native 300dpi,
as their descriptions say; the SVG is resolution-independent anyway).
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
        FormatSpec("a1-poster", 7016, 9933, "print", min_text_size=44,
                   description="A1 portrait poster 594x841mm at 300dpi"),
        FormatSpec("pullup-banner", 10039, 23622, "print", min_text_size=71,
                   description="Pull-up banner 850x2000mm at 300dpi (min text ~6mm; "
                               "cassette needs extra bottom bleed at imposition)"),
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


def get_format(name: str) -> FormatSpec:
    try:
        return _FORMATS[name]
    except KeyError:
        known = ", ".join(sorted(_FORMATS))
        raise ValueError(f"Unknown format {name!r}. Known formats: {known}") from None


def all_formats() -> list[FormatSpec]:
    return sorted(_FORMATS.values(), key=lambda f: (f.category, f.name))
