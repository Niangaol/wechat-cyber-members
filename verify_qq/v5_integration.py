"""对抗式验证 5：NoneBot 侧、qq/core 纯净性、部署与状态目录隔离（契约 §1/§8/§9）。

离线：不 import nonebot、不连网、不碰生产状态目录。
运行：python3 verify_qq/v5_integration.py
"""
import ast
import asyncio
import base64
import json
import os
import re
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'verify_qq'))

from harness import group, check, eq, observe, run, summary        # noqa: E402
import qq.bot as bot_mod                                           # noqa: E402
from qq.core.envelope import QEvent                                # noqa: E402
from qq.core.bridge import SendResult                              # noqa: E402

SELF = '10001'


def qevent(chat_type='group', chat_id='30003'):
    return QEvent(self_id=SELF, chat_type=chat_type, chat_id=chat_id,
                  sender_id='20002', sender_name='x', message_id='1', time=time.time(),
                  at_me=True, at_all=False, text='hi', images=[], segments=[], raw={})


class LoopThread:
    """后台跑一个 asyncio 事件循环，供 asyncio.run_coroutine_threadsafe 用。"""

    def __init__(self):
        self.loop = asyncio.new_event_loop()
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def _run(self):
        asyncio.set_event_loop(self.loop)
        self.loop.run_forever()

    def close(self):
        self.loop.call_soon_threadsafe(self.loop.stop)
        self.thread.join(3)
        self.loop.close()


class FakeBot:
    def __init__(self, behaviour='ok', delay=0.0, result=None):
        self.calls = []
        self.behaviour = behaviour
        self.delay = delay
        self.result = result if result is not None else {'message_id': 4242}
        self.self_id = SELF
        self.adapter = type('A', (), {'connections': {SELF: object()}})()

    async def call_api(self, action, **params):
        self.calls.append((action, params))
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.behaviour == 'raise':
            raise RuntimeError('call_api 炸了')
        if self.behaviour == 'timeout':
            await asyncio.sleep(30)
        return self.result


# ------------------------------------------------------- §1 qq/core 纯净性
def t_core_no_nonebot_ast():
    """用 AST 检查 import（比 grep 更硬：能抓到 from x import y、import a.b、函数内 import）。"""
    forbidden = {'nonebot', 'asyncio', 'anyio', 'fastapi', 'uvicorn', 'websockets'}
    offenders = []
    files = sorted((ROOT / 'qq' / 'core').glob('*.py'))
    check('qq/core 下有源文件', bool(files), str([f.name for f in files]))
    for path in files:
        tree = ast.parse(path.read_text(encoding='utf-8'))
        for node in ast.walk(tree):
            names = []
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or '']
            for name in names:
                top = str(name).split('.')[0]
                if top in forbidden:
                    offenders.append('%s:%d %s' % (path.name, node.lineno, name))
    eq('qq/core 不 import nonebot/asyncio/fastapi 等（AST 扫描）', offenders, [])

    # 反向确认：bot.py / plugins 里确实用了 nonebot（否则上面是假阳性）
    plugin_src = (ROOT / 'qq' / 'plugins' / 'qq_chat.py').read_text(encoding='utf-8')
    check('对照：qq/plugins/qq_chat.py 确实 import nonebot（证明扫描有效）',
          'from nonebot import' in plugin_src)


def t_core_import_path_magic_only_in_init():
    """契约 §1：src/ 进 sys.path 只允许在 qq/core/__init__.py。"""
    bad = []
    for path in sorted((ROOT / 'qq' / 'core').glob('*.py')):
        if path.name == '__init__.py':
            continue
        text = path.read_text(encoding='utf-8')
        if 'sys.path' in text:
            bad.append(path.name)
    eq('只有 __init__.py 动 sys.path', bad, [])


