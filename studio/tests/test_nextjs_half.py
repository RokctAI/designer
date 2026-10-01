"""The studio Next.js half may only send gateway cmds its own frappe
manifest whitelists (SDK_ECOSYSTEM.md co-location rule), and every
file it installs must exist."""

import json
import re
from pathlib import Path

STUDIO = Path(__file__).resolve().parents[1]
NEXT = STUDIO / "nextjs"


def _whitelisted_cmds():
    manifest = json.loads((STUDIO / "frappe" / "manifest.json").read_text())
    methods = manifest["app_type"]["tenant"]["hooks"]["whitelisted_methods"]
    return {key.removeprefix("{app_name}.") for key in methods}


def test_nextjs_cmds_are_own_whitelisted_methods():
    allowed = _whitelisted_cmds()
    sent = set()
    for path in (NEXT / "templates").rglob("*.ts*"):
        sent |= set(re.findall(r'"(api\.[a-z_]+\.[a-z_]+)"', path.read_text()))
    assert sent, "no gateway cmds found"
    assert sent <= allowed, sorted(sent - allowed)


def test_manifest_installs_exist():
    manifest = json.loads((NEXT / "manifest.json").read_text())
    assert manifest["name"] == "studio_sdk"
    for entry in manifest["installs"]:
        assert (NEXT / entry["from"]).exists(), entry["from"]
