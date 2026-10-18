"""队列处理循环：把一批入站消息变成一次真实回复（契约 v1 · 第 7 节）。

一次 process(row) 的顺序（每一步都只记日志，绝不向外抛异常）：

    记记忆/时间线 → STOP 检查 → 每小时上限 → 额度闸 → 生成 → 安全闸
    → 发送 → 明确要图时才生图并发送 → 记轮次

发送结果的三种结局必须分清楚（QQ 侧最容易踩的坑）：
    ok      → 记台账 + 记轮次 + 更新"上次发话时间"；
    unknown → 只记台账，**绝不重发**（请求可能已经出去了，重发就是双份）；
    failed  → 只记台账，本轮到此为止（不重发，理由同上：宁可少一句，不可重复说）。

Worker 是 QQService 的内部协作者：共享状态（锁、队列、记忆、上次发话时间）
全部由 QQService 持有，这里只负责"一代一轮"的逻辑，避免两处各存一份。
"""
import json
import logging
import time

from memory import LEARN_EVERY
from output_safe import OutputSafetyError, check_output
from quota import PRIORITY_GROUP_PLAIN, QuotaExceeded

from . import envelope, media

HOUR = 3600.0
DEFAULT_REPLY_MAX_CHARS = 200
DEFAULT_MAX_REPLIES_PER_HOUR = 30
DEFAULT_MAX_IMAGES = 2
DEFAULT_GEN_RETRIES = 1

# 风格自学习（契约 §7.1，语义照微信 resident.learn_cycle）
# 图片取不到时写进 text 的固定标记（真机缺陷回归，2026-10-18）
IMAGE_UNAVAILABLE_TEXT = '[图片未取到，无法查看]'

LEARN_INTERVAL_S = 3600.0        # 学成之后 1 小时内不再学
LEARN_MAX_INTERVAL_S = 86400.0   # 失败退避上限 24 小时
LEARN_SCAN_INTERVAL_S = 60.0     # 多久扫一次"谁攒够了样本"（防止每轮空扫）

# 与微信侧 resident.IMAGE_REPLY_DEFAULTS 逐字一致：只看"明确要图"的词，不猜意图。
IMAGE_REPLY_DEFAULTS = {
    'enabled': True,
    'keywords': ['发图', '发张图', '发个图', '来张图', '来一张', '画一张',
                 '画张', '画个', '生成图片', '发你张图'],
    'max_per_hour': 3,
}

# 结束状态写进 queue.state，出问题时能一眼看出"这条消息最后怎么了"
FINISH_CONTEXT_ONLY = 'CONTEXT_ONLY'
FINISH_STOPPED = 'STOPPED'
FINISH_AUTO_SEND_OFF = 'AUTO_SEND_OFF'
FINISH_EXPIRED = 'EXPIRED'
FINISH_RATE_LIMITED = 'RATE_LIMITED'
FINISH_QUOTA = 'WAITING_QUOTA'
FINISH_UNSAFE = 'UNSAFE'
FINISH_SENT = 'SENT'
FINISH_UNKNOWN = 'UNKNOWN'
FINISH_FAILED = 'FAILED'
FINISH_ERROR = 'ERROR'
FINISH_EMPTY = 'EMPTY'


def _int(value, default):
    """宽容取整：配置里写错类型时用默认值，不炸。"""
    if isinstance(value, bool) or value is None:
        return int(default)
    try:
        return int(value)
    except (TypeError, ValueError):
        return int(default)


