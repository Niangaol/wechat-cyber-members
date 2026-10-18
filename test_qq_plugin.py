"""qq-nonebot 层的离线单测：不装 nonebot、不连网、不连真实 QQ/微信、不碰生产库。

跑法（WSL，仓库根目录）：
    cd /mnt/d/AgentPrograms/wechat-bot && python3 -m unittest test_qq_plugin -v

覆盖四块：
1. NoneBotSender 的参数拼装与失败语义（私聊/群、base64 图片前缀、超时/异常 -> unknown=True）；
2. qq/plugins/__init__.py 的纯函数（event_payload / format_status / 服务单例）；
3. 结构性约束（AST 静态检查）：on_message 的 handler 里绝不允许出现 await；qq/bot.py 模块级
   不许 import nonebot（否则"没装 nonebot 也能跑"这条就废了）；
4. qq/config/qq.example.json 与冻结 schema（INTERFACES.md §9）对得上、且不含任何秘密。

qq/core/bridge.py 由 qq-core 负责：它还没落地时用字段完全一致的替身顶上，
本测试因此不依赖别人的进度；它落地后自动改用真的，并用契约一致性用例校验。
"""
import abc
import ast
import asyncio
import base64
import dataclasses
import json
import re
import subprocess
import sys
import tempfile
import threading
import types
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

PLUGIN_PATH = ROOT / 'qq' / 'plugins' / 'qq_chat.py'
BOT_PATH = ROOT / 'qq' / 'bot.py'
PLUGINS_INIT_PATH = ROOT / 'qq' / 'plugins' / '__init__.py'
EXAMPLE_CONFIG_PATH = ROOT / 'qq' / 'config' / 'qq.example.json'
SHARED_CREDENTIALS = '/home/niangao/.local/state/wechat-bot/credentials.json'


def _ensure_bridge() -> str:
    """保证 qq.core.bridge 可导入；返回 'real'（真模块）或 'stub'（替身）。"""
    try:
        import qq.core.bridge  # noqa: F401
        return 'real'
    except Exception:                               # noqa: BLE001  qq-core 还没落地
        pass
    import qq.core                                   # noqa: F401  先跑父包 __init__（加 src/ 到 sys.path）
    module = types.ModuleType('qq.core.bridge')

    @dataclasses.dataclass
    class SendResult:                               # 字段与契约 §4 逐字一致
        ok: bool = False
        unknown: bool = False
        error: str = ''
        message_id: str = ''

    class Sender(abc.ABC):
        @abc.abstractmethod
        def send_text(self, event, text): ...       # noqa: E704

        @abc.abstractmethod
        def send_image(self, event, path): ...      # noqa: E704

        @abc.abstractmethod
        def self_id(self): ...                      # noqa: E704

        @abc.abstractmethod
        def online(self): ...                       # noqa: E704

    module.SendResult = SendResult
    module.Sender = Sender
    sys.modules['qq.core.bridge'] = module
    setattr(sys.modules['qq.core'], 'bridge', module)
    return 'stub'


BRIDGE_SOURCE = _ensure_bridge()

import qq.bot as qqbot                                            # noqa: E402
from qq.plugins import (clear_service, event_payload, format_status,   # noqa: E402
                        get_service, set_service)

try:                                                # nonebot 只在装了的机器上测插件本体
    import nonebot as _nonebot
    HAS_NONEBBOT = True
except Exception:                                   # noqa: BLE001
    HAS_NONEBBOT = False


class _LoopThread:
    """后台线程里跑一个真事件循环：run_coroutine_threadsafe 需要一个活着的 loop。"""

    def __init__(self) -> None:
        self.loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._run, name='qq-test-loop', daemon=True)
        self._thread.start()

    def _run(self) -> None:
        asyncio.set_event_loop(self.loop)
        self.loop.run_forever()

    def close(self) -> None:
        if self.loop.is_closed():
            return
        self.loop.call_soon_threadsafe(self.loop.stop)
        self._thread.join(timeout=5)
        self.loop.close()


