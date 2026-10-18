"""qq/core 的离线单测：事件解析 / 去重台账 / 受限图片下载 / 服务全链路。

三条纪律（贯穿全文）：
- **不出网**：图片下载注入 opener/resolver/fetcher 替身；模型、搜索、生图全部注入假实现；
- **不碰生产库**：状态目录一律 tmpdir，并断言没写 ~/.local/state/qq-bot；
- **不连真实 QQ**：发送走 FakeSender，只记录调用。

跑法：cd /mnt/d/AgentPrograms/wechat-bot && python3 -m unittest test_qq_core -v
"""
import io
import json
import os
import shutil
import stat
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'src'))

from PIL import Image                                                          # noqa: E402

from qq.core import envelope, media                                            # noqa: E402
from qq.core import config as config_module                                   # noqa: E402
from qq.core import service as service_module                                 # noqa: E402
from qq.core import worker as worker_module                                   # noqa: E402
from qq.core.bridge import SendResult, Sender                                  # noqa: E402
from qq.core.service import QQService                                          # noqa: E402
from qq.core.store import Store                                                # noqa: E402
from quota import PRIORITY_DIRECT, PRIORITY_GROUP_AT, PRIORITY_GROUP_PLAIN     # noqa: E402

TEST_SELF_ID = '10001'
GROUP_ID = '20002'
FRIEND_ID = '30003'
BLOCKED_ID = '40004'


# ---------------------------------------------------------------- 工具
def png_bytes(size=(16, 16), color=(200, 30, 30)):
    buffer = io.BytesIO()
    Image.new('RGB', size, color).save(buffer, 'PNG')
    return buffer.getvalue()


def wait_for(predicate, timeout=5.0, interval=0.02):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return bool(predicate())


def onebot_payload(message_id='1', chat_type='private', chat_id=FRIEND_ID,
                   user_id=FRIEND_ID, text='你好', at=False, at_all=False,
                   image=None, self_id=TEST_SELF_ID, ts=None, post_type='message',
                   message=None):
    """造一份 OneBot v11 的 message 事件（形状与 NapCat 上报的一致）。"""
    if message is None:
        segments = []
        if at:
            segments.append({'type': 'at', 'data': {'qq': self_id}})
        if at_all:
            segments.append({'type': 'at', 'data': {'qq': 'all'}})
        if text:
            segments.append({'type': 'text', 'data': {'text': text}})
        if image:
            images = image if isinstance(image, (list, tuple)) else [image]
            for url in images:
                segments.append({'type': 'image',
                                 'data': {'url': url, 'file': 'x.png'}})
        message = segments
    payload = {'post_type': post_type, 'message_type': chat_type, 'self_id': self_id,
               'user_id': user_id, 'message_id': message_id,
               'time': time.time() if ts is None else ts,
               'sender': {'user_id': user_id, 'nickname': '年糕', 'card': '年糕'},
               'message': message}
    if chat_type == 'group':
        payload['group_id'] = chat_id
    return payload


def onebot_event(**kw):
    return envelope.from_onebot_event(onebot_payload(**kw))


def base_cfg(tmp, **over):
    cfg = {
        'state_dir': str(tmp),
        'auto_send': True,          # 单测默认开着总闸；关闸的行为另有专门用例
        'limits': {'window_5h': 1000, 'window_1d': 10000},
        'reply_max_chars': 200,
        'min_reply_seconds': 0,
        'max_replies_per_hour': 0,
        'event_max_age_s': 3600,
        'poll_interval_s': 0.05,
        'status_interval_s': 10.0,
        'max_queue': 100,
        'groups': {GROUP_ID: {'plain_mode': 'at_only'}},
        'direct_policy': 'blacklist',
        'direct_blacklist': [BLOCKED_ID],
        'mention_aliases': ['年糕'],
        'image_generation': {'enabled': True, 'max_per_hour': 3},
    }
    cfg.update(over)
    return cfg


class FakeSender(Sender):
    """发送通道替身：只记录，不碰网络。可以预设返回结果来模拟超时/失败。"""

    def __init__(self, self_id=TEST_SELF_ID):
        self._self_id = self_id
        self.online_flag = True
        self.texts = []
        self.images = []
        self.text_result = None
        self.image_result = None

    def send_text(self, event, text):
        self.texts.append({'chat_key': getattr(event, 'chat_key', ''), 'text': text})
        return self.text_result or SendResult(ok=True, unknown=False, message_id='m-1')

    def send_image(self, event, path):
        self.images.append({'chat_key': getattr(event, 'chat_key', ''), 'path': str(path)})
        return self.image_result or SendResult(ok=True, unknown=False)

    def self_id(self):
        return self._self_id

    def online(self):
        return self.online_flag


class FakeModel:
    """模型替身：固定文案 + 记录收到的上下文（风格学习要用的 call 也在）。"""

    def __init__(self, reply='好呀', on_reply=None, learn_json=None):
        self.reply_text = reply
        self.on_reply = on_reply
        self.calls = []
        self.sessions = []
        self.learn_json = learn_json or '{"style":"简洁直接","facts":["喜欢宝可梦"]}'
        self.call_count = 0
        self.call_error = None

    def call(self, messages, max_tokens=1800, model=None, provider=None):
        """风格学习走的是 provider.call 这条链（memory.learn 里调的）。"""
        self.call_count += 1
        if self.call_error:
            raise self.call_error
        return self.learn_json

    def session_for(self, chat_key):
        self.sessions.append(chat_key)

    def reply(self, fresh, history, sources, chat_context=None, hot_items=None,
              search_fn=None):
        self.calls.append({'fresh': list(fresh or []), 'history': list(history or []),
                           'sources': list(sources or []),
                           'context': chat_context or {}, 'hot': hot_items or []})
        if self.on_reply:
            self.on_reply(search_fn)
        return self.reply_text(fresh) if callable(self.reply_text) else self.reply_text


class FakeSearcher:
    def __init__(self):
        self.queries = []

    def search(self, text, aliases=()):
        self.queries.append(text)
        return [{'title': 't', 'url': 'https://example.com', 'summary': 's'}]


def service_for(tmp, cfg=None, sender=None, model=None, searcher=None,
                image_generator=None, fetcher=None, clock=time.time, hot_refresh=None,
                link_fetcher=None):
    """装配一个全注入的 QQService：不联网、不读生产配置。"""
    cfg = cfg if cfg is not None else base_cfg(tmp)
    sender = sender if sender is not None else FakeSender()
    model = model if model is not None else FakeModel()
    service = QQService(
        cfg, ROOT, sender, db_path=Path(str(tmp)) / 'qq.db', clock=clock,
        model_factory=(lambda *args: model),
        searcher=(lambda *args: searcher),
        image_generator=(lambda *args: image_generator),
        fetcher=fetcher if fetcher is not None else (lambda url, dest, **kw: None),
        hot_refresh=hot_refresh, link_fetcher=link_fetcher)
    return service, sender, model


# ---------------------------------------------------------------- envelope
class EnvelopeTests(unittest.TestCase):
    def test_array_message_is_parsed(self):
        event = onebot_event(text='晚上吃啥', at=True)
        self.assertEqual(event.chat_type, 'private')
        self.assertEqual(event.self_id, TEST_SELF_ID)
        self.assertEqual(event.sender_id, FRIEND_ID)
        self.assertEqual(event.sender_name, '年糕')
        self.assertEqual(event.text, '晚上吃啥')
        self.assertTrue(event.at_me)
        self.assertFalse(event.at_all)
        self.assertEqual(event.kind, 'private')
        self.assertEqual(event.chat_key, 'qq:%s:private:%s' % (TEST_SELF_ID, FRIEND_ID))
        self.assertEqual(event.dedupe_key,
                         '%s:private:%s:1' % (TEST_SELF_ID, FRIEND_ID))

    def test_cq_string_is_parsed_without_leaking_codes(self):
        """string 形态也必须解出纯文本——绝不能把 CQ 码塞进 text。"""
        event = onebot_event(message='[CQ:at,qq=%s] 在吗 [CQ:image,file=a.jpg]'
                                     % TEST_SELF_ID)
        self.assertEqual(event.text, '在吗')
        self.assertTrue(event.at_me)
        self.assertNotIn('CQ:', event.text)
        self.assertEqual(event.images, [{'url': '', 'file': 'a.jpg'}])

    def test_cq_escapes_are_unescaped(self):
        event = onebot_event(message='[CQ:face,id=1]&#91;数据&#93;&#44;逗号')
        self.assertEqual(event.text, '[数据],逗号')

    def test_image_segments_are_recorded_not_downloaded(self):
        event = onebot_event(text='看图', image='https://img.example.com/a.png')
        self.assertEqual(event.images,
                         [{'url': 'https://img.example.com/a.png', 'file': 'x.png'}])

    def test_at_all_is_not_at_me(self):
        event = onebot_event(text='开会了', at_all=True)
        self.assertTrue(event.at_all)
        self.assertFalse(event.at_me)

    def test_self_message_is_dropped(self):
        self.assertIsNone(envelope.from_onebot_event(
            onebot_payload(user_id=TEST_SELF_ID)))

    def test_notice_request_and_meta_are_dropped(self):
        for post_type in ('notice', 'request', 'meta_event'):
            self.assertIsNone(envelope.from_onebot_event(
                onebot_payload(post_type=post_type)))
        self.assertIsNone(envelope.from_onebot_event(
            onebot_payload(chat_type='discuss')))

    def test_missing_message_id_is_dropped(self):
        """没有 message_id 就没法去重：宁可丢，也不能冒险重复回复。"""
        payload = onebot_payload()
        payload.pop('message_id')
        self.assertIsNone(envelope.from_onebot_event(payload))

    def test_zero_ids_are_treated_as_missing(self):
        """0 不是有效 QQ 号：message_id=0 若被当成真值，一堆消息会共用同一个
        dedupe_key 互相顶掉（静默漏消息）。"""
        payload = onebot_payload()
        payload['message_id'] = 0
        self.assertIsNone(envelope.from_onebot_event(payload))
        payload = onebot_payload()
        payload['message_id'] = '0'
        self.assertIsNone(envelope.from_onebot_event(payload))
        payload = onebot_payload(self_id=0)
        self.assertIsNone(envelope.from_onebot_event(payload))
        payload = onebot_payload()
        payload['sender']['user_id'] = 0
        payload['user_id'] = 0
        self.assertIsNone(envelope.from_onebot_event(payload))

    def test_cq_param_key_case_is_ignored(self):
        """[CQ:AT,QQ=10001] 也要认出 at_me：类型大小写不敏感，键同理。"""
        event = onebot_event(message='[CQ:AT,QQ=%s] 在吗' % TEST_SELF_ID)
        self.assertTrue(event.at_me)
        self.assertEqual(event.text, '在吗')
        event = onebot_event(message='[CQ:at,QQ=all] 开会')
        self.assertTrue(event.at_all)
        self.assertFalse(event.at_me)

    def test_bad_payload_types_are_dropped(self):
        for payload in (None, [], 'x', {}, {'post_type': 'message'}):
            self.assertIsNone(envelope.from_onebot_event(payload))

    def test_batch_payload_carries_signature_and_route(self):
        event = onebot_event(message_id='55', text='在吗')

        class Decision:
            action = 'reply'
            priority = PRIORITY_DIRECT
            reason = 'direct'

        task = json.loads(envelope.batch_payload(event, Decision()))
        self.assertEqual(task['messages'][0]['signature'], event.dedupe_key)
        self.assertEqual(task['chat_key'], event.chat_key)
        self.assertEqual(task['action'], 'reply')
        self.assertEqual(task['chat_type'], 'private')
        self.assertEqual(task['chat_id'], FRIEND_ID)
        self.assertEqual(task['self_id'], TEST_SELF_ID)

    def test_from_task_restores_a_batch_event(self):
        first = onebot_event(message_id='1', text='第一句')
        second = onebot_event(message_id='2', text='第二句', image='https://a/b.png')

        class Decision:
            action = 'reply'
            priority = PRIORITY_DIRECT
            reason = 'direct'

        task = json.loads(envelope.batch_payload(first, Decision()))
        task['messages'].append(json.loads(
            envelope.batch_payload(second, Decision()))['messages'][0])
        restored = envelope.from_task(task)
        self.assertEqual(restored.chat_key, first.chat_key)
        self.assertEqual(restored.text, '第一句 第二句')
        self.assertEqual(len(restored.images), 1)


