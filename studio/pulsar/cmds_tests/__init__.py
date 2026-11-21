"""Tests of pulsar/cmds_ported.py. Needs the core checkout ($PULSAR_CORE or ../../../../core/pulsar) for the pulsar
package and its test harness; run: cd <sdk>/pulsar && python -m unittest discover -s cmds_tests -t ."""

import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
CORE = os.environ.get("PULSAR_CORE") or os.path.normpath(os.path.join(_HERE, "..", "..", "..", "..", "core", "pulsar"))
if CORE not in sys.path:
    sys.path.insert(0, CORE)
# the SDK repos sit side by side: <root>/<repo>/<sdk>/pulsar/cmds_tests -> <root>
os.environ.setdefault("PULSAR_SDK_ROOT", os.path.normpath(os.path.join(_HERE, "..", "..", "..", "..")))