class FakeBot:
    """Bot 的替身：只提供 NoneBotSender 真正用到的东西（self_id / async call_api / adapter）。"""

    def __init__(self, self_id: str = '10001', result=None, error=None,
                 delay: float = 0.0, connected: bool = True) -> None:
        self.self_id = self_id
        self.result = {'message_id': 42, 'status': 'ok'} if result is None else result
        self.error = error
        self.delay = delay
        self.calls = []
        self.adapter = types.SimpleNamespace(
            connections={self_id: object()} if connected else {})

    async def call_api(self, api, **params):
        self.calls.append({'api': api, 'params': params})
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.error is not None:
            raise self.error
        return self.result


def event(chat_type: str, chat_id) -> types.SimpleNamespace:
    """QEvent 的最小替身：NoneBotSender 只读 chat_type / chat_id。"""
    return types.SimpleNamespace(chat_type=chat_type, chat_id=chat_id)


class TargetParamsTests(unittest.TestCase):
    """目标解析是纯函数：私聊 user_id / 群 group_id，别的会话类型一律拒绝。"""

    def test_private_uses_user_id(self):
        params, err = qqbot.target_params(event('private', '20002'))
        self.assertEqual(err, '')
        self.assertEqual(params, {'message_type': 'private', 'user_id': 20002})

    def test_group_uses_group_id(self):
        params, err = qqbot.target_params(event('group', 123456789))
        self.assertEqual(err, '')
        self.assertEqual(params, {'message_type': 'group', 'group_id': 123456789})

    def test_unknown_chat_type_is_rejected(self):
        params, err = qqbot.target_params(event('discuss', '1'))
        self.assertEqual(params, {})
        self.assertIn('不支持的会话类型', err)

    def test_non_numeric_chat_id_is_rejected(self):
        params, err = qqbot.target_params(event('group', '群名不是数字'))
        self.assertEqual(params, {})
        self.assertIn('不是数字', err)

    def test_empty_chat_id_is_rejected(self):
        params, err = qqbot.target_params(event('group', ''))
        self.assertEqual(params, {})
        self.assertIn('没有 chat_id', err)

    def test_non_positive_chat_id_is_rejected(self):
        params, err = qqbot.target_params(event('private', -1))
        self.assertEqual(params, {})
        self.assertIn('不是合法 QQ 号', err)


