# Design Studio — Frontend Spec (Next.js) + Prompt Composition

Companion to `SAAS_SPEC.md` (the Frappe module). This spec covers the
user-facing layer: a focused Next.js app — not a full site, only the
studio flows — plus the backend prompt-composition piece it drives.
Written to be implemented incrementally without further context.

**The full loop this enables:**

```
setup design system (UI) ──► one-click generate (prompt composed from tokens)
      ──► provider image ──► engine comply ──► candidates with score + fix log
      ──► user picks ──► guardrailed editor (edits can't break the system)
      ──► SVG / PNG delivery
```

Two properties make the editor cheap to build and safe to expose:

1. Engine output is **structured SVG**: a flat list of shapes with
   token-hex fills, real editable `<text>`, and gradients in `<defs>`.
   No transforms, no nesting, no unknown constructs. A simple SVG DOM
   editor is enough — no canvas engine needed for v1.
2. Every save round-trips the backend's audit, so a user edit that
   drifts off-system is caught (and auto-fixed) immediately. Users can
   change things; they cannot break the brand.

---

## 1. Prompt composition (backend: `prompt_builder.py` in the Frappe module)

Users should not have to write prompts. The design system already knows
the colors and the font; the asset type supplies the template. A typed
brief is an optional refinement, not a requirement.

```python
def build_prompt(system_doc, asset_type: str, brief: str = "",
                 style_suffix: str = "") -> str:
    """Compose the full generation prompt from the design system."""
```

Composition order (all parts joined with commas/periods into one prompt):

1. **Subject** — the user's brief if given, else the default for the
   format's *category* (formats come from the engine catalog):
   | format category | zero-prompt subject template |
   |---|---|
   | brand | `minimal abstract logomark for "{brand_name}"` |
   | social | `bold social media graphic with a single focal shape and short headline space` |
   | print | `poster composition with strong focal point and headline space` |
   | web | `wide banner composition with focal point on one side` |
   | presentation | `clean title-slide background composition` |
   Aspect-ratio guidance is appended from the format's dimensions
   (e.g. `vertical 9:16 composition` for instagram-story).
2. **Palette injection** — name + hex of every color token:
   `using only these exact colors: deep blue #1a56db, amber #f59e0b, near-black #111827, white #ffffff`.
   Generators follow hex hints imperfectly, but they land close — and
   the engine snaps the remainder. Include token names; models parse
   words better than hex alone.
3. **Font hint** — from the primary Design Font's `descriptor` field
   (see §1.1): `any text set in a clean geometric sans-serif similar to
   Inter, tight letterspacing`. The generator will still hallucinate
   the font — but *close* to the brand font, so when the engine's OCR
   swaps in the real font, glyph metrics shift minimally and the layout
   survives. The hallucinated font is disposable by design.
4. **Gradient guidance** — if `gradient_allowed` is off:
   `flat solid colors only, no gradients`; if on, say nothing (the
   engine reconstructs gradients properly either way).
5. **Style suffix** — the provider's `style_suffix` verbatim.

Store the composed prompt on the Design Request in a new field
`composed_prompt` (Small Text, read-only) so every generation is
reproducible and debuggable. `jobs.process_design_request` uses
`composed_prompt`, not raw `prompt`. Regeneration feedback
(`build_feedback`) appends to the composed prompt as before.

### 1.1 Backend additions to SAAS_SPEC DocTypes

