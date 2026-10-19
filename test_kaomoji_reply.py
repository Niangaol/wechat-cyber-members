"""颜文字快捷回复：全池过闸、关键词命中、频率闸与降级路径。

2026-10-19 用户要求「发送颜文字」：消息命中关键词 → 内置池（src/kaomoji.py）
随机一条 → 直接发送，不调模型、不花额度。集成测试用 SimulatedUI 走**真实**
send_text 链路（输出闸+标题核验+逐字回读），断言发出去的就是池子里的一条。
"""
import json
import sys
import time
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT/'src'))

from kaomoji import KAOMOJI_POOL
from output_safe import check_output

from resident import Resident
from test_integration import BASE_CFG, FakeConfig, FakeModel, make_resident, stop_patches
from test_send_binding import SimulatedUI


class PoolSafetyTests(unittest.TestCase):
    def test_pool_not_empty_and_unique(self):
        self.assertGreaterEqual(len(KAOMOJI_POOL), 30, '池子太小，颜文字不够发')
        self.assertEqual(len(KAOMOJI_POOL), len(set(KAOMOJI_POOL)), '池子里有重复颜文字')

    def test_every_entry_passes_output_gate(self):
        """每条都必须过 output_safe.check_output——不过闸的条目在实机里会被
        降级（等于白放），甚至把正常消息拖进 UNSAFE_RETRY。加新条目时这里会红。"""
        for k in KAOMOJI_POOL:
            with self.subTest(kaomoji=k):
                self.assertEqual(check_output(k, 200), k)


class WantsKaomojiTests(unittest.TestCase):
    def setUp(self):
        self.r = Resident.__new__(Resident)
        self.conf = {'keywords': ['颜文字', '来条颜文字', '来个颜文字', '颜文字呢',
                                 'kaomoji', '发表情']}

    def test_keywords_detected(self):
        for word in ['颜文字', '来条颜文字', '来个颜文字', '颜文字呢', '发表情']:
            self.assertTrue(self.r.wants_kaomoji([{'text': '给我%s' % word}], self.conf), word)

    def test_kaomoji_case_insensitive(self):
        self.assertTrue(self.r.wants_kaomoji([{'text': '来点 KAOMOJI'}], self.conf))
        self.assertTrue(self.r.wants_kaomoji([{'text': 'KaomoJi 呢'}], self.conf))

    def test_plain_chat_ignored(self):
        self.assertFalse(self.r.wants_kaomoji([{'text': '今天天气不错'}], self.conf))

    def test_empty_keywords_never_match(self):
        self.assertFalse(self.r.wants_kaomoji([{'text': '颜文字'}], {'keywords': []}))


class KaomojiAllowedTests(unittest.TestCase):
    def setUp(self):
        self.r = Resident.__new__(Resident)
        self.conf = {'max_per_hour': 30, 'cooldown_s': 10}

    def test_first_hit_allowed_then_cooldown_blocks(self):
        self.assertTrue(self.r.kaomoji_reply_allowed('g:1', self.conf))
        self.assertFalse(self.r.kaomoji_reply_allowed('g:1', self.conf), '冷却内第二次要拒')

    def test_cooldown_expiry_allows_again(self):
        self.assertTrue(self.r.kaomoji_reply_allowed('g:1', self.conf))
        self.r.kaomoji_last['g:1'] -= 11          # 把上次发送时间往前挪 11 秒
        self.assertTrue(self.r.kaomoji_reply_allowed('g:1', self.conf))

    def test_hourly_cap_blocks_after_limit(self):
        conf = {'max_per_hour': 2, 'cooldown_s': 0}
        self.assertTrue(self.r.kaomoji_reply_allowed('g:1', conf))
        self.assertTrue(self.r.kaomoji_reply_allowed('g:1', conf))
        self.assertFalse(self.r.kaomoji_reply_allowed('g:1', conf), '到顶要拒')
        # 一小时后窗口滑过，恢复
        now = time.time()
        self.r.kaomoji_sent['g:1'] = [now - 3601, now - 3601]
        self.assertTrue(self.r.kaomoji_reply_allowed('g:1', conf))

    def test_other_chats_have_independent_quota(self):
        self.assertTrue(self.r.kaomoji_reply_allowed('g:1', self.conf))
        self.assertTrue(self.r.kaomoji_reply_allowed('g:2', self.conf), '别会话不受冷却影响')

    def test_conf_merge_defaults_and_override(self):
        r = make_resident(BASE_CFG)
        self.addCleanup(stop_patches, r)
        self.addCleanup(r.db.close)
        conf = r.kaomoji_reply_conf(dict(BASE_CFG, kaomoji_reply={'max_per_hour': 5}))
        self.assertEqual(conf['max_per_hour'], 5)
        self.assertEqual(conf['cooldown_s'], 10, '没覆盖的键保留默认值')
        self.assertIn('颜文字', conf['keywords'])


class KaomojiIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.cfg = dict(BASE_CFG, group_whitelist=['测试群'])
        self.r = make_resident(self.cfg)
        self.addCleanup(stop_patches, self.r)
        self.addCleanup(self.r.db.close)
        self.ui = SimulatedUI(self.cfg, '测试群(4)')
        self.r.nav = None                       # process_queue 里会自建 ChatNavigator
        self.model = FakeModel()
        self.ck = 'group:测试群'
        self.r.last_frame[self.ck] = self.ui.chat_image(self.ui.capture())
        sleeper = patch('wechat_ui.time.sleep')
        sleeper.start()
        self.addCleanup(sleeper.stop)

    def enqueue(self, text):
        return self.r.quota.enqueue(self.ck, 0, json.dumps(
            {'messages': [{'text': text}], 'want_search': False}))

    def process(self, config=None):
        with patch('resident.CONFIG', config or FakeConfig(self.cfg)):
            self.r.process_queue(self.cfg, self.ui, self.model)

    def state(self, qid):
        return self.r.db.execute('SELECT state FROM queue WHERE id=?', (qid,)).fetchone()[0]

    def test_keyword_sends_pool_kaomoji_without_model(self):
        qid = self.enqueue('来条颜文字')
        self.process()
        self.assertEqual(len(self.ui.sent), 1)
        self.assertIn(self.ui.sent[0], KAOMOJI_POOL, '发出去的必须是池子里的一条')
        self.assertEqual(self.model.calls, [], '颜文字分支不调模型、不花额度')
        self.assertEqual(self.state(qid), 'SUBMITTED')

    def test_plain_message_still_goes_to_model(self):
        qid = self.enqueue('你好')
        self.process()
        self.assertEqual(self.ui.sent, ['好的呀'])
        self.assertEqual(self.model.calls, ['reply'])
        self.assertEqual(self.state(qid), 'SUBMITTED')

    def test_disabled_config_falls_back_to_model(self):
        cfg = dict(self.cfg, kaomoji_reply={'enabled': False})
        qid = self.enqueue('来条颜文字')
        with patch('resident.CONFIG', FakeConfig(cfg)):
            self.r.process_queue(cfg, self.ui, self.model)
        self.assertEqual(self.ui.sent, ['好的呀'], '关掉功能后当普通消息回')
        self.assertEqual(self.model.calls, ['reply'])

    def test_cooldown_falls_back_to_model(self):
        qid1 = self.enqueue('颜文字')
        self.process()
        self.assertIn(self.ui.sent[-1], KAOMOJI_POOL, '第一条是颜文字')
        calls_after_first = len(self.model.calls)
        qid2 = self.enqueue('再来条颜文字')
        self.process()
        self.assertEqual(self.ui.sent[-1], '好的呀', '冷却内第二次降级回模型，不会不说话')
        self.assertEqual(len(self.model.calls), calls_after_first + 1)
        self.assertEqual(self.state(qid2), 'SUBMITTED')

    def test_direct_chat_also_gets_kaomoji(self):
        self.ck = 'direct:很帅的年糕'
        self.ui = SimulatedUI(self.cfg, '很帅的年糕')
        self.r.nav = None
        self.r.last_frame[self.ck] = self.ui.chat_image(self.ui.capture())
        qid = self.enqueue('来个颜文字')
        self.process()
        self.assertIn(self.ui.sent[-1], KAOMOJI_POOL, '私聊同样生效')
        self.assertEqual(self.state(qid), 'SUBMITTED')


if __name__ == '__main__':
    unittest.main()
