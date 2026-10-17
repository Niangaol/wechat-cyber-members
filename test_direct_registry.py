import json
import sys
import tempfile
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent / "src"))
from direct_registry import DirectRegistry


class RegistryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "friends.json"
        self.reg = DirectRegistry(self.path)
        self.cfg = {"direct_enabled": True, "group_whitelist": ["人机"], "direct_blacklist": [], "direct_whitelist": ["年糕"], "chat_types": {"人机": "group"}}

    def register(self, name="新好友", uid="wxid_test", proof="contact_profile"):
        return self.reg.register(self.cfg, name, uid, proof)

    def test_verified_friend_persists_and_merges(self):
        self.assertTrue(self.register())
        result = DirectRegistry(self.path).apply(self.cfg)
        self.assertEqual(result["direct_whitelist"], ["年糕", "新好友"])
        self.assertEqual(result["chat_types"]["新好友"], "direct")
        self.assertEqual(result["group_whitelist"], ["人机"])
        self.assertEqual(self.cfg["direct_whitelist"], ["年糕"])

    def test_group_rejected(self):
        self.assertFalse(self.register("人 机"))
        self.cfg["chat_types"]["陌生会话"] = "group"
        self.assertFalse(self.register("陌生会话"))

    def test_blacklist_immediately_revokes(self):
        self.register()
        self.cfg["direct_blacklist"] = ["新 好友"]
        self.assertNotIn("新好友", self.reg.apply(self.cfg)["direct_whitelist"])
        self.assertFalse(self.register())

    def test_switch_off(self):
        self.register()
        self.cfg["direct_enabled"] = False
        self.assertEqual(self.reg.apply(self.cfg), self.cfg)
        self.assertFalse(self.register("另一个"))

    def test_missing_proof_or_id_rejected(self):
        self.assertFalse(self.register(proof="chat_message"))
        self.assertFalse(self.register(uid=""))

    def test_conflicting_identity_rejected(self):
        self.assertTrue(self.register())
        self.assertFalse(self.register(uid="wxid_other"))
        self.assertEqual(self.reg.load()["新好友"]["wechat_id"], "wxid_test")

    def test_truncated_or_empty_name_rejected(self):
        for name in ("", "  ", "新好友…", "新\n好友"):
            self.assertFalse(self.register(name))

    def test_corrupt_state_fails_closed(self):
        for data in ("bad json", "[]", "null", '{"version":1,"friends":[]}'):
            self.path.write_text(data)
            self.assertEqual(self.reg.load(), {})

    def test_unverified_disk_rows_ignored(self):
        self.path.write_text(json.dumps({"version": 1, "friends": {"陌生群": {"proof": "chat_message", "wechat_id": "x"}}}))
        self.assertEqual(self.reg.load(), {})

if __name__ == "__main__":
    unittest.main()
