# Copyright (c) 2026 ROKCT INTELLIGENCE (PTY) LTD
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as published
# by the Free Software Foundation, version 3.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with this program. If not, see <https://www.gnu.org/licenses/>.

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
