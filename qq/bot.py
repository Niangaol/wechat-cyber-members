#!/usr/bin/env python3
"""QQ 入口：NoneBot2 + nonebot-adapter-onebot（OneBot v11，反向 WebSocket）。

职责（接口契约 qq/core/INTERFACES.md 第 8/9 节）：
1. 读 qq/config/qq.json，按契约 §9 解析监听地址与 access token（token 为空 -> 拒绝启动）；
2. nonebot.init() 起 FastAPI 驱动监听 127.0.0.1:18080（默认），NapCat 作为 ws 客户端连
   ws://127.0.0.1:18080/onebot/v11/ws；
3. 在 startup 钩子里拿 running loop，构造 NoneBotSender（把同步发送桥成
   asyncio.run_coroutine_threadsafe(bot.call_api('send_msg', ...), loop).result(timeout=...)）
   与 QQService，登记进 qq.plugins 单例；
4. 加载插件 qq/plugins/qq_chat.py（它只做"事件 -> 入队"，绝不 await 模型）。

启动（WSL，仓库根目录）：
    cd /mnt/d/AgentPrograms/wechat-bot
    QQ_BOT_ONEBOT_TOKEN='<与 NapCat 里填的一模一样的 token>' python3 -m qq.bot
自检（不启动服务、不连网）：
    python3 -m qq.bot --check       # 0=可启动 2=配置/token 不合格 3=依赖缺失

设计取舍：
- 本文件**不在模块级 import nonebot**：NoneBotSender 只按鸭子类型使用 bot（有 async
  call_api 即可），事件循环由外部注入；于是发送逻辑能在没装 nonebot 的系统 python 下
  离线单测（test_qq_plugin.py）。nonebot 只在 main() 里 import。
- 只能发到 event 自己的会话：私聊 user_id / 群 group_id，接口没有"发到任意目标"的参数，
  防止提示注入把回复改发到别人（契约 §4）。
- 失败语义：超时/异常 -> unknown=True（可能已经发出去了，worker 只记 unknown、不重发）；
  明确的"没发出去"（会话类型不支持、图不存在、当前没有已连接账号）-> unknown=False。
"""
from __future__ import annotations

import argparse
import asyncio
import base64
import hashlib
import json
import logging
import os
import sys
from concurrent.futures import TimeoutError as FutureTimeoutError
from pathlib import Path
from typing import Any, Callable, Optional, Tuple

# 允许 python3 qq/bot.py 直接跑（sys.path[0] 会是 qq/ 目录，需要补上仓库根）
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from qq.core.bridge import SendResult, Sender                      # noqa: E402  契约 §4
from qq.plugins import clear_service, get_service, set_service      # noqa: E402

log = logging.getLogger('qq.bot')

DEFAULT_HOST = '127.0.0.1'
DEFAULT_PORT = 18080
DEFAULT_PATH = '/onebot/v11/ws'
DEFAULT_TOKEN_ENV = 'QQ_BOT_ONEBOT_TOKEN'
DEFAULT_CONFIG = ROOT / 'qq' / 'config' / 'qq.json'
# nonebot-adapter-onebot 的路由是写死的（v11/adapter.py 里 setup_websocket_server），
# 配置里的 path 只能等于其中之一，否则 NapCat 连不上。
ADAPTER_WS_PATHS = ('/onebot/v11/', '/onebot/v11/ws', '/onebot/v11/ws/')
SEND_TIMEOUT_S = 30.0
MAX_IMAGE_BYTES = 10 * 1024 * 1024
ENV_PORT = 'QQ_BOT_PORT'
ENV_HOST = 'QQ_BOT_HOST'
ENV_CONFIG = 'QQ_BOT_CONFIG'


class BotConfigError(RuntimeError):
    """配置不合格就抛它：宁可不启动，也不带着半个配置跑（fail-closed）。"""


def _result(*, ok: bool, unknown: bool, error: str = '', message_id: str = '') -> SendResult:
    """统一构造 SendResult：四个字段全显式传，不依赖 dataclass 的默认值。"""
    return SendResult(ok=ok, unknown=unknown, error=error, message_id=message_id)


