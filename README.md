# designer — AI design, brand compliance enforced by code

AI models can generate a logo or a poster, but you can *tell* AI made it:
off-brand colors, noisy edges, random spacing, no standard applied. This
project is the missing layer between the generator and the deliverable —
a **design-system compliance engine** that turns raw AI raster output
into clean, brand-compliant vector artwork, the way a (very patient)
production designer would.

```
AI image  ──►  vectorize  ──►  audit against design system  ──►  auto-fix  ──►  compliant SVG
(noisy PNG)    (clean paths)   (score /100 + findings)          (snap, fix)     (production-ready)
```

## What it does

- **Raster → vector.** Reduces an AI-generated image to flat color
  layers (adaptive quantization + perceptual merging in OKLab), traces
  exact pixel boundaries into closed loops, simplifies them
  (Douglas–Peucker) and fits smooth Bézier curves while preserving sharp
  corners. Output is resolution-independent SVG with no external tracer
  needed.
- **Gradient reconstruction.** Smooth gradients quantize into stacks of
  color bands; instead of shipping that posterization, the engine
  detects band chains whose colors form a ramp in OKLab, classifies
  them linear or radial from their spatial arrangement, and emits one
  shape filled with a real SVG `<linearGradient>`/`<radialGradient>` —
  whose stops are then token-snapped like any other color.
- **Text extraction (OCR).** Generators hallucinate typography. With
  tesseract installed, text is OCR'd out of the raster, its pixels are
  inpainted away, and the copy is re-emitted as real, editable SVG
  `<text>` — which the typography rules force into the brand font, type
  scale and contrast. The hallucinated font never survives; the words do.
- **Deliverable formats — beyond logos.** A built-in catalog of real
  deliverables (`designer formats`): Instagram post/story, X post,
  YouTube thumbnail, LinkedIn/Facebook banners, OG image, A4/A3
  posters, business card, display ads, slides — plus large-format and
  folded print: `signboard-2000x800` (150dpi grand format),
  `z-fold-a4` (three panels, fold-in panel 2mm narrower),
  `corporate-folder-a4` (5mm capacity spine + pocket panel). Passing
  `--format instagram-story` rescales the artwork onto the exact
  target canvas (paths, gradients and text transformed together) and
  enforces per-format safe margins and minimum legible text size —
  plus a text-hierarchy check for multi-text layouts. Your design
  system YAML can add brand-specific formats (`formats:` block, mm or
  px) that merge into the catalog.
- **Print & screen output.** `designer render art.svg -o ad.pdf`
  writes a real vector PDF (embedded TrueType fonts, axial/radial
  shadings, Flate images, optional CMYK) — and `-o card.png` rasterizes
  with supersampled antialiasing, even-odd holes and gradients. No
  cairo, no headless browser, no external binaries.
- **Press-ready PDF geometry.** For print formats with a bleed, the
  page grows to trim + bleed + slug and the PDF carries crop marks,
  registration marks (drawn on every separation in CMYK), dashed fold
  marks at panel boundaries, a job slug line, and proper
  MediaBox/TrimBox/BleedBox (`--marks/--no-marks`). Several inputs
  make one multi-page PDF: `designer render front.svg back.svg -o
  board.pdf` for double-sided boards and folded pieces.
- **ICC-managed CMYK.** Point `print.icc_profile` at your printer's
  CMYK profile and `--cmyk` converts fills, strokes, gradient stops
  and embedded images through it, embedding the profile as the PDF's
  output intent — a press PDF with output intent (not a validated
  PDF/X file). Without a profile the conversion is naive and the
  output is explicitly reported as an unmanaged proof.
- **Dieline passthrough.** A group or shape with id/class `dieline`
  (gazebo panels, pens, folders) is never audited or auto-fixed,
  renders stroke-only in a dedicated color, and in CMYK PDFs strokes a
  `CutContour` spot separation with overprint — the way cutter vendors
  expect to receive it.
- **Templates.** A slot-marked SVG plus captured content renders a
  finished design in milliseconds — text fitted to its box with real
  glyph metrics, size-inappropriate slots dropped (small ads lose the
  logo, not the message), and repeated items flowed into a legibility-
  floored grid that refuses to shrink below readable rather than
  silently cramming.
- **Layout quality — the measurable half of taste.** Collision (text on
  text, text buried under a later opaque shape), near-miss alignment,
  spacing rhythm, visual balance and whitespace are all checked;
  collisions and alignment are auto-fixed, composition is reported.
- **Design system as data.** Your standard lives in a YAML file: brand
  color tokens, color cap, font whitelist, modular type scale, spacing
  grid, stroke-width scale, WCAG contrast minimums. The engine enforces
  whatever system you load — nothing is hard-coded.
- **Audit.** Scores any SVG or raster against the system and lists every
  violation with severity (`designer audit design.svg --min-score 90`
  works as a CI gate).
- **Auto-fix.** Snaps every fill/stroke to the perceptually nearest
  brand token **for its role** (a full-bleed background lands on a
  surface color, never a bright accent), merges palettes over the cap, recolors low-contrast text
  to the best-contrast token, snaps geometry to the spacing grid,
  normalizes stroke widths and font sizes, replaces off-system fonts,
  and deletes sub-minimum "specks" that generators leave behind.

