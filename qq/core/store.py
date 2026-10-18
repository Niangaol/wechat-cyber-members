"""QQ 侧持久化：去重表、发送台账、会话目标表（契约 v1 · 第 6 节）。

为什么单独一层：
- **去重**必须落盘。NapCat 断线重连会把同一条消息重放，只靠内存集合重启就失效，
  表现就是"机器人对同一条消息回两遍"。
- **发送台账**要能回答"上次到底发出去了没有"。QQ 这边只能拿到 ok/unknown/failed，
  unknown 绝不能当失败重发（可能已经发出去了，重发就是双份）。
- **目标表**记住 chat_key 属于哪个会话，重启后仍能把入队任务还原成可发送目标。

本层不做判定、不发网络请求；QQService 用一把锁串行化对它的访问。
"""
import sqlite3
import time
from pathlib import Path

# 去重记录的保留天数：够覆盖任何合理的重连窗口，又不会让表无限长大。
INBOUND_KEEP_S = 7 * 24 * 3600
PRUNE_EVERY = 500

SEND_STATES = ('ok', 'failed', 'unknown')


class LockedConnection:
    """给 sqlite 连接套一层串行化：每条语句都在同一把（可重入）锁下执行。

    为什么必须这么做：submit()（NoneBot 事件循环线程）与 owner 线程**共用**一个连接。
    Python 的 sqlite3 处理隐式事务时是"先读 in_transaction、再发 BEGIN"，
    两个线程同时进来就会撞出
        OperationalError: cannot start a transaction within a transaction
    （实测踩到过：并发 submit + worker 时偶发，之后那条消息就再也回不了）。
    在连接这一层加锁，比在每个调用点记得手动加锁可靠得多——
    Quota / ChatMemory / HotFeed 是 src 的代码，改不了它们也不必改。

    注意：只读属性（如 row_factory）能透传，但**给它赋值会落在包装器上**，
    不会落到真连接上。本项目的代码不这么用。
    """

    def __init__(self, connection, lock):
        self._connection = connection
        self._lock = lock

    def execute(self, *args, **kwargs):
        with self._lock:
            return self._connection.execute(*args, **kwargs)

    def executemany(self, *args, **kwargs):
        with self._lock:
            return self._connection.executemany(*args, **kwargs)

    def executescript(self, *args, **kwargs):
        with self._lock:
            return self._connection.executescript(*args, **kwargs)

    def cursor(self, *args, **kwargs):
        with self._lock:
            return self._connection.cursor(*args, **kwargs)

    def commit(self):
        with self._lock:
            return self._connection.commit()

    def rollback(self):
        with self._lock:
            return self._connection.rollback()

    def close(self):
        with self._lock:
            return self._connection.close()

    def __getattr__(self, name):
        return getattr(self._connection, name)


