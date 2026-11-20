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

"""Gateway cmds of the designer/studio SDK, ported from its frappe/ sources by tools/gen_sdk_cmds.py.

This file is pulsar/'s own source from now on: edit it here. The cmds are written against pulsar.sdk_fx_v16 (`fx`).
Cmds that could not be ported are listed with their reason in cmds_unported.json.
Loaded by pulsar.sdk_cmds_v16; a key core already serves keeps core's handler."""

import inspect

import base64
import json
import os
from pulsar import sdk_fx_v16 as fx
from pulsar import sdk_cmds_v16 as sc



def candidate_rows(request_name: str) -> list[dict]:
    """The exact candidate shape get_request_status promises
    (SAAS_SPEC section 4)."""
    rows = fx.get_all('Design Candidate', filters={'request': request_name}, fields=['name', 'slot', 'attempt', 'score_before', 'score_after', 'passed', 'selected', 'compliant_svg', 'raw_image'], order_by='slot asc, attempt asc')
    return [{'name': r.name, 'slot': r.slot, 'attempt': r.attempt, 'score_before': r.score_before, 'score_after': r.score_after, 'passed': r.passed, 'selected': r.selected, 'svg_url': r.compliant_svg, 'raw_url': r.raw_image} for r in rows]


def require(doctype: str, ptype: str='read', doc=None):
    if not fx.has_permission(doctype, ptype, doc=doc):
        fx.throw('Not permitted', fx.PermissionError)


def file_disk_path(file_url: str) -> str:
    name = fx.db.get_value('File', {'file_url': file_url}, 'name')
    if not name:
        fx.throw(f'No File record for {file_url}')
    return fx.get_doc('File', name).get_full_path()
MAX_UPLOAD_BYTES = 20 * 1024 * 1024
UPLOAD_EXTENSIONS = ('.png', '.jpg', '.jpeg', '.webp', '.svg', '.md')


def _hot_folder_settings():
    get = lambda f: fx.db.get_single_value('Design Studio Settings', f)
    return {'enabled': bool(get('hot_folder_enabled')), 'inbox': get('hot_folder_inbox'), 'outbox': get('hot_folder_outbox'), 'sheet': get('hot_folder_sheet'), 'format': get('hot_folder_format'), 'design_system': get('hot_folder_design_system')}
PRINT_JOB_FIELDS = ['name', 'candidate', 'request', 'customer', 'vendor_name', 'final_size', 'sides', 'material_finish', 'status', 'quantity', 'stock', 'due_date', 'sheet', 'press_pdf', 'imposed_pdf', 'ticket_pdf', 'layout_json', 'sales_order', 'sales_invoice', 'modified']


def get_hot_folder_status():
    """Settings plus the last pass's per-file results."""
    require('Design Studio Settings', 'read')
    cfg = _hot_folder_settings()
    last = fx.db.get_single_value('Design Studio Settings', 'hot_folder_last_run')
    cfg['last_run'] = json.loads(last) if last else []
    return cfg


def get_print_job(print_job):
    """One print job with its files and imposition layout."""
    job = fx.get_doc('Design Print Job', print_job)
    require('Design Print Job', 'read', doc=job)
    data = {f: job.get(f) for f in PRINT_JOB_FIELDS}
    data['layout'] = json.loads(job.layout_json) if job.get('layout_json') else None
    return data


def get_campaign_status(name):
    """Per-format candidates in the same shape as get_request_status."""
    doc = fx.get_doc('Design Campaign', name)
    require('Design Campaign', 'read', doc=doc)
    formats = []
    for row in doc.formats:
        entry = {'format': row.format, 'action': row.action, 'candidate': None, 'request_status': None}
        if row.candidate:
            cand = fx.db.get_value('Design Candidate', row.candidate, ['name', 'score_before', 'score_after', 'passed', 'selected', 'compliant_svg', 'raw_image'], as_dict=True)
            if cand:
                entry['candidate'] = {'name': cand.name, 'score_before': cand.score_before, 'score_after': cand.score_after, 'passed': cand.passed, 'selected': cand.selected, 'svg_url': cand.compliant_svg, 'raw_url': cand.raw_image}
        if row.derived_request:
            entry['request_status'] = fx.db.get_value('Design Request', row.derived_request, 'status')
            entry['candidates'] = candidate_rows(row.derived_request)
        formats.append(entry)
    return {'status': doc.status, 'error_message': doc.error_message, 'master_request': doc.master_request, 'formats': formats}


