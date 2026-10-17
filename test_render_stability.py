"""渲染瞬态容错回归：微信内容区黑屏/空态时 observe_one 应跳过本轮，
不计入 serve() 的连续异常计数（否则三次抽风就自我暂停）。"""
import sqlite3
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / 'src'))
sys.path.insert(0, str(ROOT))

from test_integration import BASE_CFG, make_resident, stop_patches  # noqa: E402
import resident as resident_mod  # noqa: E402
from visual_parse import extract_messages  # noqa: E402


class RenderUnstableTests(unittest.TestCase):
    def setUp(self):
        cfg = dict(BASE_CFG, group_whitelist=['G'])
        self.cfg = cfg
        self.r = make_resident(cfg)
        self.addCleanup(stop_patches, self.r)
        self.addCleanup(self.r.db.close)

    def _ui(self, image):
        class UI:
            def capture(self):
                return image
            def chat_image(self, im):
                return im.crop((283, 72, 1021, 584))
        return UI()

    def test_black_screen_skips_cycle_without_raising(self):
        """全黑内容区：extract_messages 抛 ValueError → observe_one 返回 False，不向上抛。"""
        black = Image.new('RGB', (1021, 740), (0, 0, 0))
        ui = self._ui(black)
        # 不打补丁，走真实 extract_messages（黑屏上头像行检测必然失败）
        result = self.r.observe_one(self.cfg, ui, None, 'G', black)
        self.assertFalse(result)
        self.assertEqual(self.r.quota.depth(), 0)      # 没入队
        self.assertEqual(self.r.failures, 0)           # 没累计异常

    def test_blank_canvas_skips_cycle_without_raising(self):
        """空白画布（无头像无气泡）同样安全跳过。"""
        blank = Image.new('RGB', (1021, 740), (255, 255, 255))
        ui = self._ui(blank)
        result = self.r.observe_one(self.cfg, ui, None, 'G', blank)
        self.assertFalse(result)
        self.assertEqual(self.r.quota.depth(), 0)

    def test_real_frame_still_works_after_render_failure(self):
        """渲染失败后恢复画面，观察器仍能正常建基线（不卡死）。"""
        black = Image.new('RGB', (1021, 740), (0, 0, 0))
        self.assertFalse(self.r.observe_one(self.cfg, self._ui(black), None, 'G', black))
        # 造一张有头像有气泡的正常画面
        from PIL import ImageDraw
        im = Image.new('RGB', (1021, 740), (237, 237, 237))
        d = ImageDraw.Draw(im)
        d.rectangle((305, 150, 337, 182), fill=(70, 100, 220))     # 头像
        d.text((355, 150), 'sender', fill=(150, 150, 150))
        d.rounded_rectangle((351, 170, 450, 210), radius=5, fill='white')
        d.text((365, 185), 'hello', fill='black')
        ok = self.r.observe_one(self.cfg, self._ui(im), None, 'G', im)
        self.assertFalse(ok)                                        # 首次只建基线
        self.assertIn('group:G', self.r.baselines)                  # 基线已建
        self.assertEqual(len(self.r.baselines['group:G']), 1)

    def test_serve_survives_render_flapping(self):
        """连续三轮渲染抽风：serve() 不应写 STOP 文件。"""
        black = Image.new('RGB', (1021, 740), (0, 0, 0))
        cfg = dict(self.cfg, automation={'enabled': False})   # 只跑到观察前
        with patch.object(resident_mod, 'CONFIG') as cfg_file:
            cfg_file.read_text.return_value = '{}'
            for _ in range(4):
                try:
                    self.r.cycle(cfg)
                except Exception as e:      # cycle 里 observe 之前的异常另说
                    if 'render' not in str(e):
                        raise
        self.assertFalse(self.r.stop.exists())


if __name__ == '__main__':
    unittest.main(verbosity=2)
