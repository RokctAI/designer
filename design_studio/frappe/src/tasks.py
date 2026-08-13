# Copyright (c) 2026 ROKCT INTELLIGENCE (PTY) LTD
# For license information, please see license.txt
"""Scheduled jobs for design_studio (wired via manifest scheduler_events).

- daily: raw-file retention cleanup (keep_raw_days) + crash recovery
  for requests stuck in Processing.
- hourly: queue sweep — re-enqueue requests sitting in Queued.
"""

from __future__ import annotations

import frappe
from frappe.utils import add_days, add_to_date, now_datetime

STUCK_PROCESSING_HOURS = 2
QUEUE_SWEEP_MINUTES = 15


def cleanup_raw_files():
    """Delete raw provider/upload files older than keep_raw_days.
    Candidate rows and compliant SVGs are kept forever."""
    keep_days = frappe.db.get_single_value(
        "Design Studio Settings", "keep_raw_days") or 30
    cutoff = add_days(now_datetime(), -int(keep_days))
    candidates = frappe.get_all(
        "Design Candidate",
        filters={"creation": ("<", cutoff), "raw_image": ("is", "set")},
        fields=["name", "raw_image"],
        limit_page_length=500,
    )
    for cand in candidates:
        try:
            for f in frappe.get_all("File", filters={"file_url": cand.raw_image},
                                    pluck="name"):
                frappe.delete_doc("File", f, ignore_permissions=True,
                                  delete_permanently=True)
            frappe.db.set_value("Design Candidate", cand.name, "raw_image", None)
        except Exception:
            frappe.log_error(frappe.get_traceback(),
                             f"design_studio raw cleanup failed: {cand.name}")
    frappe.db.commit()


def fail_stuck_requests():
    """Crash recovery: a request Processing for over 2 hours lost its
    worker; mark it Failed so the user is not left waiting forever."""
    cutoff = add_to_date(now_datetime(), hours=-STUCK_PROCESSING_HOURS)
    stuck = frappe.get_all(
        "Design Request",
        filters={"status": "Processing", "modified": ("<", cutoff)},
        pluck="name",
    )
    for name in stuck:
        frappe.db.set_value("Design Request", name,
                            {"status": "Failed", "error_message": "worker timeout"})
    if stuck:
        frappe.db.commit()


def sweep_queue():
    """Re-enqueue requests stuck in Queued (e.g. enqueue lost to a
    worker restart). Hourly; only touches requests idle > 15 minutes."""
    from . import pipeline

    cutoff = add_to_date(now_datetime(), minutes=-QUEUE_SWEEP_MINUTES)
    queued = frappe.get_all(
        "Design Request",
        filters={"status": "Queued", "modified": ("<", cutoff)},
        pluck="name",
        limit_page_length=100,
    )
    for name in queued:
        frappe.enqueue(pipeline.process_design_request, queue="long",
                       name=name, job_name=f"design_request:{name}")
