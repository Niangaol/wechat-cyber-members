"""QQ 核心服务：入队、单线程处理、状态自述（契约 v1 · 第 7 节）。

分工：
- **submit()** 由 NoneBot 的事件循环调用，只做"短平快"的几件事：过期过滤、
  去重、判策略、入队。持锁时间是毫秒级，绝不在这里调模型/下图片/发消息。
- **owner 线程**（start() 起的单条 daemon 线程）负责所有慢活：模型、下载、发送、
  以及它们附带的 sqlite 写入。submit 与 owner 共用一把 RLock，保证同一时刻
  只有一个人在碰那个 sqlite 连接。

注入点（离线测试用，生产留空走真实实现）：
    model_factory(cfg, db, state_dir)    → 有 .reply(...) 的模型门面（默认 StepPlan）
    searcher(cfg, db)                    → 有 .search(text) 的搜索客户端（默认 WebSearch）
    image_generator(cfg, state_dir)      → 可调用对象，入参提示词、返回本地图片路径
    工厂按"能接受几个位置参数"调用，写 lambda *a: ... 也能用。
"""
import inspect
import itertools
import json
import logging
import re
import sqlite3
import threading
import time
from pathlib import Path

from memory import ChatMemory
from quota import PRIORITY_GROUP_PLAIN, Quota, QuotaExceeded
from search import HotFeed

try:                                          # 热榜源清单（src/search.py 的 ROUTES）
    from search import ROUTES as HOT_SOURCES
except ImportError:                           # src 侧改了名字也不该让服务起不来
    HOT_SOURCES = ()

from . import config as config_module, envelope, media, policy
from .bridge import Sender                     # noqa: F401  （类型用途，同时方便调用方 import）
from .store import Store
from .worker import Worker

DEFAULT_LIMITS = {'window_5h': 6000, 'window_1d': 70000}
DEFAULT_REPLY_MAX_CHARS = 200
DEFAULT_MAX_QUEUE = 200
DEFAULT_EVENT_MAX_AGE_S = 300.0
DEFAULT_POLL_INTERVAL_S = 0.2
DEFAULT_CLAIM_LEASE_S = 300
DEFAULT_STATUS_INTERVAL_S = 5.0
DEFAULT_TASK_TTL_S = 600.0
# 首次启动先等一会儿再刷热榜：让第一轮 status.json 先落盘（看门狗据此判活）
DEFAULT_HOT_INITIAL_DELAY_S = 5.0
DEFAULT_HOT_REFRESH_S = 300.0
HOUR = 3600.0


_TEMP_SEQ = itertools.count(1)


