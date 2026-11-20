"""The ported scheduler jobs (pulsar/jobs_ported.py): each is scheduled and runs on an empty site through the worker."""

import os
import sys
import unittest

from . import CORE  # noqa: F401  (puts the core checkout on sys.path)
from pulsar import db, http_api, sdk_cmds_v16
from pulsar import queue as pq
from pulsar.ignition import pulsar_api

_SDK = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
_PREFIX = "pulsar_sdk_cmds_%s_%s_jobs_ported." % (os.path.basename(os.path.dirname(_SDK)), os.path.basename(_SDK))


def _mine():
    out = []
    for key, jobs in sdk_cmds_v16.SCHEDULER_EVENTS.items():
        for j in ([m for ms in jobs.values() for m in ms] if key == "cron" else jobs):
            if j.startswith(_PREFIX):
                out.append(j)
    return sorted(out)


class Jobs(unittest.TestCase):
    def test_jobs_are_scheduled_and_run_as_administrator_on_an_empty_site(self):
        jobs = _mine()
        self.assertTrue(jobs, "no job of %s is scheduled" % _PREFIX)
        d = db.connect("sqlite:///:memory:")
        self.addCleanup(d.close)
        reg = pulsar_api.make_registry(d)
        q = pq.Queue(d)
        called = []
        for j in jobs:  # count the entries into the real function
            module, name = sys.modules[j.rsplit(".", 1)[0]], j.rsplit(".", 1)[1]
            real = getattr(module, name)
            self.addCleanup(setattr, module, name, real)
            setattr(module, name, lambda real=real, j=j: (called.append(j), real())[1])
        ids = [q.enqueue(j) for j in jobs]
        self.assertEqual(pulsar_api.BackgroundJobs(lambda: d, []).run_once(d, reg), len(jobs))
        for job_id, name in zip(ids, jobs):
            row = q.get(job_id if isinstance(job_id, (int, str)) else job_id["id"])
            self.assertNotEqual(row["status"], "queued", name)
            self.assertIsNone(row["last_error"], "%s: %s" % (name, row["last_error"]))
        self.assertEqual(sorted(called), jobs)  # every scheduled job ran
        self.assertIsNone(http_api._ctx.user)


if __name__ == "__main__":
    unittest.main()
