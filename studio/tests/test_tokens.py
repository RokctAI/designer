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

"""Approval-link token generation and expiry."""

from datetime import datetime, timedelta

from studio_src.lib import tokens as lib


def test_tokens_are_random_urlsafe_and_long():
    seen = {lib.generate_review_token() for _ in range(50)}
    assert len(seen) == 50
    for token in seen:
        assert len(token) >= 40
        assert all(c.isalnum() or c in "-_" for c in token)


def test_tokens_equal_constant_time_compare():
    token = lib.generate_review_token()
    assert lib.tokens_equal(token, token)
    assert not lib.tokens_equal(token, token[:-1] + "x")
    assert not lib.tokens_equal(token, "")
    assert not lib.tokens_equal(None, token)


def test_expiry():
    now = datetime(2026, 1, 1, 12, 0)
    assert lib.default_expiry(now) == now + timedelta(days=14)
    assert lib.default_expiry(now, days=2) == now + timedelta(days=2)
    assert not lib.token_expired(now + timedelta(seconds=1), now)
    assert lib.token_expired(now, now)
    assert lib.token_expired(now - timedelta(days=1), now)
    assert not lib.token_expired(None, now)  # no expiry set = never


def test_decisions():
    for good in ("Approved", "Rejected", "Changes Requested"):
        assert lib.is_valid_decision(good)
    for bad in ("approved", "", None, "Pending", "yes"):
        assert not lib.is_valid_decision(bad)
