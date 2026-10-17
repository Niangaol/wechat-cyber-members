"""共用额度池：5小时/每日双窗口计数 + 分级优先级排队。所有模型调用统一消耗1单位。"""
import json
import time

# 合并后的单批消息上限：等一条消息排队时界面可能已经滚走，合并是**为了不丢**，
# 但也不能无限攒（攒太多会把模型上下文挤爆），超出就丢最老的并在日志里说明。
MERGE_LIMIT = 12


def merge_payloads(old_json, new_json):
    """把旧的待处理消息合并进新 payload：按 signature 去重，新消息排在后面。

    为什么必须合：消息在队列里等待期间，界面可能滚动/切换，新的观察里看不到它了。
    旧实现是"新任务直接覆盖旧 payload"，那条消息就**悄悄消失**了（没人回、也不报错）。
    """
    try:
        old = json.loads(old_json or '{}')
        new = json.loads(new_json or '{}')
    except ValueError:
        return new_json
    if not isinstance(old, dict) or not isinstance(new, dict):
        return new_json
    seen, merged = set(), []
    for message in (old.get('messages') or []) + (new.get('messages') or []):
        if not isinstance(message, dict):
            continue
        signature = message.get('signature')
        if signature and signature in seen:
            continue
        if signature:
            seen.add(signature)
        merged.append(message)
    trimmed = max(0, len(merged) - MERGE_LIMIT)
    if trimmed:
        merged = merged[trimmed:]
    out = dict(new)
    out['messages'] = merged
    out['want_search'] = bool(old.get('want_search') or new.get('want_search'))
    if trimmed:
        out['merge_trimmed'] = trimmed
    return json.dumps(out, ensure_ascii=False)

PRIORITY_GROUP_AT = 0    # 群里被@：最高
PRIORITY_DIRECT = 1      # 私信
PRIORITY_GROUP_PLAIN = 2 # 群普通消息：最低

PRIORITY_NAMES = {0: 'group_at', 1: 'direct', 2: 'group_plain'}

WINDOW_5H = 5 * 3600
WINDOW_1D = 24 * 3600


class QuotaExceeded(RuntimeError):
    pass


