"""对抗式验证 2：policy.decide（契约 §3）。

重点：fail-closed（配置写错类型不能 fail-open）、真 @ vs 文本假装 @、
followup 窗口、plain_mode 四档、plain_per_hour / plain_cooldown_s、
min_reply_seconds。运行：python3 verify_qq/v2_policy.py
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'verify_qq'))

from harness import group, check, eq, observe, run, summary       # noqa: E402
from qq.core.envelope import QEvent                                # noqa: E402
from qq.core.policy import decide                                  # noqa: E402
from quota import (PRIORITY_DIRECT, PRIORITY_GROUP_AT,             # noqa: E402
                   PRIORITY_GROUP_PLAIN)

SELF = '10001'
GID = '30003'
UID = '20002'
NOW = 1_700_000_000.0
print('优先级常量：DIRECT=%s GROUP_AT=%s GROUP_PLAIN=%s'
      % (PRIORITY_DIRECT, PRIORITY_GROUP_AT, PRIORITY_GROUP_PLAIN))

BASIC = {
    'groups': {GID: {'plain_mode': 'at_only'}},
    'mention_aliases': ['年糕', '年糕Agent'],
    'min_reply_seconds': 3,
    'direct_policy': 'blacklist',
    'direct_blacklist': [],
    'direct_whitelist': [],
}


def ev(chat_type='group', chat_id=GID, text='', at_me=False, at_all=False):
    return QEvent(self_id=SELF, chat_type=chat_type, chat_id=chat_id,
                  sender_id=UID, sender_name='某人', message_id='9001',
                  time=NOW, at_me=at_me, at_all=at_all, text=text,
                  images=[], segments=[], raw={})


def cfg(**over):
    out = {k: (dict(v) if isinstance(v, dict) else list(v) if isinstance(v, list) else v)
           for k, v in BASIC.items()}
    out['groups'] = {k: dict(v) for k, v in BASIC['groups'].items()}
    out.update(over)
    return out


def D(e, c=None, **kw):
    args = dict(now=NOW, queue_depth=0, last_reply_at=0, group_plain_times=None)
    args.update(kw)
    return decide(e, c if c is not None else cfg(), **args)


def show(d):
    return '%s/%s/%s' % (d.action, d.priority, d.reason)


# ---------------------------------------------------------------- 入口/群登记
def t_chat_type_guard():
    eq('chat_type=discord 必须 ignore', D(ev(chat_type='discord')).action, 'ignore')
    eq('chat_type="" 必须 ignore', D(ev(chat_type='')).action, 'ignore')
    eq('chat_type 为 None 必须 ignore', D(ev(chat_type=None)).action, 'ignore')
    check('event=None 必须 ignore', D(None).action == 'ignore', show(D(None)))
    check('cfg 不是 dict 必须 ignore', D(ev(), 'not-a-dict').action == 'ignore',
          show(D(ev(), 'not-a-dict')))


def t_unregistered_group():
    d = D(ev(text='随便说说'), cfg(groups={}))
    eq('空 groups: 未登记群 ignore', d.action, 'ignore')
    eq('空 groups: reason', d.reason, 'group_not_registered')
    d2 = D(ev(text='@年糕 在吗'), cfg(groups={}))
    eq('空 groups: 喊别名也不回（未登记群一律 ignore）', d2.action, 'ignore')
    d3 = D(ev(text='x', at_me=True), cfg(groups={'99999': {}}))
    eq('别的群: 真 @ 也不回', d3.action, 'ignore')
    d4 = D(ev(text='x'), cfg(groups=None))
    eq('groups 缺失 → ignore', d4.action, 'ignore')
    d5 = D(ev(text='x'), cfg(groups=['30003']))
    eq('groups 是 list → ignore（fail-closed）', d5.action, 'ignore')
    d6 = D(ev(text='x'), cfg(groups={GID: 'at_only'}))
    eq('groups[群号] 不是 dict → ignore', d6.action, 'ignore')
    d7 = D(ev(text='x'), cfg(groups={30003: {'plain_mode': 'all'}}))
    eq('群号键写成 int 时按 str 转（decide 侧 str(chat_id) 查找）', d7.action, 'ignore')


def t_int_group_key():
    """契约 §9 要求键是数字字符串；写 int 时 normalize 会转成 str。
    这里单独验证 policy 在拿到 int 键时的行为（不经过 normalize）。"""
    c = cfg()
    c['groups'] = {30003: {'plain_mode': 'all'}}
    d = D(ev(text='普通闲聊'), c)
    observe('（观察）groups 键写成 int 时 policy 找不到该群（ignore）——'
            '但 config.normalize 会把 int 键转成 str，生产路径无此问题',
            d.action == 'ignore', show(d))


# ---------------------------------------------------------------- 真 @ vs 文本
def t_real_at():
    d = D(ev(text='', at_me=True))
    eq('真 @: action', d.action, 'reply')
    eq('真 @: priority', d.priority, PRIORITY_GROUP_AT)
    eq('真 @: reason', d.reason, 'at_me')
    d2 = D(ev(text='帮我看看', at_me=True))
    eq('真 @ 带文本: 仍 reply', d2.action, 'reply')


def t_fake_at_by_text():
    """纯文本假装被 @：at_me=False 且文本不含别名 → 绝不能在 at_only 群回话。"""
    for text in ('@10001 在吗', '@机器人 你好', '[CQ:at,qq=10001]', 'at我一下'):
        d = D(ev(text=text))
        eq('at_only 群，文本 %r 不得 reply' % text, d.action, 'context_only')
        eq('at_only 群，文本 %r 的 reason' % text, d.reason, 'plain_at_only')


def t_alias_is_by_design():
    """契约 §3 明文要求"文本命中 mention_aliases"就回，这是被 @ 之外的独立规则。"""
    d = D(ev(text='年糕在吗'))
    eq('文本命中别名 → reply（契约 §3 明文）', d.action, 'reply')
    eq('文本命中别名 → PRIORITY_GROUP_AT', d.priority, PRIORITY_GROUP_AT)
    eq('文本命中别名 → reason', d.reason, 'mention_alias')
    d2 = D(ev(text='年糕Agent 帮我'))
    eq('别名大小写/子串匹配', d2.action, 'reply')


def t_at_all_not_me():
    """契约：at_all 不算 at_me。@全体 落回 plain_mode。"""
    d = D(ev(text='公告', at_all=True))
    eq('at_only 群: @全体 → context_only（契约未要求 @全体 必回）', d.action, 'context_only')
    d2 = D(ev(text='公告', at_all=True), cfg(groups={GID: {'plain_mode': 'all'}}))
    eq('all 群: @全体 → reply', d2.action, 'reply')


def t_at_group_entry_not_dict_before_at():
    """群配置坏掉时连真 @ 也不回（fail-closed 覆盖 @）。"""
    d = D(ev(text='x', at_me=True), cfg(groups={GID: 'oops'}))
    eq('群配置不是 dict: 真 @ 也 ignore', d.action, 'ignore')


# ---------------------------------------------------------------- 私聊
def t_private_blacklist():
    c = cfg(direct_blacklist=['20002'])
    eq('私聊黑名单命中 → ignore', D(ev('private', UID), c).action, 'ignore')
    eq('私聊黑名单命中 → reason', D(ev('private', UID), c).reason, 'direct_blacklist')
    c2 = cfg(direct_blacklist=['99999'])
    d = D(ev('private', UID), c2)
    eq('私聊黑名单未命中 → reply', d.action, 'reply')
    eq('私聊 → PRIORITY_DIRECT', d.priority, PRIORITY_DIRECT)
    eq('私聊 → reason', d.reason, 'direct')


def t_private_whitelist():
    c = cfg(direct_policy='whitelist', direct_whitelist=['20002'])
    eq('白名单命中 → reply', D(ev('private', UID), c).action, 'reply')
    c2 = cfg(direct_policy='whitelist', direct_whitelist=['99999'])
    eq('白名单未命中 → ignore', D(ev('private', UID), c2).action, 'ignore')
    eq('白名单未命中 → reason', D(ev('private', UID), c2).reason, 'direct_not_whitelisted')
    eq('白名单为空 → 谁都不接', D(ev('private', UID), cfg(direct_policy='whitelist')).action, 'ignore')


def t_private_int_ids():
    c = cfg(direct_policy='whitelist', direct_whitelist=[20002])
    eq('白名单写 int 也能命中（统一成 str 比较）', D(ev('private', UID), c).action, 'reply')
    c2 = cfg(direct_blacklist=[20002])
    eq('黑名单写 int 也能命中', D(ev('private', UID), c2).action, 'ignore')


def t_private_blacklist_dict_form():
    c = cfg(direct_blacklist={UID: {}})
    eq('黑名单写成 {id: {...}} 也能命中（_id_set 取键）',
       D(ev('private', UID), c).action, 'ignore')


def t_private_no_min_reply_gate_direct():
    """私聊也要过 min_reply_seconds 频率闸（契约 §3.4 是统一闸）。"""
    d = D(ev('private', UID), cfg(), last_reply_at=NOW - 1)
    eq('私聊 1 秒前刚回过 → context_only', d.action, 'context_only')
    eq('私聊频率闸 reason', d.reason, 'min_reply_seconds')


# ---------------------------------------------------------------- followup
def t_followup_window():
    d = D(ev(text='这个怎么弄'), last_reply_at=NOW - 30)
    eq('30s 前的回复 + 疑问 → reply', d.action, 'reply')
    eq('followup → PRIORITY_GROUP_AT', d.priority, PRIORITY_GROUP_AT)
    eq('followup → reason', d.reason, 'followup_question')
    d2 = D(ev(text='这个怎么弄'), last_reply_at=NOW - 61)
    eq('61s 前（窗口外）+ 疑问 → 不按 followup', d2.reason != 'followup_question', True)
    eq('窗口外落回 plain_mode', d2.action, 'context_only')
    d3 = D(ev(text='好的'), last_reply_at=NOW - 10)
    eq('窗口内但不是疑问 → 不 followup', d3.action, 'context_only')
    d4 = D(ev(text='这个怎么弄'), last_reply_at=NOW - 30, cfg=None) if False else         decide(ev(text='这个怎么弄'), cfg(groups={GID: {'followup_window_s': 10}}),
               now=NOW, queue_depth=0, last_reply_at=NOW - 30, group_plain_times=None)
    eq('followup_window_s=10 时 30s 前不算窗口内', d4.reason, 'plain_at_only')
    d5 = D(ev(text='在吗？'), last_reply_at=NOW - 5)
    eq('问号触发 followup', d5.reason, 'followup_question')
    d6 = D(ev(text='为什么'), last_reply_at=NOW - 5)
    eq('疑问词触发 followup', d6.reason, 'followup_question')
    d7 = D(ev(text='咋回事'), last_reply_at=NOW - 5)
    eq('"咋"触发 followup', d7.reason, 'followup_question')
    d8 = D(ev(text='x', at_me=True), last_reply_at=NOW - 5)
    eq('真 @ 优先于 followup', d8.reason, 'at_me')
    d9 = D(ev(text='年糕在吗'), last_reply_at=NOW - 5)
    eq('别名优先于 followup（顺序：at→alias→followup）', d9.reason, 'mention_alias')


# ---------------------------------------------------------------- plain_mode 四档
def t_plain_at_only():
    d = D(ev(text='随便说点什么'))
    eq('at_only: 普通消息 context_only', d.action, 'context_only')
    eq('at_only: reason', d.reason, 'plain_at_only')


def t_plain_selective():
    d = D(ev(text='随便说点什么'), cfg(groups={GID: {'plain_mode': 'selective'}}))
    eq('selective: context_only', d.action, 'context_only')
    eq('selective: reason', d.reason, 'plain_selective')


def t_plain_idle():
    c = cfg(groups={GID: {'plain_mode': 'idle', 'plain_cooldown_s': 120}})
    d = D(ev(text='闲聊'), c)
    eq('idle 空闲无冷却 → reply', d.action, 'reply')
    eq('idle → PRIORITY_GROUP_PLAIN', d.priority, PRIORITY_GROUP_PLAIN)
    eq('idle → reason', d.reason, 'plain_idle')
    eq('idle + 队列非空 → context_only',
       D(ev(text='闲聊'), c, queue_depth=1).action, 'context_only')
    eq('idle + 队列非空 → reason', D(ev(text='闲聊'), c, queue_depth=1).reason, 'plain_busy')
    eq('idle + 冷却中 → context_only',
       D(ev(text='闲聊'), c, group_plain_times=[NOW - 30]).action, 'context_only')
    eq('idle + 冷却中 → reason',
       D(ev(text='闲聊'), c, group_plain_times=[NOW - 30]).reason, 'plain_cooldown')
    eq('idle + 冷却已过 → reply',
       D(ev(text='闲聊'), c, group_plain_times=[NOW - 200]).action, 'reply')
    c2 = cfg(groups={GID: {'plain_mode': 'idle', 'plain_cooldown_s': 0}})
    eq('plain_cooldown_s=0 → 无冷却，有历史也回',
       D(ev(text='闲聊'), c2, group_plain_times=[NOW - 1]).action, 'reply')
    eq('idle 队列忙 + 冷却中 → reason 优先报 busy',
       D(ev(text='闲聊'), c, queue_depth=3, group_plain_times=[NOW - 1]).reason, 'plain_busy')


def t_plain_all():
    c = cfg(groups={GID: {'plain_mode': 'all'}})
    d = D(ev(text='闲聊'), c)
    eq('all: reply', d.action, 'reply')
    eq('all: priority', d.priority, PRIORITY_GROUP_PLAIN)
    eq('all: reason', d.reason, 'plain_all')
    eq('all: 队列忙也回', D(ev(text='闲聊'), c, queue_depth=5).action, 'reply')
    eq('all: 无冷却（契约未要求）', D(ev(text='闲聊'), c, group_plain_times=[NOW - 1]).action, 'reply')


def t_plain_unknown_mode_is_conservative():
    eq('plain_mode 没写 → at_only 行为',
       D(ev(text='闲聊'), cfg(groups={GID: {}})).reason, 'plain_at_only')
    # 实现里 mode 先 .strip().lower()，所以大写 IDLE 会被当成 idle 生效。
    c = cfg(groups={GID: {'plain_mode': 'IDLE'}})
    eq('plain_mode 大写 IDLE 被 lower() 成 idle 生效',
       D(ev(text='闲聊'), c).reason, 'plain_idle')
    c2 = cfg(groups={GID: {'plain_mode': 'whatever'}})
    eq('plain_mode 乱七八糟 → at_only（fail-closed）',
       D(ev(text='闲聊'), c2).reason, 'plain_at_only')


def t_plain_per_hour():
    c = cfg(groups={GID: {'plain_mode': 'all', 'plain_per_hour': 2}})
    eq('1 条历史（<2）→ reply',
       D(ev(text='闲聊'), c, group_plain_times=[NOW - 10]).action, 'reply')
    eq('2 条历史（=2）→ context_only',
       D(ev(text='闲聊'), c, group_plain_times=[NOW - 10, NOW - 20]).action, 'context_only')
    eq('到顶 reason', D(ev(text='闲聊'), c, group_plain_times=[NOW - 10, NOW - 20]).reason,
       'plain_hourly_cap')
    eq('1 小时以前的不算',
       D(ev(text='闲聊'), c, group_plain_times=[NOW - 3601, NOW - 4000]).action, 'reply')
    c0 = cfg(groups={GID: {'plain_mode': 'all', 'plain_per_hour': 0}})
    eq('plain_per_hour=0 → 不限',
       D(ev(text='闲聊'), c0, group_plain_times=[NOW - i for i in range(1, 50)]).action, 'reply')
    eq('plain_per_hour 到顶不影响真 @',
       D(ev(text='x', at_me=True), c, group_plain_times=[NOW - 1, NOW - 2]).action, 'reply')
    eq('plain_per_hour 到顶不影响别名',
       D(ev(text='年糕'), c, group_plain_times=[NOW - 1, NOW - 2]).action, 'reply')
    eq('plain_per_hour 到顶不影响 followup',
       D(ev(text='在吗'), c, last_reply_at=NOW - 5,
         group_plain_times=[NOW - 1, NOW - 2]).reason, 'followup_question')


def t_plain_times_numeric_form():
    """_plain_state 兼容"只给条数"的形态；此时冷却无从判断。"""
    c = cfg(groups={GID: {'plain_mode': 'idle', 'plain_cooldown_s': 120}})
    eq('group_plain_times 给数字 5（<默认上限 6）→ reply',
       D(ev(text='闲聊'), c, group_plain_times=5).action, 'reply')
    eq('group_plain_times 给数字 7（>=默认上限 6）→ 被每小时上限拦下',
       D(ev(text='闲聊'), c, group_plain_times=7).action, 'context_only')
    c2 = cfg(groups={GID: {'plain_mode': 'idle', 'plain_per_hour': 3}})
    eq('给数字且到顶 → context_only',
       D(ev(text='闲聊'), c2, group_plain_times=3).action, 'context_only')


def t_min_reply_seconds():
    eq('3s 内 → context_only', D(ev(text='x', at_me=True), last_reply_at=NOW - 2).action,
       'context_only')
    eq('3s 内 reason', D(ev(text='x', at_me=True), last_reply_at=NOW - 2).reason,
       'min_reply_seconds')
    eq('正好 3s → 放行（< 判定）', D(ev(text='x', at_me=True), last_reply_at=NOW - 3).action,
       'reply')
    eq('min_reply_seconds=0 → 不限',
       D(ev(text='x', at_me=True), cfg(min_reply_seconds=0), last_reply_at=NOW - 0.1).action,
       'reply')
    eq('last_reply_at=0（没回过）→ 放行',
       D(ev(text='x', at_me=True), cfg(), last_reply_at=0).action, 'reply')
    eq('频率闸对私聊一样生效',
       D(ev('private', UID), cfg(), last_reply_at=NOW - 1).reason, 'min_reply_seconds')


# ---------------------------------------------------------------- fail-closed 矩阵
# 契约 §10 S1 裁决（2026-10-18 晚）：
#   A) "身份/名单"字段（决定**能不能接**）：类型不对 → fail-closed → ignore
#   B) groups[g] 里 5 个"策略"字段：类型不对 → 按该字段缺失用默认值，**不影响真 @**
IDENTITY_BAD = [
    ('direct_policy 是数字', {'direct_policy': 5}, 'private'),
    ('direct_policy 是不认识的值', {'direct_policy': 'allow-all'}, 'private'),
    ('direct_policy 是 list', {'direct_policy': []}, 'private'),
    ('direct_blacklist 是字符串', {'direct_blacklist': '20002'}, 'private'),
    ('direct_whitelist 是数字',
     {'direct_policy': 'whitelist', 'direct_whitelist': 7}, 'private'),
    # min_reply_seconds 是**全局**频率闸（§3.4 对私聊与群聊统一生效），不是私聊专属
    ('min_reply_seconds 是字符串', {'min_reply_seconds': '3'}, 'global'),
    ('min_reply_seconds 是 bool', {'min_reply_seconds': True}, 'global'),
    ('groups 不是 dict', {'groups': []}, 'group'),
    ('groups[g] 不是 dict（群条目本身坏）', {'groups': {GID: []}}, 'group'),
    ('groups[g] 是字符串', {'groups': {GID: 'at_only'}}, 'group'),
]

# (名字, 群配置覆盖, 普通消息期望 (action, reason), 真 @ 期望 action)
POLICY_BAD = [
    ('groups[g].plain_mode 是数字', {'groups': {GID: {'plain_mode': 5}}},
     ('context_only', 'plain_at_only'), 'reply'),
    ('groups[g].plain_mode 是 list', {'groups': {GID: {'plain_mode': ['all']}}},
     ('context_only', 'plain_at_only'), 'reply'),
    ('groups[g].plain_mode 是不认识的字符串', {'groups': {GID: {'plain_mode': 'whatever'}}},
     ('context_only', 'plain_at_only'), 'reply'),
    ('groups[g].followup_window_s 是字符串',
     {'groups': {GID: {'followup_window_s': '60'}}},
     ('context_only', 'plain_at_only'), 'reply'),
    ('groups[g].followup_window_s 是 bool',
     {'groups': {GID: {'followup_window_s': True}}},
     ('context_only', 'plain_at_only'), 'reply'),
    ('groups[g].plain_cooldown_s 是 bool（idle）',
     {'groups': {GID: {'plain_mode': 'idle', 'plain_cooldown_s': True}}},
     ('reply', 'plain_idle'), 'reply'),
    ('groups[g].plain_cooldown_s 是字符串（idle）',
     {'groups': {GID: {'plain_mode': 'idle', 'plain_cooldown_s': '120'}}},
     ('reply', 'plain_idle'), 'reply'),
    ('groups[g].plain_per_hour 是字符串（all）',
     {'groups': {GID: {'plain_mode': 'all', 'plain_per_hour': '6'}}},
     ('reply', 'plain_all'), 'reply'),
    ('groups[g].plain_per_hour 是 bool（all）',
     {'groups': {GID: {'plain_mode': 'all', 'plain_per_hour': True}}},
     ('reply', 'plain_all'), 'reply'),
    ('mention_aliases 是字符串', {'mention_aliases': '年糕'},
     ('context_only', 'plain_at_only'), 'reply'),
    ('mention_aliases 是数字', {'mention_aliases': 5},
     ('context_only', 'plain_at_only'), 'reply'),
]


def t_identity_fields_fail_closed():
    """§10 S1 的 A 类：决定"能不能接"的字段类型写错 → 一律 ignore（绝不 reply）。

    作用域分三类（拿错事件类型会把"字段本来就不管这个会话"误判成 fail-open）：
      - private：direct_policy / direct_blacklist / direct_whitelist 只管私聊；
      - global ：min_reply_seconds 是 §3.4 的统一频率闸，私聊与群聊都要拦；
      - group  ：groups 本身 / 群条目只管群聊。
    """
    for name, over, kind in IDENTITY_BAD:
        c = cfg(**over)
        if kind == 'private':
            d = D(ev('private', UID), c)
            check('私聊身份字段 fail-closed: %s → ignore' % name,
                  d.action == 'ignore', show(d))
            d2 = D(ev('private', UID, text='帮我看看'), c)
            check('私聊身份字段 fail-closed（带文本）: %s → ignore' % name,
                  d2.action == 'ignore', show(d2))
        elif kind == 'global':
            d = D(ev('private', UID), c)
            check('全局闸 fail-closed（私聊）: %s → ignore' % name,
                  d.action == 'ignore', show(d))
            d2 = D(ev(text='x', at_me=True), c)
            check('全局闸 fail-closed（群 @）: %s → ignore' % name,
                  d2.action == 'ignore', show(d2))
            # 群普通消息在 at_only 群本来就不是 reply，频率闸根本不会被读到，
            # 所以结果是 context_only 而不是 ignore —— 关键是**绝不 reply**。
            d3 = D(ev(text='随便一句话'), c)
            check('全局闸 fail-closed（群普通消息）: %s → 绝不 reply' % name,
                  d3.action != 'reply', show(d3))
        else:
            d = D(ev(text='随便一句话'), c)
            check('群身份字段 fail-closed: %s → ignore' % name,
                  d.action == 'ignore', show(d))
            d2 = D(ev(text='x', at_me=True), c)
            check('群身份字段 fail-closed(@): %s → ignore' % name,
                  d2.action == 'ignore', show(d2))
            d3 = D(ev(text='年糕在吗'), c)
            check('群身份字段 fail-closed（喊别名）: %s → ignore' % name,
                  d3.action == 'ignore', show(d3))


def t_private_only_fields_do_not_govern_groups():
    """反向确认：direct_policy / 私聊名单坏掉**不该**拦群消息（它们只管私聊）。

    这是防"过度拦截"的对照：如果哪天有人把这些字段的校验挪到群路径上，
    所有群消息都会被一个与群无关的坏配置静默掐死。
    """
    for name, over, kind in IDENTITY_BAD:
        if kind != 'private':
            continue
        d = D(ev(text='x', at_me=True), cfg(**over))
        eq('私聊字段坏值不影响群 @：%s' % name, (d.action, d.reason), ('reply', 'at_me'))


def t_policy_fields_fall_back_to_default():
    """§10 S1 的 B 类：5 个策略字段类型写错 = 按字段缺失用默认值。

    两件事同时成立才算对：
      1. **不 fail-open**：该保守的时候仍然保守（没 @ 的普通消息不能因此变成 reply）；
      2. **不影响真 @**：@ 路径本来就不读这些字段，必须照常 reply。
    """
    for name, over, plain_expect, at_expect in POLICY_BAD:
        c = cfg(**over)
        d = D(ev(text='随便一句话'), c)
        eq('策略字段坏值的普通消息：%s' % name, (d.action, d.reason), plain_expect)
        d2 = D(ev(text='x', at_me=True), c)
        eq('策略字段坏值不影响真 @：%s' % name, d2.action, at_expect)
        eq('策略字段坏值不影响真 @ 的 reason：%s' % name, d2.reason, 'at_me')


def t_policy_field_missing_vs_broken_alias():
    """别名写成坏类型时按"没有别名"处理（不给全局兜底）。

    §10 说"按该字段缺失处理"。字面上"缺失"会退回全局 mention_aliases，
    实现选择直接返回空列表 —— 更保守（少接话）。这里钉住实际行为并报给 lead。
    """
    c = cfg(mention_aliases=['年糕'])
    c['groups'] = {GID: {'mention_aliases': 123}}
    d = D(ev(text='年糕在吗'), c)
    eq('群条目别名坏类型 → 不当成命中别名（不 reply）', d.action, 'context_only')
    observe('（口径·低）§10 说"按字段缺失处理"：字面缺失会退回全局 mention_aliases，'
            '实现直接返回空列表（更保守）。当前行为已钉住，请 lead 确认口径',
            d.reason == 'plain_at_only', show(d))
    d2 = D(ev(text='年糕在吗'), cfg())
    eq('对照：别名正常时命中', d2.reason, 'mention_alias')


def t_bad_input_types():
    c = cfg()
    eq('now 是字符串 → ignore', decide(ev(), c, now='坏', queue_depth=0,
                                       last_reply_at=0, group_plain_times=None).action, 'ignore')
    d = decide(ev(), cfg(groups={GID: {'plain_mode': 'idle'}}), now=NOW,
               queue_depth='坏', last_reply_at=0, group_plain_times=None)
    eq('queue_depth 是字符串（idle 模式）→ ignore', d.action, 'ignore')
    d2 = decide(ev(text='在吗'), c, now=NOW, queue_depth=0,
                last_reply_at='坏', group_plain_times=None)
    eq('last_reply_at 是字符串 → ignore', d2.action, 'ignore')
    d3 = decide(ev(text='x'), c, now=NOW, queue_depth=0, last_reply_at=0,
                group_plain_times='坏')
    eq('group_plain_times 是字符串 → ignore', d3.action, 'ignore')
    d4 = decide(ev(text='x'), c, now=NOW, queue_depth=0, last_reply_at=0,
                group_plain_times=[True, 'x', None, NOW - 5])
    eq('group_plain_times 里混脏值 → 只数合法时间戳', d4.action, 'context_only')


def t_optional_params_missing():
    """契约签名是关键字必填；调用方传 None 时的行为也要可预期。"""
    d = decide(ev(text='x'), cfg(), now=NOW, queue_depth=None,
               last_reply_at=None, group_plain_times=None)
    eq('queue_depth=None 视为 0', d.action, 'context_only')
    d2 = decide(ev(text='x', at_me=True), cfg(), now=NOW, queue_depth=None,
                last_reply_at=None, group_plain_times=None)
    eq('last_reply_at=None 视为没回过', d2.action, 'reply')


# ---------------------------------------------------------------- 配置优先级
def t_group_overrides_global():
    c = cfg(plain_mode='all', groups={GID: {'plain_mode': 'at_only'}})
    eq('群配置优先于全局', D(ev(text='闲聊'), c).reason, 'plain_at_only')
    # plain_mode 只从"该群"读（契约 §9 里 plain_mode 本来就只存在于 groups.<id> 内），
    # 与 followup_window_s / plain_cooldown_s / plain_per_hour 的"群→全局"回退不一致。
    c2 = cfg(plain_mode='all', groups={GID: {}})
    eq('顶层 plain_mode 不生效（回退成默认 at_only）',
       D(ev(text='闲聊'), c2).reason, 'plain_at_only')
    observe('（观察）_pick 的"群→全局回退"只覆盖 followup_window_s/plain_cooldown_s/'
            'plain_per_hour/mention_aliases，plain_mode 不回退（方向更保守，无安全影响）',
            True)
    c2b = cfg(followup_window_s=9999, groups={GID: {}})
    eq('顶层 followup_window_s 会回退生效',
       D(ev(text='在吗'), c2b, last_reply_at=NOW - 500).reason, 'followup_question')
    c3 = cfg(groups={GID: {'plain_mode': None}})
    eq('群写了 None 时退回全局/默认', D(ev(text='闲聊'), c3).reason, 'plain_at_only')


def t_aliases_group_override():
    c = cfg(mention_aliases=['年糕'], groups={GID: {'mention_aliases': ['小助手']}})
    eq('群别名生效', D(ev(text='小助手帮我'), c).reason, 'mention_alias')
    eq('群别名覆盖全局（全局别名失效）', D(ev(text='年糕帮我'), c).reason, 'plain_at_only')


group('§3 入口与群登记（fail-closed）')
for fn in (t_chat_type_guard, t_unregistered_group, t_int_group_key):
    run(fn)

group('§3 真 @ vs 文本假装 @ / @全体')
for fn in (t_real_at, t_fake_at_by_text, t_alias_is_by_design, t_at_all_not_me,
           t_at_group_entry_not_dict_before_at):
    run(fn)

group('§3 私聊 blacklist / whitelist')
for fn in (t_private_blacklist, t_private_whitelist, t_private_int_ids,
           t_private_blacklist_dict_form, t_private_no_min_reply_gate_direct):
    run(fn)

group('§3 followup 追问窗口')
for fn in (t_followup_window,):
    run(fn)

group('§3 plain_mode 四档 + plain_per_hour / plain_cooldown_s')
for fn in (t_plain_at_only, t_plain_selective, t_plain_idle, t_plain_all,
           t_plain_unknown_mode_is_conservative, t_plain_per_hour,
           t_plain_times_numeric_form):
    run(fn)

group('§3 min_reply_seconds 频率闸')
for fn in (t_min_reply_seconds,):
    run(fn)

group('§10 S1-A 身份/名单字段：类型写错必须 fail-closed → ignore')
for fn in (t_identity_fields_fail_closed,
           t_private_only_fields_do_not_govern_groups):
    run(fn)

group('§10 S1-B 策略字段：类型写错按默认值，不 fail-open、不影响真 @')
for fn in (t_policy_fields_fall_back_to_default, t_policy_field_missing_vs_broken_alias):
    run(fn)

group('§3 输入类型与缺参兜底')
for fn in (t_bad_input_types, t_optional_params_missing):
    run(fn)

def t_normalize_warn_vs_policy():
    """config.normalize 对未知 plain_mode 的 warn 文案 与 policy 的实际行为是否一致？"""
    from qq.core.config import normalize
    warns = []
    cfg_in = {'groups': {GID: {'plain_mode': 'ALL'}}}
    out = normalize(cfg_in, env={}, warn=warns.append)
    kept = out['groups'][GID]['plain_mode']
    d = D(ev(text='闲聊'), cfg_in)
    print('    normalize 原样保留的 plain_mode = %r' % kept)
    print('    normalize 的告警 = %s' % (warns or '(无)'))
    print('    policy 实际判定 = %s' % show(d))
    observe('（缺陷·低/中）normalize 告警说"按最保守的 at_only 处理"，'
            '但 policy 会 .lower() 把 ALL 当成 all 生效（方向更宽松）',
            kept == 'ALL' and d.reason == 'plain_all')


group('§3 配置优先级（群 > 全局）')
for fn in (t_group_overrides_global, t_aliases_group_override, t_normalize_warn_vs_policy):
    run(fn)

summary('policy 验证')