def t_core_importable_in_clean_process():
    """全新解释器（没有 nonebot）里 import qq.core 全链路必须成功。"""
    script = (
        "import sys; sys.path.insert(0, %r)\n"
        "import qq.core.service, qq.core.worker, qq.core.media\n"
        "import qq.core.policy, qq.core.envelope, qq.core.store, qq.core.config\n"
        "print('ALL_IMPORT_OK')\n" % str(ROOT))
    proc = subprocess.run([sys.executable, '-c', script], capture_output=True,
                          text=True, timeout=120,
                          env={k: v for k, v in os.environ.items()
                               if k not in ('PYTHONPATH',)})
    check('全新解释器里 import qq.core.* 全部成功',
          'ALL_IMPORT_OK' in proc.stdout, proc.stderr.strip()[-300:])
    check('对照：那个解释器里确实没有 nonebot', 'nonebot' not in proc.stdout)


# ------------------------------------------------------- §9.1 token fail-closed
def t_token_env_priority():
    cfg = {'onebot': {'token': 'FROM_FILE', 'token_env': 'MY_TOKEN'}}
    eq('env 优先于文件', bot_mod.resolve_onebot(cfg, env={'MY_TOKEN': 'FROM_ENV'})['token'],
       'FROM_ENV')
    eq('env 缺失时用文件', bot_mod.resolve_onebot(cfg, env={})['token'], 'FROM_FILE')
    eq('env 是空串时用文件',
       bot_mod.resolve_onebot(cfg, env={'MY_TOKEN': ''})['token'], 'FROM_FILE')
    eq('env 是空白时用文件',
       bot_mod.resolve_onebot(cfg, env={'MY_TOKEN': '   '})['token'], 'FROM_FILE')


def t_token_fail_closed():
    for name, cfg, env in [
        ('两者都空', {'onebot': {'token': '', 'token_env': 'T'}}, {}),
        ('两者都缺失', {'onebot': {}}, {}),
        ('onebot 缺失', {}, {}),
        ('onebot 不是 dict', {'onebot': 'x'}, {}),
        ('token 只有空白', {'onebot': {'token': '   '}}, {}),
    ]:
        try:
            bot_mod.resolve_onebot(cfg, env=env)
            check('token fail-closed：%s 必须拒绝启动' % name, False, '竟然通过了')
        except bot_mod.BotConfigError as exc:
            check('token fail-closed：%s 拒绝启动' % name, True, str(exc).splitlines()[0][:60])
        except Exception as exc:
            check('token fail-closed：%s 拒绝启动（异常类型）' % name, False,
                  type(exc).__name__)


def t_token_default_env_name():
    cfg = {'onebot': {'token': 'X'}}
    eq('默认 token_env 名', bot_mod.resolve_onebot(cfg, env={})['token_env'],
       'QQ_BOT_ONEBOT_TOKEN')
    got = bot_mod.resolve_onebot(cfg, env={'QQ_BOT_ONEBOT_TOKEN': 'E'})['token']
    eq('默认 token_env 会被读', got, 'E')


def t_token_never_printed():
    cfg = {'onebot': {'token': 'SECRET-TOKEN-12345'}}
    fp = bot_mod._token_fingerprint('SECRET-TOKEN-12345')
    check('token 指纹不含明文', 'SECRET-TOKEN-12345' not in fp, fp)
    check('token 指纹含长度与哈希前缀', '长度' in fp and 'sha256' in fp, fp)
    for path in ('qq/bot.py', 'qq/core/config.py'):
        text = (ROOT / path).read_text(encoding='utf-8')
        bad = re.findall(r"(?:print|log\.\w+)\([^)]*token[^)]*\)", text)
        check('%s 里没有直接打印 token 变量' % path,
              not any('token[' not in m and 'token)' in m.replace("'token'", '')
                      for m in bad), str(bad)[:200])


