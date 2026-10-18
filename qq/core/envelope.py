"""OneBot v11 事件 → 平台无关 QEvent（QQ 接入契约 v1 · 第 2 节）。

本模块只做"翻译"，不做任何裁决：
- 能不能回、要不要回由 policy.decide 决定；
- 不碰网络、不碰数据库、不 import nonebot（离线测试可直接在系统 python 下跑）。

原始 payload 原样留在 raw 里备查，但进入模型上下文的永远只是结构化字段。
"""
import json
import re
import time as _time
from dataclasses import dataclass, field

# OneBot v11 的 CQ 码： [CQ:type,key=value,key=value]
# 参数部分用 [^\[\]] 限定，天然在下一个 '[' 或本段的 ']' 前停下，
# 所以一条消息里的多个 CQ 码能被逐个切开。
_CQ_PATTERN = re.compile(r'\[CQ:([A-Za-z0-9_.\-]+)((?:,[^\[\]]*)?)\]')

# CQ 码的转义规则（OneBot v11）：& → &amp;，[ → &#91;，] → &#93;，, → &#44;
# 反转义必须**最后**还 &amp;，否则 "&amp;#91;" 会被错误地还原成 "["。
_UNESCAPE = (('&#91;', '['), ('&#93;', ']'), ('&#44;', ','), ('&amp;', '&'))


def _unescape(value):
    text = str(value if value is not None else '')
    for source, target in _UNESCAPE:
        text = text.replace(source, target)
    return text


def parse_cq_string(message):
    """最小 CQ 码解析：把 CQ 字符串拆成 [{'type':..,'data':{..}}]。

    只要能把**纯文本**取干净就够了（契约要求"绝不把 CQ 码塞进 text"），
    所以这里不追求覆盖全部 CQ 特性，只要求：CQ 码本身绝不残留进文本。
    """
    segments = []
    position = 0
    for match in _CQ_PATTERN.finditer(message):
        head = message[position:match.start()]
        if head:
            segments.append({'type': 'text', 'data': {'text': _unescape(head)}})
        data = {}
        params = match.group(2)
        if params:
            for pair in params[1:].split(','):
                if not pair:
                    continue
                key, _, value = pair.partition('=')
                if key:
                    # 参数键统一小写：OneBot v11 规范是小写，但实测有实现上报
                    # [CQ:AT,QQ=10001]。类型我们已 lower，键不 lower 的话
                    # at_me 永远认不出来（漏判 = 该回的不回）。
                    data[_unescape(key).lower()] = _unescape(value)
        segments.append({'type': match.group(1).lower(), 'data': data})
        position = match.end()
    tail = message[position:]
    if tail:
        segments.append({'type': 'text', 'data': {'text': _unescape(tail)}})
    return segments


def normalize_segments(message):
    """把 OneBot 的 message 字段统一成 list[{'type','data'}]。

    支持两种形态：array（规范形态）与 string（最小 CQ 解析）。
    坏数据一律丢掉、绝不抛异常——这个字段直接来自外部进程。
    """
    if isinstance(message, str):
        return parse_cq_string(message)
    if isinstance(message, dict):
        message = [message]
    if not isinstance(message, list):
        return []
    segments = []
    for item in message:
        if not isinstance(item, dict):
            continue
        kind = item.get('type')
        if not isinstance(kind, str) or not kind:
            continue
        data = item.get('data')
        if not isinstance(data, dict):
            data = {}
        segments.append({'type': kind.lower(), 'data': data})
    return segments


def _as_id(value):
    """QQ 号统一成字符串：OneBot 有时给 int 有时给 str，混着比会判错。

    0 一律当**缺失**：没有哪个真实 QQ 号是 0；而 message_id=0 若被当成有效值，
    所有 message_id=0 的消息会共用同一个 dedupe_key、互相顶掉（静默漏消息，
    比直接丢弃更糟——丢了至少还看得见）。
    """
    if value is None or isinstance(value, bool):
        return ''
    if isinstance(value, (int, float)):
        if not value:                      # 0 / 0.0 / -0.0
            return ''
        # 大整数在 JSON 里可能出现 1.0 这种形态，去掉无意义的小数尾巴
        return str(int(value)) if float(value).is_integer() else str(value)
    text = str(value).strip()
    return '' if text in ('0', '0.0') else text


@dataclass
class QEvent:
    """平台无关的一条 QQ 消息。字段名与契约第 2 节逐字对应。"""

    self_id: str
    chat_type: str            # 'private' | 'group'
    chat_id: str
    sender_id: str
    sender_name: str
    message_id: str
    time: float
    at_me: bool
    at_all: bool
    text: str
    images: list
    segments: list
    raw: dict = field(default_factory=dict)

    @property
    def chat_key(self):
        """会话键：qq:<机器人号>:<私聊|群聊>:<对方号|群号>。

        带上 self_id 是必须的：同一台机器上跑两个 QQ 号时，
        两个号各自的群号相同也不该共用一份记忆与额度。
        """
        return 'qq:%s:%s:%s' % (self.self_id, self.chat_type, self.chat_id)

    @property
    def dedupe_key(self):
        """去重键：同一条消息重复投递（NapCat 重连重放）只算一次。"""
        return '%s:%s:%s:%s' % (self.self_id, self.chat_type, self.chat_id,
                                self.message_id)

    @property
    def kind(self):
        """给 memory.note_messages(kind=...) 用：私聊/群聊。"""
        return self.chat_type


