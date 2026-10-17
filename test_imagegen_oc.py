"""OC 人设参考图接入生图的回归测试。

覆盖：
- oc_prefix() 从 config/assets/oc-character.md 解析外观描述（文件缺失时退回内置版）
- _ref_image_part() 读图/缩放/base64/容错（不存在、超大、非图片）
- generate() 的 payload 构造：ref_image 有值时 image 片段在 content 最前；
  API 返回 task_id 时走轮询；同步响应直接解码
"""
import base64
import io
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / 'src'))

import imagegen  # noqa: E402
from imagegen import ImageGenError, _ref_image_part, generate, oc_prefix  # noqa: E402


def png_bytes(w=800, h=600, color=(200, 120, 90)):
    im = Image.new('RGB', (w, h), color)
    buf = io.BytesIO()
    im.save(buf, 'PNG')
    return buf.getvalue()


class OcPrefixTests(unittest.TestCase):
    def test_prefix_from_file_has_key_elements(self):
        text = oc_prefix()
        for key in ('年糕', '探险帽', '背包', '靴', '像素'):
            self.assertIn(key, text)
    def test_prefix_fallback_when_file_missing(self):
        with patch.object(imagegen, 'ROOT', Path('/nonexistent-root')):
            text = oc_prefix()
        self.assertIn('年糕', text)
        self.assertIn('像素', text)
    def test_prefix_is_bounded(self):
        self.assertLess(len(oc_prefix()), 600)


class RefImageTests(unittest.TestCase):
    def setUp(self):
        self.tmp = __import__('tempfile').TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)

    def test_missing_file_returns_none(self):
        self.assertIsNone(_ref_image_part(self.dir / 'nope.png'))
    def test_oversize_returns_none(self):
        big = self.dir / 'big.png'
        big.write_bytes(b'x' * (imagegen.REF_IMAGE_MAX_BYTES + 1))
        self.assertIsNone(_ref_image_part(big))
    def test_valid_image_scaled_and_encoded(self):
        p = self.dir / 'ref.png'
        p.write_bytes(png_bytes(1200, 900))
        part = _ref_image_part(p)
        self.assertIsNotNone(part)
        self.assertTrue(part['image'].startswith('data:image/png;base64,'))
        raw = base64.b64decode(part['image'].split(',', 1)[1])
        im = Image.open(io.BytesIO(raw))
        self.assertLessEqual(max(im.size), imagegen.REF_IMAGE_MAX)
    def test_real_oc_reference_encodes(self):
        ref = imagegen.OC_REF
        if not ref.exists():
            self.skipTest('OC 参考图未存放于 %s' % ref)
        part = _ref_image_part(ref)
        self.assertIsNotNone(part)
        self.assertGreater(len(part['image']), 10000)


class PayloadTests(unittest.TestCase):
    """锁 payload 构造：不真发网络请求，只验证发给 _post 的内容。"""

    def setUp(self):
        self.tmp = __import__('tempfile').TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        self.ref = self.dir / 'ref.png'
        self.ref.write_bytes(png_bytes(400, 400))
        self.sent = {}
        def fake_post(url, payload, key, timeout=180):
            self.sent = {'url': url, 'payload': payload}
            return {'output': {'choices': [{'message': {'content': [
                {'image': 'data:image/png;base64,' + base64.b64encode(png_bytes(50, 50)).decode()}
            ]}}]}}
        self.post_patch = patch.object(imagegen, '_post', side_effect=fake_post)
        self.post_patch.start()
        self.addCleanup(self.post_patch.stop)
        self.key_patch = patch.object(imagegen, '_key', return_value='k')
        self.key_patch.start()
        self.addCleanup(self.key_patch.stop)
        self.media_patch = patch.object(imagegen, 'STATE', self.dir)
        self.media_patch.start()
        self.addCleanup(self.media_patch.stop)

    def test_text_only_payload(self):
        out = generate('一只小猫')
        content = self.sent['payload']['input']['messages'][0]['content']
        self.assertEqual(content, [{'text': '一只小猫'}])
        self.assertTrue(out.exists())
    def test_ref_image_goes_first_in_content(self):
        generate('一只小猫', ref_image=str(self.ref))
        content = self.sent['payload']['input']['messages'][0]['content']
        self.assertEqual(len(content), 2)
        self.assertIn('image', content[0])            # 图在前
        self.assertEqual(content[1], {'text': '一只小猫'})  # 文字指令在后
    def test_missing_ref_falls_back_to_text(self):
        generate('一只小猫', ref_image=str(self.dir / 'nope.png'))
        content = self.sent['payload']['input']['messages'][0]['content']
        self.assertEqual(content, [{'text': '一只小猫'}])
    def test_no_key_raises(self):
        with patch.object(imagegen, '_key', return_value=''):
            with self.assertRaises(ImageGenError):
                generate('x')
    def test_empty_prompt_raises(self):
        with self.assertRaises(ImageGenError):
            generate('   ')
    def test_task_id_response_polls(self):
        def fake_post_then_task(url, payload, key, timeout=180):
            if 'tasks' not in url:
                return {'output': {'task_id': 'T1'}}
            return {'output': {'task_status': 'SUCCEEDED', 'choices': [
                {'message': {'content': [{'image':
                 'data:image/png;base64,' + base64.b64encode(png_bytes(30, 30)).decode()}]}}]}}

        def fake_get(url, key, timeout=60):
            return fake_post_then_task(url, None, key, timeout)
        with patch.object(imagegen, '_post', side_effect=fake_post_then_task), \
             patch.object(imagegen, '_get', side_effect=fake_get), \
             patch.object(imagegen.time, 'sleep'):
            out = generate('轮询测试')
        self.assertTrue(out.exists())


if __name__ == '__main__':
    unittest.main(verbosity=2)
