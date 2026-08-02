# Field Ads — Capture-to-Ad Spec (proposal)

Third companion spec (with `SAAS_SPEC.md` and `FRONTEND_SPEC.md`).
Status: **v1 proposal** — the architecture is settled; the items in §7
are product decisions to confirm before building.

## 1. The use case

A publication (newsletter with ads, newspaper-style) sends any employee
into the field with a tablet. At a client's premises they:

1. photograph the storefront / sign / logo / products,
2. type or dictate a handful of facts (business name, offer, price,
   phone/WhatsApp, address),
3. pick an ad unit (quarter page, eighth, strip…),

…and a **finished, designed ad appears on the tablet in seconds** — in
the publication's design system, using the client's own brand colors
lifted from the photos. The sale closes on the spot because the client
is looking at their ad, not imagining it.

## 2. Why this works without AI generation

The on-the-spot path is **template-fill, not image generation**:

- No generation latency (seconds vs sub-second) and no per-ad API cost
  — the unit economics of "any employee can sell ads" depend on this.
- Deterministic output — the field agent always gets a sellable result,
  never a weird generation.
- The "designed" look comes from the compliance engine, which is
  already built: publication fonts, grid, safe margins, WCAG contrast,
  and per-unit minimum text size are enforced on the filled template.

AI generation stays available as an upsell (§5.4: premium hero
backgrounds), where latency and cost are acceptable.

Everything below is Frappe-module + frontend work. The engine needs
**zero changes**: custom ad units are `FormatSpec` instances built at
runtime (the engine accepts specs, not just catalog names), palette
extraction and logo vectorization are existing engine calls, and the
filled template is complied like any other SVG.

## 3. DocTypes

### 3.1 Advertiser (the client — captured once, reused every issue)

| Field | Type | Notes |
|---|---|---|
| advertiser_name | Data, reqd | |
| contact_* | Data | phone, whatsapp, email, address |
| photos | Table -> Advertiser Photo (`image` Attach, `kind` Select: storefront/logo/product/other) | |
| palette | Table -> Design Color Token (reuse child) | extracted via `extract_palette` from photos; agent can re-order/trim on the tablet |
| logo_svg | Attach | engine-vectorized + complied from the logo photo |
| default_offer_fields | JSON | last-used field values, pre-filled next visit |
| owner_team | Link | tenancy anchor, as elsewhere |

### 3.2 Publication + Ad Unit (the newsletter and its slots)

**Publication**: `publication_name`, `design_system` (Link — the
publication's own system: fonts, grid, contrast; this governs every ad),
`units` (Table -> Publication Ad Unit).

**Publication Ad Unit** (child): `unit_name` (e.g. "quarter-page"),
`width_px`, `height_px`, `margin` (Float, fraction), `min_text_size`
(Float), `price` (Currency, optional — enables on-the-spot quoting).
At runtime: `FormatSpec(unit_name, width_px, height_px, "print",
margin, min_text_size)` — passed straight to `ComplianceEngine`.

### 3.3 Ad Template

| Field | Type | Notes |
|---|---|---|
| template_name | Data | |
| publication | Link Publication | |
| compatible_units | Data | CSV of unit names this layout fits |
| svg_template | Attach | SVG with slot markers (§4) |
| preview | Attach | thumbnail for the picker |

### 3.4 Ad Capture (one field visit -> one ad)

| Field | Type | Notes |
|---|---|---|
| advertiser | Link Advertiser, reqd | created inline on first visit |
| publication / ad_unit / template | Links | |
| fields_json | JSON | slot values: headline, offer, price, contact… |
| status | Select | `Captured\nRendered\nApproved\nRejected\nPublished` |
| rendered_svg | Attach | the complied ad |
| score / report_json | Float / Long Text | engine audit, as everywhere else |
| captured_by | Link User | the field agent |
| approved_at | Datetime | client said yes, on the spot |

## 4. Template model (SVG + slot markers)

A template is a valid SVG (so designers can author it in any tool)
whose slot elements carry `data-slot` / `data-token` attributes:

```xml
<rect data-token="advertiser-primary" .../>   <!-- fill replaced by advertiser palette -->
<image data-slot="logo" x=".." y=".." width=".." height=".."/>
<text data-slot="headline" data-fit="shrink" x=".." y=".." font-size="32"/>
<text data-slot="offer"    data-fit="shrink" .../>
<text data-slot="contact"  .../>
```

Fill algorithm (`field_ads/renderer.py` in the module):

1. Parse with the engine's `parse_svg` (slot attrs survive as plain
   attributes on the Shape model).
