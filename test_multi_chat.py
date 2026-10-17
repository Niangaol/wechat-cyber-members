import json, sqlite3, sys, unittest
from pathlib import Path
from unittest.mock import patch
from PIL import Image
sys.path.insert(0, str(Path(__file__).parent/'src'))
from chat_navigator import ChatNavigator, find_chat_in_list, ocr_tsv
from wechat_ui import WeChatUI, SafetyError, title_matches
from resident import Resident, chat_key_of

# tesseract TSV 表头 + 若干词
TSV_HEADER = 'level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext\n'
def tsv_row(text, x, y, w=40, h=20):
    return '5\t1\t1\t1\t1\t1\t%d\t%d\t%d\t%d\t95\t%s\n' % (x*3, y*3, w*3, h*3, text)

class FakeUI:
    """假 UI：capture 返回白图；run 按命令路由（xdotool 空、tesseract TSV）。"""
    def __init__(self, tsv_lines=''):
        self.tsv_lines = tsv_lines
        self.clicks = []
        self.wid = '0x1'
        self.last_abs = (0, 0)
        self.cfg = {'target_chat': '很帅的年糕', 'display': ':99'}
    def capture(self):
        return Image.new('RGB', (980, 710), (237, 237, 237))
    def run(self, args, data=None, timeout=12):
        if args[0] == 'tesseract':
            return (TSV_HEADER + self.tsv_lines).encode()
        if args[0] == 'xdotool' and 'click' in args:
            self.clicks.append(args)
        if args[0] == 'xdotool' and args[1] == 'mousemove':
            self.clicks.append(args)
        return b''
    def clipboard_write(self, text):
        self.clipboard = text
    def ocr(self, image, psm=6):
        return ''

class NavigatorTests(unittest.TestCase):
    def setUp(self):
        sleeper = patch('chat_navigator.time.sleep')
        sleeper.start()
        self.addCleanup(sleeper.stop)

    def test_scroll_to_top_when_not_found(self):
        """当前画面找不到目标时先滚到顶再找一次（久没消息的会话会沉下去甚至滚出可视区）。"""
        ui = FakeUI()
        nav = ChatNavigator(ui)
        calls = []

        def fake_find(ui_, image, name):
            calls.append(name)
            return None if len(calls) == 1 else (160, 200)

        with patch('chat_navigator.find_chat_in_list', side_effect=fake_find), \
             patch.object(nav, '_matches_title', side_effect=[False, False, True]):
            nav.switch_to('家庭群')
        self.assertEqual(len(calls), 2, '找不到要再找一次')
        scrolls = [c for c in ui.clicks if c[-1] == '4']
        self.assertGreaterEqual(len(scrolls), 1, '应该滚过列表')

    def test_find_chat_by_name(self):
        ui = FakeUI(tsv_row('很帅的', 100, 120) + tsv_row('年糕', 145, 120))
        pos = find_chat_in_list(ui, ui.capture(), '很帅的年糕')
        self.assertIsNotNone(pos)
        # 两词拼接命中的中点（60 + (100+145+40)//2 = 202），在合理区间即可
        self.assertTrue(180 <= pos[0] <= 230)
        self.assertTrue(170 <= pos[1] <= 200)
    def test_find_chat_not_found(self):
        ui = FakeUI(tsv_row('其他人', 100, 120))
        self.assertIsNone(find_chat_in_list(ui, ui.capture(), '很帅的年糕'))
    def test_switch_verifies_title(self):
        ui = FakeUI(tsv_row('很帅的年糕', 100, 120))
        ui.ocr = lambda image, psm=6: '很帅的年糕'   # 标题 OCR mock
        nav = ChatNavigator(ui)
        nav.switch_to('很帅的年糕')
        self.assertEqual(ui.clicks, [])  # 已在目标会话时不触碰 UI
        self.assertFalse(hasattr(ui, 'clipboard'))
    def test_switch_rejects_wrong_title(self):
        ui = FakeUI(tsv_row('很帅的年糕', 100, 120))
        ui.ocr = lambda image, psm=6: '别人'   # 标题 OCR 是别的名字
        nav = ChatNavigator(ui)
        with self.assertRaises(SafetyError):
            nav.switch_to('很帅的年糕')

class LoginWindowGuardTests(unittest.TestCase):
    def test_login_window_is_never_resized(self):
        """登录小窗同名同类，绝不能被当成主窗 resize（否则用户没法扫码）。"""
        ui = WeChatUI({'display': ':99', 'expected_width': 1021, 'expected_height': 740,
                       'window_origin': [0, 0]})
        small = [{'id': '0x1', 'title': 'Weixin', 'classes': '"wechat" "wechat"',
                  'w': 292, 'h': 396, 'abs_x': 494, 'abs_y': 202}]
        calls = []
        ui.run = lambda args, data=None, timeout=12: calls.append(args) or b''
        with patch.object(WeChatUI, '_weixin_windows', staticmethod(lambda cfg: small)):
            with self.assertRaises(SafetyError):
                ui.capture()
        self.assertEqual(calls, [])      # 一个 xdotool 都没发出去