# ---------------------------------------------------------------- store
class StoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix='qq-store-'))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.store = Store(self.tmp / 'qq.db')
        self.addCleanup(self.store.close)

    def test_seen_returns_true_once(self):
        self.assertTrue(self.store.seen('k1'))
        self.assertFalse(self.store.seen('k1'))
        self.assertTrue(self.store.seen('k2'))

    def test_seen_rejects_empty_key(self):
        """空键不能登记：否则后面所有空键消息会被互相顶掉、全部不回。"""
        self.assertFalse(self.store.seen(''))
        self.assertFalse(self.store.seen(None))

    def test_target_roundtrip(self):
        chat_key = 'qq:%s:group:%s' % (TEST_SELF_ID, GROUP_ID)
        self.assertIsNone(self.store.target_of(chat_key))
        self.store.remember_target(chat_key, 'group', GROUP_ID)
        self.assertEqual(self.store.target_of(chat_key), ('group', GROUP_ID))
        self.store.remember_target(chat_key, 'group', GROUP_ID)
        self.assertEqual(self.store.stats()['targets'], 1)

    def test_send_log_roundtrip(self):
        self.store.record_send('ck', 'text', 'ok', 'm-1')
        self.store.record_send('ck', 'image', 'failed', '接口 500')
        last = self.store.last_send('ck')
        self.assertEqual(last['kind'], 'image')
        self.assertEqual(last['state'], 'failed')
        self.assertEqual(self.store.last_send('ck', 'text')['state'], 'ok')
        self.assertIsNone(self.store.last_send('没有这个会话'))
        self.assertEqual(self.store.count_sends(state='ok'), 1)
        self.assertEqual(self.store.stats()['send_failed'], 1)

    def test_file_db_uses_wal(self):
        mode = self.store.db.execute('PRAGMA journal_mode').fetchone()[0]
        self.assertEqual(str(mode).lower(), 'wal')


# ---------------------------------------------------------------- media
class MediaTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix='qq-media-'))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.opener = _RecordingOpener()

    def resolver(self, ip='93.184.216.34', port=443):
        def resolve(url):
            parts = urlsplit(url)
            return (parts, parts.hostname, port, ip)
        return resolve

    def fetch(self, url, **kw):
        kw.setdefault('opener', self.opener)
        kw.setdefault('resolver', self.resolver())
        return media.fetch_image(url, self.tmp, **kw)

    def test_downloads_png_named_by_hash_with_600_mode(self):
        raw = png_bytes()
        self.opener.responses = [(200, {'content-type': 'image/png'}, raw)]
        path = self.fetch('https://img.example.com/a.png?token=secret')
        self.assertIsNotNone(path)
        self.assertTrue(path.exists())
        import hashlib
        expected = hashlib.sha256(raw).hexdigest()[:16] + '.png'
        self.assertEqual(path.name, expected)
        self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
        self.assertEqual(path.read_bytes(), raw)
        self.assertEqual(self.opener.calls[0]['ip'], '93.184.216.34')

    def test_rejects_non_http_scheme_without_touching_dns(self):
        with mock.patch('web_reader.socket.getaddrinfo',
                        side_effect=AssertionError('不该解析 DNS')):
            self.assertIsNone(self.fetch('ftp://example.com/a.png',
                                         resolver=media.public_endpoint))
        self.assertEqual(self.opener.calls, [])

    def test_rejects_credentials_in_url(self):
        with mock.patch('web_reader.socket.getaddrinfo',
                        side_effect=AssertionError('不该解析 DNS')):
            self.assertIsNone(self.fetch('https://user:pw@example.com/a.png',
                                         resolver=media.public_endpoint))
        self.assertEqual(self.opener.calls, [])

    def test_rejects_non_standard_port(self):
        with mock.patch('web_reader.socket.getaddrinfo',
                        side_effect=AssertionError('不该解析 DNS')):
            self.assertIsNone(self.fetch('https://example.com:8080/a.png',
                                         resolver=media.public_endpoint))
        self.assertEqual(self.opener.calls, [])

    def test_rejects_private_address(self):
        with mock.patch('web_reader.socket.getaddrinfo',
                        return_value=[(2, 1, 6, '', ('127.0.0.1', 443))]):
            self.assertIsNone(self.fetch('https://example.com/a.png',
                                         resolver=media.public_endpoint))
        self.assertEqual(self.opener.calls, [])

    def test_rejects_mixed_public_and_private_dns(self):
        answers = [(2, 1, 6, '', ('93.184.216.34', 443)),
                   (2, 1, 6, '', ('10.0.0.5', 443))]
        with mock.patch('web_reader.socket.getaddrinfo', return_value=answers):
            self.assertIsNone(self.fetch('https://example.com/a.png',
                                         resolver=media.public_endpoint))
        self.assertEqual(self.opener.calls, [])

    def test_rejects_non_image_bytes(self):
        self.opener.responses = [(200, {'content-type': 'text/html'},
                                  '<html>不是图片</html>'.encode('utf-8'))]
        self.assertIsNone(self.fetch('https://img.example.com/a.png'))

    def test_rejects_broken_gif(self):
        self.opener.responses = [(200, {}, b'GIF89a' + b'\x00' * 32)]
        self.assertIsNone(self.fetch('https://img.example.com/a.gif'))

    def test_rejects_oversized_body(self):
        raw = png_bytes(size=(48, 48))
        self.assertGreater(len(raw), 64)
        self.opener.responses = [(200, {}, raw)]
        self.assertIsNone(self.fetch('https://img.example.com/a.png', max_bytes=64))

    def test_rejects_pixel_bomb(self):
        raw = png_bytes(size=(64, 64))
        self.opener.responses = [(200, {}, raw)]
        with mock.patch.object(media, 'MAX_PIXELS', 100):
            self.assertIsNone(self.fetch('https://img.example.com/a.png'))

    def test_rejects_http_error_status(self):
        self.opener.responses = [(404, {}, b'')]
        self.assertIsNone(self.fetch('https://img.example.com/a.png'))

    def test_follows_redirect_and_revalidates_each_hop(self):
        raw = png_bytes()
        self.opener.responses = [
            (302, {'location': 'https://cdn.example.com/b.png'}, b''),
            (200, {}, raw)]
        path = self.fetch('https://img.example.com/a.png')
        self.assertIsNotNone(path)
        self.assertEqual([c['url'] for c in self.opener.calls],
                         ['https://img.example.com/a.png',
                          'https://cdn.example.com/b.png'])

    def test_redirect_to_private_host_is_rejected(self):
        def resolver(url):
            if 'evil' in url:
                from web_reader import WebSafetyError
                raise WebSafetyError('禁止私网地址')
            return (urlsplit(url), 'img.example.com', 443, '93.184.216.34')

        self.opener.responses = [
            (302, {'location': 'https://evil.internal/x.png'}, b'')]
        self.assertIsNone(media.fetch_image('https://img.example.com/a.png',
                                            self.tmp, opener=self.opener,
                                            resolver=resolver))
        self.assertEqual(len(self.opener.calls), 1, '不该真的去连内网地址')

    def test_redirect_without_location_is_rejected(self):
        self.opener.responses = [(302, {}, b'')]
        self.assertIsNone(self.fetch('https://img.example.com/a.png'))

    def test_too_many_redirects(self):
        self.opener.responses = [(302, {'location': 'https://img.example.com/%d' % i}, b'')
                                 for i in range(6)]
        self.assertIsNone(self.fetch('https://img.example.com/a.png'))

    def test_opener_exception_never_propagates(self):
        self.opener.responses = [RuntimeError('连接被重置')]
        self.assertIsNone(self.fetch('https://img.example.com/a.png'))

    def test_junk_input_never_propagates(self):
        for url in (None, '', 123, 'not a url', 'https://'):
            self.assertIsNone(self.fetch(url))

    def test_within_event_limit_takes_first_n(self):
        event = onebot_event(image=['https://a/1.png', 'https://a/2.png',
                                    'https://a/3.png'])
        self.assertEqual(media.within_event_limit(event, 2),
                         ['https://a/1.png', 'https://a/2.png'])
        self.assertEqual(media.within_event_limit(event), ['https://a/1.png',
                                                           'https://a/2.png'])
        self.assertEqual(media.within_event_limit(event, 0), [])
        self.assertEqual(media.within_event_limit(event, '坏值'), [])

    def test_within_event_limit_skips_empty_urls(self):
        event = onebot_event(image=['', 'https://a/1.png'])
        self.assertEqual(media.within_event_limit(event, 5), ['https://a/1.png'])


class _RecordingOpener:
    """单次请求替身：按脚本返回，绝不真的建连接。"""

    def __init__(self, responses=None):
        self.responses = list(responses or [])
        self.calls = []

    def __call__(self, url, *, ip, timeout_s=0, max_bytes=0):
        self.calls.append({'url': url, 'ip': ip, 'timeout_s': timeout_s,
                           'max_bytes': max_bytes})
        item = self.responses.pop(0) if self.responses else (200, {}, b'')
        if isinstance(item, Exception):
            raise item
        return item


# ---------------------------------------------------------------- service
def turns_of(service, chat_key, role=None):
    with service._lock:
        sql = 'SELECT role,content FROM turns WHERE chat_key=? ORDER BY id'
        params = [chat_key]
        if role:
            sql += ' AND role=?'
            params.append(role)
        return service.db.execute(sql, params).fetchall()


def queue_state(service, chat_key):
    with service._lock:
        row = service.db.execute(
            'SELECT state FROM queue WHERE chat_key=? ORDER BY id DESC LIMIT 1',
            (chat_key,)).fetchone()
    return row[0] if row else ''


def queue_payload(service, chat_key):
    with service._lock:
        row = service.db.execute(
            'SELECT payload FROM queue WHERE chat_key=? ORDER BY id DESC LIMIT 1',
            (chat_key,)).fetchone()
    return json.loads(row[0]) if row else {}


def timeline_of(service, chat_key):
    with service._lock:
        return service.memory.get_timeline(chat_key)


class ServiceTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix='qq-core-'))
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def build(self, cfg=None, **kw):
        service, sender, model = service_for(self.tmp, cfg, **kw)
        self.addCleanup(service.stop)
        return service, sender, model

    def start(self, service):
        service.start()
        self.assertTrue(service.running(), 'start() 之后 owner 线程必须活着')