## Install

```bash
pip install -e .
# with OCR text extraction (also needs the tesseract binary):
#   apt-get install tesseract-ocr && pip install -e ".[ocr]"
```

## Quickstart

```bash
# What does the standard look like?
designer tokens

# Score raw AI output (it will not pass)
designer audit ai_logo.png

# One command: vectorize + enforce the design system
designer comply ai_logo.png -o ai_logo.svg
#   Score before fixes : 90.0/100
#   Score after fixes  : 100.0/100

# Enforce your own brand
designer comply poster.png --system brand/acme.yaml -o poster.svg

# Target a real deliverable: exact canvas, safe margins, legible text
designer formats
designer comply art.png --format instagram-story -o story.svg

# Gate a pipeline: fail CI when a deliverable is off-brand
designer audit deliverable.svg --min-score 95 --json

# Deliver it: press PDF with marks, or a raster for the web
designer render art.svg -o ad.pdf --format a4-poster --cmyk --comply
designer render art.svg -o card.png --width 1200

# Double-sided signboard: two pages, shared format, marks on both
designer render front.svg back.svg -o board.pdf --format signboard-2000x800 --cmyk
```

## Start from two colours

No design system yet? Derive one from your brand colours:

```bash
designer palette "#0F4C81" "#F5A623" --name client-x -o system.yaml
# 2-3 seeds: primary, accent, optional secondary
```

Working in OKLCH, the engine derives everything else a system needs:
an ink (near-black tinted toward the primary hue), paper and surface
tones, text colours adjusted until they actually pass the WCAG contrast
minimums (real ratios, printed in the swatch summary), a 4-step neutral
scale of the primary, plus sensible typography, layout, stroke and
print defaults (3 mm bleed at 300 dpi). The YAML it writes is a
complete, ready-to-edit design system — pass it anywhere via
`--system system.yaml`. From Python, `derive_system(seeds,
overrides={...})` deep-merges the overrides last, so every derived
value can be replaced.

## Defining your design system

```yaml
name: Acme
color:
  tokens:
    # "name: #hex", or give a role so snapping respects intent
    primary: { hex: "#1a56db", role: primary }
    accent:  { hex: "#f59e0b", role: accent }
    ink:     { hex: "#111827", role: ink }
    white:   { hex: "#ffffff", role: surface }
  max_colors: 6              # hard cap per deliverable
  snap_warning_distance: 0.18  # OKLab distance where a snap counts as aggressive
typography:
  fonts: [Inter, Helvetica Neue, sans-serif]
  scale: [12, 14, 16, 20, 24, 32, 48, 64]
gradient:
  allowed: true              # false = gradients get flattened to a token
  max_stops: 4
layout:
  grid: 8                    # spacing grid (px)
  min_element_size: 4        # anything smaller is noise -> removed
  alignment_tolerance: 2     # edges within this should align exactly
print:                       # enforced for print formats only
  bleed: 9                   # px past trim for full-bleed artwork
  min_stroke: 0.75           # thinnest line the press can hold
  max_ink_coverage: 240      # total CMYK ink %
  # Your printer's CMYK ICC profile (never bundled — profiles are
  # licensed). Set: --cmyk converts through it and embeds it as the
  # PDF output intent. Unset: naive conversion, reported as unmanaged.
  icc_profile: profiles/press.icc
formats:                     # brand formats merged into the catalog
  shelf-strip:
    unit: mm                 # mm converts at the format's dpi (default px)
    dpi: 300
    width: 1000
    height: 60
    category: print
    bleed: 3                 # overrides print.bleed for this format
    panels: [250, 250, 250, 250]   # fold marks at panel boundaries
stroke:
  widths: [1, 2, 4, 8]
accessibility:
  min_contrast_text: 4.5     # WCAG AA
  min_contrast_large_text: 3.0
  large_text_size: 24
```

## The rules

| Rule | Enforces | Auto-fix |
|---|---|---|
| `color.palette` | every fill/stroke is a brand token | snap to nearest token (OKLab) |
| `color.gradient` | gradients allowed? stops are tokens; stop count ≤ cap | snap/thin stops, or flatten to a token |
| `color.max` | distinct colors ≤ cap (gradient stops included) | merge least-used into nearest kept |
| `layout.grid` | primitives sit on the spacing grid | round to grid |
| `layout.min-size` | no sub-minimum specks | remove |
| `stroke.width` | widths from the stroke scale | snap to nearest |
| `type.font` | fonts from the whitelist | replace with primary font |
| `type.scale` | sizes from the type scale | snap to nearest |
| `a11y.contrast` | WCAG contrast for text vs its **local** background | recolor to best-contrast token |
| `type.hierarchy` | multi-text layouts span ≥2 scale levels | report only |
| `format.canvas` | canvas matches the target format | rescale + center onto format |
| `format.margin` | text inside the format's safe margin | move inside (grid-aligned) |
| `format.min-text` | text ≥ the format's legibility floor | bump to on-scale size |
| `layout.collision` | text not overlapped or buried | move clear of the overlap |
| `layout.alignment` | near-aligned edges share an exact coordinate | snap to the shared edge |
| `layout.rhythm` | gaps follow the spacing scale | report only |
| `layout.balance` | composition isn't lopsided | report only |
| `layout.whitespace` | the layout has room to breathe | report only |
| `print.hairline` | strokes survive the press (print formats) | raise to the press minimum |
| `print.bleed` | edge artwork extends past trim (print formats) | extend into the bleed |
| `print.ink` | total ink within the press limit (print formats) | report only |
| `geometry.transform` | flags transforms that couldn't be baked | report only |
| `engine.capability` | constructs the audit couldn't evaluate are reported | report only |

