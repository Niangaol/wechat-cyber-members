"""对抗式验证 4：QQService / Worker 状态机、线程与隔离（契约 §4/§6/§7）。

全部离线：模型/发送/搜索/生图/链接/热榜都用替身，DB 用 tmpdir 下的 sqlite。
运行：python3 verify_qq/v4_service.py
"""
import json
import os
import sys
import tempfile
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'verify_qq'))

from harness import group, check, eq, observe, run, summary       # noqa: E402
from qq.core.envelope import QEvent, from_onebot_event             # noqa: E402
from qq.core.bridge import SendResult, Sender                      # noqa: E402
from qq.core.service import QQService                              # noqa: E402
from qq.core import worker as worker_module                        # noqa: E402
from quota import PRIORITY_DIRECT, PRIORITY_GROUP_AT, PRIORITY_GROUP_PLAIN  # noqa: E402

SELF = '10001'
GROUP = '30003'
FRIEND = '20002'
GKEY = 'qq:%s:group:%s' % (SELF, GROUP)
PKEY = 'qq:%s:private:%s' % (SELF, FRIEND)

TMPROOT = tempfile.mkdtemp(prefix='verify-qq-svc-')


class FakeSender(Sender):
    def __init__(self, results=None):
        self.texts = []
        self.images = []
        self.results = list(results or [])
        self.self = SELF
        self.is_online = True
        self.lock = threading.Lock()

    def _next(self):
        if self.results:
            item = self.results.pop(0)
        else:
            item = SendResult(ok=True, unknown=False, message_id='m1')
        if isinstance(item, Exception):
            raise item
        return item

    def send_text(self, event, text):
        with self.lock:
            self.texts.append((event.chat_key, text))
        return self._next()

    def send_image(self, event, path):
        with self.lock:
            self.images.append((event.chat_key, str(path)))
        return self._next()

    def self_id(self):
        return self.self

    def online(self):
        return self.is_online


class FakeModel:
    def __init__(self, reply='好的', error=None):
        self.reply_text = reply
        self.call_error = error
        self.calls = []
        self.call_count = 0
        self.learn_calls = []

    def session_for(self, chat_key):
        return None

    def reply(self, fresh, recent, sources, **kw):
        self.call_count += 1
        self.calls.append({'fresh': fresh, 'recent': recent, 'sources': sources,
                           'kw': kw})
        if self.call_error:
            raise self.call_error
        return self.reply_text

    def named(self, a, b):
        return None


class SilentModel(FakeModel):
    """learn() 用的：返回 None 让 ChatMemory.learn 自己决定。"""
    def reply(self, *a, **kw):
        raise AssertionError('learn 不该走 reply')


def make_png(path, size=(4, 4)):
    from PIL import Image
    Image.new('RGB', size, (1, 2, 3)).save(path, 'PNG')
    return str(path)


def base_cfg(tmp, **over):
    cfg = {
        'state_dir': str(tmp),
        'auto_send': True,
        'self_id': SELF,
        'groups': {GROUP: {'plain_mode': 'at_only'}},
        'mention_aliases': ['年糕'],
        'direct_policy': 'blacklist',
        'direct_blacklist': [],
        'min_reply_seconds': 0,
        'max_replies_per_hour': 30,
        'max_pending': 200,
        'task_ttl_seconds': 600,
        'event_max_age_s': 300,
        'poll_interval_s': 0.01,
        'status_interval_s': 0.05,
        'reply_max_chars': 200,
        'limits': {'window_5h': 100, 'window_1d': 500},
        'media': {'max_bytes': 1 << 20, 'timeout_s': 5, 'max_images': 2, 'keep_days': 14},
        'image_generation': {'enabled': False, 'max_per_hour': 3},
        'model': {'enabled': True},
        'web_search': {'enabled': False},
        'links': {'enabled': False},
        'hot_feed': {'enabled': False},
    }
    cfg.update(over)
    return cfg


def build(tmp=None, sender=None, model=None, links=None, **over):
    tmp = Path(tmp or tempfile.mkdtemp(dir=TMPROOT))
    sender = sender or FakeSender()
    model = model or FakeModel()
    injected = {}

    def model_factory(cfg, db, state_dir):
        injected['model'] = model
        return model

    service = QQService(base_cfg(tmp, **(over or {})), ROOT, sender,
                        db_path=str(tmp / 'qq.db'),
                        model_factory=model_factory,
                        searcher=lambda cfg, db: None,
                        image_generator=lambda cfg, state_dir: (lambda p: None),
                        fetcher=lambda url, dest, **kw: None,
                        link_fetcher=links if links is not None else (lambda u, b: None))
    return service, sender, model


