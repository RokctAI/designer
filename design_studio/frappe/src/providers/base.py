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

"""Provider interface (SAAS_SPEC section 5)."""

from __future__ import annotations


class ProviderError(Exception):
    """Provider failure with a human-readable message."""


class BaseProvider:
    def __init__(self, doc):
        """``doc`` is the Generation Provider document."""
        self.doc = doc
        self.style_suffix = (getattr(doc, "style_suffix", "") or "").strip()

    def full_prompt(self, prompt: str) -> str:
        """The style suffix is load-bearing: it steers generators toward
        flat vector style, which is what makes engine output excellent."""
        prompt = (prompt or "").strip()
        if self.style_suffix:
            return f"{prompt}, {self.style_suffix}" if prompt else self.style_suffix
        return prompt

    def generate(self, prompt: str, size: str) -> bytes:
        """Return PNG bytes. Raise ProviderError with a human message.

        ``size`` is a "WxH" hint; providers pick their closest supported
        size — the engine rescales precisely onto the target canvas.
        """
        raise NotImplementedError
