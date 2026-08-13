"""Provider types that exist in the DocType Select but are not wired
yet. Uploaded artwork is the primary path for now; AI generation comes
later (SAAS_SPEC M3).
"""

from __future__ import annotations

from .base import BaseProvider, ProviderError


class UploadProvider(BaseProvider):
    """No generation: the request's attached artwork is the source.

    The pipeline never calls ``generate`` for source_mode "Uploaded
    Artwork"; reaching it means a Generated request was pointed at an
    upload provider, which is a configuration error worth a clear
    message rather than a stack trace.
    """

    def generate(self, prompt: str, size: str) -> bytes:
        raise ProviderError(
            "The 'upload' provider does not generate images. Attach artwork "
            "to the Design Request (source_mode 'Uploaded Artwork') or pick "
            "a generation provider."
        )


class _NotImplementedProvider(BaseProvider):
    """NOT YET IMPLEMENTED — stub path, clearly marked for later.

    When the AI-generation milestone lands, replace ``generate`` with a
    real HTTP client (retry x3 with exponential backoff, ProviderError
    on failure) per SAAS_SPEC section 5.
    """

    label = "provider"

    def generate(self, prompt: str, size: str) -> bytes:
        raise NotImplementedError(
            f"The {self.label!r} generation provider is defined but not yet "
            "implemented. Use source_mode 'Uploaded Artwork' or the 'mock' "
            "provider for now."
        )


class OpenAIProvider(_NotImplementedProvider):
    label = "openai"


class StabilityProvider(_NotImplementedProvider):
    label = "stability"


class CustomHttpProvider(_NotImplementedProvider):
    label = "custom_http"