class SenderTests(unittest.TestCase):
    """NoneBotSender：真事件循环 + 假 bot，测参数拼装与失败语义（不建立任何真实连接）。"""

    @classmethod
    def setUpClass(cls):
        cls.running = _LoopThread()

    @classmethod
    def tearDownClass(cls):
        cls.running.close()

    def sender(self, bot, **kwargs) -> object:
        return qqbot.NoneBotSender(bot, self.running.loop, **kwargs)

    # ---------- 正常路径 ----------

    def test_private_text_params(self):
        bot = FakeBot()
        result = self.sender(bot).send_text(event('private', '20002'), '你好')
        self.assertTrue(result.ok)
        self.assertFalse(result.unknown)
        self.assertEqual(result.message_id, '42')
        self.assertEqual(bot.calls, [{
            'api': 'send_msg',
            'params': {'message': [{'type': 'text', 'data': {'text': '你好'}}],
                       'message_type': 'private', 'user_id': 20002},
        }])

    def test_group_text_params(self):
        bot = FakeBot()
        result = self.sender(bot).send_text(event('group', '123456789'), '在的')
        self.assertTrue(result.ok)
        params = bot.calls[0]['params']
        self.assertEqual(params['message_type'], 'group')
        self.assertEqual(params['group_id'], 123456789)
        self.assertNotIn('user_id', params, '群聊不能被当成私聊发出去')

    def test_empty_text_is_not_sent(self):
        bot = FakeBot()
        result = self.sender(bot).send_text(event('private', '1'), '   ')
        self.assertFalse(result.ok)
        self.assertFalse(result.unknown, '明显没发出去：不该记成 unknown')
        self.assertEqual(bot.calls, [], '空文本不该真的调用 call_api')

    def test_image_uses_local_base64_prefix(self):
        raw = b'\x89PNG\r\n\x1a\n' + b'fake-image-bytes'
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'gen-1.png'
            path.write_bytes(raw)
            bot = FakeBot()
            result = self.sender(bot).send_image(event('private', '20002'), path)
        self.assertTrue(result.ok, result.error)
        segment = bot.calls[0]['params']['message'][0]
        self.assertEqual(segment['type'], 'image')
        self.assertTrue(segment['data']['file'].startswith('base64://'), '必须是本地字节的 base64://')
        decoded = base64.b64decode(segment['data']['file'][len('base64://'):])
        self.assertEqual(decoded, raw)

    def test_image_missing_file_is_definite_failure(self):
        result = self.sender(FakeBot()).send_image(event('private', '1'), '/nonexistent/nope.png')
        self.assertFalse(result.ok)
        self.assertFalse(result.unknown)
        self.assertIn('读不到图片', result.error)

    def test_image_over_limit_is_not_sent(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'big.png'
            path.write_bytes(b'12345')
            bot = FakeBot()
            result = self.sender(bot, max_image_bytes=4).send_image(event('private', '1'), path)
        self.assertFalse(result.ok)
        self.assertIn('超过上限', result.error)
        self.assertEqual(bot.calls, [])

    # ---------- 失败语义 ----------

    def test_timeout_is_unknown_and_not_retried(self):
        bot = FakeBot(delay=1.0)
        result = self.sender(bot, timeout_s=0.05).send_text(event('private', '1'), '慢回复')
        self.assertFalse(result.ok)
        self.assertTrue(result.unknown, '超时 = 可能已经发出去了，必须 unknown=True')
        self.assertIn('超时', result.error)

    def test_exception_is_unknown(self):
        bot = FakeBot(error=RuntimeError('WebSocket closed'))
        result = self.sender(bot).send_text(event('private', '1'), '你好')
        self.assertFalse(result.ok)
        self.assertTrue(result.unknown)
        self.assertIn('发送异常', result.error)
        self.assertIn('WebSocket closed', result.error)

    def test_call_api_raising_synchronously_is_unknown(self):
        class Exploding:
            self_id = '10001'

            def call_api(self, api, **params):      # 不是 async：调用时就炸
                raise RuntimeError('adapter 没连上')

        result = qqbot.NoneBotSender(Exploding(), self.running.loop).send_text(
            event('private', '1'), '你好')
        self.assertFalse(result.ok)
        self.assertTrue(result.unknown)

    def test_closed_loop_is_definite_failure(self):
        dead = asyncio.new_event_loop()
        dead.close()
        result = qqbot.NoneBotSender(FakeBot(), dead).send_text(event('private', '1'), '你好')
        self.assertFalse(result.ok)
        self.assertFalse(result.unknown)
        self.assertIn('事件循环不可用', result.error)

    def test_no_connected_bot_is_definite_failure(self):
        result = qqbot.NoneBotSender(None, self.running.loop).send_text(event('private', '1'), '你好')
        self.assertFalse(result.ok)
        self.assertFalse(result.unknown)
        self.assertIn('没有已连接', result.error)

    def test_bot_provider_is_used_when_no_bot_injected(self):
        bot = FakeBot()
        sender = qqbot.NoneBotSender(None, self.running.loop, bot_provider=lambda: bot)
        result = sender.send_text(event('group', '123456789'), '走 provider')
        self.assertTrue(result.ok)
        self.assertEqual(len(bot.calls), 1)

    # ---------- 身份与在线判断 ----------

    def test_self_id_and_online(self):
        connected = FakeBot(self_id='10001', connected=True)
        sender = self.sender(connected)
        self.assertEqual(sender.self_id(), '10001')
        self.assertTrue(sender.online())
        self.assertFalse(self.sender(FakeBot(self_id='10001', connected=False)).online())
        self.assertFalse(qqbot.NoneBotSender(None, self.running.loop).online())
        self.assertFalse(qqbot.NoneBotSender(connected, None).online())

    def test_message_id_from_object_result(self):
        bot = FakeBot(result=types.SimpleNamespace(message_id=777))
        result = self.sender(bot).send_text(event('private', '1'), '你好')
        self.assertTrue(result.ok)
        self.assertEqual(result.message_id, '777')

    def test_missing_message_id_is_still_ok(self):
        bot = FakeBot(result={})
        result = self.sender(bot).send_text(event('private', '1'), '你好')
        self.assertTrue(result.ok)
        self.assertEqual(result.message_id, '')


class PluginsHelperTests(unittest.TestCase):
    """qq/plugins/__init__.py 的纯函数：不碰 nonebot，直接测。"""

    def tearDown(self):
        clear_service()

    def test_event_payload_prefers_model_dump(self):
        class Model:
            def model_dump(self):
                return {'post_type': 'message'}

            def dict(self):
                return {'post_type': 'legacy'}

        self.assertEqual(event_payload(Model()), {'post_type': 'message'})

    def test_event_payload_falls_back_to_dict(self):
        class Legacy:
            def dict(self):
                return {'post_type': 'message'}

        self.assertEqual(event_payload(Legacy()), {'post_type': 'message'})

    def test_event_payload_vars_fallback(self):
        class Plain:
            def __init__(self):
                self.post_type = 'message'

        self.assertEqual(event_payload(Plain()), {'post_type': 'message'})

    def test_event_payload_never_raises(self):
        class Broken:
            def model_dump(self):
                raise ValueError('坏了')

            def dict(self):
                raise ValueError('也坏了')

        self.assertEqual(event_payload(Broken()), {})
        self.assertEqual(event_payload(None), {})

    def test_format_status_says_not_started(self):
        self.assertIn('未启动', format_status(None))
        self.assertIn('未启动', format_status({}))

    def test_format_status_covers_frozen_keys(self):
        text = format_status({'state': 'running', 'online': True, 'sent_1h': 3,
                              'queue_depth': 0, 'last_error': '', 'stop': False})
        self.assertIn('状态：running', text)
        self.assertIn('连接：是', text)
        self.assertIn('本小时已发：3', text)
        self.assertIn('队列深度：0', text)
        self.assertIn('STOP 文件：否', text)

    def test_format_status_renders_timestamps_and_extras(self):
        text = format_status({'last_event_at': 1700000000.0, 'last_send_ok_at': 0,
                              '未知字段': 'x'})
        self.assertIn('最近事件：', text)
        self.assertIn('最近发送成功：无', text)
        self.assertIn('未知字段=x', text)

    def test_service_singleton_roundtrip(self):
        self.assertIsNone(get_service())
        marker = object()
        set_service(marker)
        self.assertIs(get_service(), marker)
        clear_service()
        self.assertIsNone(get_service())


def _matcher_names(tree: ast.Module, factory: str) -> set:
    """找出 `名字 = on_message(...)` / `on_command(...)` 里的变量名。"""
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Call):
            func = node.value.func
            if isinstance(func, ast.Name) and func.id == factory:
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        names.add(target.id)
    return names


