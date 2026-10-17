import sys
import unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).parent/"src"))
import resident
from direct_registry import DirectRegistry
from test_integration import make_resident, stop_patches, BASE_CFG, FakeWeChatUI, FakeModel, FakeConfig, FakeNavigator

class DiscoveredFlowTests(unittest.TestCase):
    def test_first_inbound_is_queued_once_and_send_rechecks_registry(self):
        cfg = dict(BASE_CFG,target_chat="",direct_enabled=True,direct_whitelist=[])
        r = make_resident(cfg)
        self.addCleanup(stop_patches,r)
        self.addCleanup(r.db.close)
        registry=DirectRegistry(resident.STATE/"direct-friends.json")
        registry.register(cfg,"新好友","wxid_test","contact_profile")
        merged=resident.with_discovered(cfg)
        ui,model=FakeWeChatUI(),FakeModel()
        r.nav=FakeNavigator(ui)
        bubbles=[{"direction":"in","kind":"text","text":"你好呀","at_me":False,"bbox":[80,100,200,140],"signature":"first"}]
        with patch("visual_parse.extract_messages",return_value=bubbles):
            self.assertTrue(r.observe_one(merged,ui,model,"新好友",ui.capture()))
        self.assertEqual(r.quota.depth(),1)
        self.assertFalse(registry.pending_initial(cfg,"新好友"))
        with patch("resident.CONFIG",FakeConfig(cfg)):
            self.assertEqual(r.latest_send_config("direct:新好友")["chat_types"]["新好友"],"direct")
        with patch("visual_parse.extract_messages",return_value=bubbles):
            self.assertFalse(r.observe_one(merged,ui,model,"新好友",ui.capture()))
        self.assertEqual(r.quota.depth(),1)
        disabled=dict(cfg,direct_enabled=False)
        with patch("resident.CONFIG",FakeConfig(disabled)):
            with self.assertRaises(resident.SafetyError):
                r.latest_send_config("direct:新好友")
        revoked=dict(cfg,direct_blacklist=["新好友"])
        with patch("resident.CONFIG",FakeConfig(revoked)):
            with self.assertRaises(resident.SafetyError):
                r.latest_send_config("direct:新好友")

    def test_first_discovery_does_not_replay_before_last_outgoing(self):
        cfg=dict(BASE_CFG,target_chat="",direct_enabled=True,direct_whitelist=[])
        r=make_resident(cfg)
        self.addCleanup(stop_patches,r)
        self.addCleanup(r.db.close)
        registry=DirectRegistry(resident.STATE/"direct-friends.json")
        registry.register(cfg,"新好友","wxid_test","contact_profile")
        merged=resident.with_discovered(cfg)
        ui,model=FakeWeChatUI(),FakeModel()
        messages=[{"direction":"in","kind":"text","text":"旧消息","bbox":[80,100,200,140],"signature":"old"},
                  {"direction":"out","kind":"text","text":"已经回过","bbox":[80,200,200,240],"signature":"out"}]
        with patch("visual_parse.extract_messages",return_value=messages):
            self.assertFalse(r.observe_one(merged,ui,model,"新好友",ui.capture()))
        self.assertEqual(r.quota.depth(),0)
        self.assertFalse(registry.pending_initial(cfg,"新好友"))

if __name__=="__main__":
    unittest.main()
