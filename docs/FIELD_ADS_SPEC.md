# Field Ads — Capture-to-Ad Spec (v2)

Third companion spec (with `SAAS_SPEC.md` and `FRONTEND_SPEC.md`).
v2 incorporates the publisher's decisions:

- Ad units span **full page down to very small**, defined as fractions
  of the publication's own page grid (single publication to start).
- **Palette is optional and selectable** — many signboards have no
  logo or brand colors; the agent can extract from a photo, pick
  colors manually, or use the publication's neutral ad scheme.
- The field app is a **second frontend in Flutter** (tablet-first,
  camera-native, offline-tolerant). Next.js keeps the studio; the
  Frappe API serves both identically.
- **Composite block ads** are first-class: a retail ad built cell by
  cell (product photo + name + price + SAVE/SPECIAL badge), captured
  item-by-item in the field.
- **Logo policy by size**: small units drop the logo rather than
  compromise the text; declared per slot, enforced by the renderer.

Engine support note: the engine parses, grid-snaps and format-rescales
`<image>` elements (product photos embedded in the SVG) while treating
their pixel content as opaque — this landed with this spec revision.

## 1. Use cases

**Single-advertiser ad** (v1 core): agent photographs the client's
signboard/logo, captures a handful of facts, picks a unit + template,
and shows the finished ad on the tablet in seconds. No AI generation on
this path — template fill + compliance is what makes it look designed,
and sub-second render is what closes the sale on the spot.

**Composite retail ad** (the supermarket case): one advertiser, many
products. The agent walks the aisles in a loop — *photo → name → price
→ badge → next* — taps Done, and sees the full ad assembled: a grid of
product blocks flowing into the chosen unit, publication typography and
spacing enforced on every cell.

## 2. DocTypes

### 2.1 Publication (the newsletter and its page geometry)

| Field | Type | Notes |
|---|---|---|
| publication_name | Data, reqd | |
| design_system | Link Design System, reqd | governs every ad: fonts, grid, contrast |
| page_width_px / page_height_px | Int | the full-page canvas (fill with the real page trim at the chosen DPI — see §7.1) |
| columns / rows | Int | the page's ad grid (e.g. 4 x 8 slots) |
| gutter_px | Int | spacing between grid cells |
| units | Table -> Publication Ad Unit | |

**Publication Ad Unit** (child): `unit_name`, `col_span`, `row_span`,
`price` (Currency, optional). Pixel size is **computed** from the page
grid: `w = col_span * col_w + (col_span-1) * gutter` (same for rows) —
so "full page", "double page spread" (col_span = 2 x columns, built on
a doubled-width canvas), "half", "quarter", "eighth", down to a 1x1
classified block all come from the same grid, and resizing the page
re-derives every unit. At runtime each unit becomes
`FormatSpec(unit_name, w, h, "print", margin, min_text_size)`; margin
and min_text_size default from Settings and can be overridden per unit
(small units need proportionally larger minimum text).

### 2.2 Advertiser (captured once, reused every issue)

| Field | Type | Notes |
|---|---|---|
| advertiser_name | Data, reqd | |
| contact_* | Data | phone, whatsapp, email, address |
| photos | Table -> Advertiser Photo (`image` Attach, `kind` Select: signboard/logo/product/other) | all optional |
| palette | Table -> Design Color Token | **optional**; see palette sources below |
| palette_source | Select | `extracted\nmanual\npublication-default` |
| logo_svg | Attach | optional; engine-vectorized from a logo photo when one exists |

Palette sources (agent chooses on the tablet, in this order of
preference):

1. **extracted** — `extract_palette` on a photo; agent confirms/trims.
2. **manual** — color picker; the UI offers the publication's curated
   accent palette first, full picker behind it. For signboards with no
   usable colors this is the normal path, not the fallback.
3. **publication-default** — skip color capture entirely; the ad
   renders in the publication's neutral ad scheme. Zero-friction path.

Whatever the source, the tokens flow into template `data-token` slots
identically, and the compliance pass enforces contrast on the result —
a manually-picked yellow behind white text gets corrected exactly like
an extracted one.

### 2.3 Ad Template

| Field | Type | Notes |
|---|---|---|
| template_name | Data | |
| publication | Link | |
| compatible_units | Data | CSV of unit names |
| kind | Select | `single\ncomposite` |
| svg_template | Attach | slot-marked SVG (§3) |
| cell_template | Attach | composite only: the per-product block SVG |
| preview | Attach | thumbnail |

Ship four default `single` layouts (logo-left, logo-top, text-only,
photo card) and two `composite` layouts (blocks-with-header,
blocks-edge-to-edge) so the system works before any designer touches it.

### 2.4 Ad Capture (one field visit -> one ad)

As v1, plus composite items:

| Field | Type | Notes |
|---|---|---|
| advertiser / publication / ad_unit / template | Links | |
| issue / placement | Link Publication Issue / Link Ad Placement | set by the booking flow (§4.2); placement state follows capture status |
| fields_json | JSON | headline, offer, contact... (single kind) |
| items | Table -> Ad Capture Item | composite kind |
| status | Select | `Captured\nRendered\nApproved\nRejected\nPublished` |
| rendered_svg / score / report_json | | as everywhere |
| captured_by / approved_at | | |

