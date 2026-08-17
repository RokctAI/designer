# Copyright (c) 2026 RokctAI
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

# Copyright (c) 2026 ROKCT INTELLIGENCE (PTY) LTD
# For license information, please see license.txt
"""Background pipeline for design_studio (SAAS_SPEC section 5).

Runs on the ``long`` queue. For source_mode "Uploaded Artwork" (the
primary path today) the pipeline runs engine comply/score on the files
attached to the request instead of calling a generation provider.
"""

from __future__ import annotations

import os
import tempfile
import time

import frappe

from . import engine_bridge
from .lib import campaign as campaign_lib
from .lib import engine_dict as engine_dict_lib
from .lib import gating
from .providers import ProviderError, get_provider

RASTER_SUFFIXES = (".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif", ".tiff", ".tif")
ARTWORK_SUFFIXES = RASTER_SUFFIXES + (".svg",)


# --------------------------------------------------------------- helpers

def _settings():
    return frappe.get_cached_doc("Design Studio Settings")


def _system_dict(system_name: str) -> dict:
    system = frappe.get_doc("Design System", system_name)
    return engine_dict_lib.engine_dict_from_doc(system)


def _save_private_file(content, file_name: str, doctype: str, name: str):
    """Create a private File doc attached to ``doctype``/``name``."""
    fdoc = frappe.get_doc({
        "doctype": "File",
        "file_name": file_name,
        "attached_to_doctype": doctype,
        "attached_to_name": name,
        "is_private": 1,
        "content": content,
    })
    fdoc.save(ignore_permissions=True)
    return fdoc


def _file_disk_path(file_url: str) -> str:
    fname = frappe.db.get_value("File", {"file_url": file_url}, "name")
    if not fname:
        frappe.throw(f"No File record for {file_url}")
    return frappe.get_doc("File", fname).get_full_path()


def _attached_artwork(request_name: str) -> list[dict]:
    files = frappe.get_all(
        "File",
        filters={"attached_to_doctype": "Design Request",
                 "attached_to_name": request_name},
        fields=["name", "file_url", "file_name"],
        order_by="creation asc",
    )
    return [f for f in files
            if os.path.splitext(f.file_name or f.file_url or "")[1].lower()
            in ARTWORK_SUFFIXES]


def _publish_progress(req, slot: int, attempt: int, score_after: float | None):
    try:
        frappe.publish_realtime(
            "design_request_progress",
            {"request": req.name, "slot": slot, "attempt": attempt,
             "score_after": score_after, "status": req.status},
            user=req.requested_by or req.owner,
        )
    except Exception:
        pass  # progress events are best-effort


def _create_candidate(req, slot: int, attempt: int, result: dict,
                      raw_file_url: str | None = None,
                      generation_ms: int | None = None,
                      revision_of: str | None = None):
    cand = frappe.get_doc({
        "doctype": "Design Candidate",
        "request": req.name,
        "slot": slot,
        "attempt": attempt,
        "raw_image": raw_file_url,
        "score_before": result["score_before"],
        "score_after": result["score_after"],
        "report_json": result["report_json"],
        "passed": 1 if gating.candidate_passed(
            result["score_after"], req.min_score or 0) else 0,
        "comply_ms": result.get("comply_ms"),
        "generation_ms": generation_ms,
        "revision_of": revision_of,
    })
    cand.insert(ignore_permissions=True)
    svg_file = _save_private_file(
        result["svg"], f"{cand.name}.svg", "Design Candidate", cand.name)
    cand.db_set("compliant_svg", svg_file.file_url)
    frappe.db.commit()  # save as soon as it exists so the UI can stream
    return cand


def _fail(req, message: str):
    req.db_set("status", "Failed")
    req.db_set("error_message", (message or "")[:500])
    frappe.db.commit()


# ------------------------------------------------------ request pipeline

def process_design_request(name: str):
    req = frappe.get_doc("Design Request", name)
    if req.status not in ("Queued", "Processing"):
        return
    req.db_set("status", "Processing")
    frappe.db.commit()

    try:
        system_dict = _system_dict(req.design_system)
    except Exception as exc:
        _fail(req, f"Design system error: {exc}")
        return

    settings = _settings()
    max_dim = int(settings.max_dim or 1024)
    n_colors = int(req.n_colors or settings.default_n_colors or 6)

    try:
        if (req.source_mode or "Uploaded Artwork") == "Uploaded Artwork":
            produced = _process_uploaded(req, system_dict, n_colors, max_dim)
        else:
            produced = _process_generated(req, system_dict, n_colors, max_dim)
    except Exception as exc:
        frappe.log_error(frappe.get_traceback(),
                         f"design_studio pipeline failed: {name}")
        _fail(req, str(exc))
        return

    outcome = gating.request_outcome(produced)
    if outcome == "Failed":
        _fail(req, req.error_message or "No candidates could be produced")
    else:
        req.db_set("status", "Ready")
        req.db_set("error_message", "")
        frappe.db.commit()
    _publish_progress(req, 0, 0, None)


