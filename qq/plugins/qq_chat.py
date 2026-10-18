"""QQ 聊天插件：把 OneBot v11 事件丢给 qq/core 的 QQService（契约 §8）。

硬要求：on_message 的 handler 里只做三件事 —— event.dict() → envelope.from_onebot_event()
→ service.submit()，**永不 await 模型/网络**。生成在 QQService 自己的 owner 线程里跑，
事件循环必须保持轻：这里一旦阻塞，NapCat 的心跳会超时、消息会成片堆在两边。

两个匹配器：
- qq_chat（priority=10、block=False）：所有消息 -> 入队，自己不回任何话；
- /qqstatus（priority=1、block=True、permission=SUPERUSER）：排障入口，只有 nonebot 配置里
  SUPERUSERS 的 QQ 号能查；没配 SUPERUSERS 就谁都查不到（默认拒绝）。
  它 priority 更小且 block=True，会把命令先吃掉，于是 "/qqstatus" 不会被当成聊天内容送进模型。
"""
from nonebot import on_command, on_message
from nonebot.adapters.onebot.v11 import Bot, Event
from nonebot.log import logger
from nonebot.permission import SUPERUSER

from qq.core.envelope import from_onebot_event
from qq.plugins import event_payload, format_status, get_service

__all__ = ['chat_matcher', 'status_matcher', 'handle_message', 'handle_status']

CHAT_PRIORITY = 10
STATUS_PRIORITY = 1

chat_matcher = on_message(priority=CHAT_PRIORITY, block=False)


@chat_matcher.handle()
async def handle_message(bot: Bot, event: Event) -> None:
    """唯一的聊天入口：解析 + 入队。本函数里**不允许出现 await**（test_qq_plugin.py 用 AST 盯着）。"""
    envelope = from_onebot_event(event_payload(event))
    if envelope is None:
        return                                  # notice/request/meta_event/自己的消息：一律丢弃
    service = get_service()
    if service is None:
        # 启动竞态或已关停：丢事件，绝不在事件循环里临时造一个服务
        logger.warning('QQ 服务未就绪，丢弃一条事件（self_id={}）', getattr(bot, 'self_id', '?'))
        return
    try:
        accepted = service.submit(envelope)
    except Exception:                           # noqa: BLE001  单条事件绝不能打挂插件
        logger.exception('QQService.submit() 抛异常，事件已丢弃')
        return
    if not accepted:
        logger.debug('事件未入队（队列满/过期/去重）：chat_key={}',
                     getattr(envelope, 'chat_key', '?'))


status_matcher = on_command('qqstatus', priority=STATUS_PRIORITY, block=True, permission=SUPERUSER)


@status_matcher.handle()
async def handle_status(bot: Bot, event: Event) -> None:
    """回一条状态文本（唯一允许 await 的地方：只为把文本发给提问者，不触网、不调模型）。"""
    service = get_service()
    status = None
    if service is not None:
        try:
            status = service.status()
        except Exception as exc:                # noqa: BLE001  排障命令自己不能崩
            status = {'state': 'status() 出错：%s' % exc}
    await status_matcher.finish(format_status(status))