class SubmitGateTests(ServiceTestCase):
    """submit() 的四道门：过期、队满、重复、策略 ignore。"""

    def test_queue_full_rejects(self):
        service, sender, model = self.build(cfg=base_cfg(self.tmp, max_queue=0))
        self.assertFalse(service.submit(onebot_event()))
        self.assertEqual(service.counters()['queue_full'], 1)

    def test_queue_with_room_accepts(self):
        service, sender, model = self.build()
        self.assertTrue(service.submit(onebot_event()))
        self.assertEqual(service.counters()['queued'], 1)

    def test_stale_event_rejected(self):
        service, sender, model = self.build()
        self.assertFalse(service.submit(onebot_event(ts=time.time() - 100000)))
        self.assertEqual(service.counters()['stale'], 1)

    def test_duplicate_message_id_only_queued_once(self):
        service, sender, model = self.build()
        self.start(service)
        event = onebot_event(message_id='777')
        self.assertTrue(service.submit(event))
        self.assertFalse(service.submit(event))
        self.assertEqual(service.counters()['duplicate'], 1)
        self.assertTrue(wait_for(lambda: len(sender.texts) == 1))
        time.sleep(0.3)
        self.assertEqual(len(sender.texts), 1, '同 message_id 只处理一次')

    def test_none_event_is_counted_not_crashed(self):
        service, sender, model = self.build()
        self.assertFalse(service.submit(None))
        self.assertEqual(service.counters()['bad_event'], 1)

    def test_unregistered_group_ignored(self):
        service, sender, model = self.build()
        self.start(service)
        self.assertFalse(service.submit(
            onebot_event(chat_type='group', chat_id='88888')))
        self.assertEqual(service.counters()['ignored'], 1)
        time.sleep(0.2)
        self.assertEqual(sender.texts, [])
        self.assertNotIn('queued', service.counters())

    def test_direct_blacklist_ignored(self):
        service, sender, model = self.build()
        self.start(service)
        self.assertFalse(service.submit(onebot_event(chat_id=BLOCKED_ID,
                                                        user_id=BLOCKED_ID)))
        self.assertEqual(service.counters()['ignored'], 1)
        time.sleep(0.2)
        self.assertEqual(sender.texts, [])

    def test_notice_and_self_message_never_queue(self):
        service, sender, model = self.build()
        self.start(service)
        self.assertFalse(service.submit(envelope.from_onebot_event(
            onebot_payload(post_type='notice'))))
        self.assertIsNone(envelope.from_onebot_event(
            onebot_payload(user_id=TEST_SELF_ID)))
        time.sleep(0.2)
        self.assertEqual(sender.texts, [])
        self.assertNotIn('queued', service.counters())


class ReplyFlowTests(ServiceTestCase):
    def test_private_message_gets_replied(self):
        service, sender, model = self.build()
        self.start(service)
        event = onebot_event(text='晚上吃啥')
        self.assertTrue(service.submit(event))
        self.assertTrue(wait_for(lambda: len(sender.texts) == 1))
        self.assertEqual(sender.texts[0]['text'], '好呀')
        self.assertEqual(sender.texts[0]['chat_key'], event.chat_key)
        self.assertTrue(wait_for(lambda: queue_state(service, event.chat_key) == 'SENT'))
        self.assertEqual(service.store.last_send(event.chat_key, 'text')['state'], 'ok')
        self.assertEqual(service.status()['sent_1h'], 1)
        # 用户发言与机器人回复都进了多轮历史与时间线
        self.assertEqual([r[0] for r in turns_of(service, event.chat_key)],
                         ['user', 'assistant'])
        self.assertEqual([t['direction'] for t in timeline_of(service, event.chat_key)],
                         ['in', 'out'])
        self.assertEqual(model.calls[0]['fresh'][0]['text'], '晚上吃啥')
        self.assertEqual(model.sessions, [event.chat_key])

    def test_at_me_replies_with_top_priority(self):
        service, sender, model = self.build()
        self.start(service)
        event = onebot_event(chat_type='group', chat_id=GROUP_ID, text='看这个',
                             at=True)
        self.assertTrue(service.submit(event))
        payload = queue_payload(service, event.chat_key)
        self.assertEqual(payload['action'], 'reply')
        self.assertEqual(payload['reason'], 'at_me')
        self.assertEqual(payload['priority'], PRIORITY_GROUP_AT)
        self.assertTrue(wait_for(lambda: len(sender.texts) == 1))

    def test_text_fake_at_replies_through_alias(self):
        """手打的 @年糕 没有 at 段：不算被 @，但要按"喊名字"最高优先级接。"""
        service, sender, model = self.build()
        self.start(service)
        event = onebot_event(chat_type='group', chat_id=GROUP_ID, text='@年糕 在吗')
        self.assertFalse(event.at_me)
        self.assertTrue(service.submit(event))
        payload = queue_payload(service, event.chat_key)
        self.assertEqual(payload['action'], 'reply')
        self.assertEqual(payload['reason'], 'mention_alias')
        self.assertEqual(payload['priority'], PRIORITY_GROUP_AT)
        self.assertTrue(wait_for(lambda: len(sender.texts) == 1))

    def test_at_only_group_records_context_without_reply(self):
        service, sender, model = self.build()
        self.start(service)
        event = onebot_event(chat_type='group', chat_id=GROUP_ID, text='今天天气不错')
        self.assertTrue(service.submit(event))
        chat_key = event.chat_key
        self.assertTrue(wait_for(lambda: len(timeline_of(service, chat_key)) == 1))
        payload = queue_payload(service, chat_key)
        self.assertEqual(payload['action'], 'context_only')
        self.assertEqual(payload['reason'], 'plain_at_only')
        self.assertEqual(payload['priority'], PRIORITY_GROUP_PLAIN)
        time.sleep(0.2)
        self.assertEqual(sender.texts, [])
        self.assertFalse(model.calls, 'context_only 不该花模型额度')
        self.assertEqual(queue_state(service, chat_key), 'CONTEXT_ONLY')

    def test_group_without_plain_mode_stays_conservative_end_to_end(self):
        """群登记了但没写 plain_mode → 普通消息只当上下文（从配置一路走到判定）。

        必须走 QQService（内部会 config.normalize）：只在 policy 层断言的话，
        normalize 偷偷给没写 plain_mode 的群补一个 plain_mode='all' 是抓不住的
        ——qq-verifier 的 M07 变体正是这么存活下来的。
        """
        cfg = base_cfg(self.tmp, groups={GROUP_ID: {}})
        service, sender, model = self.build(cfg=cfg)
        self.assertEqual(service.cfg['groups'][GROUP_ID], {},
                         'normalize 不该给没写 plain_mode 的群凭空补值')
        self.start(service)
        event = onebot_event(chat_type='group', chat_id=GROUP_ID, text='闲聊一句')
        self.assertTrue(service.submit(event))
        self.assertTrue(wait_for(
            lambda: queue_state(service, event.chat_key) == 'CONTEXT_ONLY'))
        time.sleep(0.2)
        self.assertEqual(sender.texts, [], '默认必须是最保守的 at_only')
        self.assertFalse(model.calls)
        self.assertEqual(queue_payload(service, event.chat_key)['reason'],
                         'plain_at_only')

    def test_selective_group_records_context_without_reply(self):
        cfg = base_cfg(self.tmp, groups={GROUP_ID: {'plain_mode': 'selective'}})
        service, sender, model = self.build(cfg=cfg)
        self.start(service)
        event = onebot_event(chat_type='group', chat_id=GROUP_ID, text='随便说一句')
        self.assertTrue(service.submit(event))
        self.assertTrue(wait_for(
            lambda: queue_state(service, event.chat_key) == 'CONTEXT_ONLY'))
        self.assertEqual(sender.texts, [])
        self.assertEqual(queue_payload(service, event.chat_key)['reason'],
                         'plain_selective')

    def test_idle_group_replies_when_queue_is_free(self):
        cfg = base_cfg(self.tmp, groups={GROUP_ID: {'plain_mode': 'idle'}})
        service, sender, model = self.build(cfg=cfg)
        self.start(service)
        event = onebot_event(chat_type='group', chat_id=GROUP_ID, text='闲聊一句')
        self.assertTrue(service.submit(event))
        self.assertEqual(queue_payload(service, event.chat_key)['reason'], 'plain_idle')
        self.assertTrue(wait_for(lambda: len(sender.texts) == 1))

    def test_all_group_replies(self):
        cfg = base_cfg(self.tmp, groups={GROUP_ID: {'plain_mode': 'all'}})
        service, sender, model = self.build(cfg=cfg)
        self.start(service)
        event = onebot_event(chat_type='group', chat_id=GROUP_ID, text='闲聊一句')
        self.assertTrue(service.submit(event))
        self.assertEqual(queue_payload(service, event.chat_key)['reason'], 'plain_all')
        self.assertTrue(wait_for(lambda: len(sender.texts) == 1))

    def test_idle_group_stays_quiet_when_queue_busy(self):
        cfg = base_cfg(self.tmp, groups={GROUP_ID: {'plain_mode': 'idle'}})
        service, sender, model = self.build(cfg=cfg)
        # 故意不 start()：队列里先塞一条别的会话的活，制造"忙"的状态
        service.quota.enqueue('qq:%s:private:99999' % TEST_SELF_ID,
                              PRIORITY_DIRECT, '{}')
        event = onebot_event(chat_type='group', chat_id=GROUP_ID, text='闲聊一句')
        self.assertTrue(service.submit(event))
        payload = queue_payload(service, event.chat_key)
        self.assertEqual(payload['action'], 'context_only')
        self.assertEqual(payload['reason'], 'plain_busy')

    def test_hourly_reply_cap_falls_back_to_context_only(self):
        cfg = base_cfg(self.tmp, max_replies_per_hour=2)
        service, sender, model = self.build(cfg=cfg)
        event = onebot_event(text='在吗')
        for _ in range(2):
            service.memory.record_turn(event.chat_key, 'assistant', '之前的回复')
        self.start(service)
        self.assertTrue(service.submit(event))
        self.assertTrue(wait_for(
            lambda: queue_state(service, event.chat_key) == 'RATE_LIMITED'))
        self.assertEqual(sender.texts, [])
        self.assertFalse(model.calls, '到顶了就不该再花额度')
        self.assertEqual(len(timeline_of(service, event.chat_key)), 1, '消息照记时间线')

    def test_pending_at_message_is_not_swallowed_by_a_later_plain_message(self):
        """同会话排队合并时，先被 @ 的那条不能被后来的闲聊吞掉（契约 §3 + §7）。

        src 的 quota.merge_payloads 是"拿新 payload 的顶层字段当结果"的：只信顶层
        action 的话，这条 @ 会被降级成 context_only、永远没人回。所以回话意图与
        优先级都改成按**消息级**记录、worker 按整批算。
        """
        cfg = base_cfg(self.tmp, groups={GROUP_ID: {'plain_mode': 'at_only'}})
        service, sender, model = self.build(cfg=cfg)     # 故意不 start：任务留在队列里
        at_event = onebot_event(message_id='mg-at', chat_type='group',
                                chat_id=GROUP_ID, text='看这个', at=True)
        plain_event = onebot_event(message_id='mg-plain', chat_type='group',
                                   chat_id=GROUP_ID, text='随便说一句')
        self.assertTrue(service.submit(at_event))
        self.assertTrue(service.submit(plain_event))
        payload = queue_payload(service, at_event.chat_key)
        self.assertEqual(len(payload['messages']), 2, '两条消息都要留在合并后的 payload 里')
        self.assertEqual(payload['action'], 'context_only',
                         'src 的合并语义就是"新的顶层字段赢"，这里如实记录现状')
        with service._lock:
            row = service.quota.claim(service.claim_lease_s)
        service._worker.process(row)
        self.assertEqual(len(sender.texts), 1, '被 @ 的消息必须还能被回，而且只回一次')
        self.assertEqual(service.store.last_send(at_event.chat_key, 'text')['state'],
                         'ok')
        fresh = model.calls[0]['fresh']
        self.assertTrue(any('看这个' in m['text'] for m in fresh),
                        '被 @ 的那条要一起给模型看到：%r' % (fresh,))
        self.assertEqual(service.plain_reply_times(at_event.chat_key), [],
                         '按 @ 优先级回的，不该记成普通消息回复（否则冷却/上限会算错）')

    def test_search_executor_runs_at_most_once_per_reply(self):
        searcher = FakeSearcher()
        model = FakeModel('查到了', on_reply=lambda search_fn: (
            search_fn('第一次'), search_fn('第二次'), search_fn('第三次')))
        service, sender, _ = self.build(model=model, searcher=searcher)
        self.start(service)
        self.assertTrue(service.submit(onebot_event(text='最新版本怎么样')))
        self.assertTrue(wait_for(lambda: len(sender.texts) == 1))
        self.assertEqual(searcher.queries, ['第一次'], '一次回复最多查一次')


