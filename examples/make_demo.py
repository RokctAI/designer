# Copyright (c) 2026 ROKCT INTELLIGENCE (PTY) LTD
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

"""Generate the demo input: a synthetic 'AI-generated' logo.

Simulates typical generator artifacts — off-brand colors, gaussian blur
halos, and pixel noise — so the compliance pipeline has something
realistic to clean up:

    python examples/make_demo.py            # writes examples/ai_logo.png
    designer audit examples/ai_logo.png     # ~90/100, off-brand colors listed
    designer comply examples/ai_logo.png -o examples/ai_logo.compliant.svg
"""

from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

OUT = Path(__file__).parent / "ai_logo.png"

rng = np.random.default_rng(7)
img = Image.new("RGB", (512, 512), (240, 241, 246))  # off-brand near-white
draw = ImageDraw.Draw(img)
draw.ellipse((120, 90, 392, 362), fill=(30, 88, 205))      # off-brand blue
draw.ellipse((190, 160, 322, 292), fill=(238, 240, 244))   # cut-out
draw.polygon([(256, 380), (196, 470), (316, 470)], fill=(248, 160, 25))  # off-brand orange
draw.rectangle((100, 480, 412, 500), fill=(20, 24, 33))    # off-brand ink bar
img = img.filter(ImageFilter.GaussianBlur(1.2))            # generator softness
arr = np.asarray(img, dtype=np.int16)
arr = np.clip(arr + rng.integers(-8, 9, arr.shape), 0, 255).astype(np.uint8)  # grain
Image.fromarray(arr).save(OUT)
print(f"Wrote {OUT}")