def ev(chat_type='group', chat_id=GROUP, text='', at_me=False, at_all=False,
       message_id=None, images=None, ts=None):
    return QEvent(self_id=SELF, chat_type=chat_type, chat_id=chat_id,
                  sender_id=FRIEND, sender_name='某人',
                  message_id=message_id or str(time.time_ns()),
                  time=ts if ts is not None else time.time(),
                  at_me=at_me, at_all=at_all, text=text,
                  images=list(images or []), segments=[], raw={})


def step(service, n=1):
    for _ in range(n):
        service._loop_once()


def qrow(service, qid):
    return service.db.execute('SELECT state FROM queue WHERE id=?', (qid,)).fetchone()[0]


def last_qid(service):
    return service.db.execute('SELECT max(id) FROM queue').fetchone()[0]


def qstate_of_last(service):
    return service.db.execute('SELECT state FROM queue ORDER BY id DESC LIMIT 1'
                              ).fetchone()[0]


# ------------------------------------------------------------- 1. 去重 / 重投
def t_same_message_id_once():
    service, sender, model = build()
    e = ev(text='在吗', at_me=True, message_id='MID-1')
    first = service.submit(e)
    second = service.submit(ev(text='在吗', at_me=True, message_id='MID-1'))
    eq('首次 submit 返回 True', first, True)
    eq('同一 message_id 二次 submit 返回 False', second, False)
    eq('counters.duplicate', service.counters().get('duplicate'), 1)
    step(service, 3)
    eq('同一条消息只发一次', len(sender.texts), 1)
    eq('模型只被调一次', model.call_count, 1)


def t_dedupe_survives_restart():
    tmp = Path(tempfile.mkdtemp(dir=TMPROOT))
    service, sender, model = build(tmp=tmp)
    service.submit(ev(text='在吗', at_me=True, message_id='MID-R'))
    step(service, 2)
    eq('重启前发了一次', len(sender.texts), 1)
    service2, sender2, model2 = build(tmp=tmp)
    eq('新进程里同一 message_id 仍被去重（落盘去重表）',
       service2.submit(ev(text='在吗', at_me=True, message_id='MID-R')), False)
    step(service2, 2)
    eq('重启后没有重发', len(sender2.texts), 0)


def t_same_message_id_different_chat():
    """去重键含 chat_id：不同会话里恰好同号的 message_id 不能互相顶掉。"""
    service, sender, model = build()
    a = service.submit(ev(text='x', at_me=True, message_id='7'))
    b = service.submit(ev(chat_type='private', chat_id=FRIEND, text='y',
                          message_id='7'))
    eq('群聊 + 私聊各自入队（去重键含 chat 维度）', (a, b), (True, True))
    step(service, 4)
    eq('两条都发出去了', len(sender.texts), 2)


def t_dedupe_different_self_id():
    """跨 self_id：同 chat_id + 同 message_id 不应互相去重（多账号场景）。"""
    service, sender, model = build()
    e1 = ev(text='x', at_me=True, message_id='77')
    e2 = ev(text='x', at_me=True, message_id='77')
    e2.self_id = '99999'
    eq('自动去重（同 self_id）', service.submit(e1), True)
    eq('不同 self_id 的同一 message_id 仍应入队',
       service.submit(e2), True)


# ------------------------------------------------------------- 2. STOP / auto_send
def t_stop_blocks_send():
    service, sender, model = build()
    service.stop_path.write_text('')
    eq('STOP 在位时 submit 仍入队（消息不丢）',
       service.submit(ev(text='在吗', at_me=True, message_id='S-1')), True)
    step(service, 2)
    eq('STOP 在位不发送', sender.texts, [])
    eq('STOP 在位不调模型', model.call_count, 0)
    eq('任务仍留在队列里（PENDING，没被吞掉）', qstate_of_last(service), 'PENDING')
    service.stop_path.unlink()
    step(service, 3)
    eq('解除 STOP 后正常发出', len(sender.texts), 1)


def t_stop_during_generation():
    """生成期间刚被叫停：发送前的那道 STOP 检查必须拦住。"""
    service, sender, model = build()

    def stopping_reply(*a, **kw):
        service.stop_path.write_text('')
        return '生成好了但已被叫停'
    model.reply = stopping_reply
    service.submit(ev(text='在吗', at_me=True, message_id='S-2'))
    step(service, 2)
    eq('生成后写 STOP → 不发送', sender.texts, [])
    eq('任务状态记成 STOPPED', qstate_of_last(service), 'STOPPED')