def list_campaigns(page=1, page_size=20):
    require('Design Campaign', 'read')
    page, page_size = (max(1, int(page)), min(100, max(1, int(page_size))))
    return fx.get_list('Design Campaign', fields=['name', 'title', 'status', 'design_system', 'customer', 'master_request', 'creation'], order_by='creation desc', limit_start=(page - 1) * page_size, limit_page_length=page_size)


def get_candidate_svg(candidate):
    """A candidate's compliant SVG text, so Next.js can preview and edit
    it without reading a private file URL."""
    cand = fx.get_doc('Design Candidate', candidate)
    req = fx.get_doc('Design Request', cand.request)
    require('Design Request', 'read', doc=req)
    if not cand.compliant_svg:
        fx.throw(f'Candidate {cand.name} has no compliant SVG yet')
    with open(file_disk_path(cand.compliant_svg), encoding='utf-8') as fh:
        return {'svg': fh.read(), 'score': cand.score_after, 'report_json': cand.report_json}


def get_request_status(name):
    doc = fx.get_doc('Design Request', name)
    require('Design Request', 'read', doc=doc)
    return {'status': doc.status, 'error_message': doc.error_message, 'candidates': candidate_rows(doc.name)}


def list_requests(page=1, page_size=20):
    """Session user's request history for the studio home."""
    require('Design Request', 'read')
    page, page_size = (max(1, int(page)), min(100, max(1, int(page_size))))
    return fx.get_all('Design Request', filters={'requested_by': fx.session.user}, fields=['name', 'title', 'status', 'format', 'source_mode', 'design_system', 'customer', 'creation'], order_by='creation desc', limit_start=(page - 1) * page_size, limit_page_length=page_size)


def upload_file(file_data, filename):
    """Store a base64 file (artwork, or a questions.md) sent straight from Next.js as a private
    File. Returns {"file_url"} for create_design_request's
    ``file_urls``, comply_upload, audit_upload, extract_palette or
    create_document_request's ``questions_file``."""
    require('File', 'create')
    import base64
    import os
    if not (filename or '').lower().endswith(UPLOAD_EXTENSIONS):
        fx.throw('Upload a PNG, JPEG, WebP, SVG or .md file')
    if ',' in file_data[:100]:
        file_data = file_data.split(',', 1)[1]
    raw = base64.b64decode(file_data)
    if len(raw) > MAX_UPLOAD_BYTES:
        fx.throw(f'File is too large; the limit is {MAX_UPLOAD_BYTES // (1024 * 1024)}MB per file')
    f = fx.get_doc({'doctype': 'File', 'file_name': os.path.basename(filename), 'is_private': 1, 'content': raw})
    f.save()
    return {'file_url': f.file_url}


def list_design_systems():
    """Systems visible to the session user (DocType permissions apply
    via get_list)."""
    require('Design System', 'read')
    return fx.get_list('Design System', fields=['name', 'system_name', 'brand_name', 'customer', 'is_default'], order_by='modified desc')


def get_document_status(name):
    """Status + produced files + the engine's honest warnings."""
    doc = fx.get_doc('Document Request', name)
    require('Document Request', 'read', doc=doc)
    return {'status': doc.status, 'error_message': doc.error_message, 'warnings': doc.warnings, 'completeness': doc.completeness, 'outputs': [{'file_path': row.file_path, 'kind': row.kind} for row in doc.outputs or []]}


