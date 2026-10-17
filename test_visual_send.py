import sys, unittest
from pathlib import Path
from unittest.mock import patch
from PIL import Image, ImageDraw
sys.path.insert(0, str(Path(__file__).parent/'src'))
from visual_parse import has_at_mention
from calibrate import find_color_region, find_dark_icon, build_coords, save_coords, WECHAT_GREEN

class AtMentionTests(unittest.TestCase):
    def _bubble(self, with_blue):
        img = Image.new('RGB', (300, 100), (255, 255, 255))
        d = ImageDraw.Draw(img)
        d.text((20, 40), '普通消息文字', fill=(0, 0, 0))
        if with_blue:
            d.text((100, 40), '@我', fill=(70, 130, 255))  # 微信@高亮蓝
        return img
    def test_blue_mention_detected(self):
        img = self._bubble(True)
        self.assertTrue(has_at_mention(img, (0, 0, 300, 100)))
    def test_no_blue_not_detected(self):
        img = self._bubble(False)
        self.assertFalse(has_at_mention(img, (0, 0, 300, 100)))
    def test_small_region_ignored(self):
        img = self._bubble(True)
        self.assertFalse(has_at_mention(img, (0, 0, 5, 5)))

class CalibrateTests(unittest.TestCase):
    def test_find_green_button(self):
        img = Image.new('RGB', (550, 550), (240, 240, 240))
        d = ImageDraw.Draw(img)
        d.rectangle([400, 480, 520, 520], fill=WECHAT_GREEN)  # 发表按钮
        regions = find_color_region(img, WECHAT_GREEN)
        self.assertTrue(len(regions) >= 1)
        cx, cy = regions[0][0], regions[0][1]
        self.assertTrue(400 <= cx <= 520 and 480 <= cy <= 520)
    def test_no_green_returns_empty(self):
        img = Image.new('RGB', (100, 100), (255, 255, 255))
        self.assertEqual(find_color_region(img, WECHAT_GREEN), [])
    def test_find_dark_icon(self):
        img = Image.new('RGB', (100, 100), (255, 255, 255))
        d = ImageDraw.Draw(img)
        d.rectangle([10, 10, 30, 30], fill=(30, 30, 30))  # 相机图标
        pos = find_dark_icon(img, (0, 0, 80, 80))
        self.assertIsNotNone(pos)
        self.assertTrue(10 <= pos[0] <= 30 and 10 <= pos[1] <= 30)
    def test_build_coords(self):
        img = Image.new('RGB', (550, 550), (240, 240, 240))
        d = ImageDraw.Draw(img)
        d.rectangle([400, 480, 520, 520], fill=WECHAT_GREEN)
        d.rectangle([10, 10, 30, 30], fill=(30, 30, 30))
        coords = build_coords(img, (1004, 524))
        self.assertIn('publish_button', coords)
        bx, by = coords['publish_button']
        # 检测中心应落在按钮 bbox 内（采样+聚合有少量偏移，验证在范围内）
        self.assertTrue(1004 + 400 <= bx <= 1004 + 520)
        self.assertTrue(524 + 480 <= by <= 524 + 520)
        self.assertIn('camera_icon', coords)
    def test_save_coords(self):
        import tempfile, json as J
        with tempfile.TemporaryDirectory() as td:
            p = save_coords({'camera_icon': [1, 2]}, Path(td)/'c.json')
            self.assertEqual(J.loads(Path(p).read_text()), {'camera_icon': [1, 2]})

class SendImageTests(unittest.TestCase):
    """send_image → send_image_png 的闸门逻辑（mock 掉真实点击/截图）。"""
    def setUp(self):
        sleeper = patch('wechat_ui.time.sleep')
        sleeper.start()
        self.addCleanup(sleeper.stop)
        import tempfile
        from wechat_ui import WeChatUI, prepare_png_bytes
        cfg = {'display': ':99', 'target_chat': '很帅的年糕', 'reply_max_chars': 200}
        self.ui = WeChatUI(cfg)
        self.ui.wid = '0x1'          # 已核验窗口（focus_window 要求）
        self.img_path = Path(tempfile.mkdtemp())/'x.png'
        Image.new('RGB', (10, 10), (255, 0, 0)).save(self.img_path)
        self.png = prepare_png_bytes(self.img_path.read_bytes())[0]
        # 剪贴板/按键/回读全部 mock 掉：只验证闸门顺序
        self.ui.clip_read = lambda: ('none', b'')
        self.ui.clip_write = lambda *a, **k: None
        self.keys = []
        self.ui.key = lambda k: self.keys.append(k)
        self.ui.run = lambda args, data=None, timeout=12: self.png
    def _shot(self, preview=False):
        img = Image.new('RGB', (1021, 740), (237, 237, 237))
        if preview:
            ImageDraw.Draw(img).rectangle((355, 635, 510, 672), fill=(200, 180, 140))
        return img
    def test_draft_blocks(self):
        from wechat_ui import SafetyError
        with patch.object(self.ui, 'verify_target', return_value=self._shot()), \
             patch.object(self.ui, '_draft_text', return_value='草稿'):
            with self.assertRaises(SafetyError):
                self.ui.send_image(str(self.img_path))
    def test_no_preview_aborts(self):
        # 粘贴后输入区没有新预览 → 中止，且绝不按 Return
        from wechat_ui import SafetyError
        with patch.object(self.ui, 'verify_target', return_value=self._shot()), \
             patch.object(self.ui, '_draft_text', return_value=''):
            with self.assertRaises(SafetyError):
                self.ui.send_image(str(self.img_path))
        self.assertNotIn('Return', self.keys)
    def test_preview_present_sends(self):
        # 调用顺序：起始、粘贴前、预览、ready、last、最终
        shots = [self._shot(False), self._shot(False), self._shot(True),
                 self._shot(True), self._shot(True), self._shot(False)]
        with patch.object(self.ui, 'verify_target', side_effect=shots), \
             patch.object(self.ui, '_draft_text', return_value=''):
            self.ui.send_image(str(self.img_path))
        self.assertIn('ctrl+v', self.keys)
        self.assertIn('Return', self.keys)

if __name__ == '__main__':
    unittest.main(verbosity=2)
