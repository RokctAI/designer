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

"""End-to-end agency workflow: seed colours + business details in,
a full identity drop out.

    python examples/agency_demo.py "#0F4C81" "#F5A623" \
        --name "Demo Trading (Pty) Ltd" -o demo-out/

From 2-3 seed colours and the client's contact details this script
    (a) derives a complete design system (derive_system),
    (b) writes the system YAML (usable anywhere via --system),
    (c) renders three deterministic palette variations of the business
        card and A5 flyer as client-proof PNGs,
    (d) renders press PDFs (CMYK, bleed, printer's marks) for the card
        (front+back), the A4 z-fold and the signboard (front+back),
    (e) renders the brand manual PDF (with a generated monogram logo).

Everything is deterministic: same seeds + details, same bytes out.
See docs/AGENCY_WORKFLOW.md for the walkthrough.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import yaml

from designer.brandbook import render_brandbook
from designer.color import oklab_to_rgb, parse_color, rgb_to_oklab, to_hex
from designer.formats import get_format, mm_to_px
from designer.palette import derive_system
from designer.render import render_pdf, render_png
from designer.svg import parse_svg
from designer.template import (
    AGENCY_TYPE_SCALE,
    TemplateData,
    palette_for_system,
    render as render_template,
)
from designer.tokens import DesignSystem, system_from_dict

TEMPLATES = Path(__file__).resolve().parent / "templates" / "agency"

# Custom formats the pack needs beyond the built-in catalog; these ride
# in the client system YAML so every tool sees them via --system.
CUSTOM_FORMATS = {
    "business-card-90x50": {
        "unit": "mm", "dpi": 300, "width": 90, "height": 50, "bleed": 3,
        "category": "print", "min_text_size": 2,
        "description": "Business card 90x50mm at 300dpi",
    },
    "flyer-a5": {
        "unit": "mm", "dpi": 300, "width": 148, "height": 210, "bleed": 3,
        "category": "print", "min_text_size": 2,
        "description": "A5 flyer 148x210mm at 300dpi",
    },
}


def _mid_seed(a: str, b: str) -> str:
    """Deterministic third accent: the OKLab midpoint of two seeds."""
    la = rgb_to_oklab(parse_color(a))
    lb = rgb_to_oklab(parse_color(b))
    return to_hex(oklab_to_rgb(tuple((x + y) / 2 for x, y in zip(la, lb))))


def build_system(seeds: list[str], name: str) -> tuple[dict, DesignSystem]:
    data = derive_system(seeds, name=name, overrides={
        "typography": {"scale": list(AGENCY_TYPE_SCALE)},
        "formats": CUSTOM_FORMATS,
    })
    return data, system_from_dict(data)


def variations(seeds: list[str], name: str) -> list[tuple[str, DesignSystem]]:
    """Three deterministic palette treatments for client proofs."""
    inverted = [seeds[1], seeds[0]] + seeds[2:]
    midtone = [seeds[0], _mid_seed(seeds[0], seeds[1])] + seeds[2:]
    return [
        (key, build_system(s, f"{name} — {key}")[1])
        for key, s in (("brand", seeds), ("inverted", inverted),
                       ("midtone", midtone))
    ]


def _fill(template_name: str, system: DesignSystem, fields: dict[str, str],
          logo: Path | None = None):
    template = parse_svg(TEMPLATES / f"{template_name}.svg")
    images = {"logo": str(logo)} if logo else {}
    data = TemplateData(fields=fields, palette=palette_for_system(system),
                        images=images)
    return render_template(template, data, system)


def make_logo(out: Path, system: DesignSystem, name: str) -> Path:
    """Deterministic monogram placeholder so the brandbook's logo page
    has something real to show; swap in the client's mark when it exists."""
    palette = palette_for_system(system)
    primary, accent, on_primary = palette[0], palette[1], palette[4]
    initial = next((ch for ch in name if ch.isalpha()), "A").upper()
    out.write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 240 240" '
        'width="240" height="240">\n'
        f'  <rect x="8" y="8" width="224" height="224" fill="{primary}"/>\n'
        f'  <rect x="8" y="196" width="224" height="36" fill="{accent}"/>\n'
        f'  <text x="120" y="150" text-anchor="middle" font-size="120" '
        f'font-weight="bold" fill="{on_primary}" '
        f'font-family="DejaVu Sans">{initial}</text>\n'
        "</svg>\n",
        encoding="utf-8",
    )
    return out