def _handlers(tree: ast.Module, matchers: set) -> list:
    """找出被 `@匹配器.handle()` 装饰的异步函数。"""
    out = []
    for node in ast.walk(tree):
        if isinstance(node, ast.AsyncFunctionDef):
            for decorator in node.decorator_list:
                text = ast.unparse(decorator)
                if any(text.startswith(name + '.handle') for name in matchers):
                    out.append(node)
    return out


class PluginSourceTests(unittest.TestCase):
    """结构性约束（不装 nonebot 也能跑）：契约里最容易写歪的两条钉死在这里。"""

    def setUp(self):
        self.source = PLUGIN_PATH.read_text(encoding='utf-8')
        self.tree = ast.parse(self.source)

    def test_chat_handler_never_awaits(self):
        handlers = _handlers(self.tree, _matcher_names(self.tree, 'on_message'))
        self.assertEqual(len(handlers), 1, 'on_message 应当只有一个 handler')
        awaits = [n for n in ast.walk(handlers[0]) if isinstance(n, (ast.Await, ast.AsyncWith, ast.AsyncFor))]
        self.assertEqual(awaits, [], 'on_message 的 handler 里绝不允许 await/async with（契约 §8）')

    def test_chat_handler_parses_and_submits(self):
        self.assertIn('from_onebot_event(', self.source)
        handlers = _handlers(self.tree, _matcher_names(self.tree, 'on_message'))
        body = ast.unparse(handlers[0])
        self.assertIn('.submit(', body, 'handler 必须把事件交给 service.submit()')
        self.assertIn('get_service()', body, 'service 实例只能从 qq.plugins 单例取')

    def test_status_command_is_superuser_only_and_blocks(self):
        self.assertIn("on_command('qqstatus'", self.source)
        self.assertIn('permission=SUPERUSER', self.source)
        handlers = _handlers(self.tree, _matcher_names(self.tree, 'on_command'))
        self.assertTrue(handlers, 'on_command 应当有 handler')
        body = ast.unparse(handlers[0])
        self.assertIn('format_status(', body)
        self.assertIn('status()', body)

    def test_plugins_init_does_not_import_nonebot(self):
        tree = ast.parse(PLUGINS_INIT_PATH.read_text(encoding='utf-8'))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    self.assertFalse(alias.name.startswith('nonebot'),
                                     'qq/plugins/__init__.py 不许 import nonebot（离线测试依赖它）')
            if isinstance(node, ast.ImportFrom):
                self.assertFalse((node.module or '').startswith('nonebot'),
                                 'qq/plugins/__init__.py 不许 import nonebot（离线测试依赖它）')

    def test_bot_module_has_no_top_level_nonebot_import(self):
        tree = ast.parse(BOT_PATH.read_text(encoding='utf-8'))
        offenders = []
        for node in tree.body:                      # 只看模块顶层，函数内 import 是允许的
            if isinstance(node, ast.Import):
                offenders += [a.name for a in node.names if a.name.startswith('nonebot')]
            if isinstance(node, ast.ImportFrom) and (node.module or '').startswith('nonebot'):
                offenders.append(node.module)
        self.assertEqual(offenders, [], 'nonebot 只能在 main() 里 import（否则离线单测跑不了）')

    def test_bot_module_declares_expected_helpers(self):
        for name in ('target_params', 'NoneBotSender', 'load_config', 'resolve_onebot', 'main'):
            self.assertTrue(hasattr(qqbot, name), 'qq/bot.py 缺少 %s' % name)


