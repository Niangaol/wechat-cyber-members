"""群接话策略测试：正式群"@ 必回、普通消息选择性接话"的本地规则。

这里的判定完全不调模型、不花额度——它决定"哪些普通消息值得回"，是上线时最容易被
写成"限流的全接"的地方（那就等于没筛选），所以逐条锁死。
"""
import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / 'src'))
from resident import Resident                                    # noqa: E402

CFG = {
    'mention_aliases': ['年糕Agent', '年糕'],
    'groups': {
        '人机': {'plain_mode': 'selective', 'plain_cooldown_s': 120,
                 'plain_per_hour': 6, 'followup_window_s': 60},
        '闲聊群': {'plain_mode': 'at_only'},
        '测试群': {'plain_mode': 'all'},
    },
}


def resident():
    r = Resident.__new__(Resident)          # 只要判定函数，不需要完整初始化
    r.last_reply_at = {}
    r.plain_replies = {}
    return r


def msgs(text, at_me=0):
    return [{'direction': 'in', 'kind': 'text', 'text': text, 'at_me': at_me,
             'signature': 'sig-' + text[:6]}]


class GroupPolicyTests(unittest.TestCase):
    def test_all_mode_answers_everything(self):
        allow, why = resident().group_plain_decision('测试群', msgs('随便说点啥'), CFG)
        self.assertTrue(allow)
        self.assertEqual(why, 'plain_all')

    def test_unlisted_group_defaults_to_at_only(self):
        allow, why = resident().group_plain_decision('没登记过的群', msgs('在吗'), CFG)
        self.assertFalse(allow)
        self.assertEqual(why, 'plain_at_only')

    def test_at_only_group_ignores_plain(self):
        allow, why = resident().group_plain_decision('闲聊群', msgs('年糕在吗'), CFG)
        self.assertFalse(allow, 'at_only 的群不该接普通消息')
        self.assertEqual(why, 'plain_at_only')

    def test_selective_answers_when_called_by_name(self):
        allow, why = resident().group_plain_decision('人机', msgs('年糕你怎么看'), CFG)
        self.assertTrue(allow)
        self.assertEqual(why, 'plain_called_by_name')

    def test_selective_ignores_plain_chatter(self):
        """没喊名字、也没在追问——只作上下文，不接话（别退化成"限流的全接"）。"""
        allow, why = resident().group_plain_decision('人机', msgs('今天天气不错啊'), CFG)
        self.assertFalse(allow)
        self.assertEqual(why, 'plain_not_addressed')

    def test_selective_answers_followup_question_within_window(self):
        r = resident()
        r.last_reply_at['group:人机'] = time.time() - 10      # 10 秒前刚回过
        allow, why = r.group_plain_decision('人机', msgs('那你吃了吗？'), CFG)
        self.assertTrue(allow)
        self.assertEqual(why, 'plain_followup_question')

    def test_followup_question_outside_window_is_ignored(self):
        r = resident()
        r.last_reply_at['group:人机'] = time.time() - 300     # 已经过了追问窗口
        allow, why = r.group_plain_decision('人机', msgs('那你吃了吗？'), CFG)
        self.assertFalse(allow)
        self.assertEqual(why, 'plain_not_addressed')

    def test_plain_reply_has_cooldown(self):
        r = resident()
        self.assertTrue(r.group_plain_decision('人机', msgs('年糕'), CFG)[0])
        r.plain_replies['人机'] = [time.time()]                # 刚接过一次
        allow, why = r.group_plain_decision('人机', msgs('年糕在嘛'), CFG)
        self.assertFalse(allow)
        self.assertEqual(why, 'plain_cooldown')

    def test_plain_reply_hourly_cap(self):
        r = resident()
        r.plain_replies['人机'] = [time.time() - 1800 + i for i in range(6)]   # 半小时内 6 次
        allow, why = r.group_plain_decision('人机', msgs('年糕帮我看看'), CFG)
        self.assertFalse(allow)
        self.assertEqual(why, 'plain_hourly_cap')

    def test_cooldown_does_not_apply_to_ignored_messages(self):
        """冷却只约束"确实该接"的消息：别人闲聊不该把冷却额度消耗掉。"""
        r = resident()
        r.plain_replies['人机'] = [time.time()]
        allow, why = r.group_plain_decision('人机', msgs('哈哈哈'), CFG)
        self.assertFalse(allow)
        self.assertEqual(why, 'plain_not_addressed', '闲聊不该报"冷却中"')

IDLE_CFG = {
    'mention_aliases': ['年糕Agent', '年糕'],
    'groups': {'人机': {'plain_mode': 'idle', 'plain_cooldown_s': 120,
                         'plain_per_hour': 6, 'followup_window_s': 60}},
}


