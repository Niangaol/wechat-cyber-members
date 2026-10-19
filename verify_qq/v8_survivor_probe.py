"""对抗式验证 8：逐个核查"存活突变"到底是不是真缺口。

对 v6 里存活的 3 个突变，分别回答三个问题：
  1. 这个突变到底改了什么语义？（构造最小复现，看行为差异）
  2. 现有测试里有没有任何一处覆盖它？（grep + 实际跑）
  3. 它是"测试缺口"还是"等价突变"（改了但行为不变）？

运行：python3 verify_qq/v8_survivor_probe.py
"""
import re
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'verify_qq'))

from harness import group, check, eq, observe, run, summary      # noqa: E402
from qq.core.envelope import QEvent                              # noqa: E402
from qq.core.policy import decide, DEFAULT_PLAIN_MODE            # noqa: E402
from qq.core import media                                        # noqa: E402
from web_reader import public_endpoint, WebSafetyError           # noqa: E402
from qq.core.bridge import SendResult, Sender                    # noqa: E402
from qq.core.service import QQService                            # noqa: E402

SELF = '10001'
GROUP = '30003'
TMPROOT = tempfile.mkdtemp(prefix='verify-qq-survivor-')


def ev(text='', at_me=False, chat_id=GROUP):
    return QEvent(self_id=SELF, chat_type='group', chat_id=chat_id, sender_id='20002',
                  sender_name='x', message_id=str(time.time_ns()), time=time.time(),
                  at_me=at_me, at_all=False, text=text, images=[], segments=[], raw={})


# --------------------------------------------------------------- M07
def t_m07_semantics():
    """M07：DEFAULT_PLAIN_MODE 从 at_only 改成 all 会怎样？"""
    eq('当前 DEFAULT_PLAIN_MODE', DEFAULT_PLAIN_MODE, 'at_only')
    d = decide(ev('随便聊聊'), {'groups': {GROUP: {}}, 'mention_aliases': ['年糕']},
               now=time.time(), queue_depth=0, last_reply_at=0, group_plain_times=None)
    print('    groups 里只写群号（没写 plain_mode）时的判定：%s/%s/%s'
          % (d.action, d.priority, d.reason))
    eq('未写 plain_mode 的群默认最保守', d.action, 'context_only')
    eq('reason 是 plain_at_only', d.reason, 'plain_at_only')
    # 覆盖情况：现有测试有没有钉住这个默认值（常量 + 行为两条腿）？
    text = (ROOT / 'test_qq_core_policy.py').read_text(encoding='utf-8')
    pins_constant = bool(re.search(
        r"assertEqual\(\s*policy\.DEFAULT_PLAIN_MODE\s*,\s*'at_only'", text))
    pins_behaviour = bool(re.search(
        r"groups=\{'20002':\s*\{\}\}", text))
    print('    test_qq_core_policy.py 里钉住常量的断言：%s' % pins_constant)
    print('    test_qq_core_policy.py 里"合法群条目不写 plain_mode"的用例：%s'
          % pins_behaviour)
    observe('（已补覆盖）M07 改的就是 DEFAULT_PLAIN_MODE 常量本身，'
            '现在测试同时钉了常量与行为两条腿 —— 与突变位置同源',
            pins_constant and pins_behaviour,
            'constant=%s behaviour=%s' % (pins_constant, pins_behaviour))


