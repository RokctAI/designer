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

"""Campaign fan-out decisions: derive vs regenerate (SAAS_SPEC 5).

``aspect_waste(master, fmt)`` = 1 - (area of the uniformly-scaled
master on fmt's canvas / fmt's canvas area). Deriving (re-complying the
same master artwork onto the target canvas) is always preferred: it is
pure CPU, free, and pixel-consistent across the campaign. Regeneration
is the fallback for extreme aspect changes.
"""

from __future__ import annotations

from typing import Iterable, Mapping

DEFAULT_REGEN_THRESHOLD = 0.35

ACTION_DERIVE = "derive"
ACTION_REGENERATE = "regenerate"


def aspect_waste(master_w: float, master_h: float,
                 fmt_w: float, fmt_h: float) -> float:
    """Fraction of the target canvas left empty when the master is
    uniformly scaled to fit inside it. 0.0 = same aspect, perfect fill."""
    if master_w <= 0 or master_h <= 0 or fmt_w <= 0 or fmt_h <= 0:
        raise ValueError("dimensions must be positive")
    scale = min(fmt_w / master_w, fmt_h / master_h)
    used = (master_w * scale) * (master_h * scale)
    return 1.0 - used / (fmt_w * fmt_h)


def fanout_action(master_w: float, master_h: float,
                  fmt_w: float, fmt_h: float,
                  threshold: float = DEFAULT_REGEN_THRESHOLD) -> str:
    waste = aspect_waste(master_w, master_h, fmt_w, fmt_h)
    return ACTION_DERIVE if waste <= threshold else ACTION_REGENERATE


def plan_fanout(master_size: tuple[float, float],
                targets: Iterable[Mapping],
                threshold: float = DEFAULT_REGEN_THRESHOLD) -> list[dict]:
    """Decide derive-vs-regenerate for every target format.

    ``targets`` items need keys ``format``, ``width``, ``height``.
    Returns [{"format", "action", "waste"}, ...] in input order.
    """
    mw, mh = master_size
    plan = []
    for t in targets:
        waste = aspect_waste(mw, mh, float(t["width"]), float(t["height"]))
        plan.append({
            "format": t["format"],
            "action": ACTION_DERIVE if waste <= threshold else ACTION_REGENERATE,
            "waste": round(waste, 4),
        })
    return plan
