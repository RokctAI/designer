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

"""Pulsar side of the studio engine: files, the design-request pipeline, campaign fan-out, the document-request
pipeline and the hot-folder pass. Hand-ported over pulsar.sdk_fx_v16 (`fx`); runs on the job queue as Administrator.

Files are the site's file store (reg.file_store) with a File row each; the engine works on local paths, so a stored file
is written to a temporary path only for the length of one engine call."""

from __future__ import annotations

import base64
import contextlib
import json
import os
import tempfile
import time

from pulsar import http_api
from pulsar import platform_api_v16 as papi
from pulsar import sdk_fx_v16 as fx

from . import documents as documents_lib
from . import engine_bridge
from . import campaign as campaign_lib
from . import engine_dict as engine_dict_lib
from . import gating
from . import profile as profile_lib
from . import startupos_bridge
from .providers import ProviderError, get_provider

RASTER_SUFFIXES = (".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif", ".tiff", ".tif")
ARTWORK_SUFFIXES = RASTER_SUFFIXES + (".svg",)
STUCK_PROCESSING_HOURS = 2
QUEUE_SWEEP_MINUTES = 15


# -- files ------------------------------------------------------------------------------------------------------------
def _reg():
    reg = http_api.session_registry()
    if reg is None:
        raise RuntimeError("no document registry")
    return reg


def save_private_file(content, file_name, doctype, name):
    """Store bytes (or text) as a private File attached to doctype/name; the File row."""
    if isinstance(content, str):
        content = content.encode("utf-8")
    return papi.save_file(_reg(), os.path.basename(file_name), content, 1, attached_to=(doctype, name))


def read_file(file_url):
    """The bytes of a stored file; fails when there is no File row for the URL."""
    if not fx.db.get_value("File", {"file_url": file_url}, "name"):
        fx.throw(f"No File record for {file_url}")
    return _reg().file_store.read(file_url)


@contextlib.contextmanager
def local_path(file_url):
    """The stored file at a temporary local path (with its own extension) for one engine call."""
    suffix = os.path.splitext(file_url)[1] or ".bin"
    handle = tempfile.NamedTemporaryFile(suffix=suffix, delete=False)
    try:
        handle.write(read_file(file_url))
        handle.close()
        yield handle.name
    finally:
        with contextlib.suppress(OSError):
            os.unlink(handle.name)


# -- helpers ------------------------------------------------------------------------------------------------------------
def settings():
    return fx.get_single("Design Studio Settings")


def system_dict(system_name):
    return engine_dict_lib.engine_dict_from_doc(fx.get_doc("Design System", system_name))


def attached_artwork(request_name):
    files = fx.get_all("File", filters={"attached_to_doctype": "Design Request", "attached_to_name": request_name},
                       fields=["name", "file_url", "file_name"], order_by="creation asc")
    out = []
    for f in files:
        f = dict(f)
        if os.path.splitext(f.get("file_name") or f.get("file_url") or "")[1].lower() in ARTWORK_SUFFIXES:
            out.append(f)
    return out


def _create_candidate(req, slot, attempt, result, raw_file_url=None, generation_ms=None, revision_of=None):
    cand = fx.get_doc({
        "doctype": "Design Candidate", "request": req.name, "slot": slot, "attempt": attempt, "raw_image": raw_file_url,
        "score_before": result["score_before"], "score_after": result["score_after"], "report_json": result["report_json"],
        "passed": 1 if gating.candidate_passed(result["score_after"], req.min_score or 0) else 0,
        "comply_ms": result.get("comply_ms"), "generation_ms": generation_ms, "revision_of": revision_of})
    cand.insert(ignore_permissions=True)
    try:
        svg_file = save_private_file(result["svg"], f"{cand.name}.svg", "Design Candidate", cand.name)
        cand.db_set("compliant_svg", svg_file["file_url"])
    except Exception:
        # there are no transactions: never leave a candidate row that is missing its compliant_svg
        fx.delete_doc("Design Candidate", cand.name, force=True)
        raise
    return cand