class OnebotResolveTests(unittest.TestCase):
    """契约 §9 的 token 优先级与端口解析：env(token_env) > onebot.token；两者都空 -> 拒绝启动。"""

    def test_env_token_wins_over_config(self):
        cfg = {'onebot': {'host': '127.0.0.1', 'port': 18080,
                          'path': '/onebot/v11/ws',
                          'token': '配置文件里的', 'token_env': 'QQ_BOT_ONEBOT_TOKEN'}}
        out = qqbot.resolve_onebot(cfg, {'QQ_BOT_ONEBOT_TOKEN': '环境变量里的'})
        self.assertEqual(out['token'], '环境变量里的')
        self.assertEqual(out['host'], '127.0.0.1')
        self.assertEqual(out['port'], 18080)
        self.assertEqual(out['path'], '/onebot/v11/ws')

    def test_config_token_used_when_env_missing(self):
        cfg = {'onebot': {'token': '配置文件里的', 'token_env': 'SOME_OTHER_ENV'}}
        out = qqbot.resolve_onebot(cfg, {})
        self.assertEqual(out['token'], '配置文件里的')
        self.assertEqual(out['token_env'], 'SOME_OTHER_ENV')
        self.assertEqual(out['port'], 18080, '缺省端口应当是 18080')

    def test_empty_token_is_refused(self):
        with self.assertRaises(qqbot.BotConfigError):
            qqbot.resolve_onebot({'onebot': {'token': '', 'token_env': 'NO_SUCH_ENV'}}, {})
        with self.assertRaises(qqbot.BotConfigError):
            qqbot.resolve_onebot({}, {})

    def test_env_port_overrides_config(self):
        out = qqbot.resolve_onebot({'onebot': {'token': 'x', 'port': 18080}},
                                   {'QQ_BOT_PORT': '19090'})
        self.assertEqual(out['port'], 19090)

    def test_bad_port_is_refused(self):
        with self.assertRaises(qqbot.BotConfigError):
            qqbot.resolve_onebot({'onebot': {'token': 'x', 'port': '不是端口'}}, {})
        with self.assertRaises(qqbot.BotConfigError):
            qqbot.resolve_onebot({'onebot': {'token': 'x', 'port': 99999}}, {})


