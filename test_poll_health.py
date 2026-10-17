"""轮询汇总不能把切换失败/渲染异常伪装成已观察。"""
import json
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from test_integration import BASE_CFG, make_resident, stop_patches
from wechat_ui import SafetyError


class PollHealthTests(unittest.TestCase):
    def setUp(self):
        self.cfg = dict(BASE_CFG, target_chat='', watch_chats=['G'], group_whitelist=['G'])
        self.r = make_resident(self.cfg)
        self.addCleanup(stop_patches, self.r)
        self.addCleanup(self.r.db.close)
        self.r.nav = SimpleNamespace(switch_to=lambda name: object())

    def status(self):
        return json.loads((Path(self.r._tmp) / 'status.json').read_text())

    def observe_event(self, state, name='G'):
        def observe(*args):
            self.r.status(state, chat='group:' + name)
            return state == 'queued'
        return observe

    def test_switch_failure_not_overwritten_as_polled(self):
        with patch.object(self.r.nav, 'switch_to', side_effect=SafetyError('找不到目标')):
            self.r.observe_all(self.cfg, None, None)
        result = self.status()
        self.assertEqual(result['state'], 'poll_degraded')
        self.assertEqual(result['observed_chats'], 0)
        self.assertEqual(result['poll_health']['outcomes'][0]['state'], 'paused_chat_switch')
        self.assertFalse(result['poll_health']['outcomes'][0]['title_verified'])

    def test_unstable_render_is_not_successful_observation(self):
        with patch.object(self.r, 'observe_one', side_effect=self.observe_event('render_unstable')):
            self.r.observe_all(self.cfg, None, None)
        result = self.status()
        self.assertEqual(result['state'], 'poll_degraded')
        outcome = result['poll_health']['outcomes'][0]
        self.assertTrue(outcome['title_verified'])
        self.assertFalse(outcome['observed'])
        self.assertEqual(outcome['state'], 'render_unstable')

    def test_observe_error_streak_survives_final_summary(self):
        self.r.chat_failures['G'] = 4
        with patch.object(self.r, 'observe_one', side_effect=ValueError('bad frame')):
            self.r.observe_all(self.cfg, None, None)
        self.assertEqual(self.status()['poll_health']['outcomes'][0]['state'], 'observe_degraded')
        self.assertEqual(self.status()['state'], 'poll_degraded')

    def test_healthy_baseline_is_reported_with_count(self):
        self.r.baselines['group:G'] = ['a', 'b']
        with patch.object(self.r, 'observe_one', side_effect=self.observe_event('watching')):
            self.r.observe_all(self.cfg, None, None)
        result = self.status()
        self.assertEqual(result['state'], 'polled')
        self.assertEqual(result['observed_chats'], 1)
        self.assertEqual(result['poll_health']['outcomes'][0]['baseline_count'], 2)
        # 后续学习/发送状态不能抹掉本轮观察健康证据。
        self.r.status('reply_draft_ready')
        self.assertEqual(self.status()['poll_health'], result['poll_health'])

    def test_debounce_is_waiting_not_proven_observed(self):
        with patch.object(self.r, 'observe_one', side_effect=self.observe_event('debouncing')):
            self.r.observe_all(self.cfg, None, None)
        self.assertEqual(self.status()['state'], 'poll_waiting')
        self.assertEqual(self.status()['observed_chats'], 0)

    def test_mixed_chat_failure_does_not_erase_healthy_chat(self):
        cfg = dict(self.cfg, watch_chats=['G', 'H'], group_whitelist=['G', 'H'])
        def switch(name):
            if name == 'H':
                raise SafetyError('无法核验H')
            return object()
        self.r.nav.switch_to = switch
        with patch.object(self.r, 'observe_one', side_effect=self.observe_event('watching')):
            self.r.observe_all(cfg, None, None)
        result = self.status()
        self.assertEqual(result['state'], 'poll_degraded')
        self.assertEqual(result['observed_chats'], 1)
        self.assertEqual(len(result['poll_health']['outcomes']), 2)

    def test_empty_watch_list_never_claims_success(self):
        self.r.observe_all(dict(self.cfg, watch_chats=[]), None, None)
        self.assertEqual(self.status()['state'], 'poll_degraded')
        self.assertEqual(self.status()['observed_chats'], 0)


if __name__ == '__main__':
    unittest.main()
