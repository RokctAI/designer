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
