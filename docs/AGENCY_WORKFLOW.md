# Agency workflow: seeds to signed-off identity drop

The agency stack turns 2-3 seed colours plus the client's contact
details into the complete small-business identity package: derived
design system, client proofs, press-ready PDFs and the brand manual.
Everything is deterministic — same inputs, same bytes — and every
artifact goes through the same engine (`derive_system` ->
slot-marked templates -> `render_png`/`render_pdf`).

## One command

```bash
python examples/agency_demo.py "#0F4C81" "#F5A623" \
    --name "Demo Trading (Pty) Ltd" \
    --tagline "Import. Export. Delivered." \
    --phone "+27 11 555 0123" --email hello@demotrading.co.za \
    --address "12 Harbour Rd, Durban" \
    -o demo-out/
```

Output tree:

```
demo-out/
  system.yaml                     # the derived design system (b)
  logo.svg / logo.png             # generated monogram placeholder
  proofs/                         # client proofs (c)
    card-brand.png    flyer-brand.png       # seeds as given
    card-inverted.png flyer-inverted.png    # primary/accent swapped
    card-midtone.png  flyer-midtone.png     # OKLab-midpoint accent
  press/                          # press PDFs, CMYK + bleed + marks (d)
    business-card-90x50.pdf       # 2 pages: front + back
    z-fold-a4.pdf                 # panel-aware, fold marks
    signboard-2000x800.pdf        # 2 pages: front + back
  brandbook.pdf                   # the brand manual (e)
```

## The stages

1. **Derive the system** — `derive_system(seeds, overrides=...)`
   produces the full token set (ink/paper/surface/text with WCAG-passing
   contrast, neutral scale) from the seeds. The demo overrides two
   things: the typography scale becomes the print ladder
   `designer.template.AGENCY_TYPE_SCALE`, and a `formats:` block adds
   the custom `business-card-90x50` and `flyer-a5` formats. The dict is
   written to `system.yaml`, so from here on **every** tool takes
   `--system demo-out/system.yaml`.

2. **Proof variations** — three deterministic palette treatments
   (as-given, inverted, OKLab-midpoint accent) each derive their own
   system; the same templates re-render under each because templates
   bind fills to palette roles (`data-token="advertiser-N"`, order in
   `AGENCY_PALETTE_ROLES`), never to hex values.

3. **Press PDFs** — templates are filled via `designer.template.render`
   (text fitted with real font metrics, empty slots vanish) and handed
   to `render_pdf(docs, ..., cmyk=True, format=spec, bleed=..., marks=True)`:
   multi-page front/back files, crop + registration marks, fold marks
   at the z-fold's 100/99/98 mm panel boundaries, TrimBox/BleedBox, and
   a job slug naming the colorspace. Set `print.icc_profile` in the
   system YAML to get color-managed CMYK with an embedded output
   intent; without it the conversion is naive and labeled unmanaged.

4. **Brand manual** — `designer brandbook --system demo-out/system.yaml
   --logo demo-out/logo.svg -o demo-out/brandbook.pdf` (the demo calls
   the same code). Cover, logo page with clear-space guide, swatches
   with HEX/RGB/CMYK and the guaranteed contrast table, the type scale
   at actual size, and the production specs — typeset in the system's
   own tokens.

## The template pack

`examples/templates/agency/` documents its own conventions
([README](../examples/templates/agency/README.md)): shared slots
(`business-name`, `tagline`, `phone`, `email`, `address`, `logo`),
palette-role tokens, trim-size canvases with bled backgrounds, and
panel-aware layouts for the folded formats. Adding a deliverable to
the drop = one slot-marked SVG plus (if it's a new size) one
`formats:` entry.