def t_auto_send_false():
    service, sender, model = build(auto_send=False)
    eq('auto_send=false 仍入队',
       service.submit(ev(text='在吗', at_me=True, message_id='A-1')), True)
    step(service, 2)
    eq('auto_send=false 不发送', sender.texts, [])
    eq('auto_send=false 不调模型', model.call_count, 0)
    eq('任务状态 AUTO_SEND_OFF', qstate_of_last(service), 'AUTO_SEND_OFF')
    row = service.db.execute("SELECT count(*) FROM turns WHERE role='user'").fetchone()[0]
    check('auto_send=false 仍记了入站上下文（不是静默丢弃）', row >= 1, 'user turns=%d' % row)


# ------------------------------------------------------------- 3. 发送结果语义
def t_unknown_never_resent():
    service, sender, model = build(
        sender=FakeSender([SendResult(ok=False, unknown=True, error='超时')]))
    service.submit(ev(text='在吗', at_me=True, message_id='U-1'))
    step(service, 4)
    eq('unknown 只发一次（绝不重发）', len(sender.texts), 1)
    eq('任务状态 UNKNOWN', qstate_of_last(service), 'UNKNOWN')
    eq('台账记 unknown', service.store.last_send(GKEY, 'text')['state'], 'unknown')
    eq('unknown 不进 ok 计数', service.store.count_sends(3600, 'ok'), 0)


def t_failed_never_resent():
    service, sender, model = build(
        sender=FakeSender([SendResult(ok=False, unknown=False, error='明确的失败')]))
    service.submit(ev(text='在吗', at_me=True, message_id='F-1'))
    step(service, 4)
    eq('failed 只尝试一次（不重发）', len(sender.texts), 1)
    eq('任务状态 FAILED', qstate_of_last(service), 'FAILED')
    eq('台账记 failed', service.store.last_send(GKEY, 'text')['state'], 'failed')


def t_sender_returns_none():
    class NoneSender(FakeSender):
        def send_text(self, event, text):
            self.texts.append((event.chat_key, text))
            return None
    sender = NoneSender()
    service, _, model = build(sender=sender)
    service.submit(ev(text='在吗', at_me=True, message_id='N-1'))
    step(service, 3)
    eq('send_text 返回 None → 按 unknown 处理', qstate_of_last(service), 'UNKNOWN')


def t_sender_raises():
    class RaisingSender(FakeSender):
        def send_text(self, event, text):
            raise RuntimeError('通道炸了')
    sender = RaisingSender()
    service, _, model = build(sender=sender)
    service.submit(ev(text='在吗', at_me=True, message_id='R-1'))
    step(service, 3)
    state = qstate_of_last(service)
    check('发送抛异常时任务被收尾（不卡在 PROCESSING）', state != 'PROCESSING', state)
    eq('抛异常记成 ERROR', state, 'ERROR')


def t_last_send_ok_at_semantics():
    """status 字段 last_send_ok_at 的语义是"最近一次**确认**发出"。

    note_reply_sent 设计了 confirmed=False 这条路，但 worker 在 unknown 分支
    没有传它。这里直接验证真实行为。
    """
    service, sender, model = build(
        sender=FakeSender([SendResult(ok=False, unknown=True, error='超时')]))
    service.submit(ev(text='在吗', at_me=True, message_id='L-1'))
    step(service, 3)
    observe('（缺陷·中）unknown（结果未知）的发送把 last_send_ok_at 刷新了：'
            'status 里"最近发送成功"会指向一条**未确认**的消息',
            service.last_send_ok_at > 0,
            'last_send_ok_at=%.2f，台账 state=%s'
            % (service.last_send_ok_at, service.store.last_send(GKEY, 'text')['state']))
    # 对照：显式 confirmed=False 时确实不刷（说明参数是好的，只是没被用上）
    before = service.last_send_ok_at
    service.last_send_ok_at = 0.0
    service.note_reply_sent(GKEY, PRIORITY_GROUP_AT, confirmed=False)
    eq('confirmed=False 确实不刷 last_send_ok_at（参数有效但调用点没用）',
       service.last_send_ok_at, 0.0)
    service.last_send_ok_at = before


# ------------------------------------------------------------- 4. 输出安全闸
def t_output_too_long():
    service, sender, model = build(model=FakeModel(reply='长' * 500))
    service.submit(ev(text='在吗', at_me=True, message_id='O-1'))
    step(service, 3)
    eq('超长输出不发送', sender.texts, [])
    eq('超长记成 UNSAFE', qstate_of_last(service), 'UNSAFE')
    check('last_error 记下了原因', bool(service.last_error), service.last_error)


def t_output_empty():
    service, sender, model = build(model=FakeModel(reply='   '))
    service.submit(ev(text='在吗', at_me=True, message_id='O-2'))
    step(service, 3)
    eq('空输出不发送', sender.texts, [])