class StopFileTests(ServiceTestCase):
    def test_stop_file_blocks_speaking_until_removed(self):
        service, sender, model = self.build()
        service.stop_path.write_text('停', encoding='utf-8')
        self.start(service)
        event = onebot_event(text='在吗')
        self.assertTrue(service.submit(event))
        time.sleep(0.4)
        self.assertEqual(sender.texts, [], 'STOP 存在时绝不出话')
        # 不只是"不发送"：连生成都不做、额度一点都不花
        # （删掉生成前那道 STOP 检查，这几条断言必须挂）
        self.assertEqual(model.calls, [], 'STOP 在位时不该调模型')
        self.assertEqual(service.quota.status()['used_5h'], 0,
                         'STOP 在位时不该消耗额度')
        self.assertTrue(service.status()['stop'])
        service.stop_path.unlink()
        self.assertTrue(wait_for(lambda: len(sender.texts) == 1),
                        '解除 STOP 之后消息不该丢')
        self.assertIn(service.status()['stop'], (False,))

    def test_stop_check_inside_processing_blocks_generation(self):
        """STOP 在位时，**已经领出来的任务**也必须停在生成之前（不调模型、不花额度）。

        为什么要绕过 _loop_once 直接驱动 process：_loop_once 里还有一道 STOP 检查
        （干脆不领任务），只做端到端断言的话，把处理里那道检查删掉测试照样绿
        ——qq-verifier 的突变测试正是这么发现"25 个突变里它存活"的。
        这里手工把任务领出来再喂给 process，专门逼那道检查。
        """
        service, sender, model = self.build()
        service.stop_path.write_text('停', encoding='utf-8')
        event = onebot_event(text='在吗')
        self.assertTrue(service.submit(event))
        with service._lock:
            row = service.quota.claim(service.claim_lease_s)
        self.assertIsNotNone(row)
        service._worker.process(row)
        self.assertEqual(model.calls, [], 'STOP 在位时不该调模型')
        self.assertEqual(service.quota.status()['used_5h'], 0, 'STOP 在位时不该花额度')
        self.assertEqual(sender.texts, [])
        self.assertEqual(queue_state(service, event.chat_key), 'STOPPED')

    def test_stop_checked_again_right_before_sending(self):
        """生成期间被叫停（STOP 在生成**之后**才出现）就绝不许发送。

        这是"发送前再查一次 STOP"那道检查的唯一覆盖点：_loop_once 与处理开头的
        两道 STOP 检查都发生在它之前，只有这条能证明"生成完到发送之间"也查了。
        """
        service, sender, model = self.build()
        chat_key = 'qq:%s:private:%s' % (TEST_SELF_ID, FRIEND_ID)

        def stop_during_generation(search_fn):
            service.stop_path.write_text('停', encoding='utf-8')

        model.on_reply = stop_during_generation
        self.start(service)
        self.assertTrue(service.submit(onebot_event(text='在吗')))
        self.assertTrue(wait_for(lambda: queue_state(service, chat_key) == 'STOPPED'))
        # 回复确实生成好了（STOP 是在生成期间出现的），但一个字都不许发出去
        self.assertEqual(len(model.calls), 1, '这条用例必须走到"生成完"那一步')
        self.assertEqual(sender.texts, [], '生成期间被叫停就不能发送')
        self.assertIsNone(service.store.last_send(chat_key, 'text'),
                          '连一条发送记录都不该落')


class SendResultTests(ServiceTestCase):
    def _run(self, sender_result, expected_state):
        service, sender, model = self.build(sender=FakeSender())
        sender.text_result = sender_result
        self.start(service)
        event = onebot_event(text='在吗')
        self.assertTrue(service.submit(event))
        self.assertTrue(wait_for(
            lambda: queue_state(service, event.chat_key) == expected_state))
        return service, sender, event

    def test_unknown_send_is_never_retried(self):
        service, sender, event = self._run(
            SendResult(ok=False, unknown=True, error='网关超时'), 'UNKNOWN')
        self.assertEqual(len(sender.texts), 1)
        self.assertEqual(service.store.last_send(event.chat_key, 'text')['state'],
                         'unknown')
        time.sleep(0.4)
        self.assertEqual(len(sender.texts), 1, 'unknown 绝不能重发（可能已经发出去了）')

    def test_unknown_send_does_not_refresh_confirmed_timestamp(self):
        """D1 回归：unknown 只算"刚说过话"，不算"确认发出"。

        last_send_ok_at 的语义是"最近一次**确认**发出"。被超时的发送刷新它，
        就会与 send_log 里的 state=unknown 自相矛盾（看门狗会以为消息发出去了）。
        """
        service, sender, event = self._run(
            SendResult(ok=False, unknown=True, error='网关超时'), 'UNKNOWN')
        self.assertEqual(service.status()['last_send_ok_at'], 0.0,
                         '没确认的发送不该刷新 last_send_ok_at')
        self.assertGreater(service.last_reply_at(event.chat_key), 0.0,
                           '但要记下"刚说过话"，避免几秒内又说一遍')
        self.assertEqual(service.status()['sent_1h'], 0,
                         'unknown 不计入"确认发出"的统计')

    def test_failed_send_is_recorded_and_not_retried(self):
        service, sender, event = self._run(
            SendResult(ok=False, unknown=False, error='接口 500'), 'FAILED')
        self.assertEqual(len(sender.texts), 1)
        self.assertEqual(service.store.last_send(event.chat_key, 'text')['state'],
                         'failed')
        self.assertEqual(service.last_error, '')

    def test_unsafe_reply_is_blocked(self):
        service, sender, model = self.build(model=FakeModel('啰' * 300))
        self.start(service)
        event = onebot_event(text='在吗')
        self.assertTrue(service.submit(event))
        self.assertTrue(wait_for(
            lambda: queue_state(service, event.chat_key) == 'UNSAFE'))
        self.assertEqual(sender.texts, [], '没过安全闸的回复一个字都不能发')
        self.assertTrue(service.status()['last_error'])

    def test_generation_error_is_retried_once_then_gives_up(self):
        model = FakeModel('好呀')

        def explode(fresh):
            raise RuntimeError('模型挂了')

        model.reply_text = explode
        service, sender, model = self.build(model=model)
        self.start(service)
        event = onebot_event(text='在吗')
        self.assertTrue(service.submit(event))
        self.assertTrue(wait_for(
            lambda: queue_state(service, event.chat_key) == 'ERROR', timeout=8.0))
        self.assertEqual(sender.texts, [])
        self.assertEqual(len(model.calls), 2, '失败最多重排一次')
        self.assertTrue(service.status()['last_error'])


class ImageReplyTests(ServiceTestCase):
    def test_image_failure_does_not_resend_text(self):
        attempts = []

        def broken_generator(prompt):
            attempts.append(prompt)
            raise RuntimeError('生图接口挂了')

        service, sender, model = self.build(model=FakeModel('好，画一张'),
                                            image_generator=broken_generator)
        self.start(service)
        self.assertTrue(service.submit(onebot_event(text='帮我画一张图')))
        self.assertTrue(wait_for(lambda: len(attempts) == 1))
        self.assertEqual(len(sender.texts), 1)
        self.assertEqual(sender.images, [])
        time.sleep(0.3)
        self.assertEqual(len(sender.texts), 1, '文字已发出，图失败绝不能重发文字')

    def test_image_sent_after_successful_text(self):
        generated = []
        target = self.tmp / 'gen.png'

        def generator(prompt):
            generated.append(prompt)
            target.write_bytes(png_bytes())
            return target

        service, sender, model = self.build(model=FakeModel('好，画一张'),
                                            image_generator=generator)
        self.start(service)
        event = onebot_event(text='帮我画一张小猫')
        self.assertTrue(service.submit(event))
        self.assertTrue(wait_for(lambda: len(sender.images) == 1))
        self.assertEqual(len(sender.texts), 1)
        self.assertEqual(sender.images[0]['path'], str(target))
        self.assertIn('小猫', generated[0])
        self.assertIn('年糕.Agent', generated[0])
        self.assertEqual(service.store.last_send(event.chat_key, 'image')['state'],
                         'ok')
        self.assertTrue(wait_for(
            lambda: [t['kind'] for t in timeline_of(service, event.chat_key)]
            == ['text', 'text', 'image']))

    def test_image_reply_is_not_triggered_without_keyword(self):
        calls = []
        service, sender, model = self.build(
            model=FakeModel('好呀'),
            image_generator=lambda prompt: calls.append(prompt))
        self.start(service)
        self.assertTrue(service.submit(onebot_event(text='在吗')))
        self.assertTrue(wait_for(lambda: len(sender.texts) == 1))
        time.sleep(0.2)
        self.assertEqual(calls, [])
        self.assertEqual(sender.images, [])

    def test_image_hourly_cap_is_per_chat(self):
        target = self.tmp / 'gen.png'
        target.write_bytes(png_bytes())

        def generator(prompt):
            return target

        cfg = base_cfg(self.tmp, image_generation={'enabled': True,
                                                   'max_per_hour': 1})
        service, sender, model = self.build(cfg=cfg, model=FakeModel('好，画一张'),
                                            image_generator=generator)
        self.start(service)
        self.assertTrue(service.submit(onebot_event(message_id='1', text='画一张猫')))
        self.assertTrue(wait_for(lambda: len(sender.images) == 1))
        self.assertTrue(service.submit(onebot_event(message_id='2', text='画一张狗')))
        self.assertTrue(wait_for(lambda: len(sender.texts) == 2))
        time.sleep(0.3)
        self.assertEqual(len(sender.images), 1, '每会话每小时发图数要封顶')


class InboundImageTests(ServiceTestCase):
    def test_images_are_fetched_through_injected_fetcher(self):
        calls = []

        def fetcher(url, dest_dir, **kwargs):
            calls.append({'url': url, 'dest': str(dest_dir), 'kwargs': kwargs})
            Path(dest_dir).mkdir(parents=True, exist_ok=True)
            path = Path(dest_dir) / ('img-%d.png' % len(calls))
            path.write_bytes(png_bytes())
            return path

        service, sender, model = self.build(fetcher=fetcher)
        self.start(service)
        event = onebot_event(text='看这张', image='https://img.example.com/a.png')
        self.assertTrue(service.submit(event))
        self.assertTrue(wait_for(lambda: len(calls) == 1))
        self.assertEqual(calls[0]['url'], 'https://img.example.com/a.png')
        self.assertEqual(calls[0]['dest'], str(service.media_dir))
        self.assertTrue(wait_for(
            lambda: len(timeline_of(service, event.chat_key)) >= 1))
        entry = timeline_of(service, event.chat_key)[0]
        self.assertEqual(entry['kind'], 'image')
        self.assertTrue(entry['image_path'].endswith('img-1.png'))
        self.assertTrue(wait_for(lambda: len(sender.texts) == 1))

    def test_image_count_per_event_is_capped(self):
        urls = []

        def fetcher(url, dest_dir, **kwargs):
            urls.append(url)
            return None

        cfg = base_cfg(self.tmp, media={'max_images': 2})
        service, sender, model = self.build(cfg=cfg, fetcher=fetcher)
        self.start(service)
        self.assertTrue(service.submit(onebot_event(
            text='三张图', image=['https://a/1.png', 'https://a/2.png',
                                 'https://a/3.png'])))
        self.assertTrue(wait_for(lambda: len(urls) == 2))
        time.sleep(0.2)
        self.assertEqual(urls, ['https://a/1.png', 'https://a/2.png'])

    def test_image_download_failure_falls_back_to_text(self):
        service, sender, model = self.build(fetcher=lambda url, dest, **kw: None)
        self.start(service)
        event = onebot_event(text='看这张', image='https://img.example.com/a.png')
        self.assertTrue(service.submit(event))
        self.assertTrue(wait_for(lambda: len(sender.texts) == 1))
        entry = timeline_of(service, event.chat_key)[0]
        self.assertEqual(entry['kind'], 'image')
        self.assertEqual(entry['image_path'], '')


