"""诊断 2：完全照抄 v4_service.py 的 build()/step() 路径，复现"生成后写 STOP"。"""
import sys, tempfile, time, logging
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / 'src'))
from qq.core.envelope import QEvent
from qq.core.bridge import SendResult, Sender
from qq.core.service import QQService
logging.basicConfig(level=logging.INFO, format='%(levelname)s %(message)s')

SELF, GROUP = '10001', '30003'


class FakeSender(Sender):
    def __init__(self):
        self.texts = []
    def send_text(self, e, t):
        print('>>> send_text：%r' % t)
        self.texts.append((e.chat_key, t))
        return SendResult(ok=True, unknown=False, message_id='m1')
    def send_image(self, e, p):
        return SendResult(ok=True, unknown=False, message_id='m1')
    def self_id(self):
        return SELF
    def online(self):
        return True


class FakeModel:
    def __init__(self, reply='好的'):
        self.reply_text = reply
        self.call_count = 0
    def session_for(self, k):
        return None
    def reply(self, fresh, recent, sources, **kw):
        self.call_count += 1
        return self.reply_text


def base_cfg(tmp):
    return {'state_dir': str(tmp), 'auto_send': True, 'self_id': SELF,
            'groups': {GROUP: {'plain_mode': 'at_only'}}, 'mention_aliases': ['年糕'],
            'direct_policy': 'blacklist', 'direct_blacklist': [],
            'min_reply_seconds': 0, 'max_replies_per_hour': 30, 'max_pending': 200,
            'task_ttl_seconds': 600, 'event_max_age_s': 300, 'poll_interval_s': 0.01,
            'status_interval_s': 0.05, 'reply_max_chars': 200,
            'limits': {'window_5h': 100, 'window_1d': 500},
            'media': {'max_bytes': 1 << 20, 'timeout_s': 5, 'max_images': 2,
                      'keep_days': 14},
            'image_generation': {'enabled': False, 'max_per_hour': 3},
            'model': {'enabled': True}, 'web_search': {'enabled': False},
            'links': {'enabled': False}, 'hot_feed': {'enabled': False}}


def build():
    tmp = Path(tempfile.mkdtemp(prefix='probe2-'))
    sender, model = FakeSender(), FakeModel()

    def model_factory(cfg, db, state_dir):
        return model

    svc = QQService(base_cfg(tmp), ROOT, sender, db_path=str(tmp / 'qq.db'),
                    model_factory=model_factory,
                    searcher=lambda cfg, db: None,
                    image_generator=lambda cfg, sd: (lambda p: None),
                    fetcher=lambda url, dest, **kw: None,
                    link_fetcher=lambda u, b: None)
    return svc, sender, model


def ev(text='', at_me=False, message_id=None):
    return QEvent(self_id=SELF, chat_type='group', chat_id=GROUP, sender_id='20002',
                  sender_name='某人', message_id=message_id or str(time.time_ns()),
                  time=time.time(), at_me=at_me, at_all=False, text=text,
                  images=[], segments=[], raw={})


service, sender, model = build()
print('stop_path =', service.stop_path)


def stopping_reply(*a, **kw):
    print('>>> 生成中：即将写 STOP 到 %s' % service.stop_path)
    service.stop_path.write_text('')
    print('>>> 写完：exists=%s any_stop=%s' % (service.stop_path.exists(),
                                              service.any_stop()))
    return '生成好了但已被叫停'


model.reply = stopping_reply
service.submit(ev(text='在吗', at_me=True, message_id='S-2'))
print('submit 后 exists=%s' % service.stop_path.exists())
for i in (1, 2):
    service._loop_once()
    print('第 %d 次 _loop_once 后：texts=%r state=%s'
          % (i, sender.texts,
             service.db.execute('SELECT state FROM queue ORDER BY id DESC LIMIT 1').fetchone()))