def list_document_requests(page=1, page_size=20):
    """Session user's document-request history."""
    require('Document Request', 'read')
    page, page_size = (max(1, int(page)), min(100, max(1, int(page_size))))
    return fx.get_all('Document Request', filters={'requested_by': fx.session.user}, fields=['name', 'title', 'business_name', 'document_scope', 'status', 'customer', 'creation'], order_by='creation desc', limit_start=(page - 1) * page_size, limit_page_length=page_size)


def list_print_jobs(status=None, limit=50):
    """Print jobs for the board, newest first."""
    require('Design Print Job', 'read')
    filters = {'status': status} if status else {}
    return fx.get_all('Design Print Job', filters=filters, fields=PRINT_JOB_FIELDS, order_by='modified desc', limit_page_length=int(limit))


def save_hot_folder_settings(values):
    """Update the hot-folder settings from the Next.js settings page."""
    require('Design Studio Settings', 'write')
    if isinstance(values, str):
        values = json.loads(values)
    doc = fx.get_single('Design Studio Settings')
    mapping = {'enabled': 'hot_folder_enabled', 'inbox': 'hot_folder_inbox', 'outbox': 'hot_folder_outbox', 'sheet': 'hot_folder_sheet', 'format': 'hot_folder_format', 'design_system': 'hot_folder_design_system'}
    for key, field in mapping.items():
        if key in (values or {}):
            doc.set(field, values[key])
    doc.save()
    return get_hot_folder_status()


def update_print_job(print_job, values):
    """Set the production fields the board edits (quantity, stock, due
    date, sheet, size, sides, finish, vendor, status)."""
    job = fx.get_doc('Design Print Job', print_job)
    require('Design Print Job', 'write', doc=job)
    if isinstance(values, str):
        values = json.loads(values)
    editable = {'quantity', 'stock', 'due_date', 'sheet', 'final_size', 'sides', 'material_finish', 'vendor_name', 'status'}
    for key, value in (values or {}).items():
        if key in editable:
            job.set(key, value)
    job.save()
    return get_print_job(job.name)


_CMDS = [
    ('api.design_campaign.get_campaign_status', 'get_campaign_status', [('name', inspect.Parameter.empty)], False, None),
    ('api.design_campaign.list_campaigns', 'list_campaigns', [('page', 1), ('page_size', 20)], False, None),
    ('api.design_request.get_candidate_svg', 'get_candidate_svg', [('candidate', inspect.Parameter.empty)], False, None),
    ('api.design_request.get_request_status', 'get_request_status', [('name', inspect.Parameter.empty)], False, None),
    ('api.design_request.list_requests', 'list_requests', [('page', 1), ('page_size', 20)], False, None),
    ('api.design_request.upload_file', 'upload_file', [('file_data', inspect.Parameter.empty), ('filename', inspect.Parameter.empty)], False, None),
    ('api.design_system.list_design_systems', 'list_design_systems', [], False, None),
    ('api.document_request.get_document_status', 'get_document_status', [('name', inspect.Parameter.empty)], False, None),
    ('api.document_request.list_document_requests', 'list_document_requests', [('page', 1), ('page_size', 20)], False, None),
    ('api.print_shop.get_hot_folder_status', 'get_hot_folder_status', [], False, None),
    ('api.print_shop.get_print_job', 'get_print_job', [('print_job', inspect.Parameter.empty)], False, None),
    ('api.print_shop.list_print_jobs', 'list_print_jobs', [('status', None), ('limit', 50)], False, None),
    ('api.print_shop.save_hot_folder_settings', 'save_hot_folder_settings', [('values', inspect.Parameter.empty)], False, None),
    ('api.print_shop.update_print_job', 'update_print_job', [('print_job', inspect.Parameter.empty), ('values', inspect.Parameter.empty)], False, None),
]

for _path, _name, _params, _guest, _methods in _CMDS:
    sc.fn(_path, _params, globals()[_name], guest=_guest, methods=_methods or ("GET", "POST"))