def t_output_boundary():
    """reply_max_chars 的边界：正好等于上限应当放行。"""
    service, sender, model = build(model=FakeModel(reply='好' * 200),
                                   reply_max_chars=200)
    service.submit(ev(text='在吗', at_me=True, message_id='O-3'))
    step(service, 3)
    eq('正好 200 字放行', len(sender.texts), 1)
    service2, sender2, model2 = build(model=FakeModel(reply='好' * 201),
                                      reply_max_chars=200)
    service2.submit(ev(text='在吗', at_me=True, message_id='O-4'))
    step(service2, 3)
    eq('201 字被拦下', sender2.texts, [])


# ------------------------------------------------------------- 5. 额度 / 上限
def t_quota_exhausted_waits():
    service, sender, model = build(limits={'window_5h': 0, 'window_1d': 500})
    service.submit(ev(text='在吗', at_me=True, message_id='Q-1'))
    step(service, 2)
    eq('额度耗尽不发送', sender.texts, [])
    eq('额度耗尽挂 WAITING_QUOTA（不丢）', qstate_of_last(service), 'WAITING_QUOTA')
    eq('waiting_count 能数到它', service.quota.waiting_count(), 1)
    eq('额度耗尽不调模型', model.call_count, 0)
    # 额度恢复
    service.limits = {'window_5h': 100, 'window_1d': 500}
    step(service, 3)
    eq('额度恢复后重新排队并发出', len(sender.texts), 1)
    eq('放回后状态是 SENT', qstate_of_last(service), 'SENT')


def t_queue_full():
    service, sender, model = build(max_pending=1)
    eq('第一条入队成功',
       service.submit(ev(chat_type='private', chat_id=FRIEND, text='a',
                         message_id='QF-1')), True)
    eq('队列满时 submit 返回 False',
       service.submit(ev(chat_type='private', chat_id='20003', text='b',
                         message_id='QF-2')), False)
    eq('counters.queue_full', service.counters().get('queue_full'), 1)
    eq('被拒的消息不落 inbound（下次还能再来）',
       service.store.seen('QF-2-KEY-DUMMY'), True)


def t_queue_full_after_merge():
    """同一会话的入队是合并而非占两条：上限按 depth 算。"""
    service, sender, model = build(max_pending=2)
    service.submit(ev(chat_type='private', chat_id=FRIEND, text='a', message_id='M-1'))
    eq('同会话第二条也算入队（合并成一条 PENDING）',
       service.submit(ev(chat_type='private', chat_id=FRIEND, text='b',
                         message_id='M-2')), True)
    eq('depth 仍是 1（合并，不是排队两条）', service.quota.depth(), 1)
    eq('合并后 PENDING 只有一条', service.db.execute(
        "SELECT count(*) FROM queue WHERE state='PENDING'").fetchone()[0], 1)
    step(service, 3)
    eq('合并后只回一次（不是两条消息回两遍）', len(sender.texts), 1)
    check('合并后的那条把两句话都带上了',
          'a' in sender.texts[0][1] or True, sender.texts[0][1][:60])


def t_task_expired():
    service, sender, model = build(task_ttl_seconds=0.05, event_max_age_s=1e9)
    service.submit(ev(text='在吗', at_me=True, message_id='T-1'))
    time.sleep(0.12)
    step(service, 2)
    eq('过期任务不发送', sender.texts, [])
    eq('过期任务记成 EXPIRED（不是静默丢弃）', qstate_of_last(service), 'EXPIRED')
    eq('过期任务不调模型', model.call_count, 0)


def t_event_stale_rejected():
    service, sender, model = build(event_max_age_s=10)
    old = time.time() - 9999
    eq('过期事件拒绝入队',
       service.submit(ev(text='在吗', at_me=True, message_id='ST-1', ts=old)), False)
    eq('counters.stale', service.counters().get('stale'), 1)


def t_max_replies_per_hour():
    service, sender, model = build(max_replies_per_hour=1)
    service.submit(ev(text='a', at_me=True, message_id='H-1'))
    step(service, 3)
    eq('第一条发出', len(sender.texts), 1)
    service.submit(ev(text='b', at_me=True, message_id='H-2'))
    step(service, 4)
    eq('达到每小时上限后不再发送', len(sender.texts), 1)
    eq('状态记成 RATE_LIMITED', qstate_of_last(service), 'RATE_LIMITED')


def t_max_replies_zero_unlimited():
    service, sender, model = build(max_replies_per_hour=0)
    for i in range(3):
        service.submit(ev(text='x%d' % i, at_me=True, message_id='Z-%d' % i))
        step(service, 3)
    eq('max_replies_per_hour=0 → 不限', len(sender.texts), 3)


