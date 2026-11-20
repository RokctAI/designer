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