class ImageUnavailableTests(ServiceTestCase):
    """真机缺陷回归（2026-10-18 19:46）：图片取不到时绝不许装懂。

    现象：假 NapCat 发「图片 + 这张图里是什么」，图片 URL 握手超时取不到，
    机器人却回"是本糕的像素探险形象呀！戴着探险帽、背着蓝色小背包……"
    ——它根本没看到图，只收到一条 kind=image、text 为空、没有附件的新消息，就编了。
    """

    MARK = '图片未取到'          # 只断言关键片段，允许标记文案被微调

    def dead_fetcher(self, calls=None):
        def fetch(url, dest_dir, **kwargs):
            if calls is not None:
                calls.append(url)
            return None
        return fetch

    def ok_fetcher(self, name='ok.png'):
        def fetch(url, dest_dir, **kwargs):
            Path(dest_dir).mkdir(parents=True, exist_ok=True)
            path = Path(dest_dir) / name
            path.write_bytes(png_bytes())
            return path
        return fetch

    def test_failed_download_is_announced_to_the_model(self):
        calls = []
        service, sender, model = self.build(fetcher=self.dead_fetcher(calls))
        self.start(service)
        event = onebot_event(text='这张图里是什么',
                             image='https://img.example.com/a.png')
        self.assertTrue(service.submit(event))
        self.assertTrue(wait_for(lambda: len(sender.texts) == 1),
                        '取不到图也要照常回话，只是不许装懂')
        self.assertEqual(calls, ['https://img.example.com/a.png'])
        fresh = model.calls[0]['fresh']
        self.assertEqual(fresh[0]['kind'], 'image')
        self.assertIn(self.MARK, fresh[0]['text'], '必须告诉模型图没拿到：%r' % (fresh,))
        self.assertIn('这张图里是什么', fresh[0]['text'], '用户原话不能丢')
        entry = timeline_of(service, event.chat_key)[0]
        self.assertIn(self.MARK, entry['text'], '时间线里也要留同一条痕迹')
        self.assertEqual(entry['image_path'], '')

    def test_image_only_message_with_failed_download_is_never_empty(self):
        """只有图片、下载失败：text 也不能为空（空 text + 无附件 = 让模型瞎猜）。"""
        service, sender, model = self.build(fetcher=self.dead_fetcher())
        self.start(service)
        event = onebot_event(text='', image='https://img.example.com/a.png')
        self.assertTrue(service.submit(event))
        self.assertTrue(wait_for(lambda: len(sender.texts) == 1))
        fresh = model.calls[0]['fresh']
        self.assertTrue(fresh[0]['text'].strip(), '绝不能把空 text 丢给模型')
        self.assertIn(self.MARK, fresh[0]['text'])

    def test_successful_download_keeps_text_untouched(self):
        """下载成功时行为不变：text 原样、没有标记、时间线里有图片路径。"""
        service, sender, model = self.build(fetcher=self.ok_fetcher())
        self.start(service)
        event = onebot_event(text='这张图里是什么',
                             image='https://img.example.com/a.png')
        self.assertTrue(service.submit(event))
        self.assertTrue(wait_for(lambda: len(sender.texts) == 1))
        fresh = model.calls[0]['fresh']
        self.assertEqual(fresh[0]['text'], '这张图里是什么')
        self.assertNotIn(self.MARK, fresh[0]['text'])
        self.assertTrue(timeline_of(service, event.chat_key)[0]['image_path']
                        .endswith('ok.png'))

    def test_failed_first_image_is_not_replaced_by_the_second(self):
        """前一条的图挂了、后一条的图成功：不能张冠李戴。"""
        def fetch(url, dest_dir, **kwargs):
            if 'bad' in url:
                return None
            return self.ok_fetcher('good.png')(url, dest_dir, **kwargs)

        service, sender, model = self.build(fetcher=fetch)
        first = onebot_event(message_id='i-1', text='',
                             image='https://img.example.com/bad.png')
        second = onebot_event(message_id='i-2', text='',
                              image='https://img.example.com/good.png')
        self.assertTrue(service.submit(first))
        self.assertTrue(service.submit(second))
        with service._lock:
            row = service.quota.claim(service.claim_lease_s)
        service._worker.process(row)
        entries = [e for e in timeline_of(service, first.chat_key)
                   if e['direction'] == 'in']
        self.assertEqual(len(entries), 2)
        self.assertEqual(entries[0]['image_path'], '', '第一条的图没拿到，不能挂别人的图')
        self.assertIn(self.MARK, entries[0]['text'])
        self.assertTrue(entries[1]['image_path'].endswith('good.png'))
        self.assertNotIn(self.MARK, entries[1]['text'], '第二条的图是好的，不该被标记')


class StatusTests(ServiceTestCase):
    CONTRACT_FIELDS = ('state', 'heartbeat', 'queue_depth', 'self_id', 'online',
                       'last_event_at', 'last_send_ok_at', 'last_error', 'sent_1h',
                       'stop')

    def test_status_has_contract_fields_and_is_written_atomically(self):
        service, sender, model = self.build()
        self.start(service)
        payload = service.status()
        for field in self.CONTRACT_FIELDS:
            self.assertIn(field, payload)
        self.assertEqual(payload['state'], 'running')
        self.assertEqual(payload['self_id'], TEST_SELF_ID)
        self.assertTrue(payload['online'])
        self.assertFalse(payload['stop'])
        on_disk = json.loads(service.status_path.read_text(encoding='utf-8'))
        self.assertEqual(on_disk['state'], 'running')
        self.assertEqual(on_disk['self_id'], TEST_SELF_ID)
        self.assertEqual(stat.S_IMODE(service.status_path.stat().st_mode), 0o600)

    def test_status_file_is_always_complete_json(self):
        """原子写的**真正**不变量：随时读到的 status.json 都是完整 JSON。

        别断言"目录里没有临时文件"：心跳线程也在原子写，write_text 与 replace
        之间天然有个窗口，那种断言必然 flaky（qq-verifier 实测 25 次挂 5 次）。
        """
        cfg = base_cfg(self.tmp, status_interval_s=0.1)
        service, sender, model = self.build(cfg=cfg)
        self.start(service)
        self.assertTrue(wait_for(lambda: service.status_path.exists(), timeout=3.0))

        def heartbeat():
            return json.loads(service.status_path.read_text(encoding='utf-8'))['heartbeat']

        # 先"等到心跳真的走一格"再密集读：写死"2 秒内必须走"是负载敏感的断言
        # （25 个 python 抢 CPU 时它挂过），wait_for 只是把等待放宽，不放松不变量。
        first = heartbeat()
        self.assertTrue(wait_for(lambda: heartbeat() > first, timeout=10.0),
                        '心跳线程该一直往前走')
        beats = []
        for _ in range(300):
            try:
                beats.append(heartbeat())
            except ValueError as exc:               # 读到半截 JSON 就是原子写失效
                self.fail('读到了半截 status.json：%s' % exc)
            time.sleep(0.005)
        self.assertEqual(len(beats), 300)
        self.assertEqual(beats, sorted(beats), '心跳必须单调不减')

    def test_status_reports_queue_depth_and_stop(self):
        service, sender, model = self.build()
        service.stop_path.write_text('停', encoding='utf-8')
        self.assertTrue(service.submit(onebot_event()))
        payload = service.status()
        self.assertEqual(payload['queue_depth'], 1)
        self.assertTrue(payload['stop'])
        self.assertEqual(payload['state'], 'stopped')

    def test_status_survives_sender_failure(self):
        class BrokenSender(FakeSender):
            def self_id(self):
                raise RuntimeError('通道没连上')

            def online(self):
                raise RuntimeError('通道没连上')

        service, sender, model = self.build(sender=BrokenSender())
        payload = service.status()
        self.assertEqual(payload['self_id'], '')
        self.assertFalse(payload['online'])

    def test_status_after_stop_is_readable(self):
        service, sender, model = self.build()
        self.start(service)
        self.assertTrue(service.submit(onebot_event()))
        self.assertTrue(wait_for(lambda: len(sender.texts) == 1))
        service.stop()
        self.assertFalse(service.running())
        payload = service.status()
        self.assertEqual(payload['state'], 'stopped')
        on_disk = json.loads(service.status_path.read_text(encoding='utf-8'))
        self.assertEqual(on_disk['state'], 'stopped')

    def test_state_dir_is_isolated_from_production(self):
        production = Path.home() / '.local' / 'state' / 'qq-bot'
        before = production.stat().st_mtime_ns if production.exists() else None
        service, sender, model = self.build()
        self.start(service)
        self.assertTrue(service.submit(onebot_event()))
        self.assertTrue(wait_for(lambda: len(sender.texts) == 1))
        service.status()
        self.assertEqual(service.state_dir, Path(str(self.tmp)))
        self.assertTrue((self.tmp / 'qq.db').exists())
        self.assertTrue((self.tmp / 'status.json').exists())
        after = production.stat().st_mtime_ns if production.exists() else None
        self.assertEqual(before, after, '测试绝不能碰生产状态目录 ~/.local/state/qq-bot')

    def test_start_stop_lifecycle(self):
        service, sender, model = self.build()
        self.assertFalse(service.running())
        self.start(service)
        self.assertTrue(service.submit(onebot_event()))
        self.assertTrue(wait_for(lambda: len(sender.texts) == 1))
        service.stop()
        self.assertFalse(service.running())
        service.stop()          # 重复 stop 不该炸
        self.assertFalse(service.running())