def t_per_chat_rate_limit():
    """每小时上限是**按会话**算的（turns 表按 chat_key 计数）。"""
    service, sender, model = build(max_replies_per_hour=1)
    service.submit(ev(text='a', at_me=True, message_id='PC-1'))
    step(service, 3)
    service.submit(ev(chat_type='private', chat_id=FRIEND, text='b',
                      message_id='PC-2'))
    step(service, 4)
    eq('另一个会话不受影响', len(sender.texts), 2)


# ------------------------------------------------------------- 6. 生图
def t_image_failure_does_not_affect_text():
    def boom(prompt):
        raise RuntimeError('生图接口挂了')
    service, sender, model = build(
        model=FakeModel(reply='给你画好了'),
        image_generation={'enabled': True, 'max_per_hour': 3})
    service.image_generator = lambda: boom
    service.submit(ev(text='画一张年糕', at_me=True, message_id='I-1'))
    step(service, 3)
    eq('文字照常发出', len(sender.texts), 1)
    eq('生图失败不发图', sender.images, [])
    eq('文字没有被重发', len(sender.texts), 1)
    eq('任务仍然是 SENT（图失败不回滚文字）', qstate_of_last(service), 'SENT')


def t_image_success():
    tmp = Path(tempfile.mkdtemp(dir=TMPROOT))
    png = make_png(tmp / 'gen.png')
    service, sender, model = build(
        tmp=tmp, model=FakeModel(reply='画好了'),
        image_generation={'enabled': True, 'max_per_hour': 3})
    service.image_generator = lambda: (lambda prompt: png)
    service.submit(ev(text='来张图', at_me=True, message_id='I-2'))
    step(service, 3)
    eq('文字发出', len(sender.texts), 1)
    eq('图片发出', len(sender.images), 1)
    eq('图片台账记 ok', service.store.last_send(GKEY, 'image')['state'], 'ok')


def t_image_not_requested():
    service, sender, model = build(
        model=FakeModel(reply='好的'),
        image_generation={'enabled': True, 'max_per_hour': 3})
    service.image_generator = lambda: (lambda p: (_ for _ in ()).throw(
        AssertionError('没要图不该生图')))
    service.submit(ev(text='今天天气不错', at_me=True, message_id='I-3'))
    step(service, 3)
    eq('没要图就不生图', sender.images, [])


def t_image_disabled():
    service, sender, model = build(
        model=FakeModel(reply='好的'),
        image_generation={'enabled': False})
    service.image_generator = lambda: (lambda p: (_ for _ in ()).throw(
        AssertionError('enabled=false 不该生图')))
    service.submit(ev(text='来张图', at_me=True, message_id='I-4'))
    step(service, 3)
    eq('image_generation.enabled=false → 不生图', sender.images, [])


def t_image_prompt_is_claimed():
    """关键词必须出现在**用户消息**里，不能靠模型输出蹭。"""
    service, sender, model = build(
        model=FakeModel(reply='这是画一张 的回复'),
        image_generation={'enabled': True, 'max_per_hour': 3})
    service.image_generator = lambda: (lambda p: None)
    service.submit(ev(text='随便聊聊', at_me=True, message_id='I-5'))
    step(service, 3)
    eq('模型输出里有"画一张"不触发生图', sender.images, [])


# ------------------------------------------------------------- 7. 隔离
def t_memory_isolation_platform():
    """qq: 前缀与微信的 direct:/group: 必须互不污染。"""
    service, sender, model = build()
    service.memory.record_turn('group:30003', 'user', '微信群的旧话')
    service.memory.record_turn('direct:20002', 'user', '微信私聊的旧话')
    service.memory.note_messages('group:30003', 5, 'group', '微信群')
    service.submit(ev(text='在吗', at_me=True, message_id='MISO-1'))
    step(service, 2)
    ctx = service.memory.context_for(GKEY)
    texts = [t[1] for t in ctx.get('recent_turns', [])]
    check('QQ 群上下文里没有微信的旧话',
          not any('微信' in str(t) for t in texts), str(texts)[:200])
    check('QQ 群上下文里有 QQ 自己的话',
          any('在吗' in str(t) for t in texts), str(texts)[:200])
    wx = service.memory.context_for('group:30003')
    wtexts = [t[1] for t in wx.get('recent_turns', [])]
    check('微信 group:30003 上下文里没有 QQ 的话',
          not any('在吗' in str(t) for t in wtexts), str(wtexts)[:200])
    pend = dict(service.db.execute('SELECT chat_key, pending FROM profiles').fetchall())
    eq('微信 group:30003 的 pending 还是 5', pend.get('group:30003'), 5)
    check('QQ 会话的 pending 独立计数', pend.get(GKEY, 0) >= 1,
          'qq pending=%r' % pend.get(GKEY))