def target_params(event: Any) -> Tuple[dict, str]:
    """从事件里取出 OneBot send_msg 的目标参数（纯函数，离线可测）。

    只认 event 自己的会话：private -> user_id，group -> group_id。
    返回 (params, error)：error 非空时 params 是空 dict。
    """
    chat_type = str(getattr(event, 'chat_type', '') or '')
    chat_id = str(getattr(event, 'chat_id', '') or '')
    if chat_type not in ('private', 'group'):
        return {}, '不支持的会话类型：%r' % (chat_type,)
    if not chat_id:
        return {}, '事件没有 chat_id'
    try:
        numeric = int(chat_id)
    except (TypeError, ValueError):
        return {}, 'chat_id 不是数字：%r' % (chat_id,)
    if numeric <= 0:
        return {}, 'chat_id 不是合法 QQ 号：%r' % (chat_id,)
    key = 'user_id' if chat_type == 'private' else 'group_id'
    return {'message_type': chat_type, key: numeric}, ''


def _message_id_of(result: Any) -> str:
    """从 call_api 的返回值里挖 message_id（dict 或适配器对象两种形态）。"""
    if isinstance(result, dict):
        value = result.get('message_id')
    else:
        value = getattr(result, 'message_id', None)
    return '' if value is None else str(value)


class NoneBotSender(Sender):
    """把 QQService 的**同步**发送需求桥到 NoneBot 的异步 call_api（契约 §4/§8）。

    - 不 import nonebot：bot 只按鸭子类型用（有 async call_api 即可），事件循环外部注入 ——
      于是可以在没有 nonebot、也没有真实连接的情况下单测参数拼装与失败语义；
    - 每次发送都现取 Bot（反向 ws 断开重连后 Bot 对象会换），拿不到就明确报"未发送"；
    - 图片走本地字节转 base64://，绝不用远端 URL（契约 §8）。
    """

    def __init__(self, bot: Any = None, loop: Any = None, *,
                 bot_provider: Optional[Callable[[], Any]] = None,
                 timeout_s: float = SEND_TIMEOUT_S,
                 max_image_bytes: int = MAX_IMAGE_BYTES,
                 logger: logging.Logger = log) -> None:
        self._bot = bot
        self.loop = loop
        self._bot_provider = bot_provider
        self.timeout_s = float(timeout_s)
        self.max_image_bytes = int(max_image_bytes)
        self.log = logger

    # ---------- 连接与身份 ----------

    def _resolve_bot(self) -> Any:
        """现取一个已连接的 Bot；构造时注入的固定对象优先（单测用）。"""
        if self._bot is not None:
            return self._bot
        if self._bot_provider is None:
            return None
        try:
            return self._bot_provider()
        except Exception as exc:                    # noqa: BLE001
            self.log.debug('取已连接 Bot 失败：%s', exc)
            return None

    def self_id(self) -> str:
        bot = self._resolve_bot()
        if bot is None:
            return ''
        return str(getattr(bot, 'self_id', '') or '')

    def online(self) -> bool:
        """事件循环活着 + 有 Bot +（能拿到连接表时）连接表里有这个账号。

        拿不到连接表（HTTP 模式、测试替身）时不阻断发送，交给真实发送结果说话。
        """
        loop = self.loop
        if loop is None or loop.is_closed():
            return False
        bot = self._resolve_bot()
        if bot is None:
            return False
        connections = getattr(getattr(bot, 'adapter', None), 'connections', None)
        if isinstance(connections, dict):
            return str(getattr(bot, 'self_id', '')) in connections
        return True

    # ---------- 发送 ----------

    def send_text(self, event: Any, text: Any) -> SendResult:
        content = '' if text is None else str(text)
        if not content.strip():
            return _result(ok=False, unknown=False, error='文本为空，未发送')
        return self._send(event, [{'type': 'text', 'data': {'text': content}}])

    def send_image(self, event: Any, path: Any) -> SendResult:
        """本地图片 -> {'type':'image','data':{'file':'base64://...'}}（契约 §8）。"""
        target = Path(str(path))
        try:
            raw = target.read_bytes()
        except Exception as exc:                    # noqa: BLE001
            return _result(ok=False, unknown=False, error='读不到图片文件 %s：%s' % (target, exc))
        if not raw:
            return _result(ok=False, unknown=False, error='图片文件是空的：%s' % target)
        if len(raw) > self.max_image_bytes:
            return _result(ok=False, unknown=False,
                           error='图片超过上限（%d > %d 字节）' % (len(raw), self.max_image_bytes))
        payload = 'base64://' + base64.b64encode(raw).decode('ascii')
        return self._send(event, [{'type': 'image', 'data': {'file': payload}}])

    def _send(self, event: Any, message: list) -> SendResult:
        params, error = target_params(event)
        if error:
            return _result(ok=False, unknown=False, error=error)
        loop = self.loop
        if loop is None or loop.is_closed():
            return _result(ok=False, unknown=False, error='事件循环不可用（None 或已关闭），未发送')
        bot = self._resolve_bot()
        if bot is None:
            return _result(ok=False, unknown=False, error='当前没有已连接的 QQ 账号，未发送')
        try:
            coro = bot.call_api('send_msg', message=message, **params)
        except Exception as exc:                    # noqa: BLE001
            return _result(ok=False, unknown=True,
                           error='构造发送调用失败：%s: %s' % (type(exc).__name__, exc))
        try:
            future = asyncio.run_coroutine_threadsafe(coro, loop)
        except Exception as exc:                    # noqa: BLE001
            coro.close()                            # 避免 coroutine was never awaited 告警
            return _result(ok=False, unknown=True,
                           error='把发送任务丢进事件循环失败：%s: %s' % (type(exc).__name__, exc))
        try:
            # 阻塞的是 QQService 的 owner 线程，不是事件循环线程：可以安全等待
            outcome = future.result(timeout=self.timeout_s)
        except FutureTimeoutError:
            future.cancel()                         # 只取消这次等待，消息可能已经发出去了
            return _result(ok=False, unknown=True,
                           error='发送超时（>%.1fs），结果未知，不重发' % self.timeout_s)
        except Exception as exc:                    # noqa: BLE001
            return _result(ok=False, unknown=True,
                           error='发送异常：%s: %s' % (type(exc).__name__, exc))
        return _result(ok=True, unknown=False, message_id=_message_id_of(outcome))