def _fail(req, message):
    req.db_set("status", "Failed")
    req.db_set("error_message", (message or "")[:500])


# -- design requests ----------------------------------------------------------------------------------------------------
def process_design_request(name):
    req = fx.get_doc("Design Request", name)
    if req.status not in ("Queued", "Processing"):
        return
    req.db_set("status", "Processing")
    try:
        sdict = system_dict(req.design_system)
    except Exception as exc:
        _fail(req, f"Design system error: {exc}")
        return
    req.db_set("design_system_fingerprint", engine_dict_lib.fingerprint(sdict))
    cfg = settings()
    max_dim = int(cfg.get("max_dim") or 1024)
    n_colors = int(req.n_colors or cfg.get("default_n_colors") or 6)
    try:
        mode = req.source_mode or "Uploaded Artwork"
        if mode == "Uploaded Artwork":
            produced = _process_uploaded(req, sdict, n_colors, max_dim)
        elif mode == "Template":
            produced = _process_template(req, sdict)
        else:
            produced = _process_generated(req, sdict, n_colors, max_dim)
    except Exception as exc:
        fx.log_error(fx.get_traceback(), f"studio pipeline failed: {name}")
        _fail(req, str(exc))
        return
    if gating.request_outcome(produced) == "Failed":
        _fail(req, req.get("error_message") or "No candidates could be produced")
    else:
        req.db_set("status", "Ready")
        req.db_set("error_message", "")


def _process_uploaded(req, sdict, n_colors, max_dim):
    """Comply every artwork file attached to the request (up to n_candidates): no provider, no spend, pure CPU."""
    files = attached_artwork(req.name)
    if not files:
        req.db_set("error_message", "No artwork attached: attach PNG/SVG files to this request (source_mode 'Uploaded Artwork')")
        return 0
    produced = 0
    for slot, f in enumerate(files[:gating.clamp_n_candidates(req.n_candidates or len(files))], start=1):
        try:
            with local_path(f["file_url"]) as path:
                result = engine_bridge.comply_file(path, sdict, n_colors=n_colors, max_dim=max_dim, format=req.format or None)
        except engine_bridge.EngineError as exc:
            fx.log_error(str(exc), f"studio comply failed: {req.name}")  # complexity errors: skip, never fatal
            continue
        _create_candidate(req, slot, 1, result, raw_file_url=f["file_url"])
        produced += 1
    return produced


def _data_uri(file_url):
    """A stored image as a data URI, so the candidate SVG is self-contained."""
    ext = os.path.splitext(file_url)[1].lower().lstrip(".")
    mime = {"jpg": "jpeg", "svg": "svg+xml"}.get(ext, ext or "png")
    return f"data:image/{mime};base64," + base64.b64encode(read_file(file_url)).decode("ascii")


def _template_background(req, prompt):
    """The only place an image model touches a template poster; any failure leaves the poster without a background."""
    if not (prompt or "").strip() or not req.get("provider"):
        return None
    try:
        provider_doc = fx.get_doc("Generation Provider", req.provider)
        if not provider_doc.get("enabled"):
            return None
        provider = get_provider(provider_doc)
        png = provider.generate(provider.full_prompt(prompt), "1024x1024")
    except Exception as exc:
        fx.log_error(str(exc), f"studio template background: {req.name}")
        return None
    return "data:image/png;base64," + base64.b64encode(png).decode("ascii")


def _process_template(req, sdict):
    """Fill a poster template by code: the merchant's own text, prices and photos go into fixed slots."""
    raw = req.get("template_data") or "{}"
    data = json.loads(raw) if isinstance(raw, str) else dict(raw)
    images = {slot: _data_uri(url) for slot, url in (data.get("images") or {}).items() if url}
    background = _template_background(req, data.get("background_prompt") or "")
    if background:
        images["background"] = background
    items = []
    for item in data.get("items") or []:
        row = dict(item)
        if row.get("image_url"):
            row["image_href"] = _data_uri(row["image_url"])
        items.append(row)
    try:
        result = engine_bridge.render_template(req.template, {"fields": data.get("fields") or {}, "images": images,
                                                              "items": items}, sdict)
    except engine_bridge.EngineError as exc:
        req.db_set("error_message", str(exc)[:500])
        return 0
    _create_candidate(req, 1, 1, result)
    return 1


