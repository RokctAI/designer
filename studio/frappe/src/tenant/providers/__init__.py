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

"""Generation provider registry (SAAS_SPEC 2.4 / 5).

Implemented today: ``upload`` (no generation — the request's attached
artwork is the source) and ``mock`` (deterministic flat PNG, zero cost,
used by all lifecycle tests). ``openai`` / ``stability`` /
``custom_http`` are defined but stubbed: instantiating them works,
``generate`` raises NotImplementedError until the AI-generation
milestone (SAAS_SPEC M3).
"""

from __future__ import annotations

from .base import BaseProvider, ProviderError
from .mock import MockProvider
from .stubs import CustomHttpProvider, OpenAIProvider, StabilityProvider, UploadProvider

_REGISTRY = {
    "upload": UploadProvider,
    "mock": MockProvider,
    "openai": OpenAIProvider,
    "stability": StabilityProvider,
    "custom_http": CustomHttpProvider,
}


def get_provider(doc) -> BaseProvider:
    """``doc`` is a Generation Provider document (or anything exposing
    ``provider_type`` and ``style_suffix``)."""
    ptype = getattr(doc, "provider_type", None) or "upload"
    cls = _REGISTRY.get(ptype)
    if cls is None:
        raise ProviderError(f"Unknown provider type {ptype!r}")
    return cls(doc)


__all__ = ["BaseProvider", "ProviderError", "get_provider"]
