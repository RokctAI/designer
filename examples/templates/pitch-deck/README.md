# Pitch-deck template pack

Slot-marked SVG templates for a startup pitch deck: title, content,
data (metrics grid) and closing/ask slides. Rendered with
`designer.template.render` — same conventions as the other templates in
`examples/templates/`. Every canvas is the `slide-16x9` preset
(1920×1080, screen), so a rendered slide audits directly with
`-f slide-16x9` and drops into a 16:9 deck (e.g. the StartupOS
`.pptx` generator, see `docs/STARTUPOS_PIPELINE.md`) as a full-bleed
background or a finished slide image.

## Palette roles

No template hard-codes brand colors. Every fill carries
`data-token="advertiser-N"`, bound to the same **roles** as the agency
pack (`designer.template.AGENCY_PALETTE_ROLES`):

| token          | role       |
|----------------|------------|
| `advertiser-1` | primary    |
| `advertiser-2` | accent     |
| `advertiser-3` | ink        |
| `advertiser-4` | surface    |
| `advertiser-5` | on-primary |
| `advertiser-6` | paper      |

Build the ordered palette with
`designer.template.palette_for_system(system)`. The colors baked into
the SVGs are only the default-system fallbacks.

One deliberate difference from the agency pack: **no text sits on a
primary fill**. Role-poor systems (e.g. `systems/supacharge.yaml`,
which declares no `primary` token) resolve `primary` and `on-primary`
to the same dark surface, so on-primary text would vanish. All copy is
ink-on-surface, which audits clean on dark and light systems alike;
primary and accent appear only as bands and rules.

## Slots

Text slots: `business-name`, `tagline`, `date`, `kicker` (the section
eyebrow — "PROBLEM", "TRACTION"), `heading`, `point-1`…`point-4`,
`footnote`, `email`, `phone`. Image slots: `logo`, `hero`. Empty slots
vanish cleanly. Slots marked `data-fit="shrink"` step down the system
type scale until the text fits; declared sizes come from the engine's
default scale (the `slide-16x9` screen space), so no scale override is
needed.

| template            | slots |
|---------------------|-------|
| `slide-title.svg`   | `logo`, `business-name`, `tagline`, `date` |
| `slide-content.svg` | `kicker`, `heading`, `point-1`…`point-4`, `hero` |
| `slide-data.svg`    | `kicker`, `heading`, `footnote` + items region |
| `slide-closing.svg` | `kicker`, `heading`, `point-1`…`point-3`, `email`, `phone`, `logo` |

## The data slide

`slide-data.svg` carries a `data-region="items"` rectangle and flows
`stat-cell.svg` into it — one cell per `designer.template.Item`, with
`price` as the big value, `title` as the metric label and `badge` as
the delta line (e.g. `Item(title="ARR", price="R14.2m",
badge="+61% YoY")`). Four metrics fill the region at exactly the
cell's native 360×240 geometry, so the common four-stat slide stays on
the 8px grid; other counts still flow (centered), at the cost of
grid-snap warnings in the audit.

## Format

| template            | format      | canvas    |
|---------------------|-------------|-----------|
| all `slide-*.svg`   | `slide-16x9`| 1920×1080 |

Screen format: no bleed, backgrounds cover the canvas exactly. Text
respects the preset's 5% safe margin and 18px text minimum. Export
with `render_png(doc)` (or `designer render slide.svg -o slide.png`)
for deck embedding.
