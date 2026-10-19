"""运行时串扰审计：证明/证伪 lead 的假设"某个用例领到了前一个用例遗留的任务"。

做法：在同一次进程里跑完 v4 的全部探针，同时钩住三处：
  1. QQService.__init__ —— 记录每个服务实例的 state_dir / db_path / id；
  2. Quota.enqueue    —— 记录 (连接身份, qid, chat_key)；
  3. Worker.process   —— 记录 (连接身份, qid)，与 enqueue 配对。

判据（任何一条不成立就是**真的串扰**）：
  A. 每个服务实例的 db_path 各不相同（除显式复用 tmp 的 restart 用例）；
  B. 每个被 process 的任务，都能在**同一个连接**上找到它的 enqueue 记录；
  C. 没有任务被"跨连接"处理（qid 配到了别的连接上）。

用法： python3 verify_qq/_isolation_audit.py
"""
import sys
import types
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE.parent / 'src'))

source = (HERE / 'v4_service.py').read_text(encoding='utf-8')
head = source.split("\ngroup('§6/§7", 1)[0]
mod = types.ModuleType('v4_audit')
mod.__file__ = str(HERE / 'v4_service.py')
exec(compile(head, str(HERE / 'v4_service.py'), 'exec'), mod.__dict__)

from quota import Quota                                   # noqa: E402
from qq.core.worker import Worker                          # noqa: E402

SERVICES = []          # (id, db_path, state_dir)
ENQ = []               # (conn_id, qid, chat_key)
PROC = []              # (conn_id, qid)

_orig_init = mod.QQService.__init__


def init(self, *a, **kw):
    _orig_init(self, *a, **kw)
    SERVICES.append((id(self), str(self.db_path), str(self.state_dir)))


mod.QQService.__init__ = init

_orig_enq = Quota.enqueue


def enqueue(self, chat_key, priority, payload):
    qid = _orig_enq(self, chat_key, priority, payload)
    ENQ.append((_conn_key(self.db), qid, str(chat_key)))
    return qid


Quota.enqueue = enqueue

_orig_proc = Worker.process


PROC_DETAIL = []


def _conn_key(conn):
    """稳定的"哪个库"标识。

    **不能**用 id(conn)：Python 回收对象后会复用地址，实测不同用例的连接会撞到同一个
    id（第一版审计就因此报了一堆假阳性）。用 state_dir/db 路径才是稳定的。
    """
    try:
        rows = conn.execute('PRAGMA database_list').fetchall()
        for row in rows:
            if row[1] == 'main':
                return str(row[2])
    except Exception:                               # noqa: BLE001
        pass
    return 'unknown'


def process(self, row):
    key = _conn_key(self.service.db)
    PROC.append((key, row[0]))
    PROC_DETAIL.append({'key': key, 'qid': row[0],
                        'state_dir': str(self.service.state_dir),
                        'action': _peek_action(row)})
    return _orig_proc(self, row)


def _peek_action(row):
    import json as _json
    try:
        return _json.loads(row[4] or '{}').get('action')
    except Exception:                               # noqa: BLE001
        return '?'


Worker.process = process

# 跑完全部探针
for name in list(vars(mod)):
    pass
exec(compile("\ngroup('§6/§7" + source.split("\ngroup('§6/§7", 1)[1]
             .split("print('')\nprint('---- 用例隔离审计 ----')")[0],
             str(HERE / 'v4_service.py'), 'exec'), mod.__dict__)

print()
print('=' * 70)
print('运行时串扰审计结果')
print('=' * 70)
print('服务实例数：%d' % len(SERVICES))
paths = [p for _, p, _ in SERVICES]
uniq = set(paths)
print('不同 db_path 数：%d（重复的：%s）'
      % (len(uniq), [p for p in uniq if paths.count(p) > 1] or '无'))
print('enqueue 次数：%d；process 次数：%d' % (len(ENQ), len(PROC)))

enq_by_conn = {}
for conn, qid, chat in ENQ:
    enq_by_conn.setdefault(conn, {})[qid] = chat

