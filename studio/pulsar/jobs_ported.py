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

"""Scheduler jobs of the designer/studio SDK. Committed; source of truth: edit here.

Written against pulsar.sdk_fx_v16 (`fx`); the worker runs them as Administrator on its own registry.
Jobs still to port are listed with their reason in jobs_unported.json. Loaded by pulsar.sdk_cmds_v16."""

import inspect  # noqa: F401
from pulsar.sdk_fx_v16 import add_days
from pulsar.sdk_fx_v16 import add_to_date
from pulsar.sdk_fx_v16 import now_datetime
from pulsar import sdk_fx_v16 as fx


def _only(persona, job):
    """Wrap job so it runs on sites of this persona only (app_role, default tenant)."""
    def run():
        if (fx.conf.get('app_role') or 'tenant') != persona:
            return None
        return job()
    run.__name__ = job.__name__
    return run



def cleanup_raw_files():
    """Delete raw provider/upload files older than keep_raw_days.
    Candidate rows and compliant SVGs are kept forever."""
    keep_days = fx.db.get_single_value('Design Studio Settings', 'keep_raw_days') or 30
    cutoff = add_days(now_datetime(), -int(keep_days))
    candidates = fx.get_all('Design Candidate', filters={'creation': ('<', cutoff), 'raw_image': ('is', 'set')}, fields=['name', 'raw_image'], limit_page_length=500)
    for cand in candidates:
        try:
            for f in fx.get_all('File', filters={'file_url': cand.raw_image}, pluck='name'):
                fx.delete_doc('File', f, ignore_permissions=True, delete_permanently=True)
            fx.db.set_value('Design Candidate', cand.name, 'raw_image', None)
        except Exception:
            fx.log_error(fx.get_traceback(), f'studio raw cleanup failed: {cand.name}')
    fx.db.commit()
STUCK_PROCESSING_HOURS = 2


def _stuck_before(row_modified, cutoff):
    """True when a stored `modified` stamp (text, either separator) is older than cutoff."""
    return bool(row_modified) and fx.get_datetime(row_modified) < cutoff


def fail_stuck_requests():
    """Crash recovery: a request Processing for over 2 hours lost its worker; mark it Failed so the user is not left
    waiting forever. Design and Document Requests share the status machine, so both are swept."""
    cutoff = add_to_date(now_datetime(), hours=-STUCK_PROCESSING_HOURS)
    for doctype in ('Design Request', 'Document Request'):
        for row in fx.get_all(doctype, filters={'status': 'Processing'}, fields=['name', 'modified']):
            row = dict(row)
            if _stuck_before(row.get('modified'), cutoff):
                fx.db.set_value(doctype, row['name'], {'status': 'Failed', 'error_message': 'worker timeout'})
    fx.db.commit()


def _lib():
    """The studio engine package (studio/pulsar/lib), loaded once from beside this file."""
    import importlib.util
    import os
    import sys
    if 'pulsar_studio_lib' not in sys.modules:
        base = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'lib')
        spec = importlib.util.spec_from_file_location('pulsar_studio_lib', os.path.join(base, '__init__.py'),
                                                      submodule_search_locations=[base])
        module = importlib.util.module_from_spec(spec)
        sys.modules['pulsar_studio_lib'] = module
        spec.loader.exec_module(module)
    import importlib
    return importlib.import_module('pulsar_studio_lib.pipeline')


QUEUE_SWEEP_MINUTES = 15


def sweep_queue():
    """Hourly: re-enqueue requests stuck in Queued (an enqueue lost to a worker restart); only those idle over 15 minutes
    (at most 100 of each kind per run). The job name dedupes against a job already waiting."""
    pipeline = _lib()
    cutoff = add_to_date(now_datetime(), minutes=-QUEUE_SWEEP_MINUTES)
    for doctype, fn, prefix in (('Design Request', pipeline.process_design_request, 'design_request'),
                                ('Document Request', pipeline.process_document_request, 'document_request')):
        queued = [dict(r) for r in fx.get_all(doctype, filters={'status': 'Queued'}, fields=['name', 'modified'])]
        for row in [r for r in queued if _stuck_before(r.get('modified'), cutoff)][:100]:
            fx.enqueue(fn, queue='long', name=row['name'], job_name=f"{prefix}:{row['name']}")


def process_hot_folder():
    """Every scheduler tick: one hot-folder pass when enabled in Design Studio Settings."""
    _lib().run_hot_folder_pass()


SCHEDULER_EVENTS = {
    "all": [
        "process_hot_folder"
    ],
    "hourly": [
        "sweep_queue"
    ],
    "daily": [
        "cleanup_raw_files",
        "fail_stuck_requests"
    ]
}

