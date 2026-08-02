# Example: raw AI output in, compliant vector out

| File | What it is |
|---|---|
| `make_demo.py` | Generates the demo input — a synthetic "AI-generated" logo with off-brand colors, blur halos and pixel noise |
| `ai_logo.png` | **Input**: the raw raster, as an image generator would emit it |
| `audit_before.txt` | `designer audit` on the raw input — scores 90/100, lists every off-brand color and its nearest token |
| `ai_logo.compliant.svg` | **Output** of `designer comply` — clean vector paths, every color snapped to a brand token, 100/100 |
| `comply_output.txt` | The comply run's report: what was found and what fix was applied |

## Second example: gradient + hallucinated typography

| File | What it is |
|---|---|
| `make_poster_demo.py` | Generates `ai_poster.png`: a smooth gradient background plus a text headline in an arbitrary font |
| `ai_poster.png` | **Input**: the kind of output where naive vectorization posterizes the gradient and fossilizes the fake font as outlines |
| `ai_poster.compliant.svg` | **Output**: one real `<linearGradient>` with token-snapped stops, and the headline as editable `<text>` in the brand font (score 67 -> 100) |
| `poster_comply_output.txt` | The comply run's report |

Reproduce:

```bash
python examples/make_demo.py
designer audit  examples/ai_logo.png --colors 5
designer comply examples/ai_logo.png -o examples/ai_logo.compliant.svg --colors 5
```