def _process_uploaded(req, system_dict: dict, n_colors: int, max_dim: int) -> int:
    """Comply every artwork file attached to the request (cap at
    n_candidates). This is the primary path today: no provider, no
    spend, pure CPU."""
    files = _attached_artwork(req.name)
    if not files:
        req.db_set("error_message",
                   "No artwork attached: attach PNG/SVG files to this "
                   "request (source_mode 'Uploaded Artwork')")
        return 0
    cap = gating.clamp_n_candidates(req.n_candidates or len(files))
    produced = 0
    for slot, f in enumerate(files[:cap], start=1):
        try:
            path = _file_disk_path(f.file_url)
            result = engine_bridge.comply_file(
                path, system_dict, n_colors=n_colors, max_dim=max_dim,
                format=req.format or None)
        except engine_bridge.EngineError as exc:
            # ComplexityError and friends: mark and move on, never fatal.
            frappe.log_error(str(exc), f"design_studio comply failed: {req.name}")
            _publish_progress(req, slot, 1, None)
            continue
        _create_candidate(req, slot, 1, result, raw_file_url=f.file_url)
        _publish_progress(req, slot, 1, result["score_after"])
        produced += 1
    return produced


def _process_generated(req, system_dict: dict, n_colors: int, max_dim: int) -> int:
    """Provider generation loop with score gating and regeneration
    feedback (SAAS_SPEC section 5). Works today only with the 'mock'
    provider; real providers raise NotImplementedError until the AI
    milestone."""
    if not (req.provider):
        req.db_set("error_message", "No generation provider configured")
        return 0
    provider_doc = frappe.get_doc("Generation Provider", req.provider)
    if not provider_doc.enabled:
        req.db_set("error_message",
                   f"Provider {req.provider} is disabled")
        return 0
    provider = get_provider(provider_doc)

    try:
        w, h = engine_bridge.format_size(req.format or "logo")
        size = f"{int(w)}x{int(h)}"
    except engine_bridge.EngineError:
        size = "1024x1024"

    base_prompt = (req.composed_prompt or req.prompt or "").strip()
    n_candidates = gating.clamp_n_candidates(req.n_candidates or 1)
    max_attempts = max(1, int(req.max_attempts or 1))
    produced = 0

    for slot in range(1, n_candidates + 1):
        prompt = base_prompt
        attempts: list[dict] = []
        for attempt in range(1, max_attempts + 1):
            started = time.monotonic()
            try:
                image_bytes = provider.generate(provider.full_prompt(prompt), size)
            except (ProviderError, NotImplementedError) as exc:
                req.db_set("error_message", str(exc)[:500])
                break  # slot skipped, not fatal
            generation_ms = int((time.monotonic() - started) * 1000)

            tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
            try:
                tmp.write(image_bytes)
                tmp.close()
                result = engine_bridge.comply_file(
                    tmp.name, system_dict, n_colors=n_colors,
                    max_dim=max_dim, format=req.format or None)
            except engine_bridge.EngineError as exc:
                # Photographic/complex output: reinforce flat style once.
                frappe.log_error(str(exc),
                                 f"design_studio comply failed: {req.name}")
                prompt = base_prompt + "\nStrictly flat vector style, solid colors only."
                continue
            finally:
                os.unlink(tmp.name)

            raw_file = _save_private_file(
                image_bytes, f"{req.name}-s{slot}a{attempt}.png",
                "Design Request", req.name)
            attempts.append({
                "attempt": attempt, "result": result,
                "raw_file_url": raw_file.file_url,
                "generation_ms": generation_ms,
                "score_after": result["score_after"],
            })
            _publish_progress(req, slot, attempt, result["score_after"])
            if gating.candidate_passed(result["score_after"], req.min_score or 0):
                break
            prompt = base_prompt + "\n" + engine_bridge.build_feedback(
                result["report_json"], system_dict)

        best = gating.best_attempt(attempts)
        if best:
            _create_candidate(req, slot, best["attempt"], best["result"],
                              raw_file_url=best["raw_file_url"],
                              generation_ms=best["generation_ms"])
            produced += 1
    return produced