2. `data-token="advertiser-*"` fills → the advertiser's extracted
   palette (position 1 = primary, 2 = secondary…). Every replacement is
   then subject to the publication system's contrast rules in step 5 —
   an advertiser color that fails contrast gets recolored by the
   engine, exactly like any other violation.
3. `data-slot="logo"` → inline the advertiser's vectorized `logo_svg`
   scaled into the slot box.
4. Text slots → fill from `fields_json`. `data-fit="shrink"`: measure
   the string with PIL `ImageFont.truetype` of the publication's actual
   font file and walk *down* the type scale until it fits the slot
   width (real glyph metrics, not estimates — the bench has the font
   files).
5. Run `ComplianceEngine(publication_system, format=unit_spec).comply()`
   on the filled document. This is what makes it look designed: grid,
   margins, contrast, minimum text size for the unit — enforced, with
   the fix log stored like every other candidate.

## 5. Pipeline & API

### 5.1 First visit to a client (once per advertiser)

`register_advertiser(name, contact, photos[])` →
background job: `extract_palette` on the best photo(s); logo photo →
engine comply with `format="logo"` → `logo_svg`. Returns the palette
for the agent to confirm/trim on the tablet.

### 5.2 The capture (every ad)

`render_ad(advertiser, publication, ad_unit, template, fields_json)` →
runs §4 **synchronously** (template fill + comply is sub-second, no
queue needed) → returns `{"svg", "score", "report_json", "capture"}`.
The tablet shows the finished ad immediately.

### 5.3 Approval

`approve_capture(capture)` → status Approved, timestamps. Published
status is set by the issue-assembly process (out of scope here; the
rendered SVG is the deliverable this system hands over). The standard
guardrailed editor (FRONTEND_SPEC §2.2) opens on any rendered ad for
touch-ups before approval.

### 5.4 Premium upsell (optional, not v1-blocking)

`render_ad(..., hero=True)` additionally runs a generation request
(prompt composed from the advertiser's palette + business type + offer)
for a background layer behind the template content, through the normal
candidate pipeline. Slower and costs a generation — priced accordingly.

## 6. Tablet frontend (extends FRONTEND_SPEC)

New route group `/field` in the same Next.js app:

- `/field/capture` — one screen, big controls: advertiser picker
  (or inline create), camera inputs, the 5–8 text fields, unit picker
  (with prices), template picker (thumbnails), Render button.
- Result screen: the ad full-width, score badge, "what we enforced"
  log, Edit (opens the standard editor), Approve (client taps).
- Offline tolerance: the capture form and photos queue in IndexedDB
  and sync when connectivity returns; rendering requires the server —
  show queued state honestly. (Fully-offline rendering is possible
  later by compiling the engine to WASM — noted, not planned.)

## 7. Open decisions before building

1. **Ad units**: the real slot dimensions/grid of the newsletter
   (px at what DPI?), and whether one publication or several.
2. **Template authoring**: who draws the initial template set — do we
   spec 3–4 standard layouts (logo-left, logo-top, text-only, photo
   card) to ship as defaults?
3. **Approval → billing**: does on-the-spot approval need a price
   quote + signature/payment hook in the capture flow, or is billing
   handled elsewhere in the host app?
4. **Product photos in ads**: v1 ads are vector + text + logo. Placing
   a *photograph* (not vectorized) into a slot means embedding raster
   in the SVG — supported by SVG, but the engine treats it as opaque
   (report-only). Decide if v1 needs photo slots or vector-only.
