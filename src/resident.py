"""常驻机器人：分级入队、共用额度池、分会话记忆、排队发送。缺Key/异常时默认不发。"""
import argparse, fcntl, hashlib, json, logging, os, re, signal, sqlite3, threading, time
from pathlib import Path
from urllib.parse import urlsplit
from wechat_ui import (WeChatUI, SafetyError, UIUnavailable, normalize,
                       prepare_png_bytes)
from imagegen import generate as generate_image, oc_prefix, OC_REF
from multimodal import StepPlan, STATE, ModelUnavailable
from web_reader import fetch_public_text
from quota import (Quota, QuotaExceeded, PRIORITY_GROUP_AT, PRIORITY_DIRECT,
                   PRIORITY_GROUP_PLAIN, PRIORITY_NAMES)
from search import HotFeed, needs_search, ROUTES as HOT_ROUTES
from web_search import WebSearch
from moments import MomentComposer
from moment_release import MomentRelease, ReleaseError, load_coords
from moments_publisher import PublisherError
from moment_interact import MomentInbox, InteractionPipeline, BATCH_SIZE
from chat_navigator import (ChatNavigator, row_band_sig, row_changed,
                            avatar_rows, avatar_key)
from direct_registry import DirectRegistry
from direct_discovery import DirectDiscovery
from memory import ChatMemory
from output_safe import check_output, OutputSafetyError
from ui_lease import ui_lease, UILeaseBusy

ROOT = Path(__file__).resolve().parent.parent
CONFIG = ROOT/'config'/'resident.json'


def with_discovered(cfg):
    return DirectRegistry(STATE/'direct-friends.json').apply(cfg)
DEFAULT_LIMITS = {'window_5h': 6000, 'window_1d': 70000}


def atomic_json(path, value):
    temp = path.with_suffix('.tmp')
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2))
    temp.chmod(0o600)
    temp.replace(path)


def fingerprint(image):
    return hashlib.sha256(image.convert('RGB').tobytes()).hexdigest()


def frames_similar(a, b, tol=0.05):
    """两帧是否"基本一致"：容忍动态内容造成的少量像素变化。

    原来用 sha256 全等比较，聊天里只要有一个持续变化的东西（对面机器人连发、
    动图、收到新消息），画面就永远"不稳定"：观察卡在 debouncing，
    发送前校验永远 CHANGED，整条会话直接哑掉（2026-10-17 实录：测试群里
    对面机器人一路说话，年糕.Agent 五分钟没回一条）。
    缩到 64x48 灰阶再比，"变了多少"比"完全一样"更贴近真正想知道的事。
    """
    if a is None or b is None or a.size != b.size:
        return False
    import numpy as np
    x = np.asarray(a.convert('L').resize((64, 48)), dtype='int16')
    y = np.asarray(b.convert('L').resize((64, 48)), dtype='int16')
    return bool((np.abs(x - y) > 24).mean() <= tol)


def chat_key_of(cfg, title, chat_type=None):
    """群聊只准精确白名单；已确认私信按黑名单。类型未知时拒绝猜测。

    标题本身不能证明是私信（群名不一定含“群”）。chat_type 必须来自
    已核验的 UI 类型或人工 chat_types 配置；旧 target_chat 与
    direct_whitelist 均视为已登记私信。
    """
    t = normalize(title)
    if not t:
        return None
    groups = {normalize(g): g for g in cfg.get('group_whitelist', []) if normalize(g)}
    types = {normalize(k): v for k, v in cfg.get('chat_types', {}).items()}
    kind = chat_type if chat_type is not None else types.get(t)
    # 仅接受微信完整标题尾部的成员数，不接受截断名/任意前缀匹配。
    base = re.sub(r'[（(][0-9]+[）)]$', '', t)
    group_name = t if t in groups else base if base in groups else None
    if kind == 'group' or (kind is None and group_name is not None):
        return 'group:' + groups[group_name] if group_name is not None else None
    registered = {normalize(x) for x in cfg.get('direct_whitelist', []) if normalize(x)}
    registered.add(normalize(cfg.get('target_chat', '')))
    if kind is None and t in registered:
        kind = 'direct'
    if kind != 'direct':
        return None
    if t in {normalize(x) for x in cfg.get('direct_blacklist', [])}:
        return None
    return 'direct:' + title



def gather_sources(messages, cfg):
    urls = []
    for m in messages:
        # URL 只吃 ASCII 字符集：老写法 [^\s<>"\u3000]+ 会把紧跟的中文一起吞掉
        # （"看这个 https://a/b，挺好的" 会抠成 "https://a/b，挺好的"，拿去请求必然 404）。
        for url in re.findall(r"https?://[A-Za-z0-9\-._~:/?#\[\]@!$&'()*+,;=%]+",
                              m.get('text', '')):
            url = url.rstrip(".,;:!?)]}'")
            if url not in urls:
                urls.append(url)
    results = []
    if not cfg['links']['enabled']:
        return results
    # 总预算：抓网页是最慢的一步（单次超时 10s，允许 4 次跳转 → 一个 URL 最坏 40s）。
    # 不设上限的话，一条带两个链接的消息能把这一轮回复卡住一分多钟。
    budget = float(cfg['links'].get('total_budget_seconds', 12) or 12)
    started = time.time()
    for url in urls[:cfg['links']['max_urls']]:
        if time.time() - started > budget:
            results.append({'url': url, 'status': 'skipped_budget'})
            logging.info('link_skipped_budget url=%s', url[:60])
            continue
        try:
            results.append(fetch_public_text(url, cfg['links']))
        except Exception as e:
            results.append({'url': url, 'status': 'unreadable', 'reason': type(e).__name__})
    return results


def trailing_new(previous, current):
    """保守重叠：找不到连续区间就返回 None（重建基线，不回放历史）。"""
    if not previous:
        return None
    for n in range(min(len(previous), len(current)), 0, -1):
        for start in range(len(current)-n, -1, -1):
            if current[start:start+n] == previous[-n:]:
                return start+n
    return None


class _QuotedOCR:
    """OCR 模型包装：每次调用前扣共用额度；额度不足就禁用模型兜底，退回本地 OCR 结果。"""

    def __init__(self, resident, cfg, model):
        self.resident, self.cfg, self.model = resident, cfg, model

    def ocr_bubble_image(self, image):
        self.resident.spend(self.model, self.cfg, PRIORITY_GROUP_PLAIN, 'ocr')
        return self.model.ocr_bubble_image(image)

    def ocr_bubbles_image(self, image, bboxes):
        """批量读多个气泡（一次调用读全部）。

        这个方法和上面的单气泡版是两条不同的路：观察管道走的是**批量**这条
        （visual_parse.ocr_bubbles(..., force=True)）。2026-10-17 实测发现这里
        缺了批量版本 —— 调用直接 AttributeError，被 ocr_bubbles 的 except 吞掉，
        于是"用模型纠正本地 OCR"的功能**从来没有真正跑过**：群里读到的永远是
        tesseract 的原始错字（@年糕 被读成 @#ik，机器人就照着错字回话）。
        """
        self.resident.spend(self.model, self.cfg, PRIORITY_GROUP_PLAIN, 'ocr')
        return self.model.ocr_bubbles_image(image, bboxes)


BASELINE_STATE_VERSION = 2


