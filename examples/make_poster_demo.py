# Copyright (c) 2026 RokctAI
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.

"""Generate the poster demo input: gradient background + text.

Exercises the two hard generator artifacts the engine now solves:
a smooth gradient (would otherwise posterize) and a text headline in
an arbitrary font (generators hallucinate typography; the pipeline
re-emits it as real <text> in the brand font instead of outlines).

    python examples/make_poster_demo.py
    designer comply examples/ai_poster.png -o examples/ai_poster.compliant.svg
"""

from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

OUT = Path(__file__).parent / "ai_poster.png"

W, H = 512, 640
rng = np.random.default_rng(11)

# Vertical off-brand blue -> near-black gradient background.
t = np.linspace(0, 1, H)[:, None, None]
top, bottom = np.array((40, 100, 220)), np.array((15, 20, 35))
arr = (top * (1 - t) + bottom * t).astype(np.uint8)
arr = np.repeat(arr, W, axis=1)

img = Image.fromarray(arr)
draw = ImageDraw.Draw(img)
# Flat off-brand accent badge.
draw.ellipse((356, 60, 460, 164), fill=(250, 165, 30))
# Headline in an arbitrary font (stand-in for hallucinated typography).
font = ImageFont.truetype(
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 56
)
draw.text((48, 420), "SUMMER SALE", font=font, fill=(245, 246, 250))

# Generator grain.
arr = np.asarray(img, dtype=np.int16)
arr = np.clip(arr + rng.integers(-5, 6, arr.shape), 0, 255).astype(np.uint8)
Image.fromarray(arr).save(OUT)
print(f"Wrote {OUT}")
