"""qq/core/policy.py 的离线单测：接话判定链（契约第 3 节）。

不联网、不碰生产库、不写任何文件。
跑法：cd /mnt/d/AgentPrograms/wechat-bot && python3 -m unittest test_qq_core_policy -v
"""
import sys
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'src'))

from quota import PRIORITY_DIRECT, PRIORITY_GROUP_AT, PRIORITY_GROUP_PLAIN   # noqa: E402

from qq.core import envelope, policy                                         # noqa: E402
from qq.core.policy import decide                                            # noqa: E402


def make_event(chat_type='group', chat_id='20002', text='你好', at_me=False,
               at_all=False, self_id='10001'):
    """直接构造 QEvent：policy 只读字段，不必绕一圈 OneBot 解析。"""
    return envelope.QEvent(self_id=self_id, chat_type=chat_type, chat_id=chat_id,
                           sender_id='30003', sender_name='年糕', message_id='1',
                           time=time.time(), at_me=at_me, at_all=at_all, text=text,
                           images=[], segments=[], raw={})


def config(**over):
    base = {
        'direct_policy': 'blacklist',
        'direct_blacklist': ['40004'],
        'groups': {'20002': {'plain_mode': 'at_only'}},
        'mention_aliases': ['年糕'],
        'min_reply_seconds': 3,
    }
    base.update(over)
    return base


def run(event, cfg=None, now=1000.0, depth=0, last_reply=0, plain_times=None):
    return decide(event, cfg if cfg is not None else config(), now=now,
                  queue_depth=depth, last_reply_at=last_reply,
                  group_plain_times=plain_times)


class ChatTypeTests(unittest.TestCase):
    def test_unknown_chat_type_is_ignored(self):
        self.assertEqual(run(make_event(chat_type='discuss')).action, 'ignore')

    def test_none_event_is_ignored(self):
        self.assertEqual(decide(None, config(), now=1.0, queue_depth=0,
                                last_reply_at=0, group_plain_times=None).action,
                         'ignore')

    def test_non_dict_config_is_ignored(self):
        self.assertEqual(decide(make_event(), [], now=1.0, queue_depth=0,
                                last_reply_at=0, group_plain_times=None).action,
                         'ignore')


class DirectTests(unittest.TestCase):
    def test_blacklisted_private_is_ignored(self):
        decision = run(make_event(chat_type='private', chat_id='40004'))
        self.assertEqual(decision.action, 'ignore')
        self.assertEqual(decision.reason, 'direct_blacklist')

    def test_other_private_replies_with_direct_priority(self):
        decision = run(make_event(chat_type='private', chat_id='30003'))
        self.assertEqual(decision.action, 'reply')
        self.assertEqual(decision.priority, PRIORITY_DIRECT)

    def test_default_policy_is_blacklist(self):
        cfg = config()
        cfg.pop('direct_policy')
        self.assertEqual(run(make_event(chat_type='private', chat_id='30003'),
                             cfg).action, 'reply')

    def test_whitelist_requires_membership(self):
        cfg = config(direct_policy='whitelist', direct_whitelist=['30003'])
        ignored = run(make_event(chat_type='private', chat_id='99999'), cfg)
        self.assertEqual(ignored.action, 'ignore')
        self.assertEqual(ignored.reason, 'direct_not_whitelisted')
        allowed = run(make_event(chat_type='private', chat_id='30003'), cfg)
        self.assertEqual(allowed.action, 'reply')
        self.assertEqual(allowed.priority, PRIORITY_DIRECT)

    def test_invalid_direct_policy_is_ignored(self):
        self.assertEqual(run(make_event(chat_type='private', chat_id='30003'),
                             config(direct_policy='whatever')).action, 'ignore')

    def test_bad_blacklist_type_is_ignored(self):
        self.assertEqual(run(make_event(chat_type='private', chat_id='30003'),
                             config(direct_blacklist='40004')).action, 'ignore')

    def test_blacklist_accepts_int_and_str_ids(self):
        cfg = config(direct_blacklist=[40004])
        self.assertEqual(run(make_event(chat_type='private', chat_id='40004'),
                             cfg).action, 'ignore')