**Ad Capture Item** (child): `photo` (Attach), `title` (Data), `price`
(Data — keep as text: "R29.99", "2 for R30"), `badge` (Select:
`none\nsave\nspecial\nnew`), `sort_order` (Int).

## 3. Template model

### 3.1 Slot markers (as v1)

`data-slot` (logo/headline/offer/body/contact/photo), `data-token`
(palette-mapped fills), `data-fit="shrink"` (PIL font-metric fitting
down the type scale until the text fits the slot box).

### 3.2 Size-responsive slots (the logo policy)

```xml
<image data-slot="logo" data-optional="true" data-min-unit-width="400"
       data-freed-to="headline" .../>
```

- `data-optional="true"` + `data-min-unit-width` — the renderer drops
  this slot entirely when the target unit's width is below the
  threshold. Small ads lose the logo; the text never shrinks to make
  room for it.
- `data-freed-to="<slot>"` — when dropped, the named slot's box is
  extended to absorb the freed rectangle (union of the two boxes), so
  the headline gets the space. No general reflow in v1 — one declared
  beneficiary per optional slot.
- Same mechanism works for any slot (e.g. drop the photo in a 1x1
  classified block, keep name + price + phone).

### 3.3 Composite regions (the supermarket grid)

The composite template marks one region:

```xml
<rect data-region="items" x=".." y=".." width=".." height=".."
      data-min-cell="140" fill="none"/>
```

The cell template is its own slot-marked SVG (photo slot + title +
price + badge). Renderer algorithm:

1. N = item count. Choose the column count that best fills the region:
   `cols = clamp(round(sqrt(N * region_w/region_h)), 1, floor(region_w/min_cell))`,
   `rows = ceil(N / cols)`; cell = region grid cell minus gutter.