def _process_generated(req, sdict, n_colors, max_dim):
    """Provider generation loop with score gating and regeneration feedback (works today with the 'mock' provider)."""
    if not req.get("provider"):
        req.db_set("error_message", "No generation provider configured")
        return 0
    provider_doc = fx.get_doc("Generation Provider", req.provider)
    if not provider_doc.get("enabled"):
        req.db_set("error_message", f"Provider {req.provider} is disabled")
        return 0
    provider = get_provider(provider_doc)
    try:
        w, h = engine_bridge.format_size(req.format or "logo")
        size = f"{int(w)}x{int(h)}"
    except engine_bridge.EngineError:
        size = "1024x1024"
    base_prompt = (req.get("composed_prompt") or req.get("prompt") or "").strip()
    max_attempts = max(1, int(req.max_attempts or 1))
    produced = 0
    for slot in range(1, gating.clamp_n_candidates(req.n_candidates or 1) + 1):
        prompt, attempts = base_prompt, []
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
                result = engine_bridge.comply_file(tmp.name, sdict, n_colors=n_colors, max_dim=max_dim, format=req.format or None)
            except engine_bridge.EngineError as exc:
                fx.log_error(str(exc), f"studio comply failed: {req.name}")
                prompt = base_prompt + "\nStrictly flat vector style, solid colors only."
                continue
            finally:
                os.unlink(tmp.name)
            raw_file = save_private_file(image_bytes, f"{req.name}-s{slot}a{attempt}.png", "Design Request", req.name)
            attempts.append({"attempt": attempt, "result": result, "raw_file_url": raw_file["file_url"],
                             "generation_ms": generation_ms, "score_after": result["score_after"]})
            if gating.candidate_passed(result["score_after"], req.min_score or 0):
                break
            prompt = base_prompt + "\n" + engine_bridge.build_feedback(result["report_json"], sdict)
        best = gating.best_attempt(attempts)
        if best:
            _create_candidate(req, slot, best["attempt"], best["result"], raw_file_url=best["raw_file_url"],
                              generation_ms=best["generation_ms"])
            produced += 1
    return produced


# -- campaign fan-out ---------------------------------------------------------------------------------------------------
def _master_artwork(camp):
    if not camp.get("master_request"):
        fx.throw("Campaign needs a master_request whose candidate is fanned out across formats")
    master_req = fx.get_doc("Design Request", camp.master_request)
    cand_name = fx.db.get_value("Design Candidate", {"request": master_req.name, "selected": 1}, "name")
    if not cand_name:
        rows = sorted((dict(r) for r in fx.get_all("Design Candidate", filters={"request": master_req.name},
                                                   fields=["name", "passed", "score_after"])),
                      key=lambda r: (-(r.get("passed") or 0), -(r.get("score_after") or 0)))
        cand_name = rows[0]["name"] if rows else None
    if not cand_name:
        fx.throw(f"Master request {master_req.name} has no candidates yet")
    cand = fx.get_doc("Design Candidate", cand_name)
    if not cand.get("compliant_svg"):
        fx.throw(f"Candidate {cand.name} has no compliant SVG")
    return master_req, cand, read_file(cand.compliant_svg).decode("utf-8")


def _spawn_regeneration(camp, master_req, fmt):
    derived = fx.get_doc({
        "doctype": "Design Request", "title": f"{camp.get('title') or camp.name} — {fmt}", "customer": camp.get("customer"),
        "source_mode": "Generated", "prompt": master_req.get("prompt"), "composed_prompt": master_req.get("composed_prompt"),
        "design_system": camp.design_system, "format": fmt, "n_candidates": 1, "min_score": master_req.get("min_score"),
        "max_attempts": master_req.get("max_attempts"), "provider": master_req.get("provider"),
        "n_colors": master_req.get("n_colors"), "status": "Queued", "requested_by": master_req.get("requested_by")})
    derived.insert(ignore_permissions=True)
    fx.enqueue(process_design_request, queue="long", name=derived.name, job_name=f"design_request:{derived.name}")
    return derived