All color math runs in **OKLab**, so "nearest color" matches human
perception, and contrast checks implement **WCAG 2.x** exactly.

## Python API

```python
from designer import ComplianceEngine, load_system
from designer.svg import save

engine = ComplianceEngine(load_system("brand/acme.yaml"))
doc = engine.load("ai_poster.png")     # rasters are vectorized automatically
report = engine.comply(doc)            # audit + fix in place
print(report.score, report.to_text())
save(doc, "poster.svg")
```

## Where this is headed

- semantic layer annotation via a vision model — tagging regions as
  icon / wordmark / decoration so they move as units in editors, and
  reading stylized display type that OCR cannot;
- brand-system linting for whole campaigns (cross-deliverable consistency);
- a feedback loop that turns audit findings into regeneration prompts;
- full PDF/X-4 conformance (XMP metadata, validated output conditions)
  on top of the current press PDF with output intent.

## Known limitations (verified by adversarial testing)

Honesty is a feature. What the engine cannot do, it says so about —
in the report, not just in this file.

- **Photographs are embedded, not traced.** Photographic regions become
  `<image>` elements and are excluded from the audit (their content is
  not brand-checked). An image that is photographic end to end is
  refused with a clear `ComplexityError` — it is a photo, not a design.
- **OCR reads flat and tilted text, not arced or heavily stylized
  type.** The rotation sweep covers roughly ±25°; curved baselines and
  decorative display faces still fall through to vector outlines. Busy
  backgrounds degrade recognition, and non-English needs the tesseract
  language pack plus `--ocr-lang`. Whenever OCR is unavailable or a
  construct is skipped, the report says so (`engine.capability`).
- **`clipPath`/`mask`/`filter` are preserved but not evaluated.** They
  round-trip so rendering stays faithful, and each raises a capability
  finding, so an audit can never silently pass art it did not see.
  `<use>`, CSS `<style>` rules and transforms *are* resolved. Compound
  CSS selectors (`text.brand`) and rotated primitives that cannot be
  baked are reported rather than guessed at.
- **Gradients:** linear and radial (including diagonal, subtle and
  off-center) are reconstructed, and flat color-blocking is rejected by
  a smoothness test; conic and mesh gradients still posterize.
- **CMYK is only color-managed when you supply a profile.** With
  `print.icc_profile` set, conversion runs through littlecms and the
  profile ships in the PDF as its output intent — but the file is
  *not* validated PDF/X and the engine does not claim it is. Without
  a profile the conversion is naive: adequate for a proof and the
  ink-coverage sanity check, and reported as unmanaged.
- **Fonts must be installed to be measured or rendered.** A missing
  family falls back to a substitute face and the difference is
  reported, never silently applied.
- **Composition judgment is reported, not fixed.** Balance, rhythm,
  whitespace and hierarchy describe the layout; only collisions and
  near-miss alignment are repaired automatically, because those have a
  single correct answer and the others are a designer's call.

## Development

```bash
pip install -e . pytest
python -m pytest tests/ -q
```

## Agency workflow: seeds to identity drop

The full agency pipeline — seed colours in; system YAML, three proof
variations, press PDFs (CMYK + marks, front/back multi-page) and the
brand manual out:

```bash
python examples/agency_demo.py "#0F4C81" "#F5A623" \
    --name "Demo Trading (Pty) Ltd" -o demo-out/
designer brandbook --system demo-out/system.yaml \
    --logo demo-out/logo.svg -o demo-out/brandbook.pdf
```

Walkthrough in [docs/AGENCY_WORKFLOW.md](docs/AGENCY_WORKFLOW.md); the
role-driven template pack is documented in
[examples/templates/agency/README.md](examples/templates/agency/README.md).
The same conventions drive the 16:9 pitch-deck pack
([examples/templates/pitch-deck/README.md](examples/templates/pitch-deck/README.md))
that feeds the StartupOS deck generator — pipeline in
[docs/STARTUPOS_PIPELINE.md](docs/STARTUPOS_PIPELINE.md) — and the A4
company-profile pack
([examples/templates/company-profile/README.md](examples/templates/company-profile/README.md)),
the visual target for the studio's most-requested tender returnable.

## Agency operations layer

`studio/` is a Frappe app fragment (agency-as-a-service shell around this engine): see [studio/README.md](studio/README.md).
