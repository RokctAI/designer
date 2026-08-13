# Agency template pack

Slot-marked SVG templates for the standard small-business identity
drop: cards, flyer, folded brochure, banner, signboard, folder and
merch. Rendered with `designer.template.render` — same conventions as
the other templates in `examples/templates/`.

## Palette roles

No template hard-codes brand colors. Every fill carries
`data-token="advertiser-N"`, bound to a **role**, so any derived
design system restyles the whole pack:

| token          | role       |
|----------------|------------|
| `advertiser-1` | primary    |
| `advertiser-2` | accent     |
| `advertiser-3` | ink        |
| `advertiser-4` | surface    |
| `advertiser-5` | on-primary |
| `advertiser-6` | paper      |

Build the ordered palette from a system with
`designer.template.palette_for_system(system)` (the order is
`designer.template.AGENCY_PALETTE_ROLES`). The colors baked into the
SVGs are only the default-system fallbacks.

## Slots

All templates share the same slot vocabulary: `business-name`,
`tagline`, `phone`, `email`, `address` (text) and `logo` (image).
Empty slots vanish cleanly. Slots marked `data-fit="shrink"` step down
the system type scale until the text fits — the pack's sizes come from
`designer.template.AGENCY_TYPE_SCALE`, so install that ladder as the
system's typography scale (the demo's `derive_system` override does
this) for print-appropriate fitting.

## Formats and bleed

Each template canvas is the **trim size** of a real format at its
press dpi; backgrounds extend past the trim by the bleed so
`render_pdf(..., format=spec, bleed=..., marks=True)` produces a
press-ready page:

| template                     | format                          | trim               | bleed |
|------------------------------|---------------------------------|--------------------|-------|
| `business-card.svg` / `-back`| custom `business-card-90x50`*   | 90x50mm @300dpi    | 3mm   |
| `flyer-a5.svg`               | custom `flyer-a5`*              | 148x210mm @300dpi  | 3mm   |
| `z-fold-a4.svg`              | `z-fold-a4`                     | 297x210mm @300dpi  | 3mm   |
| `pullup-banner.svg`          | `pullup-banner`                 | 850x2000mm @300dpi | 3mm   |
| `signboard-2000x800.svg` / `-back` | `signboard-2000x800`      | 2000x800mm @150dpi | 3mm   |
| `corporate-folder-a4.svg`    | `corporate-folder-a4`           | 445x385mm @300dpi  | 3mm   |
| `pen-barrel.svg`             | `pen-barrel-70x15`              | 70x15mm @300dpi    | 2mm   |

\* declared in the client system YAML's `formats:` block (see
`examples/agency_demo.py`); the rest are built-in presets.

The folded formats respect their panel geometry: the z-fold's content
zones stay inside the 100/99/98mm panels (fold-in panel 2mm narrower),
and the folder keeps its covers clear of the 5mm spine and the 80mm
fold-up pocket strip.