def _first_bot() -> Any:
    """现取一个已连接的 Bot：反向 ws 连上来之后 get_bots() 里才有。"""
    try:
        import nonebot                            # noqa: PLC0415  只在真正要发时才需要
        bots = nonebot.get_bots()
    except Exception as exc:                        # noqa: BLE001
        log.debug('取 Bot 失败：%s', exc)
        return None
    if isinstance(bots, dict):
        for bot in bots.values():
            return bot
    return None


# ---------------------------------------------------------------- 配置


def load_config(path: Any) -> dict:
    """读配置文件；文件不存在/不是合法 JSON 直接 SystemExit（启动即失败，别猜）。"""
    target = Path(str(path)).expanduser()
    if not target.is_file():
        raise SystemExit(
            '找不到配置文件：%s\n'
            '先复制示例：cp qq/config/qq.example.json qq/config/qq.json 然后按 _ 开头的说明改。' % target)
    try:
        data = json.loads(target.read_text(encoding='utf-8'))
    except Exception as exc:                        # noqa: BLE001
        raise SystemExit('配置文件不是合法 JSON：%s（%s）' % (target, exc))
    if not isinstance(data, dict):
        raise SystemExit('配置文件顶层必须是 JSON 对象：%s' % target)
    return data


def resolve_onebot(cfg: dict, env: Any = None) -> dict:
    """按契约 §9 解析监听参数与 access token。

    - host/port/path 读 cfg['onebot']，默认 127.0.0.1 / 18080 / /onebot/v11/ws；
      环境变量 QQ_BOT_PORT / QQ_BOT_HOST 可以临时覆盖（联调不用改配置文件）；
    - token：env(onebot.token_env) 优先，其次 onebot.token；两者都空 -> BotConfigError
      （fail-closed：绝不无鉴权开监听）。
    """
    environ = os.environ if env is None else env
    block = cfg.get('onebot')
    if not isinstance(block, dict):
        block = {}
    host = str(environ.get(ENV_HOST) or block.get('host') or DEFAULT_HOST).strip()
    port_raw = environ.get(ENV_PORT) or block.get('port') or DEFAULT_PORT
    try:
        port = int(port_raw)
    except (TypeError, ValueError):
        raise BotConfigError('onebot.port 不是整数：%r' % (port_raw,))
    if not 1 <= port <= 65535:
        raise BotConfigError('onebot.port 超出范围：%r' % (port_raw,))
    path = str(block.get('path') or DEFAULT_PATH).strip() or DEFAULT_PATH
    token_env = str(block.get('token_env') or DEFAULT_TOKEN_ENV).strip() or DEFAULT_TOKEN_ENV
    token = str(environ.get(token_env) or '').strip() or str(block.get('token') or '').strip()
    if not token:
        raise BotConfigError(
            '没有可用的 access token：环境变量 %s 和 onebot.token 都是空的。\n'
            '两端必须一致：先 export %s=<随机串>（或填进 qq/config/qq.json），'
            '再把同一个 token 填进 NapCat 的反向 ws 配置。' % (token_env, token_env))
    return {'host': host, 'port': port, 'path': path,
            'token': token, 'token_env': token_env}


