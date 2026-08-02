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
- **Design system as data.** Your standard lives in a YAML file: brand
  color tokens, color cap, font whitelist, modular type scale, spacing
  grid, stroke-width scale, WCAG contrast minimums. The engine enforces
  whatever system you load — nothing is hard-coded.
- **Audit.** Scores any SVG or raster against the system and lists every
  violation with severity (`designer audit design.svg --min-score 90`
  works as a CI gate).
- **Auto-fix.** Snaps every fill/stroke to the perceptually nearest
  brand token, merges palettes over the cap, recolors low-contrast text
  to the best-contrast token, snaps geometry to the spacing grid,
  normalizes stroke widths and font sizes, replaces off-system fonts,
  and deletes sub-minimum "specks" that generators leave behind.

## Install

```bash
pip install -e .
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

# Gate a pipeline: fail CI when a deliverable is off-brand
designer audit deliverable.svg --min-score 95 --json
```

## Defining your design system

```yaml
name: Acme
color:
  tokens:
    primary: "#1a56db"
    accent:  "#f59e0b"
    ink:     "#111827"
    white:   "#ffffff"
  max_colors: 6              # hard cap per deliverable
  snap_warning_distance: 0.18  # OKLab distance where a snap counts as aggressive
typography:
  fonts: [Inter, Helvetica Neue, sans-serif]
  scale: [12, 14, 16, 20, 24, 32, 48, 64]
layout:
  grid: 8                    # spacing grid (px)
  min_element_size: 4        # anything smaller is noise -> removed
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
| `color.max` | distinct colors ≤ cap | merge least-used into nearest kept |
| `layout.grid` | primitives sit on the spacing grid | round to grid |
| `layout.min-size` | no sub-minimum specks | remove |
| `stroke.width` | widths from the stroke scale | snap to nearest |
| `type.font` | fonts from the whitelist | replace with primary font |
| `type.scale` | sizes from the type scale | snap to nearest |
| `a11y.contrast` | WCAG contrast for text | recolor to best-contrast token |
| `geometry.transform` | flags unevaluated transforms | report only |

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

Today the engine covers the production half of a junior designer's job:
take generated art, make it clean, on-brand, accessible and delivery-ready,
deterministically and at scale. The roadmap toward senior-level scope:

- text detection/OCR in rasters so headlines become real `<text>` (editable,
  font-enforced) instead of outlines;
- layout intelligence (alignment, optical spacing, hierarchy scoring);
- gradient and photo-region handling alongside flat vector layers;
- brand-system linting for whole campaigns (cross-deliverable consistency);
- a feedback loop that turns audit findings into regeneration prompts.

## Development

```bash
pip install -e . pytest
python -m pytest tests/ -q
```