class Worker:
    """QQService 的处理循环实现（单线程，只在 owner 线程里被调用）。"""

    def __init__(self, service):
        self.service = service
        self._learn_after = {}       # chat_key -> 这个时间点之前不再学
        self._learn_fails = {}       # chat_key -> 连续失败次数（指数退避用）
        self._learn_scan_at = 0.0    # 下一次扫"谁攒够样本"的时间

    # ---------- 主流程 ----------
    def process(self, row):
        """对外入口：兜住一切意外，绝不把"领走了却没收尾"的任务留在 PROCESSING。"""
        try:
            return self._process(row)
        except Exception as exc:                   # noqa: BLE001 兜底不能漏
            logging.error('qq_process_crashed id=%s chat=%s type=%s reason=%s',
                          row[0], row[1] if len(row) > 1 else '?',
                          type(exc).__name__, str(exc)[:160])
            self.service.note_error('处理异常: %s' % type(exc).__name__)
            self._finish_if_processing(row[0], FINISH_ERROR)
            return False

    def _finish_if_processing(self, qid, state):
        """只在任务还是 PROCESSING 时收尾：别覆盖已经写好的 RETRY_LATER 等状态。"""
        try:
            row = self.service.db.execute('SELECT state FROM queue WHERE id=?',
                                          (qid,)).fetchone()
            if row and row[0] == 'PROCESSING':
                self.service.quota.finish(qid, state)
        except Exception:                          # noqa: BLE001
            pass

    def _process(self, row):
        qid, chat_key, priority = row[0], row[1], row[2]
        task = _load_payload(row[4])
        messages = [m for m in (task.get('messages') or []) if isinstance(m, dict)]
        event = envelope.from_task(task)
        if event is None or not messages:
            self.service.quota.finish(qid, FINISH_EMPTY)
            return False

        # 回话意图与优先级都按**整批**算，而不是只信顶层那一个字段：
        # 同会话排队时 quota.merge_payloads 会把新 payload 的顶层字段当结果，
        # 只看顶层的话，"先被 @ 后来了句闲聊"这条 @ 就被降级成 context_only 了。
        wants = [m for m in messages if m.get('wants_reply')]
        wants_reply = task.get('action') == 'reply' or bool(wants)
        priority = _merge_priority(priority, wants)

        # ① 先记上下文：回不回、发不发得出去，这条消息都进了时间线与记忆。
        #    context_only 的意义全在这里——不回话也要有上下文。
        try:
            self._record_inbound(event, chat_key, messages)
        except Exception as exc:                   # noqa: BLE001 记不上也不能不回话
            logging.warning('qq_record_inbound_failed chat=%s type=%s',
                            chat_key, type(exc).__name__)

        # ② 整批都不需要回的（context_only），记完就走
        if not wants_reply:
            self.service.quota.finish(qid, FINISH_CONTEXT_ONLY)
            return False

        # ③ STOP：停手不出话（消息已入时间线，不会丢上下文）
        if self.service.any_stop():
            logging.info('qq_stop_skip chat=%s reason=stop_file', chat_key)
            self.service.quota.finish(qid, FINISH_STOPPED)
            return False

        # ③.5 总闸（契约 §9）：auto_send=false 时只记录、不发送。
        # 首次部署默认就是关的，验收通过后才在 qq.json 里打开。
        if not self.service.auto_send:
            logging.info('qq_auto_send_off chat=%s reason=auto_send_false', chat_key)
            self.service.quota.finish(qid, FINISH_AUTO_SEND_OFF)
            return False

        # ③.6 入队任务的保鲜期（task_ttl_seconds）：深夜排到第二天早上的活就别回了
        ttl = self.service.task_ttl_s
        age = self.service.clock() - float(row[3] or 0)
        if ttl > 0 and age > ttl:
            logging.info('qq_task_expired chat=%s age=%.0fs ttl=%.0fs', chat_key, age, ttl)
            self.service.quota.finish(qid, FINISH_EXPIRED)
            return False

        # ④ 每小时回复上限：到顶就退回 context_only（不花额度）
        cap = _int(self.service.cfg.get('max_replies_per_hour'),
                   DEFAULT_MAX_REPLIES_PER_HOUR)
        sent_last_hour = self._replies_last_hour(chat_key)
        if cap > 0 and sent_last_hour >= cap:
            logging.info('qq_reply_rate_limited chat=%s sent_1h=%d cap=%d',
                         chat_key, sent_last_hour, cap)
            self.service.quota.finish(qid, FINISH_RATE_LIMITED)
            return False

        # ⑤ 额度闸：用完就把任务挂起（等恢复后由循环放回），不丢
        try:
            self.service.quota.check(self.service.limits)
        except QuotaExceeded as exc:
            logging.warning('qq_quota_exhausted chat=%s reason=%s', chat_key, exc)
            self.service.note_error('额度已用尽: %s' % str(exc)[:80])
            self.service.quota.wait(qid)
            return False

        # ⑥ 生成
        try:
            reply = self._generate(chat_key, messages, priority)
        except OutputSafetyError as exc:
            # 安全闸拦下的回复绝不发给用户；退回 context_only 并记录原因
            logging.warning('qq_reply_blocked chat=%s reason=%s', chat_key, str(exc)[:80])
            self.service.note_error('输出未过安全闸: %s' % str(exc)[:80])
            self.service.quota.finish(qid, FINISH_UNSAFE)
            return False
        except Exception as exc:                   # noqa: BLE001 模型/网络什么都可能
            logging.error('qq_reply_failed chat=%s type=%s reason=%s',
                          chat_key, type(exc).__name__, str(exc)[:160])
            self.service.note_error('生成失败: %s' % type(exc).__name__)
            self._retry_or_finish(qid, chat_key, priority, task, FINISH_ERROR)
            return False

        # ⑦ 发送（发之前再查一次 STOP：生成期间可能刚被叫停）
        if self.service.any_stop():
            self.service.quota.finish(qid, FINISH_STOPPED)
            return False
        result = self.service.sender.send_text(event, reply)
        if result is None:
            result = _unknown('发送通道返回空')
        if result.unknown:
            # 可能已经发出去了：只记台账，绝不重发。
            # confirmed=False 很关键：这条**没有确认**，不能刷新 last_send_ok_at
            # （那个字段的语义是"最近一次确认发出"，被超时刷新就与 send_log 的
            # state=unknown 自相矛盾了）。但"刚说过话"要记——避免几秒内又说一遍。
            self.service.store.record_send(chat_key, 'text', 'unknown',
                                           result.error, ts=self.service.clock())
            self.service.note_reply_sent(chat_key, priority, confirmed=False)
            self._record_outbound(chat_key, reply)
            logging.warning('qq_send_unknown chat=%s reason=%s', chat_key,
                            result.error[:120])
            self.service.quota.finish(qid, FINISH_UNKNOWN)
            return True
        if not result.ok:
            self.service.store.record_send(chat_key, 'text', 'failed',
                                           result.error, ts=self.service.clock())
            logging.error('qq_send_failed chat=%s reason=%s', chat_key,
                          result.error[:120])
            self.service.quota.finish(qid, FINISH_FAILED)
            return True

        self.service.store.record_send(chat_key, 'text', 'ok',
                                       result.message_id, ts=self.service.clock())
        self.service.note_reply_sent(chat_key, priority)
        self._record_outbound(chat_key, reply)
        self.service.quota.finish(qid, FINISH_SENT)
        self.service.quota.note_served(chat_key)
        logging.info('qq_reply_sent chat=%s priority=%s chars=%d',
                     chat_key, priority, len(reply))

        # ⑧ 生图：文字已确认发出，图是附加项。图失败**不重发文字**、不回滚。
        if self._wants_image(messages):
            self._send_image(event, chat_key, messages)
        return True

    # ---------- 入站记录 ----------
    def _record_inbound(self, event, chat_key, messages):
        """下载图片 + 写记忆与时间线。图片下载失败只当下纯文字消息处理。"""
        conf = self._media_conf()
        # 结果按 URL 精确对应，不再按顺序 pop：那种写法在「前一条的图挂了、
        # 后一条的图成功」时，会把后一条的图算到前一条头上（张冠李戴）。
        outcomes = {}
        for url in media.within_event_limit(event, conf['max_images']):
            outcomes[url] = self.service.fetch_image(
                url, self.service.media_dir,
                max_bytes=conf['max_bytes'], timeout_s=conf['timeout_s']) or ''
        self.service.memory.note_messages(chat_key, len(messages), event.kind,
                                          event.sender_name)
        for message in messages:
            original = str(message.get('text') or '')
            image_path, missing = _resolve_images(message, outcomes)
            if missing and not image_path:
                # 取不到图就必须**说出来**：真机实测（2026-10-18 19:46）消息是
                # 图片 + 这张图里是什么、图片 URL 超时，模型只收到一条 kind=image、
                # text 为空、又没附件的新消息，它就把 OC 人设脑补成了图片内容，
                # 描述得煞有介事。用户最反感装懂。
                message['text'] = (original + ' ' + IMAGE_UNAVAILABLE_TEXT).strip()
                message['image_missing'] = True
                logging.info('qq_image_unavailable chat=%s url_count=%d', chat_key,
                             len(message.get('images') or []))
            # 用户发言落库成 user turn（学习样本与多轮历史的来源，与微信侧 P1-9 同一做法）：
            # 这里刻意记**用户原话**而不是带标记的文本——标记是给模型/时间线看的，
            # 不该混进这个人的说话风格学习样本里。原话本来就空时才退回标记。
            self.service.memory.record_turn(chat_key, 'user',
                                            (original or message['text'])[:500])
            self.service.memory.add_timeline(
                chat_key, 'in', str(message.get('kind') or 'text'),
                str(message.get('text') or ''), image_path,
                at_me=1 if message.get('at_me') else 0,
                ts=float(message.get('ts') or 0) or self.service.clock())

    def _record_outbound(self, chat_key, reply):
        """机器人说过的话也要进记忆与时间线，否则下一轮会失忆。"""
        try:
            self.service.memory.record_turn(chat_key, 'assistant', reply)
            self.service.memory.add_timeline(chat_key, 'out', 'text', reply)
        except Exception as exc:                   # noqa: BLE001
            logging.warning('qq_record_outbound_failed chat=%s type=%s',
                            chat_key, type(exc).__name__)

    # ---------- 生成 ----------
    def _generate(self, chat_key, messages, priority):
        """组装上下文 → 调模型 → 过安全闸。返回可直接发送的文字。"""
        service = self.service
        context = service.memory.context_for(chat_key)
        fresh = [{'direction': 'in',
                  'kind': str(m.get('kind') or 'text'),
                  'text': str(m.get('text') or ''),
                  'description': str(m.get('description') or ''),
                  'signature': str(m.get('signature') or '')} for m in messages]
        query = ' '.join(m['text'] for m in fresh if m['text'])
        # 热榜只用**本地缓存**（relevant 不联网）：QQ 侧不额外引入网络依赖
        hot = service.feed.relevant(query) if query else []
        # 链接阅读（契约 §7.1）：消息里有 http(s) 链接就去读一下。
        # 受 links 段预算约束，读不到只留个状态条目，绝不影响回文字。
        sources = service.gather_sources(messages)
        if sources:
            logging.info('qq_links_read chat=%s urls=%d', chat_key, len(sources))
        model = service.model()
        try:
            model.session_for(chat_key)            # 供应商侧会话隔离（失败不影响回复）
        except Exception:                          # noqa: BLE001
            pass
        try:
            reply = model.reply(fresh, context.get('recent_turns', []), sources,
                                chat_context=context, hot_items=hot,
                                search_fn=service.search_fn())
        finally:
            # 额度按"发起过一次模型调用"记：失败也花了这一次
            service.quota.consume(priority)
        return check_output(reply, service.reply_max_chars)

    def _retry_or_finish(self, qid, chat_key, priority, task, state):
        """生成失败最多重排一次：模型偶尔抽风，但没有上限的重排会变成死循环。"""
        tries = _int(task.get('gen_retries'), 0)
        if tries < DEFAULT_GEN_RETRIES:
            task['gen_retries'] = tries + 1
            self.service.quota.finish(qid, 'RETRY_LATER')
            self.service.quota.enqueue(chat_key, priority,
                                       json.dumps(task, ensure_ascii=False))
            self.service.quota.note_yield(chat_key)
            logging.info('qq_reply_retry chat=%s attempt=%d', chat_key, tries + 1)
            return
        self.service.quota.finish(qid, state)

    # ---------- 配置 ----------
    def _media_conf(self):
        """契约 §9 的 media 段；保留早期顶层别名做兜底。"""
        cfg = self.service.cfg
        block = cfg.get('media') if isinstance(cfg.get('media'), dict) else {}
        return {
            'max_bytes': _int(block.get('max_bytes'),
                              _int(cfg.get('media_max_bytes'), media.MAX_BYTES)),
            'timeout_s': _int(block.get('timeout_s'),
                              _int(cfg.get('media_timeout_s'), media.TIMEOUT_S)),
            'max_images': _int(block.get('max_images'),
                               _int(cfg.get('max_images_per_event'), DEFAULT_MAX_IMAGES)),
            'keep_days': _int(block.get('keep_days'), 14),
        }

    # ---------- 生图 ----------
    def _image_conf(self):
        """契约 §9 的 image_generation 段。

        默认**关**：生图花钱且要凭据，只有配置里明确 enabled=true 才动手。
        关键词表沿用微信侧那一套（写死，不给配置改），只看"明确要图"的词，不猜意图。
        """
        block = self.service.cfg.get('image_generation')
        block = block if isinstance(block, dict) else {}
        enabled = block.get('enabled')
        per_hour = block.get('max_per_hour')
        return {'enabled': bool(enabled) if isinstance(enabled, bool) else False,
                'max_per_hour': (_int(per_hour, IMAGE_REPLY_DEFAULTS['max_per_hour'])
                                 if not isinstance(per_hour, bool) else
                                 IMAGE_REPLY_DEFAULTS['max_per_hour']),
                'keywords': IMAGE_REPLY_DEFAULTS['keywords']}

    def _wants_image(self, messages):
        """只看用户消息里有没有明确的要图词；不猜意图、不看回复内容。"""
        conf = self._image_conf()
        if not conf.get('enabled'):
            return False
        words = [str(w) for w in (conf.get('keywords') or []) if str(w).strip()]
        text = ' '.join(str(m.get('text') or '') for m in messages)
        return any(word in text for word in words)

    def _send_image(self, event, chat_key, messages):
        """文字已经发出去了：图成功就记一笔，失败只记日志（不重发文字）。"""
        service = self.service
        conf = self._image_conf()
        cap = max(1, _int(conf.get('max_per_hour'), 3))
        if not service.image_allowed(chat_key, cap):
            logging.info('qq_image_rate_limited chat=%s cap=%d', chat_key, cap)
            return False
        ask = ' '.join(str(m.get('text') or '') for m in messages)[:200]
        try:
            prompt = service.image_prompt(ask)
        except Exception as exc:                   # noqa: BLE001 提示词都拼不出来就别画了
            logging.error('qq_image_prompt_failed chat=%s type=%s',
                          chat_key, type(exc).__name__)
            return False
        try:
            path = service.image_generator()(prompt)
        except Exception as exc:                   # noqa: BLE001 图失败不能拖垮文字回复
            logging.error('qq_image_failed chat=%s type=%s reason=%s',
                          chat_key, type(exc).__name__, str(exc)[:140])
            service.note_error('生图失败: %s' % type(exc).__name__)
            return False
        if not path:
            service.note_error('生图未产出图片')
            return False
        result = service.sender.send_image(event, path)
        if result is None:
            result = _unknown('发送通道返回空')
        state = 'unknown' if result.unknown else ('ok' if result.ok else 'failed')
        service.store.record_send(chat_key, 'image', state, result.error or str(path),
                                  ts=service.clock())
        if result.ok and not result.unknown:
            service.note_image_sent(chat_key)
            service.memory.add_timeline(chat_key, 'out', 'image', '', str(path))
            logging.info('qq_image_sent chat=%s path=%s', chat_key, str(path)[:120])
        else:
            logging.warning('qq_image_send_%s chat=%s reason=%s', state, chat_key,
                            str(result.error)[:120])
        return True

    # ---------- 风格自学习 ----------
    def learn_cycle(self):
        """空闲时学一次风格（契约 §7.1，语义照微信 resident.learn_cycle）。

        触发条件：某会话 note_messages 累计 >= LEARN_EVERY(20) 条、队列空闲、
        且不在退避期。学一次花一次额度（priority=GROUP_PLAIN）。
        学到的 style/facts 只写进**该 chat_key** 的档案——ChatMemory 按 chat_key
        分表，天然保证跨会话、跨平台互不污染。
        一轮最多学一个会话（每次学习要花好几秒 + 一次额度，别一口气全学完）。
        """
        service = self.service
        now = service.clock()
        if now < self._learn_scan_at:
            return False
        self._learn_scan_at = now + LEARN_SCAN_INTERVAL_S
        try:
            rows = service.memory.db.execute(
                'SELECT chat_key FROM profiles WHERE pending>=? ORDER BY pending DESC',
                (LEARN_EVERY,)).fetchall()
        except Exception as exc:                    # noqa: BLE001 扫不动就下轮再说
            logging.warning('qq_learn_scan_failed type=%s', type(exc).__name__)
            return False
        for (chat_key,) in rows:
            if now < self._learn_after.get(chat_key, 0):
                continue
            sample = service.memory.learning_sample(chat_key)
            if not sample:
                # 样本被安全闸筛空了：别每轮白扫一次，等一小时再来
                self._learn_after[chat_key] = now + LEARN_INTERVAL_S
                logging.info('qq_learn_no_sample chat=%s', chat_key)
                continue
            return self._learn_one(chat_key, sample)
        return False

    def _learn_one(self, chat_key, sample):
        service = self.service
        now = service.clock()
        try:
            service.quota.check(service.limits)
        except QuotaExceeded:
            logging.info('qq_learn_paused_quota chat=%s', chat_key)
            return False
        except Exception as exc:                    # noqa: BLE001
            logging.warning('qq_learn_quota_check_failed type=%s', type(exc).__name__)
            return False
        try:
            service.quota.consume(PRIORITY_GROUP_PLAIN)   # 学一次算一次模型调用
        except Exception as exc:                    # noqa: BLE001
            logging.warning('qq_learn_consume_failed type=%s', type(exc).__name__)
        try:
            ok = bool(service.memory.learn(chat_key, sample, service.model()))
        except Exception as exc:                    # noqa: BLE001 学习失败不该影响回复
            logging.warning('qq_learn_failed chat=%s type=%s reason=%s',
                            chat_key, type(exc).__name__, str(exc)[:120])
            ok = False
        if ok:
            self._learn_fails.pop(chat_key, None)
            self._learn_after[chat_key] = now + LEARN_INTERVAL_S
            logging.info('qq_learned chat=%s samples=%d', chat_key, len(sample))
            return True
        fails = self._learn_fails.get(chat_key, 0) + 1
        self._learn_fails[chat_key] = fails
        wait = self._learn_backoff(fails)
        self._learn_after[chat_key] = now + wait
        logging.warning('qq_learn_failed chat=%s samples=%d retry_after_h=%.1f',
                        chat_key, len(sample), wait / HOUR)
        return False

    @staticmethod
    def _learn_backoff(fails):
        """失败退避：1h → 2h → 4h → …，上限 24h。

        每次尝试要花好几秒（还可能连着失败），退避是为了别一直白花；
        上限 24h 是为了"改好了配置不用等到天荒地老"。
        """
        try:
            count = max(1, int(fails))
        except (TypeError, ValueError):
            count = 1
        return min(LEARN_INTERVAL_S * (2 ** (count - 1)), LEARN_MAX_INTERVAL_S)

    # ---------- 计数 ----------
    def _replies_last_hour(self, chat_key):
        """该会话一小时内已经回了多少条（契约要求用 turns 表计数）。

        这里刻意用系统时钟而不是注入时钟：turns 是 memory.record_turn 写的，
        它内部固定用 time.time()，拿另一个时钟去比会数错。
        """
        try:
            row = self.service.memory.db.execute(
                "SELECT count(*) FROM turns WHERE chat_key=? AND role='assistant'"
                ' AND created>?', (chat_key, time.time() - HOUR)).fetchone()
        except Exception:                          # noqa: BLE001 查不到就按没回过
            return 0
        return int(row[0]) if row else 0