# ---------------------------------------------------------------- 并发
class ConcurrencyTests(ServiceTestCase):
    def test_submit_from_many_threads_while_worker_runs(self):
        """submit 线程与 owner 线程共用一个 sqlite 连接，不能撞出事务错误。

        回归用例：并发 submit + worker 时曾经偶发
        OperationalError: cannot start a transaction within a transaction，
        撞上之后那条消息就一直卡在 PROCESSING 里再也回不了。
        """
        service, sender, model = self.build()
        self.start(service)
        errors = []

        def hammer(index):
            try:
                for i in range(8):
                    service.submit(onebot_event(
                        message_id='%d-%d' % (index, i),
                        chat_id='5000%d' % index, user_id='5000%d' % index,
                        text='并发消息 %d' % i))
            except Exception as exc:               # noqa: BLE001
                errors.append('%s: %s' % (type(exc).__name__, exc))

        threads = [threading.Thread(target=hammer, args=(k,)) for k in range(4)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(10)
        self.assertEqual(errors, [])
        self.assertTrue(wait_for(
            lambda: service.quota.depth() == 0
            and service.status()['store']['sends'] >= len(threads), timeout=20.0))
        self.assertEqual(service.counters().get('queue_full'), None)


# ---------------------------------------------------------------- 默认适配器
class DefaultAdapterTests(unittest.TestCase):
    """契约第 7 节的调用形态 vs src 真实签名：适配器必须只传真实签名认得的参数。

    这几条特别值得钉住：契约写的是 StepPlan(cfg, db, state_dir=...) 与
    generate(prompt, state_dir=..., credentials_file=...)，而 src 那边是**会演进**的。
    适配器一旦写成"多传参数 → 抛 TypeError 再退回"，生图就会白发一次请求（花钱）。
    """

    def test_invoke_adapts_to_factory_arity(self):
        def zero():
            return 'zero'

        def two(cfg, db):
            return (cfg, db)

        def var(*args):
            return args

        self.assertEqual(service_module._invoke(zero, 1, 2, 3), 'zero')
        self.assertEqual(service_module._invoke(two, 'c', 'd', 'e'), ('c', 'd'))
        self.assertEqual(service_module._invoke(var, 1, 2, 3), (1, 2, 3))

    def test_default_image_generator_forwards_state_dir_and_credentials(self):
        import imagegen
        calls = []

        def fake_generate(prompt, **kwargs):
            calls.append((prompt, kwargs))
            return 'gen.png'

        with mock.patch.object(imagegen, 'generate', fake_generate):
            factory = service_module._default_image_generator_factory(
                {'image_generation': {'credentials_file': '/tmp/cred.json'}},
                Path('/tmp/qq-state'))
            self.assertEqual(factory('画一只年糕'), 'gen.png')
        self.assertEqual(len(calls), 1, '生图适配器只能发一次请求，不能靠抛异常重试')
        prompt, kwargs = calls[0]
        self.assertEqual(prompt, '画一只年糕')
        self.assertEqual(kwargs['state_dir'], Path('/tmp/qq-state'))
        self.assertEqual(kwargs['credentials_file'], '/tmp/cred.json')
        self.assertIn('ref_image', kwargs, '要带上 OC 参考图')
        self.assertNotIn('provider', kwargs)

    def test_default_image_generator_survives_old_signature(self):
        """src/imagegen 退回旧签名（只有 prompt/ref_image）时也得能用。"""
        import imagegen
        calls = []

        def old_generate(prompt, base=None, model=None, ref_image=None):
            calls.append(prompt)
            return 'old.png'

        with mock.patch.object(imagegen, 'generate', old_generate):
            factory = service_module._default_image_generator_factory({}, Path('/tmp/x'))
            self.assertEqual(factory('画猫'), 'old.png')
        self.assertEqual(calls, ['画猫'])

    def test_default_model_factory_forwards_state_dir(self):
        import multimodal
        calls = []

        class FakeStepPlan:
            def __init__(self, cfg, db=None, state_dir=None):
                calls.append((cfg, db, state_dir))

        with mock.patch.object(multimodal, 'StepPlan', FakeStepPlan):
            service_module._default_model_factory({'cfg': 1}, 'DB', Path('/tmp/qq-state'))
        self.assertEqual(calls, [({'cfg': 1}, 'DB', Path('/tmp/qq-state'))])

    def test_default_model_factory_survives_old_signature(self):
        import multimodal
        calls = []

        class OldStepPlan:
            def __init__(self, cfg, db=None):
                calls.append((cfg, db))

        with mock.patch.object(multimodal, 'StepPlan', OldStepPlan):
            service_module._default_model_factory({}, None, Path('/tmp/x'))
        self.assertEqual(calls, [({}, None)])

    def test_default_image_generator_reads_block_only_when_dict(self):
        import imagegen
        seen = {}

        def fake_generate(prompt, **kwargs):
            seen.update(kwargs)
            return 'x.png'

        with mock.patch.object(imagegen, 'generate', fake_generate):
            factory = service_module._default_image_generator_factory(
                {'image_generation': '这不是字典'}, Path('/tmp/x'))
            factory('画猫')
        self.assertEqual(seen['state_dir'], Path('/tmp/x'))


# ---------------------------------------------------------------- config（契约 §9）
class ConfigTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix='qq-config-'))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.warns = []

    def warn(self, message):
        self.warns.append(str(message))

    def write_cfg(self, data, name='qq.json'):
        path = self.tmp / name
        path.write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')
        return path

    def loaded(self, data, **kw):
        kw.setdefault('warn', self.warn)
        return config_module.load_config(self.write_cfg(data), **kw)

    # ---------- load_config ----------
    def test_missing_file_raises(self):
        with self.assertRaises(config_module.QQConfigError):
            config_module.load_config(self.tmp / '没有这个文件.json')

    def test_broken_json_raises(self):
        path = self.tmp / 'bad.json'
        path.write_text('{不是 JSON', encoding='utf-8')
        with self.assertRaises(config_module.QQConfigError):
            config_module.load_config(path)

    def test_non_object_top_level_raises(self):
        with self.assertRaises(config_module.QQConfigError):
            self.loaded([1, 2, 3])

    def test_frozen_example_shape_loads_without_warning(self):
        """拿队友的 qq.example.json 原样跑一遍：它是 §9 冻结 schema 的样本。"""
        example = ROOT / 'qq' / 'config' / 'qq.example.json'
        if not example.is_file():
            self.skipTest('还没有 qq/config/qq.example.json')
        cfg = config_module.load_config(example, warn=self.warn)
        self.assertEqual(cfg['direct_policy'], 'blacklist')
        self.assertEqual(cfg['groups'], {})
        self.assertFalse(cfg['auto_send'])
        self.assertEqual(cfg['max_pending'], 200)
        self.assertEqual(cfg['task_ttl_seconds'], 600)
        self.assertEqual(cfg['media']['max_images'], 2)
        self.assertFalse(cfg['image_generation']['enabled'])
        self.assertIn('onebot', cfg)
        self.assertEqual([w for w in self.warns if '未知配置字段' in w], [],
                         '示例文件里不该有未知字段：%r' % (self.warns[:3],))

    def test_prepare_dir_false_does_not_touch_state_dir(self):
        cfg = self.loaded({'state_dir': str(self.tmp / '不该被创建')})
        self.assertFalse(Path(cfg['state_dir']).exists())

    # ---------- §9.5 未知字段 ----------
    def test_unknown_key_warns_but_does_not_crash(self):
        cfg = self.loaded({'state_dir': str(self.tmp), 'wat': 1})
        self.assertEqual(cfg['wat'], 1)
        self.assertTrue(any('未知配置字段' in w for w in self.warns), self.warns)

    def test_underscore_keys_are_comments_and_stay_silent(self):
        cfg = self.loaded({'state_dir': str(self.tmp), '_说明': '注释', '_更多': {}})
        self.assertFalse([w for w in self.warns if '未知配置字段' in w], self.warns)
        self.assertEqual(cfg['_说明'], '注释')

    # ---------- §9.1 token ----------
    def test_token_from_env_wins(self):
        cfg = config_module.normalize({'onebot': {'token': '文件里的',
                                                 'token_env': 'MY_TOKEN'}})
        self.assertEqual(config_module.resolve_token(cfg, {'MY_TOKEN': '环境里的'}),
                         '环境里的')

    def test_token_falls_back_to_config_file(self):
        cfg = config_module.normalize({'onebot': {'token': '文件里的'}})
        self.assertEqual(config_module.resolve_token(cfg, {}), '文件里的')

    def test_token_missing_raises(self):
        cfg = config_module.normalize({'onebot': {'token': ''}})
        with self.assertRaises(config_module.QQConfigError):
            config_module.resolve_token(cfg, {})

    def test_token_env_name_defaults(self):
        cfg = config_module.normalize({})
        self.assertEqual(cfg['onebot']['token_env'],
                         config_module.DEFAULT_TOKEN_ENV)
        self.assertEqual(
            config_module.resolve_token(cfg, {config_module.DEFAULT_TOKEN_ENV: 'x'}),
            'x')

    def test_load_config_require_token_flag(self):
        with self.assertRaises(config_module.QQConfigError):
            self.loaded({'onebot': {'token': ''}}, require_token=True, env={})
        cfg = self.loaded({'onebot': {'token': 'ok'}}, require_token=True, env={})
        self.assertEqual(cfg['onebot']['token'], 'ok')

    # ---------- §9.2 groups ----------
    def test_groups_must_be_dict(self):
        with self.assertRaises(config_module.QQConfigError):
            self.loaded({'groups': ['123']})

    def test_empty_groups_is_legal(self):
        self.assertEqual(self.loaded({'groups': {}})['groups'], {})

    def test_non_numeric_group_key_is_dropped_with_warning(self):
        cfg = self.loaded({'groups': {'123': {'plain_mode': 'idle'},
                                      '某某群': {'plain_mode': 'idle'}}})
        self.assertEqual(list(cfg['groups']), ['123'])
        self.assertTrue(any('不是数字群号' in w for w in self.warns), self.warns)

    def test_bad_group_entry_is_dropped(self):
        cfg = self.loaded({'groups': {'123': 'idle'}})
        self.assertEqual(cfg['groups'], {})
        self.assertTrue(any('必须是对象' in w for w in self.warns), self.warns)

    def test_unknown_plain_mode_warns_but_keeps_value(self):
        cfg = self.loaded({'groups': {'123': {'plain_mode': '随便'}}})
        self.assertEqual(cfg['groups']['123']['plain_mode'], '随便')
        self.assertTrue(any('plain_mode' in w for w in self.warns), self.warns)

    def test_uppercase_plain_mode_is_legal_and_lowercased(self):
        """契约 §10：plain_mode 先 strip().lower() 再判合法性。

        以前 config 会 warn 说"按最保守的 at_only 处理"，而 policy 自己 lower()
        后当 all 用——告警与行为相反，最坑人。
        """
        cfg = self.loaded({'groups': {'123': {'plain_mode': '  ALL  '}}})
        self.assertEqual(cfg['groups']['123']['plain_mode'], 'all')
        self.assertFalse([w for w in self.warns if 'plain_mode' in w], self.warns)

    # ---------- §9.3 direct_policy ----------
    def test_bad_direct_policy_becomes_blacklist(self):
        cfg = self.loaded({'direct_policy': '都对'})
        self.assertEqual(cfg['direct_policy'], 'blacklist')
        self.assertTrue(any('direct_policy' in w for w in self.warns), self.warns)

    def test_whitelist_is_accepted(self):
        self.assertEqual(self.loaded({'direct_policy': 'WHITELIST'})['direct_policy'],
                         'whitelist')

    def test_bad_name_list_becomes_empty(self):
        cfg = self.loaded({'direct_blacklist': '123'})
        self.assertEqual(cfg['direct_blacklist'], [])

    # ---------- §9.4 state_dir ----------
    def test_state_dir_expanduser(self):
        cfg = config_module.normalize({'state_dir': '~/qq-测试目录'})
        self.assertEqual(cfg['state_dir'], str(Path.home() / 'qq-测试目录'))

    def test_prepare_state_dir_creates_with_700(self):
        target = self.tmp / '深层' / 'state'
        cfg = {'state_dir': str(target)}
        path = config_module.prepare_state_dir(cfg)
        self.assertTrue(path.is_dir())
        self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o700)

    def test_defaults_are_filled(self):
        cfg = config_module.normalize({})
        self.assertEqual(cfg['min_reply_seconds'], 3)
        self.assertEqual(cfg['max_replies_per_hour'], 30)
        self.assertEqual(cfg['reply_max_chars'], 200)
        self.assertEqual(cfg['limits'], {'window_5h': 100, 'window_1d': 500})
        self.assertEqual(cfg['media']['keep_days'], 14)

    def test_bad_type_falls_back_to_default_with_warning(self):
        cfg = config_module.normalize({'min_reply_seconds': '三秒', 'auto_send': 'yes'},
                                     warn=self.warn)
        self.assertEqual(cfg['min_reply_seconds'], 3)
        self.assertFalse(cfg['auto_send'])
        self.assertEqual(len(self.warns), 2, self.warns)

    def test_links_defaults_match_the_contract(self):
        """契约 §9 的 links 段默认值必须逐字一致——链接阅读的预算全靠它兜底。"""
        cfg = config_module.normalize({})
        self.assertEqual(cfg['links'], {'enabled': True, 'max_urls': 2,
                                        'max_bytes': 250000, 'max_chars': 9000,
                                        'timeout': 10, 'total_budget_seconds': 12})

    def test_hot_feed_defaults_to_disabled(self):
        """契约 §10 裁定 hot_feed 默认 false（要走网络的东西不许悄悄开）。"""
        self.assertFalse(config_module.normalize({})['hot_feed']['enabled'])
        self.assertFalse(
            config_module.normalize({'hot_feed': {'refresh_seconds': 60}}
                                    )['hot_feed']['enabled'],
            '只写了 refresh_seconds 也要关着')
        self.assertTrue(config_module.normalize(
            {'hot_feed': {'enabled': True}})['hot_feed']['enabled'])

    def test_hot_feed_absent_means_disabled(self):
        self.assertFalse(config_module.normalize({})['hot_feed']['enabled'])

    def test_hot_feed_explicit_value_is_kept(self):
        cfg = config_module.normalize({'hot_feed': {'enabled': True,
                                                    'refresh_seconds': 60}})
        self.assertTrue(cfg['hot_feed']['enabled'])
        self.assertEqual(cfg['hot_feed']['refresh_seconds'], 60)

    def test_max_queue_alias_maps_to_max_pending(self):
        self.assertEqual(config_module.normalize({'max_queue': 7})['max_pending'], 7)

    def test_normalize_does_not_mutate_input(self):
        original = {'groups': {'123': {'plain_mode': 'idle'}}, 'wat': 1}
        config_module.normalize(original, warn=self.warn)
        self.assertEqual(original, {'groups': {'123': {'plain_mode': 'idle'}},
                                    'wat': 1})

    # ---------- self_id ----------
    def test_self_id_roundtrip(self):
        cfg = {'state_dir': str(self.tmp)}
        self.assertEqual(config_module.resolve_self_id(cfg), '')
        path = config_module.write_self_id(self.tmp, '10001')
        self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
        self.assertEqual(config_module.resolve_self_id(cfg), '10001')
        self.assertEqual(config_module.resolve_self_id({'self_id': 20002,
                                                        'state_dir': str(self.tmp)}),
                         '20002')