def t_port_and_path():
    eq('默认 host/port/path',
       [bot_mod.resolve_onebot({'onebot': {'token': 'T'}}, env={})[k]
        for k in ('host', 'port', 'path')],
       ['127.0.0.1', 18080, '/onebot/v11/ws'])
    eq('环境变量覆盖端口',
       bot_mod.resolve_onebot({'onebot': {'token': 'T'}}, env={'QQ_BOT_PORT': '19999'})['port'],
       19999)
    observe('（观察）port="" 被当成"没写"回落到默认 18080（与 normalize 的取值一致，'
            '不是拒绝）',
            bot_mod.resolve_onebot({'onebot': {'token': 'T', 'port': ''}}, env={})['port']
            == 18080)
    observe('（观察）QQ_BOT_PORT="" 同样回落到默认',
            bot_mod.resolve_onebot({'onebot': {'token': 'T'}},
                                   env={'QQ_BOT_PORT': ''})['port'] == 18080)
    for bad in ('abc', '0', '70000', '-1'):
        try:
            bot_mod.resolve_onebot({'onebot': {'token': 'T', 'port': bad}}, env={})
            check('非法端口 %r 必须拒绝' % bad, False, '竟然通过了')
        except bot_mod.BotConfigError:
            check('非法端口 %r 被拒绝' % bad, True)
        except Exception as exc:
            check('非法端口 %r 被拒绝（异常类型）' % bad, False, type(exc).__name__)
    eq('路径缺省补默认',
       bot_mod.resolve_onebot({'onebot': {'token': 'T', 'path': '  '}}, env={})['path'],
       '/onebot/v11/ws')
    check('适配器写死的路由表非空', len(bot_mod.ADAPTER_WS_PATHS) >= 1,
          str(bot_mod.ADAPTER_WS_PATHS))


# ------------------------------------------------------- §4/§8 发送目标
def t_target_params():
    eq('私聊 → user_id', bot_mod.target_params(qevent('private', '20002')),
       ({'message_type': 'private', 'user_id': 20002}, ''))
    eq('群聊 → group_id', bot_mod.target_params(qevent('group', '30003')),
       ({'message_type': 'group', 'group_id': 30003}, ''))
    for ct, cid in (('guild', '1'), ('', '1'), ('group', ''), ('group', 'abc'),
                    ('group', '-5'), ('group', '0'), ('group', '1.5')):
        params, err = bot_mod.target_params(qevent(ct, cid))
        check('拒绝目标 chat_type=%r chat_id=%r' % (ct, cid),
              params == {} and bool(err), 'params=%r err=%r' % (params, err))


def t_sender_targets_only_own_chat():
    loop = LoopThread()
    try:
        for ct, cid, key in (('group', '30003', 'group_id'),
                             ('private', '20002', 'user_id')):
            fake = FakeBot()
            sender = bot_mod.NoneBotSender(fake, loop.loop)
            res = sender.send_text(qevent(ct, cid), '内容')
            check('%s 发送成功' % ct, res.ok and not res.unknown, res)
            action, params = fake.calls[0]
            eq('%s 用 send_msg' % ct, action, 'send_msg')
            eq('%s 目标参数' % ct, params.get(key), int(cid))
            eq('%s message_type' % ct, params.get('message_type'), ct)
            eq('%s message 结构' % ct, params.get('message'),
               [{'type': 'text', 'data': {'text': '内容'}}])
            check('%s 没有额外的收件人参数（接口不含任意目标）' % ct,
                  set(params) == {'message_type', key, 'message'}, str(sorted(params)))
    finally:
        loop.close()


def t_sender_rejects_bad_target():
    loop = LoopThread()
    try:
        fake = FakeBot()
        sender = bot_mod.NoneBotSender(fake, loop.loop)
        res = sender.send_text(qevent('guild', '1'), 'x')
        eq('不支持会话类型 → 不发', fake.calls, [])
        check('明确失败（unknown=False）', not res.ok and not res.unknown, res)
    finally:
        loop.close()