def run(seeds: list[str], fields: dict[str, str], outdir: Path) -> list[Path]:
    name = fields["business-name"]
    outdir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []

    def note(path: Path) -> Path:
        written.append(path)
        return path

    # (a) + (b) — derive the system and persist it.
    data, system = build_system(seeds, name)
    system_yaml = note(outdir / "system.yaml")
    system_yaml.write_text(yaml.safe_dump(data, sort_keys=False),
                           encoding="utf-8")

    logo = note(make_logo(outdir / "logo.svg", system, name))
    # Template <image> slots embed rasters; the vector goes to the book.
    logo_png = note(outdir / "logo.png")
    render_png(parse_svg(logo), logo_png, width=480)

    # (c) — client proofs: three palette treatments of card + flyer.
    proofs = outdir / "proofs"
    proofs.mkdir(exist_ok=True)
    for key, variant in variations(seeds, name):
        card = _fill("business-card", variant, fields, logo_png)
        render_png(card, note(proofs / f"card-{key}.png"), width=1000)
        flyer = _fill("flyer-a5", variant, fields, logo_png)
        render_png(flyer, note(proofs / f"flyer-{key}.png"), width=700)

    # (d) — press PDFs: CMYK with bleed and printer's marks.
    press = outdir / "press"
    press.mkdir(exist_ok=True)

    card_spec = get_format("business-card-90x50", extra=system.formats)
    render_pdf(
        [_fill("business-card", system, fields, logo_png),
         _fill("business-card-back", system, fields, logo_png)],
        note(press / "business-card-90x50.pdf"),
        cmyk=True, format=card_spec, bleed=card_spec.bleed, marks=True,
    )

    zfold_spec = get_format("z-fold-a4")
    render_pdf(
        _fill("z-fold-a4", system, fields, logo_png),
        note(press / "z-fold-a4.pdf"),
        cmyk=True, format=zfold_spec, bleed=system.bleed, marks=True,
    )

    board_spec = get_format("signboard-2000x800")
    render_pdf(
        [_fill("signboard-2000x800", system, fields, logo_png),
         _fill("signboard-2000x800-back", system, fields, logo_png)],
        note(press / "signboard-2000x800.pdf"),
        cmyk=True, format=board_spec,
        bleed=mm_to_px(3, board_spec.dpi),  # 3mm at the board's 150dpi
        marks=True,
    )

    # (e) — the brand manual.
    render_brandbook(system, note(outdir / "brandbook.pdf"), logo=logo)
    return written


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Derive a design system from seed colours and render "
        "the full agency deliverable drop.")
    parser.add_argument("seeds", nargs="+", metavar="HEX",
                        help="2-3 seed colours: primary, accent[, secondary]")
    parser.add_argument("--name", required=True, help="business name")
    parser.add_argument("--tagline", default="Import. Export. Delivered.")
    parser.add_argument("--phone", default="+27 11 555 0123")
    parser.add_argument("--email", default="hello@example.co.za")
    parser.add_argument("--address", default="12 Harbour Rd, Durban")
    parser.add_argument("--outdir", "-o", default="agency-out",
                        help="output directory (default agency-out/)")
    args = parser.parse_args(argv)
    if not 2 <= len(args.seeds) <= 3:
        parser.error("give 2 or 3 seed colours")

    fields = {
        "business-name": args.name,
        "tagline": args.tagline,
        "phone": args.phone,
        "email": args.email,
        "address": args.address,
    }
    written = run(list(args.seeds), fields, Path(args.outdir))
    for path in written:
        print(f"wrote {path} ({path.stat().st_size:,} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