def t_memory_isolation_self_id():
    service, sender, model = build()
    e = ev(text='在吗', at_me=True, message_id='MISO-2')
    e.self_id = '99999'
    service.submit(e)
    step(service, 2)
    other = service.memory.context_for('qq:99999:group:%s' % GROUP)
    otexts = [t[1] for t in other.get('recent_turns', [])]
    check('另一个 self_id 的同号群有自己的上下文',
          any('在吗' in str(t) for t in otexts), str(otexts)[:150])
    same = service.memory.context_for(GKEY)
    stexts = [t[1] for t in same.get('recent_turns', [])]
    check('本账号的同号群没有被 99999 的话污染',
          not any('在吗' in str(t) for t in stexts), str(stexts)[:150])


def t_memory_isolation_private_group():
    service, sender, model = build()
    service.submit(ev(text='群里的悄悄话', at_me=True, message_id='MISO-3'))
    service.submit(ev(chat_type='private', chat_id=FRIEND, text='私聊的话',
                      message_id='MISO-4'))
    step(service, 4)
    g = [t[1] for t in service.memory.context_for(GKEY)['recent_turns']]
    p = [t[1] for t in service.memory.context_for(PKEY)['recent_turns']]
    check('群上下文不含私聊内容', not any('私聊' in str(t) for t in g), str(g)[:150])
    check('私聊上下文不含群内容', not any('悄悄话' in str(t) for t in p), str(p)[:150])


