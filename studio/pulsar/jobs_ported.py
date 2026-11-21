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


def fail_stuck_requests():
    """Crash recovery: a request Processing for over 2 hours lost its
    worker; mark it Failed so the user is not left waiting forever.
    Design and Document Requests share the status machine, so both are
    swept."""
    cutoff = add_to_date(now_datetime(), hours=-STUCK_PROCESSING_HOURS)
    changed = False
    for doctype in ('Design Request', 'Document Request'):
        stuck = fx.get_all(doctype, filters={'status': 'Processing', 'modified': ('<', cutoff)}, pluck='name')
        for name in stuck:
            fx.db.set_value(doctype, name, {'status': 'Failed', 'error_message': 'worker timeout'})
        changed = changed or bool(stuck)
    if changed:
        fx.db.commit()


SCHEDULER_EVENTS = {
    "daily": [
        "cleanup_raw_files",
        "fail_stuck_requests"
    ]
}