# ---------------------------------------------------------------- 契约 §9 落到服务上
class AutoSendGateTests(ServiceTestCase):
    def test_auto_send_off_records_but_never_sends(self):
        cfg = base_cfg(self.tmp, auto_send=False)
        service, sender, model = self.build(cfg=cfg)
        self.start(service)
        event = onebot_event(text='在吗')
        self.assertTrue(service.submit(event))
        self.assertTrue(wait_for(
            lambda: queue_state(service, event.chat_key) == 'AUTO_SEND_OFF'))
        self.assertEqual(sender.texts, [])
        self.assertFalse(model.calls, '不发就不该花模型额度')
        self.assertEqual(len(timeline_of(service, event.chat_key)), 1, '消息照记时间线')
        self.assertFalse(service.status()['auto_send'])

    def test_task_ttl_expires_stale_queue_items(self):
        cfg = base_cfg(self.tmp, task_ttl_seconds=0.05)
        service, sender, model = self.build(cfg=cfg)
        event = onebot_event(text='深夜的消息')
        self.assertTrue(service.submit(event))          # 故意先不启 worker
        time.sleep(0.2)
        self.start(service)
        self.assertTrue(wait_for(
            lambda: queue_state(service, event.chat_key) == 'EXPIRED'))
        self.assertEqual(sender.texts, [])

    def test_media_prune_removes_only_expired_files(self):
        service, sender, model = self.build(
            cfg=base_cfg(self.tmp, media={'keep_days': 1}))
        old = service.media_dir / 'old.png'
        fresh = service.media_dir / 'fresh.png'
        old.write_bytes(png_bytes())
        fresh.write_bytes(png_bytes())
        stale = time.time() - 3 * 24 * 3600
        os.utime(old, (stale, stale))
        self.assertEqual(service._maybe_prune_media(), 1)
        self.assertFalse(old.exists())
        self.assertTrue(fresh.exists())
        self.assertEqual(service._maybe_prune_media(), 0, '一小时内不该重复扫')

    def test_media_keep_days_zero_disables_pruning(self):
        service, sender, model = self.build(
            cfg=base_cfg(self.tmp, media={'keep_days': 0}))
        old = service.media_dir / 'old.png'
        old.write_bytes(png_bytes())
        stale = time.time() - 30 * 24 * 3600
        os.utime(old, (stale, stale))
        self.assertEqual(service._maybe_prune_media(), 0)
        self.assertTrue(old.exists())

    def test_hot_round_refreshes_one_source_and_rotates(self):
        """一轮只刷一个源，且挑最久没刷过的那个（微信侧 hot_cycle 同一套做法）。"""
        service, sender, model = self.build()
        calls = []

        class FakeFeed:
            def refresh(self, only_source=None, force=False):
                calls.append(only_source)
                service.db.execute('INSERT OR REPLACE INTO hot_meta(source,fetched)'
                                   ' VALUES(?,?)', (only_source, time.time()))
                service.db.commit()
                return 1

            def relevant(self, query, limit=6):
                return []

        service.feed = FakeFeed()
        sources = [str(item[0]) for item in service_module.HOT_SOURCES]
        self.assertGreaterEqual(len(sources), 2, 'src/search.py 的 ROUTES 至少两个源')
        self.assertEqual(service._hot_round(), 1)
        self.assertEqual(service._hot_round(), 1)
        self.assertEqual(len(calls), 2)
        self.assertIn(calls[0], sources)
        self.assertNotEqual(calls[0], calls[1], '两轮该刷两个不同的源（轮转）')

    def test_hot_thread_not_started_when_disabled(self):
        service, sender, model = self.build(
            cfg=base_cfg(self.tmp, hot_feed={'enabled': False}),
            hot_refresh=lambda: 1)
        self.start(service)
        self.assertFalse(service._hot_enabled())
        self.assertIsNone(service._hot_thread, '关着就不该起热榜线程')

    def test_hot_thread_runs_when_enabled(self):
        service, sender, model = self.build(
            cfg=base_cfg(self.tmp, hot_feed={'enabled': True,
                                             'refresh_seconds': 30}),
            hot_refresh=lambda: 1)
        with mock.patch.object(service_module, 'DEFAULT_HOT_INITIAL_DELAY_S', 0.05):
            self.start(service)
            self.assertIsNotNone(service._hot_thread)
            self.assertTrue(wait_for(lambda: service.hot_heartbeat > 0, timeout=5.0))
            self.assertLess(service.hot_heartbeat, time.time() + 1)

    def test_hot_failure_is_contained_in_its_own_thread(self):
        def broken():
            raise RuntimeError('RSSHub 挂了')

        service, sender, model = self.build(
            cfg=base_cfg(self.tmp, hot_feed={'enabled': True,
                                             'refresh_seconds': 30}),
            hot_refresh=broken)
        with mock.patch.object(service_module, 'DEFAULT_HOT_INITIAL_DELAY_S', 0.05):
            self.start(service)
            self.assertTrue(wait_for(lambda: service.hot_heartbeat > 0, timeout=5.0))
            self.assertTrue(service._hot_thread.is_alive(), '一轮失败不该把线程弄死')
            self.assertTrue(service.submit(onebot_event(text='热榜挂了也要能回')))
            self.assertTrue(wait_for(lambda: len(sender.texts) == 1, timeout=5.0))

    def test_blocking_hot_refresh_does_not_block_worker_or_heartbeat(self):
        """回归用例（2026-10-18 真机事故）：热榜刷新卡死时，回复链与心跳必须照常。

        当时 feed.refresh() 撞上公共 RSSHub 实例限流，跑在 owner 线程里，
        结果整条回复链连 status.json 一起被卡死好几分钟（health 报 status_file=false）。
        """
        release = threading.Event()
        entered = []

        def blocking():
            entered.append(1)
            release.wait(30)                    # 模拟网络挂住：一直不返回
            return 0

        cfg = base_cfg(self.tmp, hot_feed={'enabled': True, 'refresh_seconds': 30},
                       status_interval_s=1.0)
        service, sender, model = self.build(cfg=cfg, hot_refresh=blocking)
        self.addCleanup(release.set)
        with mock.patch.object(service_module, 'DEFAULT_HOT_INITIAL_DELAY_S', 0.05):
            self.start(service)
            self.assertTrue(wait_for(lambda: entered, timeout=5.0), '热榜线程该开始刷了')
            stamp = service.status_path.stat().st_mtime_ns
            self.assertTrue(wait_for(
                lambda: service.status_path.stat().st_mtime_ns != stamp, timeout=5.0),
                '热榜卡住时 status.json 也必须继续被写')
            event = onebot_event(text='热榜卡住也要能回')
            self.assertTrue(service.submit(event))
            self.assertTrue(wait_for(lambda: len(sender.texts) == 1, timeout=6.0),
                            '热榜卡住时消息仍要被处理')
            self.assertLess(time.time() - service.heartbeat, 5.0,
                            '心跳不该落后 5 秒以上')

    def test_heartbeat_survives_a_slow_model_call(self):
        """owner 线程在跑模型时回不到循环顶部：心跳必须由独立线程维持。"""
        started = threading.Event()
        release = threading.Event()

        def slow_reply(fresh):
            started.set()
            release.wait(10)
            return '慢回复'

        service, sender, model = self.build(
            model=FakeModel(slow_reply),
            cfg=base_cfg(self.tmp, status_interval_s=1.0))
        self.addCleanup(release.set)
        self.start(service)
        self.assertTrue(service.submit(onebot_event(text='在吗')))
        self.assertTrue(started.wait(5.0))
        stamp = service.status_path.stat().st_mtime_ns
        self.assertTrue(wait_for(
            lambda: service.status_path.stat().st_mtime_ns != stamp, timeout=5.0),
            '模型调用期间心跳不能停')
        release.set()
        self.assertTrue(wait_for(lambda: len(sender.texts) == 1, timeout=6.0))

    def test_status_timestamps_follow_events_and_sends(self):
        """契约 §7 的 last_event_at / last_send_ok_at 要真的动起来。"""
        service, sender, model = self.build()
        self.assertEqual(service.status()['last_event_at'], 0.0)
        # 被策略拒掉的事件也算"收到过"：否则 groups 空配置时永远是 0，排查时看不出
        self.assertFalse(service.submit(onebot_event(chat_type='group',
                                                     chat_id='88888')))
        self.assertGreater(service.status()['last_event_at'], 0.0)
        self.assertEqual(service.status()['last_accepted_at'], 0.0)
        self.start(service)
        self.assertTrue(service.submit(onebot_event(message_id='ok-1', text='在吗')))
        self.assertGreater(service.status()['last_accepted_at'], 0.0)
        self.assertTrue(wait_for(lambda: len(sender.texts) == 1))
        self.assertGreater(service.status()['last_send_ok_at'], 0.0)

    def test_image_generation_off_by_default(self):
        calls = []
        cfg = base_cfg(self.tmp)
        cfg['image_generation'] = {'enabled': False, 'max_per_hour': 3}
        service, sender, model = self.build(
            cfg=cfg, model=FakeModel('好，画一张'),
            image_generator=lambda prompt: calls.append(prompt))
        self.start(service)
        self.assertTrue(service.submit(onebot_event(text='帮我画一张图')))
        self.assertTrue(wait_for(lambda: len(sender.texts) == 1))
        time.sleep(0.2)
        self.assertEqual(calls, [], '契约 §9 默认关着生图，命中关键词也不能画')
        self.assertEqual(sender.images, [])

    def test_self_id_binding_is_persisted(self):
        """配置里没写 self_id：登录后绑定要落盘（契约 §9 的 self_id.txt）。"""
        service, sender, model = self.build()
        self.assertEqual(service.self_id(), TEST_SELF_ID)
        self.assertEqual(service.bind_self_id('30003'), '30003')
        self.assertTrue((service.state_dir / 'self_id.txt').is_file())
        self.assertEqual(config_module.read_self_id(service.state_dir), '30003')

    def test_self_id_from_config_is_not_overwritten(self):
        service, sender, model = self.build(cfg=base_cfg(self.tmp, self_id='20002'))
        self.assertEqual(service.bind_self_id('99999'), '',
                         '配置里写了 self_id 就不该被登录结果覆盖')
        self.assertFalse((service.state_dir / 'self_id.txt').exists())

    def test_self_id_falls_back_to_bound_file(self):
        sender = FakeSender()
        service, _, _ = self.build(sender=sender)
        config_module.write_self_id(service.state_dir, '30003')
        sender._self_id = ''
        self.assertEqual(service.self_id(), '30003')