def process_campaign(name):
    """Fan-out: re-comply the selected master candidate into each target format (derive); an extreme aspect change on
    a Generated master spawns a fresh Design Request (regenerate)."""
    camp = fx.get_doc("Design Campaign", name)
    if camp.status not in ("Draft", "Processing"):
        return
    camp.db_set("status", "Processing")
    try:
        master_req, master_cand, master_svg = _master_artwork(camp)
        sdict = system_dict(camp.design_system)
        master_size = engine_bridge.format_size(master_req.format or "logo")
    except Exception as exc:
        camp.db_set("status", "Failed")
        camp.db_set("error_message", str(exc)[:500])
        return
    threshold = float(settings().get("campaign_regen_threshold") or campaign_lib.DEFAULT_REGEN_THRESHOLD)
    ok = 0
    formats = camp.get("formats") or []
    for row in formats:
        try:
            fmt_size = engine_bridge.format_size(row["format"])
        except engine_bridge.EngineError as exc:
            fx.log_error(str(exc), f"studio campaign: {name}")
            continue
        action = campaign_lib.fanout_action(master_size[0], master_size[1], fmt_size[0], fmt_size[1], threshold=threshold)
        if action == campaign_lib.ACTION_REGENERATE and (master_req.get("source_mode") or "") == "Generated":
            row["action"] = campaign_lib.ACTION_REGENERATE
            row["derived_request"] = _spawn_regeneration(camp, master_req, row["format"]).name
            ok += 1
            continue
        try:
            result = engine_bridge.comply_svg_text(master_svg, sdict, format=row["format"])
        except engine_bridge.EngineError as exc:
            fx.log_error(str(exc), f"studio campaign: {name}")
            continue
        cand = _create_candidate(master_req, 0, 1, result, revision_of=master_cand.name)
        row["action"] = campaign_lib.ACTION_DERIVE
        row["candidate"] = cand.name
        ok += 1
    camp.status = "Ready" if ok else "Failed"
    if not ok:
        camp.error_message = "No format could be produced"
    camp.save(ignore_permissions=True)


# -- document requests --------------------------------------------------------------------------------------------------
def _contained_output_path(output_dir, relative_path):
    destination = os.path.join(output_dir, *relative_path.split("/"))
    base = os.path.realpath(output_dir)
    if not os.path.realpath(destination).startswith(base + os.sep):
        fx.throw(f"Refusing to write {relative_path!r} outside the request's output directory")
    return destination


def _record_outputs(req, rows, warnings, completeness):
    req.set("outputs", [])
    for row in rows:
        req.append("outputs", row)
    req.warnings = warnings[:2000] if warnings else ""
    if completeness is not None:
        req.completeness = float(completeness)
    req.save(ignore_permissions=True)


def _kind(relative_path):
    if relative_path.endswith(documents_lib.PITCH_DECK_SUFFIX):
        return "deck"
    if relative_path.endswith(documents_lib.FINANCIAL_MODEL_SUFFIX):
        return "model"
    return "document"


def process_document_request(name):
    req = fx.get_doc("Document Request", name)
    if req.status not in ("Queued", "Processing"):
        return
    req.db_set("status", "Processing")
    scope = req.get("document_scope") or "Full Suite"
    try:
        if req.get("questions_file"):
            startupos_bridge.write_questions(req.business_name, read_file(req.questions_file).decode("utf-8"),
                                             workspace_root=req.get("workspace_root") or None)
        produced = _process_briefs(req) if scope == "Briefs" else _process_compile(req, scope)
    except (startupos_bridge.StartupOSBridgeError, profile_lib.ProfileRenderError) as exc:
        _fail(req, str(exc))
        return
    except Exception as exc:
        fx.log_error(fx.get_traceback(), f"studio documents pipeline failed: {name}")
        _fail(req, str(exc))
        return
    if gating.request_outcome(produced) == "Failed":
        _fail(req, req.get("error_message") or "No documents could be produced")
    else:
        req.db_set("status", "Ready")
        req.db_set("error_message", "")