def _resolve_images(message, outcomes):
    """→ (本地图片路径, 有没有图片没拿到)。

    按 URL 精确对上自己的下载结果：一条消息可能带多张图，也可能一张都没下成
    （超时 / 超每事件上限 / 空链接），这些都必须能被认出来，才能如实告诉模型。
    """
    images = [i for i in (message.get('images') or []) if isinstance(i, dict)]
    if not images:
        return '', False
    missing = False
    for image in images:
        url = str(image.get('url') or '').strip()
        if not url or url not in outcomes:
            missing = True                      # 空链接、或超出每事件上限没去下
            continue
        if outcomes[url]:
            return str(outcomes[url]), False
        missing = True                          # 下载失败
    return '', missing


def _merge_priority(claimed, wants):
    """一批合并任务按**最紧急**的那条消息算优先级（数字越小越紧急）。

    不然"先被 @（GROUP_AT）后来了句闲聊（GROUP_PLAIN）"合并后会被当成普通闲聊，
    既排错队，也会污染 plain 回复的冷却/每小时上限账本。
    """
    best = claimed
    for message in wants:
        value = message.get('wants_priority')
        if isinstance(value, bool) or not isinstance(value, int):
            continue
        if isinstance(best, bool) or not isinstance(best, int) or value < best:
            best = value
    return best


def _load_payload(payload):
    try:
        task = json.loads(payload or '{}')
    except (TypeError, ValueError):
        return {}
    return task if isinstance(task, dict) else {}


def _unknown(reason):
    from .bridge import SendResult
    return SendResult(ok=False, unknown=True, error=reason)