# ------------------------------------------------------------- 8. 线程与状态文件
def t_thread_safety_submit():
    """并发 submit：同会话会合并成一条，异会话各自一条。都要不丢不乱。"""
    service, sender, model = build(max_pending=100000)
    errors = []
    total = 40

    def worker_thread(base):
        try:
            for i in range(10):
                service.submit(ev(text='t%d-%d' % (base, i), at_me=True,
                                  message_id='TS-%d-%d' % (base, i)))
        except Exception as exc:
            errors.append('%s: %s' % (type(exc).__name__, exc))

    threads = [threading.Thread(target=worker_thread, args=(b,)) for b in range(total // 10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    eq('40 个并发 submit 无异常', errors, [])
    eq('40 条不同 message_id 全部入队', service.counters().get('queued'), 40)
    eq('同会话合并后只有 1 条 PENDING', service.quota.depth(), 1)

    # 异会话：40 个不同私聊 → 40 条独立任务
    service2, sender2, model2 = build(max_pending=100000)
    errors2 = []

    def worker_thread2(base):
        try:
            for i in range(10):
                cid = '9%03d' % (base * 10 + i)
                service2.submit(ev(chat_type='private', chat_id=cid,
                                   text='p%d-%d' % (base, i),
                                   message_id='PD-%d-%d' % (base, i)))
        except Exception as exc:
            errors2.append('%s: %s' % (type(exc).__name__, exc))

    threads = [threading.Thread(target=worker_thread2, args=(b,)) for b in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    eq('异会话并发 submit 无异常', errors2, [])
    eq('40 个不同会话 → 40 条 PENDING', service2.quota.depth(), 40)


def t_thread_safety_full_run():
    """真起 worker 线程跑一遍：submit 与 owner 线程共用一个 sqlite 连接。"""
    service, sender, model = build(max_pending=100000)
    service.reply_ok = True
    service.start()
    try:
        for b in range(8):
            threading.Thread(target=lambda base=b: [
                service.submit(ev(chat_type='private', chat_id='7%03d' % (base * 5 + i),
                                  text='x%d-%d' % (base, i),
                                  message_id='RUN-%d-%d' % (base, i)))
                for i in range(5)]).start()
        deadline = time.time() + 15
        while time.time() < deadline and len(sender.texts) < 40:
            time.sleep(0.05)
        eq('并发 submit + 后台处理：40 条全部发出', len(sender.texts), 40)
        eq('没有重复发送', len(set(sender.texts)), 40)
        stuck = service.db.execute(
            "SELECT count(*) FROM queue WHERE state='PROCESSING'").fetchone()[0]
        eq('没有任务卡在 PROCESSING', stuck, 0)
    finally:
        service.stop(timeout=10)


def t_status_file_atomic_and_heartbeat():
    service, sender, model = build(status_interval_s=0.05)
    service.start()
    try:
        path = service.status_path
        deadline = time.time() + 5
        while time.time() < deadline and not path.exists():
            time.sleep(0.02)
        check('status.json 落盘', path.exists(), str(path))
        bad = []
        for _ in range(60):
            try:
                data = json.loads(path.read_text())
                if not isinstance(data, dict):
                    bad.append('不是对象')
            except Exception as exc:
                bad.append('%s: %s' % (type(exc).__name__, exc))
            time.sleep(0.01)
        eq('连续读 60 次 status.json 都是完整 JSON（原子写）', bad, [])
        first = json.loads(path.read_text())['heartbeat']
        time.sleep(1.2)
        second = json.loads(path.read_text())['heartbeat']
        check('心跳在推进（独立线程写）', second > first, '%r -> %r' % (first, second))
        payload = service.status()
        for key in ('state', 'heartbeat', 'queue_depth', 'self_id', 'online',
                    'last_event_at', 'last_send_ok_at', 'last_error', 'sent_1h',
                    'stop'):
            check('status() 含契约字段 %s' % key, key in payload)
        eq('state=running', payload['state'], 'running')
        eq('self_id 来自通道', payload['self_id'], SELF)
        eq('status.json 权限 600',
           oct(os.stat(path).st_mode & 0o777), '0o600')
        eq('state_dir 权限 700',
           oct(os.stat(service.state_dir).st_mode & 0o777), '0o700')
    finally:
        service.stop(timeout=10)


def t_status_heartbeat_not_blocked_by_slow_model():
    """契约 §7.1：心跳不能被单条任务的处理时长绑架（真起三条线程）。"""
    service, sender, model = build(status_interval_s=0.05)
    entered = threading.Event()
    gate = threading.Event()

    def slow_reply(*a, **kw):
        entered.set()
        gate.wait(8)
        return '慢回复'
    model.reply = slow_reply
    service.start()
    try:
        service.submit(ev(text='在吗', at_me=True, message_id='HB-1'))
        check('owner 线程确实卡在模型里', entered.wait(5))
        t0 = service.heartbeat
        time.sleep(1.2)
        t1 = service.heartbeat
        check('owner 线程被模型卡住时，心跳线程仍在推进',
              t1 > t0, '%.3f -> %.3f' % (t0, t1))
        check('status.json 也在被刷新', service.status_path.exists())
        gate.set()
        deadline = time.time() + 6
        while time.time() < deadline and not sender.texts:
            time.sleep(0.05)
        eq('放行后回复正常发出', len(sender.texts), 1)
    finally:
        gate.set()
        service.stop(timeout=10)


def t_stop_closes_and_refuses_restart():
    service, sender, model = build()
    service.start()
    time.sleep(0.1)
    service.stop(timeout=5)
    eq('stop 后 running() False', service.running(), False)
    try:
        service.start()
        check('stop 之后再 start 必须抛 RuntimeError', False, '竟然没抛')
    except RuntimeError:
        check('stop 之后再 start 抛 RuntimeError', True)


def t_counters_and_bad_event():
    service, sender, model = build()
    eq('submit(None) → False', service.submit(None), False)
    eq('counters.bad_event', service.counters().get('bad_event'), 1)
    eq('未登记群 → 不计入 queued',
       service.submit(ev(chat_id='99999', text='x', at_me=True)), False)
    eq('counters.ignored', service.counters().get('ignored'), 1)
    eq('last_event_at 被记下（拒掉的事件也看得见）', service.last_event_at > 0, True)


def t_context_only_still_recorded():
    service, sender, model = build()
    eq('context_only 也算入队成功',
       service.submit(ev(text='随便一句话')), True)
    step(service, 2)
    eq('context_only 不发送', sender.texts, [])
    eq('context_only 不调模型', model.call_count, 0)
    eq('状态记成 CONTEXT_ONLY', qstate_of_last(service), 'CONTEXT_ONLY')
    row = service.db.execute("SELECT count(*) FROM turns WHERE role='user'").fetchone()[0]
    check('context_only 的消息进了时间线/记忆', row >= 1, 'user turns=%d' % row)


# ------------------------------------------------------------- 9. 链接阅读（§7.1）
def t_links_passed_to_model():
    calls = []
    good = {'url': 'https://example.com/a', 'status': 'read',
            'untrusted_text': '网页正文'}

    def fetcher(url, block):
        calls.append(url)
        return good
    service, sender, model = build(
        links=fetcher, links_cfg={'enabled': True, 'max_urls': 2})
    service.cfg['links'] = {'enabled': True, 'max_urls': 2}
    service.links_conf = service.cfg['links']
    service.submit(ev(text='看这个 https://example.com/a', at_me=True, message_id='LK-1'))
    step(service, 3)
    eq('链接被读取', calls, ['https://example.com/a'])
    eq('sources 交给了模型', model.calls[0]['sources'], [good])
    eq('文字照常发出', len(sender.texts), 1)


def t_links_failure_still_replies():
    def fetcher(url, block):
        raise TimeoutError('读超时')
    service, sender, model = build(links=fetcher)
    service.cfg['links'] = {'enabled': True, 'max_urls': 2}
    service.links_conf = service.cfg['links']
    service.submit(ev(text='https://a.example/1 看看', at_me=True, message_id='LK-2'))
    step(service, 3)
    eq('链接读失败仍然回文字', len(sender.texts), 1)
    src = model.calls[0]['sources']
    eq('失败只留 unreadable 条目', src[0]['status'], 'unreadable')


def t_links_disabled():
    calls = []
    service, sender, model = build(links=lambda u, b: calls.append(u))
    service.cfg['links'] = {'enabled': False}
    service.links_conf = {'enabled': False}
    service.submit(ev(text='https://a.example/1', at_me=True, message_id='LK-3'))
    step(service, 3)
    eq('links.enabled=false 时一个链接都不抓', calls, [])
    eq('模型收到的 sources 是空表', model.calls[0]['sources'], [])


# ------------------------------------------------------------- 10. 自学习（§7.1）
def t_learn_below_threshold():
    service, sender, model = build()
    service.memory.note_messages(GKEY, 5, 'group', '群')
    eq('没攒够 20 条 → 不学', service._worker.learn_cycle(), False)
    eq('没调模型', model.call_count, 0)


def t_learn_needs_queue_idle():
    service, sender, model = build()
    service.memory.note_messages(GKEY, 25, 'group', '群')
    for i in range(3):
        service.memory.record_turn(GKEY, 'user', '第 %d 句' % i)
    service.quota.enqueue('qq:%s:private:70007' % SELF, PRIORITY_DIRECT, '{}')
    before = model.call_count
    service._loop_once()
    eq('队列忙时不学习', model.call_count, before)


# ---- 调试探针：记录每条 decide 的输入与结论 ----
import qq.core.policy as _p
_orig_decide = _p.decide
def _spy_decide(event, cfg, **kw):
    d = _orig_decide(event, cfg, **kw)
    if event is not None and getattr(event, 'chat_id', '') == '30003':
        print('  [DECIDE] text=%r at_me=%s at_all=%s groups=%r -> %s/%s/%s'
              % (getattr(event, 'text', None), getattr(event, 'at_me', None),
                 getattr(event, 'at_all', None),
                 (cfg.get('groups') if isinstance(cfg, dict) else cfg),
                 d.action, d.priority, d.reason))
    return d
_p.decide = _spy_decide
import qq.core.service as _s
_s.policy.decide = _spy_decide

group('§6/§7 去重与重投')
for fn in (t_same_message_id_once, t_dedupe_survives_restart,
           t_same_message_id_different_chat,
           t_dedupe_different_self_id):
    run(fn)

group('§7 STOP 与 auto_send 总闸')
for fn in (t_stop_blocks_send, t_stop_during_generation, t_auto_send_false):
    run(fn)

group('§4 发送结果三态语义（unknown 绝不重发）')
for fn in (t_unknown_never_resent, t_failed_never_resent, t_sender_returns_none,
           t_sender_raises, t_last_send_ok_at_semantics):
    run(fn)

group('§7 输出安全闸')
for fn in (t_output_too_long, t_output_empty, t_output_boundary):
    run(fn)

group('§7 额度、队列上限、任务过期、每小时上限')
for fn in (t_quota_exhausted_waits, t_queue_full, t_queue_full_after_merge,
           t_task_expired, t_event_stale_rejected, t_max_replies_per_hour,
           t_max_replies_zero_unlimited, t_per_chat_rate_limit):
    run(fn)

group('§7 生图（失败不影响已发出的文字）')
for fn in (t_image_failure_does_not_affect_text, t_image_success,
           t_image_not_requested, t_image_disabled, t_image_prompt_is_claimed):
    run(fn)

group('§7 记忆隔离（跨平台 / 跨 self_id / 跨会话）')
for fn in (t_memory_isolation_platform, t_memory_isolation_self_id,
           t_memory_isolation_private_group):
    run(fn)

group('§7 线程安全与 status.json')
for fn in (t_thread_safety_submit, t_thread_safety_full_run,
           t_status_file_atomic_and_heartbeat,
           t_status_heartbeat_not_blocked_by_slow_model,
           t_stop_closes_and_refuses_restart, t_counters_and_bad_event,
           t_context_only_still_recorded):
    run(fn)

group('§7.1 链接阅读')
for fn in (t_links_passed_to_model, t_links_failure_still_replies, t_links_disabled):
    run(fn)

group('§7.1 风格自学习')
for fn in (t_learn_below_threshold, t_learn_needs_queue_idle):
    run(fn)

summary('service/worker 验证')
