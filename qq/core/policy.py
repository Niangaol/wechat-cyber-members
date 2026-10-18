"""接话判定：一条 QQ 消息要不要回、按什么优先级回（契约 v1 · 第 3 节）。

三条铁律：
1. **确定性**：只看配置和事件字段，不调模型、不查网络、不花额度。
2. **fail-closed（分档，见契约 §10 S1）**：
   - 决定"能不能接"的身份/名单字段（chat_type、direct_policy、名单本身、groups）
     类型不对 → ignore（宁可少回一句，不可在拿不准的时候说话）；
   - 群条目里那几个**接话策略**字段（plain_mode/followup_window_s/
     plain_cooldown_s/plain_per_hour/mention_aliases）类型写错 → 按"该字段缺失"
     处理、退回默认值，不让一个笔误把整个群的消息都丢掉。
     真 @ 的路径根本不读这些字段，所以 @ 永远不受影响。
3. **理由可查**：每条 Decision 都带 reason，日志里能一眼看出"为什么没回"。

判定顺序（与契约逐条对应，不做合并、不重排）：
    chat_type → private 黑白名单 → group 登记/at/别名/追问/plain_mode/每日上限
    → 最后统一过频率闸 min_reply_seconds
"""
import logging
from dataclasses import dataclass

from quota import PRIORITY_GROUP_AT, PRIORITY_DIRECT, PRIORITY_GROUP_PLAIN

DEFAULT_DIRECT_POLICY = 'blacklist'
DEFAULT_MIN_REPLY_SECONDS = 3
DEFAULT_FOLLOWUP_WINDOW_S = 60
DEFAULT_PLAIN_COOLDOWN_S = 120
DEFAULT_PLAIN_PER_HOUR = 6
DEFAULT_MAX_REPLIES_PER_HOUR = 30
DEFAULT_PLAIN_MODE = 'at_only'

# 追问的"疑问"特征：问号 + 常见疑问词。与微信侧 resident.group_plain_decision
# 用的是同一套判断依据（那边只有 吗/咋/怎么/为什么/啥/多少，这里补了 呢/哪/为啥）。
QUESTION_MARKS = ('?', '？')
QUESTION_WORDS = ('吗', '呢', '咋', '怎么', '为什么', '为啥', '啥', '多少', '哪')

# "一小时内"的窗口。冷却与每小时上限都按它算。
HOUR = 3600.0

VALID_MODES = ('at_only', 'selective', 'idle', 'all')


class _BadConfig(ValueError):
    """配置类型不对：由 decide 兜住并降级成 ignore（fail-closed）。"""


@dataclass
class Decision:
    """action: 'reply' | 'context_only' | 'ignore'。

    - reply        ：要回话，priority 决定排队次序；
    - context_only ：不回话，但消息照记时间线（当上下文用）；
    - ignore       ：连上下文都不留（未登记群、黑名单、自己发的……）。
    """

    action: str
    priority: int
    reason: str


def _num(block, key, default):
    """取数字配置：缺失用默认；存在但不是数字（含 bool）→ 类型不对。"""
    if not isinstance(block, dict) or key not in block or block[key] is None:
        return float(default)
    value = block[key]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise _BadConfig(key)
    return float(value)


def _text(block, key, default=''):
    """取字符串配置：缺失用默认；存在但不是字符串 → 类型不对。"""
    if not isinstance(block, dict) or key not in block or block[key] is None:
        return default
    value = block[key]
    if not isinstance(value, str):
        raise _BadConfig(key)
    return value


def _pick(group_entry, cfg, key, default):
    """先看该群自己的配置，再退回全局配置（两处都支持，读法只有一种）。"""
    for block in (group_entry, cfg):
        if isinstance(block, dict) and key in block and block[key] is not None:
            return block
    return None


def _pick_num(group_entry, cfg, key, default):
    block = _pick(group_entry, cfg, key, default)
    return _num(block or {}, key, default) if block is not None else float(default)


def _id_set(block, key):
    """id 集合：缺失=空集；是 dict 就取键（容忍 {id: {...}} 写法）；其它类型 → 类型不对。"""
    if not isinstance(block, dict) or key not in block or block[key] is None:
        return set()
    value = block[key]
    if isinstance(value, dict):
        value = list(value.keys())
    if isinstance(value, str) or not isinstance(value, (list, tuple, set, frozenset)):
        raise _BadConfig(key)
    out = set()
    for item in value:
        if isinstance(item, bool) or isinstance(item, (dict, list)):
            continue
        text = str(item).strip()
        if text:
            out.add(text)
    return out