class GroupRegistrationTests(unittest.TestCase):
    def test_unregistered_group_is_ignored(self):
        decision = run(make_event(chat_id='99999'))
        self.assertEqual(decision.action, 'ignore')
        self.assertEqual(decision.reason, 'group_not_registered')

    def test_missing_groups_config_ignores_all_groups(self):
        self.assertEqual(run(make_event(), config(groups=None)).action, 'ignore')

    def test_groups_wrong_type_is_ignored(self):
        self.assertEqual(run(make_event(), config(groups=['20002'])).action,
                         'ignore')

    def test_group_entry_wrong_type_is_ignored(self):
        self.assertEqual(run(make_event(), config(groups={'20002': 'idle'})).action,
                         'ignore')


class GroupAtTests(unittest.TestCase):
    def test_at_me_replies_with_top_priority(self):
        decision = run(make_event(at_me=True))
        self.assertEqual(decision.action, 'reply')
        self.assertEqual(decision.priority, PRIORITY_GROUP_AT)
        self.assertEqual(decision.reason, 'at_me')

    def test_at_all_is_not_at_me(self):
        """@全体成员不是叫我：不能当成被 @。"""
        decision = run(make_event(text='@全体成员 开会了', at_all=True))
        self.assertEqual(decision.action, 'context_only')
        self.assertEqual(decision.reason, 'plain_at_only')

    def test_cq_reply_quote_is_not_at_me(self):
        """契约 §10 D11：引用回复（[CQ:reply]）不算"被 @"，at_only 群里只当上下文。"""
        event = make_event(text='在吗')
        event.segments = [{'type': 'reply', 'data': {'id': '12345'}},
                          {'type': 'text', 'data': {'text': '在吗'}}]
        self.assertFalse(event.at_me)
        decision = run(event)
        self.assertEqual(decision.action, 'context_only')

    def test_text_fake_at_hits_alias(self):
        """手打的 @年糕 没有 at 段，但确实是在叫人 → 走别名通道、最高优先级。"""
        event = make_event(text='@年糕 在吗')
        self.assertFalse(event.at_me)
        decision = run(event)
        self.assertEqual(decision.action, 'reply')
        self.assertEqual(decision.priority, PRIORITY_GROUP_AT)
        self.assertEqual(decision.reason, 'mention_alias')

    def test_alias_from_group_entry_overrides_global(self):
        cfg = config(mention_aliases=['别的名字'],
                     groups={'20002': {'plain_mode': 'at_only',
                                       'mention_aliases': ['小助手']}})
        self.assertEqual(run(make_event(text='小助手 帮我看看'), cfg).action, 'reply')
        self.assertEqual(run(make_event(text='年糕 帮我看看'), cfg).action,
                         'context_only')

    def test_alias_match_ignores_case(self):
        cfg = config(mention_aliases=['YearCake'])
        self.assertEqual(run(make_event(text='yearcake 在吗'), cfg).action, 'reply')

    def test_bad_alias_type_is_treated_as_missing(self):
        """契约 §10 S1：别名类型写错按"没配别名"处理，不能让整个群 ignore。"""
        cfg = config(mention_aliases='年糕')
        self.assertEqual(run(make_event(text='年糕 在吗'), cfg).action,
                         'context_only')
        self.assertEqual(run(make_event(text='看这个', at_me=True), cfg).action,
                         'reply', '真 @ 必须不受影响')


class FollowupTests(unittest.TestCase):
    def setUp(self):
        # idle+追问都会走到"要不要接"的判定，用 selective 隔离出追问这一条通道
        self.cfg = config(groups={'20002': {'plain_mode': 'selective'}})

    def test_question_within_window_replies(self):
        decision = run(make_event(text='那这个怎么弄'), self.cfg,
                       now=1000.0, last_reply=970.0)
        self.assertEqual(decision.action, 'reply')
        self.assertEqual(decision.priority, PRIORITY_GROUP_AT)
        self.assertEqual(decision.reason, 'followup_question')

    def test_statement_within_window_stays_context(self):
        decision = run(make_event(text='挺好的'), self.cfg,
                       now=1000.0, last_reply=970.0)
        self.assertEqual(decision.action, 'context_only')
        self.assertEqual(decision.reason, 'plain_selective')

    def test_question_outside_window_stays_context(self):
        decision = run(make_event(text='那这个怎么弄'), self.cfg,
                       now=1000.0, last_reply=900.0)
        self.assertEqual(decision.action, 'context_only')

    def test_window_can_come_from_group_entry(self):
        cfg = config(groups={'20002': {'plain_mode': 'selective',
                                       'followup_window_s': 10}})
        self.assertEqual(run(make_event(text='为什么'), cfg, now=1000.0,
                             last_reply=980.0).action, 'context_only')
        self.assertEqual(run(make_event(text='为什么'), cfg, now=1000.0,
                             last_reply=995.0).action, 'reply')

    def test_no_reply_yet_means_no_followup(self):
        self.assertEqual(run(make_event(text='为什么'), self.cfg,
                             last_reply=0).action, 'context_only')