class ExampleConfigTests(unittest.TestCase):
    """示例配置必须与 INTERFACES.md 第 9 节的冻结 schema 对得上，且不含任何秘密。"""

    @classmethod
    def setUpClass(cls):
        cls.raw = EXAMPLE_CONFIG_PATH.read_text(encoding='utf-8')
        cls.cfg = json.loads(cls.raw)

    def test_frozen_top_level_keys(self):
        required = ['self_id', 'state_dir', 'auto_send', 'onebot', 'napcat',
                    'direct_policy', 'direct_blacklist', 'direct_whitelist',
                    'direct_whitelist', 'group_policy', 'groups', 'mention_aliases',
                    'limits', 'min_reply_seconds', 'max_replies_per_hour', 'max_pending',
                    'task_ttl_seconds', 'reply_max_chars', 'reply_image_limit',
                    'image_generation', 'media', 'links', 'model', 'web_search', 'hot_feed']
        missing = [key for key in required if key not in self.cfg]
        self.assertEqual(missing, [], '示例配置缺字段：%s' % missing)

    def test_onebot_block(self):
        onebot = self.cfg['onebot']
        self.assertEqual(onebot['host'], '127.0.0.1', '反向 ws 只允许监听回环地址')
        self.assertEqual(onebot['port'], 18080)
        self.assertEqual(onebot['path'], '/onebot/v11/ws')
        self.assertEqual(onebot['token_env'], 'QQ_BOT_ONEBOT_TOKEN')
        self.assertEqual(onebot['token'], '', 'token 绝不进仓库')

    def test_napcat_webui_is_loopback(self):
        self.assertEqual(self.cfg['napcat']['webui_host'], '127.0.0.1')
        self.assertEqual(self.cfg['napcat']['webui_port'], 6099)

    def test_groups_are_empty_by_default_and_keyed_by_group_id(self):
        self.assertEqual(self.cfg['groups'], {}, '默认谁都不接')
        self.assertEqual(self.cfg['group_policy'], 'whitelist')
        sample = self.cfg['_groups_示例']
        modes = {entry.get('plain_mode') for key, entry in sample.items() if isinstance(entry, dict)}
        self.assertIn('at_only', modes, '示例里要有 at_only 策略')
        self.assertIn('idle', modes, '示例里要有 idle 策略')

    def test_auto_send_off_by_default(self):
        self.assertIs(self.cfg['auto_send'], False)

    def test_direct_and_limits(self):
        self.assertEqual(self.cfg['direct_policy'], 'blacklist')
        self.assertEqual(self.cfg['direct_blacklist'], [])
        self.assertEqual(self.cfg['limits'], {'window_5h': 100, 'window_1d': 500})
        self.assertEqual(self.cfg['min_reply_seconds'], 3)
        self.assertEqual(self.cfg['max_replies_per_hour'], 30)
        self.assertEqual(self.cfg['max_pending'], 200)
        self.assertEqual(self.cfg['reply_max_chars'], 200)
        self.assertTrue(self.cfg['mention_aliases'])

    def test_state_dir_is_qq_own_directory(self):
        self.assertTrue(self.cfg['state_dir'].endswith('/qq-bot'))
        self.assertNotIn('wechat-bot/', self.cfg['state_dir'], 'state_dir 不能和微信的混用')

    def test_shared_credentials_are_absolute(self):
        for section, key in (('model', 'credential_file'),
                             ('web_search', 'credential_file'),
                             ('image_generation', 'credentials_file')):
            value = self.cfg[section][key]
            self.assertEqual(value, SHARED_CREDENTIALS,
                             '%s.%s 必须复用微信那份 600 凭据的绝对路径' % (section, key))

    def test_model_block_has_no_key(self):
        model = self.cfg['model']
        self.assertTrue(model['base_url'].startswith('https://'))
        self.assertTrue(model['model'])
        self.assertEqual(model['api_key_env'], 'STEP_PLAN_API_KEY')
        self.assertNotIn('api_key', model, '密钥只能走环境变量/凭据文件')
        self.assertFalse(model['api_key_env'].startswith('sk-'))

    def test_image_generation_and_search_defaults(self):
        self.assertIs(self.cfg['image_generation']['enabled'], False)
        self.assertEqual(self.cfg['image_generation']['max_per_hour'], 3)
        self.assertTrue(self.cfg['web_search']['enabled'])
        self.assertEqual(self.cfg['web_search']['provider'], 'tavily')
        for key in ('max_bytes', 'timeout_s', 'max_images', 'keep_days'):
            self.assertIn(key, self.cfg['media'])

    def test_links_block_matches_frozen_defaults(self):
        """契约 §10：links 默认开——别人贴链接就该能读；最多 2 个、总预算 12 秒。"""
        links = self.cfg['links']
        self.assertIs(links['enabled'], True)
        self.assertEqual([links['max_urls'], links['max_bytes'], links['max_chars'],
                          links['timeout'], links['total_budget_seconds']],
                         [2, 250000, 9000, 10, 12])

    def test_hot_feed_is_off_by_default(self):
        """契约 §10：RSSHub 是第三方慢源，示例里默认关；要热榜自己开。"""
        hot = self.cfg['hot_feed']
        self.assertIs(hot['enabled'], False)
        self.assertEqual(hot['refresh_seconds'], 300)
        self.assertIn('要热榜自己', json.dumps(hot, ensure_ascii=False), '得把"要热榜自己开"写清楚')

    def test_core_normalize_reports_zero_warnings(self):
        """契约 §9.5 + §10：示例配置喂给 qq-core 的 normalize 必须零告警（验收脚本会查这条）。"""
        try:
            from qq.core import config as core_config
        except Exception as exc:                    # noqa: BLE001
            self.skipTest('qq/core/config.py 还导不进来：%s' % exc)
        warns = []
        core_config.normalize(self.cfg, env={}, warn=warns.append)
        self.assertEqual(warns, [], 'normalize 对示例配置有告警：%s' % warns)

    def test_no_obvious_secrets_in_example(self):
        self.assertNotIn('sk-', self.raw)
        self.assertIsNone(re.search(r'Bearer\s+[A-Za-z0-9._-]{8,}', self.raw),
                          '示例里不该出现真的 Bearer token（说明文字里提到 Bearer <token> 是允许的）')
        self.assertIsNone(re.search(r'\b[0-9a-fA-F]{32,}\b', self.raw), '示例里不该有长十六进制串')
        self.assertIsNone(re.search(r'\b\d{10,}\b', self.raw), '示例里不该出现真实 QQ 号/群号的痕迹')