def _str_list(block, key):
    """字符串列表：缺失=空列表；其它类型 → 类型不对。"""
    if not isinstance(block, dict) or key not in block or block[key] is None:
        return []
    value = block[key]
    if isinstance(value, str) or not isinstance(value, (list, tuple, set, frozenset)):
        raise _BadConfig(key)
    out = []
    for item in value:
        if isinstance(item, (dict, list, bool)) or item is None:
            continue
        text = str(item).strip()
        if text:
            out.append(text)
    return out


def _aliases(group_entry, cfg):
    """别名：群配置优先，全局兜底（微信侧 mention_aliases 写在全局）。"""
    block = _pick(group_entry, cfg, 'mention_aliases', None)
    if block is None:
        return []
    return _str_list(block, 'mention_aliases')


def _safe_num(group_entry, cfg, key, default):
    """契约 §10 S1：群条目里这个数值字段类型写错 → 按"字段缺失"用默认值。

    不这么做的后果：某个群把 followup_window_s 写成字符串，整个群的消息全 ignore，
    连真 @ 都进不来（@ 路径虽不读它，但异常会冒到 decide 的兜底里）。
    """
    try:
        return _pick_num(group_entry, cfg, key, default)
    except _BadConfig:
        logging.warning('qq_policy_field_ignored field=%s value_type_error'
                        '（按缺失处理，契约 §10 S1）', key)
        return float(default)


def _safe_aliases(group_entry, cfg):
    """同上：mention_aliases 类型写错就当作没有别名。"""
    try:
        return _aliases(group_entry, cfg)
    except _BadConfig:
        logging.warning('qq_policy_field_ignored field=mention_aliases value_type_error'
                        '（按缺失处理，契约 §10 S1）')
        return []


def _safe_mode(group_entry):
    """plain_mode 只认群条目里的值（契约 §10 S2：顶层写了也无效）。"""
    try:
        return (_text(group_entry, 'plain_mode', DEFAULT_PLAIN_MODE).strip().lower()
                or DEFAULT_PLAIN_MODE)
    except _BadConfig:
        logging.warning('qq_policy_field_ignored field=plain_mode value_type_error'
                        '（按缺失处理，契约 §10 S1）')
        return DEFAULT_PLAIN_MODE


def _hit_alias(text, aliases):
    low = str(text or '').casefold()
    return any(alias.casefold() in low for alias in aliases if alias)


def is_question(text):
    """含问号或疑问词就算"在问"（追问判定用）。"""
    text = str(text or '')
    return any(mark in text for mark in QUESTION_MARKS) or any(
        word in text for word in QUESTION_WORDS)


def _plain_state(group_plain_times, now):
    """→ (一小时内的时间戳列表, 一小时内条数)。

    契约把 group_plain_times 写成"一小时内条数"，但冷却判定需要的是**时间戳**，
    所以两种形态都收：给列表/元组就按时间戳筛（顺便得到条数），给数字就只认条数
    （这时冷却无从判断，按"没有冷却"处理）。其它类型 → 类型不对 → ignore。
    """
    if group_plain_times is None:
        return [], 0
    if isinstance(group_plain_times, bool):
        raise _BadConfig('group_plain_times')
    if isinstance(group_plain_times, (int, float)):
        return [], max(0, int(group_plain_times))
    if not isinstance(group_plain_times, (list, tuple, set, frozenset)):
        raise _BadConfig('group_plain_times')
    stamps = []
    for item in group_plain_times:
        if isinstance(item, bool) or not isinstance(item, (int, float)):
            continue
        if float(now) - float(item) < HOUR:
            stamps.append(float(item))
    stamps.sort()
    return stamps, len(stamps)


def _decide_private(event, cfg):
    policy = _text(cfg, 'direct_policy', DEFAULT_DIRECT_POLICY).strip().lower()
    chat_id = str(getattr(event, 'chat_id', '') or '').strip()
    if policy == 'blacklist':
        if chat_id in _id_set(cfg, 'direct_blacklist'):
            return Decision('ignore', PRIORITY_GROUP_PLAIN, 'direct_blacklist')
        return Decision('reply', PRIORITY_DIRECT, 'direct')
    if policy == 'whitelist':
        if chat_id not in _id_set(cfg, 'direct_whitelist'):
            return Decision('ignore', PRIORITY_GROUP_PLAIN, 'direct_not_whitelisted')
        return Decision('reply', PRIORITY_DIRECT, 'direct')
    raise _BadConfig('direct_policy')


