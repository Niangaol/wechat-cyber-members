"""诊断：生成期间写 STOP 后，发送前那道检查到底看没看到文件。"""
import sys, tempfile, time, logging
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / 'src'))
from qq.core.envelope import QEvent
from qq.core.bridge import SendResult, Sender
from qq.core.service import QQService
logging.basicConfig(level=logging.INFO, format='%(levelname)s %(message)s')

SELF, GROUP = '10001', '30003'
tmp = Path(tempfile.mkdtemp(prefix='probe-stop-'))


class S(Sender):
    def __init__(self):
        self.texts = []
    def send_text(self, e, t):
        print('>>> send_text 被调用，text=%r' % t)
        self.texts.append(t)
        return SendResult(True, False)
    def send_image(self, e, p):
        return SendResult(True, False)
    def self_id(self):
        return SELF
    def online(self):
        return True


class M:
    def __init__(self, svc):
        self.svc = svc
        self.n = 0
    def session_for(self, k):
        return None
    def reply(self, *a, **kw):
        self.n += 1
        print('>>> 模型开始生成，此刻 stop_path=%s exists=%s'
              % (self.svc.stop_path, self.svc.stop_path.exists()))
        self.svc.stop_path.write_text('')
        print('>>> 写完 STOP，exists=%s；any_stop()=%s'
              % (self.svc.stop_path.exists(), self.svc.any_stop()))
        return '生成好了但已被叫停'


sender = S()
svc = QQService({'state_dir': str(tmp), 'auto_send': True, 'self_id': SELF,
                 'groups': {GROUP: {'plain_mode': 'at_only'}},
                 'min_reply_seconds': 0, 'hot_feed': {'enabled': False},
                 'links': {'enabled': False},
                 'limits': {'window_5h': 100, 'window_1d': 500}},
                ROOT, sender, db_path=str(tmp / 'a.db'))
model = M(svc)
svc._model = model
svc.submit(QEvent(self_id=SELF, chat_type='group', chat_id=GROUP, sender_id='20002',
                  sender_name='x', message_id='S-2', time=time.time(), at_me=True,
                  at_all=False, text='在吗', images=[], segments=[], raw={}))
print('submit 后 stop_path=%s exists=%s' % (svc.stop_path, svc.stop_path.exists()))
print('--- 第 1 次 _loop_once ---')
svc._loop_once()
print('第 1 次后：texts=%r' % sender.texts)
print('queue state =', svc.db.execute('SELECT state FROM queue ORDER BY id DESC LIMIT 1').fetchone())
print('--- 第 2 次 _loop_once ---')
svc._loop_once()
print('第 2 次后：texts=%r' % sender.texts)
print('最终 queue state =', svc.db.execute('SELECT state FROM queue ORDER BY id DESC LIMIT 1').fetchone())
print('stop_path 属性 =', repr(getattr(svc, 'stop_path', '<缺失>')))
print('state_dir 下的文件 =', sorted(p.name for p in tmp.iterdir()))
