# StartupOS pitch-deck pipeline

How designer turns a founder's brand inputs (RokctAI/The-Rokct-Protocol,
StartupOS) into the deck-ready assets its 12-slide `.pptx` generator
consumes, and where the hand-off between the two repos sits.

## The pipeline

```
questionnaire  ──►  designer palette  ──►  system.yaml     ──►  designer brandbook
(brand colours)     (derive system)        (brand/)             (brandbook.pdf)

logo upload    ──►  designer comply   ──►  designer audit  ──►  designer render
(raster PNG)        (vectorize + fix)      (score, gate)        (logo.svg / logo.png)

pitch-deck templates + system.yaml ──► template.render ──► designer audit ──► designer render
(examples/templates/pitch-deck/)       (fill slots)         (-f slide-16x9)    (slide PNGs 1920×1080)
```

Everything lands in the StartupOS instance's `brand/` folder; the
StartupOS generator embeds the PNGs into its `.pptx`. Designer produces
and polices the assets — it does not write PowerPoint files, and it does
not generate images. Where a slide wants a photographic hero or
background, an image model produces the raster and designer is the
compliance layer between that output and the deck (same shape as the
Supacharge kit, `docs/SUPACHARGE_PIPELINE.md`).

## What exists today vs. the bridge

| Step | Where | Status |
|---|---|---|
| Seed colours → full design system YAML (`designer palette`) | this repo | exists |
| Brand manual PDF (`designer brandbook`) | this repo | exists |
| Raster logo → clean SVG on the system (`designer comply`) | this repo | exists |
| Compliance gate (`designer audit --min-score`) | this repo | exists |
| Deck-ready exports (`designer render` → PNG/SVG/PDF) | this repo | exists |
| 16:9 slide templates (`examples/templates/pitch-deck/`) | this repo | exists |
| `slide-16x9` format preset (1920×1080, 5% margin, 18px text floor) | this repo | exists |
| A4 company-profile templates (`examples/templates/company-profile/`, `a4-poster` preset) — the visual target for the `company_profile` tender returnable | this repo | exists |
| Founder questionnaire → seed colours + logo upload | StartupOS | bridge, in review |
| Calling designer and writing outputs into `brand/` | StartupOS | bridge, in review |
| Embedding `brand/` assets into the 12-slide `.pptx` | StartupOS | bridge, in review |
| Fragment-side StartupOS seam (`studio/frappe/src/tenant/startupos_bridge.py`: compile suite, export briefs, provision `questions.md`) | this repo (studio fragment) | exists |
| Document Request pipeline (exec compiles the suite from Frappe) | this repo (studio fragment) | exists |
| Brief JSONs → Design Campaign (`create_campaign_from_briefs`) | this repo (studio fragment) | exists |
| Image-model heroes/backgrounds for slides | image model | out of designer's scope; designer audits/complies the output |

## Design system

The founder questionnaire yields 2–3 brand colours; `designer palette`
derives the full system — WCAG-passing text colours, neutrals,
typography, layout — and writes the YAML that every later step takes
via `--system`:

```bash
designer palette "#0F4C81" "#F5A623" --name "Acme (Pty) Ltd" -o brand/system.yaml
designer brandbook -s brand/system.yaml --logo brand/logo.svg -o brand/brandbook.pdf
```

## Logo processing

The uploaded logo is a raster; the deck (and the brandbook) want a
clean vector snapped to the system, plus a PNG rendition:

```bash
# vectorize + auto-fix onto the founder's system, then gate
designer comply logo_upload.png -s brand/system.yaml -o brand/logo.svg
designer audit brand/logo.svg -s brand/system.yaml --min-score 90

# deck-ready raster rendition
designer render brand/logo.svg -o brand/logo.png --width 1024
```

## Slides

The pitch-deck pack (`examples/templates/pitch-deck/`, conventions in
its README) covers the generator's 12 slides with four templates:

| StartupOS slide | Template |
|---|---|
| Title | `slide-title.svg` |
| Problem, Solution, GTM, Competition, Team, Corporate Standing | `slide-content.svg` |
| Market, Business Model, Traction, Financials | `slide-data.svg` (+ `stat-cell.svg` metrics) |
| Ask | `slide-closing.svg` |

Filling is the deterministic `designer.template.render` path — slots,
`palette_for_system`, shrink-fitting — then the standard gate and
export:

```python
from designer.svg import parse_svg, save
from designer.template import TemplateData, palette_for_system, render
from designer.tokens import load_system

system = load_system("brand/system.yaml")
data = TemplateData(
    fields={"business-name": "Acme (Pty) Ltd", "tagline": "One honest sentence"},
    palette=palette_for_system(system),
    images={"logo": "brand/logo.png"},
)
save(render(parse_svg("examples/templates/pitch-deck/slide-title.svg"),
            data, system), "title.svg")
```

```bash
designer audit title.svg -s brand/system.yaml -f slide-16x9 --min-score 90
designer render title.svg -o brand/slides/01-title.png --width 1920

# Image-model hero/background candidates gate the same way:
designer comply hero_raw.png -s brand/system.yaml -f slide-16x9 -o hero.svg
designer audit hero.svg -s brand/system.yaml -f slide-16x9
```

Rules that matter for the deck: `color.*` (token snapping onto the
derived palette), `type.font` / `type.scale` (the derived system's
fonts and the screen scale), `a11y.contrast` (ink-on-surface floors —
the pack deliberately puts no text on primary fills, so role-poor dark
systems audit clean), `format.canvas` / `format.margin` /
`format.min-text` (exact 1920×1080, 5% safe margin, 18px floor).

Photographic heroes will always score low on palette-cap findings (a
photo is not token art) — as with the Supacharge tutor renders, the
useful signals there are canvas mismatches and stray text, so gate
heroes on those, not on `--min-score`.

## The `brand/` contract

The StartupOS bridge (in review in the protocol repo) owns the folder;
designer only defines what lands in it:

```
brand/
  system.yaml       # designer palette output — the single source of truth
  brandbook.pdf     # designer brandbook
  logo.svg          # designer comply output (vector master)
  logo.png          # designer render rendition
  slides/*.png      # rendered, audited 1920×1080 slide art
```

The `.pptx` step consumes `slides/*.png` as full-slide images (or
backgrounds behind live text boxes — the generator's call); designer's
guarantee stops at "every asset in `brand/` passed the audit against
`system.yaml`".