class Quota:
    """usage 表记录每次模型调用；check 在两个窗口都未超限才放行。"""

    def __init__(self, db, yield_after=3):
        self.db = db
        # 同一会话连续让位超过 yield_after 次就换别的会话先发（防单会话饿死其他会话）
        self._yield_after = max(0, int(yield_after))
        self._yielded = {}   # chat_key -> 连续让位次数
        self.db.execute(
            'CREATE TABLE IF NOT EXISTS usage(id INTEGER PRIMARY KEY, created REAL, priority INTEGER)')
        self.db.execute(
            'CREATE TABLE IF NOT EXISTS queue(id INTEGER PRIMARY KEY AUTOINCREMENT,'
            ' chat_key TEXT, priority INTEGER, created REAL, payload TEXT, state TEXT)')
        self.db.commit()

    def note_yield(self, chat_key):
        """记录一次让位（调用方在 RETRY_LATER 重新入队时调用）。"""
        self._yielded[chat_key] = self._yielded.get(chat_key, 0) + 1

    def note_served(self, chat_key):
        self._yielded[chat_key] = 0

    def count(self, window):
        return self.db.execute('SELECT count(*) FROM usage WHERE created>?',
                               (time.time() - window,)).fetchone()[0]

    def status(self):
        return {'used_5h': self.count(WINDOW_5H), 'used_1d': self.count(WINDOW_1D)}

    def check(self, limits):
        """limits={'window_5h':6000,'window_1d':70000}；任窗口超限抛 QuotaExceeded"""
        u5, u1 = self.count(WINDOW_5H), self.count(WINDOW_1D)
        if u5 >= limits['window_5h']:
            raise QuotaExceeded('5小时额度已用尽(%d/%d)' % (u5, limits['window_5h']))
        if u1 >= limits['window_1d']:
            raise QuotaExceeded('每日额度已用尽(%d/%d)' % (u1, limits['window_1d']))

    def next_reset_seconds(self, limits):
        """距额度恢复的秒数：只算已超限的窗口（没超的窗口不构成等待），取最晚恢复者。"""
        now = time.time()
        resets = []
        for window, limit in ((WINDOW_5H, limits['window_5h']), (WINDOW_1D, limits['window_1d'])):
            if self.count(window) < limit:
                continue
            row = self.db.execute('SELECT min(created) FROM usage WHERE created>?',
                                  (now - window,)).fetchone()
            if row and row[0]:
                resets.append(window - (now - row[0]))
        return int(max(resets)) if resets else 0

    def wait(self, qid):
        """任务转入等待（不丢，额度恢复后 requeue_waiting 放回）。"""
        self.db.execute('UPDATE queue SET state=? WHERE id=?', ('WAITING_QUOTA', qid))
        self.db.commit()

    def requeue_waiting(self):
        """额度恢复后把等待中的任务放回待处理；返回放回条数。"""
        cur = self.db.execute('UPDATE queue SET state=? WHERE state=?',
                              ('PENDING', 'WAITING_QUOTA'))
        self.db.commit()
        return cur.rowcount

    def waiting_count(self):
        return self.db.execute("SELECT count(*) FROM queue WHERE state='WAITING_QUOTA'").fetchone()[0]

    def consume(self, priority=PRIORITY_DIRECT):
        self.db.execute('INSERT INTO usage(created,priority) VALUES(?,?)',
                        (time.time(), priority))
        self.db.commit()

    def enqueue(self, chat_key, priority, payload):
        """入队；同 chat_key 已有未处理任务时**合并**（不是丢弃），按 signature 去重。

        旧行为是"新的把旧的标成 SUPERSEDED 直接丢掉"——等待期间滚出视口的那条消息
        就再也没人回、也不报错。现在把旧 payload 的消息合进新的这一条：仍然只有
        一个待处理任务（不会重复回两遍），但每条消息都还在。
        """
        row = self.db.execute("SELECT id, payload FROM queue WHERE state='PENDING'"
                              ' AND chat_key=? ORDER BY id DESC LIMIT 1',
                              (chat_key,)).fetchone()
        if row and row[1]:
            payload = merge_payloads(row[1], payload)
            self.db.execute('UPDATE queue SET state=? WHERE id=?', ('MERGED', row[0]))
        cur = self.db.execute(
            'INSERT INTO queue(chat_key,priority,created,payload,state) VALUES(?,?,?,?,?)',
            (chat_key, priority, time.time(), payload, 'PENDING'))
        self.db.commit()
        return cur.lastrowid

    def peek(self):
        """只看不取：按优先级再按入队时间取最早一条待处理任务。

        公平性：同一 chat_key 连续让位超过阈值时，本轮改取其他会话的任务，
        避免单个拥塞会话反复插队饿死其他会话。"""
        row = self.db.execute(
            'SELECT id,chat_key,priority,created,payload FROM queue'
            ' WHERE state=? ORDER BY priority,created LIMIT 1', ('PENDING',)).fetchone()
        if row is None:
            return None
        if self._yield_after and self._yielded.get(row[1], 0) >= self._yield_after:
            alt = self.db.execute(
                'SELECT id,chat_key,priority,created,payload FROM queue'
                ' WHERE state=? AND chat_key<>? ORDER BY priority,created LIMIT 1',
                ('PENDING', row[1])).fetchone()
            if alt is not None:
                self._yielded[row[1]] = 0
                return alt
        return row

    def claim(self, lease_seconds=300):
        """取走并标记 PROCESSING；超租约的僵尸任务重新可被领，防崩溃卡死。

        与 peek 保持同一套公平性规则：同一会话连续让位过多时让位其他会话。
        """
        now = time.time()
        base = ('SELECT id,chat_key,priority,created,payload FROM queue'
                ' WHERE state=? OR (state=? AND created<?)'
                ' ORDER BY priority,created LIMIT 1')
        row = self.db.execute(base, ('PENDING', 'PROCESSING', now - lease_seconds)).fetchone()
        if row is not None and self._yield_after and self._yielded.get(row[1], 0) >= self._yield_after:
            alt = self.db.execute(
                'SELECT id,chat_key,priority,created,payload FROM queue'
                " WHERE (state=? OR (state=? AND created<?)) AND chat_key<>?"
                ' ORDER BY priority,created LIMIT 1',
                ('PENDING', 'PROCESSING', now - lease_seconds, row[1])).fetchone()
            if alt is not None:
                self._yielded[row[1]] = 0
                row = alt
        taken = self.db.execute(
            'UPDATE queue SET state=? WHERE id=?', ('PROCESSING', row[0])).fetchone() \
            if row is not None else None
        self.db.commit()
        if row is None:
            return None
        return (row[0], row[1], row[2], row[3], row[4])

    def depth(self):
        return self.db.execute(
            'SELECT count(*) FROM queue WHERE state=?', ('PENDING',)).fetchone()[0]

    def finish(self, qid, state):
        self.db.execute('UPDATE queue SET state=? WHERE id=?', (state, qid))
        self.db.commit()