@unittest.skipUnless(BRIDGE_SOURCE == 'real', 'qq/core/bridge.py 还没落地（当前用替身）')
class BridgeContractTests(unittest.TestCase):
    """qq-core 落地后自动生效：确保 bridge 与契约 §4 一致（本层按这个接口写的）。"""

    def test_send_result_fields(self):
        import dataclasses as dc
        from qq.core.bridge import SendResult
        if dc.is_dataclass(SendResult):
            names = [f.name for f in dc.fields(SendResult)]
        else:
            names = list(getattr(SendResult, '__annotations__', {}))
        for field in ('ok', 'unknown', 'error', 'message_id'):
            self.assertIn(field, names)

    def test_sender_interface(self):
        from qq.core.bridge import Sender
        for name in ('send_text', 'send_image', 'self_id', 'online'):
            self.assertTrue(hasattr(Sender, name), 'Sender 缺方法 %s' % name)
        self.assertTrue(issubclass(qqbot.NoneBotSender, Sender))


@unittest.skipUnless(HAS_NONEBBOT, '没装 nonebot2：跳过插件本体用例（sender/纯函数用例照跑）')
class PluginRuntimeTests(unittest.TestCase):
    """装了 nonebot 时加载真插件，用假事件 + 假服务跑一遍 handler（不连网、不连真实 QQ）。"""

    plugin = None
    reason = ''
    bot = types.SimpleNamespace(self_id='10001')

    @classmethod
    def setUpClass(cls):
        try:
            import nonebot
            from nonebot.adapters.onebot.v11 import Adapter
            nonebot.init(driver='~fastapi', onebot_access_token='test-token-not-real')
            nonebot.get_driver().register_adapter(Adapter)
        except Exception as exc:                    # noqa: BLE001
            cls.reason = 'nonebot 初始化失败（可能缺 FastAPI 驱动）：%s' % exc
            return
        try:
            import qq.core.envelope                  # noqa: F401  qq-core 提供
        except Exception as exc:                    # noqa: BLE001
            cls.reason = 'qq/core/envelope.py 还没落地：%s' % exc
            return
        try:
            import importlib
            cls.plugin = importlib.import_module('qq.plugins.qq_chat')
        except Exception as exc:                    # noqa: BLE001
            cls.reason = '插件导入失败：%s' % exc

    def setUp(self):
        if self.plugin is None:
            self.skipTest(self.reason or '插件不可用')
        clear_service()

    def tearDown(self):
        clear_service()

    @staticmethod
    def payload(**over) -> dict:
        data = {
            'post_type': 'message', 'message_type': 'private', 'sub_type': 'friend',
            'self_id': 10001, 'user_id': 20002, 'message_id': 333, 'time': 1700000000,
            'font': 0, 'sender': {'user_id': 20002, 'nickname': '测试'},
            'message': [{'type': 'text', 'data': {'text': '你好'}}], 'raw_message': '你好',
        }
        data.update(over)
        return data

    @staticmethod
    def fake_event(data: dict):
        return types.SimpleNamespace(model_dump=lambda: data)

    def run_handler(self, data: dict):
        return asyncio.run(self.plugin.handle_message(self.bot, self.fake_event(data)))

    def test_plugin_loads_via_nonebot_loader_in_fresh_process(self):
        """契约 §8 的 `nonebot.load_plugin('qq.plugins.qq_chat')` 必须能被解析。

        必须开新进程：NoneBot 的加载器要求插件模块"加载前没被 import 过"（import 过就抛
        "not loaded as a plugin"）。子进程只做 init + register_adapter + load_plugin，
        **不调用 nonebot.run()**，所以一个端口都不会监听、也不会出网。
        """
        if not (ROOT / 'qq' / 'core' / 'envelope.py').is_file():
            self.skipTest('qq/core/envelope.py 还没落地')
        script = (
            'import sys\n'
            'sys.path.insert(0, %r)\n'
            'import nonebot\n'
            'from nonebot.adapters.onebot.v11 import Adapter\n'
            "nonebot.init(driver='~fastapi', onebot_access_token='test-token-not-real')\n"
            'nonebot.get_driver().register_adapter(Adapter)\n'
            "plugin = nonebot.load_plugin('qq.plugins.qq_chat')\n"
            "assert plugin is not None, 'load_plugin 返回 None'\n"
            "print('LOADER_OK', plugin.module_name)\n" % str(ROOT)
        )
        proc = subprocess.run([sys.executable, '-c', script], cwd=str(ROOT),
                              capture_output=True, text=True, timeout=180)
        self.assertIn('LOADER_OK', proc.stdout, 'stdout=%s\nstderr=%s' % (proc.stdout, proc.stderr))

    def test_handler_submits_parsed_event(self):
        class FakeService:
            def __init__(self):
                self.events = []

            def submit(self, env):
                self.events.append(env)
                return True

        service = FakeService()
        set_service(service)
        self.run_handler(self.payload())
        self.assertEqual(len(service.events), 1)
        self.assertEqual(service.events[0].chat_type, 'private')
        self.assertEqual(str(service.events[0].chat_id), '20002')

    def test_handler_drops_non_message_events(self):
        class FakeService:
            def __init__(self):
                self.events = []

            def submit(self, env):
                self.events.append(env)
                return True

        service = FakeService()
        set_service(service)
        self.run_handler({'post_type': 'notice', 'notice_type': 'group_recall'})
        self.run_handler(self.payload(sender={'user_id': 10001, 'nickname': '自己'}))
        self.assertEqual(service.events, [], '通知与自己的消息都不该进队列')

    def test_handler_without_service_is_noop(self):
        clear_service()
        self.assertIsNone(self.run_handler(self.payload()))

    def test_handler_swallows_submit_exception(self):
        class Boom:
            def submit(self, env):
                raise RuntimeError('队列炸了')

        set_service(Boom())
        self.assertIsNone(self.run_handler(self.payload()), '单条事件绝不能打挂插件')

    def test_status_command_renders_status(self):
        class FakeService:
            def status(self):
                return {'state': 'running', 'queue_depth': 0, 'online': True}

        set_service(FakeService())
        self.assertIn('状态：running', format_status(FakeService().status()))

    def test_status_command_without_service(self):
        clear_service()
        self.assertIn('未启动', format_status(None))


if __name__ == '__main__':
    unittest.main(verbosity=2)