class PlainModeTests(unittest.TestCase):
    def group(self, mode, **extra):
        entry = {'plain_mode': mode}
        entry.update(extra)
        return config(groups={'20002': entry})

    def test_at_only_is_context_only(self):
        decision = run(make_event(text='今天天气不错'), self.group('at_only'))
        self.assertEqual(decision.action, 'context_only')
        self.assertEqual(decision.reason, 'plain_at_only')

    def test_selective_is_context_only(self):
        decision = run(make_event(text='今天天气不错'), self.group('selective'))
        self.assertEqual(decision.action, 'context_only')
        self.assertEqual(decision.reason, 'plain_selective')

    def test_idle_replies_when_queue_is_free(self):
        decision = run(make_event(text='今天天气不错'), self.group('idle'), depth=0)
        self.assertEqual(decision.action, 'reply')
        self.assertEqual(decision.priority, PRIORITY_GROUP_PLAIN)
        self.assertEqual(decision.reason, 'plain_idle')

    def test_idle_stays_quiet_when_queue_is_busy(self):
        decision = run(make_event(text='今天天气不错'), self.group('idle'), depth=1)
        self.assertEqual(decision.action, 'context_only')
        self.assertEqual(decision.reason, 'plain_busy')

    def test_idle_respects_cooldown(self):
        decision = run(make_event(text='今天天气不错'), self.group('idle'),
                       now=1000.0, plain_times=[950.0])
        self.assertEqual(decision.action, 'context_only')
        self.assertEqual(decision.reason, 'plain_cooldown')

    def test_idle_replies_after_cooldown(self):
        decision = run(make_event(text='今天天气不错'), self.group('idle'),
                       now=1000.0, plain_times=[700.0])
        self.assertEqual(decision.action, 'reply')

    def test_group_cooldown_override(self):
        cfg = self.group('idle', plain_cooldown_s=600)
        self.assertEqual(run(make_event(text='闲聊'), cfg, now=1000.0,
                             plain_times=[700.0]).action, 'context_only')

    def test_all_replies(self):
        decision = run(make_event(text='今天天气不错'), self.group('all'))
        self.assertEqual(decision.action, 'reply')
        self.assertEqual(decision.priority, PRIORITY_GROUP_PLAIN)
        self.assertEqual(decision.reason, 'plain_all')

    def test_all_replies_even_when_busy(self):
        self.assertEqual(run(make_event(text='闲聊'), self.group('all'),
                             depth=5).action, 'reply')

    def test_unknown_mode_falls_back_to_at_only(self):
        decision = run(make_event(text='闲聊'), self.group('freestyle'))
        self.assertEqual(decision.action, 'context_only')
        self.assertEqual(decision.reason, 'plain_at_only')

    def test_missing_plain_mode_defaults_to_at_only(self):
        """群登记了但没写 plain_mode：必须按最保守的 at_only 只当上下文。

        钉住默认值本身：把 DEFAULT_PLAIN_MODE 从 at_only 改成 all 时这条必须挂
        （qq-verifier 的突变测试正是这么发现"默认值没人测"的）。
        """
        self.assertEqual(policy.DEFAULT_PLAIN_MODE, 'at_only')
        decision = run(make_event(text='今天天气不错'), config(groups={'20002': {}}))
        self.assertEqual(decision.action, 'context_only')
        self.assertEqual(decision.reason, 'plain_at_only')

    def test_plain_mode_is_case_insensitive(self):
        """契约 §10：plain_mode 先 strip().lower() 再判合法性，"ALL" 合法。"""
        cfg = config(groups={'20002': {'plain_mode': '  ALL  '}})
        decision = run(make_event(text='闲聊'), cfg)
        self.assertEqual(decision.action, 'reply')
        self.assertEqual(decision.priority, PRIORITY_GROUP_PLAIN)
        self.assertEqual(decision.reason, 'plain_all')

    def test_plain_mode_wrong_type_falls_back_to_at_only(self):
        """契约 §10 S1：plain_mode 类型写错 → 按缺失（at_only），不是 ignore。"""
        decision = run(make_event(text='闲聊'), self.group(123))
        self.assertEqual(decision.action, 'context_only')
        self.assertEqual(decision.reason, 'plain_at_only')
        self.assertEqual(run(make_event(text='看这个', at_me=True),
                             self.group(123)).action, 'reply')

    def test_bad_group_numbers_fall_back_to_defaults(self):
        """followup_window_s / plain_cooldown_s / plain_per_hour 类型写错同理。"""
        cfg = self.group('idle', followup_window_s='一分钟',
                         plain_cooldown_s='两分钟', plain_per_hour='六条')
        decision = run(make_event(text='闲聊'), cfg, depth=0)
        self.assertEqual(decision.action, 'reply')
        self.assertEqual(decision.reason, 'plain_idle')
        # "按缺失处理"= 用默认值（追问窗口 60 秒），行为必须与"这个字段压根没写"一模一样
        broken = self.group('selective', followup_window_s='一分钟')
        absent = self.group('selective')
        for cfg in (broken, absent):
            self.assertEqual(run(make_event(text='为什么呀'), cfg, now=1000.0,
                                 last_reply=990.0).reason, 'followup_question')
            self.assertEqual(run(make_event(text='为什么呀'), cfg, now=1000.0,
                                 last_reply=900.0).action, 'context_only')

    def test_top_level_plain_mode_has_no_effect(self):
        """契约 §10 S2：plain_mode 只在群条目里生效，顶层写了也退回 at_only。"""
        cfg = config(plain_mode='all', groups={'20002': {}})
        decision = run(make_event(text='闲聊'), cfg)
        self.assertEqual(decision.action, 'context_only')
        self.assertEqual(decision.reason, 'plain_at_only')

    def test_plain_per_hour_cap_blocks(self):
        cfg = self.group('all', plain_per_hour=2)
        times = [990.0, 995.0]
        decision = run(make_event(text='闲聊'), cfg, now=1000.0, plain_times=times)
        self.assertEqual(decision.action, 'context_only')
        self.assertEqual(decision.reason, 'plain_hourly_cap')

    def test_plain_per_hour_zero_means_unlimited(self):
        cfg = self.group('all', plain_per_hour=0)
        decision = run(make_event(text='闲聊'), cfg, now=1000.0,
                       plain_times=[990.0] * 50)
        self.assertEqual(decision.action, 'reply')

    def test_old_plain_replies_fall_out_of_the_hour_window(self):
        cfg = self.group('all', plain_per_hour=1)
        decision = run(make_event(text='闲聊'), cfg, now=10000.0,
                       plain_times=[1000.0])          # 两小时前，早出窗口了
        self.assertEqual(decision.action, 'reply')

    def test_plain_times_accepts_a_bare_count(self):
        cfg = self.group('all', plain_per_hour=1)
        self.assertEqual(run(make_event(text='闲聊'), cfg, plain_times=1).action,
                         'context_only')
        self.assertEqual(run(make_event(text='闲聊'), cfg, plain_times=0).action,
                         'reply')

    def test_bad_plain_times_type_is_ignored(self):
        self.assertEqual(run(make_event(text='闲聊'), self.group('all'),
                             plain_times='很多').action, 'ignore')