def from_onebot_event(payload):
    """OneBot v11 事件 → QEvent；不是"该处理的消息"就返回 None。

    丢弃规则（契约第 2 节，fail-closed）：
    - post_type 不是 message（notice/request/meta_event 一律丢）；
    - message_type 不是 private/group；
    - 自己发的消息（sender.user_id == self_id）；
    - 拿不到机器人自己的号（self_id）——没有它就无法隔离会话与去重；
    - 拿不到 message_id——没有它就无法去重，宁可丢也不能冒"重复回复"的险。
    """
    if not isinstance(payload, dict):
        return None
    if payload.get('post_type') != 'message':
        return None
    chat_type = payload.get('message_type')
    if chat_type not in ('private', 'group'):
        return None

    self_id = _as_id(payload.get('self_id'))
    if not self_id:
        return None
    sender = payload.get('sender')
    if not isinstance(sender, dict):
        sender = {}
    sender_id = _as_id(sender.get('user_id'))
    if not sender_id:
        sender_id = _as_id(payload.get('user_id'))
    if not sender_id or sender_id == self_id:
        return None                       # 自己发的消息不回

    chat_id = _as_id(payload.get('group_id' if chat_type == 'group' else 'user_id'))
    if not chat_id:
        return None
    message_id = _as_id(payload.get('message_id'))
    if not message_id:
        return None

    segments = normalize_segments(payload.get('message'))
    texts, images = [], []
    at_me = at_all = False
    for segment in segments:
        kind, data = segment['type'], segment['data']
        if kind == 'text':
            texts.append(str(data.get('text') or ''))
        elif kind == 'image':
            images.append({'url': str(data.get('url') or ''),
                           'file': str(data.get('file') or '')})
        elif kind == 'at':
            target = _as_id(data.get('qq'))
            if target == 'all':
                at_all = True
            elif target and target == self_id:
                at_me = True

    try:
        stamp = float(payload.get('time') or 0) or _time.time()
    except (TypeError, ValueError):
        stamp = _time.time()

    return QEvent(self_id=self_id, chat_type=chat_type, chat_id=chat_id,
                  sender_id=sender_id,
                  sender_name=str(sender.get('card') or sender.get('nickname') or '').strip(),
                  message_id=message_id, time=stamp, at_me=at_me, at_all=at_all,
                  text=''.join(texts).strip(), images=images, segments=segments,
                  raw=payload)


def from_task(task):
    """把 worker 队列里的 payload 还原成一个 QEvent（批次级）。

    队列里存的是"一批消息"，这里把它们合成**一个**事件交给 sender：
    - text/images 是整批的并集（生图提示词、图片下载都看它）；
    - at_me 是整批的或（"这条要回"在入队时已经由 policy 定过了）。
    """
    if not isinstance(task, dict):
        return None
    messages = task.get('messages')
    if not isinstance(messages, list):
        messages = []
    texts, images = [], []
    at_me = at_all = False
    for message in messages:
        if not isinstance(message, dict):
            continue
        texts.append(str(message.get('text') or ''))
        for image in (message.get('images') or []):
            if isinstance(image, dict):
                images.append({'url': str(image.get('url') or ''),
                               'file': str(image.get('file') or '')})
        at_me = at_me or bool(message.get('at_me'))
        at_all = at_all or bool(message.get('at_all'))
    return QEvent(self_id=_as_id(task.get('self_id')),
                  chat_type=str(task.get('chat_type') or ''),
                  chat_id=_as_id(task.get('chat_id')),
                  sender_id=_as_id(task.get('sender_id')),
                  sender_name=str(task.get('sender_name') or ''),
                  message_id=_as_id(task.get('message_id')),
                  time=float(task.get('time') or 0) or _time.time(),
                  at_me=at_me, at_all=at_all,
                  text=' '.join(t for t in texts if t).strip(),
                  images=images, segments=[], raw={})


def batch_payload(event, decision, max_messages=12):
    """把一条事件打包成 Quota 队列可用的 JSON payload。

    结构刻意与微信侧一致（messages + signature），这样 quota.merge_payloads
    的去重/合并逻辑原样可用：等待期间又来了新消息时是**合并**而不是覆盖。
    """
    message = {'signature': event.dedupe_key,
               'direction': 'in',
               'kind': 'image' if event.images else 'text',
               'text': event.text,
               'description': '',
               'images': list(event.images),
               'at_me': bool(event.at_me),
               'at_all': bool(event.at_all),
               'ts': float(event.time or 0),
               'message_id': event.message_id,
               # "这条要不要回"必须记在**消息级**：同会话排队期间又来了新消息时，
               # quota.merge_payloads 是拿新 payload 的顶层字段当结果的，
               # 只留一个顶层 action 的话，后到的一句闲聊会把先前那条 @ 的回话意图
               # 覆盖成 context_only —— 被 @ 的消息就再也没人回了。
               'wants_reply': str(getattr(decision, 'action', 'reply')) == 'reply',
               'wants_priority': int(getattr(decision, 'priority', 0))}
    task = {'messages': [message],
            'want_search': False,
            'action': str(getattr(decision, 'action', 'reply')),
            'reason': str(getattr(decision, 'reason', '')),
            'priority': int(getattr(decision, 'priority', 0)),
            'self_id': event.self_id,
            'chat_type': event.chat_type,
            'chat_id': event.chat_id,
            'chat_key': event.chat_key,
            'sender_id': event.sender_id,
            'sender_name': event.sender_name,
            'message_id': event.message_id,
            'time': float(event.time or 0),
            'max_messages': int(max_messages)}
    return json.dumps(task, ensure_ascii=False)