class Store:
    def __init__(self, db_path, lock=None):
        """db_path 可以是文件路径、':memory:'，或一个已建好的 sqlite3.Connection。

        传 Connection 是为了让 QQService 把 Quota / ChatMemory / Store 挂在**同一个**
        连接上——尤其是 ':memory:' 库，换连接就等于换库。
        传 lock（可选）则把连接包成 LockedConnection，跨线程串行化（见上）。
        """
        opened = not isinstance(db_path, sqlite3.Connection)
        self.db, self._owned = _connect(db_path), opened
        if lock is not None:
            self.db = LockedConnection(self.db, lock)
        self._inserts = 0
        self._ensure_tables()

    # ---------- 建表 ----------
    def _ensure_tables(self):
        self.db.execute('CREATE TABLE IF NOT EXISTS inbound('
                        ' dedupe_key TEXT PRIMARY KEY, chat_key TEXT, created REAL)')
        self.db.execute('CREATE TABLE IF NOT EXISTS send_log('
                        ' id INTEGER PRIMARY KEY, chat_key TEXT, kind TEXT, state TEXT,'
                        ' detail TEXT, created REAL)')
        self.db.execute('CREATE TABLE IF NOT EXISTS targets('
                        ' chat_key TEXT PRIMARY KEY, chat_type TEXT, chat_id TEXT,'
                        ' updated REAL)')
        self.db.commit()

    # ---------- 去重 ----------
    def seen(self, dedupe_key, chat_key='', ts=None):
        """第一次见到这个键返回 True 并登记；重复投递返回 False。

        靠主键冲突实现，天然对"多线程同时投递同一条"安全（INSERT OR IGNORE 是原子的）。
        """
        key = str(dedupe_key or '')
        if not key:
            # 空键不能进表：所有空键会互相顶掉，等于把后面所有消息都去重没了。
            return False
        now = float(ts) if ts is not None else time.time()
        cursor = self.db.execute(
            'INSERT OR IGNORE INTO inbound(dedupe_key, chat_key, created) VALUES(?,?,?)',
            (key, str(chat_key or ''), now))
        self.db.commit()
        self._inserts += 1
        if self._inserts % PRUNE_EVERY == 0:
            self.prune_inbound(now)
        return cursor.rowcount == 1

    def prune_inbound(self, now=None):
        """清掉过期的去重记录，返回删除条数。"""
        now = float(now) if now is not None else time.time()
        cursor = self.db.execute('DELETE FROM inbound WHERE created<?',
                                 (now - INBOUND_KEEP_S,))
        self.db.commit()
        return cursor.rowcount

    # ---------- 会话目标 ----------
    def remember_target(self, chat_key, chat_type, chat_id, ts=None):
        now = float(ts) if ts is not None else time.time()
        self.db.execute(
            'INSERT INTO targets(chat_key, chat_type, chat_id, updated) VALUES(?,?,?,?)'
            ' ON CONFLICT(chat_key) DO UPDATE SET chat_type=excluded.chat_type,'
            ' chat_id=excluded.chat_id, updated=excluded.updated',
            (str(chat_key or ''), str(chat_type or ''), str(chat_id or ''), now))
        self.db.commit()

    def target_of(self, chat_key):
        """→ (chat_type, chat_id)；没登记过返回 None。"""
        row = self.db.execute('SELECT chat_type, chat_id FROM targets WHERE chat_key=?',
                              (str(chat_key or ''),)).fetchone()
        return (row[0], row[1]) if row else None

    def targets(self, limit=200):
        return [{'chat_key': r[0], 'chat_type': r[1], 'chat_id': r[2], 'updated': r[3]}
                for r in self.db.execute(
                    'SELECT chat_key,chat_type,chat_id,updated FROM targets'
                    ' ORDER BY updated DESC LIMIT ?', (int(limit),)).fetchall()]

    # ---------- 发送台账 ----------
    def record_send(self, chat_key, kind, state, detail='', ts=None):
        now = float(ts) if ts is not None else time.time()
        self.db.execute(
            'INSERT INTO send_log(chat_key, kind, state, detail, created) VALUES(?,?,?,?,?)',
            (str(chat_key or ''), str(kind or ''), str(state or ''), str(detail or '')[:500],
             now))
        self.db.commit()

    def last_send(self, chat_key, kind=None):
        """最近一条发送记录（失败也算）→ dict；没有返回 None。"""
        sql = ('SELECT id,chat_key,kind,state,detail,created FROM send_log WHERE chat_key=?')
        params = [str(chat_key or '')]
        if kind:
            sql += ' AND kind=?'
            params.append(str(kind))
        sql += ' ORDER BY id DESC LIMIT 1'
        row = self.db.execute(sql, params).fetchone()
        if not row:
            return None
        return {'id': row[0], 'chat_key': row[1], 'kind': row[2], 'state': row[3],
                'detail': row[4], 'created': row[5]}

    def last_ok_send_at(self, chat_key):
        """最近一次确认发送成功的时间；没有返回 0。status.json 的 last_send_ok_at 用它。"""
        row = self.db.execute("SELECT max(created) FROM send_log WHERE chat_key=?"
                              " AND state='ok'", (str(chat_key or ''),)).fetchone()
        return float(row[0] or 0) if row else 0.0

    def count_sends(self, window=3600, state='ok', chat_key=None):
        sql = 'SELECT count(*) FROM send_log WHERE created>?'
        params = [time.time() - float(window)]
        if state:
            sql += ' AND state=?'
            params.append(str(state))
        if chat_key:
            sql += ' AND chat_key=?'
            params.append(str(chat_key))
        return int(self.db.execute(sql, params).fetchone()[0])

    # ---------- 汇总 ----------
    def stats(self):
        def one(sql, params=()):
            return int(self.db.execute(sql, params).fetchone()[0])
        return {'inbound': one('SELECT count(*) FROM inbound'),
                'targets': one('SELECT count(*) FROM targets'),
                'sends': one('SELECT count(*) FROM send_log'),
                'send_ok': one("SELECT count(*) FROM send_log WHERE state='ok'"),
                'send_failed': one("SELECT count(*) FROM send_log WHERE state='failed'"),
                'send_unknown': one("SELECT count(*) FROM send_log WHERE state='unknown'")}

    def close(self):
        """只关自己开的连接；外部传进来的 Connection 由调用方负责。"""
        if self._owned:
            try:
                self.db.close()
            except sqlite3.Error:
                pass


def _connect(db_path):
    """打开（必要时创建）数据库；文件库开 WAL，兼顾崩溃安全与并发读。"""
    if isinstance(db_path, sqlite3.Connection):
        return db_path
    path = str(db_path)
    if path != ':memory:':
        Path(path).parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path, timeout=10, check_same_thread=False)
    con.execute('PRAGMA busy_timeout=10000')
    try:
        con.execute('PRAGMA journal_mode=WAL')
    except sqlite3.Error:
        pass          # ':memory:' 库不支持 WAL；不影响正确性
    con.execute('PRAGMA synchronous=NORMAL')
    return con
