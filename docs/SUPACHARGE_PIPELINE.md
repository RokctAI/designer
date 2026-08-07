# Supacharge expo pipeline

How designer turns the Supacharge exhibition-kit briefs (RokctAI/agent,
`lms/team/marketing/expo/`) into print-ready deliverables, and how it can
watch the tutor-image pipeline.

## The pipeline

```
brief JSON  ──►  image model  ──►  designer comply  ──►  designer audit  ──►  designer render
(briefs/*.json)  (raw PNG)         (vectorize + fix)     (score, CI gate)     (PDF @300dpi / PNG)
```

The briefs are generation specs — final copy, layout direction, brand
pointers — not artwork. An image model produces raw raster candidates;
designer is the compliance layer between that output and the printer.

This covers the kit's **six still assets**: three pull-up banners
(850×2000mm), the A1 poster, the A5 flyer and the A5 table talker. The two
`screen_loop_video` briefs are out of designer's scope (no video support);
their key frames can still be audited as `slide-16x9` rasters.

## Design systems

Two system files encode the two branding candidates. Both derive every
value from the agent repo's branding JSONs — sources are cited inline.

| File | Direction | Source | Status |
|---|---|---|---|
| `designer/systems/supacharge.yaml` | Option A — dark `#0b0b0b` + burnt orange `#e0793c` | `lms/team/marketing/expo/branding.json` | merged on agent main |
| `designer/systems/supacharge-b.yaml` | Option B — cream `#F8F4E8` + marker red `#E84040` | `lms/team/marketing/expo-option-b/branding-b.json` | **pending owner decision** |

Print values (`bleed: 35`, `min_stroke: 1`) are px in the 300dpi space of
the large-format print presets below — 3mm bleed and a ~0.25pt hairline
floor.

## Formats

New presets in `designer/formats.py` for the kit and the app renders:

| Preset | px | Real size | For |
|---|---|---|---|
| `a1-poster` | 7016×9933 | 594×841mm @300dpi | poster brief `SC-EXPO-PO01` |
| `pullup-banner` | 10039×23622 | 850×2000mm @300dpi | the three banner briefs |
| `tutor-card` | 1080×1440 | app px | `card_1080x1440.png` renders |
| `tutor-avatar` | 512×512 | app px | `avatar_512.png` renders |
| `tutor-avatar-small` | 168×168 | app px | `avatar_168.png` renders |
| `onboarding-slide` | 1080×1920 | app px | onboarding `slide_1080x1920.png` |
| `onboarding-card` | 1080×1350 | app px | onboarding `card_1080x1350.png` |

The A5 flyer/table talker fit the existing `a4-poster`-style flow at A5
via `render --dpi`; add an `a5-flyer` preset if format-rule enforcement
at exact A5 canvas is wanted. The banner briefs also call for +100mm
bottom bleed for the cassette — that is asymmetric, so it is handled at
imposition, not by the uniform `print.bleed`.

## Running it

```bash
# 1. Vectorize the model's raw poster and auto-fix onto the brand system
designer comply poster_raw.png -s designer/systems/supacharge.yaml \
    -f a1-poster -o poster.svg

# 2. Gate: score the compliant SVG (CI-friendly exit code)
designer audit poster.svg -s designer/systems/supacharge.yaml \
    -f a1-poster --min-score 90

# 3. Print master: vector PDF at press resolution
designer render poster.svg -o poster.pdf --dpi 300

# Banners: same, with -f pullup-banner
# Auditing option B candidates: swap in -s designer/systems/supacharge-b.yaml
# Auditing a shipped tutor render directly (raster in, no comply step):
designer audit lms/team/tutors/CAPS/tutor_001/appearance/renders/card_1080x1440.png \
    -s designer/systems/supacharge.yaml -f tutor-card
```

Rules that matter for this kit: `color.*` (token snapping — one accent per
surface stays on `#e0793c`/`#E84040`), `typography.*` (Inter whitelist,
kills hallucinated fonts via OCR re-set text), `accessibility.contrast`
(muted text floors on the dark/cream grounds), `format.canvas` /
`format.margin` / `format.min-text` (exact trim size, safe margins,
distance legibility), `print.*` (bleed, hairline floor, ink coverage).

## Proposal: audit step in agent's `tutor_images.yml` (non-blocking)

The agent repo's workflow derives app renditions from source portraits
and commits them. A designer audit slotted after the render step would
attach a compliance report without gating anything — the owner reviews
tutor images by eye; designer flags, never rejects:

```yaml
# after "Derive renditions", before "Commit renditions"
- name: Designer audit (report only)
  continue-on-error: true            # flags, never rejects
  run: |
    python -m pip install --quiet git+https://github.com/RokctAI/designer
    for f in lms/team/tutors/CAPS/*/appearance/renders/card_1080x1440.png; do
      echo "== $f"
      designer audit "$f" -s "$(python -c 'import designer, pathlib; \
        print(pathlib.Path(designer.__file__).parent / "systems/supacharge.yaml")')" \
        -f tutor-card --json || true
    done | tee designer-audit.txt
- name: Upload audit report
  uses: actions/upload-artifact@v4
  with: { name: designer-audit, path: designer-audit.txt }
```

Notes for whoever wires it in: photographic portraits will always score
low on palette-cap findings (a photo is not token art) — the useful
signals are canvas mismatches, stray margins/specks and any text that
sneaks into a render. `--min-score` is deliberately absent and
`continue-on-error` is set: the step must never block the commit step.
This is a proposal only; the agent workflow is not modified by this
repository.