def t_sender_image_base64():
    loop = LoopThread()
    tmp = Path(tempfile.mkdtemp(prefix='verify-qq-img-'))
    png = tmp / 'a.png'
    png.write_bytes(b'\x89PNG\r\n\x1a\n' + b'x' * 32)
    try:
        fake = FakeBot()
        sender = bot_mod.NoneBotSender(fake, loop.loop)
        res = sender.send_image(qevent('group', '30003'), png)
        check('图片发送成功', res.ok, res)
        _, params = fake.calls[0]
        msg = params['message']
        eq('图片段类型', msg[0]['type'], 'image')
        check('图片走 base64:// 本地字节（不用远端 URL）',
              msg[0]['data']['file'].startswith('base64://'), msg[0]['data']['file'][:30])
        raw = base64.b64decode(msg[0]['data']['file'][len('base64://'):])
        eq('base64 内容与文件一致', raw, png.read_bytes())

        # 超限
        big = tmp / 'big.png'
        big.write_bytes(b'x' * 100)
        sender2 = bot_mod.NoneBotSender(FakeBot(), loop.loop, max_image_bytes=50)
        r2 = sender2.send_image(qevent('group', '30003'), big)
        check('超大图片明确拒绝', not r2.ok and not r2.unknown, r2)
        # 不存在
        r3 = sender.send_image(qevent('group', '30003'), tmp / 'nope.png')
        check('读不到的图片明确拒绝', not r3.ok and not r3.unknown, r3)
        r4 = sender.send_image(qevent('group', '30003'), tmp / 'empty.png')
        check('空文件明确拒绝', not r4.ok, r4)
    finally:
        (tmp / 'empty.png').write_bytes(b'')
        loop.close()


def t_sender_failure_semantics():
    loop = LoopThread()
    try:
        # call_api 抛异常 → unknown（可能已发出）
        s1 = bot_mod.NoneBotSender(FakeBot('raise'), loop.loop)
        r1 = s1.send_text(qevent(), 'x')
        check('call_api 抛异常 → unknown=True（不重发）', r1.unknown and not r1.ok, r1)
        # 超时 → unknown
        s2 = bot_mod.NoneBotSender(FakeBot('timeout'), loop.loop, timeout_s=0.2)
        r2 = s2.send_text(qevent(), 'x')
        check('发送超时 → unknown=True（不重发）', r2.unknown and not r2.ok, r2)
        # 没有 loop → 明确失败，不是 unknown
        s3 = bot_mod.NoneBotSender(FakeBot(), None)
        r3 = s3.send_text(qevent(), 'x')
        check('没有事件循环 → unknown=False（明确没发出去）',
              not r3.ok and not r3.unknown, r3)
        # loop 已关闭
        lt = LoopThread()
        lt.close()
        s4 = bot_mod.NoneBotSender(FakeBot(), lt.loop)
        r4 = s4.send_text(qevent(), 'x')
        check('事件循环已关闭 → unknown=False', not r4.ok and not r4.unknown, r4)
        # 没有 bot
        s5 = bot_mod.NoneBotSender(None, loop.loop, bot_provider=lambda: None)
        r5 = s5.send_text(qevent(), 'x')
        check('没有已连接账号 → unknown=False', not r5.ok and not r5.unknown, r5)
        # 空文本
        s6 = bot_mod.NoneBotSender(FakeBot(), loop.loop)
        r6 = s6.send_text(qevent(), '   ')
        check('空文本不发送', not r6.ok and not r6.unknown, r6)
        eq('空文本没触发 call_api', s6._bot.calls, [])
    finally:
        loop.close()


def t_sender_result_message_id():
    loop = LoopThread()
    try:
        s = bot_mod.NoneBotSender(FakeBot(result={'message_id': 987}), loop.loop)
        eq('从 dict 取 message_id', s.send_text(qevent(), 'x').message_id, '987')
        obj = type('R', (), {'message_id': 555})()
        s2 = bot_mod.NoneBotSender(FakeBot(result=obj), loop.loop)
        eq('从对象取 message_id', s2.send_text(qevent(), 'x').message_id, '555')
        s3 = bot_mod.NoneBotSender(FakeBot(result={}), loop.loop)
        eq('拿不到 message_id 时为空串', s3.send_text(qevent(), 'x').message_id, '')
    finally:
        loop.close()


