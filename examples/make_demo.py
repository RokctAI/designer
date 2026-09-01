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