def _process_compile(req, scope):
    artifacts = documents_lib.parse_artifacts(req.get("artifacts"))
    result = startupos_bridge.compile_documents(
        req.business_name, workspace_root=req.get("workspace_root") or None,
        compliance_root=req.get("compliance_root") or None,
        render=documents_lib.needs_render(scope, bool(req.get("render_binaries"))), only=artifacts or None)
    selected = list(result["written"]) if artifacts else documents_lib.select_outputs(scope, result["written"])
    rows = [{"file_path": rel, "kind": _kind(rel)} for rel in selected]
    warnings = list(result["warnings"])
    if req.get("render_profile"):
        if documents_lib.BUSINESS_PROFILE_FILENAME in selected:
            rows.extend(_render_branded_profile(req, result["output_dir"]))
        else:
            warnings.append("Render A4 Profile was requested but this request does not deliver "
                            f"{documents_lib.BUSINESS_PROFILE_FILENAME}; add {documents_lib.BUSINESS_PROFILE_STEM} to the "
                            "artifact selection (or use a markdown scope). Nothing was rendered.")
    _record_outputs(req, rows, documents_lib.format_warnings(warnings, result["missing_fields"]), result.get("completeness"))
    if not rows:
        req.db_set("error_message", f"The compiler wrote {len(result['written'])} files but none matched scope {scope!r}")
    return len(rows)


def _render_branded_profile(req, output_dir):
    values = startupos_bridge.instance_values(req.business_name, workspace_root=req.get("workspace_root") or None,
                                              compliance_root=req.get("compliance_root") or None)
    sdict = system_dict(req.design_system) if req.get("design_system") else None
    pages = profile_lib.render_profile_pages(values["values"], system_dict=sdict, pack_dir=req.get("profile_pack_dir") or None,
                                             generated_on=fx.nowdate())
    rows = []
    for rel, svg_text in pages.items():
        destination = _contained_output_path(output_dir, rel)
        os.makedirs(os.path.dirname(destination), exist_ok=True)
        with open(destination, "w", encoding="utf-8") as fh:
            fh.write(svg_text)
        rows.append({"file_path": rel, "kind": "render"})
    return rows


def _process_briefs(req):
    result = startupos_bridge.export_briefs(req.business_name, workspace_root=req.get("workspace_root") or None,
                                            compliance_root=req.get("compliance_root") or None)
    out_dir = result["output_dir"]
    rows = [{"file_path": os.path.relpath(path, out_dir).replace(os.sep, "/"), "kind": "brief"} for path in result["briefs"]]
    _record_outputs(req, rows, "\n".join(result["coaching"]), None)
    if not rows:
        req.db_set("error_message", "No brief had its required marketing answers; see warnings for the questions that "
                                    "unlock each brief")
    return len(rows)


# -- hot folder ---------------------------------------------------------------------------------------------------------
def hot_folder_settings():
    get = lambda f: fx.db.get_single_value("Design Studio Settings", f)  # noqa: E731
    return {"enabled": bool(get("hot_folder_enabled")), "inbox": get("hot_folder_inbox"), "outbox": get("hot_folder_outbox"),
            "sheet": get("hot_folder_sheet"), "format": get("hot_folder_format"),
            "design_system": get("hot_folder_design_system")}


def run_hot_folder_pass(force=False):
    """One pass over the configured inbox (paths are the administrator's own settings in Design Studio Settings)."""
    cfg = hot_folder_settings()
    if not (cfg["enabled"] or force) or not cfg["inbox"] or not cfg["outbox"]:
        return []
    sdict = system_dict(cfg["design_system"]) if cfg["design_system"] else None
    results = engine_bridge.process_hot_folder(cfg["inbox"], cfg["outbox"], system_dict=sdict, format=cfg["format"],
                                               sheet=cfg["sheet"])
    if results:
        fx.db.set_single_value("Design Studio Settings", "hot_folder_last_run", json.dumps(results)[:100000])
    return results