def t_send_result_normalizes_none():
    r = SendResult(ok=None, unknown=None, error=None, message_id=None)
    eq('SendResult 把 None 归一', (r.ok, r.unknown, r.error, r.message_id),
       (False, False, '', ''))


def t_sender_online():
    loop = LoopThread()
    try:
        s = bot_mod.NoneBotSender(FakeBot(), loop.loop)
        eq('在线（连接表里有这个账号）', s.online(), True)
        bot = FakeBot()
        bot.adapter = type('A', (), {'connections': {}})()
        s2 = bot_mod.NoneBotSender(bot, loop.loop)
        eq('连接表里没有该账号 → 不在线', s2.online(), False)
        s3 = bot_mod.NoneBotSender(None, loop.loop, bot_provider=lambda: None)
        eq('没有 bot → 不在线', s3.online(), False)
        eq('没有 loop → 不在线', bot_mod.NoneBotSender(FakeBot(), None).online(), False)
        eq('self_id 透传', s.self_id(), SELF)
    finally:
        loop.close()


def t_plugin_never_awaits_in_handler():
    """契约 §8：handle_message 里不允许出现 await（AST 检查，不是看文本）。"""
    path = ROOT / 'qq' / 'plugins' / 'qq_chat.py'
    tree = ast.parse(path.read_text(encoding='utf-8'))
    handlers = {}
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            handlers[node.name] = node
    target = handlers.get('handle_message')
    check('找到 handle_message', target is not None)
    awaits = [n.lineno for n in ast.walk(target)
              if isinstance(n, (ast.Await, ast.AsyncFor, ast.AsyncWith))]
    eq('handle_message 里没有 await/async for/async with', awaits, [])
    calls = {n.func.id for n in ast.walk(target)
             if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
    check('handle_message 只做 envelope 解析 + submit',
          {'from_onebot_event', 'get_service'} <= calls, str(sorted(calls)))


# ------------------------------------------------------- §9 示例配置
def t_example_config_matches_schema():
    from qq.core import config as config_module
    data = json.loads((ROOT / 'qq' / 'config' / 'qq.example.json').read_text(encoding='utf-8'))
    schema = config_module.SCHEMA_KEYS
    real = {k for k in data if not str(k).startswith('_')}
    missing = sorted(schema - real)
    extra = sorted(real - schema - {'links'})
    eq('示例配置缺的 §9 冻结字段', missing, [])
    eq('示例配置多出的未知字段', extra, [])
    onebot = data['onebot']
    for key in ('host', 'port', 'path', 'token', 'token_env'):
        check('onebot 含 %s' % key, key in onebot)
    eq('示例里 token 是占位符（空）', onebot['token'], '')
    eq('示例里 host 是回环', onebot['host'], '127.0.0.1')
    eq('示例里 auto_send 默认关', data['auto_send'], False)
    eq('示例里 group_policy 固定 whitelist', data['group_policy'], 'whitelist')
    text = (ROOT / 'qq' / 'config' / 'qq.example.json').read_text(encoding='utf-8')
    check('示例文件里没有真实 QQ 号（只有示例号）',
          not re.search(r'\b[1-9]\d{8,10}\b', text.replace('123456789', '')),
          str(re.findall(r'\b[1-9]\d{8,10}\b', text))[:80])
    check('示例配置能被 normalize 吃下（含未知键只 warn 不崩）',
          isinstance(config_module.normalize(data, env={}, warn=lambda m: None), dict))
    warns = []
    config_module.normalize(data, env={}, warn=warns.append)
    eq('示例配置本身不产生任何告警（逐字对得上）', warns, [])


def t_production_state_dir_not_touched():
    """默认 state_dir 必须指向 ~/.local/state/qq-bot，且本套验证不创建它。"""
    from qq.core import config as config_module
    eq('DEFAULT_STATE_DIR', config_module.DEFAULT_STATE_DIR, '~/.local/state/qq-bot')
    eq('expanduser 后', str(config_module.effective_state_dir({})),
       str(Path('~/.local/state/qq-bot').expanduser()))
    check('本套验证没有创建生产状态目录',
          not (Path('~/.local/state/qq-bot').exists()
               and os.environ.get('VERIFY_TOUCHED_PROD') == '1'))


def t_custom_state_dir_isolated():
    """给了自定义 state_dir 时，QQService 只在那里落文件。"""
    from qq.core.service import QQService
    from qq.core.bridge import Sender

    class S(Sender):
        def send_text(self, e, t):
            return SendResult(True, False)
        def send_image(self, e, p):
            return SendResult(True, False)
        def self_id(self):
            return SELF
        def online(self):
            return True
    tmp = Path(tempfile.mkdtemp(prefix='verify-qq-state-'))
    prod = Path('~/.local/state/qq-bot').expanduser()
    before = set(os.listdir(prod)) if prod.exists() else None
    svc = QQService({'state_dir': str(tmp), 'hot_feed': {'enabled': False}},
                    ROOT, S(), db_path=str(tmp / 'a.db'))
    svc.status()
    after = set(os.listdir(prod)) if prod.exists() else None
    eq('生产状态目录内容没有变化', before, after)
    eq('自定义目录里有 db', (tmp / 'a.db').exists(), True)
    eq('自定义目录里有 status.json', (tmp / 'status.json').exists(), True)
    eq('目录权限 700', oct(os.stat(tmp).st_mode & 0o777), '0o700')


def t_deploy_files_sane():
    service = ROOT / 'wsl' / 'qq-bot.service'
    check('qq-bot.service 存在', service.is_file())
    text = service.read_text(encoding='utf-8')
    check('service 里没有明文 token', 'token=' not in text.replace('token_env', ''),
          [l for l in text.splitlines() if 'token' in l.lower()][:4])
    check('service 是 User 级（无 User=root 之类）', 'User=root' not in text)
    check('service 有 Restart 策略', 'Restart=' in text)
    check('service 指向 qq.bot 入口', 'qq.bot' in text or 'qq/bot.py' in text)
    sh = ROOT / 'wsl' / 'install-qq.sh'
    sh_text = sh.read_text(encoding='utf-8')
    check('install-qq.sh 有 pipefail', 'set -euo pipefail' in sh_text or 'set -eu' in sh_text)
    for name in ('wsl/qq-health.py', 'wsl/qq-acceptance.py', 'wsl/qq-napcat.service',
                 'docs/QQ.md'):
        check('%s 存在' % name, (ROOT / name).is_file())
    for name in ('wsl/qq-health.py', 'wsl/qq-acceptance.py'):
        proc = subprocess.run([sys.executable, '-m', 'py_compile', str(ROOT / name)],
                              capture_output=True, text=True)
        eq('%s 语法正确' % name, proc.returncode, 0)


group('§1 qq/core 纯净性（不依赖 nonebot/asyncio）')
for fn in (t_core_no_nonebot_ast, t_core_import_path_magic_only_in_init,
           t_core_importable_in_clean_process):
    run(fn)

group('§9.1 token fail-closed')
for fn in (t_token_env_priority, t_token_fail_closed, t_token_default_env_name,
           t_token_never_printed, t_port_and_path):
    run(fn)

group('§4/§8 只发到 event 自己的会话 + 失败语义')
for fn in (t_target_params, t_sender_targets_only_own_chat, t_sender_rejects_bad_target,
           t_sender_image_base64, t_sender_failure_semantics,
           t_sender_result_message_id, t_send_result_normalizes_none,
           t_sender_online, t_plugin_never_awaits_in_handler):
    run(fn)

group('§9 示例配置与生产状态目录隔离')
for fn in (t_example_config_matches_schema, t_production_state_dir_not_touched,
           t_custom_state_dir_isolated, t_deploy_files_sane):
    run(fn)

summary('集成/部署验证')
