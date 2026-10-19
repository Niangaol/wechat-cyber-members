"""对抗式验证 1：envelope.from_onebot_event（契约 §2）。

只读 qq/**，不改任何实现文件。运行：python3 verify_qq/v1_envelope.py
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'verify_qq'))

from harness import group, check, eq, observe, run, summary   # noqa: E402
from qq.core.envelope import (from_onebot_event, parse_cq_string,   # noqa: E402
                              normalize_segments, batch_payload)

SELF = '10001'
OTHER = '20002'
GID = '30003'


def base(**kw):
    payload = {
        'post_type': 'message',
        'message_type': 'group',
        'self_id': 10001,
        'group_id': 30003,
        'user_id': 20002,
        'message_id': 9001,
        'time': 1700000000,
        'sender': {'user_id': 20002, 'nickname': '某人', 'card': '群名片'},
        'message': [{'type': 'text', 'data': {'text': '你好'}}],
    }
    payload.update(kw)
    return payload


# ---------------------------------------------------------------- string 形态

def t_string_at_me():
    ev = from_onebot_event(base(message='[CQ:at,qq=10001] 在吗'))
    check('string: 解析成功', ev is not None)
    eq('string: at_me', ev.at_me, True)
    eq('string: at_all', ev.at_all, False)
    eq('string: text 不含 CQ 码', ev.text, '在吗')
    check('string: text 里没有 "[CQ:" 残留', '[CQ:' not in ev.text, ev.text)


def t_string_at_all():
    ev = from_onebot_event(base(message='[CQ:at,qq=all] 全体公告'))
    eq('string @全体: at_all', ev.at_all, True)
    eq('string @全体: at_me 必须为 False', ev.at_me, False)
    eq('string @全体: text', ev.text, '全体公告')


def t_string_at_other():
    """别人被 @ —— 绝不能被当成 @我。"""
    ev = from_onebot_event(base(message='[CQ:at,qq=20002] 你来看'))
    eq('string @别人: at_me', ev.at_me, False)
    eq('string @别人: text', ev.text, '你来看')


def t_string_escape():
    ev = from_onebot_event(base(message='&amp; &#91; &#93; &#44; end'))
    eq('escape: &amp;->&', ev.text, '& [ ] , end')
    ev2 = from_onebot_event(base(message='&amp;#91;'))
    eq('escape: &amp;#91; 双重转义保持不变', ev2.text, '&amp;#91;' if False else '&#91;')
    ev3 = from_onebot_event(base(message='&#91;CQ:at,qq=10001&#93;'))
    eq('escape: 转义的 CQ 码不得触发 at_me', ev3.at_me, False)
    eq('escape: 转义的 CQ 码还原成纯文本', ev3.text, '[CQ:at,qq=10001]')


def t_string_at_embedded():
    ev = from_onebot_event(base(message='先说[CQ:at,qq=10001]后说'))
    eq('内嵌 at: text 拼接', ev.text, '先说后说')
    eq('内嵌 at: at_me', ev.at_me, True)


def t_string_image():
    ev = from_onebot_event(
        base(message='[CQ:image,file=a.png,url=https://x.test/a.png]看这图'))
    eq('string image: images', ev.images,
       [{'url': 'https://x.test/a.png', 'file': 'a.png'}])
    eq('string image: text 只留纯文本', ev.text, '看这图')


def t_string_multi_image_and_reply():
    ev = from_onebot_event(base(
        message='[CQ:reply,id=1][CQ:image,file=1.jpg][CQ:image,file=2.jpg]两张'))
    eq('多图: images 数量', len(ev.images), 2)
    eq('多图: reply 段不进 text', ev.text, '两张')


def t_string_no_cq():
    ev = from_onebot_event(base(message='就是普通一句话'))
    eq('普通 string: text', ev.text, '就是普通一句话')
    eq('普通 string: at_me', ev.at_me, False)


def t_string_empty():
    ev = from_onebot_event(base(message=''))
    eq('空 string: text', ev.text, '')
    check('空 string: 事件仍成立（message_id 在）', ev is not None)


def t_string_only_cq():
    ev = from_onebot_event(base(message='[CQ:at,qq=10001]'))
    eq('只有 CQ 段: text 为空', ev.text, '')
    eq('只有 CQ 段: at_me', ev.at_me, True)


def t_string_broken_cq():
    """畸形 CQ 码：不能把整条消息吞掉，也不能抛异常。"""
    for bad in ('[CQ:at,qq=10001', '[CQ:]', '[CQ:at]', '[CQ:at,qq=10001]extra]',
                '[CQ:at,qq=10001,,]'):
        ev = from_onebot_event(base(message=bad))
        check('畸形 CQ %r 不抛异常且事件成立' % bad, ev is not None)


def t_string_cq_uppercase():
    """契约 §10：CQ 参数键必须统一 lower()，[CQ:AT,QQ=10001] 要能认出 at_me。

    段类型与参数键都归一成小写；漏掉键会让真 @ 认不出来（该回的不回）。
    """
    ev = from_onebot_event(base(message='[CQ:AT,QQ=10001]嗨'))
    eq('大写 CQ 段类型归一成小写', ev.segments[0]['type'], 'at')
    eq('大写 CQ: 参数键统一小写（§10）', list(ev.segments[0]['data'].keys()), ['qq'])
    eq('大写 CQ: 参数值原样保留', ev.segments[0]['data']['qq'], '10001')
    eq('大写 [CQ:AT,QQ=<self>] 必须识别成 at_me（§10）', ev.at_me, True)
    eq('大写 CQ 的 text 里不含 CQ 码', ev.text, '嗨')

    for raw, label in (
            ('[CQ:AT,QQ=10001]在吗', '全大写'),
            ('[CQ:At,Qq=10001]在吗', '混合大小写'),
            ('[CQ:at,QQ=10001]在吗', '类型小写键大写'),
            ('[CQ:AT,qQ=10001]在吗', '类型大写键混合')):
        ev2 = from_onebot_event(base(message=raw))
        eq('%s 参数键归一' % label, list(ev2.segments[0]['data'].keys()), ['qq'])
        eq('%s 仍能识别 at_me' % label, ev2.at_me, True)
        eq('%s text 干净' % label, ev2.text, '在吗')

    ev3 = from_onebot_event(base(message='[CQ:AT,QQ=all]公告'))
    eq('大写 CQ + @全体：at_all', ev3.at_all, True)
    eq('大写 CQ + @全体：at_me 仍为 False', ev3.at_me, False)

    ev4 = from_onebot_event(base(
        message='[CQ:IMAGE,File=a.png,URL=https://x.test/a.png]看图'))
    eq('大写 image 段的参数键也归一',
       sorted(ev4.segments[0]['data'].keys()), ['file', 'url'])
    eq('大写 image 段能提取 url', ev4.images,
       [{'url': 'https://x.test/a.png', 'file': 'a.png'}])
    eq('大写 image 段 text 干净', ev4.text, '看图')

    # 边界：段类型前缀 CQ 本身仍区分大小写（§10 只要求"参数键"小写化）
    ev5 = from_onebot_event(base(message='[cq:at,qq=10001]在吗'))
    observe('（观察）小写 [cq:at,...] 整个不当 CQ 码解析（§10 只要求参数键小写化；'
            'OneBot 规范里 CQ 前缀就是大写，保留现状）',
            ev5.at_me is False, 'at_me=%r text=%r' % (ev5.at_me, ev5.text))


# ---------------------------------------------------------------- array 形态

def t_array_basic():
    ev = from_onebot_event(base(message=[
        {'type': 'at', 'data': {'qq': '10001'}},
        {'type': 'text', 'data': {'text': ' 你好'}},
        {'type': 'image', 'data': {'url': 'https://x.test/p.jpg', 'file': 'p.jpg'}},
    ]))
    eq('array: at_me', ev.at_me, True)
    eq('array: text（strip 后）', ev.text, '你好')
    eq('array: images', ev.images, [{'url': 'https://x.test/p.jpg', 'file': 'p.jpg'}])


def t_array_at_all():
    ev = from_onebot_event(base(message=[
        {'type': 'at', 'data': {'qq': 'all'}},
        {'type': 'text', 'data': {'text': '公告'}}]))
    eq('array @全体: at_all', ev.at_all, True)
    eq('array @全体: at_me', ev.at_me, False)


def t_array_qq_int():
    ev = from_onebot_event(base(message=[{'type': 'at', 'data': {'qq': 10001}}]))
    eq('array: qq 是 int 也要认出 at_me', ev.at_me, True)


def t_array_dirty():
    """脏 array：非 dict 项、缺 data、缺 type 一律跳过，不抛异常。"""
    ev = from_onebot_event(base(message=[
        'plain-string-item', 42, {'data': {'text': 'x'}}, {'type': ''},
        {'type': 'text', 'data': 'not-a-dict'},
        {'type': 'text', 'data': {'text': '好'}}]))
    eq('脏 array: text 只取合法段', ev.text, '好')


def t_array_empty():
    ev = from_onebot_event(base(message=[]))
    eq('空 array: text', ev.text, '')
    check('空 array: 事件成立', ev is not None)


def t_dict_message():
    ev = from_onebot_event(base(message={'type': 'text', 'data': {'text': '单个段'}}))
    eq('message 是单个 dict: 也能解析', ev.text, '单个段')


def t_message_missing():
    ev = from_onebot_event(base(message=None))
    eq('message 缺失: text', ev.text, '')
    check('message 缺失: 事件仍成立', ev is not None)


def t_message_bad_type():
    ev = from_onebot_event(base(message=12345))
    eq('message 是数字: text 空', ev.text, '')


# ---------------------------------------------------------------- 丢弃规则

def t_drop_non_message():
    for post in ('notice', 'request', 'meta_event', 'message_sent', '', None, 'MESSAGE'):
        eq('post_type=%r 必须丢弃' % post,
           from_onebot_event(base(post_type=post)), None)


def t_drop_bad_message_type():
    for mt in ('guild', 'discord', '', None, 'GROUP', 'channel'):
        eq('message_type=%r 必须丢弃' % mt,
           from_onebot_event(base(message_type=mt)), None)


def t_drop_self():
    p = base(sender={'user_id': 10001, 'nickname': '我'})
    eq('sender.user_id == self_id 必须丢弃', from_onebot_event(p), None)
    p2 = base(sender={}, user_id=10001)
    eq('sender 缺失时回退 payload.user_id == self_id 必须丢弃',
       from_onebot_event(p2), None)
    p3 = base(sender={'user_id': '10001'})
    eq('self_id/user_id 一个是 int 一个是 str 也要认出是自己',
       from_onebot_event(p3), None)


def t_drop_no_ids():
    eq('self_id 缺失必须丢弃', from_onebot_event(base(self_id=None)), None)
    eq('self_id="" 必须丢弃', from_onebot_event(base(self_id='')), None)
    eq('message_id 缺失必须丢弃', from_onebot_event(base(message_id=None)), None)
    eq('message_id="" 必须丢弃', from_onebot_event(base(message_id='')), None)

    eq('群聊 group_id 缺失必须丢弃', from_onebot_event(base(group_id=None)), None)
    eq('私聊 user_id 缺失必须丢弃',
       from_onebot_event(base(message_type='private', user_id=None,
                              sender={'user_id': None})), None)
    eq('sender.user_id 与 payload.user_id 都缺失必须丢弃',
       from_onebot_event(base(sender={}, user_id=None)), None)
    # 观察项：id 为 0 时 _as_id 得到字符串 '0'（真值），不会被丢弃。
    observe('（观察）self_id=0 未被丢弃（契约只说"拿不到"，0 被当成有效值）',
            from_onebot_event(base(self_id=0)) is not None)
    observe('（观察）message_id=0 未被丢弃；多条 message_id=0 会共用同一 dedupe_key',
            from_onebot_event(base(message_id=0)) is not None)


def t_drop_not_dict():
    for bad in (None, [], 'x', 42):
        eq('payload 不是 dict（%r）必须丢弃' % (bad,),
           from_onebot_event(bad), None)


# ---------------------------------------------------------------- chat_key/dedupe

def t_keys_group():
    ev = from_onebot_event(base())
    eq('群聊 chat_key', ev.chat_key, 'qq:10001:group:30003')
    eq('群聊 dedupe_key', ev.dedupe_key, '10001:group:30003:9001')
    eq('群聊 kind', ev.kind, 'group')


def t_keys_private():
    ev = from_onebot_event(base(message_type='private', group_id=None,
                                user_id=20002, sender={'user_id': 20002}))
    eq('私聊 chat_key', ev.chat_key, 'qq:10001:private:20002')
    eq('私聊 dedupe_key', ev.dedupe_key, '10001:private:20002:9001')
    eq('私聊 chat_id == 对方号', ev.chat_id, '20002')
    eq('私聊 kind', ev.kind, 'private')


def t_keys_int_str_uniform():
    a = from_onebot_event(base(self_id=10001, group_id=30003, message_id=9001))
    b = from_onebot_event(base(self_id='10001', group_id='30003', message_id='9001'))
    eq('int/str 混用得到同一个 chat_key', a.chat_key, b.chat_key)
    eq('int/str 混用得到同一个 dedupe_key', a.dedupe_key, b.dedupe_key)


def t_keys_diff_self_id():
    a = from_onebot_event(base(self_id=10001))
    b = from_onebot_event(base(self_id=10002))
    check('跨 self_id 的 chat_key 必须不同（记忆隔离）', a.chat_key != b.chat_key,
          '%s vs %s' % (a.chat_key, b.chat_key))


def t_sender_name():
    eq('sender_name 优先 card',
       from_onebot_event(base(sender={'user_id': 20002, 'card': 'C', 'nickname': 'N'})).sender_name, 'C')
    eq('card 为空时用 nickname',
       from_onebot_event(base(sender={'user_id': 20002, 'card': '', 'nickname': 'N'})).sender_name, 'N')
    eq('都没有时为空串',
       from_onebot_event(base(sender={'user_id': 20002})).sender_name, '')


def t_time_field():
    eq('time 正常取值', from_onebot_event(base(time=1700000000)).time, 1700000000.0)
    eq('time 是字符串数字也能取', from_onebot_event(base(time='1700000000')).time, 1700000000.0)
    ev = from_onebot_event(base(time='坏值'))
    check('time 是坏值时回退当前时间（不抛异常）', ev.time > 1e9, 'time=%r' % ev.time)


# ---------------------------------------------------------------- 边界：文本伪装

def t_fake_at_in_plain_text():
    """纯文本里的 "@昵称" 不能产生 at_me（只有真 at 段才算）。"""
    for text in ('@10001 在吗', '有人@我', '@年糕 来', 'at 10001'):
        ev = from_onebot_event(base(message=text))
        eq('纯文本 %r 不得产生 at_me' % text, ev.at_me, False)
        eq('纯文本 %r 不得产生 at_all' % text, ev.at_all, False)


def t_at_missing_qq():
    ev = from_onebot_event(base(message=[{'type': 'at', 'data': {}}]))
    eq('at 段缺 qq: at_me', ev.at_me, False)
    ev2 = from_onebot_event(base(message=[{'type': 'at', 'data': {'qq': ''}}]))
    eq('at 段 qq 为空: at_me', ev2.at_me, False)


def t_at_all_variants():
    for val in ('all', 'ALL', 'All'):
        ev = from_onebot_event(base(message=[{'type': 'at', 'data': {'qq': val}}]))
        eq('at qq=%r 是否算 at_all' % val, ev.at_all, val == 'all')


# ---------------------------------------------------------------- batch_payload

def t_batch_payload():
    import json
    ev = from_onebot_event(base(message='[CQ:at,qq=10001] 帮我看看'))

    class D:
        action = 'reply'
        reason = 'at_me'
        priority = 7
    task = json.loads(batch_payload(ev, D()))
    eq('payload: action', task['action'], 'reply')
    eq('payload: chat_key', task['chat_key'], 'qq:10001:group:30003')
    eq('payload: 单条 messages', len(task['messages']), 1)
    msg = task['messages'][0]
    eq('payload: signature == dedupe_key', msg['signature'], ev.dedupe_key)
    eq('payload: direction', msg['direction'], 'in')
    eq('payload: at_me 透传', msg['at_me'], True)
    eq('payload: text', msg['text'], '帮我看看')


def t_batch_payload_kind_image():
    import json
    ev = from_onebot_event(base(
        message=[{'type': 'image', 'data': {'url': 'https://a/b.png', 'file': 'b.png'}}]))
    class D:
        action = 'reply'; reason = 'r'; priority = 1
    task = json.loads(batch_payload(ev, D()))
    eq('payload: 有图时 kind=image', task['messages'][0]['kind'], 'image')


def t_parse_cq_direct():
    segs = parse_cq_string('a[CQ:at,qq=1]b[CQ:face,id=3]c')
    eq('parse_cq_string: 段类型序列', [s['type'] for s in segs], ['text', 'at', 'text', 'face', 'text'])
    eq('parse_cq_string: 文本拼接',
       ''.join(s['data'].get('text', '') for s in segs if s['type'] == 'text'), 'abc')


def t_normalize_direct():
    eq('normalize_segments(str)', [s['type'] for s in normalize_segments('x[CQ:at,qq=1]')],
       ['text', 'at'])
    eq('normalize_segments(None)', normalize_segments(None), [])


group('§2 envelope.from_onebot_event（string CQ）')
for fn in (t_string_at_me, t_string_at_all, t_string_at_other, t_string_escape,
           t_string_at_embedded, t_string_image, t_string_multi_image_and_reply,
           t_string_no_cq, t_string_empty, t_string_only_cq, t_string_broken_cq,
           t_string_cq_uppercase):
    run(fn)

group('§2 array/dict 形态')
for fn in (t_array_basic, t_array_at_all, t_array_qq_int, t_array_dirty,
           t_array_empty, t_dict_message, t_message_missing, t_message_bad_type):
    run(fn)

group('§2 丢弃规则（fail-closed）')
for fn in (t_drop_non_message, t_drop_bad_message_type, t_drop_self,
           t_drop_no_ids, t_drop_not_dict):
    run(fn)

group('§2 chat_key / dedupe_key / kind')
for fn in (t_keys_group, t_keys_private, t_keys_int_str_uniform,
           t_keys_diff_self_id, t_sender_name, t_time_field):
    run(fn)

group('§2 对抗：文本伪装 @ / 边界')
for fn in (t_fake_at_in_plain_text, t_at_missing_qq, t_at_all_variants):
    run(fn)

group('§2 batch_payload / 解析辅助')
for fn in (t_batch_payload, t_batch_payload_kind_image, t_parse_cq_direct,
           t_normalize_direct):
    run(fn)

summary('envelope 验证')
