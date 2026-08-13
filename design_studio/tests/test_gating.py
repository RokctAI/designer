"""Score gating, best-attempt selection and the request status machine."""

from design_studio_src.lib import gating


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