# ----------------------------------------------------- campaign fan-out

def process_campaign(name: str):
    """V1 fan-out: re-comply the selected master candidate into each
    target format (derive). Extreme aspect changes fall back to a fresh
    Design Request sharing the master's prompt (regenerate) when the
    master was Generated; uploaded-artwork masters always derive."""
    camp = frappe.get_doc("Design Campaign", name)
    if camp.status not in ("Draft", "Processing"):
        return
    camp.db_set("status", "Processing")
    frappe.db.commit()

    try:
        master_req, master_cand, master_svg = _master_artwork(camp)
        system_dict = _system_dict(camp.design_system)
        master_size = engine_bridge.format_size(master_req.format or "logo")
    except Exception as exc:
        camp.db_set("status", "Failed")
        camp.db_set("error_message", str(exc)[:500])
        frappe.db.commit()
        return

    settings = _settings()
    threshold = float(settings.campaign_regen_threshold or
                      campaign_lib.DEFAULT_REGEN_THRESHOLD)
    ok = 0
    for row in camp.formats:
        try:
            fmt_size = engine_bridge.format_size(row.format)
        except engine_bridge.EngineError as exc:
            frappe.log_error(str(exc), f"design_studio campaign: {name}")
            continue
        action = campaign_lib.fanout_action(
            master_size[0], master_size[1], fmt_size[0], fmt_size[1],
            threshold=threshold)
        if action == campaign_lib.ACTION_REGENERATE and \
                (master_req.source_mode or "") == "Generated":
            derived = _spawn_regeneration(camp, master_req, row.format)
            row.db_set("action", campaign_lib.ACTION_REGENERATE)
            row.db_set("derived_request", derived.name)
            ok += 1
            continue
        # Derive: pure-CPU re-comply of the SAME master artwork onto
        # this canvas — instant, free, pixel-consistent.
        try:
            result = engine_bridge.comply_svg_text(
                master_svg, system_dict, format=row.format)
        except engine_bridge.EngineError as exc:
            frappe.log_error(str(exc), f"design_studio campaign: {name}")
            continue
        cand = _create_candidate(master_req, 0, 1, result,
                                 revision_of=master_cand.name)
        row.db_set("action", campaign_lib.ACTION_DERIVE)
        row.db_set("candidate", cand.name)
        ok += 1

    camp.db_set("status", "Ready" if ok else "Failed")
    if not ok:
        camp.db_set("error_message", "No format could be produced")
    frappe.db.commit()


def _master_artwork(camp):
    if not camp.master_request:
        frappe.throw("Campaign needs a master_request whose candidate is "
                     "fanned out across formats")
    master_req = frappe.get_doc("Design Request", camp.master_request)
    cand_name = frappe.db.get_value(
        "Design Candidate",
        {"request": master_req.name, "selected": 1}, "name")
    if not cand_name:
        cand_name = frappe.db.get_value(
            "Design Candidate", {"request": master_req.name}, "name",
            order_by="passed desc, score_after desc")
    if not cand_name:
        frappe.throw(f"Master request {master_req.name} has no candidates yet")
    cand = frappe.get_doc("Design Candidate", cand_name)
    if not cand.compliant_svg:
        frappe.throw(f"Candidate {cand.name} has no compliant SVG")
    with open(_file_disk_path(cand.compliant_svg), encoding="utf-8") as fh:
        return master_req, cand, fh.read()


def _spawn_regeneration(camp, master_req, fmt: str):
    derived = frappe.get_doc({
        "doctype": "Design Request",
        "title": f"{camp.title or camp.name} — {fmt}",
        "customer": camp.customer,
        "source_mode": "Generated",
        "prompt": master_req.prompt,
        "composed_prompt": master_req.composed_prompt,
        "design_system": camp.design_system,
        "format": fmt,
        "n_candidates": 1,
        "min_score": master_req.min_score,
        "max_attempts": master_req.max_attempts,
        "provider": master_req.provider,
        "n_colors": master_req.n_colors,
        "status": "Queued",
        "requested_by": master_req.requested_by,
    })
    derived.insert(ignore_permissions=True)
    frappe.db.commit()
    frappe.enqueue(process_design_request, queue="long",
                   name=derived.name, job_name=f"design_request:{derived.name}")
    return derived
