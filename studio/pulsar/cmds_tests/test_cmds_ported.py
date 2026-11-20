import sys
import unittest

from . import CORE  # noqa: F401  (puts the core checkout on sys.path)
from pulsar import http_api
from tests.test_platform_api_v16 import Base

MODULE = "pulsar_sdk_cmds_designer_studio_cmds_ported"


class Ported(Base):
    def cmds(self):
        mod = sys.modules.get(MODULE)
        self.assertIsNotNone(mod, "cmds_ported.py did not load")
        return mod._CMDS

    def test_every_cmd_is_registered(self):
        for key, name, params, guest, methods in self.cmds():
            self.assertIn(key, http_api.WHITELIST, key)

    def test_the_cmds_keep_their_guest_flag_and_ask_for_a_login(self):
        for key, name, params, guest, methods in self.cmds():
            spec = http_api.WHITELIST[key]
            if spec["fn"].__module__ != "pulsar.sdk_cmds_v16":
                continue  # a key core serves keeps core's handler
            self.assertEqual(spec["allow_guest"], bool(guest), key)
            if not guest:
                self.assertEqual(self.api(key)[0], 401, key)

    def test_a_cmd_of_core_is_not_replaced(self):
        self.assertEqual(http_api.WHITELIST["api.user.get_profile"]["fn"].__module__, "pulsar.user_api_v16")


if __name__ == "__main__":
    unittest.main()
