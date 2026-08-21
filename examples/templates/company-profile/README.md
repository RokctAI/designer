# Company-profile template pack

Slot-marked SVG templates for an A4 company profile — the
most-requested tender returnable: a cover page and a content page
(overview, leadership, track record, contact). Rendered with
`designer.template.render` — same conventions as the other packs in
`examples/templates/`. Both canvases are the `a4-poster` preset
(794×1123, print at 96dpi), so a rendered page audits directly with
`-f a4-poster` and exports to PNG or press PDF like any other print
deliverable.

## Palette roles

No template hard-codes brand colors. Every fill carries
`data-token="advertiser-N"`, bound to the same **roles** as the agency
and pitch-deck packs (`designer.template.AGENCY_PALETTE_ROLES`):

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

Like the pitch-deck pack, **no text sits on a primary fill**: role-poor
systems (e.g. `systems/supacharge.yaml`) resolve `primary` and
`on-primary` to the same dark surface, so on-primary copy would vanish.
All copy is ink-on-surface (or ink on a paper card), which audits clean
on dark and light systems alike; primary and accent appear only as
bands and rules.

## Slots

Text slots reuse the shared vocabulary where one exists
(`business-name`, `tagline`, `kicker`, `date`, `heading`,
`point-1`…`point-4`, `email`, `phone`) and add the profile-specific
ones: `reg-number` and `vat-number` (the registration block),
`leadership-title` and `lead-1`…`lead-3` (the leadership block),
`track-title` (over the items region). Image slot: `logo`. Empty slots
vanish cleanly. Slots marked `data-fit="shrink"` step down the system
type scale until the text fits; declared sizes come from the engine's
default scale, so no scale override is needed.

| template              | slots |
|-----------------------|-------|
| `profile-cover.svg`   | `logo`, `kicker`, `business-name`, `tagline`, `reg-number`, `vat-number`, `date` |
| `profile-content.svg` | `kicker`, `heading`, `point-1`…`point-4`, `leadership-title`, `lead-1`…`lead-3`, `track-title`, `email`, `phone` + items region |

## The track-record region

`profile-content.svg` carries a `data-region="items"` rectangle and
flows `record-cell.svg` into it — one cell per
`designer.template.Item`, with `price` as the big value, `title` as
the label and `badge` as the context line (e.g. `Item(title="Contracts
delivered", price="240+", badge="on time")`). Three proof points fill
the 664px region at exactly the cell's native 200×160 geometry, so the
common three-metric row stays on the 8px grid; other counts still flow
(centered), at the cost of grid-snap warnings in the audit.

## Format

| template               | format      | trim      |
|------------------------|-------------|-----------|
| both `profile-*.svg`   | `a4-poster` | 794×1123  |

Print format: backgrounds extend 40px past the trim, clearing a
3mm-at-300dpi (35.4px) bleed while staying on the 8px grid. Text
respects the preset's 5% safe margin and 12px text minimum. Export
with `render_png(doc)` for a preview, or `designer render page.svg -o
page.pdf --cmyk` for press output.
