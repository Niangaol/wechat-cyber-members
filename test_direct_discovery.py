import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from PIL import Image, ImageDraw
sys.path.insert(0,str(Path(__file__).parent/"src"))
from direct_discovery import DirectDiscovery, contact_id
from direct_registry import DirectRegistry
from wechat_ui import WeChatUI

class DiscoveryTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.registry = DirectRegistry(Path(tmp.name)/"friends.json")
        self.cfg = {"direct_enabled":True,"direct_auto_discover":True,"direct_whitelist":[],"group_whitelist":["Vibe AI Lab 招新交流群"],"direct_blacklist":["拉黑好友"]}

    def test_positive_profile(self):
        self.assertEqual(contact_id("新好友\nWeixin ID: wxid_abc\nRemark Add Alias", "新好友"),"wxid_abc")

    def test_missing_identity_or_profile_control_rejected(self):
        for text in ("新好友 WeChat ID: wxid_abc", "新好友 Remark", "别人 Weixin ID: wxid_abc Remark"):
            self.assertIsNone(contact_id(text,"新好友"))

    def test_group_profile_rejected(self):
        self.assertIsNone(contact_id("新好友 Weixin ID: wxid_abc Remark Group Name", "新好友"))

    def test_scan_enrolls_only_confirmed_friends_and_preserves_policy(self):
        ui = Mock()
        discovery = DirectDiscovery(self.registry)
        discovery.inspect_profile = Mock(side_effect=lambda u,n,name: "wxid_abc" if name=="新好友" else None)
        with patch("direct_discovery.ChatNavigator"), patch("direct_discovery.list_candidates",return_value=["Vibe Al Lab 招新交流群","拉黑好友","陌生群","新好友"]):
            self.assertEqual(discovery.scan(self.cfg,ui,now=1000),["新好友"])
        self.assertEqual([c.args[2] for c in discovery.inspect_profile.call_args_list],["陌生群","新好友"])
        self.assertIn("新好友",self.registry.apply(self.cfg)["direct_whitelist"])
        self.assertNotIn("陌生群",self.registry.apply(self.cfg)["direct_whitelist"])

    def test_disabled_and_interval_make_no_ui_calls(self):
        ui = Mock()
        discovery = DirectDiscovery(self.registry)
        discovery.last_scan = 1000
        self.assertEqual(discovery.scan(self.cfg,ui,now=1010),[])
        self.cfg["direct_enabled"] = False
        self.assertEqual(discovery.scan(self.cfg,ui,now=2000),[])
        self.assertEqual(ui.mock_calls,[])

    def test_attempt_budget(self):
        ui = Mock()
        discovery = DirectDiscovery(self.registry)
        discovery.inspect_profile = Mock(return_value=None)
        with patch("direct_discovery.ChatNavigator"),patch("direct_discovery.list_candidates",return_value=["一","二","三","四"]):
            discovery.scan(self.cfg,ui,now=1000)
        self.assertEqual(discovery.inspect_profile.call_count,3)

    def test_initial_ack_survives_rediscovery(self):
        self.registry.register(self.cfg,"新好友","wxid_test","contact_profile")
        self.assertTrue(self.registry.pending_initial(self.cfg,"新好友"))
        self.registry.ack_initial("新好友")
        self.registry.register(self.cfg,"新好友","wxid_test","contact_profile")
        self.assertFalse(self.registry.pending_initial(self.cfg,"新好友"))

    def test_wrong_cached_preview_retries_with_exact_name_location(self):
        from chat_navigator import ChatNavigator
        from test_multi_chat import FakeUI
        ui=FakeUI()
        nav=ChatNavigator(ui)
        # _matches_title 前 4 次为 False：初始核验、点击后核验、补帧再核验、
        # 第二次初始核验；之后按精确名称行点（320）才算成功。
        with patch("chat_navigator.time.sleep"), \
             patch("chat_navigator.find_list_anchor",return_value=None), \
             patch.object(nav,"_matches_title",side_effect=[False,False,False,False,True]), \
             patch.object(nav,"rows_for",return_value=[]), \
             patch.object(nav,"match_rows",return_value=(170,110)), \
             patch("chat_navigator.find_chat_in_list",return_value=(170,320)) as exact:
            nav.switch_to("李想26计科")
        self.assertEqual(exact.call_count,1)
        moves=[c for c in ui.clicks if "mousemove" in c]
        self.assertEqual(moves[-1][-1],"320")

    def test_exact_name_row_wins_over_group_message_preview(self):
        from chat_navigator import find_chat_in_list
        image=Image.new("RGB",(1021,740),(237,237,237))
        with patch("chat_navigator.find_list_anchor",return_value=None), \
             patch("direct_discovery.candidate_rows",return_value=[("李想26计科",(170,320))]), \
             patch("chat_navigator.ocr_tsv") as tsv:
            self.assertEqual(find_chat_in_list(Mock(),image,"李想26计科"),(170,320))
            tsv.assert_not_called()

    def test_widened_sidebar_does_not_look_like_an_input_draft(self):
        ui=WeChatUI({"display":":99"})
        image=Image.new("RGB",(1021,740),(237,237,237))
        draw=ImageDraw.Draw(image)
        draw.line((338,90,338,550),fill=(213,213,213))
        draw.rectangle((300,660,320,670),fill="black")
        ui.ocr=lambda crop,psm: "列表时间戳" if min(crop.convert("L").getdata())<100 else ""
        self.assertEqual(ui._draft_text(image),"")

    def test_title_candidates_never_accept_cropped_prefix(self):
        ui = WeChatUI({"display":":99"})
        image = Image.new("RGB",(1021,740),(237,237,237))
        draw = ImageDraw.Draw(image)
        draw.line((338,90,338,550),fill=(213,213,213))
        draw.rectangle((355,32,390,47),fill="black")
        draw.rectangle((700,32,720,47),fill="black")
        ui.run = Mock(return_value="短标题".encode())
        self.assertEqual(ui.title_texts(image),[])
        ui.run.assert_not_called()

if __name__=="__main__":
    unittest.main()
