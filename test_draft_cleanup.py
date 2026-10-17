"""输入框探针 / 草稿清理的单元测试（用桩件，不碰真 UI）。

这两处都有过真事故：空输入框的探针被当成"还有草稿"，导致自动清理永远失败 →
发送被"输入框有草稿"永久拦住。所以单独锁死。
"""
import sys, unittest
from pathlib import Path
from unittest.mock import patch
from PIL import Image
sys.path.insert(0, str(Path(__file__).parent / 'src'))
from wechat_ui import WeChatUI, SafetyError


class InputProbeTests(unittest.TestCase):
    def make_ui(self, clipboard_value):
        ui = WeChatUI.__new__(WeChatUI)          # 跳过 __init__：不连真 X
        ui.cfg = {'display': ':99'}
        ui.last_abs = (0, 0)
        ui.wid = '0x1'
        ui.verify_target = lambda expected_chat=None: Image.new('RGB', (8, 8))
        ui._draft_text = lambda image: False
        ui.run = lambda args, data=None, timeout=12: b''
        ui.key = lambda key: None
        writes = []
        ui.clipboard_write = lambda text: writes.append(text)
        ui.clipboard_read = lambda: clipboard_value
        return ui, writes

    def test_probe_sentinel_means_empty(self):
        """空输入框 ctrl+c 读回的是我们写的探针 —— 那是"空"，不是"有草稿"。"""
        ui, writes = self.make_ui('__WECHAT_INPUT_PROBE__')
        with patch('wechat_ui.time.sleep'):
            self.assertEqual(ui.input_text(), '')
        self.assertIn('__WECHAT_INPUT_PROBE__', writes, '确实要先写探针再读')

    def test_reads_real_draft(self):
        ui, _ = self.make_ui('看到摇一摇了，这是准备摇个隐藏战利品？')
        with patch('wechat_ui.time.sleep'):
            self.assertEqual(ui.input_text(), '看到摇一摇了，这是准备摇个隐藏战利品？')

    def test_unreadable_returns_empty(self):
        ui, _ = self.make_ui(None)
        with patch('wechat_ui.time.sleep'):
            self.assertEqual(ui.input_text(), '')

    def test_clear_refuses_text_that_is_not_ours(self):
        """只清自己写的那句：内容对不上就拒绝，绝不动别人的草稿。"""
        ui, _ = self.make_ui('别人写了一半的话')
        with patch('wechat_ui.time.sleep'):
            with self.assertRaises(SafetyError):
                ui.clear_input(expect_text='我们刚才那句')

    def test_clears_our_own_draft(self):
        ui, _ = self.make_ui('我们刚才那句')
        ui.verify_target = lambda expected_chat=None: Image.new('RGB', (8, 8))
        keys = []
        ui.key = lambda key: keys.append(key)
        reads = iter(['我们刚才那句', ''])       # 清之前有、清之后空
        ui.clipboard_read = lambda: next(reads)
        with patch('wechat_ui.time.sleep'):
            self.assertTrue(ui.clear_input(expect_text='我们刚才那句'))
        self.assertIn('ctrl+a', keys)
        self.assertIn('Delete', keys, '要用 ctrl+a + Delete 清（实测唯一可靠的方式）')


if __name__ == '__main__':
    unittest.main()
