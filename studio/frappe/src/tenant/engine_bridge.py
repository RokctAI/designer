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


def render_candidate_png(svg_text: str, out_path: str, width: int = 1024,
                         construction: bool = False, background: str = "#ffffff") -> str:
    designer, parse_svg, serialize, VectorizeOptions, _ = _engine_modules()
    tmp = tempfile.NamedTemporaryFile(
        "w", suffix=".svg", delete=False, encoding="utf-8")
    try:
        tmp.write(svg_text)
        tmp.close()
        doc = parse_svg(tmp.name)
        designer.render_png(doc, out_path, width=int(width), background=background,
                            construction=bool(construction))
    except Exception as exc:
        raise EngineError(f"PNG render failed: {exc}") from exc
    finally:
        os.unlink(tmp.name)
    return out_path


def render_candidate_pdf(svg_text: str, out_path: str, dpi: float = 300.0,
                         cmyk: bool = True, format: str | None = None,
                         system_dict: dict | None = None, marks: bool = True,
                         overprint_black: bool = True,
                         construction: bool = False) -> str:
    """Press-ready vector PDF. When ``format`` (and system) are given the
    SVG is first re-complied onto that format's canvas so print rules
    (bleed, min stroke, ink coverage) run before the render.

    Print formats get bleed from the format/system and, with ``marks``,
    crop/registration marks, the colour control strip and job slug.
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
        spec, bleed, icc = None, 0.0, None
        if format:
            from designer.tokens import system_from_dict

            spec = _engine_modules()[4].get_format(format)
            system = system_from_dict(system_dict) if system_dict else None
            if spec.category == "print":
                bleed = spec.bleed if spec.bleed is not None else (
                    system.bleed if system else 0.0)
                icc = system.icc_profile if system else None
        is_print = spec is not None and spec.category == "print"
        designer.render_pdf(doc, out_path, dpi=float(dpi), cmyk=bool(cmyk),
                            format=spec, bleed=bleed,
                            marks=bool(marks) and is_print, icc_profile=icc,
                            overprint_black=bool(overprint_black),
                            construction=bool(construction))
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


# -- construction guides, prepress and print-shop paperwork ---------------


def _doc_from_svg(svg_text: str):
    _, parse_svg, _, _, _ = _engine_modules()
    tmp = tempfile.NamedTemporaryFile(
        "w", suffix=".svg", delete=False, encoding="utf-8")
    try:
        tmp.write(svg_text)
        tmp.close()
        return parse_svg(tmp.name)
    finally:
        os.unlink(tmp.name)


def construction(svg_text: str) -> dict:
    """Construction guides for a design: plain-language notes, the ⚠
    warnings among them, the raw geometry and an overlay SVG. Never
    scores or fails a design."""
    from designer.construct import construct, overlay
    from designer.svg import serialize

    doc = _doc_from_svg(svg_text)
    con = construct(doc)
    return {
        "notes": con.notes(),
        "warnings": con.warnings(),
        "circles": [{"cx": c.cx, "cy": c.cy, "r": c.r} for c in con.circles],
        "horizontals": [{"y": y, "edges": n} for y, n in con.horizontals],
        "verticals": [{"x": x, "edges": n} for x, n in con.verticals],
        "ratios": [{"a": i + 1, "b": j + 1, "ratio": r} for i, j, r in con.ratios],
        "overlay_svg": serialize(overlay(doc, con)),
    }


def preflight_pdf(pdf_path: str, min_ppi: float = 300.0, max_ink: float = 300.0,
                  min_bleed_mm: float = 3.0) -> dict:
    """Preflight a client PDF. Returns the report as a dict
    (``blocked``, ``score``, ``findings``)."""
    import json

    from designer.preflight import preflight_pdf as _preflight

    try:
        report = _preflight(pdf_path, min_ppi=min_ppi, max_ink=max_ink,
                            min_bleed_mm=min_bleed_mm)
    except Exception as exc:
        raise EngineError(f"Preflight failed: {exc}") from exc
    return json.loads(report.to_json())


def list_sheets() -> dict:
    from designer.impose import SHEETS_MM

    return {name: list(mm) for name, mm in SHEETS_MM.items()}


def impose(pdf_path: str, out_path: str, sheet="SRA3", quantity: int | None = None,
           gap_mm: float | None = None, margin_mm: float = 10.0) -> dict:
    """N-up a one-page print PDF onto a press sheet. Returns the layout."""
    from designer.impose import impose_pdf

    try:
        layout = impose_pdf(pdf_path, out_path, sheet=sheet, quantity=quantity,
                            gap_mm=gap_mm, margin_mm=margin_mm)
    except ValueError as exc:
        raise EngineError(str(exc)) from exc
    data = layout.to_dict()
    if quantity:
        data["sheets"] = layout.sheets_for(quantity)
    return data


def _job(job: dict | None):
    from designer.production import Job

    job = dict(job or {})
    known = {k: job.pop(k) for k in list(job) if k in Job.__dataclass_fields__}
    if known.get("quantity") is not None:
        known["quantity"] = int(known["quantity"])
    return Job(**known, extra={k: str(v) for k, v in job.items() if v})


def job_ticket(svg_text: str, out_path: str, job: dict | None = None,
               system_dict: dict | None = None, format: str | None = None,
               layout: dict | None = None) -> str:
    """One-page A4 job ticket PDF for the press operator."""
    from designer.impose import Layout
    from designer.production import job_ticket as _ticket

    doc = _doc_from_svg(svg_text)
    report = None
    if system_dict:
        from designer.engine import ComplianceEngine
        from designer.tokens import system_from_dict

        report = ComplianceEngine(system_from_dict(system_dict), format=format).audit(doc)
    lay = None
    if layout:
        lay = Layout(layout["sheet"], tuple(layout["sheet_mm"]), tuple(layout["item_mm"]),
                     layout["cols"], layout["rows"], layout["rotated"],
                     layout["bleed_mm"], layout["gap_mm"])
    _ticket(doc, out_path, _job(job), report=report, layout=lay)
    return out_path


def proof(svg_texts: list[str], out_path: str, job: dict | None = None,
          approve_url: str = "") -> str:
    """Watermarked low-res client proof PDF with a sign-off block."""
    from designer.production import proof as _proof

    _proof([_doc_from_svg(t) for t in svg_texts], out_path, _job(job),
           approve_url=approve_url)
    return out_path


def process_hot_folder(inbox: str, outbox: str, system_dict: dict | None = None,
                       format: str | None = None, sheet: str | None = None) -> list[dict]:
    """One hot-folder pass (see designer.hotfolder)."""
    from designer.hotfolder import process_folder
    from designer.tokens import system_from_dict

    system = system_from_dict(system_dict) if system_dict else None
    return [r.to_dict() for r in process_folder(
        inbox, outbox, system=system, format=format or None, sheet=sheet or None)]


def render_pages_pdf(svg_texts: list[str], out_path: str, cmyk: bool = True,
                     format: str | None = None, system_dict: dict | None = None,
                     marks: bool = True) -> str:
    """One multi-page PDF from several designs (front/back, folded
    panels), sharing format, bleed and marks."""
    designer = _engine_modules()[0]
    docs = [_doc_from_svg(t) for t in svg_texts]
    spec, bleed, icc = None, 0.0, None
    if format:
        from designer.tokens import system_from_dict

        spec = _engine_modules()[4].get_format(format)
        system = system_from_dict(system_dict) if system_dict else None
        if spec.category == "print":
            bleed = spec.bleed if spec.bleed is not None else (system.bleed if system else 0.0)
            icc = system.icc_profile if system else None
    is_print = spec is not None and spec.category == "print"
    try:
        designer.render_pdf(docs, out_path, cmyk=bool(cmyk), format=spec, bleed=bleed,
                            marks=bool(marks) and is_print, icc_profile=icc)
    except Exception as exc:
        raise EngineError(f"PDF render failed: {exc}") from exc
    return out_path


def brandbook_pdf(system_dict: dict, out_path: str, logo_path: str | None = None) -> str:
    """The design system as an A4 brand manual PDF."""
    from designer.brandbook import BrandbookError, build_brandbook
    from designer.render import render_pdf
    from designer.tokens import system_from_dict

    try:
        pages = build_brandbook(system_from_dict(system_dict), logo=logo_path)
    except BrandbookError as exc:
        raise EngineError(str(exc)) from exc
    render_pdf(pages, out_path)
    return out_path
