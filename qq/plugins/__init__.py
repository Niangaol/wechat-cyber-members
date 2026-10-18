"""QQ 插件包：入口（qq/bot.py）与插件（qq/plugins/*.py）之间的共享小工具。

本模块**只允许用标准库**：qq/bot.py 在模块导入期就会 import 它，离线测试也直接 import 它，
所以这里绝对不能 import nonebot，否则"没装 nonebot 也能跑的测试"就废了。

它提供三样东西：
1. QQService 单例：入口在 NoneBot 的 startup 钩子里 set_service()，插件在收到事件时 get_service()。
   为什么单例不放 qq/bot.py 里：用 `python3 -m qq.bot` 启动时入口模块名是 `__main__`，
   插件里写 `import qq.bot` 会**再执行一遍**入口文件，拿到的是另一个模块对象和另一个空单例。
   放在包里，两边 import 的都是同一个 `qq.plugins`，身份唯一。
2. event_payload()：把 NoneBot 的事件对象转成 OneBot 原始字典（契约 §8 的 event.dict()）。
3. format_status()：把 QQService.status() 的字典排成人能看的中文（/qqstatus 用）。
"""
from __future__ import annotations

import time
from typing import Any, Optional

__all__ = [
    'set_service', 'get_service', 'clear_service',
    'event_payload', 'format_status',
]

# 进程内唯一的 QQService 实例；读写都发生在 NoneBot 的同一个事件循环线程里，
# 一次赋值在 CPython 里是原子的，所以不加锁。
_service: Optional[Any] = None


def set_service(service: Any) -> None:
    """登记 QQService（只由 qq/bot.py 的 startup 钩子调用）。"""
    global _service
    _service = service


def get_service() -> Optional[Any]:
    """取 QQService；没启动或已关停时返回 None。

    插件必须容忍 None（启动竞态 / 单测环境）：拿到 None 时静默丢弃事件，
    绝不在这里临时 new 一个服务出来（会绕过 db/队列，属于隐性 bug）。
    """
    return _service


def clear_service() -> None:
    """关停时清空，避免插件继续往一个已经 stop 的实例里塞事件。"""
    global _service
    _service = None


def event_payload(event: Any) -> dict:
    """取事件的原始字段字典。

    契约 §8 写的是 `event.dict()`；pydantic v2 的模型上 `.dict()` 还在但会发弃用告警，
    所以优先 `model_dump()`，退而 `.dict()`，都没有就 `vars()`（测试替身 / 老对象）。
    任何异常都吞掉并返回 {}，由 envelope.from_onebot_event() 去丢弃这条事件——
    "解析不了的事件"不该把插件的 handler 打崩。
    """
    for attr in ('model_dump', 'dict'):
        fn = getattr(event, attr, None)
        if callable(fn):
            try:
                data = fn()
            except Exception:                       # noqa: BLE001
                continue
            if isinstance(data, dict):
                return data
    try:
        return dict(vars(event))
    except Exception:                               # noqa: BLE001
        return {}


# status() 字典的字段顺序与中文名（契约 §7 冻结的键）
_STATUS_FIELDS = (
    ('state', '状态'),
    ('heartbeat', '心跳'),
    ('queue_depth', '队列深度'),
    ('self_id', '绑定账号'),
    ('online', '连接'),
    ('last_event_at', '最近事件'),
    ('last_send_ok_at', '最近发送成功'),
    ('last_error', '最近错误'),
    ('sent_1h', '本小时已发'),
    ('stop', 'STOP 文件'),
)


def _fmt_value(key: str, value: Any) -> str:
    """把单个字段值排成人话：时间戳转本地时间，布尔转是否，None 转未知。"""
    if value is None:
        return '未知'
    if isinstance(value, bool):
        return '是' if value else '否'
    if key.endswith('_at'):
        try:
            ts = float(value)
        except (TypeError, ValueError):
            return str(value)
        if ts <= 0:
            return '无'
        return time.strftime('%m-%d %H:%M:%S', time.localtime(ts))
    return str(value)


def format_status(status: Any) -> str:
    """把 QQService.status() 排成中文多行文本（纯函数，离线可测）。

    None / 空 dict / 非 dict → 明确的"服务未启动"。绝不抛异常：
    /qqstatus 是排障入口，它自己崩掉就失去了意义。
    """
    if not isinstance(status, dict) or not status:
        return 'QQ 服务未启动（qq.plugins 里没有服务实例）'
    known = {key for key, _ in _STATUS_FIELDS}
    lines = ['QQ 机器人状态：']
    for key, label in _STATUS_FIELDS:
        if key in status:
            lines.append('  %s：%s' % (label, _fmt_value(key, status.get(key))))
    extra = sorted(k for k in status if k not in known)
    if extra:
        lines.append('  其它：' + '，'.join('%s=%s' % (k, _fmt_value(k, status[k])) for k in extra))
    return '\n'.join(lines)