class TitleSafetyTests(unittest.TestCase):
    def test_exact_direct(self):
        self.assertTrue(title_matches('很帅的年糕', ' 很帅的年糕 '))
    def test_partial_or_extended_title_rejected(self):
        for actual in ['很帅', '很帅的年糕骗子', '很帅的年糕...', '很帅的年糕(4)']:
            self.assertFalse(title_matches('很帅的年糕', actual))
    def test_group_member_count(self):
        for actual in ['家庭群', '家庭群(4)', '家庭群（12）']:
            self.assertTrue(title_matches('家庭群', actual, True))
    def test_group_partial_or_extended_title_rejected(self):
        for actual in ['家庭', '家庭群骗子(4)', '家庭群...', '家庭群(4)骗子']:
            self.assertFalse(title_matches('家庭群', actual, True))
    def test_empty_title_rejected(self):
        self.assertFalse(title_matches('', ''))
    def test_navigator_rejects_prefix_collision(self):
        ui = FakeUI()
        ui.ocr = lambda image, psm=6: '很帅的年糕骗子'
        with patch('chat_navigator.time.sleep'):
            with self.assertRaises(SafetyError):
                ChatNavigator(ui).switch_to('很帅的年糕')
    def test_navigator_accepts_whitelisted_group_member_count(self):
        ui = FakeUI()
        ui.cfg['group_whitelist'] = ['家庭群']
        ui.ocr = lambda image, psm=6: '家庭群(4)'
        with patch('chat_navigator.time.sleep'):
            ChatNavigator(ui).switch_to('家庭群')

class ConfigTests(unittest.TestCase):
    def setUp(self):
        self.r = Resident.__new__(Resident)  # 不跑 __init__
    def test_chat_key_direct(self):
        cfg = {'target_chat': '很帅的年糕', 'group_whitelist': [], 'direct_blacklist': []}
        self.assertEqual(chat_key_of(cfg, '很帅的年糕'), 'direct:很帅的年糕')
    def test_chat_key_group_whitelist(self):
        cfg = {'target_chat': 'A', 'group_whitelist': ['家庭群'], 'direct_blacklist': []}
        self.assertEqual(chat_key_of(cfg, '家庭群'), 'group:家庭群')
    def test_chat_key_blacklist_rejected(self):
        cfg = {'target_chat': 'A', 'group_whitelist': [], 'direct_blacklist': ['推销']}
        self.assertIsNone(chat_key_of(cfg, '推销'))
    def test_chat_key_nonwhitelist_group_rejected(self):
        cfg = {'target_chat': 'A', 'group_whitelist': ['家庭群'], 'direct_blacklist': []}
        self.assertIsNone(chat_key_of(cfg, '陌生人群'))
    def test_unknown_type_fails_closed(self):
        self.assertIsNone(chat_key_of({}, '摄影同好'))
    def test_known_direct_with_group_in_name_allowed(self):
        self.assertEqual(chat_key_of({}, '群青', chat_type='direct'), 'direct:群青')
    def test_nonwhitelist_group_without_group_character_rejected(self):
        self.assertIsNone(chat_key_of({}, '摄影同好', chat_type='group'))
    def test_group_prefix_does_not_pass(self):
        cfg = {'group_whitelist': ['家庭群']}
        for name in ['家庭', '家庭群骗子', '家庭群...']:
            self.assertIsNone(chat_key_of(cfg, name, chat_type='group'))
    def test_group_member_count_keeps_canonical_key(self):
        cfg = {'group_whitelist': ['家庭群']}
        self.assertEqual(chat_key_of(cfg, '家庭群(4)', chat_type='group'), 'group:家庭群')
    def test_configured_direct_type(self):
        cfg = {'chat_types': {'新朋友': 'direct'}}
        self.assertEqual(chat_key_of(cfg, '新朋友'), 'direct:新朋友')
    def test_explicit_blacklist_blocks_direct(self):
        cfg = {'direct_blacklist': ['推销']}
        self.assertIsNone(chat_key_of(cfg, '推销', chat_type='direct'))
    def test_group_only_watch_list(self):
        self.assertEqual(self.r.watch_list({'watch_chats': ['家庭群']}), ['家庭群'])
    def test_watch_list_dedup(self):
        cfg = {'target_chat': 'A', 'watch_chats': ['B', 'A', 'C']}
        self.assertEqual(self.r.watch_list(cfg), ['A', 'B', 'C'])

class BaselineIsolationTests(unittest.TestCase):
    def test_two_chats_independent_baselines(self):
        r = Resident.__new__(Resident)
        r.baselines, r.last_hash = {}, {}
        r.baselines['direct:A'] = ['s1', 's2']
        r.baselines['group:B'] = ['x1']
        self.assertNotEqual(r.baselines['direct:A'], r.baselines['group:B'])
        r.baselines.pop('direct:A')
        self.assertIn('group:B', r.baselines)  # 清一个不影响另一个

if __name__ == '__main__':
    unittest.main(verbosity=2)