# ---------------------------------------------------------------- 契约 §7.1 A：链接阅读
class LinkReadTests(ServiceTestCase):
    def fetcher(self, results, calls=None):
        """替身 fetcher：按 URL 给结果，可抛异常。"""
        def fetch(url, block):
            if calls is not None:
                calls.append({'url': url, 'block': dict(block)})
            item = results.get(url)
            if isinstance(item, Exception):
                raise item
            return item
        return fetch

    def test_sources_are_passed_to_model(self):
        calls = []
        good = {'url': 'https://example.com/a', 'status': 'read',
                'untrusted_text': '网页正文'}
        service, sender, model = self.build(
            model=FakeModel('看了'),
            link_fetcher=self.fetcher({'https://example.com/a': good}, calls))
        self.start(service)
        self.assertTrue(service.submit(onebot_event(
            text='看这个 https://example.com/a 挺有意思')))
        self.assertTrue(wait_for(lambda: len(sender.texts) == 1))
        self.assertEqual(len(calls), 1)
        self.assertEqual(model.calls[0]['sources'], [good],
                         '读到的网页要作为 web_sources 交给模型')

    def test_link_failure_still_replies(self):
        """读到一半失败/超时：只留一个状态条目，文字回复照发。"""
        service, sender, model = self.build(
            model=FakeModel('读不到也回'),
            link_fetcher=self.fetcher({
                'https://a.example/1': TimeoutError('读超时'),
                'https://a.example/2': {'url': 'https://a.example/2',
                                        'status': 'read', 'untrusted_text': '第二篇'}}))
        self.start(service)
        self.assertTrue(service.submit(onebot_event(
            text='https://a.example/1 和 https://a.example/2')))
        self.assertTrue(wait_for(lambda: len(sender.texts) == 1))
        sources = model.calls[0]['sources']
        self.assertEqual(sources[0], {'url': 'https://a.example/1',
                                      'status': 'unreadable',
                                      'reason': 'TimeoutError'})
        self.assertEqual(sources[1]['status'], 'read')

    def test_private_link_is_rejected_without_network(self):
        """私网/本机地址由 web_reader 直接挡掉（这里用的是**真实**那条链路）。"""
        service, sender, model = self.build()
        sources = service.gather_sources([{'text': '看看 http://127.0.0.1:8080/secret'}])
        self.assertEqual(len(sources), 1)
        self.assertEqual(sources[0]['status'], 'unreadable')
        self.assertNotIn('untrusted_text', sources[0])

    def test_links_disabled_returns_empty_and_never_fetches(self):
        calls = []
        service, sender, model = self.build(
            cfg=base_cfg(self.tmp, links={'enabled': False}),
            link_fetcher=self.fetcher({}, calls))
        self.assertEqual(service.gather_sources([{'text': 'https://a.example/x'}]), [])
        self.assertEqual(calls, [])

    def test_max_urls_caps_the_batch(self):
        calls = []
        service, sender, model = self.build(
            cfg=base_cfg(self.tmp, links={'enabled': True, 'max_urls': 1}),
            link_fetcher=self.fetcher({}, calls))
        service.gather_sources([{'text': 'https://a.example/1 https://a.example/2'}])
        self.assertEqual([c['url'] for c in calls], ['https://a.example/1'])

    def test_budget_exhausted_marks_skipped(self):
        calls = []

        def slow(url, block):
            calls.append(url)
            time.sleep(0.05)
            return {'url': url, 'status': 'read', 'untrusted_text': 'x'}

        service, sender, model = self.build(
            cfg=base_cfg(self.tmp, links={'enabled': True, 'max_urls': 2,
                                          'total_budget_seconds': 0.01}),
            link_fetcher=slow)
        sources = service.gather_sources(
            [{'text': 'https://a.example/1 https://a.example/2'}])
        self.assertEqual(calls, ['https://a.example/1'], '预算用完后不该再抓')
        self.assertEqual(sources[-1]['status'], 'skipped_budget')

    def test_per_url_timeout_is_capped_by_remaining_budget(self):
        seen = []
        service, sender, model = self.build(
            cfg=base_cfg(self.tmp, links={'enabled': True, 'timeout': 30,
                                          'total_budget_seconds': 5}),
            link_fetcher=self.fetcher({}, None) if False else
            (lambda url, block: seen.append(block['timeout']) or None))
        service.gather_sources([{'text': 'https://a.example/1'}])
        self.assertLessEqual(seen[0], 5, '单条 URL 的超时不能超过总预算')

    def test_no_link_means_no_fetch(self):
        calls = []
        service, sender, model = self.build(link_fetcher=self.fetcher({}, calls))
        self.assertEqual(service.gather_sources([{'text': '今天天气不错'}]), [])
        self.assertEqual(calls, [])

    def test_extract_urls_dedupes_and_strips_punctuation(self):
        urls = service_module.extract_urls([
            {'text': '看 https://a.example/1，还有 https://a.example/1 和 https://b.example/2。'},
            {'text': '再来 https://c.example/3'}])
        self.assertEqual(urls, ['https://a.example/1', 'https://b.example/2',
                                'https://c.example/3'])
        self.assertEqual(service_module.extract_urls(
            [{'text': 'https://a/1 https://a/2'}], limit=1), ['https://a/1'])


# ---------------------------------------------------------------- 契约 §7.1 B：风格自学习
class LearnCycleTests(ServiceTestCase):
    CHAT = 'qq:%s:private:%s' % (TEST_SELF_ID, FRIEND_ID)
    OTHER = 'qq:%s:private:60006' % TEST_SELF_ID

    def seed_pending(self, service, chat_key, count=None):
        service.memory.note_messages(chat_key, count or 20, 'private', '朋友')
        for i in range(count or 20):
            service.memory.record_turn(chat_key, 'user', '第 %d 句样本' % i)

    def test_learn_cycle_writes_only_that_chat(self):
        service, sender, model = self.build()
        self.seed_pending(service, self.CHAT)
        service.memory.note_messages(self.OTHER, 1, 'private', '别人')
        self.assertTrue(service._worker.learn_cycle())
        self.assertEqual(model.call_count, 1)
        learned = service.memory.context_for(self.CHAT)
        self.assertEqual(learned['style'], '简洁直接')
        self.assertEqual(learned['facts'], ['喜欢宝可梦'])
        untouched = service.memory.context_for(self.OTHER)
        self.assertEqual(untouched['style'], '')
        self.assertEqual(untouched['facts'], [],
                         '学到的风格与事实只能进该 chat_key 的档案')

    def test_learn_consumes_one_quota_unit(self):
        service, sender, model = self.build()
        self.seed_pending(service, self.CHAT)
        before = service.quota.status()['used_5h']
        self.assertTrue(service._worker.learn_cycle())
        self.assertEqual(service.quota.status()['used_5h'], before + 1)
        row = service.db.execute('SELECT priority FROM usage ORDER BY id DESC LIMIT 1'
                                 ).fetchone()
        self.assertEqual(row[0], PRIORITY_GROUP_PLAIN)

    def test_learn_below_threshold_does_nothing(self):
        service, sender, model = self.build()
        self.seed_pending(service, self.CHAT, count=5)
        self.assertFalse(service._worker.learn_cycle())
        self.assertEqual(model.call_count, 0)

    def test_success_cools_down_for_an_hour(self):
        service, sender, model = self.build()
        self.seed_pending(service, self.CHAT)
        self.assertTrue(service._worker.learn_cycle())
        service._worker._learn_scan_at = 0.0        # 绕开"60 秒扫一次"的节流
        self.seed_pending(service, self.CHAT)       # 又攒了 20 条
        self.assertFalse(service._worker.learn_cycle())
        self.assertEqual(model.call_count, 1, '一小时内不该再学一次')
        self.assertGreater(service._worker._learn_after[self.CHAT], time.time())

    def test_scan_is_throttled_to_once_a_minute(self):
        service, sender, model = self.build()
        self.seed_pending(service, self.CHAT)
        self.assertTrue(service._worker.learn_cycle())
        self.seed_pending(service, self.CHAT)       # 又攒了 20 条
        self.assertFalse(service._worker.learn_cycle(), '60 秒内不该重复扫')
        self.assertEqual(model.call_count, 1)

    def test_failure_backs_off_exponentially(self):
        service, sender, model = self.build()
        model.call_error = RuntimeError('模型挂了')
        self.seed_pending(service, self.CHAT)
        self.assertFalse(service._worker.learn_cycle())
        self.assertEqual(service._worker._learn_fails[self.CHAT], 1)
        self.assertGreater(service._worker._learn_after[self.CHAT], time.time())

    def test_backoff_sequence_is_capped_at_24h(self):
        backoff = service_module.Worker._learn_backoff
        self.assertEqual([backoff(n) / 3600 for n in (1, 2, 3, 4, 5)],
                         [1.0, 2.0, 4.0, 8.0, 16.0])
        self.assertEqual(backoff(6) / 3600, 24.0)
        self.assertEqual(backoff(50) / 3600, 24.0)
        self.assertEqual(backoff('坏值') / 3600, 1.0)

    def test_learn_only_runs_when_queue_is_idle(self):
        service, sender, model = self.build()
        self.seed_pending(service, self.CHAT)
        calls = []
        real = service._worker.learn_cycle
        service._worker.learn_cycle = lambda: calls.append(1) or real()
        service.quota.enqueue('qq:%s:private:70007' % TEST_SELF_ID,
                              PRIORITY_DIRECT, '{}')
        service._loop_once()                        # 进来时队列是忙的 → 不学
        self.assertEqual(calls, [])
        service._loop_once()                        # 队列空了 → 该学了
        self.assertEqual(calls, [1])

    def test_learn_runs_automatically_when_idle(self):
        service, sender, model = self.build()
        self.seed_pending(service, self.CHAT)
        self.start(service)
        self.assertTrue(wait_for(
            lambda: service.memory.context_for(self.CHAT)['style'] != '', timeout=6.0),
            '队列空闲时应该自动学一次')
        self.assertEqual(model.call_count, 1)


if __name__ == '__main__':
    unittest.main(verbosity=2)

