"""回复链路发图：触发、上限、异步生图与失败兜底。

2026-10-18 起生图改为**后台线程**（约 20 秒，不需要 UI，不该堵队列），
发送由主循环的 flush_pending_images 完成——所以"调用后立即发送"的旧断言
全部改成了"排队 → flush → 发送"。
"""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from test_integration import BASE_CFG, make_resident, stop_patches


class SyncThread:
    """把后台线程换成同步执行：测试里才能确定性地断言中间状态。"""

    def __init__(self, target=None, args=(), daemon=None):
        self._target, self._args = target, args

    def start(self):
        self._target(*self._args)


class WantsImageTests(unittest.TestCase):
    def setUp(self):
        self.r = __import__('resident').Resident.__new__(__import__('resident').Resident)

    def test_explicit_keyword_detected(self):
        conf = {'keywords': ['发图', '发张图', '画一张']}
        fresh = [{'text': '你能发张图吗'}]
        self.assertTrue(self.r.wants_image(fresh, conf))
        self.assertFalse(self.r.wants_image([{'text': '你能发图吗'}], {'keywords': ['发张图']}))

    def test_plain_chat_is_ignored(self):
        conf = {'keywords': ['发图', '画一张']}
        self.assertFalse(self.r.wants_image([{'text': '今天天气不错'}], conf))

    def test_no_keywords_means_never(self):
        self.assertFalse(self.r.wants_image([{'text': '发图'}], {'keywords': []}))


class ImageReplyTests(unittest.TestCase):
    def setUp(self):
        self.cfg = dict(BASE_CFG)
        self.r = make_resident(self.cfg)
        self.addCleanup(stop_patches, self.r)
        self.addCleanup(self.r.db.close)
        self.png = tempfile.NamedTemporaryFile(suffix='.png', delete=False)
        self.png.write(b'raw-bytes')
        self.png.close()
        self.ui = Mock()
        self.r.latest_send_config = Mock(return_value={})
        self.r.image_sent = {}

    def conf(self, **kw):
        return dict(self.cfg, image_reply=dict({'enabled': True, 'max_per_hour': 3}, **kw))

    def test_sends_generated_image_and_records_delivery(self):
        with patch('resident.generate_image', return_value=Path(self.png.name)), \
             patch('resident.prepare_png_bytes', return_value=(b'png-bytes', 8, 8)), \
             patch('resident.threading.Thread', SyncThread):
            ok = self.r.maybe_send_image_reply(self.conf(), self.ui, '测试群', 'group:测试群',
                                               [{'text': '发张图看看'}])
        self.assertTrue(ok)                              # 排队生图成功
        self.ui.send_image_png.assert_not_called()       # 异步：此时还没碰 UI
        self.r.nav = Mock()                              # flush 只需要 switch_to
        self.assertEqual(self.r.flush_pending_images(self.cfg, self.ui), 1)
        self.ui.send_image_png.assert_called_once()
        args = self.ui.send_image_png.call_args
        self.assertEqual(args.args[0], b'png-bytes')
        self.assertEqual(args.kwargs['expected_chat'], '测试群')
        row = self.r.db.execute("SELECT state FROM deliveries ORDER BY id DESC LIMIT 1").fetchone()
        self.assertEqual(row[0], 'IMAGE_SUBMITTED')

    def test_failure_is_swallowed_and_reported(self):
        """生图失败：任务标 failed，绝不碰 UI；文字回复早就不受影响。"""
        with patch('resident.generate_image', side_effect=RuntimeError('no key')), \
             patch('resident.threading.Thread', SyncThread):
            ok = self.r.maybe_send_image_reply(self.conf(), self.ui, '测试群', 'group:测试群',
                                               [{'text': '画一张'}])
        self.assertTrue(ok)                              # 排队成功 ≠ 图一定生成成功
        self.r.nav = Mock()                              # flush 用例里不需要真导航
        self.ui.send_image_png.assert_not_called()
        job = self.r._image_jobs()[0]
        self.assertEqual(job['state'], 'failed')
        self.assertEqual(self.r.flush_pending_images(self.cfg, self.ui), 0)
        self.ui.send_image_png.assert_not_called()

    def test_hourly_cap(self):
        self.r.image_sent = {'group:测试群': [__import__('time').time()] * 3}
        with patch('resident.generate_image') as gen:
            ok = self.r.maybe_send_image_reply(self.conf(), self.ui, '测试群', 'group:测试群',
                                               [{'text': '发图'}])
        self.assertFalse(ok)
        gen.assert_not_called()
        status = json.loads((Path(self.r._tmp) / 'status.json').read_text())
        self.assertEqual(status['state'], 'image_reply_rate_limited')

    def test_disabled_switch_blocks(self):
        with patch('resident.generate_image') as gen:
            ok = self.r.maybe_send_image_reply(self.conf(enabled=False), self.ui, '测试群',
                                               'group:测试群', [{'text': '发图'}])
        self.assertFalse(ok)
        gen.assert_not_called()

    def test_non_image_request_does_nothing(self):
        with patch('resident.generate_image') as gen:
            ok = self.r.maybe_send_image_reply(self.conf(), self.ui, '测试群', 'group:测试群',
                                               [{'text': '晚上吃啥'}])
        self.assertFalse(ok)
        gen.assert_not_called()


if __name__ == '__main__':
    unittest.main()