def _decide_group(event, cfg, now, queue_depth, last_reply_at, group_plain_times):
    groups = cfg.get('groups')
    if groups is None:
        return Decision('ignore', PRIORITY_GROUP_PLAIN, 'group_not_registered')
    if not isinstance(groups, dict):
        raise _BadConfig('groups')
    chat_id = str(getattr(event, 'chat_id', '') or '').strip()
    entry = groups.get(chat_id)
    if entry is None:
        # 未登记的群一律 ignore：不记时间线、不花额度、绝不回话。
        return Decision('ignore', PRIORITY_GROUP_PLAIN, 'group_not_registered')
    if not isinstance(entry, dict):
        raise _BadConfig('groups.%s' % chat_id)

    # ① 真 @（OneBot 的 at 段指向机器人）
    if getattr(event, 'at_me', False):
        return Decision('reply', PRIORITY_GROUP_AT, 'at_me')

    text = str(getattr(event, 'text', '') or '')

    # ② 文本里喊名字（包括手打的假 @"@年糕"：它没有 at 段，但确实是在叫人）
    if _hit_alias(text, _safe_aliases(entry, cfg)):
        return Decision('reply', PRIORITY_GROUP_AT, 'mention_alias')

    # ③ 机器人刚在这个群里说过话，且这句是追问
    window = _safe_num(entry, cfg, 'followup_window_s', DEFAULT_FOLLOWUP_WINDOW_S)
    if last_reply_at and window > 0 and (float(now) - float(last_reply_at)) <= window \
            and is_question(text):
        return Decision('reply', PRIORITY_GROUP_AT, 'followup_question')

    # ④ 普通消息：按该群的 plain_mode 走
    mode = _safe_mode(entry)
    stamps, count = _plain_state(group_plain_times, now)
    if mode == 'all':
        reply, reason = True, 'plain_all'
    elif mode == 'idle':
        # 必须"真的空闲"：队列里没有别的活在排队，免得把别人的 @ 挤到闲聊后面。
        if int(queue_depth or 0) > 0:
            reply, reason = False, 'plain_busy'
        else:
            cooldown = _safe_num(entry, cfg, 'plain_cooldown_s',
                                 DEFAULT_PLAIN_COOLDOWN_S)
            if cooldown > 0 and stamps and (float(now) - stamps[-1]) < cooldown:
                reply, reason = False, 'plain_cooldown'
            else:
                reply, reason = True, 'plain_idle'
    elif mode == 'selective':
        reply, reason = False, 'plain_selective'
    else:
        # 没写或写了没见过的值：按最保守的 at_only 处理
        reply, reason = False, 'plain_at_only'

    if reply:
        cap = _safe_num(entry, cfg, 'plain_per_hour', DEFAULT_PLAIN_PER_HOUR)
        if cap > 0 and count >= cap:
            reply, reason = False, 'plain_hourly_cap'

    if reply:
        return Decision('reply', PRIORITY_GROUP_PLAIN, reason)
    return Decision('context_only', PRIORITY_GROUP_PLAIN, reason)


def decide(event, cfg, *, now, queue_depth, last_reply_at, group_plain_times):
    """判定一条事件怎么处理。参数与契约第 3 节逐字一致。

    now              ：当前时间戳（由调用方注入，方便离线测试与统一时钟）；
    queue_depth      ：当前待处理队列深度（idle 模式判"忙不忙"）；
    last_reply_at    ：该会话上一次**成功回话**的时间（0/None 表示还没回过）；
    group_plain_times：该群一小时内"普通消息"回复的时间戳（见 _plain_state）。
    """
    if event is None or not isinstance(cfg, dict):
        return Decision('ignore', PRIORITY_GROUP_PLAIN, 'no_event')
    chat_type = str(getattr(event, 'chat_type', '') or '')
    try:
        if chat_type == 'private':
            decision = _decide_private(event, cfg)
        elif chat_type == 'group':
            decision = _decide_group(event, cfg, float(now), queue_depth,
                                     last_reply_at, group_plain_times)
        else:
            return Decision('ignore', PRIORITY_GROUP_PLAIN, 'chat_type:%s' % chat_type)

        # ⑤ 频率闸：任何"要回话"的判定都要过。被挡下的消息不是丢了——调用方
        #    仍会把它写进时间线（context_only 语义），只是这一轮不出话。
        if decision.action == 'reply':
            gate = _num(cfg, 'min_reply_seconds', DEFAULT_MIN_REPLY_SECONDS)
            if gate > 0 and last_reply_at and (float(now) - float(last_reply_at)) < gate:
                return Decision('context_only', PRIORITY_GROUP_PLAIN, 'min_reply_seconds')
        return decision
    except _BadConfig as exc:
        return Decision('ignore', PRIORITY_GROUP_PLAIN, 'bad_config:%s' % exc)
    except (TypeError, ValueError, AttributeError) as exc:      # noqa: BLE001
        return Decision('ignore', PRIORITY_GROUP_PLAIN, 'bad_input:%s' % type(exc).__name__)
