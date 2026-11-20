"""The studio engine modules, pipelines and the two ported jobs. Needs Pillow, numpy, PyYAML and pypdf, and the
designer package of this repository (its root is put on sys.path here; deployed sites install designer-compliance)."""

import io
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta

from . import CORE  # noqa: F401  (puts the core checkout on sys.path)

_REPO = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", ".."))
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)

import yaml  # noqa: E402
from PIL import Image, ImageDraw  # noqa: E402

from pulsar import http_api  # noqa: E402
from pulsar import sdk_fx_v16 as fx  # noqa: E402
from tests.test_platform_api_v16 import Base  # noqa: E402

JOBS = "pulsar_sdk_cmds_designer_studio_jobs_ported"


def flat_png():
    img = Image.new("RGB", (256, 256), "#ffffff")
    ImageDraw.Draw(img).ellipse([64, 64, 192, 192], fill="#1a56db")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


class Studio(Base):
    def setUp(self):
        super().setUp()
        self.jobs = sys.modules[JOBS]
        self.pipe = self.jobs._lib()
        self.reg.conf = {"encryption_key": "k"}
        http_api._ctx.registry, http_api._ctx.user = self.reg, http_api.ADMIN
        for attr in ("registry", "user"):
            self.addCleanup(setattr, http_api._ctx, attr, None)
        with open(os.path.join(_REPO, "designer", "systems", "default.yaml"), encoding="utf-8") as fh:
            self.sdict = yaml.safe_load(fh)
        old = self.pipe.system_dict
        self.pipe.system_dict = lambda name: self.sdict
        self.addCleanup(setattr, self.pipe, "system_dict", old)
        self.add("Design System", name="ds", system_name="ds")

    def request(self, name="r1", status="Queued", **kw):
        row = dict(title="t", design_system="ds", status=status, source_mode="Uploaded Artwork", n_candidates=2, min_score=50,
                   modified=(datetime.now() - timedelta(hours=3)).isoformat(sep=" ", timespec="seconds"))
        row.update(kw)
        self.add("Design Request", name=name, **row)

    def attach(self, request, name, content):
        self.pipe.save_private_file(content, name, "Design Request", request)

    def get(self, doctype, name):
        return self.reg.store.get(doctype, name)

    def test_uploaded_artwork_becomes_a_scored_candidate_with_its_svg(self):
        self.request()
        self.attach("r1", "logo.png", flat_png())
        self.pipe.process_design_request("r1")
        self.assertEqual(self.get("Design Request", "r1")["status"], "Ready")
        cands = self.reg.store.rows_of("Design Candidate")
        self.assertEqual(len(cands), 1)
        self.assertIsNotNone(cands[0]["score_after"])
        self.assertIn(b"<svg", self.reg.file_store.read(cands[0]["compliant_svg"]))

    def test_a_request_without_artwork_fails_with_the_reason(self):
        self.request()
        self.pipe.process_design_request("r1")
        row = self.get("Design Request", "r1")
        self.assertEqual(row["status"], "Failed")
        self.assertIn("No artwork attached", row["error_message"])

    def test_a_finished_request_is_not_processed_again(self):
        self.request(status="Ready")
        self.attach("r1", "logo.png", flat_png())
        self.pipe.process_design_request("r1")
        self.assertEqual(self.reg.store.rows_of("Design Candidate"), [])

    def test_a_generated_request_runs_the_mock_provider(self):
        self.add("Generation Provider", name="mock", provider_type="mock", enabled=1)
        self.request(source_mode="Generated", provider="mock", prompt="a logo", max_attempts=1, n_candidates=1)
        self.pipe.process_design_request("r1")
        self.assertEqual(self.get("Design Request", "r1")["status"], "Ready")
        self.assertEqual(len(self.reg.store.rows_of("Design Candidate")), 1)

    def test_a_file_without_a_file_row_is_refused(self):
        with self.assertRaises(Exception):
            self.pipe.read_file("/private/files/none.png")

    def test_sweep_requeues_only_old_queued_requests_once(self):
        queued = []
        old = fx.enqueue
        fx.enqueue = lambda fn, **kw: queued.append((fn.__name__, kw["name"], kw["job_name"]))
        self.addCleanup(setattr, fx, "enqueue", old)
        self.request("old")
        self.request("fresh", modified=datetime.now().isoformat(sep=" ", timespec="seconds"))
        self.request("busy", status="Processing")
        self.jobs.sweep_queue()
        self.assertEqual(queued, [("process_design_request", "old", "design_request:old")])

    def test_stuck_processing_requests_fail(self):
        self.request("stuck", status="Processing")
        self.request("fine", status="Processing", modified=datetime.now().isoformat(sep=" ", timespec="seconds"))
        self.jobs.fail_stuck_requests()
        self.assertEqual((self.get("Design Request", "stuck")["status"], self.get("Design Request", "fine")["status"]),
                         ("Failed", "Processing"))

    def test_the_hot_folder_does_nothing_until_enabled_then_records_the_pass(self):
        inbox, outbox = tempfile.mkdtemp(), tempfile.mkdtemp()
        with open(os.path.join(inbox, "a.png"), "wb") as fh:
            fh.write(flat_png())
        self.add("Design Studio Settings", name="Design Studio Settings", hot_folder_enabled=0, hot_folder_inbox=inbox,
                 hot_folder_outbox=outbox)
        self.jobs.process_hot_folder()
        self.assertEqual(os.listdir(outbox), [])
        self.reg.store.update("Design Studio Settings", "Design Studio Settings",
                              dict(self.get("Design Studio Settings", "Design Studio Settings"), hot_folder_enabled=1))
        self.jobs.process_hot_folder()
        self.assertTrue(os.listdir(outbox))
        self.assertTrue(self.get("Design Studio Settings", "Design Studio Settings").get("hot_folder_last_run"))

    def test_a_campaign_derives_each_format_from_the_master(self):
        self.request("master", status="Ready", format="a4-poster")
        self.attach("master", "logo.png", flat_png())
        self.reg.store.update("Design Request", "master", dict(self.get("Design Request", "master"), status="Queued"))
        self.pipe.process_design_request("master")
        self.add("Design Campaign", name="c1", title="c", design_system="ds", master_request="master", status="Draft",
                 formats=[{"format": "a4-poster"}, {"format": "a1-poster"}])
        self.pipe.process_campaign("c1")
        camp = self.get("Design Campaign", "c1")
        self.assertEqual(camp["status"], "Ready")
        self.assertEqual([f.get("action") for f in camp["formats"]], ["derive", "derive"])
        self.assertEqual(len(self.reg.store.rows_of("Design Candidate")), 3)

    def test_a_document_request_fails_plainly_without_the_startupos_engine(self):
        self.add("Document Request", name="d1", title="d", business_name="Acme", status="Queued", document_scope="Briefs")
        self.pipe.process_document_request("d1")
        row = self.get("Document Request", "d1")
        self.assertEqual(row["status"], "Failed")
        self.assertIn("startupos", row["error_message"])

    def test_get_candidate_svg_reads_the_file_store(self):
        cmds = sys.modules["pulsar_sdk_cmds_designer_studio_cmds_ported"]
        self.request("r9", status="Ready", requested_by="boss")
        f = self.pipe.save_private_file("<svg/>", "c.svg", "Design Candidate", "cand1")
        self.add("Design Candidate", name="cand1", request="r9", compliant_svg=f["file_url"], score_after=90)
        self.assertEqual(cmds.read_file_text(f["file_url"]), "<svg/>")

    def test_pure_gating_and_tokens(self):
        from pulsar_studio_lib import gating, tokens
        self.assertTrue(gating.can_transition("Queued", "Processing"))
        self.assertFalse(gating.can_transition("Failed", "Ready"))
        self.assertEqual(gating.clamp_n_candidates("x"), 1)
        self.assertEqual(gating.request_outcome(0), "Failed")
        self.assertTrue(tokens.tokens_equal("a", "a") and not tokens.tokens_equal("a", "b"))
        self.assertNotIn("<script", tokens.proof_email_html("<script>x</script>", "https://e.example/r", "T"))


if __name__ == "__main__":
    unittest.main()
