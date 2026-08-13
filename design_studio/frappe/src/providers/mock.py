"""Mock provider: deterministic flat-vector-style PNG, zero cost, no
network. All lifecycle tests run against it (SAAS_SPEC M1).
"""

from __future__ import annotations

import io

from .base import BaseProvider, ProviderError


class MockProvider(BaseProvider):
    def generate(self, prompt: str, size: str = "512x512") -> bytes:
        try:
            from PIL import Image, ImageDraw
        except ImportError as exc:  # pragma: no cover
            raise ProviderError("Pillow is required for the mock provider") from exc

        try:
            w, h = (int(v) for v in (size or "512x512").lower().split("x"))
        except ValueError:
            w = h = 512
        w, h = max(64, min(w, 2048)), max(64, min(h, 2048))

        # Flat artwork by construction: surface background, one big
        # primary disc, one accent bar. Exactly the input class the
        # engine is excellent at.
        img = Image.new("RGB", (w, h), "#ffffff")
        draw = ImageDraw.Draw(img)
        cx, cy, r = w // 2, h // 2, min(w, h) // 3
        draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill="#1a56db")
        bar_h = max(8, h // 12)
        draw.rectangle([w // 8, h - 2 * bar_h, w - w // 8, h - bar_h],
                       fill="#f59e0b")

        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()