class RateGateTests(unittest.TestCase):
    def test_gate_blocks_within_min_reply_seconds(self):
        decision = run(make_event(chat_type='private', chat_id='30003'),
                       now=1000.0, last_reply=998.0)
        self.assertEqual(decision.action, 'context_only')
        self.assertEqual(decision.reason, 'min_reply_seconds')

    def test_gate_passes_after_min_reply_seconds(self):
        self.assertEqual(run(make_event(chat_type='private', chat_id='30003'),
                             now=1000.0, last_reply=996.0).action, 'reply')

    def test_gate_also_applies_to_at_me(self):
        decision = run(make_event(at_me=True), now=1000.0, last_reply=999.0)
        self.assertEqual(decision.action, 'context_only')
        self.assertEqual(decision.reason, 'min_reply_seconds')

    def test_no_gate_without_previous_reply(self):
        self.assertEqual(run(make_event(chat_type='private', chat_id='30003'),
                             now=1000.0, last_reply=0).action, 'reply')

    def test_gate_can_be_switched_off(self):
        self.assertEqual(run(make_event(chat_type='private', chat_id='30003'),
                             config(min_reply_seconds=0), now=1000.0,
                             last_reply=999.9).action, 'reply')

    def test_bad_gate_type_is_ignored(self):
        self.assertEqual(run(make_event(chat_type='private', chat_id='30003'),
                             config(min_reply_seconds='快')).action, 'ignore')


if __name__ == '__main__':
    unittest.main(verbosity=2)