def _token_fingerprint(token: str) -> str:
    """只打印长度与哈希前 8 位，绝不打印 token 明文。"""
    return '长度 %d，sha256 前 8 位 %s' % (len(token), hashlib.sha256(token.encode()).hexdigest()[:8])


def _dep_report() -> Tuple[bool, list]:
    """检查 qq/core 三个模块文件在不在 + nonebot/适配器能不能 import。

    返回 (能否启动, 输出行)。--check 用它当部署前的门禁。
    """
    lines = []
    ok = True
    for name in ('bridge.py', 'envelope.py', 'service.py'):
        exists = (ROOT / 'qq' / 'core' / name).is_file()
        lines.append('  qq/core/%s：%s' % (name, '在' if exists else '缺失'))
        ok = ok and exists
    try:
        import nonebot                            # noqa: PLC0415
        lines.append('  nonebot2：可导入 %s' % getattr(nonebot, '__version__', ''))
    except Exception as exc:                        # noqa: BLE001
        lines.append('  nonebot2：不可导入（%s）' % exc)
        ok = False
    try:
        import nonebot.adapters.onebot.v11        # noqa: PLC0415,F401
        lines.append('  nonebot-adapter-onebot：可导入')
    except Exception as exc:                        # noqa: BLE001
        lines.append('  nonebot-adapter-onebot：不可导入（%s）' % exc)
        ok = False
    return ok, lines


# ---------------------------------------------------------------- 启动


