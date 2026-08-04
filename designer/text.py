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

import math
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
    angle: float = 0.0  # degrees clockwise; non-zero for tilted headlines


def ocr_available() -> bool:
    try:
        import pytesseract

        pytesseract.get_tesseract_version()
        return True
    except Exception:
        return False


def extract_text(
    img: Image.Image,
    min_confidence: float = 60.0,
    lang: str = "eng",
    angles: tuple[float, ...] = (0.0, -8.0, 8.0, -15.0, 15.0, -25.0, 25.0),
) -> tuple[Image.Image, list[TextSpan]]:
    """OCR the image, sweeping rotations so tilted headlines are found.

    Generators love setting headlines on an angle, and upright-only OCR
    misses them entirely — the text then survives as vector outlines,
    which is exactly what this module exists to prevent.

    Every angle is read independently from the *original* image, then
    the candidates compete: the longest, most confident reading of a
    region wins and overlapping weaker readings are discarded. Without
    that arbitration a tilted line comes back shredded into fragments
    that each matched at a different angle.

    Returns (image with detected text painted out, spans). The input is
    not modified.
    """
    candidates: list[Candidate] = []
    for angle in angles:
        candidates.extend(_candidates_at_angle(img, min_confidence, lang, angle))

    # Longer, more confident readings win. Upright gets an explicit
    # bonus: a tilted pass often reads the same words with a marginally
    # higher score but an inflated box, and upright is the truth when
    # both can read it.
    def score(c: Candidate) -> float:
        letters = len(c.span.text.replace(" ", ""))
        upright_bonus = 1.15 if abs(c.angle) < 1e-6 else 1.0
        return c.span.confidence * math.sqrt(max(1, letters)) * upright_bonus

    candidates.sort(key=score, reverse=True)

    accepted: list[Candidate] = []
    for candidate in candidates:
        letters = len(candidate.span.text.replace(" ", ""))
        if letters < 2:
            continue
        if abs(candidate.angle) > 1e-6 and letters < 3:
            continue  # short fragments off-axis are almost always noise
        # Arbitration happens in ORIGINAL coordinates — boxes from
        # different rotations are not otherwise comparable.
        if any(
            _boxes_overlap(candidate.origin_box, other.origin_box) for other in accepted
        ):
            continue
        accepted.append(candidate)

    if not accepted:
        return img, []

    # Erase per angle, in that angle's own frame, so tilted runs are
    # removed cleanly rather than by an oversized upright rectangle.
    working = img.convert("RGB")
    for angle in sorted({c.angle for c in accepted}):
        boxes = [c.box for c in accepted if c.angle == angle]
        working = _erase_at_angle(working, boxes, angle)

    spans = [c.span for c in accepted]
    spans.sort(key=lambda s: (s.y, s.x))
    return working.convert(img.mode), spans


Box = tuple[float, float, float, float]  # left, top, right, bottom


@dataclass
class Candidate:
    """One OCR reading: the span in original coordinates, the box to
    erase (in the rotated frame it was read in), the angle, and the box
    in original coordinates used to arbitrate against other readings."""

    span: TextSpan
    box: Box
    angle: float
    origin_box: Box


def _boxes_overlap(a: Box, b: Box) -> bool:
    return not (a[2] <= b[0] or b[2] <= a[0] or a[3] <= b[1] or b[3] <= a[1])


def _rotated_copy(img: Image.Image, angle: float) -> Image.Image:
    return img.convert("RGB").rotate(
        angle, resample=Image.BICUBIC, expand=True, fillcolor=_edge_color(img)
    )


def _candidates_at_angle(
    img: Image.Image, min_confidence: float, lang: str, angle: float
) -> list[Candidate]:
    """Read text at one rotation, mapped back to original coordinates."""
    if abs(angle) < 1e-6:
        spans, boxes = _read(img, min_confidence, lang)
        return [
            Candidate(span=s, box=b, angle=0.0, origin_box=b)
            for s, b in zip(spans, boxes)
        ]

    rotated = _rotated_copy(img, angle)
    spans, boxes = _read(rotated, min_confidence, lang)
    if not spans:
        return []

    theta = math.radians(-angle)
    rcx, rcy = rotated.width / 2, rotated.height / 2
    ocx, ocy = img.width / 2, img.height / 2

    def to_origin(px: float, py: float) -> tuple[float, float]:
        dx, dy = px - rcx, py - rcy
        return (
            ocx + dx * math.cos(theta) - dy * math.sin(theta),
            ocy + dx * math.sin(theta) + dy * math.cos(theta),
        )

    out = []
    for span, box in zip(spans, boxes):
        ox, oy = to_origin(span.x, span.y)
        if not (0 <= ox <= img.width and 0 <= oy <= img.height):
            continue
        left, top, right, bottom = box
        corners = [
            to_origin(left, top),
            to_origin(right, top),
            to_origin(right, bottom),
            to_origin(left, bottom),
        ]
        xs = [c[0] for c in corners]
        ys = [c[1] for c in corners]
        # The rotated box is axis-aligned in ITS frame, so its height
        # there is the true glyph height regardless of the tilt.
        out.append(
            Candidate(
                span=TextSpan(
                    text=span.text,
                    x=ox,
                    y=oy,
                    font_size=span.font_size,
                    color=span.color,
                    confidence=span.confidence,
                    angle=-angle,
                ),
                box=box,
                angle=angle,
                origin_box=(min(xs), min(ys), max(xs), max(ys)),
            )
        )
    return out


def _erase_at_angle(img: Image.Image, boxes: list[Box], angle: float) -> Image.Image:
    """Paint out boxes in the rotated frame, then map back."""
    if abs(angle) < 1e-6:
        arr = np.asarray(img, dtype=np.uint8).copy()
        for left, top, right, bottom in boxes:
            _erase_box(arr, left, top, right, bottom)
        return Image.fromarray(arr)

    rotated = _rotated_copy(img, angle)
    arr = np.asarray(rotated, dtype=np.uint8).copy()
    for left, top, right, bottom in boxes:
        _erase_box(arr, left, top, right, bottom)
    back = Image.fromarray(arr).rotate(-angle, resample=Image.BICUBIC, expand=True)
    left = (back.width - img.width) // 2
    top = (back.height - img.height) // 2
    return back.crop((left, top, left + img.width, top + img.height))


def _edge_color(img: Image.Image) -> tuple[int, int, int]:
    arr = np.asarray(img.convert("RGB"), dtype=np.uint8)
    border = np.concatenate([arr[0], arr[-1], arr[:, 0], arr[:, -1]])
    return tuple(int(v) for v in np.median(border, axis=0))


def _read(
    img: Image.Image, min_confidence: float = 60.0, lang: str = "eng"
) -> tuple[list[TextSpan], list[Box]]:
    """One upright OCR pass. Returns spans and their pixel boxes; the
    image is not modified (erasing is the caller's decision, after
    candidates from every angle have competed)."""
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

    arr = np.asarray(rgb, dtype=np.uint8)
    spans: list[TextSpan] = []
    boxes: list[Box] = []
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
        boxes.append((left, top, right, bottom))

    return spans, boxes


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