def atomic_json(path, value):
    """原子写 JSON：先写同目录临时文件 → 改权限 → replace（同 src/resident.atomic_json）。

    直接覆写 status.json 的风险是"读的人正好读到写了一半的文件"，
    看门狗据此判断存活，读到半个 JSON 会误判成服务挂了。

    临时文件名必须**每次都不一样**：status.json 有多个写者（心跳线程、
    owner 线程开局那一份、调用方显式的 status()）。共用固定的 status.tmp 时，
    一个写者会把另一个的临时文件 rename 走，另一个 chmod 时就
    FileNotFoundError（实测踩到过，日志里一串 qq_status_write_failed）。
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.parent / ('.%s.%d.tmp' % (path.name, next(_TEMP_SEQ)))
    try:
        temp.write_text(json.dumps(value, ensure_ascii=False, indent=2))
        temp.chmod(0o600)
        temp.replace(path)
    except BaseException:
        try:
            temp.unlink()
        except OSError:
            pass
        raise


def _param_names(func):
    """能拿到签名就返回参数名集合，拿不到（内置/替身）返回空集。"""
    try:
        return set(inspect.signature(func).parameters)
    except (TypeError, ValueError):
        return set()


def _accepted(func, candidates):
    """挑出 func 真正接受的那些关键字参数（值为空的丢掉）。

    两种都算"接受"：显式写了这个形参，或者带 **kwargs（那就什么都能收）。
    为什么不写"先多传、抛 TypeError 再退回"：生图是**花钱**的，
    那种写法会在真出错时白发一次请求（甚至成功一次、失败一次，白花两份钱）。
    """
    items = {k: v for k, v in candidates.items() if v}
    try:
        params = inspect.signature(func).parameters
    except (TypeError, ValueError):
        return items
    if any(p.kind is inspect.Parameter.VAR_KEYWORD for p in params.values()):
        return items
    return {k: v for k, v in items.items() if k in params}


def _invoke(factory, *args):
    """按工厂实际能接受的位置参数个数调用它。

    注入点要让人写得舒服：lambda *a: FakeModel()、lambda: model、
    lambda cfg, db, state_dir: Real(...) 这三种写法都得能用，
    不能逼调用方去背参数表。
    """
    if factory is None:
        return None
    try:
        params = inspect.signature(factory).parameters
    except (TypeError, ValueError):
        return factory(*args)
    values = list(params.values())
    if any(p.kind is inspect.Parameter.VAR_POSITIONAL for p in values):
        return factory(*args)
    positional = [p for p in values
                  if p.kind in (inspect.Parameter.POSITIONAL_ONLY,
                                inspect.Parameter.POSITIONAL_OR_KEYWORD)]
    return factory(*args[:len(positional)])


# URL 字符集**只收 ASCII 可见字符**：微信侧 gather_sources 用的是
# [^\s<>"\u3000]+，中文聊天里"看这个 https://a/b，挺好的"会把"，挺好的"
# 一起吞进 URL（实测），拿去请求必然 404。这里少收几个字符，宁可截短。
URL_PATTERN = re.compile(r"https?://[A-Za-z0-9\-._~:/?#\[\]@!$&'()*+,;=%]+")
# 尾巴上的标点几乎总是句读，不是 URL 的一部分
URL_TRAILING = '.,;:!?' + chr(39) + chr(34) + '。，、；：！？）］」』'


def extract_urls(messages, limit=0):
    """从一批消息文本里抠 http(s) 链接：去重、砍掉中文标点尾巴、保序。

    尾部标点必须剥掉——中文聊天里
    "看这个 https://a/b。" 的句号会被当成 URL 的一部分，直接 404。
    """
    urls = []
    for message in messages or ():
        text = message.get('text') if isinstance(message, dict) else message
        for url in URL_PATTERN.findall(str(text or '')):
            url = url.rstrip(URL_TRAILING)
            if url and url not in urls:
                urls.append(url)
    if limit and limit > 0:
        return urls[:limit]
    return urls


def _default_link_fetcher(url, block):
    """默认链接读取：src/web_reader.fetch_public_text（只公网 http/https、DNS 固定）。"""
    from web_reader import fetch_public_text
    return fetch_public_text(url, block)


def _default_model_factory(cfg, db, state_dir):
    """默认模型门面：src/multimodal.py 的 StepPlan（契约 §7 指定）。

    契约写的是 StepPlan(cfg, db, state_dir=...)，实际签名只有 (cfg, db)。
    这里按**真实签名**挑参数传——多传一个不认识的 kwarg 会直接把服务起不来。
    """
    from multimodal import StepPlan
    return StepPlan(cfg, db, **_accepted(StepPlan.__init__, {'state_dir': state_dir}))


def _default_searcher_factory(cfg, db):
    """默认搜索客户端：src/web_search.py 的 WebSearch（缓存/上限/熔断都在它里面）。"""
    from web_search import WebSearch
    block = cfg.get('web_search')
    return WebSearch(db, block if isinstance(block, dict) else None)


def _default_image_generator_factory(cfg, state_dir):
    """默认生图器：src/imagegen.py。

    契约写的是 generate(prompt, state_dir=..., credentials_file=...)，
    实际签名只有 (prompt, base, model, ref_image)。这里同样按真实签名挑参数传，
    **绝不**用"抛 TypeError 再重试"的写法——生图是花钱的，一次请求都不能白发。
    """
    from imagegen import generate as generate_image, OC_REF
    block = cfg.get('image_generation')
    block = block if isinstance(block, dict) else {}
    wanted = {'state_dir': state_dir,
              'credentials_file': str(block.get('credentials_file') or ''),
              'base': block.get('base'),
              'model': block.get('model'),
              'ref_image': OC_REF}
    accepted = _accepted(generate_image, wanted)

    def generate(prompt):
        return generate_image(prompt, **accepted)

    return generate


class QQService:
    """平台无关的 QQ 核心服务。同步阻塞实现，不依赖 nonebot/asyncio。"""

    def __init__(self, cfg, root, sender, db_path=None, clock=time.time, *,
                 model_factory=None, searcher=None, image_generator=None, fetcher=None,
                 hot_refresh=None, link_fetcher=None):
        # 契约 §9：先过一遍 config.normalize（补默认值、校验 groups/direct_policy、
        # 未知字段只 warn），拿到的才算可信配置。传进来的 dict 不会被改动。
        self.cfg = config_module.normalize(cfg)
        self.root = Path(root)
        self.sender = sender
        self._clock = clock if callable(clock) else time.time
        # 锁必须**先**建：submit 线程与 owner 线程共用一个 sqlite 连接，
        # 连接层要靠它串行化（见 store.LockedConnection 的说明）。
        self._lock = threading.RLock()

        # 契约 §9.4：state_dir 要 expanduser，并且 chmod 700（里面有聊天内容）
        self.state_dir = config_module.prepare_state_dir(self.cfg)
        self.media_dir = self.state_dir / 'media'
        self.stop_path = self.state_dir / 'STOP'
        self.status_path = self.state_dir / 'status.json'
        self.media_dir.mkdir(parents=True, exist_ok=True)
        # 契约 §9 总闸：false = 只记录/入队、不发送（首次部署默认关）
        self.auto_send = bool(self.cfg.get('auto_send'))
        self.task_ttl_s = _float(self.cfg.get('task_ttl_seconds'),
                                 DEFAULT_TASK_TTL_S)
        self.hot_conf = self.cfg.get('hot_feed') or {}
        self._hot_refresh = hot_refresh          # 测试注入：一轮刷新的替身
        self._last_media_prune = 0.0

        self.db_path = db_path if db_path is not None else self.state_dir / 'qq.db'
        # Store 开连接，Quota/ChatMemory/HotFeed 共用同一个（':memory:' 才有一致性）
        self.store = Store(self.db_path, lock=self._lock)
        self.db = self.store.db
        self.quota = Quota(self.db)
        self.memory = ChatMemory(self.db)
        self.feed = HotFeed(self.db)

        self.limits = self.cfg.get('limits')
        if not isinstance(self.limits, dict):
            self.limits = dict(DEFAULT_LIMITS)
        self.reply_max_chars = _int(self.cfg.get('reply_max_chars'),
                                    DEFAULT_REPLY_MAX_CHARS)
        # 契约 §9 的 max_pending 是队列上限；max_queue 是早期别名（normalize 已折算）
        self.max_queue = max(0, _int(self.cfg.get('max_pending'), DEFAULT_MAX_QUEUE))
        self.event_max_age_s = _float(self.cfg.get('event_max_age_s'),
                                      DEFAULT_EVENT_MAX_AGE_S)
        self.poll_interval_s = max(0.01, _float(self.cfg.get('poll_interval_s'),
                                                DEFAULT_POLL_INTERVAL_S))
        self.claim_lease_s = max(1, _int(self.cfg.get('claim_lease_s'),
                                         DEFAULT_CLAIM_LEASE_S))
        self.status_interval_s = max(0.0, _float(self.cfg.get('status_interval_s'),
                                                 DEFAULT_STATUS_INTERVAL_S))
        self.aliases = _str_list(self.cfg.get('mention_aliases'))

        self._model_factory = model_factory
        self._searcher_factory = searcher
        self._image_factory = image_generator
        self._fetcher = fetcher
        self._link_fetcher = link_fetcher
        self.links_conf = self.cfg.get('links') or {}
        self._model = None
        self._searcher = None
        self._image = None
        self._search_params = None

        self._stopping = threading.Event()
        self._hot_stop = threading.Event()
        self._thread = None
        self._status_thread = None
        self._hot_thread = None
        self._worker = Worker(self)
        self._closed = False

        self._last_reply = {}        # chat_key -> 上次真正发出回复的时间
        self._plain_replies = {}     # chat_key -> [群普通消息回复时间]
        self._image_times = {}       # chat_key -> [发图时间]
        self._counters = {}

        self.heartbeat = 0.0           # 心跳线程写的：进程还活着
        self.worker_heartbeat = 0.0    # owner 线程最近一轮循环：队列有没有在动
        self.hot_heartbeat = 0.0       # 热榜线程最近一轮：热榜有没有卡住
        self.last_event_at = 0.0
        self.last_accepted_at = 0.0
        self.last_send_ok_at = 0.0
        self.last_error = ''

    # ---------- 生命周期 ----------
    def start(self):
        """起 daemon 线程。重复调用无副作用。

        三条线程各管一件事（契约 §7 只说了 owner 一条；把心跳与热榜分出去是
        2026-10-18 真机事故的修正，理由见 _status_loop / _hot_loop 的注释）：
          - qq-core-worker：owner thread，唯一处理队列/模型/发送的线程；
          - qq-core-status：只写 status.json 心跳，不被单条任务的处理时长绑架；
          - qq-core-hot   ：只刷热榜（网络 I/O），卡住也只卡它自己。
        热榜关掉时不起第三条。
        """
        if self._closed:
            raise RuntimeError('服务已关闭，不能重新启动')
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return
            self._stopping.clear()
            self._hot_stop.clear()
            self.heartbeat = self._clock()
            self.worker_heartbeat = self.heartbeat
            self._thread = threading.Thread(target=self._loop, name='qq-core-worker',
                                            daemon=True)
            self._thread.start()
            self._status_thread = threading.Thread(target=self._status_loop,
                                                   name='qq-core-status', daemon=True)
            self._status_thread.start()
            if self._hot_enabled():
                self._hot_thread = threading.Thread(target=self._hot_loop,
                                                    name='qq-core-hot', daemon=True)
                self._hot_thread.start()

    def stop(self, timeout=5.0):
        """通知所有线程退出并等待；只在真的退出后才关数据库。"""
        self._stopping.set()
        self._hot_stop.set()
        threads = (self._thread, self._status_thread, self._hot_thread)
        for item in threads:
            if item is not None and item.is_alive():
                item.join(float(timeout))
        thread = self._thread
        with self._lock:
            self._thread = None
            self._status_thread = None
            self._hot_thread = None
            self.heartbeat = self._clock()
            if not self._closed and (thread is None or not thread.is_alive()):
                self._closed = True
                try:
                    self.status()
                except Exception as exc:            # noqa: BLE001 关服务不该因为写状态失败
                    logging.warning('qq_status_on_stop_failed type=%s',
                                    type(exc).__name__)
                self.store.close()

    def running(self):
        thread = self._thread
        return bool(thread is not None and thread.is_alive())

    def clock(self):
        """统一时钟（可注入）：服务和 worker 里所有\"现在几点\"都走它。"""
        return self._clock()

    def any_stop(self):
        """STOP 文件存在 = 停手不出话（不是退出进程）。"""
        try:
            return self.stop_path.exists()
        except OSError:
            return True          # 查不了就当作"被叫停"：宁可不出话

    # ---------- 入队 ----------
    def submit(self, event):
        """线程安全入队；返回 True 表示这条消息真的排上了。

        拒绝的四种情况都不算"出错"，是设计好的门：
          - 事件过期（重连后重放很久以前的）；
          - 队列已满；
          - 同 message_id 重复投递（断线重放，只处理一次）；
          - 策略判定 ignore（未登记群/黑名单/自己发的……）。
        """
        if event is None or not getattr(event, 'chat_key', ''):
            self._bump('bad_event')
            return False
        now = self._clock()
        # 只要**收到**就记一笔：被策略拒掉的事件也要能在 status 里看见
        #（否则 groups 空配置时 last_event_at 永远是 0，排查时看不出到底有没有收到）
        self.last_event_at = now
        stamp = float(getattr(event, 'time', 0) or 0)
        if stamp and self.event_max_age_s > 0 and (now - stamp) > self.event_max_age_s:
            self._bump('stale')
            logging.info('qq_event_stale chat=%s age=%.0fs', event.chat_key, now - stamp)
            return False
        chat_key = event.chat_key
        with self._lock:
            if self.quota.depth() >= self.max_queue:
                self._bump('queue_full')
                logging.warning('qq_queue_full depth=%d max=%d', self.quota.depth(),
                                self.max_queue)
                return False
            if not self.store.seen(event.dedupe_key, chat_key, now):
                self._bump('duplicate')
                logging.info('qq_event_duplicate chat=%s message_id=%s',
                             chat_key, event.message_id)
                return False
            decision = policy.decide(
                event, self.cfg, now=now, queue_depth=self.quota.depth(),
                last_reply_at=self._last_reply.get(chat_key, 0),
                group_plain_times=list(self._plain_replies.get(chat_key, ())))
            if decision.action == 'ignore':
                self._bump('ignored')
                logging.info('qq_event_ignored chat=%s reason=%s', chat_key,
                             decision.reason)
                return False
            self.store.remember_target(chat_key, event.chat_type, event.chat_id, now)
            self.quota.enqueue(chat_key, decision.priority,
                               envelope.batch_payload(event, decision))
            self._bump('queued')
        self.last_accepted_at = now
        logging.info('qq_event_queued chat=%s action=%s reason=%s priority=%d',
                     chat_key, decision.action, decision.reason, decision.priority)
        return True

    # ---------- 处理循环 ----------
    def _loop(self):
        logging.info('qq_worker_started state_dir=%s', self.state_dir)
        try:
            self.status()          # 起来先落一份：看门狗第一时间就能看到文件
        except Exception as exc:                    # noqa: BLE001
            logging.warning('qq_status_first_write_failed type=%s', type(exc).__name__)
        while not self._stopping.is_set():
            try:
                self._loop_once()
            except Exception as exc:                # noqa: BLE001 循环绝不能死
                logging.error('qq_worker_loop_error type=%s reason=%s',
                              type(exc).__name__, str(exc)[:200])
                self.note_error('%s: %s' % (type(exc).__name__, str(exc)[:120]))
                self._stopping.wait(1.0)
            self.worker_heartbeat = self._clock()
        logging.info('qq_worker_stopped')

    def _status_loop(self):
        """心跳线程：唯一职责是按 status_interval_s 把 status.json 写新。

        为什么不在 owner 线程里写（原来就是这么写的，2026-10-18 真机踩到）：
        一次模型调用十几秒、一次热榜刷新能挂几分钟，那期间 owner 线程回不到
        循环顶部，心跳就停在很久以前——看门狗据此判活会误判成"服务死了"。
        心跳的语义是"进程还活着"，不该被单条任务的处理时长绑架。
        """
        logging.info('qq_status_thread_started interval=%.1fs', self.status_interval_s)
        while not self._stopping.is_set():
            self.heartbeat = self._clock()
            try:
                self.status()
            except Exception as exc:                # noqa: BLE001
                logging.warning('qq_status_write_failed type=%s', type(exc).__name__)
            self._stopping.wait(max(0.5, self.status_interval_s))
        logging.info('qq_status_thread_stopped')

    def _hot_enabled(self):
        conf = self.hot_conf if isinstance(self.hot_conf, dict) else {}
        return bool(conf.get('enabled'))

    def _hot_loop(self):
        """热榜线程：每轮只刷一个最久没刷过的源，且只在队列空闲时刷。

        真机事故（2026-10-18 17:48）：热榜刷新原来跑在 owner 线程里，
        feed.refresh() 撞上公共 RSSHub 实例限流，整条回复链连同心跳一起被卡死
        好几分钟（status.json 一直不生成、health 报 status_file=false）。
        热榜只是"背景素材"，它慢不该拖住任何一条回复——所以整件事挪到这条线程，
        并且照微信侧 hot_cycle 的做法：一次只刷一个源、只挑最久没刷的那个、
        队列不空闲就等下一轮。
        """
        interval = max(30.0, _float(self.hot_conf.get('refresh_seconds'),
                                    DEFAULT_HOT_REFRESH_S))
        delay = min(interval, DEFAULT_HOT_INITIAL_DELAY_S)
        logging.info('qq_hot_thread_started interval=%.0fs first_delay=%.0fs',
                     interval, delay)
        if self._hot_stop.wait(delay):              # 先让第一轮 status.json 落盘
            logging.info('qq_hot_thread_stopped')
            return
        while not self._hot_stop.is_set():
            if self._queue_is_idle():
                source = ''
                try:
                    count = self._hot_round()
                except Exception as exc:            # noqa: BLE001 热榜失败绝不影响回复
                    count = 0
                    logging.warning('qq_hot_refresh_failed type=%s reason=%s',
                                    type(exc).__name__, str(exc)[:120])
                if count:
                    logging.info('qq_hot_refreshed sources=%d', count)
            self.hot_heartbeat = self._clock()
            if self._hot_stop.wait(interval):
                break
        logging.info('qq_hot_thread_stopped')

    def _queue_is_idle(self):
        """队列空才刷热榜（与微信侧 hot_cycle 同一个语义）。查询失败按忙处理。"""
        try:
            with self._lock:
                return self.quota.depth() == 0
        except Exception:                           # noqa: BLE001
            return False

    def _hot_round(self):
        """一轮刷新：只刷一个源。返回刷成功的源数。

        注入替身时按"一轮"调用它一次（离线测试用，绝不真的出网）。
        """
        if self._hot_refresh is not None:
            return int(self._hot_refresh() or 0)
        sources = [str(item[0]) for item in HOT_SOURCES if item]
        if not sources:
            return 0
        source = self._next_hot_source(sources)
        return int(self.feed.refresh(only_source=source) or 0)

    def _next_hot_source(self, sources):
        """挑最久没刷过的源。

        用 hot_meta 表里的 fetched（**持久化**）而不是内存指针：服务一重启内存
        就归零，结果永远只刷第一个源（微信侧 2026-10-17 实测：一晚上全是 weibo_hot）。
        """
        fetched = {}
        try:
            with self._lock:
                rows = self.db.execute('SELECT source, fetched FROM hot_meta').fetchall()
            fetched = {row[0]: (row[1] or 0) for row in rows}
        except Exception:                           # noqa: BLE001 查不到就按都没刷过
            fetched = {}
        return min(sources, key=lambda name: fetched.get(name, 0))

    def _loop_once(self):
        # STOP 存在时**不领任务**：消息留在队列里（每会话按合并上限封顶），
        # 解除 STOP 后自然会被处理，不会静默丢消息。
        if self.any_stop():
            self._stopping.wait(1.0)
            return
        self._maybe_prune_media()
        self._requeue_quota_waiting()
        if self._queue_is_idle():
            # 风格自学习只在空闲时做（契约 §7.1）：它要调模型，别跟回复抢
            self._worker.learn_cycle()
        with self._lock:
            row = self.quota.claim(self.claim_lease_s)
        if row is None:
            self._stopping.wait(self.poll_interval_s)
            return
        self._worker.process(row)

    def _maybe_prune_media(self):
        """按 media.keep_days 清掉过期的下载图片（每小时最多做一次）。"""
        block = self.cfg.get('media')
        keep_days = _int((block or {}).get('keep_days'), 14)
        if keep_days <= 0:
            return 0
        now = self._clock()
        if now - self._last_media_prune < HOUR:
            return 0
        self._last_media_prune = now
        deadline = now - keep_days * 24 * 3600
        removed = 0
        try:
            entries = list(self.media_dir.iterdir())
        except OSError:
            return 0
        for path in entries:
            try:
                if path.is_file() and path.stat().st_mtime < deadline:
                    path.unlink()
                    removed += 1
            except OSError:
                continue                            # 删不掉就留着，下次再说
        if removed:
            logging.info('qq_media_pruned removed=%d keep_days=%d', removed, keep_days)
        return removed

    def self_id(self):
        """当前绑定的 QQ 号：通道给的优先，其次配置，最后 state_dir/self_id.txt。"""
        value = self._safe(lambda: str(self.sender.self_id() or ''), '')
        return (value or str(self.cfg.get('self_id') or '')
                or config_module.read_self_id(self.state_dir))

    def bind_self_id(self, self_id):
        """登录后把绑定到的账号写回 state_dir/self_id.txt（配置里写了就听配置的）。"""
        value = str(self_id or '').strip()
        if not value or str(self.cfg.get('self_id') or '').strip():
            return ''
        config_module.write_self_id(self.state_dir, value)
        return value

    def _requeue_quota_waiting(self):
        """额度恢复后把挂起的任务放回队列（语义同微信侧 quota.requeue_waiting）。"""
        try:
            if not self.quota.waiting_count():
                return 0
            self.quota.check(self.limits)
        except QuotaExceeded:
            return 0
        except Exception:                           # noqa: BLE001
            return 0
        with self._lock:
            count = self.quota.requeue_waiting()
        if count:
            logging.info('qq_quota_resumed requeued=%d', count)
        return count

    # ---------- 共享状态 ----------
    def note_reply_sent(self, chat_key, priority, confirmed=True):
        """记下"机器人刚在这里说过话"。频率闸、群追问判定都读它。

        confirmed=False（发送结果 unknown）时只更新"刚说过话"，不动
        last_send_ok_at——那个字段的语义是"最近一次**确认**发出"。
        """
        now = self._clock()
        with self._lock:
            self._last_reply[chat_key] = now
            if confirmed:
                self.last_send_ok_at = now
                self.last_error = ''
            if _int(priority, -1) == PRIORITY_GROUP_PLAIN:
                stamps = [t for t in self._plain_replies.get(chat_key, ())
                          if now - t < HOUR]
                stamps.append(now)
                self._plain_replies[chat_key] = stamps

    def last_reply_at(self, chat_key):
        with self._lock:
            return float(self._last_reply.get(chat_key, 0) or 0)

    def plain_reply_times(self, chat_key):
        with self._lock:
            return list(self._plain_replies.get(chat_key, ()))

    def image_allowed(self, chat_key, cap):
        """该会话一小时内发图是否还没到上限。"""
        now = self._clock()
        with self._lock:
            stamps = [t for t in self._image_times.get(chat_key, ())
                      if now - t < HOUR]
            self._image_times[chat_key] = stamps
            return len(stamps) < max(1, _int(cap, 1))

    def note_image_sent(self, chat_key):
        now = self._clock()
        with self._lock:
            self._image_times.setdefault(chat_key, []).append(now)

    def note_error(self, message):
        self.last_error = str(message or '')[:300]

    def _bump(self, name):
        with self._lock:
            self._counters[name] = self._counters.get(name, 0) + 1

    def counters(self):
        with self._lock:
            return dict(self._counters)

    # ---------- 注入点 ----------
    def model(self):
        """模型门面（懒加载：真正构造 StepPlan 要读密钥/建 provider，别在 __init__ 里做）。"""
        if self._model is None:
            factory = self._model_factory or _default_model_factory
            self._model = _invoke(factory, self.cfg, self.db, self.state_dir)
        return self._model

    def searcher(self):
        if self._searcher is None:
            factory = self._searcher_factory or _default_searcher_factory
            self._searcher = _invoke(factory, self.cfg, self.db)
        return self._searcher

    def search_fn(self):
        """给模型用的搜索执行器：**一次回复最多查一次**（第二道闸在这里）。"""
        state = {'used': 0}

        def run(text):
            if state['used'] >= 1:
                return []
            state['used'] += 1
            query = str(text or '').strip()
            if not query:
                return []
            client = self.searcher()
            if client is None:
                return []
            try:
                if self._search_params is None:
                    self._search_params = _param_names(client.search)
                if 'aliases' in self._search_params:
                    return client.search(query, aliases=tuple(self.aliases))
                return client.search(query)
            except Exception as exc:                # noqa: BLE001 搜索失败不能拖垮回复
                logging.warning('qq_search_failed type=%s reason=%s',
                                type(exc).__name__, str(exc)[:120])
                return []

        return run

    def image_generator(self):
        if self._image is None:
            factory = self._image_factory or _default_image_generator_factory
            self._image = _invoke(factory, self.cfg, self.state_dir)
        return self._image

    def fetch_image(self, url, dest_dir, *, max_bytes=None, timeout_s=None):
        """下载一张图片（唯一出网点）。可注入：离线测试给替身，绝不真的出网。"""
        fetcher = self._fetcher or media.fetch_image
        kwargs = {}
        if max_bytes is not None:
            kwargs['max_bytes'] = int(max_bytes)
        if timeout_s is not None:
            kwargs['timeout_s'] = float(timeout_s)
        return fetcher(url, dest_dir, **kwargs)

    def gather_sources(self, messages):
        """消息里的 http(s) 链接 → web_sources（契约 §7.1）。

        三条纪律：
        1. 最多 links.max_urls 个、整批最多 links.total_budget_seconds 秒——
           单条 URL 的超时会被压到"剩余预算"以内（web_reader 允许 4 次跳转，
           不压的话一个 URL 最坏能跑到 40 秒，把这一轮回复整个卡住）；
        2. 任何失败/超时/超量都只记一个状态条目，**绝不抛出**；
        3. 只读公网 http/https——私网/本机/带凭据/非标端口全由 web_reader 挡掉。

        返回的条目会原样进 model.reply 的 web_sources（StepPlan 标成 untrusted）。
        """
        conf = self.links_conf if isinstance(self.links_conf, dict) else {}
        if not conf.get('enabled'):
            return []
        try:
            limit = max(0, int(conf.get('max_urls', 2)))
        except (TypeError, ValueError):
            limit = 2
        if limit <= 0:
            return []
        urls = extract_urls(messages, limit)
        if not urls:
            return []
        try:
            budget = max(0.0, float(conf.get('total_budget_seconds', 12) or 0))
        except (TypeError, ValueError):
            budget = 12.0
        try:
            per_url = max(1.0, float(conf.get('timeout', 10) or 10))
        except (TypeError, ValueError):
            per_url = 10.0
        fetcher = self._link_fetcher or _default_link_fetcher
        started = self._clock()
        results = []
        for url in urls:
            remaining = budget - (self._clock() - started)
            if remaining <= 0:
                results.append({'url': url, 'status': 'skipped_budget'})
                logging.info('qq_link_skipped_budget url=%s', url[:60])
                continue
            block = dict(conf)
            block['timeout'] = max(1.0, min(per_url, remaining))
            try:
                item = fetcher(url, block)
            except Exception as exc:                # noqa: BLE001 读不到网页不该影响回文字
                results.append({'url': url, 'status': 'unreadable',
                                'reason': type(exc).__name__})
                logging.info('qq_link_unreadable url=%s type=%s', url[:60],
                             type(exc).__name__)
                continue
            if isinstance(item, dict):
                results.append(item)
        return results

    def image_prompt(self, ask):
        """生图提示词：OC 人设外观 + 用户原话（截断，防超长被接口拒）。"""
        from imagegen import oc_prefix
        own = str(self.cfg.get('image_prompt_prefix') or '').strip()
        try:
            prefix = own or oc_prefix()
        except Exception:                           # noqa: BLE001
            prefix = ''
        return ('以年糕.Agent 的 OC 形象画一张图。OC 外观：%s。用户要求：%s'
                % (prefix, str(ask or '')[:200]))[:3900]

    # ---------- 状态 ----------
    def status(self):
        """服务自述 + 原子写 status.json（契约 §7 的字段一个不少）。"""
        now = self._clock()
        with self._lock:
            try:
                depth = self.quota.depth()
                waiting = self.quota.waiting_count()
                stats = self.store.stats()
                sent_1h = self.store.count_sends(HOUR, 'ok')
            except sqlite3.Error as exc:
                # stop() 之后再问一次状态（看门狗收尾时会这么干）不能直接炸：
                # 库已经关了，就把计数类的字段当 0 报出去，进程状态照旧是准的。
                logging.warning('qq_status_db_unavailable type=%s', type(exc).__name__)
                depth, waiting, sent_1h, stats = 0, 0, 0, {}
            counters = dict(self._counters)
        payload = {
            'state': 'running' if self.running() else 'stopped',
            'heartbeat': now,
            'queue_depth': depth,
            'self_id': self.self_id(),
            'online': self._safe(lambda: bool(self.sender.online()), False),
            'last_event_at': self.last_event_at,
            'last_accepted_at': self.last_accepted_at,
            'last_send_ok_at': self.last_send_ok_at,
            'last_error': self.last_error,
            'sent_1h': sent_1h,
            'stop': self.any_stop(),
            # 以下是给人看的补充信息（契约没要求，但排查时全靠它）
            'auto_send': self.auto_send,
            'task_ttl_seconds': self.task_ttl_s,
            'worker_heartbeat': self.worker_heartbeat,
            'hot_heartbeat': self.hot_heartbeat,
            'queue_waiting_quota': waiting,
            'counters': counters,
            'store': stats,
            'state_dir': str(self.state_dir),
            'db_path': str(self.db_path),
        }
        self._write_status(payload)
        return payload

    def _write_status(self, payload):
        atomic_json(self.status_path, payload)

    @staticmethod
    def _safe(call, default):
        """状态查询绝不能因为发送通道抽风而失败。"""
        try:
            return call()
        except Exception:                           # noqa: BLE001
            return default


def _int(value, default):
    if isinstance(value, bool) or value is None:
        return int(default)
    try:
        return int(value)
    except (TypeError, ValueError):
        return int(default)


def _float(value, default):
    if isinstance(value, bool) or value is None:
        return float(default)
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _str_list(value):
    if isinstance(value, str) or not isinstance(value, (list, tuple, set, frozenset)):
        return []
    return [str(item).strip() for item in value
            if not isinstance(item, (dict, list, bool)) and str(item).strip()]
