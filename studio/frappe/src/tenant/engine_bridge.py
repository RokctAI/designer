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

"""Every touch of the designer-compliance engine lives in this one file
(SAAS_SPEC section 3) so engine upgrades are a one-file review.

The engine runs in-process: ~0.3s / ~7MB peak per 512px flat-artwork
job. ``designer.ComplexityError`` (photographic input) is surfaced as
EngineError with the engine's user-facing message — callers must NOT
retry those.
"""

from __future__ import annotations

import os
import tempfile
import time

from .lib import feedback as _feedback


class EngineError(Exception):
    """Engine failure with a user-facing message."""


def _engine_modules():
    """Import lazily so this module stays importable when the
    designer-compliance pip package is absent (e.g. plain unit tests)."""
    try:
        import designer
        from designer.svg import parse_svg, serialize
        from designer.vectorize import VectorizeOptions
        from designer import formats as designer_formats
    except ImportError as exc:  # pragma: no cover
        raise EngineError(
            "The designer-compliance engine is not installed on this bench "
            "(pip install designer-compliance)"
        ) from exc
    return designer, parse_svg, serialize, VectorizeOptions, designer_formats


def validate_format(name: str) -> None:
    """Raise EngineError if ``name`` is not in the engine's catalog."""
    designer, _, _, _, formats = _engine_modules()
    try:
        formats.get_format(name)
    except ValueError as exc:
        raise EngineError(str(exc)) from exc


def list_formats() -> list[dict]:
    designer, _, _, _, formats = _engine_modules()
    return [
        {"name": f.name, "width": f.width, "height": f.height,
         "category": f.category, "description": f.description}
        for f in formats.all_formats()
    ]


def format_size(name: str) -> tuple[float, float]:
    designer, _, _, _, formats = _engine_modules()
    spec = formats.get_format(name)
    return spec.width, spec.height


def comply_file(image_path: str, system_dict: dict, n_colors: int = 6,
                max_dim: int = 1024, format: str | None = None) -> dict:
    """Vectorize (if raster) + comply. Returns
    {"svg", "score_before", "score_after", "report_json", "comply_ms"}.
    Raises EngineError on failure.
    """
    designer, parse_svg, serialize, VectorizeOptions, _ = _engine_modules()
    started = time.monotonic()
    try:
        system = designer.system_from_dict(system_dict)
        engine = designer.ComplianceEngine(system, format=format)
        doc = engine.load(
            image_path,
            VectorizeOptions(n_colors=int(n_colors), max_dim=int(max_dim)),
        )
        score_before = engine.audit(doc).score
        report = engine.comply(doc)
        svg_text = serialize(doc)
    except (designer.ComplexityError, designer.InvalidImageError) as exc:
        raise EngineError(str(exc)) from exc
    except EngineError:
        raise
    except Exception as exc:
        raise EngineError(f"Engine failed on {os.path.basename(image_path)}: {exc}") from exc
    return {
        "svg": svg_text,
        "score_before": float(score_before),
        "score_after": float(report.score),
        "report_json": report.to_json(),
        "comply_ms": int((time.monotonic() - started) * 1000),
    }


def audit_file(file_path: str, system_dict: dict, n_colors: int = 6,
               max_dim: int = 1024) -> dict:
    """Audit only (SVG or raster). Returns {"score", "report_json"}."""
    designer, parse_svg, serialize, VectorizeOptions, _ = _engine_modules()
    try:
        system = designer.system_from_dict(system_dict)
        engine = designer.ComplianceEngine(system)
        doc = engine.load(
            file_path,
            VectorizeOptions(n_colors=int(n_colors), max_dim=int(max_dim)),
        )
        report = engine.audit(doc)
    except (designer.ComplexityError, designer.InvalidImageError) as exc:
        raise EngineError(str(exc)) from exc
    except Exception as exc:
        raise EngineError(f"Engine failed on {os.path.basename(file_path)}: {exc}") from exc
    return {"score": float(report.score), "report_json": report.to_json()}


def comply_svg_text(svg_text: str, system_dict: dict,
                    format: str | None = None) -> dict:
    """Parse an SVG string (engine's own sanitizing parser), comply it —
    optionally onto a different format canvas (campaign derivation).
    Same return shape as comply_file. Unparseable SVG raises EngineError.
    """
    tmp = tempfile.NamedTemporaryFile(
        "w", suffix=".svg", delete=False, encoding="utf-8")
    try:
        tmp.write(svg_text)
        tmp.close()
        return comply_file(tmp.name, system_dict, format=format)
    finally:
        os.unlink(tmp.name)


def render_candidate_png(svg_text: str, out_path: str, width: int = 1024) -> str:
    designer, parse_svg, serialize, VectorizeOptions, _ = _engine_modules()
    tmp = tempfile.NamedTemporaryFile(
        "w", suffix=".svg", delete=False, encoding="utf-8")
    try:
        tmp.write(svg_text)
        tmp.close()
        doc = parse_svg(tmp.name)
        designer.render_png(doc, out_path, width=int(width))
    except Exception as exc:
        raise EngineError(f"PNG render failed: {exc}") from exc
    finally:
        os.unlink(tmp.name)
    return out_path


def render_candidate_pdf(svg_text: str, out_path: str, dpi: float = 300.0,
                         cmyk: bool = True, format: str | None = None,
                         system_dict: dict | None = None) -> str:
    """Press-ready vector PDF. When ``format`` (and system) are given the
    SVG is first re-complied onto that format's canvas so print rules
    (bleed, min stroke, ink coverage) run before the render.

    Note: printer's marks (crop/registration) are not drawn yet — the
    engine's render_pdf has no marks support; bleed comes from the
    design system's print config. Callers pass ``marks`` today only as a
    recorded preference.
    """
    designer, parse_svg, serialize, VectorizeOptions, _ = _engine_modules()
    if format and system_dict:
        svg_text = comply_svg_text(svg_text, system_dict, format=format)["svg"]
    tmp = tempfile.NamedTemporaryFile(
        "w", suffix=".svg", delete=False, encoding="utf-8")
    try:
        tmp.write(svg_text)
        tmp.close()
        doc = parse_svg(tmp.name)
        designer.render_pdf(doc, out_path, dpi=float(dpi), cmyk=bool(cmyk))
    except EngineError:
        raise
    except Exception as exc:
        raise EngineError(f"PDF render failed: {exc}") from exc
    finally:
        os.unlink(tmp.name)
    return out_path


def extract_palette(file_path: str, n: int = 6) -> list[dict]:
    """Palette extraction from an uploaded image (FRONTEND_SPEC 1.2)."""
    try:
        from designer.raster import load_image, palette_report, quantize
        from designer.color import to_hex
    except ImportError as exc:  # pragma: no cover
        raise EngineError("designer-compliance is not installed") from exc
    try:
        qimg = quantize(load_image(file_path), n_colors=int(n))
        return [{"hex": to_hex(rgb), "coverage": round(cov, 4)}
                for rgb, cov in palette_report(qimg)]
    except Exception as exc:
        raise EngineError(f"Palette extraction failed: {exc}") from exc


def build_feedback(report_json: str, system_dict: dict) -> str:
    """Prompt guidance for regeneration; pure logic lives in lib."""
    return _feedback.build_feedback(report_json, system_dict)