class Resident:
    def __init__(self):
        os.umask(0o077)
        STATE.mkdir(parents=True, exist_ok=True)
        STATE.chmod(0o700)
        self.lock = open(STATE/'instance.lock', 'w')
        fcntl.flock(self.lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        self.db = sqlite3.connect(STATE/'ledger.sqlite')
        self.db.execute('CREATE TABLE IF NOT EXISTS deliveries('
                        ' id INTEGER PRIMARY KEY, created REAL, state TEXT, digest TEXT)')
        self.quota = Quota(self.db)
        self.memory = ChatMemory(self.db)
        self.feed = HotFeed(self.db)
        self.moments = None  # 懒加载（需要 model）
        self.release = None  # 懒加载（需要 ui + 坐标标定）
        self.inbox = MomentInbox(self.db)
        self.interact = None  # 懒加载（需要 model）
        self.nav = None      # 懒加载（需要 ui）
        self._row_sigs = {}      # 会话名 -> 列表行像素签名（判断这轮要不要切进去）
        self._row_y = {}         # 会话名 -> 列表行中心 y（上次成功切换时记下）
        self._avatar_of = {}     # 会话名 -> 头像指纹（把"行"和"会话"绑定，不靠 OCR 名字）
        self._visited_at = {}    # 会话名 -> 最近一次切进去观察的时间（防连续重访）
        self._last_sweep = 0     # 上次全量扫描所有会话的时间
        self.baselines = {}      # chat_key -> [signature,...]
        self.last_frame = {}     # chat_key -> 观察时的聊天区截图（发送前比对用）
        self.last_hash = {}      # chat_key -> 指纹
        self.last_sent = {}      # chat_key -> 时间
        self.image_sent = {}     # chat_key -> [发图时间]，回复链路每小时上限用
        self.last_reply_at = {}  # chat_key -> 上次真正发出回复的时间（群追问判定用）
        self.plain_replies = {}  # 群名 -> [普通接话时间]，用于冷却与每小时上限
        self.last_remind = {}    # chat_key -> 上次休息提醒时间
        self.chat_failures = {}  # chat name -> 连续观察失败次数
        self.seen_signatures = {}
        self._load_seen()
        self.history = {}        # chat_key -> [turns]
        self.running = True
        self.failures = 0
        self.stop = STATE/'STOP'
        signal.signal(signal.SIGTERM, lambda *_: setattr(self, 'running', False))
        signal.signal(signal.SIGINT, lambda *_: setattr(self, 'running', False))

    def _model_brief(self):
        """给 status.json 用的模型概况：健康检查/看门狗靠它发现认证失败和熔断。"""
        model = getattr(self, '_model', None)
        if model is None:
            return None
        try:
            mh = model.health()['main']
            return {'provider': mh['name'], 'model': mh['model'], 'key_present': mh['key_present'],
                    'circuit_open': mh['circuit_open'], 'disabled': mh['disabled_reason'],
                    'last_error': mh['last_error']}
        except Exception:                                  # noqa: BLE001
            return None

    def status(self, state, **kw):
        self._last_status = {'state': state, **kw}
        q = self.quota.status()
        atomic_json(STATE/'status.json', {
            'state': state, 'heartbeat': time.time(), 'pid': os.getpid(),
            'queue_depth': self.quota.depth(), 'quota_used_5h': q['used_5h'],
            'quota_used_1d': q['used_1d'], 'auto_publish_moments': False,
            'poll_health': getattr(self, 'last_poll', None),
            'model': self._model_brief(), **kw})

    @staticmethod
    def _note_seen(seen, sigs, keep=600):
        """登记"已见过"的签名。dict 当有序集合用：保留最近 keep 条，超出裁掉最老的。

        内存里也要有上限：跑几个月就是几万个签名，一直涨没意义。
        """
        for s in sigs:
            seen[s] = True
        if len(seen) > keep * 2:
            for key in list(seen.keys())[:len(seen) - keep]:
                del seen[key]

    def _persist_seen(self):
        """基线/已见签名落盘：重启后仍能识别停机期间到达的新消息，而不是吞进新基线。

        带版本与结构校验：损坏或结构不符一律视为无基线（重新观察建基线），
        绝不把不可信内容当已见集合，避免历史消息被当成新消息回放。
        """
        try:
            atomic_json(STATE / 'baselines.json', {
                'version': BASELINE_STATE_VERSION,
                'baselines': self.baselines,
                'seen': {ck: list(sigs)[-400:] for ck, sigs in
                         self.seen_signatures.items()},
                'saved_at': time.time()})
        except Exception as e:      # noqa: BLE001
            # 落盘失败不致命（内存里还在跑），但一定要能查到原因
            logging.error('baseline_persist_failed type=%s reason=%s',
                          type(e).__name__, str(e)[:120])

    def _load_seen(self):
        try:
            data = json.loads((STATE / 'baselines.json').read_text())
        except Exception as e:      # noqa: BLE001 读不到就当没有：重建基线，绝不回放历史
            logging.warning('baseline_state_unreadable type=%s reason=%s',
                            type(e).__name__, str(e)[:100])
            return
        if not isinstance(data, dict) or data.get('version') != BASELINE_STATE_VERSION:
            logging.warning('baseline_state_unusable_rebuilding')
            return
        baselines = data.get('baselines')
        seen = data.get('seen')
        if not isinstance(baselines, dict) or not isinstance(seen, dict):
            logging.warning('baseline_state_shape_invalid_rebuilding')
            return
        clean_b, clean_s = {}, {}
        for ck, sigs in baselines.items():
            if isinstance(ck, str) and isinstance(sigs, list):
                clean_b[ck] = [s for s in sigs if isinstance(s, str)][-400:]
        for ck, sigs in seen.items():
            if isinstance(ck, str) and isinstance(sigs, list):
                # 用 dict 当"有序集合"：要保留"最近见过的"才有意义——
                # set 是无序的，落盘时 sorted()[-400:] 会把最近的消息随机丢掉，
                # 重启后那条消息又被当成新消息，重复回一遍（2026-10-17 复核发现）。
                clean_s[ck] = {s: True for s in sigs if isinstance(s, str)}
        self.baselines, self.seen_signatures = clean_b, clean_s

    def spend(self, model, cfg, priority, what):
        """统一扣额度：先检查再消耗；超限就跳过本次调用。"""
        limits = cfg.get('limits', DEFAULT_LIMITS)
        self.quota.check(limits)
        self.quota.consume(priority)

    # ---------- 观察（多会话轮询） ----------
    def watch_list(self, cfg):
        """监控清单：白名单群（+ 启用时的登记私信）。

        默认只监控显式列出的会话；不在任何清单里的标题一律不轮询、不允许发送。
        direct_enabled=false 时**完全不看私聊**（2026-10-17 用户决定只保留群聊）。
        私聊代码与测试都留着：改回 true 就恢复，不用动别的地方。
        """
        names = []
        if cfg.get('direct_enabled', True):
            if cfg.get('target_chat'):
                names.append(cfg['target_chat'])
            for c in cfg.get('direct_whitelist', []) or []:
                if c and c not in names:
                    names.append(c)
        for c in cfg.get('watch_chats', []):
            if c and c not in names:
                names.append(c)
        return names

    def observe_one(self, cfg, ui, model, name, image):
        """观察单个会话（已切换并验过标题）。返回是否入队。"""
        ck = chat_key_of(cfg, name)
        if not ck:
            return False
        digest = fingerprint(ui.chat_image(image))
        if self.last_hash.get(ck) == digest:
            self.status('watching', chat=ck, baseline_ready=bool(self.baselines.get(ck)))
            return False
        # 画面可能永远"不稳定"（对面机器人连发消息、聊天里有动图）：
        # 最多重试 debounce_retries 次，仍在动就用最新一帧继续，绝不整段哑掉。
        stable = None
        tries = max(1, int(cfg.get('debounce_retries', 3)))
        for _ in range(tries):
            time.sleep(cfg['debounce_seconds'])
            candidate = ui.capture()
            if frames_similar(ui.chat_image(candidate), ui.chat_image(image)):
                stable = candidate
                break
            image = candidate
        if stable is None:
            stable = image
            logging.info('debounce_timeout chat=%s tries=%d', ck, tries)
        from visual_parse import (extract_messages, classify, ocr_bubbles,
                                   has_at_mention, mentions_me)
        aliases = cfg.get('mention_aliases') or [cfg.get('bot_name', '')]
        try:
            bubbles = extract_messages(stable)  # 历史基线不落图；仅新媒体入队时保存裁图
        except ValueError as e:
            # 渲染瞬态（内容区黑屏/空态/窗口尺寸变化）是环境问题不是逻辑错误：
            # 跳过本轮、不计入连续异常，否则微信抽风三次就把机器人自己暂停了。
            self.status('render_unstable', chat=ck, reason=str(e)[:80])
            return False
        readable = [b for b in bubbles
                    if b['direction'] != 'in'
                    or (b['bbox'][2]-b['bbox'][0] > 8 and b['bbox'][3]-b['bbox'][1] > 10)]
        sigs = [b['signature'] for b in bubbles]
        old = self.baselines.get(ck)
        if not hasattr(self, 'seen_signatures'):
            self.seen_signatures = {}
        seen = self.seen_signatures.setdefault(ck, {})
        self.last_frame[ck] = ui.chat_image(stable).copy()
        # automation.reply_to_existing 以前只写在配置里、没人读它 ✗（配置撒谎）。
        # 现在它是真开关：true = 首次看到某个会话时，把界面上的历史消息也回一次；
        # false（默认）= 只建基线、绝不回放——聊天历史里那批未读不会突然被机器人"接话"。
        replay_existing = bool((cfg.get('automation') or {}).get('reply_to_existing'))
        initial_registry = DirectRegistry(STATE/"direct-friends.json")
        initial_direct = (old is None and ck.startswith("direct:")
                          and initial_registry.pending_initial(cfg,name))
        if initial_direct:
            # 新发现好友的第一条真实私信不能吞进基线；仅接最后一轮入站（最多3条）。
            # 旧会话/群聊仍不回放历史，已有发送后的历史也不重新接话。
            tail = []
            for bubble in reversed(bubbles):
                if bubble["direction"] == "out":
                    break
                if bubble["direction"] == "in":
                    tail.append(bubble["signature"])
                if len(tail) >= 3:
                    break
            self._note_seen(seen, [s for s in sigs if s not in tail])
            replay_existing = bool(tail)
        if old is None:
            self.baselines[ck] = sigs
            self.last_hash[ck] = digest
            if not replay_existing:
                # 首次观察：只建 baseline，绝不回放历史消息
                self._note_seen(seen, sigs)
                self._persist_seen()
                if initial_direct:
                    initial_registry.ack_initial(name)
                self.status('baseline_created', chat=ck, visible_count=len(sigs),
                            history_replay=False)
                logging.info('observe_baseline chat=%s first_time visible=%d seen=%d',
                             ck, len(sigs), len(seen))
                return False
            logging.warning('observe_baseline chat=%s replay_existing visible=%d',
                            ck, len(sigs))
            self.status('baseline_created', chat=ck, visible_count=len(sigs),
                        history_replay=True)
            old = sigs          # 让 continuity 成立，fresh 才会把可见入站消息都算新
        # 无条件成立（首次回放时 old 已置为 sigs）
        assert old is not None
        # 无重叠视口无法证明是新消息：保守重建基线；会话内已见指纹防滚动回放。
        continuity = bool(set(old).intersection(sigs)) or not old
        # 视口没有重叠（滚动/重启/界面差异）时保守重建基线，但"已见签名"还在的
        # 会话里，没见过的入站消息仍然要回：否则对面一直在说话、机器人一条不回
        # （2026-10-17 实测事故：测试群被重建基线吞掉一整段对话）。
        # 真正第一次看到的会话 seen 为空 → 仍然一条都不回放。
        fresh = [m for m in bubbles
                 if m['direction'] == 'in' and m['signature'] not in seen
                 and (continuity or bool(seen) or replay_existing)]
        new_sigs = [s for s in sigs if s not in seen]
        if initial_direct:
            initial_registry.ack_initial(name)
        self._note_seen(seen, sigs)
        self.baselines[ck] = sigs
        self.last_hash[ck] = digest
        if new_sigs:        # 没有新签名就别写盘：每轮都写一次纯属浪费磁盘/电池
            self._persist_seen()
        # 决策留痕：重启后"新消息被吞掉"这类问题只能靠这行日志复盘
        logging.info('observe_decision chat=%s baseline=%d visible=%d continuity=%s '
                     'fresh=%d seen=%d', ck, len(old), len(sigs), continuity,
                     len(fresh), len(seen))
        if fresh and not continuity:
            self.status('baseline_rebuilt_with_fresh', chat=ck, fresh=len(fresh))
        if not fresh:
            self.status('watching', chat=ck)
            return False
        # 确认有真新消息才花模型：一次批量 OCR 读全部气泡（本地多变体打底，模型纠正）。
        # 这样模型调用次数 = 新消息批次数，与轮询频率解耦；纯监控零额度。
        ocr_model = _QuotedOCR(self, cfg, model) if model is not None else None
        # 要不要"无条件"用一次模型 OCR 读全部气泡：
        # - 私聊/小而精的群（idle、all）：要，文本准确性直接影响回复质量；
        # - 只做筛选的群（selective、at_only）：走启发式就够了 —— 214 人的招新大群
        #   消息量很大，每来一批都烧一次模型 OCR 是纯浪费（@ 检测本身是看蓝色像素，
        #   不依赖 OCR；"喊名字"这类关键词启发式会自己触发模型）。
        mode = str((self.group_policy(name, cfg) or {}).get('plain_mode') or '')
        force_ocr = (not ck.startswith('group:')) or mode in ('idle', 'all')
        texts = ocr_bubbles(ui, stable, [b['bbox'] for b in readable],
                            model=ocr_model, aliases=aliases, force=force_ocr)
        for b, text in zip(readable, texts):
            if not b.get('text'):
                b['text'] = text[:2000]
            # 类型判定：有文字→text；无文字大气泡→image；小气泡→sticker
            b['kind'] = classify(stable.crop(tuple(b['bbox'])), b['text'])
            if b['kind'] == 'image' and b['text']:
                # 图片里的文字不是对方说的话：留着当线索，但别当成消息正文
                # （否则回复模型会对着一张表情包聊里面的字，2026-10-17 实测）
                b['description'] = ('[图片内文字] ' + b['text'])[:200]
                b['text'] = ''
            # @判定：文本别名为主，蓝色高亮为辅（微信 Linux 端 @ 是纯黑文字）
            b['at_me'] = b['kind'] == 'text' and (
                mentions_me(b['text'], aliases)
                or ('@' in b['text'] and has_at_mention(stable, b['bbox'])))
            if not b['text']:
                b['description'] = '[图片/表情或OCR失败]'
        # 图片/表情包在滚动时会露出不同裁切，签名每次都变，会被当成"又一条新消息"
        # 反复回；按"位置相近 + 10 分钟内"去重（2026-10-17 实测：同一张图连回两次）。
        bucket = getattr(self, 'media_recent', None)
        if bucket is None:
            bucket = self.media_recent = {}
        recent = [item for item in bucket.get(ck, []) if time.time() - item[1] < 600]
        kept = []
        for m in fresh:
            if m.get('kind') in ('image', 'sticker'):
                bb = tuple(m['bbox'])
                if any(abs(bb[0] - o[0]) <= 14 and abs(bb[1] - o[1]) <= 14 for o, _ in recent):
                    logging.info('media_duplicate chat=%s bbox=%s', ck, bb)
                    continue
                recent.append((bb, time.time()))
            kept.append(m)
        bucket[ck] = recent
        fresh = kept
        if not fresh:
            self.status('watching', chat=ck)
            return False
        # 新媒体落盘裁图（只有真的新消息才写文件）
        from multimedia import inbox_media_dir
        for m in fresh:
            if m.get('kind') in ('image', 'sticker'):
                path = inbox_media_dir(ck) / ('bubble-' + hashlib.sha256(m['signature'].encode()).hexdigest()[:20] + '.png')
                stable.crop(tuple(m['bbox'])).save(path)
                m['crop_path'] = str(path)
        priority = PRIORITY_DIRECT
        ignored_reason = ''
        if ck.startswith('group:'):
            if any(m.get('at_me') for m in fresh):
                priority = PRIORITY_GROUP_AT
            else:
                # 群里的普通消息先过**本地**规则（不调模型、不花额度）：
                # 正式群默认只接"喊名字"和"刚回过话+问句"，其余只留上下文。
                allow, why = self.group_plain_decision(name, fresh, cfg)
                if not allow:
                    ignored_reason = why
                else:
                    priority = PRIORITY_GROUP_PLAIN
                    if why == 'plain_selected':
                        self.plain_replies.setdefault(name, []).append(time.time())
        if ignored_reason:
            # 不接话也要把上下文记下来（学习样本 + 多轮历史都靠它）
            for m in fresh:
                self.memory.record_turn(ck, 'user', str(m.get('text', ''))[:500])
                self.memory.add_timeline(ck, m['direction'], m.get('kind', 'text'),
                                         m.get('text', ''), m.get('crop_path', ''),
                                         m.get('at_me', 0))
            self.memory.note_messages(ck, len(fresh), 'group', name)
            self.status('group_plain_ignored', chat=ck, reason=ignored_reason,
                        fresh=len(fresh))
            logging.info('group_plain_ignored chat=%s reason=%s fresh=%d',
                         ck, ignored_reason, len(fresh))
            return False
        want_search = needs_search(' '.join(str(m.get('text', '')) for m in fresh))
        if want_search:
            # 需要热榜时只补刷"最久没刷的那一个源"：整批刷新最坏要 60 秒
            # （4 个源 × 15 秒超时），会把这一轮回复整个卡死等它。
            # 慢的活交给空闲时的轮转（每 5 分钟一个源）。
            try:
                self.hot_checked = 0
                self.hot_cycle(cfg)
            except Exception:      # noqa: BLE001 热榜补不上也不该影响回复
                pass
        payload = json.dumps({'messages': [m for m in fresh], 'want_search': want_search},
                             ensure_ascii=False)
        qid = self.quota.enqueue(ck, priority, payload)
        # P1-9 修复：用户发言落库成 user turn（学习样本和多轮历史的来源）
        for m in fresh:
            self.memory.record_turn(ck, 'user', str(m.get('text', ''))[:500])
            # 多模态时间线：文字/图片/表情按会话隔离落库
            self.memory.add_timeline(ck, m['direction'], m.get('kind', 'text'),
                                     m.get('text', ''), m.get('crop_path', ''),
                                     m.get('at_me', 0))
        self.memory.note_messages(ck, len(fresh), 'group' if ck.startswith('group:') else 'direct', name)
        self.status('queued', chat=ck, priority=PRIORITY_NAMES[priority], queue_id=qid,
                    fresh=len(fresh))
        return True

    def _reply_times(self):
        """各会话"机器人上次发话"的时间。

        测试里 Resident 是手工装配的（不走 __init__），所以这里兜底建表：
        少一个属性不该让整条回复链崩掉。
        """
        if not hasattr(self, 'last_reply_at'):
            self.last_reply_at = {}
        if not hasattr(self, 'plain_replies'):
            self.plain_replies = {}
        return self.last_reply_at

    def group_policy(self, name, cfg):
        """取某个群的接话策略；没配的群按最保守处理（只回 @）。"""
        groups = cfg.get('groups') or {}
        for key, value in groups.items():
            if normalize(key) == normalize(name) and isinstance(value, dict):
                return dict(value)
        return {'plain_mode': 'at_only'}

    @staticmethod
    def _at_others(text, aliases):
        """文本里是否 @ 了别人（@ 后面跟的不是机器人别名）。

        只认"行首或空白之后"的 @——邮箱（niangao@example.com）里的 @ 前面不是
        空白，不会误判成提及。OCR 把昵称和后续文字粘在一起时用前缀匹配兜底
        （"@年糕Agent你好" 仍算 @ 机器人）。拿不准就当没 @ 别人，不误伤。
        """
        norm = {normalize(a).lower() for a in aliases if normalize(a)}
        if not norm:
            return False
        for m in re.finditer(r'(?:^|(?<=\s))@([^\s@]{1,16})', text or ''):
            name = normalize(m.group(1)).lower()
            if not name:
                continue
            if any(name == a or name.startswith(a) for a in norm):
                continue
            return True
        return False

    def group_plain_decision(self, name, fresh, cfg):
        """群里的**普通消息**要不要接话：本地确定性规则，不调模型、不花额度。

        计划（2026-10-17 上线评审）：
        - @ 消息走另一条路（PRIORITY_GROUP_AT），这里只管没被 @ 的
        - 明确喊名字（年糕/Agent 别名）→ 接
        - 机器人刚回过话（默认 60 秒内）且这批里有问句 → 接（在跟它聊）
        - plain_mode=idle 时：队列空闲的话，闲聊也接一句（用户要求"空闲时可以回一下"）
        - 其余不接，只当上下文；并且受"同群冷却 + 每小时上限"限制
        返回 (要不要接, 原因)。
        """
        policy = self.group_policy(name, cfg)
        mode = str(policy.get('plain_mode') or 'at_only')
        text = ' '.join(str(m.get('text', '')) for m in fresh)
        aliases = [normalize(a) for a in (cfg.get('mention_aliases') or []) if normalize(a)]
        low = normalize(text).lower()
        # 用户 2026-10-18：群里 @ 别人的消息不用回——那是在跟别人说话，插一句很招人烦。
        # 放在所有模式之前：这是全局规则，不是某个群的偏好（连 plain_mode=all 也拦）。
        # @ 到自己的消息走 at_me 优先级通道，根本到不了这里；文本里再出现别名只是
        # OCR 没认出 @ 时的兜底，所以"提到机器人"优先于"@ 了别人"。
        if not any(a and a.lower() in low for a in aliases) \
                and self._at_others(text, aliases):
            return False, 'plain_at_others'
        if mode == 'all':
            return True, 'plain_all'
        # idle（用户 2026-10-17 要求：群聊普通消息空闲时可以回一下）：
        # 保留 selective 的两条快速通道，另外在"真的空闲"时也接一句闲聊。
        if mode not in ('selective', 'idle'):
            return False, 'plain_at_only'
        reason = None
        if any(alias and alias.lower() in low for alias in aliases):
            reason = 'plain_called_by_name'
        else:
            window = float(policy.get('followup_window_s', 60) or 60)
            if time.time() - self._reply_times().get('group:' + name, 0) <= window:
                question = any(ch in text for ch in ('?', '？')) or any(
                    word in text for word in ('吗', '咋', '怎么', '为什么', '啥', '多少'))
                if question:
                    reason = 'plain_followup_question'
        # selective：只有"被喊名字"或"刚回过话且在追问"才进入候选，其余只作上下文。
        # 注意别在冷却之后兜底放行——那会变成"限流的全接"，和 selective 是两回事。
        if reason is None:
            if mode != 'idle':
                return False, 'plain_not_addressed'
            # idle 模式：闲聊也接一句，但必须"真的空闲"——队列里没有别的活在排队，
            # 免得把别人的 @ 挤到闲聊后面去。拿不准就当忙，宁可不接。
            try:
                # 高频群允许最多一个待处理项，仍保留积压保护与原有优先级。
                limit = 1 if policy.get('plain_allow_when_busy') is True else 0
                busy = self.quota.depth() > limit
            except Exception:      # noqa: BLE001 查询失败按忙处理，宁可少接一句
                busy = True
            if busy:
                return False, 'plain_busy'
            reason = 'plain_idle'
        # 冷却与小时上限只约束"确实该接"的消息
        replies = getattr(self, 'plain_replies', None)
        if replies is None:
            replies = self.plain_replies = {}
        history = [t for t in replies.get(name, []) if time.time() - t < 3600]
        replies[name] = history
        cooldown = float(policy.get('plain_cooldown_s', 120) or 120)
        if history and time.time() - history[-1] < cooldown:
            return False, 'plain_cooldown'
        if len(history) >= int(policy.get('plain_per_hour', 6) or 6):
            return False, 'plain_hourly_cap'
        return True, reason

    def _ocr_row_name(self, ui, frame, top, names):
        """只在头像认不出来时用：读这一行的名字，和登记名做一次匹配（很少触发）。"""
        from chat_navigator import _line_matches
        try:
            crop = frame.crop((121, max(0, top - 2), 294, min(frame.height, top + 22)))
            text = (ui.ocr(crop, 7) or '').strip()
        except Exception:            # noqa: BLE001 认不出就当没认出
            return None
        if not text:
            return None
        for name in names:
            if _line_matches(normalize(name), text):
                return name
        return None

    def _row_sig(self, image, y):
        """会话行像素签名（实现与 navigator 共用，保证"看到的行"= "点的行"）。"""
        return row_band_sig(image, y)

    @staticmethod
    def _row_changed(prev, sig):
        return row_changed(prev, sig)

    def plan_visits(self, cfg, ui, names):
        """先看会话列表动没动，再决定这一轮切进哪几个会话。

        用"头像指纹"把列表行绑定到会话（中文昵称 OCR 常读错，不能用来认行）：
        1) 截一帧，纯 numpy 找头像行（无 OCR，约 0.05s）；
        2) 行头像指纹 → 会话名（首次访问时学习）；
        3) 行像素（名字+预览+角标）与上一轮一致 → 跳过；
        4) 头像不在可视区 → 不切、也不滚动（来新消息会被顶到最上面，自然可见）。
        兜底：每 observe_full_sweep_seconds 秒补看 ≤observe_sweep_batch 个会话。
        """
        interval = float(cfg.get('observe_full_sweep_seconds', 600) or 0)
        batch = max(1, int(cfg.get('observe_sweep_batch', 2) or 2))
        now = time.time()
        sweep = (not interval) or (now - getattr(self, '_last_sweep', 0) >= interval)
        frame = ui.capture()
        rows = avatar_rows(frame)
        by_avatar = {}
        for name, key in getattr(self, '_avatar_of', {}).items():
            by_avatar.setdefault(key, name)
        chosen, seen = [], {}
        for (top, bot) in rows:
            y = (top + bot) // 2
            key = avatar_key(frame, y, rows)
            name = by_avatar.get(key)
            if name is None or name not in names:
                # 头像认不出来（换了头像/新会话）：顶部几行读一次名字认人，
                # 认出来就顺手更新头像指纹；认不出就交给下面"未知"学习。
                if y <= 300:
                    guess = self._ocr_row_name(ui, frame, top, names)
                    if guess:
                        self._avatar_of[guess] = key
                        by_avatar[key] = guess
                        name = guess
                if name is None or name not in names:
                    continue
            sig = self._row_sig(frame, y)
            seen[name] = (y, sig)
            if self._row_changed(self._row_sigs.get(name), sig):
                # 同一会话冷却：顶部浮动通知条/悬停态会让签名连跳，冷却把
                # "反复切进来看同一行"限制在最多每 cooldown 秒一次。
                cool = float(cfg.get('observe_visit_cooldown_s', 5) or 0)
                if now - getattr(self, '_visited_at', {}).get(name, 0) >= cool:
                    chosen.append(name)
        for name, (y, sig) in seen.items():
            self._row_y[name] = y
            self._row_sigs[name] = sig
        unknown = [n for n in names if n not in getattr(self, '_avatar_of', {})]
        chosen.extend(unknown[:batch])
        if sweep:
            rest = [n for n in names if n in getattr(self, '_avatar_of', {})
                    and n not in chosen]
            if rest:
                cursor = getattr(self, '_sweep_cursor', 0) % len(rest)
                pick = [rest[(cursor + i) % len(rest)] for i in range(min(batch, len(rest)))]
                chosen.extend(pick)
                self._sweep_cursor = cursor + len(pick)
            self._last_sweep = now
        chosen = list(dict.fromkeys(chosen))   # 同一会话可能被多行/兜底重复选中
        if chosen:
            logging.info('observe_plan visits=%d/%d sweep=%s chosen=%s',
                         len(chosen), len(names), sweep, ','.join(chosen)[:120])
        return chosen

    def observe_all(self, cfg, ui, model):
        """轮询所有监控会话：逐个切换→观察。切换和截图都是本地操作，不耗额度。"""
        if not self.nav:
            self.nav = ChatNavigator(ui)
        # 配置一致性：watch_chats 里的群若不在 group_whitelist 会被静默跳过，这里显式警告
        wl = cfg.get('group_whitelist', []) or []
        norm_wl = [normalize(g) for g in wl]
        missing = [n for n in self.watch_list(cfg) if chat_key_of(cfg,n) is None]
        if missing:
            self.status('watch_config_warning', not_whitelisted=missing[:5])
        queued = 0
        outcomes = []
        names = self.watch_list(cfg)
        # 只切进"会话列表里看起来变了"的会话（-80% 的无谓切换）：
        # 8 个会话每轮全切一遍要 20 多秒，新消息最坏要等一整轮才被发现。
        visiting = names
        t_plan = time.time()
        try:
            if ui is not None:
                visiting = self.plan_visits(cfg, ui, names)
        except Exception:             # noqa: BLE001 任何异常都退回全量，绝不因此漏消息
            visiting = names
        plan_s = time.time() - t_plan
        if len(visiting) < len(names):
            for name in names:
                if name in visiting:
                    continue
                ck = chat_key_of(cfg, name)
                outcomes.append({'chat': name, 'title_verified': True, 'observed': True,
                                 'state': 'watching', 'skipped_unchanged': True,
                                 'baseline_ready': bool(ck and ck in self.baselines)})
        t_visits = time.time()
        for name in visiting:
            outcome = {'chat': name, 'title_verified': False, 'observed': False}
            outcomes.append(outcome)
            try:
                try:
                    self.nav.pending_hint = (self._row_y.get(name),
                                             self._row_sigs.get(name),
                                             self._avatar_of.get(name))
                except Exception:                 # noqa: BLE001 测试里的假 navigator
                    pass
                image = self.nav.switch_to(name)
                if not hasattr(self, '_visited_at'):
                    self._visited_at = {}
                self._visited_at[name] = time.time()
                if getattr(self.nav, 'last_row_y', None) is not None:
                    self._row_y[name] = self.nav.last_row_y
                    try:
                        self._avatar_of[name] = avatar_key(image, self.nav.last_row_y)
                    except Exception:         # noqa: BLE001 学习失败不影响观察
                        pass
            except UIUnavailable as e:
                # 登录窗/客户端重启：标记"UI 不可用"让主循环退避，并且日志限流
                # （不然一晚上几万行 cycle_timing + 每次两行失败，把线索全淹了）
                self.ui_down_since = time.time()
                outcome.update(state='ui_unavailable', reason=str(e)[:60])
                if time.time() - getattr(self, 'ui_logged_at', 0) > 300:
                    self.ui_logged_at = time.time()
                    logging.warning('ui_unavailable chat=%s reason=%s', name, str(e)[:80])
                continue
            except SafetyError as e:
                outcome.update(state='paused_chat_switch', reason=str(e)[:60])
                self.status('paused_chat_switch', chat=name, reason=str(e)[:60])
                continue
            try:
                outcome['title_verified'] = True
                self._last_status = None
                queued += int(self.observe_one(cfg, ui, model, name, image))
                event = self._last_status or {}
                state = event.get('state', 'observation_unreported')
                outcome.update(state=state, observed=state in ('watching', 'baseline_created', 'queued'))
                if 'visible_count' in event:
                    outcome['visible_count'] = event['visible_count']
                if 'reason' in event:
                    outcome['reason'] = event['reason']
                ck = chat_key_of(cfg, name)
                if ck and ck.startswith('direct:') and not cfg.get('direct_enabled', True):
                    # 私聊已关闭：改名残留也不发（fail-closed）
                    outcome.update(state='direct_disabled', reason='私聊功能已关闭')
                    self.status('direct_disabled', chat=ck)
                    continue
                outcome['baseline_ready'] = ck in self.baselines
                outcome['baseline_count'] = len(self.baselines.get(ck, []))
                self.chat_failures[name] = 0
                self.ui_down_since = 0        # UI 回来了，清掉退避标记
            except UIUnavailable as e:
                # UI 整个不可用（登录窗/客户端重启）：安静退避，别每 2 秒刷一行日志
                n = self.chat_failures.get(name, 0) + 1
                self.chat_failures[name] = n
                self.ui_down_since = time.time()
                outcome.update(state='ui_unavailable', error_type='UIUnavailable', streak=n)
                now = time.time()
                if now - getattr(self, 'ui_logged_at', 0) > 300:
                    self.ui_logged_at = now
                    logging.warning('ui_unavailable chat=%s streak=%d reason=%s',
                                    name, n, str(e)[:80])
                    self.status('ui_unavailable', chat=name, reason=str(e)[:60])
            except QuotaExceeded:
                raise
            except Exception as e:
                # P1-7 修复：连续失败要显式降级，不能静默吞掉
                n = self.chat_failures.get(name, 0) + 1
                self.chat_failures[name] = n
                outcome.update(state='observe_degraded' if n >= 5 else 'observe_failed',
                               error_type=type(e).__name__, streak=n)
                logging.error('observe_one_failed chat=%s type=%s streak=%d',
                              name, type(e).__name__, n)
                if n >= 5:
                    self.status('observe_degraded', chat=name, streak=n,
                                error_type=type(e).__name__)
        visits_s = time.time() - t_visits
        t_tail = time.time()
        observed = sum(bool(o['observed']) for o in outcomes)
        failed = any(o.get('state') not in ('watching', 'baseline_created', 'queued', 'debouncing') for o in outcomes)
        self.last_poll = {'checked_at': time.time(), 'configured': len(names),
                          'observed': observed, 'outcomes': outcomes,
                          'not_whitelisted': missing[:5]}
        state = ('poll_degraded' if failed or missing or not names else
                 'polled' if observed == len(names) else 'poll_waiting')
        self.status(state, queued=queued, chats=len(names), observed_chats=observed)
        logging.info('observe_breakdown plan=%.1fs visits=%.1fs(%d/%d) tail=%.1fs',
                     plan_s, visits_s, len(visiting), len(names), time.time() - t_tail)

    # ---------- 上线窗口（用户 2026-10-18 要求：早上 8 点到晚上 10 点） ----------
    ONLINE_WINDOW_DEFAULTS = {'enabled': True, 'start_hour': 8, 'stop_hour': 22}

    def online_now(self, cfg, hour=None):
        """当前是否在上线窗口内。返回 (是否在窗口内, 原因)。

        窗口外整个 cycle 直接跳过：不观察、不回复、不发朋友圈、不互动。
        - 默认就是 8–22，配置整段缺失也按这个来（用户明确要的作息）
        - enabled=false 或配置写错（非整数/区间反了）→ 按始终在线处理并记日志：
          宁可多回一句，也不要因为一个配置笔误让机器人整天哑掉
        - 结束小时是**排外**的：22 点整下班，8 点整上班
        """
        win = dict(self.ONLINE_WINDOW_DEFAULTS)
        win.update(cfg.get('online_window') or {})
        if win.get('enabled') is False:
            return True, 'window_disabled'
        try:
            start, stop = int(win['start_hour']), int(win['stop_hour'])
        except (TypeError, ValueError):
            logging.error('online_window 小时数不是整数，按始终在线处理：%r', win)
            return True, 'bad_config'
        if not (0 <= start < stop <= 24):
            logging.error('online_window 区间不合法（要 0<=开始<结束<=24），按始终在线处理：%r', win)
            return True, 'bad_window'
        now = time.localtime().tm_hour if hour is None else int(hour)
        inside = start <= now < stop
        return inside, ('in_window' if inside else 'outside_window')

    # ---------- 发图（回复链路） ----------
    IMAGE_REPLY_DEFAULTS = {
        'enabled': True,
        'every_n': 0,        # 每 N 条回复补一张图（0=关，只认关键词）；2026-10-18 配置里=3
        'keywords': ['发图', '发张图', '发个图', '来张图', '来一张', '画一张',
                     '画张', '画个', '生成图片', '发你张图'],
        'max_per_hour': 3,
        'max_px': 2048,      # 回复配图最长边；用户 2026-10-18 要求"当表情包"，配置里=512
    }

    # 配图多样性（用户 2026-10-18：要有意义、不太一样，今天的自拍照太无趣了）：
    # 每条配图按顺序轮换一种构图/视角，保证连续两张不一样。
    IMAGE_VARIETY = [
        '中景，角色正在现场做事，能看到环境细节',
        '特写，只拍脸和手，表情夸张，像表情包',
        '俯视，角色很小、环境占大部分，突出场面',
        '背影或侧影，角色面向画面深处，有故事感',
        '两格分镜，左边是之前、右边是之后',
        '道具大特写，关键物品占画面中心，角色在旁边',
        '角色被场景淹没（对话框/代码/食物堆成山），只露出个头',
        '动态瞬间，角色在跑/跳/摔，带运动模糊',
    ]

    def image_prompt(self, fresh):
        '''配图提示词：话题优先 + 构图轮换。

        用户 2026-10-18 要求要有意义、不太一样。老写法是「以 OC 形象画一张图」，
        模型就每次都交一张站立挥手的自拍照。现在改成：先把群聊话题演成一个
        具体场景，OC 角色是场景里的演员而不是拍照模特；构图按 IMAGE_VARIETY
        轮换，连续两张不会同个姿势。
        '''
        ask = ' '.join(str(m.get('text', '')) for m in fresh)[:200]
        seq = getattr(self, '_image_variety_seq', 0)
        self._image_variety_seq = seq + 1
        variety = self.IMAGE_VARIETY[seq % len(self.IMAGE_VARIETY)]
        return ('画一张跟群聊话题有关的情景梗图，不要自拍照、不要单人肖像站姿。'
                '话题：%s。'
                '把话题演成一个具体场景：年糕.Agent（外观：%s）身在场景里做事或做出反应，'
                '环境、道具、动作都要和话题相关，画面要有笑点或信息量，像群聊表情包。'
                '构图：%s。'
                '不要文字、不要水印、不要logo，不要站立挥手这种通用姿势。'
                % (ask, oc_prefix(), variety))[:3900]
    def image_reply_conf(self, cfg):
        conf = dict(self.IMAGE_REPLY_DEFAULTS)
        conf.update(cfg.get('image_reply') or {})
        return conf

    @staticmethod
    def wants_image(messages, conf):
        """只看用户消息里有没有明确的要图词；不猜意图、不看回复内容。"""
        words = [w for w in (conf.get('keywords') or []) if w]
        text = ' '.join(str(m.get('text', '')) for m in messages)
        return any(w in text for w in words)

    def image_reply_allowed(self, ck, conf):
        now = time.time()
        stamps = [t for t in getattr(self, 'image_sent', {}).get(ck, []) if now - t < 3600]
        self.image_sent[ck] = stamps
        return len(stamps) < max(1, int(conf.get('max_per_hour', 3) or 1))

    def should_attach_image(self, ck, conf, fresh):
        """这条回复要不要补图：明确要图词必发；否则按 every_n 抽样（0=关）。"""
        if self.wants_image(fresh, conf):
            return True, 'asked'
        n = int(conf.get('every_n', 0) or 0)
        if n <= 0:
            return False, ''
        if not hasattr(self, 'image_counter'):
            self.image_counter = {}
        self.image_counter[ck] = self.image_counter.get(ck, 0) + 1
        if self.image_counter[ck] % n == 0:
            return True, 'sampled'
        return False, ''

    def maybe_send_image_reply(self, cfg, ui, chat_name, ck, fresh):
        """决定这条回复要不要补图，并把生图丢到后台线程。

        文字回复已经发出去了。生图（约 20 秒）**不需要 UI**，所以绝不能同步跑在
        队列里——那样每张图让后面的消息白等 20 秒（用户要"说话快"，2026-10-18
        改为后台生成）。真正需要 UI 的只有"发送"，那一步留给主循环（UI 的唯一
        属主）在安全点做，见 flush_pending_images。

        额度在这里就先占位（image_sent），避免后台还没生完、同一会话又超发。
        """
        conf = self.image_reply_conf(cfg)
        if not conf.get('enabled'):
            return False
        want, why = self.should_attach_image(ck, conf, fresh)
        if not want:
            return False
        if not self.image_reply_allowed(ck, conf):
            logging.info('image_reply_rate_limited chat=%s', ck)
            self.status('image_reply_rate_limited', chat=ck)
            return False
        prompt = self.image_prompt(fresh)
        self.image_sent.setdefault(ck, []).append(time.time())   # 先占额度
        job = {'ck': ck, 'chat': chat_name, 'prompt': prompt, 'why': why,
               'created': time.time(), 'state': 'generating',
               'max_px': int(conf.get('max_px', 2048) or 2048)}
        self._image_jobs().append(job)
        threading.Thread(target=self._generate_image_job, args=(job,), daemon=True).start()
        self.status('image_reply_queued', chat=ck, reason=why)
        return True

    def _image_jobs(self):
        if not hasattr(self, 'image_jobs'):
            self.image_jobs = []
        return self.image_jobs

    def _generate_image_job(self, job):
        """后台线程：只生图，绝不碰 UI（切会话/粘贴/回车都是全局状态）。"""
        try:
            path = generate_image(job['prompt'], ref_image=OC_REF)
            data = Path(path).read_bytes()
            png, w, h = prepare_png_bytes(data, max_px=job.get('max_px') or 2048)
            job.update(png=png, width=w, height=h, state='ready')
            logging.info('image_generated chat=%s %dx%d bytes=%d',
                         job['ck'], w, h, len(png))
        except Exception as exc:                 # noqa: BLE001 失败只记录
            job.update(state='failed', error=type(exc).__name__)
            logging.error('image_generate_failed chat=%s type=%s reason=%s',
                          job['ck'], type(exc).__name__, str(exc)[:140])

    def flush_pending_images(self, cfg, ui, limit=2):
        """把后台生成好的图发出去。**只由主循环调用**——UI 只能有一个属主。

        发送前会先切回目标会话并核验标题（防发错窗），再走与同步链路相同的
        send_image_png（它内部还会反复核验）。失败只记录，不影响别的消息。
        """
        ready = [j for j in self._image_jobs() if j.get('state') == 'ready']
        if not ready:
            return 0
        sent = 0
        for job in ready[:limit]:
            ck, name = job['ck'], job['chat']
            try:
                self.latest_send_config(ck)              # 授权可能已被撤销
                if not getattr(self, 'nav', None):
                    self.nav = ChatNavigator(ui)
                self.nav.switch_to(name)                 # 切回目标会话 + 标题核验
                ui.send_image_png(job['png'], expected_chat=name,
                                  guard=lambda: self.latest_send_config(ck))
                self.db.execute('INSERT INTO deliveries(created,state,digest) VALUES(?,?,?)',
                                (time.time(), 'IMAGE_SUBMITTED',
                                 hashlib.sha256(job['png']).hexdigest()))
                self.db.commit()
                job['state'] = 'sent'
                logging.info('image_reply_submitted chat=%s %dx%d bytes=%d',
                             ck, job['width'], job['height'], len(job['png']))
                self.status('image_reply_submitted', chat=ck,
                            width=job['width'], height=job['height'], why=job.get('why'))
                sent += 1
            except Exception as exc:                     # noqa: BLE001
                job.update(state='failed', error=type(exc).__name__)
                logging.error('image_reply_failed chat=%s type=%s reason=%s',
                              ck, type(exc).__name__, str(exc)[:140])
                self.status('image_reply_failed', chat=ck, error_type=type(exc).__name__)
        self._prune_image_jobs()
        return sent

    def _prune_image_jobs(self, keep=20):
        """图在内存里（PNG 一张几百 KB～几 MB），只留最近 20 条防涨内存。"""
        jobs = self._image_jobs()
        if len(jobs) > keep:
            del jobs[:len(jobs) - keep]

    # ---------- 发送 ----------
    def latest_send_config(self, ck):
        """每次发送重新核验磁盘策略；队列中的历史授权不能永久有效。"""
        if self.stop.exists():
            raise SafetyError('STOP 已启用，禁止发送')
        latest = with_discovered(json.loads(CONFIG.read_text()))
        name = ck.split(':', 1)[1]
        if (not latest.get('automation', {}).get('enabled') or chat_key_of(latest, name) != ck
                or (ck.startswith('direct:') and not latest.get('direct_enabled', True))):
            raise SafetyError('发送授权已撤销或会话类型未知')
        return latest

    def process_queue(self, cfg, ui, model):
        row = self.quota.claim()
        if not row:
            return False
        qid, ck, priority, _, payload = row
        t_item = time.time()
        t_switch = t_model = t_send = 0.0
        task = {}
        try:
            task = json.loads(payload)
            # 急停可能正好落在这一轮开始之后：别动 UI、别花额度，把这条放回队列，
            # 等急停解除再回（下面的晚检是最后一道保险，那时已经发不动了）。
            if self.stop.exists():
                self.quota.finish(qid, 'STOPPED_REQUEUED')
                self.quota.enqueue(ck, priority, payload)
                self.status('paused_stop_file', chat=ck, requeued=True)
                return False
            if ck.startswith('direct:') and not cfg.get('direct_enabled', True):
                # 私聊已关闭：队列里残留的私聊任务直接作废，不发（fail-closed）
                self.quota.finish(qid, 'DIRECT_DISABLED')
                self.status('direct_disabled', chat=ck, queue_id=qid)
                logging.info('direct_disabled_dropped chat=%s qid=%s', ck, qid)
                return False
            # 「以群聊为主」的硬保证：私聊轮到自己时，只要队列里还有优先级别更高的活
            # （群 @ = 0 级），就先把自己放回队列，等群里的活干完再回。
            # 最多让位 3 次，避免和别的会话互相踢皮球导致谁都不发。
            if priority == PRIORITY_DIRECT:
                top = self.quota.peek()
                if top and top[2] < priority and int(task.get('yield_count', 0)) < 3:
                    task['yield_count'] = int(task.get('yield_count', 0)) + 1
                    self.quota.finish(qid, 'YIELDED_FOR_GROUP')
                    self.quota.enqueue(ck, priority, json.dumps(task, ensure_ascii=False))
                    self.status('direct_yielded_for_group', chat=ck,
                                attempts=task['yield_count'])
                    logging.info('direct_yielded_for_group chat=%s attempts=%d',
                                 ck, task['yield_count'])
                    return False
            fresh = task['messages']
            # 防发错窗：先切到该任务对应的会话并核验标题，再发送
            chat_name = ck.split(':', 1)[1]
            self.latest_send_config(ck)
            if not self.nav:
                self.nav = ChatNavigator(ui)
            t_switch = time.time()
            try:
                self.nav.switch_to(chat_name)
            except UIUnavailable as e:
                # 环境不可用（窗口没起来 / 还停在登录窗 / 归位不了）：**不吃重试次数**，
                # 原样放回队列等 UI 回来。重启微信客户端时最容易撞上这种，
                # 以前会被当成"切换失败"两次就丢掉消息。
                self.quota.finish(qid, 'DEFERRED_UI')
                self.quota.enqueue(ck, priority, payload)
                logging.warning('switch_deferred_ui_unavailable chat=%s reason=%s',
                                ck, str(e)[:80])
                self.status('ui_unavailable', chat=ck, reason=str(e)[:60])
                return True
            except SafetyError as e:
                # 切不进去不等于消息该丢：列表滚动、窗口正忙都可能是一过性的。
                # 重新入队重试有限次；真的反复不行才放弃并显式记录（要人看一眼）。
                attempt = int(task.get('switch_retries', 0) or 0) + 1
                limit = int(cfg.get('max_send_retries', 2) or 0)
                self.baselines.pop(ck, None)
                self.last_hash.pop(ck, None)
                if attempt <= limit:
                    task['switch_retries'] = attempt
                    self.quota.finish(qid, 'SWITCH_RETRY')
                    self.quota.enqueue(ck, priority, json.dumps(task, ensure_ascii=False))
                    logging.warning('switch_failed_retry chat=%s attempt=%d/%d reason=%s',
                                    ck, attempt, limit, str(e)[:90])
                    self.status('send_aborted_wrong_chat', chat=ck, retry=attempt,
                                reason=str(e)[:60])
                else:
                    self.quota.finish(qid, 'SWITCH_FAILED')
                    logging.error('switch_failed_giving_up chat=%s reason=%s',
                                  ck, str(e)[:120])
                    self.status('send_aborted_wrong_chat', chat=ck, giving_up=True,
                                reason=str(e)[:60])
                return True
            now = time.time()
            if now - self.last_sent.get(ck, 0) < cfg['min_reply_seconds']:
                self.quota.finish(qid, 'RETRY_LATER')
                self.quota.enqueue(ck, priority, payload)
                self.quota.note_yield(ck)
                return True
            # 每小时回复上限（防刷屏、防两个机器人互相刷）：到顶就把消息留在队列里，
            # 下个周期再试（此间不花额度）。配置里写 0 表示不限制。
            cap = int(cfg.get('max_replies_per_hour', 0) or 0)
            if cap:
                sent_last_hour = self.db.execute(
                    "SELECT count(*) FROM turns WHERE chat_key=? AND role='assistant'"
                    " AND created>?", (ck, time.time() - 3600)).fetchone()[0]
                if sent_last_hour >= cap:
                    self.quota.finish(qid, 'RATE_LIMITED')
                    self.quota.enqueue(ck, priority, payload)
                    self.quota.note_yield(ck)
                    logging.info('reply_rate_limited chat=%s sent_last_hour=%d cap=%d',
                                 ck, sent_last_hour, cap)
                    self.status('reply_rate_limited', chat=ck,
                                sent_last_hour=sent_last_hour, cap=cap)
                    return True
            ctx = self.memory.context_for(ck)
            sources = gather_sources(fresh, cfg)
            question = ' '.join(str(m.get('text', '')) for m in fresh)
            self.spend(model, cfg, priority, 'reply')
            # 热榜照旧：本地缓存、免费，只在正则命中时塞进上下文。
            hot = self.feed.relevant(question) if task.get('want_search') else []
            # 联网搜索改成**模型自己调工具**：这里只交一个执行器进去，
            # 查不查、查什么词由模型决定（一次回复最多查一次，见 search_tool）。
            # 注意：搜索现在发生在 model.reply() 内部，也就是落在"生成期间画面变了没"
            # 的比对窗口里——比原来多 1~3 秒。被判定 CHANGED 时会重排一次，
            # 重排走缓存（cache_ttl 600s）不再花钱，所以代价是延迟不是丢失。
            search_calls = []
            search_fn = self.search_tool(cfg, search_calls)
            t_switch = time.time() - t_switch
            # 生成前先拍一帧，拿它和生成后的帧比较。不能用"上次观察"的旧帧：
            # 会话平静时 observe_one 会提前返回、不更新 last_frame，旧帧一对比
            # 就误判成"生成期间变了"，把已经生成好的回复白白丢掉（实测连丢两次）。
            try:
                frame_before = ui.chat_image(ui.verify_target(expected_chat=chat_name))
            except SafetyError:
                frame_before = None
            t_model = time.time()
            # 会话标识按会话隔离且不含群名（供应商要求稳定会话；我们只发哈希）
            try:
                model.session_for(ck)
            except Exception:                              # noqa: BLE001
                pass
            reply = check_output(model.reply(fresh, ctx.get('recent_turns', []), sources,
                                             chat_context=ctx, hot_items=hot,
                                             search_fn=search_fn), cfg['reply_max_chars'])
            t_model = time.time() - t_model
            # 生成期间用户切走/来新消息/手工发了 → 放弃本次，重新观察
            self.latest_send_config(ck)
            frame_now = ui.chat_image(ui.verify_target(expected_chat=chat_name))
            # 容忍"动态内容造成的少量变化"（对面还在说话/动图），只有画面整体
            # 变了才放弃；会话身份由 switch_to 的标题核验兜底。
            if frame_before is None or not frames_similar(frame_before, frame_now, tol=0.08):
                # 生成期间画面整个变了（对方又发了几条 / 有人手动切走）：
                # 不能就这么把这条消息吞掉——把它的签名从"已见"里摘掉，
                # 下一轮观察会重新当成新消息回。摘多了会变成来回打转（每次都白花
                # 一次模型调用），所以每会话最多连续摘 3 次，之后放弃并**显式记录
                # 漏掉的是哪条**，让人能看见。
                tries = getattr(self, 'changed_retries', None)
                if tries is None:
                    tries = self.changed_retries = {}
                n = tries.get(ck, 0)
                self.quota.finish(qid, 'CHANGED_RETRY' if n < 3 else 'CHANGED')
                self.last_hash.pop(ck, None)
                if n < 3:
                    tries[ck] = n + 1
                    bucket = self.seen_signatures.get(ck)
                    if bucket is not None:
                        for m in fresh:
                            bucket.pop(m.get('signature'), None)
                        self._persist_seen()
                    logging.info('frame_changed_requeue chat=%s attempt=%d', ck, n + 1)
                else:
                    logging.error('reply_dropped_frame_changed chat=%s text=%s', ck,
                                  ' | '.join(str(m.get('text', ''))[:60]
                                             for m in fresh)[:200])
                    self.baselines.pop(ck, None)
                return True
            if self.stop.exists():
                self.quota.finish(qid, 'STOPPED')
                return False
            t_send = time.time()
            if not hasattr(self, 'last_reply_text'):
                self.last_reply_text = {}
            self.last_reply_text[ck] = reply       # 失败后自证草稿是不是我们写的
            after = ui.send_text(reply, expected_chat=chat_name,
                                 expected_guard=lambda: self.latest_send_config(ck))
            t_send = time.time() - t_send
            # 记下"机器人刚在这里说过话"：群里普通消息的 60 秒追问判定要用
            self._reply_times()[ck] = time.time()
            logging.info('reply_timing chat=%s priority=%s switch=%.1fs model=%.1fs '
                         'send=%.1fs total=%.1fs', ck, PRIORITY_NAMES[priority],
                         t_switch, t_model, t_send, time.time() - t_item)
            self.quota.finish(qid, 'SUBMITTED')
            self.db.execute('INSERT INTO deliveries(created,state,digest) VALUES(?,?,?)',
                            (now, 'SUBMITTED', hashlib.sha256(payload.encode()).hexdigest()))
            self.db.commit()
            self.last_sent[ck] = time.time()
            self.quota.note_served(ck)
            if getattr(self, 'changed_retries', None):
                self.changed_retries.pop(ck, None)     # 发成功就清掉计数
            self.memory.record_turn(ck, 'assistant', reply)
            self.memory.add_timeline(ck, 'out', 'text', reply)
            self.history[ck] = []
            self.baselines.pop(ck, None)
            self.last_hash.pop(ck, None)
            self.status('reply_submitted', chat=ck, priority=PRIORITY_NAMES[priority],
                        queue_id=qid, link_reads=len(sources),
                        search_calls=len(search_calls), search_hits=sum(search_calls),
                        hot_items=len(hot))
            # 用户明确要图时，文字回复之后再生图并发送（失败只记录，不回滚文字）
            self.maybe_send_image_reply(cfg, ui, chat_name, ck, fresh)
        except OutputSafetyError as e:
            # 出话没过安全闸 → 不发给用户（这条铁律不变），但也不能让这条消息
            # 静默消失：再生成一次（模型偶尔会踩线），第二次仍不过就放弃并记录原因。
            attempt = int(task.get('unsafe_retries', 0) or 0) + 1
            limit = max(1, int(cfg.get('max_unsafe_retries', 1) or 1))
            if attempt <= limit:
                task['unsafe_retries'] = attempt
                self.quota.finish(qid, 'UNSAFE_RETRY')
                self.quota.enqueue(ck, priority, json.dumps(task, ensure_ascii=False))
                logging.warning('reply_unsafe_retry chat=%s attempt=%d reason=%s',
                                ck, attempt, str(e)[:80])
                self.status('reply_blocked_safety', chat=ck, queue_id=qid, retry=attempt)
            else:
                self.quota.finish(qid, 'UNSAFE_REPLY')
                logging.error('reply_blocked_giving_up chat=%s reason=%s', ck, str(e)[:100])
                self.status('reply_blocked_safety', chat=ck, queue_id=qid, giving_up=True)
            return True
        except QuotaExceeded as e:
            # 高优先级消息（群@/私信）撞限额：发休息提醒并转入等待，额度恢复自动继续
            if priority in (PRIORITY_GROUP_AT, PRIORITY_DIRECT):
                now = time.time()
                if now - self.last_remind.get(ck, 0) >= cfg.get('remind_cooldown', 300):
                    wait_min = max(1, self.quota.next_reset_seconds(cfg.get('limits', DEFAULT_LIMITS)) // 60)
                    try:
                        self.latest_send_config(ck)
                        ui.send_text('小年糕正在休息，请稍候再说～请等待：%d分钟' % wait_min,
                                     expected_chat=chat_name, expected_guard=lambda: self.latest_send_config(ck))
                        self.last_remind[ck] = now
                        self.quota.wait(qid)
                        self.status('resting_reminded', chat=ck, wait_minutes=wait_min,
                                    waiting=self.quota.waiting_count())
                        return True
                    except Exception as e2:
                        logging.error('remind_failed type=%s', type(e2).__name__)
            self.quota.finish(qid, 'QUOTA_WAIT')
            self.status('paused_quota', chat=ck, reason=str(e))
            return False
        except UIUnavailable as e:
            # 发送/生成过程中 UI 没了（客户端重启、X 挂了）：放回队列等它回来，
            # 不吃重试次数；也不去动"草稿"——UI 都没了，现场判断不了。
            self.quota.finish(qid, 'DEFERRED_UI')
            self.quota.enqueue(ck, priority, payload)
            logging.warning('deferred_ui_unavailable chat=%s reason=%s', ck, str(e)[:90])
            self.status('ui_unavailable', chat=ck, reason=str(e)[:60])
            return True
        except SafetyError as e:
            self.quota.finish(qid, 'ERROR_SafetyError')
            logging.error('queue_item_failed type=SafetyError qid=%s reason=%s',
                          qid, str(e)[:140])
            # 我们刚打进去、没能发出去的那句会留在输入框里；不清掉的话这条会话
            # 之后每次发送都被"输入框有草稿"拦住，等于永久哑掉。
            # 只在"输入框里确实是我们刚才那句"时才动手，别人的草稿一律不碰。
            mine = getattr(self, 'last_reply_text', {}).get(ck)
            try:
                if mine and ui.input_text(expected_chat=chat_name).strip() == mine.strip():
                    if ui.clear_input(expected_chat=chat_name, expect_text=mine):
                        logging.info('draft_cleared chat=%s', ck)
            except Exception as e2:      # noqa: BLE001
                logging.error('draft_cleanup_failed type=%s reason=%s',
                              type(e2).__name__, str(e2)[:100])
            self.status('queue_item_error', chat=ck, error_type='SafetyError')
        except (ModelUnavailable, OSError, ValueError) as e:
            # 临时故障（模型服务抖动、网络超时、响应被截断）：这条消息不能直接丢，
            # 原样重新入队重试有限次（payload 里带 retries 计数，重试也失败才放弃）。
            attempt = int(task.get('retries', 0) or 0) + 1
            limit = int(cfg.get('max_send_retries', 2) or 0)
            if attempt <= limit:
                self.quota.finish(qid, 'RETRY_TRANSIENT')
                task['retries'] = attempt
                if cfg.get('retry_backoff_seconds'):
                    time.sleep(float(cfg['retry_backoff_seconds']))
                self.quota.enqueue(ck, priority, json.dumps(task, ensure_ascii=False))
                logging.warning('queue_item_retry qid=%s attempt=%d/%d type=%s reason=%s',
                                qid, attempt, limit, type(e).__name__, str(e)[:100])
                self.status('queue_item_retry', chat=ck, attempt=attempt,
                            error_type=type(e).__name__)
                return True
            self.quota.finish(qid, 'ERROR_' + type(e).__name__)
            logging.error('queue_item_failed_giving_up type=%s qid=%s reason=%s',
                          type(e).__name__, qid, str(e)[:140])
            self.status('queue_item_error', chat=ck, error_type=type(e).__name__)
        except Exception as e:
            self.quota.finish(qid, 'ERROR_' + type(e).__name__)
            # 带上原因：SafetyError 的文案就是"哪道闸拦的"，不记下来只能干瞪眼
            logging.error('queue_item_failed type=%s qid=%s reason=%s',
                          type(e).__name__, qid, str(e)[:140])
            self.status('queue_item_error', chat=ck, error_type=type(e).__name__)
        return True

    # ---------- 自学习 ----------
    def ui_backoff_seconds(self, cfg):
        """UI 不可用时改用长退避（默认 30 秒）。

        否则一个登录窗能让我们每 2 秒空转一轮、每轮两行日志：实测 2 分钟 64 行，
        一夜几万行——既费盘又淹掉真正的线索。
        """
        down = getattr(self, 'ui_down_since', 0)
        if down and time.time() - down < 600:
            return float(cfg.get('ui_backoff_seconds', 30) or 30)
        return 0

    def poll_is_degraded(self):
        """上一轮有没有会话"没看成"（切不进去/异常），用于决定要不要自救。"""
        lp = getattr(self, 'last_poll', None) or {}
        for o in lp.get('outcomes', []) or []:
            if o.get('state') not in ('watching', 'baseline_created', 'queued', 'debouncing'):
                return True
        return False

    def recover_ui(self, cfg, ui):
        """观察连续失败时自救一次：微信拉回前台 + Esc 关浮层，然后正常重试。

        以前没有这条路：一旦有浮层挡住（小程序窗/朋友圈），每个会话都切不进去，
        主循环会一直 poll_degraded 自己好不了。自救每 120 秒最多一次，避免刷键。
        """
        now = time.time()
        if now - getattr(self, 'recovered_at', 0) < 120:
            return False
        self.recovered_at = now
        try:
            ui.activate()
            # 左侧导航可能被留在「通讯录」（好友发现流程中断时会这样）：切回聊天页，
            # 否则会话列表根本不在视野里，每个会话都切不进去，一轮能卡 70 多秒。
            if hasattr(ui, 'open_chat_tab'):
                ui.open_chat_tab()
                logging.info('ui_recover_chat_tab')
        except Exception as e:              # noqa: BLE001 自救失败也不能让主循环挂掉
            logging.warning('ui_recover_failed type=%s reason=%s',
                            type(e).__name__, str(e)[:100])
            self.status('ui_recover_failed', reason=str(e)[:80])
            return False
        logging.info('ui_recover done')
        self.status('ui_recover')
        return True

    def maintain_cycle(self, cfg):
        """定期清理：媒体裁图只留最近 media_keep_days 天。

        每张图片/表情消息都会落一张裁图，不清就一路涨（实测大半天 37MB）。
        时间线里过期的图片引用在回复前会先 exists() 检查，所以删掉是安全的。
        """
        every = float(cfg.get('maintain_seconds', 6 * 3600) or 0)
        if every <= 0:
            return
        now = time.time()
        if now - getattr(self, 'maintained_at', 0) < every:
            return
        self.maintained_at = now
        keep_days = float(cfg.get('media_keep_days', 14) or 14)
        cutoff = now - keep_days * 86400
        base = Path(STATE) / 'media'
        removed = freed = 0
        if base.exists():
            for path in base.rglob('*'):
                try:
                    if not path.is_file():
                        continue
                    info = path.stat()
                    if info.st_mtime >= cutoff:
                        continue
                    size = info.st_size
                    path.unlink()
                    removed += 1
                    freed += size
                except OSError:
                    continue
        if removed:
            logging.info('maintain_media removed=%d freed_mb=%.1f keep_days=%s',
                         removed, freed / 1048576.0, keep_days)

    def search_tool(self, cfg, calls):
        """造一个交给模型调用的搜索执行器；calls 是调用记录，用来兜住"最多一次"。

        失败一律当成"没搜到"：搜索是锦上添花，绝不能因为它把整条回复搞挂。
        这里不抛异常——上层正处在发送链路里，一个网络抖动不该让消息丢掉。
        """
        def run(query):
            if calls:
                # 模型那侧靠"第二段不带 tools"保证只调一次，这里是第二道闸：
                # 万一调用链被改动，或者模型一口气吐了多个 tool_call，也不会多花钱。
                logging.info('web_search_extra_call_ignored query=%s', str(query)[:40])
                return []
            query = str(query or '').strip()
            if not query:
                return []
            block = cfg.get('web_search') or {}
            if not block.get('enabled', True):
                return []
            calls.append(0)                    # 先占位：失败也算"查过了"，不允许再来一次
            try:
                searcher = getattr(self, 'searcher', None)
                if searcher is None:
                    searcher = self.searcher = WebSearch(self.db, block)
                else:
                    searcher.configure(block)  # 配置热更新：改 json 不用重启
                items = searcher.search(query, ori_question=query,
                                        aliases=cfg.get('mention_aliases') or [])
                calls[-1] = len(items)
                self.status('web_searched', hits=len(items), query=query[:40],
                            error=(getattr(searcher, 'last_error', '') or '')[:60])
                return items
            except Exception as exc:      # noqa: BLE001 搜索失败不能拖垮回复
                logging.warning('web_search_failed type=%s', type(exc).__name__)
                self.status('web_search_failed', type=type(exc).__name__)
                return []
        return run

    def hot_cycle(self, cfg):
        """空闲时轮转刷新 RSSHub 热榜。

        热榜让机器人接得住"最近有什么热点/最新"这类问题，但公共实例慢且限流
        （实测一个源 5-15 秒），所以只在队列空的时候、每 hot_refresh_seconds
        刷一个源，几个源轮着来。配置里不给这个键就完全不刷（离线测试用）。
        """
        every = int(cfg.get('hot_refresh_seconds') or 0)
        if every <= 0 or not HOT_ROUTES:
            return
        now = time.time()
        if now - getattr(self, 'hot_checked', 0) < every:
            return
        self.hot_checked = now
        # 选"最久没刷过的源"，不用内存里的轮转指针：服务一重启指针就归零，
        # 结果永远只刷第一个源（2026-10-17 实测：一晚上全是 weibo_hot）。
        try:
            fetched = dict(self.db.execute('SELECT source, fetched FROM hot_meta'))
        except Exception:            # noqa: BLE001
            fetched = {}
        source = min((r[0] for r in HOT_ROUTES), key=lambda s: fetched.get(s, 0))
        try:
            ok = self.feed.refresh(only_source=source)
            logging.info('hot_refresh source=%s ok=%d', source, ok)
        except Exception as e:      # noqa: BLE001 网络/解析问题都不该影响回复
            logging.warning('hot_refresh_failed source=%s type=%s', source, type(e).__name__)

    def learn_cycle(self, cfg, model):
        rows = self.db.execute('SELECT chat_key FROM profiles WHERE pending>=20').fetchall()
        if not hasattr(self, 'learn_after'): self.learn_after = {}
        for (ck,) in rows:
            if time.time() < self.learn_after.get(ck, 0): continue
            sample = self.memory.learning_sample(ck)
            if not sample:
                self.status('learn_waiting_samples', chat=ck)
                continue
            try:
                self.spend(model, cfg, PRIORITY_GROUP_PLAIN, 'learn')
                ok = self.memory.learn(ck, sample, model)
                if not hasattr(self, 'learn_fails'):
                    self.learn_fails = {}
                if ok:
                    self.learn_fails.pop(ck, None)
                    self.learn_after[ck] = time.time() + 3600
                else:
                    # 失败退避：每次尝试要花 4–5 秒，连续失败就拉长间隔，别一直白花。
                    n = self.learn_fails.get(ck, 0) + 1
                    self.learn_fails[ck] = n
                    self.learn_after[ck] = time.time() + min(3600 * (2 ** n), 86400)
                if not ok:
                    # 静默失败最坑：状态里写着 learn_failed 却没有任何原因可查
                    logging.warning('learn_failed chat=%s reason=model_output_unusable '
                                    'samples=%d retry_after_h=%d', ck, len(sample),
                                    max(1, int((self.learn_after[ck] - time.time()) / 3600)))
                self.status('learned' if ok else 'learn_failed', chat=ck)
            except QuotaExceeded:
                self.status('paused_quota', chat=ck)
                return
            except Exception as e:
                logging.error('learn_failed chat=%s type=%s', ck, type(e).__name__)

    # ---------- 朋友圈 ----------
    def interact_cycle(self, cfg, model):
        """互动管道：收件箱攒够 BATCH_SIZE 条→双Agent决策+评论→等确认。"""
        ic = cfg.get('interact') or {}
        if not ic.get('enabled'):
            return
        if self.inbox.pending_count() < BATCH_SIZE:
            return
        if not self.interact:
            self.interact = InteractionPipeline(model, ic)
        try:
            self.spend(model, cfg, PRIORITY_GROUP_PLAIN, 'interact_decide')
            self.spend(model, cfg, PRIORITY_GROUP_PLAIN, 'interact_compose')
        except QuotaExceeded:
            return
        try:
            stats = self.interact.run_batch(self.inbox)
            if stats.get('skipped') == 'whitelist_only_no_friends':
                # 配置一致性警告（与 watch_chats 警告同模式）：不静默跳过
                self.status('interact_blocked_no_friends',
                            hint='interact.whitelist_only=true 但未配置 interact.friends 名单；'
                                 '补上好友名（微信昵称）后再启用')
                return
            self.status('interact_ready', waiting_approval=True, **stats)
        except Exception as e:
            logging.error('interact_failed type=%s', type(e).__name__)
            self.status('interact_failed', error_type=type(e).__name__)

    def moment_cycle(self, cfg, model):
        """2-3天一条：生成草稿+配图后停在 DRAFT 等你确认；auto_publish=false 永不自动发。"""
        mc = cfg.get('moments') or {}
        if not mc.get('enabled'):
            return
        if not self.moments:
            self.moments = MomentComposer(self.db, model, mc)
        pending = self.db.execute("SELECT count(*) FROM moments WHERE state='DRAFT'").fetchone()[0]
        if pending or not self.moments.due():
            return
        try:
            self.spend(model, cfg, PRIORITY_GROUP_PLAIN, 'moment_draft')
        except QuotaExceeded:
            return
        d = self.moments.draft()
        if not d:
            self.status('moment_draft_failed')
            return
        image = ''
        if d.get('need_image'):
            try:
                from imagegen import generate, oc_prefix, OC_REF
                seed = d['seed']
                # OC 人设前缀保证每次画的是同一个角色；参考图辅助定型
                p = generate(oc_prefix() + '。场景：' + seed +
                             '。像素艺术风格，暖色调，画面干净无文字，不要出现任何文字。',
                             ref_image=OC_REF)
                self.moments.attach_image(d['id'], str(p))
                image = str(p)
            except Exception as e:
                logging.error('moment_image_failed type=%s', type(e).__name__)
        self.status('moment_draft_ready', moment_id=d['id'], topic=d['topic'],
                    text=d['text'], image=image, waiting_approval=True)

    def moment_publish_cycle(self, cfg, ui, model):
        """人审令牌在位才发布朋友圈草稿。

        没有令牌 = 没人确认过，直接返回（这是常态，不刷状态）；
        未标定/发布不确定/异常 → 草稿保持 DRAFT、令牌保留，下次原样重试。
        """
        mc = cfg.get('moments') or {}
        if not mc.get('enabled'):
            return
        if not (cfg.get('automation') or {}).get('allow_moments'):
            # 朋友圈总闸：automation.allow_moments=false 时，即使草稿与
            # 人审令牌都在位也不发布（令牌只代表“内容被确认过”，不代表“现在发”）
            return
        if self.moments is None:
            self.moments = MomentComposer(self.db, model, mc)
        if self.release is None:
            self.release = MomentRelease(self.db, ui, composer=self.moments,
                                         coords=load_coords(cfg), cfg=mc, state_dir=STATE)
        try:
            result = self.release.publish()
        except ReleaseError:
            return
        except SafetyError as e:
            # 安全闸拒绝（STOP/未标定/窗口不安全）＝不发，属于正常结局，不刷错误日志
            self.status('moment_publish_blocked', reason=str(e)[:80])
            return
        except NotImplementedError as e:
            self.status('moment_publish_uncalibrated', reason=str(e)[:80])
            return
        except PublisherError as e:
            self.status('moment_publish_uncertain', reason=str(e)[:80])
            return
        except Exception as e:
            logging.error('moment_publish_failed type=%s', type(e).__name__)
            self.status('moment_publish_failed', error_type=type(e).__name__)
            return
        self.status('moment_published', moment_id=result['id'], topic=result['topic'],
                    chars=len(result['text']), with_image=bool(result['image']))

    # ---------- 主循环 ----------
    def cycle(self, cfg):
        if self.stop.exists():
            self.status('paused_stop_file')
            return
        try:
            with ui_lease(STATE):
                self._cycle(cfg)
        except UILeaseBusy:
            self.status('ui_busy', skipped=True)

    def _cycle(self, cfg):
        if self.stop.exists():
            self.status('paused_stop_file')
            return
        inside, why = self.online_now(cfg)
        if not inside:
            # 用户 2026-10-18：只在早上 8 点到晚上 10 点上线。窗口外整轮跳过，
            # 状态写成 offline_window——health.py 一眼能看出"不是坏了，是到点下班"。
            if not getattr(self, '_offline_logged', False):
                logging.info('offline_window 不在上线窗口内，本轮跳过（%s）', why)
                self.status('offline_window', reason=why)
                self._offline_logged = True
            return
        if getattr(self, '_offline_logged', False):
            logging.info('online_window 已进入上线窗口，恢复工作')
            self._offline_logged = False
        ui = WeChatUI(cfg)
        model = StepPlan(cfg, self.db)      # 带上 db：真实 usage / 错误分类落到 model_calls
        self._model = model                 # 供 status 暴露模型健康（看门狗据此告警）
        if not cfg['automation']['enabled']:
            self.status('observe_only', model_key_present=bool(model.key()))
            return
        if not model.key():
            self.status('waiting_step_plan_key')
            return
        # 额度恢复后唤醒等待中的任务（含休息提醒期间积压的消息）
        limits = cfg.get('limits', DEFAULT_LIMITS)
        try:
            self.quota.check(limits)
            woken = self.quota.requeue_waiting()
            if woken:
                self.status('quota_restored', woken=woken)
        except QuotaExceeded:
            pass
        if self.poll_is_degraded():
            self.recover_ui(cfg, ui)
        t_observe = time.time()
        t_disc = time.time()
        if cfg.get("direct_auto_discover", False):
            if not hasattr(self, "direct_discovery"):
                self.direct_discovery = DirectDiscovery(DirectRegistry(STATE/"direct-friends.json"))
            try:
                self.status("discovering_direct")
                self.direct_discovery.scan(cfg, ui)
                cfg = with_discovered(cfg)
                ui.cfg = cfg
            except SafetyError as exc:
                logging.info("direct_discovery_ui_unavailable reason=%s", str(exc)[:80])
        disc_s = time.time() - t_disc
        if disc_s >= 1.0:
            logging.info('discovery_timing %.1fs', disc_s)
        try:
            self.observe_all(cfg, ui, model)
        except SafetyError:
            self.status('paused_wrong_chat_or_ui')
            return
        except QuotaExceeded as e:
            self.status('paused_quota', reason=str(e))
            return
        observe_s = time.time() - t_observe
        # 队列按 max_sends_per_cycle 发：消息成串到达时一轮多回一条，
        # 不再"一轮只发一条、剩下排队慢慢等"。发送本身仍然串行（同一个 UI）。
        budget = int((cfg.get('concurrency') or {}).get('max_sends_per_cycle', 1) or 1)
        served = 0
        t_queue = time.time()
        while served < max(1, budget) and self.quota.depth():
            before = self.quota.depth()
            if self.process_queue(cfg, ui, model) is False:
                break
            if self.quota.depth() >= before:      # 重排队/等待额度：本轮不再空转
                break
            served += 1
        # 后台生好的图在这里发：主循环是 UI 的唯一属主，先于空闲维护任务做
        # （图是用户刚要的东西，优先级高于热榜/学习这类家务活）。
        self.flush_pending_images(cfg, ui)
        logging.info('cycle_timing observe=%.1fs queue=%.1fs served=%d depth=%d',
                     observe_s, time.time() - t_queue, served, self.quota.depth())
        if self.quota.depth() == 0:
            self.maintain_cycle(cfg)
            self.hot_cycle(cfg)
        self.learn_cycle(cfg, model)
        self.moment_cycle(cfg, model)
        self.moment_publish_cycle(cfg, ui, model)
        self.interact_cycle(cfg, model)

    def serve(self, once=False):
        logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
        while self.running:
            cfg = with_discovered(json.loads(CONFIG.read_text()))
            try:
                self.cycle(cfg)
                self.failures = 0
            except SafetyError as e:
                # 环境未就绪/现场不安全：这一轮本来就发不出去，只记状态，
                # 不计入 STOP 阈值（否则 WSL 每次重启/微信未登录都会把机器人按停）
                self.failures = 0
                self.status('paused_unsafe', reason=str(e)[:80])
            except Exception as e:
                self.failures += 1
                logging.error('cycle_failed type=%s count=%d', type(e).__name__, self.failures)
                self.status('error', error_type=type(e).__name__, failures=self.failures)
                if self.failures >= 3:
                    self.stop.write_text('连续3次异常，已安全暂停。')
            if once:
                break
            # UI 不可用（登录窗/客户端重启）时退避：不然每 2 秒空转一轮刷一行日志。
            # 下限从 2 秒降到 1 秒：轮询越密，新消息被发现得越早（回复延迟的一部分
            # 就是"等下一轮"）；UI 挂了依然走 ui_backoff_seconds 的长退避。
            time.sleep(max(1.0, float(cfg['poll_seconds']), self.ui_backoff_seconds(cfg)))


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--once', action='store_true')
    args = ap.parse_args()
    Resident().serve(args.once)
