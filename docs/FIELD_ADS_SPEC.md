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

## 4. API (extends v1's §5)

| Method | Args | Behavior |
|---|---|---|
| `register_advertiser` | name, contact, photos=[], palette_mode, manual_colors=[] | photos optional; palette per §2.2; logo vectorized only when a logo photo is provided |
| `render_ad` | advertiser, publication, ad_unit, template, fields_json={}, items=[] | synchronous template fill (§3) + comply; returns `{"svg", "score", "report_json", "capture"}`; structured `unit_too_small` error per §3.3.2 |
| `rerender_capture` | capture, fields_json/items patch | edit-in-the-field = change the inputs and re-render (sub-second). This replaces any need for an SVG editor on the tablet. |
| `approve_capture` | capture | as v1 |
| `list_units` | publication | units with computed px sizes + prices, for the picker |

## 5. Flutter field app (the second frontend)

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

## 6. What stays out of AI generation

Both field paths (single and composite) are generation-free. The
premium AI hero background (v1 §5.4) remains an option for `single`
ads only, and never blocks the on-the-spot flow: the plain render
shows first, the hero variant arrives when ready.

## 7. Remaining decisions

1. **Page geometry**: the real page trim size and DPI of the
   publication, and its column/row grid (fills §2.1; everything else
   derives from it). Suggested default until confirmed: A4 portrait at
   150dpi → 1240x1754px, 4 columns x 8 rows, 16px gutter.
2. **Badge styles**: SAVE / SPECIAL / NEW ship as token-colored
   pill + bold label; confirm wording set (multilingual?).
3. **Approval → billing**: unchanged from v1 — hook point exists at
   `approve_capture`; wiring to quotes/payments lives in the host app.