2. If the resulting cell edge < `data-min-cell`: too many items for
   this unit — the API returns a structured error naming the smallest
   unit that fits (the Flutter app offers the upgrade: "12 items needs
   a half page — switch?"). Never silently shrink below legibility.
3. For each item (by sort_order): fill the cell template — photo into
   the photo slot (embedded `<image>`, center-crop to the slot's
   aspect), title/price with `data-fit="shrink"`, badge slot filled
   with the badge style (a small token-colored shape + label) or
   dropped for `none`.
4. Place cells row-major into the region; last row centers if partial.
5. Run the publication comply pass (with the unit's FormatSpec) over
   the assembled document — one pass over the whole ad, cells included.

Product photos stay raster (`<image>` with attached-file href;
`render_png` composes them for print output). The engine grid-snaps
and rescales their geometry but never vectorizes their content —
that's correct for photographs.

## 4. Issue inventory & flatplan (don't sell what you can't print)

The page grid makes inventory computable: an issue has N ad pages,
each a `columns x rows` grid; every sold ad occupies a `col_span x
row_span` rectangle. Availability is a **placement** question, not a
cell count — 4 scattered free cells do not fit a 2x2 quarter page —
so every availability answer comes from actually attempting a
first-fit placement against current holds + confirmations.

### 4.1 DocTypes

**Publication Issue**: `publication` (Link), `issue_no`,
`publish_date`, `sales_deadline` (Datetime — no new holds after),
`status` (`Open\nLayout Locked\nPublished`), `pages` (Table ->
Issue Page).

**Issue Page** (child): `page_no`, `sellable` (Check — cover/editorial
pages excluded), `reserved_cells` (Data — CSV of `col,row` cells held
back for editorial within an otherwise sellable page).

**Ad Placement** (autoname `PL-.#####`): `issue`, `page_no`, `col`,
`row`, `col_span`, `row_span`, `capture` (Link Ad Capture),
`state` (`Hold\nConfirmed\nCancelled`), `hold_expires_at` (Datetime).
The placement IS the inventory record: grid rectangles of non-Cancelled
placements may never overlap (validated on save; the whole grid is at
most ~32 cells/page, so validation is a trivial scan).

### 4.2 Booking flow (built into the field capture)

1. Agent opens capture → picks the issue (default: next Open issue) →
   the unit picker shows **live availability per unit** ("quarter: 3
   left, half: 1 left, full: sold out") from `get_issue_availability`.
   Sold-out units render disabled — the agent cannot start a capture
   that can't be printed.
2. Picking a unit calls `hold_slot` → a Hold placement at the
   first-fit position, with a TTL (Settings, default 4h). The hold
   survives the whole capture + client conversation.
3. `approve_capture` → placement Confirmed. Rejected/abandoned →
   Cancelled; the rectangle frees immediately. A scheduler job expires
   stale Holds every 15 min.
4. After `sales_deadline` or when the issue is Layout Locked, holds
   are refused with a clear error.

Two agents racing for the last half page: `hold_slot` is atomic
(placement insert + overlap validation in one transaction) — the
second agent gets `sold_out` plus the nearest available alternatives
(smaller units that still fit, or the next issue).

Offline reality (Flutter): holds require the server. Offline, the app
shows last-synced availability marked "unconfirmed" and lets capture
proceed; the hold is attempted at sync, and a failed hold flags the
capture for re-negotiation instead of silently overselling. Honest
state over false certainty.

### 4.3 The flatplan (back office)

`get_issue_map(issue)` returns every page's grid with its placements
(position, span, state, advertiser, rendered thumbnail). The Next.js
studio gets `/studio/issues/[id]`: the classic newspaper flatplan —
pages side by side, ads drawn on their grids, color-coded Hold vs
Confirmed, drag to reposition (same-size moves only, until Layout
Locked; unit size never changes after confirmation). "Export issue"
downloads every confirmed ad's SVG/PNG named by page/position, ready
for the page-assembly tool.

Availability math note: first-fit placement at hold time can fragment
pages (a later big unit may not fit although enough total cells
remain). The flatplan's drag-repositioning is the human defrag tool;
`get_issue_availability` also returns a `fragmented: true` hint per
unit when a repack (ignoring positions, keeping sizes) would fit one
more of that unit but current positions don't — so the desk knows
shuffling would open a slot before turning a sale away.

### 4.4 Sales visibility

Standard Frappe reports over Ad Placement / Ad Capture give the desk:
sold vs available per unit per issue, revenue to date (unit prices),
holds outstanding and expiring, per-agent sales counts. A small
`/studio/issues` index lists open issues with fill % and deadline
countdown.

## 5. API (extends v1's §5)

| Method | Args | Behavior |
|---|---|---|
| `register_advertiser` | name, contact, photos=[], palette_mode, manual_colors=[] | photos optional; palette per §2.2; logo vectorized only when a logo photo is provided |
| `render_ad` | advertiser, publication, ad_unit, template, fields_json={}, items=[] | synchronous template fill (§3) + comply; returns `{"svg", "score", "report_json", "capture"}`; structured `unit_too_small` error per §3.3.2 |
| `rerender_capture` | capture, fields_json/items patch | edit-in-the-field = change the inputs and re-render (sub-second). This replaces any need for an SVG editor on the tablet. |
| `approve_capture` | capture | as v1 |
| `list_units` | publication | units with computed px sizes + prices, for the picker |
| `get_issue_availability` | issue | per unit: `{available, sold, held, fragmented}` via first-fit placement against current placements (§4) |
| `hold_slot` | issue, ad_unit | atomic Hold placement or `sold_out` error with alternatives; TTL from Settings |
| `get_issue_map` | issue | full flatplan data for the studio board |

## 6. Flutter field app (the second frontend)

Separate codebase from the Next.js studio; same Frappe API.

- **Stack**: Flutter (tablet-first, works on phones), `camera` +
  image picker, `flutter_svg` for ad preview, `drift` (SQLite) for the
  offline queue, background sync via `workmanager`. Auth: Frappe API
  key/secret per user, provisioned by QR from the desk.
- **Capture wizard (single)**: advertiser (search or inline create) →
  camera (signboard/logo, skippable) → palette step (three source
  buttons per §2.2) → facts form (5–8 fields, big inputs, voice
  dictation via platform keyboard) → unit picker (with prices) →
  template picker (thumbnails) → **Render**.
- **Capture loop (composite)**: after unit/template selection the app
  enters the aisle loop: full-screen camera → photo → title/price/badge
  overlay form → **Next** (repeat) → **Done** → render. Item list is
  reorderable; items editable before and after render.
- **Result screen**: the ad full-width (flutter_svg), score badge,
  "what we enforced" log, **Edit** (reopens the inputs → `rerender_capture`),
  **Approve** (client taps; capture Approved + timestamp).
- **Offline**: captures and photos queue locally; render requires the
  server — queued captures show honestly as "pending render"; sync
  renders them and notifies. (Client-side rendering via a WASM build of
  the engine is a noted non-goal for now.)
- Editing model on the tablet is deliberately **inputs, not SVG**:
  because template fill is deterministic, editing the inputs and
  re-rendering is strictly simpler and safer than an SVG editor, and
  it's what a field agent actually wants. The full guardrailed SVG
  editor remains a studio (Next.js) feature for the back office.

## 7. What stays out of AI generation

Both field paths (single and composite) are generation-free. The
premium AI hero background (v1 §5.4) remains an option for `single`
ads only, and never blocks the on-the-spot flow: the plain render
shows first, the hero variant arrives when ready.

## 8. Remaining decisions

1. **Page geometry**: the real page trim size and DPI of the
   publication, and its column/row grid (fills §2.1; everything else
   derives from it). Suggested default until confirmed: A4 portrait at
   150dpi → 1240x1754px, 4 columns x 8 rows, 16px gutter.
2. **Badge styles**: SAVE / SPECIAL / NEW ship as token-colored
   pill + bold label; confirm wording set (multilingual?).
3. **Approval → billing**: unchanged from v1 — hook point exists at
   `approve_capture`; wiring to quotes/payments lives in the host app.
