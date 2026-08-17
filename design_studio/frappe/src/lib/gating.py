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

"""Score gating, attempt selection and the Design Request status machine.

Pure functions — the pipeline and API call these; tests cover them
without a bench.
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

N_CANDIDATES_CAP = 4

REQUEST_STATUSES = ("Draft", "Queued", "Processing", "Ready", "Delivered", "Failed")

# Single-direction machine (SAAS_SPEC 2.2): any state may go to Failed.
_ALLOWED: dict[str, tuple[str, ...]] = {
    "Draft": ("Queued", "Failed"),
    "Queued": ("Processing", "Failed"),
    "Processing": ("Ready", "Failed"),
    "Ready": ("Delivered", "Failed"),
    "Delivered": ("Failed",),
    "Failed": (),
}


def can_transition(current: str, target: str) -> bool:
    if current == target:
        return True
    return target in _ALLOWED.get(current, ())


def candidate_passed(score_after: float | None, min_score: float) -> bool:
    if score_after is None:
        return False
    return float(score_after) >= float(min_score)


def clamp_n_candidates(n: Any, cap: int = N_CANDIDATES_CAP) -> int:
    try:
        n = int(n)
    except (TypeError, ValueError):
        n = 1
    return max(1, min(n, cap))


def best_attempt(attempts: Sequence[Mapping]) -> Mapping | None:
    """Pick the attempt to keep for a slot: highest score_after wins;
    on a tie the earliest attempt wins (identical quality, less spend
    already sunk — deterministic either way)."""
    best = None
    for att in attempts:
        score = att.get("score_after")
        score = float(score) if score is not None else float("-inf")
        if best is None or score > best[0]:
            best = (score, att)
    return best[1] if best else None


def request_outcome(candidate_count: int) -> str:
    """A request is Failed only if zero candidates were produced."""
    return "Ready" if candidate_count > 0 else "Failed"
