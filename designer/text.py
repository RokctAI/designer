"""Text extraction: lift text out of the raster and re-set it properly.

Image generators hallucinate typography — invented fonts, warped
glyphs, near-words. Vectorizing that only preserves the mistake as
outlines. Instead, this module OCRs the raster, removes the detected
text pixels (inpainting a plausible background), and returns text spans
so the pipeline can re-emit real, editable SVG <text> — which the
typography rules then force into the design system's font, type scale
and contrast. The hallucinated font never survives; the copy does.

Requires the optional OCR dependency (tesseract binary + pytesseract);
``ocr_available()`` reports whether it's usable at runtime.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from PIL import Image

from designer.color import RGB, delta_e

# Height of a tesseract word box relative to the font's em size, on
# average (caps + typical descenders). Used to estimate font-size.
_BOX_TO_EM = 0.72
# Baseline sits at roughly this fraction of the box height from the top.
_BASELINE_RATIO = 0.8


@dataclass
class TextSpan:
    text: str
    x: float           # left edge of the line
    y: float           # baseline
    font_size: float
    color: RGB
    confidence: float  # mean OCR confidence 0-100


def ocr_available() -> bool:
    try:
        import pytesseract

        pytesseract.get_tesseract_version()
        return True
    except Exception:
        return False


def extract_text(
    img: Image.Image, min_confidence: float = 60.0, lang: str = "eng"
) -> tuple[Image.Image, list[TextSpan]]:
    """OCR the image; returns (image with text regions painted over,
    detected spans). The input image is not modified. ``lang`` is a
    tesseract language spec (e.g. "eng+fra"); the matching traineddata
    must be installed."""
    import pytesseract

    rgb = img.convert("RGB")
    data = pytesseract.image_to_data(
        rgb, config="--psm 11", lang=lang, output_type=pytesseract.Output.DICT
    )

    lines: dict[tuple[int, int, int], list[int]] = {}
    for i in range(len(data["text"])):
        word = (data["text"][i] or "").strip()
        try:
            conf = float(data["conf"][i])
        except (TypeError, ValueError):
            continue
        if not word or conf < min_confidence:
            continue
        if not any(ch.isalnum() for ch in word):
            continue
        key = (data["block_num"][i], data["par_num"][i], data["line_num"][i])
        lines.setdefault(key, []).append(i)

    arr = np.asarray(rgb, dtype=np.uint8).copy()
    spans: list[TextSpan] = []
    for indices in lines.values():
        words = [(data["left"][i], data["top"][i], data["width"][i], data["height"][i],
                  data["text"][i].strip(), float(data["conf"][i])) for i in indices]
        words.sort(key=lambda w: w[0])
        text = " ".join(w[4] for w in words)
        if len(text.replace(" ", "")) < 2:
            continue
        left = min(w[0] for w in words)
        top = min(w[1] for w in words)
        right = max(w[0] + w[2] for w in words)
        bottom = max(w[1] + w[3] for w in words)
        height = bottom - top
        if height < 6 or right - left < 6:
            continue

        color = _text_color(arr, left, top, right, bottom)
        if color is None:
            continue  # no pixels stand out from the background: not text

        spans.append(
            TextSpan(
                text=text,
                x=float(left),
                y=float(top + height * _BASELINE_RATIO),
                font_size=round(height / _BOX_TO_EM, 1),
                color=color,
                confidence=sum(w[5] for w in words) / len(words),
            )
        )
        _erase_box(arr, left, top, right, bottom)

    if not spans:
        return img, []
    out = Image.fromarray(arr).convert(img.mode)
    return out, spans


def _border_ring(arr: np.ndarray, left: int, top: int, right: int, bottom: int, pad: int = 3):
    h, w = arr.shape[:2]
    l, t = max(0, left - pad), max(0, top - pad)
    r, b = min(w, right + pad), min(h, bottom + pad)
    ring = np.concatenate(
        [
            arr[t:top, l:r].reshape(-1, 3) if top > t else np.empty((0, 3), np.uint8),
            arr[bottom:b, l:r].reshape(-1, 3) if b > bottom else np.empty((0, 3), np.uint8),
            arr[top:bottom, l:left].reshape(-1, 3) if left > l else np.empty((0, 3), np.uint8),
            arr[top:bottom, right:r].reshape(-1, 3) if r > right else np.empty((0, 3), np.uint8),
        ]
    )
    return ring


def _text_color(
    arr: np.ndarray, left: int, top: int, right: int, bottom: int
) -> RGB | None:
    """Median color of the glyph pixels: those that differ clearly from
    the local background around the box."""
    ring = _border_ring(arr, left, top, right, bottom)
    if len(ring) == 0:
        return None
    bg = tuple(int(v) for v in np.median(ring, axis=0))
    box = arr[top:bottom, left:right].reshape(-1, 3)
    # Cheap channel-distance prefilter, then perceptual confirmation on
    # the median so one delta_e call decides.
    dist = np.abs(box.astype(np.int16) - np.array(bg, dtype=np.int16)).sum(axis=1)
    glyph = box[dist > 60]
    if len(glyph) < 10:
        return None
    color = tuple(int(v) for v in np.median(glyph, axis=0))
    if delta_e(color, bg) < 0.08:
        return None
    return color


def _erase_box(arr: np.ndarray, left: int, top: int, right: int, bottom: int) -> None:
    """Paint over a text box, interpolating each row between the colors
    just outside its left and right edges so flat and gradient
    backgrounds both heal cleanly."""
    h, w = arr.shape[:2]
    pad = 2
    l, t = max(0, left - pad), max(0, top - pad)
    r, b = min(w, right + pad), min(h, bottom + pad)
    sample = 4
    for row in range(t, b):
        lo = arr[row, max(0, l - sample) : l]
        hi = arr[row, r : min(w, r + sample)]
        left_col = lo.mean(axis=0) if len(lo) else (hi.mean(axis=0) if len(hi) else None)
        right_col = hi.mean(axis=0) if len(hi) else left_col
        if left_col is None:
            continue
        ramp = np.linspace(0, 1, r - l)[:, None]
        arr[row, l:r] = ((1 - ramp) * left_col + ramp * right_col).astype(np.uint8)