def main(argv: Optional[list] = None) -> int:
    parser = argparse.ArgumentParser(prog='qq.bot',
                                     description='QQ 机器人入口（NoneBot2 + OneBot v11 反向 WS）')
    parser.add_argument('--check', action='store_true',
                        help='只校验配置与依赖，不启动服务（0=可启动 2=配置不合格 3=依赖缺失）')
    parser.add_argument('--config', default=None,
                        help='配置文件路径（默认 qq/config/qq.json，也可用环境变量 QQ_BOT_CONFIG）')
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO,
                        format='%(asctime)s %(levelname)s %(name)s: %(message)s')

    cfg_path = args.config or os.environ.get(ENV_CONFIG) or str(DEFAULT_CONFIG)
    cfg = load_config(cfg_path)                     # 读不到 -> SystemExit，退出码非 0
    try:
        onebot = resolve_onebot(cfg)
    except BotConfigError as exc:
        log.error('配置校验失败，拒绝启动：%s', exc)
        return 2

    if args.check:
        deps_ok, dep_lines = _dep_report()
        token_source = onebot['token_env'] if os.environ.get(onebot['token_env']) else 'onebot.token'
        print('配置文件：%s' % Path(cfg_path).expanduser())
        print('反向 WS 监听：%s:%s%s（NapCat 作为客户端连过来）'
              % (onebot['host'], onebot['port'], onebot['path']))
        print('access token：%s（来自 %s）' % (_token_fingerprint(onebot['token']), token_source))
        print('state_dir：%s' % cfg.get('state_dir'))
        print('auto_send：%s%s' % (bool(cfg.get('auto_send')),
                                   '' if cfg.get('auto_send') else '（只记录不发送）'))
        groups = cfg.get('groups')
        print('已登记群：%s' % (len(groups) if isinstance(groups, dict) else '配置有问题（不是对象）'))
        print('依赖与模块：')
        print('\n'.join(dep_lines))
        if onebot['path'] not in ADAPTER_WS_PATHS:
            print('提醒：onebot.path 不在适配器写死的路由 %s 里，NapCat 必须连其中之一。'
                  % (ADAPTER_WS_PATHS,))
            deps_ok = False
        if not deps_ok:
            print('自检结论：还不能启动（见上面"缺失/不可导入/路由不一致"）。')
            return 3
        print('自检结论：可以启动。')
        return 0

    # ---- 真正的启动路径：只有这里才 import nonebot ----
    try:
        import nonebot
        from nonebot.adapters.onebot.v11 import Adapter as OneBotV11Adapter
    except ImportError as exc:
        log.error('没装 nonebot2 / nonebot-adapter-onebot（%s）。安装：'
                  'cd %s && python3 -m pip install -r qq/requirements.txt', exc, ROOT)
        return 3

    if onebot['path'] not in ADAPTER_WS_PATHS:
        log.warning('onebot.path=%s 与适配器写死的路由 %s 不一致；实际只会监听这些路径，'
                    'NapCat 必须连其中之一。', onebot['path'], list(ADAPTER_WS_PATHS))
    if onebot['host'] not in ('127.0.0.1', 'localhost', '::1'):
        log.warning('onebot.host=%s 不是回环地址：监听会暴露到局域网（有 token 也请谨慎）。', onebot['host'])

    # access token 两端一致：适配器校验 Authorization: Bearer <token>（不是查询串），
    # NapCat 的反向 ws 客户端也要填同一个 token。
    # 显式传参是主路径（已实测 adapter.onebot_config.onebot_access_token 拿到本值；
    # 该字段 alias 是 onebot_v11_access_token 且 populate_by_name=True）；
    # 再补一个环境变量别名 ONEBOT_V11_ACCESS_TOKEN 兜底，防止将来适配器改成只读环境变量。
    os.environ.setdefault(onebot['token_env'], onebot['token'])
    os.environ.setdefault('ONEBOT_V11_ACCESS_TOKEN', onebot['token'])
    nonebot.init(driver='~fastapi', host=onebot['host'], port=onebot['port'],
                 onebot_access_token=onebot['token'], log_level='INFO')
    driver = nonebot.get_driver()
    driver.register_adapter(OneBotV11Adapter)

    @driver.on_startup
    async def _on_startup() -> None:
        """拿 running loop -> 造 sender -> start() 服务 -> 登记单例。

        注意：这里是 QQService 唯一被创建的地方；插件通过 qq.plugins.get_service() 取它。
        """
        from qq.core.service import QQService       # noqa: PLC0415  qq-core 提供的核心服务

        loop = asyncio.get_running_loop()
        sender = NoneBotSender(None, loop, bot_provider=_first_bot)
        service = QQService(cfg, ROOT, sender)
        service.start()
        set_service(service)
        log.info('QQ 服务已启动：监听 %s:%s%s，state_dir=%s，auto_send=%s',
                 onebot['host'], onebot['port'], onebot['path'],
                 cfg.get('state_dir'), bool(cfg.get('auto_send')))
        if not cfg.get('auto_send'):
            log.warning('auto_send=false：当前只记录/入队、不发送（首次部署验收后再打开）')

    @driver.on_shutdown
    async def _on_shutdown() -> None:
        """关停：先停服务（它只在 owner 线程里干活），再清单例。"""
        service = get_service()
        clear_service()
        if service is None:
            return
        try:
            service.stop(timeout=5.0)
            log.info('QQ 服务已停止')
        except Exception:                            # noqa: BLE001
            log.exception('停止 QQ 服务时出错（继续退出）')

    nonebot.load_plugin('qq.plugins.qq_chat')
    log.info('开始监听（Ctrl-C 退出）')
    nonebot.run()
    return 0


if __name__ == '__main__':
    sys.exit(main())