- **Design Font** child gains `descriptor` (Data): plain-language
  description used in prompts. Auto-suggest on the frontend from a
  small static map (e.g. Inter/Helvetica/Arial → "clean geometric
  sans-serif"; Georgia/Times → "classic serif"; Poppins → "rounded
  geometric sans-serif"); user-editable.
- **Design System** gains `brand_name` (Data) — used in zero-prompt
  logo subjects.
- **Design Request** gains `composed_prompt` (Small Text, read-only).
- New DocType **Design Candidate Revision** (autoname `DCR-.#####`):
  `candidate` (Link, reqd), `svg` (Attach), `score` (Float),
  `report_json` (Long Text), `edited_by` (Link User). Every editor save
  creates one; the candidate's `compliant_svg` always points at the
  latest passing revision. Gives undo history for free.

### 1.2 Backend API additions (whitelisted, extending SAAS_SPEC §4)

| Method | Args | Returns / behavior |
|---|---|---|
| `generate_quick` | format, design_system=None, brief="" | composes prompt via build_prompt, creates + enqueues a Design Request; returns `{"name"}`. This is the "just click Generate Logo" path. |
| `get_design_system` | name | full JSON: brand_name, tokens `[{name, hex, role}]`, fonts `[{name, descriptor}]`, type_scale, grid, stroke_widths, gradient config, contrast minimums. Drives the editor's constrained controls. |
| `save_candidate_edit` | candidate, svg (string) | parse + **audit** the edited SVG against the request's system. If violations are auto-fixable, run comply and return the fixed SVG. Creates a Design Candidate Revision. Returns `{"svg", "score", "report_json", "revision"}`. Reject (417) only if the SVG is unparseable. |
| `extract_palette` | file_url, n=6 | engine palette extraction from an uploaded image (`designer.raster.quantize` + `palette_report`): returns `[{hex, coverage}]`. Powers "import brand colors from your existing logo" in the setup wizard. |
| `render_png` | candidate, width=1024 | server-side raster of the SVG for downloads/social exports (cairosvg or resvg; optional dependency — return 501 with a clear message if absent and let the frontend fall back to client-side rasterization via canvas). |
| `list_requests` | page, page_size | session user's request history for the studio home. |

Security notes for `save_candidate_edit`: parse with the engine's own
`parse_svg`, which enforces an attribute security policy — event-handler
attributes (`on*`) are stripped, `href`/`xlink:href` values are limited
to `data:image/*`, http(s) and relative targets, and `<script>`/
`<foreignObject>`/unknown elements are dropped (each removal is recorded
in `doc.warnings` and surfaced by the `engine.capability` rule). That
policy is necessary but NOT sufficient on its own: also (a) serve
candidate previews with a restrictive CSP (`script-src 'none'` for the
preview context, or render inside a sandboxed iframe), (b) never store
SVG that failed parsing, and (c) permission-check every call
(candidate's request `requested_by` or Design Manager role). Treat all
uploaded SVG as untrusted even after sanitization.

---

## 2. Next.js app

### 2.1 Stack and integration

- Next.js (app router) + TypeScript + Tailwind + shadcn/ui.
  TanStack Query for data fetching; no global state library needed.
- Deployed on the **same origin** as Frappe behind the existing reverse
  proxy (e.g. `/studio` → Next.js, everything else → Frappe). Auth is
  then just the Frappe session cookie; every call is
  `POST /api/method/<app>.design_studio.api.<method>` with
  `X-Frappe-CSRF-Token`. No CORS, no token plumbing.
  (If a separate domain is ever needed, switch to Frappe API
  key/secret pairs — but same-origin is the default.)
- Realtime progress: poll `get_request_status` every 2s while a request
  is Queued/Processing (simple, robust); upgrade to Frappe socket.io
  later if needed.

### 2.2 Routes

**`/setup` — design system wizard** (first-run and editable later)

1. Brand basics: brand_name.
2. Colors: token list editor — color picker + name + role per row;
   "Import from an image" uploads an existing logo/asset and calls
   `extract_palette`, pre-filling rows the user can rename/trim.
3. Fonts: searchable font select (Google Fonts static list bundled at
   build time — name + category only, no font files needed server-side);
   `descriptor` auto-filled from category, editable. Offer an optional
   "suggest by industry" shortcut: a small static matrix mapping
   industry vertical -> starter font + type-scale defaults (e.g.
   finance -> serif, logistics -> bold geometric sans).
4. Rules: grid, type scale, stroke widths, max colors, gradient
   allowed/max stops, contrast minimums — pre-filled with engine
   defaults inside a collapsed "Advanced" section. Most users never
   open it.
5. Live preview panel (right side, always visible): a sample card
   rendered from the current tokens — background surface, primary
   button, headline in the chosen font (loaded from Google Fonts CDN
   client-side for preview only), accent chip. Updates as they type.

Saves via standard Frappe REST on the Design System DocType.

**`/studio` — generate**

- Format tiles grouped by category, straight from the engine catalog
  (expose it via a `list_formats` whitelisted method that returns
  `designer.formats.all_formats()` as JSON): **Brand** logo, icon —
  **Social** Instagram post/story, X post, Facebook cover, LinkedIn
  banner, YouTube thumbnail — **Print** A4/A3 poster, business card —
  **Web** OG image, display ads — **Presentation** 16:9 slide. Each
  tile shows name + aspect-ratio thumbnail.
- One optional textarea: placeholder *"Optional — describe what you
  want. Leave empty and we'll compose it from your brand."*
- Generate button → `generate_quick` → progress card with per-slot
  status (from get_request_status: attempt counts, scores as they
  stream in). Below: request history via `list_requests`.

**`/studio/[request]` — candidate gallery**

- Grid of candidates: inline SVG preview (render the SVG string
  directly — it's engine-generated and structurally safe), score badge
  (color-coded: ≥95 green, ≥80 amber, else red), PASSED/BEST-EFFORT tag.
- Expandable **"What we fixed"** panel per candidate: rendered from
  `report_json` findings — this is the product's signature moment
  ("snapped 5 colors to your palette, set headline in Inter 64px,
  contrast 8.1:1"). Show fixed items with checkmarks, open items as
  warnings.
- Select button → `select_candidate` → routes to the editor.

**`/studio/campaign/[id]` — campaign board**

One brief fanned out to every chosen format (SAAS_SPEC campaign
fan-out): a responsive grid of format cards, each filling in live as
its derivation/regeneration completes — aspect-true previews, score
badges, per-card "derived from master" or "regenerated" tag. Any card
opens the standard editor. "Download all" exports a zip via repeated
`render_png`.

**`/studio/issues` + `/studio/issues/[id]` — issue flatplan**

Ad-inventory back office for publications (FIELD_ADS_SPEC §4): issue
index with fill % and sales-deadline countdown; per-issue flatplan
board — pages as grids, placements color-coded Hold/Confirmed, drag to
reposition same-size (until Layout Locked), fragmentation hints, and
"Export issue" (all confirmed ads as SVG/PNG named by page/position).

**Field capture is NOT in this app.** The field ad flow is a separate
**Flutter** tablet app (camera-native, offline queue) specified in
`FIELD_ADS_SPEC.md` §5, talking to the same Frappe API. This Next.js
studio remains the back office: design systems, generation, campaign
board, and the full SVG editor (including touch-ups on field-captured
ads when needed).

**`/asset/[candidate]` — guardrailed editor**

Load the SVG string + `get_design_system`. Parse the SVG client-side
into the same flat model the engine emits (shapes list + defs). Render
as controlled React SVG. Controls are **constrained by the design
system** — that's the whole trick:

- Click a shape → side panel shows its properties:
  - fill: swatch row of **token colors only** (from get_design_system).
    No free color picker exists in this UI.
  - stroke width: select from the system's stroke scale.
- Click a `<text>` → edit content inline (contentEditable overlay or
  input in panel); font-size: select from **type scale only**; font:
  select from **system fonts only**; fill: token swatches.
- Drag shapes/text → position snaps to the system grid live
  (round to `grid` on drop).
- Gradient shape selected → per-stop token swatches (stops stay
  token-constrained), angle rotation control.
- Delete shape, reorder z (move up/down in the shapes list).
- Save → `save_candidate_edit` with the serialized SVG. Backend
  re-audits (belt over the frontend's braces), auto-fixes drift,
  returns the canonical SVG + new score; editor swaps its state to the
  returned SVG. Revision history panel from Design Candidate Revisions
  with one-click restore.
- Download: SVG (direct), PNG via `render_png` (fall back to client
  canvas rasterization if the server returns 501).

Post-OCR nuance to handle in the editor: the real brand font's metrics
differ from the hallucinated font's, so replaced text can run wider or
narrower than the space the generator left for it. The editor's
inline-edit + grid-snap drag covers the manual fix; a "fit to width"
button (binary-search font-size within the type scale until the text
fits its original box width, measured via `getComputedTextLength`) is a
cheap, high-value addition — put it in F2.

### 2.3 Components worth naming

`TokenSwatchRow`, `ScoreBadge`, `FixLog(reportJson)`, `SvgStage`
(controlled SVG renderer + selection/drag), `PropertyPanel`,
`SystemPreviewCard` (setup wizard live preview), `FontSelect`,
`PaletteImporter`.

---

## 3. Milestones

**F0 — wizard + wiring.** `/setup` complete against Design System REST +
`extract_palette`. Accept: a new user creates a working design system
in under 3 minutes; `as_engine_dict` round-trips.

**F1 — generate + gallery.** `/studio` and `/studio/[request]` against
`generate_quick`/`get_request_status`/`select_candidate` with the mock
provider. Accept: zero-typed-prompt Logo generation end to end;
composed_prompt visible in a debug expander; fix log renders from
report_json.

**F2 — editor.** `/asset/[candidate]` with constrained controls,
save_candidate_edit round-trip, revisions, fit-to-width. Accept: any
sequence of editor actions keeps score ≥ its pre-edit value (property
test: random edit fuzzing stays compliant after save).

**F3 — polish.** PNG export, request history, mobile-usable gallery,
Frappe socket.io realtime replacing polling.

---

## 4. Prompt-composition backend milestone (belongs with SAAS_SPEC M1)

`prompt_builder.py` + `composed_prompt` field + `generate_quick` +
descriptor field/map. Accept (unit tests, no provider needed):
- empty brief + Logo → prompt contains brand_name, every token hex,
  the font descriptor, and the style suffix;
- brief given → brief leads the prompt, palette/font/style still
  appended;
- `gradient_allowed=0` → prompt contains "no gradients".
