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

"""Hot folder: drop files in, get print-ready output or a reason back.

``process_file`` handles one file; ``process_folder`` one pass over an
inbox (sources move to ``done/`` or ``failed/`` so nothing is processed
twice); the CLI's ``hotfolder --watch`` loops it. Frappe's scheduler
calls ``process_folder`` the same way.

Per file, into ``outbox``:
- client PDF -> ``<name>.preflight.txt/.json`` (+ ``<name>.imposed.pdf``
  when a sheet is given and preflight passed)
- SVG / raster -> comply, ``<name>.print.pdf`` (CMYK, bleed, marks),
  ``<name>.report.txt/.json``, ``<name>.ticket.pdf``
"""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass, field
from pathlib import Path

ARTWORK = {".svg", ".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff"}


@dataclass
class Result:
    source: str
    passed: bool
    score: float
    outputs: list[str] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return dict(self.__dict__)


def _write_report(report, base: Path) -> list[str]:
    txt, js = Path(f"{base}.txt"), Path(f"{base}.json")
    txt.write_text(report.to_text(), encoding="utf-8")
    js.write_text(report.to_json(), encoding="utf-8")
    return [str(txt), str(js)]


def _problems(report) -> list[str]:
    return [f.message for f in report.findings if not f.fixed
            and (f.blocking or f.severity.value != "info")]


def process_file(path: str | Path, outbox: str | Path, system=None, format: str | None = None,
                 sheet: str | None = None, job=None) -> Result:
    """Run one file through the gate. ``system`` is a DesignSystem (or
    None for the default); ``format`` a print format name."""
    from designer.engine import ComplianceEngine
    from designer.tokens import load_system

    path, outbox = Path(path), Path(outbox)
    outbox.mkdir(parents=True, exist_ok=True)
    stem = outbox / path.stem
    suffix = path.suffix.lower()

    if suffix == ".pdf":
        from designer.preflight import preflight_pdf

        report = preflight_pdf(path)
        outputs = _write_report(report, Path(f"{stem}.preflight"))
        if sheet and not report.blocked:
            from designer.impose import impose_pdf

            imposed = Path(f"{stem}.imposed.pdf")
            impose_pdf(path, imposed, sheet=sheet, quantity=getattr(job, "quantity", None))
            outputs.append(str(imposed))
        return Result(path.name, not report.blocked, report.score, outputs, _problems(report))

    if suffix not in ARTWORK:
        return Result(path.name, False, 0.0, [], [f"unsupported file type {suffix}"])

    from designer.production import job_ticket
    from designer.render import render_pdf

    engine = ComplianceEngine(system or load_system(None), format=format)
    try:
        doc = engine.load(str(path))
    except Exception as exc:  # unreadable or too complex to trace
        return Result(path.name, False, 0.0, [], [str(exc)])
    report = engine.comply(doc)
    outputs = _write_report(report, Path(f"{stem}.report"))
    if not report.blocked:
        spec = engine.format
        is_print = spec is not None and spec.category == "print"
        bleed = (spec.bleed if spec.bleed is not None else engine.system.bleed) if is_print else 0.0
        pdf = Path(f"{stem}.print.pdf")
        render_pdf(doc, pdf, cmyk=True, format=spec, bleed=bleed, marks=is_print,
                   icc_profile=engine.system.icc_profile)
        outputs.append(str(pdf))
        layout = None
        if sheet and is_print:
            from designer.impose import impose_pdf

            imposed = Path(f"{stem}.imposed.pdf")
            layout = impose_pdf(pdf, imposed, sheet=sheet, quantity=getattr(job, "quantity", None))
            outputs.append(str(imposed))
        ticket = Path(f"{stem}.ticket.pdf")
        job_ticket(doc, ticket, job, report=report, layout=layout)
        outputs.append(str(ticket))
    return Result(path.name, not report.blocked, report.score, outputs, _problems(report))


def process_folder(inbox: str | Path, outbox: str | Path, **kwargs) -> list[Result]:
    """One pass: every file in ``inbox`` (not sub-folders) is processed
    and moved to ``inbox/done`` or ``inbox/failed``. A ``summary.json``
    in ``outbox`` lists the pass."""
    inbox, outbox = Path(inbox), Path(outbox)
    results = []
    for src in sorted(p for p in inbox.iterdir() if p.is_file() and not p.name.startswith(".")):
        try:
            res = process_file(src, outbox, **kwargs)
        except Exception as exc:
            res = Result(src.name, False, 0.0, [], [f"crashed: {exc}"])
        dest = inbox / ("done" if res.passed else "failed")
        dest.mkdir(exist_ok=True)
        shutil.move(str(src), str(dest / src.name))
        results.append(res)
    if results:
        outbox.mkdir(parents=True, exist_ok=True)
        (outbox / "summary.json").write_text(
            json.dumps([r.to_dict() for r in results], indent=2), encoding="utf-8")
    return results
