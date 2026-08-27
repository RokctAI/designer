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

"""Score gating, best-attempt selection and the request status machine."""

from studio_src.lib import gating


def test_status_machine_forward_only():
    assert gating.can_transition("Draft", "Queued")
    assert gating.can_transition("Queued", "Processing")
    assert gating.can_transition("Processing", "Ready")
    assert gating.can_transition("Ready", "Delivered")
    for state in gating.REQUEST_STATUSES:
        assert gating.can_transition(state, state)  # no-op allowed
        if state != "Failed":
            assert gating.can_transition(state, "Failed")
    assert not gating.can_transition("Ready", "Queued")
    assert not gating.can_transition("Delivered", "Ready")
    assert not gating.can_transition("Draft", "Ready")
    assert not gating.can_transition("Failed", "Queued")


def test_candidate_passed():
    assert gating.candidate_passed(95, 95)
    assert gating.candidate_passed(100, 95)
    assert not gating.candidate_passed(94.9, 95)
    assert not gating.candidate_passed(None, 95)


def test_clamp_n_candidates():
    assert gating.clamp_n_candidates(3) == 3
    assert gating.clamp_n_candidates(99) == 4
    assert gating.clamp_n_candidates(0) == 1
    assert gating.clamp_n_candidates("2") == 2
    assert gating.clamp_n_candidates(None) == 1
    assert gating.clamp_n_candidates("junk") == 1


def test_best_attempt_keeps_highest_score_earliest_on_tie():
    attempts = [
        {"attempt": 1, "score_after": 82.0},
        {"attempt": 2, "score_after": 97.5},
        {"attempt": 3, "score_after": 97.5},
    ]
    assert gating.best_attempt(attempts)["attempt"] == 2
    assert gating.best_attempt([]) is None
    assert gating.best_attempt([{"attempt": 1, "score_after": None}])["attempt"] == 1


def test_request_outcome():
    assert gating.request_outcome(0) == "Failed"
    assert gating.request_outcome(1) == "Ready"
    assert gating.request_outcome(4) == "Ready"