# --------------------------------------------------------------- M12
def t_m12_equivalence():
    """M12：去掉 media._fetch 里的端口白名单——是不是等价突变？"""
    ok_rejected = 0
    for url in ('http://example.com:8080/x.png', 'http://example.com:22/x.png',
                'http://example.com:8443/x.png'):
        try:
            public_endpoint(url)
        except WebSafetyError:
            ok_rejected += 1
    eq('默认 resolver（public_endpoint）自己就拒绝非 80/443', ok_rejected, 3)
    # 生产路径会不会注入 resolver？
    src = (ROOT / 'qq' / 'core' / 'service.py').read_text(encoding='utf-8')
    injects = 'resolver' in src
    check('生产路径 QQService.fetch_image 不注入 resolver（只传 max_bytes/timeout_s）',
          not injects)
    # 注入 resolver 时那道检查才是活的
    def lying_resolver(url):
        from urllib.parse import urlsplit
        return urlsplit(url), 'example.com', 8080, '93.184.216.34'
    result = media.fetch_image('http://example.com:8080/x.png',
                               Path(TMPROOT) / 'm12',
                               opener=lambda url, **kw: (200, {}, b'x'),
                               resolver=lying_resolver)
    eq('注入 resolver 时端口检查确实生效（返回 None）', result, None)
    observe('（等价突变）M12 存活**不代表缺口**：默认 resolver 已包含同样的端口限制'
            '（§10 D7 之后还额外拒了端口 0），_fetch 里那道是纵深防御；'
            '只有注入 resolver 时才可观测',
            ok_rejected == 3 and not injects)


# --------------------------------------------------------------- M16
def t_m16_semantics():
    """M16：去掉"生成前"的 STOP 检查会怎样？发送前还有第二道。"""
    class S(Sender):
        def __init__(self):
            self.texts = []
        def send_text(self, e, t):
            self.texts.append(t)
            return SendResult(True, False)
        def send_image(self, e, p):
            return SendResult(True, False)
        def self_id(self):
            return SELF
        def online(self):
            return True

    class M:
        def __init__(self):
            self.n = 0
        def session_for(self, k):
            return None
        def reply(self, *a, **kw):
            self.n += 1
            return '不该被生成'

    tmp = Path(tempfile.mkdtemp(dir=TMPROOT))
    sender, model = S(), M()
    svc = QQService({'state_dir': str(tmp), 'auto_send': True, 'self_id': SELF,
                     'groups': {GROUP: {'plain_mode': 'at_only'}},
                     'min_reply_seconds': 0, 'hot_feed': {'enabled': False},
                     'links': {'enabled': False},
                     'limits': {'window_5h': 100, 'window_1d': 500}},
                    ROOT, sender, db_path=str(tmp / 'a.db'),
                    model_factory=lambda cfg, db, sd: model,
                    searcher=lambda cfg, db: None,
                    image_generator=lambda cfg, sd: (lambda p: None),
                    fetcher=lambda u, d, **kw: None,
                    link_fetcher=lambda u, b: None)
    svc.stop_path.write_text('')
    svc.submit(ev('在吗', at_me=True))
    svc._loop_once()
    eq('STOP 在位：不发送', sender.texts, [])
    eq('STOP 在位：不调模型（生成前那道检查负责）', model.n, 0)
    eq('STOP 在位：不花额度', svc.quota.status()['used_5h'], 0)
    # 现有测试覆盖了什么？
    text = (ROOT / 'test_qq_core.py').read_text(encoding='utf-8')
    cls = re.search(r'class StopFileTests.*?(?=\nclass )', text, re.S)
    body = cls.group(0) if cls else ''
    names = re.findall(r'def (test_\w+)', body)
    print('    StopFileTests 里的用例：%s' % names)
    asserts_model = 'call_count' in body or 'calls' in body
    asserts_quota = 'used_5h' in body or 'quota' in body
    print('    其中是否断言了"没有调模型"：%s' % asserts_model)
    print('    其中是否断言了"没有花额度"：%s' % asserts_quota)
    observe('（已补覆盖）qq-core 已在 StopFileTests 里补上"不调模型"断言，'
            'M16 这条缺口已闭合（是否补"不花额度"见上一行）',
            asserts_model, 'model=%s quota=%s' % (asserts_model, asserts_quota))


group('M07 存活突变核查：plain_mode 默认值')
for fn in (t_m07_semantics,):
    run(fn)
group('M12 存活突变核查：端口白名单')
for fn in (t_m12_equivalence,):
    run(fn)
group('M16 存活突变核查：STOP 生成前检查')
for fn in (t_m16_semantics,):
    run(fn)

summary('存活突变核查')
