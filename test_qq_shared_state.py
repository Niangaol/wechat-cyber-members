"""共享模块的状态目录注入测试（QQ 与微信必须能用不同 state_dir 且互不串）。

背景：QQ 入口要独立的状态/凭据/session（~/.local/state/qq-bot/），但不能为此改坏微信。
这些用例锁死"不传 state_dir 就完全等于老行为"这条兼容性承诺。
"""
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / 'src'))

import imagegen                                                  # noqa: E402
import model_api                                                 # noqa: E402
from imagegen import _key                                        # noqa: E402
from model_api import ModelProvider, STATE, resolve_providers     # noqa: E402


class StateDirInjectionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_default_state_dir_is_wechat(self):
        """不传 state_dir：凭据/session 仍指向微信老目录（向后兼容的硬要求）。"""
        p = ModelProvider({'base_url': 'https://x', 'model': 'm'}, 'main')
        self.assertEqual(p.state_dir, STATE)
        self.assertEqual(p.session_file, STATE / 'model-session.txt')

    def test_injected_state_dir_moves_session_and_credentials(self):
        (self.dir / 'credentials.json').write_text(json.dumps({'api_key': 'qq-key'}))
        p = ModelProvider({'base_url': 'https://x', 'model': 'm'}, 'main',
                          state_dir=self.dir)
        self.assertEqual(p.state_dir, self.dir)
        self.assertEqual(p.session_file, self.dir / 'model-session.txt')
        self.assertEqual(p.key(), 'qq-key')

    def test_absolute_credential_file_shares_wechat_credentials(self):
        """credential_file 给绝对路径时可以直接复用微信那份凭据，不用复制密钥。"""
        shared = self.dir / 'shared-credentials.json'
        shared.write_text(json.dumps({'api_key': 'shared-key'}))
        p = ModelProvider({'base_url': 'https://x', 'model': 'm',
                           'credential_file': str(shared),
                           'credential_key': 'api_key'}, 'main', state_dir=self.dir / 'nope')
        self.assertEqual(p.key(), 'shared-key')

    def test_resolve_providers_passes_state_dir(self):
        cfg = {'model': {'base_url': 'https://x', 'model': 'm'}}
        provs = resolve_providers(cfg, state_dir=self.dir)
        self.assertEqual(provs['main'].state_dir, self.dir)
        self.assertEqual(provs['ocr'].state_dir, self.dir)

    def test_step_plan_keeps_injected_state_dir(self):
        from multimodal import StepPlan
        cfg = {'model': {'base_url': 'https://x', 'model': 'm'}}
        sp = StepPlan(cfg, state_dir=self.dir)
        self.assertEqual(sp.state_dir, self.dir)
        self.assertEqual(sp.main.state_dir, self.dir)

    def test_imagegen_key_reads_injected_dir(self):
        (self.dir / 'credentials.json').write_text(json.dumps({'image_gen_api_key': 'img'}))
        self.assertEqual(_key(self.dir), 'img')
        self.assertEqual(_key(), _key())          # 不传时仍读老目录，不抛异常

    def test_imagegen_key_accepts_absolute_credentials_file(self):
        f = self.dir / 'gen.json'
        f.write_text(json.dumps({'image_gen_api_key': 'img2'}))
        self.assertEqual(_key(None, str(f)), 'img2')

    def test_imagegen_generate_signature_is_backward_compatible(self):
        """老调用方（只有 prompt / ref_image）的签名必须还能用。"""
        import inspect
        sig = inspect.signature(imagegen.generate)
        for name in ('prompt', 'ref_image', 'state_dir', 'credentials_file'):
            self.assertIn(name, sig.parameters)
        self.assertIsNone(sig.parameters['state_dir'].default)


if __name__ == '__main__':
    unittest.main()