cross = []
for conn, qid in PROC:
    if qid not in enq_by_conn.get(conn, {}):
        cross.append((conn, qid))
shared = {p: [s for s in SERVICES if s[1] == p] for p in uniq if paths.count(p) > 1}
print('A. db_path 出现重复的：')
for path, items in shared.items():
    print('     %s  <- %d 个服务实例' % (path, len(items)))
probe_of = {}
for key, items in getattr(mod, '_STATE_DIRS', {}).items():
    for caller, kind in items:
        probe_of.setdefault(key, []).append('%s(%s)' % (caller, kind))
for k, v in probe_of.items():
    if len(v) > 1:
        print('   对应的 probe：%s' % (v,))
explicit_share = all(
    all('explicit' in c for c in probe_of.get(k, []))
    for k in probe_of if len(probe_of.get(k, [])) > 1)
explicit_share_only = explicit_share and bool(shared)
print('   重复是否只发生在**显式复用 tmp 的 restart 用例**里：%s'
      % ('是（设计如此：t_dedupe_survives_restart 故意在同一 db 上重启一次）'
         if explicit_share_only else '否'))
print('B. 被 process 的任务都能在**同一个连接**上找到 enqueue：%s'
      % ('是' if not cross else '否 —— 跨连接处理了 %d 条：%s' % (len(cross), cross[:5])))
print('C. 未配对的 process 记录：%s' % (cross or '无'))
# D. 每个连接上"被处理"的次数不能超过"入队"的次数（否则就是凭空多处理了任务）
enq_cnt = {}
for conn, qid, chat in ENQ:
    enq_cnt[conn] = enq_cnt.get(conn, 0) + 1
proc_cnt = {}
for conn, qid in PROC:
    proc_cnt[conn] = proc_cnt.get(conn, 0) + 1
phantom = {c: (proc_cnt[c], enq_cnt.get(c, 0)) for c in proc_cnt
           if proc_cnt[c] > enq_cnt.get(c, 0)}
print('D. 有"处理次数 > 入队次数"的连接（凭空多处理的）：%s'
      % (phantom or '无'))
dup = {}
for conn, qid in PROC:
    dup[(conn, qid)] = dup.get((conn, qid), 0) + 1
multi = {k: v for k, v in dup.items() if v > 1}
print('E. 同一个 (连接, qid) 被处理多次的：%s' % (multi or '无'))
if multi:
    probe_of = {}
    for key, items in getattr(mod, '_STATE_DIRS', {}).items():
        for caller, kind in items:
            probe_of.setdefault(key, []).append(caller)
    for (conn, qid), times in multi.items():
        print('  ---- 细节：库 %s 上的 qid=%d 被 process() 调用 %d 次 ----'
              % (conn.split('/')[-2] if '/' in conn else conn, qid, times))
        for rec in PROC_DETAIL:
            if rec['key'] == conn and rec['qid'] == qid:
                names = probe_of.get(rec['state_dir'], ['?'])
                print('     probe=%s  action=%s' % (names, rec['action']))
    print()
    print('  说明：process() 被调用多次**不必然**是重复发送 —— WAITING_QUOTA 的设计就是')
    print('  "第一次尝试先 park、额度恢复后再处理一次"（t_quota_exhausted_waits 正是这条路径）。')
    print('  真正的"多发"要看最终发出去几条，由各探针自己的 sender.texts 断言覆盖。')

# 真正的串扰 = 跨库处理 / 未配对；D、E 是"需要解释"的信息项：
#   WAITING_QUOTA 的设计就是同一 qid 被 process() 调用两次（先 park、后处理），
#   是否"多发"由各探针自己的 sender.texts 断言兜底（t_quota_exhausted_waits 断言恰好 1 条）。
bad = bool(cross) or not explicit_share_only
print()
print('结论：%s' % ('存在串扰，需要继续查' if bad else
                  '未发现任何跨用例串扰（每个服务各自独立的 state_dir / qq.db，'
                  '没有任何任务被跨连接处理）'))