class IdleModeTests(unittest.TestCase):
    """idle 模式：用户要求「群聊普通消息空闲时可以回一下」。

    「空闲」必须是真的空闲：队列里还有别的活时不接闲聊，免得把正经回复挤到后面；
    冷却与每小时上限照旧生效。
    """

    def resident_with_depth(self, depth):
        r = resident()
        r.quota = type("Q", (), {"depth": lambda self: depth})()
        return r

    def test_idle_answers_chatter_when_queue_empty(self):
        allow, why = self.resident_with_depth(0).group_plain_decision('人机', msgs('今天天气不错啊'), IDLE_CFG)
        self.assertTrue(allow)
        self.assertEqual(why, 'plain_idle')

    def test_idle_skips_chatter_when_busy(self):
        allow, why = self.resident_with_depth(2).group_plain_decision('人机', msgs('今天天气不错啊'), IDLE_CFG)
        self.assertFalse(allow)
        self.assertEqual(why, 'plain_busy')

    def test_busy_override_is_bounded_and_keeps_cooldown(self):
        import copy
        cfg = copy.deepcopy(IDLE_CFG)
        cfg['groups']['人机']['plain_allow_when_busy'] = True
        r = self.resident_with_depth(1)
        self.assertTrue(r.group_plain_decision('人机', msgs('天气不错'), cfg)[0])
        r.plain_replies['人机'] = [time.time()]
        self.assertEqual(r.group_plain_decision('人机', msgs('天气不错'), cfg),
                         (False, 'plain_cooldown'))
        self.assertEqual(self.resident_with_depth(2).group_plain_decision(
            '人机', msgs('天气不错'), cfg), (False, 'plain_busy'))

    def test_at_others_is_never_answered(self):
        """用户 2026-10-18：群里 @ 别人的消息不用回——那是在跟别人说话。"""
        for text in ['@张三 看看这个', '@Metavis 这个怎么修？', '@Vincent 太sb了']:
            with self.subTest(text=text):
                allow, why = self.resident_with_depth(0).group_plain_decision(
                    '人机', msgs(text), IDLE_CFG)
                self.assertFalse(allow)
                self.assertEqual(why, 'plain_at_others')

    def test_at_others_beats_followup_question(self):
        """追问窗口内也不行：@ 别人的问句照样不接。"""
        r = self.resident_with_depth(0)
        r.last_reply_at['group:人机'] = time.time() - 5
        allow, why = r.group_plain_decision('人机', msgs('@李四 这个怎么修？'), IDLE_CFG)
        self.assertEqual((allow, why), (False, 'plain_at_others'))

    def test_at_others_also_blocks_all_mode(self):
        """连 plain_mode=all 也拦：这是全局规则，不是某个群的偏好。"""
        allow, why = resident().group_plain_decision('测试群', msgs('@张三 看看'), CFG)
        self.assertEqual((allow, why), (False, 'plain_at_others'))

    def test_mentioning_the_bot_still_wins_over_at_others(self):
        """同时 @ 机器人和别人：以被喊到为准（OCR 没认出 @ 时的兜底）。"""
        for text in ['年糕 @张三 都看看', '@年糕Agent @张三 看看']:
            with self.subTest(text=text):
                allow, why = self.resident_with_depth(0).group_plain_decision(
                    '人机', msgs(text), IDLE_CFG)
                self.assertTrue(allow)
                self.assertEqual(why, 'plain_called_by_name')

    def test_email_is_not_a_mention(self):
        """邮箱里的 @ 前面不是空白，不能误判成"@ 别人"把正常聊天拦掉。"""
        allow, why = self.resident_with_depth(0).group_plain_decision(
            '人机', msgs('联系我 niangao@example.com'), IDLE_CFG)
        self.assertTrue(allow)
        self.assertEqual(why, 'plain_idle')

    def test_idle_still_answers_when_called_even_if_busy(self):
        allow, why = self.resident_with_depth(3).group_plain_decision('人机', msgs('年糕在吗'), IDLE_CFG)
        self.assertTrue(allow)
        self.assertEqual(why, 'plain_called_by_name')

    def test_idle_respects_cooldown(self):
        r = self.resident_with_depth(0)
        r.plain_replies['人机'] = [time.time()]
        allow, why = r.group_plain_decision('人机', msgs('哈哈哈'), IDLE_CFG)
        self.assertFalse(allow)
        self.assertEqual(why, 'plain_cooldown')

    def test_idle_respects_hourly_cap(self):
        r = self.resident_with_depth(0)
        r.plain_replies['人机'] = [time.time() - 1800 + i for i in range(6)]
        allow, why = r.group_plain_decision('人机', msgs('在吗'), IDLE_CFG)
        self.assertFalse(allow)
        self.assertEqual(why, 'plain_hourly_cap')

    def test_selective_mode_unchanged_by_idle_addition(self):
        """回归：加了 idle 之后，selective 的群不能跟着变吵。"""
        allow, why = self.resident_with_depth(0).group_plain_decision('人机', msgs('今天天气不错啊'), CFG)
        self.assertFalse(allow)
        self.assertEqual(why, 'plain_not_addressed')


if __name__ == '__main__':
    unittest.main()
