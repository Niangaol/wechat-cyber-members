#!/usr/bin/env python3
"""QQ 侧离线验收：把所有"不连真实 QQ 就能验"的闸门跑一遍，最后给一张表。

覆盖（契约 qq/core/INTERFACES.md §9 与部署约定）：
  1. 部署物 · systemd 单元静态检查（ExecStart/EnvironmentFile/Restart、无 DISPLAY、不依赖微信）
  2. 部署物 · install-qq.sh 安全检查（bash -n 语法 + 不含 sudo 执行 + 不启停服务 + 不碰微信）
  3. 部署物 · 文档与验收脚本齐备（docs/QQ.md、wsl/qq-health.py、README 里的 QQ 入口）
  4. 代码齐备性（qq/core 契约模块 + qq/bot.py + 示例配置 + requirements）
  5. 离线单测 test_qq_*（unittest discover，只挑 QQ 的，0 条 = FAIL）
  6. 配置 schema（qq.json 冻结版：token 生效性、groups 白名单、napcat 回环、plain_mode 取值…）
  7. 启动自检（venv 里跑 python -m qq.bot --check：0=可启动 / 2=token或端口 / 3=依赖或核心模块）
  8. STOP 语义 + status.json 落盘（tmpdir 里真跑 QQService，绝不用生产状态目录）
  9. 状态目录权限 700
 10. NapCat ⇄ NoneBot 一致性（端口/路径/token/messagePostFormat/reportSelfMessage + WebUI 回环）
 11. venv 与依赖（QQ 专用 venv 里能 import nonebot）

用法：
    python3 wsl/qq-acceptance.py                      # 完整验收
    python3 wsl/qq-acceptance.py --no-tests           # 跳过单测（快）
    python3 wsl/qq-acceptance.py --allow-uninstalled  # 本机还没安装：相关项记 SKIP 而不是 FAIL
    python3 wsl/qq-acceptance.py --config /path/qq.json --env-file /path/qq.env
    python3 wsl/qq-acceptance.py --json               # 机器可读结果
退出码：0 = 全过（允许有 SKIP）；1 = 有 FAIL。
本脚本只读 + 只写自己的临时目录；不连外网、不碰微信服务、不碰 ~/.local/state/wechat-bot/。
"""
import argparse
import hashlib
import importlib
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
CONF_DEFAULT = Path.home() / '.config' / 'qq-bot' / 'qq.json'
ENV_DEFAULT = Path.home() / '.config' / 'qq-bot' / 'qq.env'
STATE_DEFAULT = Path.home() / '.local' / 'state' / 'qq-bot'
VENV_DEFAULT = Path.home() / '.local' / 'share' / 'qq-bot' / 'venv'
CORE_MODULES = ('config', 'envelope', 'policy', 'bridge', 'media', 'store', 'service', 'worker')
PLAIN_MODES = ('at_only', 'selective', 'idle', 'all')
# OneBot v11 适配器把路由写死成这三个（qq-nonebot 实测），配置里的 path 必须落在这里面，否则 NapCat 连过来 404
ALLOWED_WS_PATHS = ('/onebot/v11/', '/onebot/v11/ws', '/onebot/v11/ws/')
NAP_CONFIG_DIRS = (Path.home() / 'Napcat' / 'opt' / 'QQ' / 'resources' / 'app' / 'app_launcher' / 'napcat' / 'config',
                   Path('/opt/QQ/resources/app/app_launcher/napcat/config'),
                   Path.home() / '.config' / 'QQ' / 'NapCat' / 'config')

RESULTS = []
ARGS = None


class SkipCheck(Exception):
    """这项现在不适用（还没安装 / 别人还没交付）——不算失败，但要在表里如实写出来。"""


def check(name, fn):
    try:
        detail = fn() or ''
    except SkipCheck as exc:
        RESULTS.append(('SKIP', name, str(exc)))
    except Exception as exc:                            # noqa: BLE001
        RESULTS.append(('FAIL', name, '%s: %s' % (type(exc).__name__, str(exc)[:200])))
    else:
        RESULTS.append(('PASS', name, detail))


def need_install(what):
    """本机"还没安装"这类缺失：默认算 FAIL，--allow-uninstalled 时降级为 SKIP。"""
    if ARGS.allow_uninstalled:
        raise SkipCheck('%s（--allow-uninstalled：安装前的自检，不算失败）' % what)
    raise AssertionError('%s；先跑 bash wsl/install-qq.sh' % what)


def read_json(path):
    try:
        return json.loads(Path(path).read_text(encoding='utf-8'))
    except Exception:                                   # noqa: BLE001
        return None


def read_env_file(path):
    """把 qq.env 读成 dict：验收脚本是手工跑的，QQ_BOT_ONEBOT_TOKEN 通常只在服务环境里。"""
    out = {}
    try:
        for line in Path(path).read_text(encoding='utf-8').splitlines():
            line = line.strip()
            if not line or line.startswith('#') or '=' not in line:
                continue
            k, v = line.split('=', 1)
            out[k.strip()] = v.strip().strip('"').strip("'")
    except Exception:                                   # noqa: BLE001
        pass
    return out


def env_file_path():
    """qq.env 的路径：可用 --env-file 覆盖（测试要能指向临时文件，别读真 token）。"""
    return Path(ARGS.env_file).expanduser() if getattr(ARGS, 'env_file', None) else ENV_DEFAULT


def env_lookup(key):
    """取值优先级：真环境变量 > qq.env（systemd 的 EnvironmentFile）。"""
    if key in os.environ and os.environ[key].strip():
        return os.environ[key].strip(), '环境变量'
    val = read_env_file(env_file_path()).get(key, '')
    if val.strip():
        return val.strip(), str(env_file_path())
    return '', '未设置'


def cfg_path():
    return Path(ARGS.config).expanduser() if ARGS.config else CONF_DEFAULT


def load_cfg(required=True):
    path = cfg_path()
    cfg = read_json(path)
    if not isinstance(cfg, dict):
        if required:
            need_install('读不到配置 %s' % path)
        raise SkipCheck('读不到配置 %s' % path)
    return cfg


def effective_token(cfg):
    """契约 §9.1：环境变量（onebot.token_env 指定）优先，其次 onebot.token；返回 (token, 来源)。"""
    onebot = cfg.get('onebot') if isinstance(cfg.get('onebot'), dict) else {}
    name = onebot.get('token_env') or 'QQ_BOT_ONEBOT_TOKEN'
    tok, where = env_lookup(str(name))
    if tok:
        return tok, '%s（%s）' % (name, where)
    raw = onebot.get('token')
    if isinstance(raw, str) and raw.strip():
        return raw.strip(), 'qq.json:onebot.token'
    return '', '空'


def token_fp(tok):
    """比对用的指纹：只泄漏长度和哈希前 8 位，绝不打印明文。"""
    return '长度%d/sha256前8=%s' % (len(tok), hashlib.sha256(tok.encode('utf-8')).hexdigest()[:8])


# ---------------------------------------------------------------- 1. systemd 单元
def unit_lines(path):
    """返回去掉注释和空行后的指令行（systemd 眼里只有这些行才算数）。"""
    out = []
    for line in path.read_text(encoding='utf-8').splitlines():
        s = line.strip()
        if not s or s.startswith('#') or s.startswith(';'):
            continue
        out.append(s)
    return out


def check_units():
    problems, infos = [], []
    bot_unit = ROOT / 'wsl' / 'qq-bot.service'
    nap_unit = ROOT / 'wsl' / 'qq-napcat.service'
    for p in (bot_unit, nap_unit):
        if not p.exists():
            problems.append('缺 %s' % p.name)
    if problems:
        raise AssertionError('；'.join(problems))

    lines = unit_lines(bot_unit)
    text = '\n'.join(lines)
    if 'WorkingDirectory=/mnt/d/AgentPrograms/wechat-bot' not in text:
        problems.append('WorkingDirectory 不是仓库根')
    m = [l for l in lines if l.startswith('ExecStart=')]
    if not m:
        problems.append('没有 ExecStart')
    else:
        ex = m[0]
        if '/venv/bin/python' not in ex:
            problems.append('ExecStart 没用 QQ 专用 venv 的 python：%s' % ex)
        if '-m qq.bot' not in ex:
            problems.append('ExecStart 不是 python -m qq.bot：%s' % ex)
    if not [l for l in lines if l.startswith('EnvironmentFile=') and 'qq.env' in l]:
        problems.append('没有 EnvironmentFile=…/qq-bot/qq.env')
    if 'Restart=always' not in lines:
        problems.append('Restart 不是 always')
    if [l for l in lines if re.match(r'^\s*Environment\s*=.*\bDISPLAY=', l)]:
        problems.append('单元里设置了 DISPLAY（QQ 链路不该有虚拟屏）')
    for l in lines:
        mm = re.match(r'^(PartOf|BindsTo|Requires|Wants|After|Before)\s*=\s*(.+)$', l)
        if mm and 'wechat' in mm.group(2):
            problems.append('单元依赖了微信服务：%s' % l)
    # 允许 UnsetEnvironment=DISPLAY（那是清理，不是设置）
    if not [l for l in lines if l.startswith('UnsetEnvironment=') and 'DISPLAY' in l]:
        infos.append('提示：没有 UnsetEnvironment=DISPLAY（建议显式清掉，防止继承 :99）')
    infos.append('qq-bot: ExecStart=%s' % (m[0] if m else '?'))
    if problems:
        raise AssertionError('；'.join(problems))
    return '；'.join(infos)


# ------------------------------------------------------- 2. install-qq.sh 安全检查
def check_install_script():
    sh = ROOT / 'wsl' / 'install-qq.sh'
    if not sh.exists():
        raise AssertionError('缺 wsl/install-qq.sh')
    done = subprocess.run(['bash', '-n', str(sh)], capture_output=True, text=True, timeout=30)
    if done.returncode != 0:
        raise AssertionError('bash -n 语法检查失败：%s' % done.stderr.strip()[:200])
    src = sh.read_text(encoding='utf-8')
    bad = []
    if re.search(r'(?m)^\s*sudo\b', src):
        bad.append('脚本里有直接执行的 sudo')
    if re.search(r'(?m)^\s*systemctl\s+--user\s+(start|stop|restart|enable|disable|kill|reload)\b', src):
        bad.append('脚本会启停/开关服务（只允许 daemon-reload）')
    if re.search(r'systemctl[^\n]*wechat', src):
        bad.append('脚本的 systemctl 调用里出现了微信服务')
    if re.search(r'wechat-bot\.service|wechat-stack\.service|wechat-soak\.service', src):
        bad.append('脚本提到了微信的单元文件')
    if 'state/wechat-bot' in src and not re.search(r'不写', src):
        bad.append('脚本可能写微信的状态目录')
    if bad:
        raise AssertionError('；'.join(bad))
    has_next = '剩下的必须由人来做' in src
    return 'bash -n 通过；无 sudo 执行、不启停服务、不碰微信；含人工步骤清单=%s' % has_next


# ---------------------------------------------------------- 3. 文档与脚本齐备性
def check_docs():
    problems = []
    qqmd = ROOT / 'docs' / 'QQ.md'
    health = ROOT / 'wsl' / 'qq-health.py'
    for p in (qqmd, health):
        if not p.exists():
            problems.append('缺 %s' % p.relative_to(ROOT))
    if qqmd.exists():
        doc = qqmd.read_text(encoding='utf-8')
        for kw in ('NapCat', '18080', '反向 WS', '回滚', '风控', '6099', '127.0.0.1'):
            if kw not in doc:
                problems.append('docs/QQ.md 缺少关键内容：%s' % kw)
    readme = ROOT / 'README.md'
    if readme.exists():
        text = readme.read_text(encoding='utf-8')
        if 'docs/QQ.md' not in text:
            problems.append('README.md 没有链到 docs/QQ.md')
        elif 'NapCat' not in text:
            problems.append('README.md 的 QQ 段落没写清 NapCat 接入')
    else:
        problems.append('缺 README.md')
    if not (ROOT / 'wsl' / 'install-qq.sh').exists():
        problems.append('缺 wsl/install-qq.sh')
    if problems:
        raise AssertionError('；'.join(problems))
    return 'docs/QQ.md + wsl/qq-health.py + install-qq.sh 齐备；README 有 QQ 入口'


# --------------------------------------------------------------- 4. 代码齐备性
def check_files():
    missing = []
    for name in CORE_MODULES:
        if not (ROOT / 'qq' / 'core' / (name + '.py')).exists():
            missing.append('qq/core/%s.py' % name)
    for rel in ('qq/bot.py', 'qq/plugins/qq_chat.py', 'qq/config/qq.example.json', 'qq/requirements.txt'):
        if not (ROOT / rel).exists():
            missing.append(rel)
    if missing:
        raise AssertionError('契约要求的文件还没到位：%s' % '、'.join(missing))
    return 'qq/core 8 个契约模块 + bot/plugin/示例配置/依赖清单 全部就位'


# ------------------------------------------------------------------- 5. 离线单测
def check_tests():
    if ARGS.no_tests:
        raise SkipCheck('按 --no-tests 跳过')
    # 优先用 QQ 专用 venv 的解释器：装了 nonebot 才能把插件测试全跑起来
    # （系统 python3 下 test_qq_plugin 有 7 条会自动 skip，覆盖不全）。
    venv_py = VENV_DEFAULT / 'bin' / 'python'
    interp = str(venv_py) if venv_py.exists() else sys.executable
    which = 'venv' if interp != sys.executable else '系统 python3'
    done = subprocess.run([interp, '-m', 'unittest', 'discover', '-p', 'test_qq_*.py', '-v'],
                          cwd=str(ROOT), capture_output=True, text=True, timeout=900)
    out = (done.stdout or '') + (done.stderr or '')
    ran = 0
    mm = re.search(r'Ran (\d+) tests?', out)
    if mm:
        ran = int(mm.group(1))
    if ran == 0:
        raise AssertionError('一条 test_qq_* 都没跑到（QQ 侧还没有离线测试）')
    if done.returncode != 0 or 'FAILED' in out:
        tail = '\n'.join([l for l in out.splitlines() if l.strip()][-12:])
        raise AssertionError('单测没全绿：Ran %d tests，尾巴：%s' % (ran, tail.replace('\n', ' | ')[:400]))
    return 'Ran %d tests，全绿（test_qq_*，离线，解释器=%s）' % (ran, which)


# ------------------------------------------------------------------ 6. 配置 schema
def check_schema():
    cfg = load_cfg()
    problems, warns = [], []
    if not isinstance(cfg, dict):
        raise AssertionError('顶层不是对象')

    onebot = cfg.get('onebot')
    if not isinstance(onebot, dict):
        problems.append('缺 onebot 段')
        onebot = {}
    port = onebot.get('port')
    if not isinstance(port, int) or not (1024 <= port <= 65535):
        problems.append('onebot.port 不是合法端口：%r' % (port,))
    path = onebot.get('path')
    if not isinstance(path, str) or not path.startswith('/'):
        problems.append('onebot.path 必须以 / 开头：%r' % (path,))
    elif path not in ALLOWED_WS_PATHS:
        problems.append('onebot.path=%r 不在适配器写死的路由 %s 里（NapCat 连过来会 404）'
                        % (path, '、'.join(ALLOWED_WS_PATHS)))
    host = onebot.get('host')
    if host != '127.0.0.1':
        warns.append('onebot.host=%r（反向 WS 只该听回环）' % (host,))

    tok, where = effective_token(cfg)
    if not tok:
        problems.append('生效 token 为空（env %s 与 qq.json onebot.token 都空，程序会拒绝启动）'
                        % (onebot.get('token_env') or 'QQ_BOT_ONEBOT_TOKEN'))
    else:
        warns.append('token 来源：%s · %s' % (where, token_fp(tok)))

    envport, envwhere = env_lookup('QQ_BOT_PORT')
    if envport and port and str(envport) != str(port):
        problems.append('QQ_BOT_PORT=%s（%s）与 onebot.port=%s 不一致' % (envport, envwhere, port))

    envcfg, _ = env_lookup('QQ_BOT_CONFIG')
    if envcfg and Path(envcfg).expanduser().resolve() != cfg_path().resolve():
        warns.append('QQ_BOT_CONFIG=%s 与本次验收读的 %s 不是同一个文件' % (envcfg, cfg_path()))

    groups = cfg.get('groups')
    if groups is None:
        problems.append('缺 groups（群白名单）：契约要求显式给出，谁都没登记就谁都不接')
    elif not isinstance(groups, dict):
        problems.append('groups 必须是 dict（键=群号字符串），现在是 %s' % type(groups).__name__)
    elif not groups:
        warns.append('groups 是空 dict（合法 = 谁都不接）；要接群请显式登记群号')
    else:
        for gid, item in groups.items():
            if not re.fullmatch(r'\d+', str(gid)):
                problems.append('groups 的键不是数字群号：%r' % (gid,))
            if not isinstance(item, dict):
                problems.append('groups[%s] 不是对象' % gid)
                continue
            mode = item.get('plain_mode', 'at_only')
            if mode not in PLAIN_MODES:
                problems.append('groups[%s].plain_mode=%r 不在 %s 里' % (gid, mode, '/'.join(PLAIN_MODES)))
            for key in ('plain_cooldown_s', 'plain_per_hour', 'followup_window_s'):
                if key in item and not isinstance(item[key], int):
                    problems.append('groups[%s].%s 不是整数' % (gid, key))

    dp = cfg.get('direct_policy', 'blacklist')
    if dp not in ('blacklist', 'whitelist'):
        warns.append('direct_policy=%r 非法（契约：按 blacklist 处理并 warn）' % (dp,))
    if cfg.get('group_policy') != 'whitelist':
        problems.append('group_policy 必须是 whitelist（固定值）：%r' % (cfg.get('group_policy'),))

    sd = cfg.get('state_dir')
    if not isinstance(sd, str) or not sd.strip():
        problems.append('state_dir 缺失或不是字符串')
    nap = cfg.get('napcat') if isinstance(cfg.get('napcat'), dict) else {}
    if nap.get('webui_host') != '127.0.0.1':
        problems.append('napcat.webui_host=%r 不是 127.0.0.1（0.0.0.0 等于把面板暴露到局域网）'
                        % (nap.get('webui_host'),))
    if 'webui_port' in nap and not isinstance(nap.get('webui_port'), int):
        problems.append('napcat.webui_port 不是整数')

    rmc = cfg.get('reply_max_chars')
    if not isinstance(rmc, int) or rmc <= 0:
        problems.append('reply_max_chars 必须是正整数：%r' % (rmc,))
    limits = cfg.get('limits')
    if not isinstance(limits, dict) or not limits:
        problems.append('缺 limits（额度池 window_5h/window_1d）')
    else:
        for k in ('window_5h', 'window_1d'):
            if k in limits and not isinstance(limits[k], int):
                problems.append('limits.%s 不是整数' % k)
    if not isinstance(cfg.get('auto_send'), bool):
        problems.append('auto_send 必须是 bool（总闸）')
    elif cfg.get('auto_send'):
        warns.append('auto_send=true：会真发消息，确认这是验收之后的状态')

    if problems:
        raise AssertionError('；'.join(problems[:4]) + ('（共 %d 项）' % len(problems)))
    detail = 'schema 通过'
    if groups:
        detail += ' · groups=%d 个群' % len(groups)
    if warns:
        detail += ' · 提示：' + '；'.join(warns[:3])
    return detail


# ------------------------------------- 7. 启动自检（python -m qq.bot --check 门禁）
def check_startup_gate():
    """qq-nonebot 提供的门禁：--check 退出码 0=可启动 / 2=token 或端口问题 / 3=依赖或核心模块缺失。

    用**临时配置**跑：state_dir 指向 tmpdir，绝不把自检的副作用落到生产状态目录；
    cwd 用仓库根，确保 import 的是仓库里的 qq 包。
    """
    cfg = load_cfg()
    venv_py = VENV_DEFAULT / 'bin' / 'python'
    if not venv_py.exists():
        need_install('QQ 专用 venv 不存在（%s）' % VENV_DEFAULT)
    onebot = cfg.get('onebot') if isinstance(cfg.get('onebot'), dict) else {}
    tok, where = effective_token(cfg)
    tmp = Path(tempfile.mkdtemp(prefix='qq-accept-check-'))
    tmp_cfg = tmp / 'qq.json'
    probe = dict(cfg)
    probe['state_dir'] = str(tmp)
    tmp_cfg.write_text(json.dumps(probe, ensure_ascii=False), encoding='utf-8')

    env = {k: v for k, v in os.environ.items() if not k.startswith('QQ_BOT_')}
    env['QQ_BOT_CONFIG'] = str(tmp_cfg)
    if onebot.get('port') is not None:
        env['QQ_BOT_PORT'] = str(onebot.get('port'))
    if tok:
        env[str(onebot.get('token_env') or 'QQ_BOT_ONEBOT_TOKEN')] = tok
    done = subprocess.run([str(venv_py), '-m', 'qq.bot', '--check', '--config', str(tmp_cfg)],
                          cwd=str(ROOT), capture_output=True, text=True, timeout=180, env=env)
    out = (done.stdout or '') + (done.stderr or '')
    tail = ' | '.join(l.strip() for l in out.splitlines() if l.strip())[-220:]
    if done.returncode != 0:
        raise AssertionError('--check 退出码 %d（0=可启动/2=token或端口/3=依赖或核心模块）：%s'
                             % (done.returncode, tail))
    return '--check 退出码 0：%s' % tail


# ------------------------------------------------- 8. STOP 语义（tmpdir 行为验证）
class _FakeSender:
    def __init__(self, result_cls):
        self.result_cls = result_cls
        self.sent = []

    def send_text(self, event, text):
        self.sent.append(('text', text))
        return self.result_cls(ok=True, unknown=False, error='', message_id='fake')

    def send_image(self, event, path):
        self.sent.append(('image', str(path)))
        return self.result_cls(ok=True, unknown=False, error='', message_id='fake')

    def self_id(self):
        return '10001'

    def online(self):
        return True


def check_stop():
    example = ROOT / 'qq' / 'config' / 'qq.example.json'
    cfg = read_json(example)
    if not isinstance(cfg, dict):
        raise SkipCheck('还没有 qq/config/qq.example.json，构造不出 cfg')
    sys.path.insert(0, str(ROOT))
    try:
        env_mod = importlib.import_module('qq.core.envelope')
        svc_mod = importlib.import_module('qq.core.service')
    except Exception as exc:                            # noqa: BLE001
        raise SkipCheck('qq/core（envelope/service）还导不进来：%s: %s' % (type(exc).__name__, exc))
    QQService = getattr(svc_mod, 'QQService', None)
    if QQService is None:
        raise AssertionError('qq/core/service.py 里没有 QQService（契约 §7）')
    result_cls = getattr(svc_mod, 'SendResult', None) or getattr(
        importlib.import_module('qq.core.bridge'), 'SendResult')

    payload = {'post_type': 'message', 'message_type': 'private', 'self_id': '10001',
               'user_id': '20002', 'message_id': 'accept-1', 'time': time.time(),
               'sender': {'user_id': '20002', 'nickname': '验收'}, 'raw_message': '验收消息',
               'message': [{'type': 'text', 'data': {'text': '验收消息'}}]}
    event = env_mod.from_onebot_event(payload)
    if event is None:
        raise AssertionError('from_onebot_event 把一条正常私聊事件判成了 None')

    tmp = Path(tempfile.mkdtemp(prefix='qq-accept-'))
    cfg = dict(cfg)
    cfg['state_dir'] = str(tmp)
    cfg['auto_send'] = True                             # 故意开着：STOP 必须在发送之前拦住
    cfg['model'] = dict(cfg.get('model') or {}, enabled=False)   # 离线：不调模型、不出网
    sender = _FakeSender(result_cls)
    svc = None
    try:
        (tmp / 'STOP').write_text('验收用\n', encoding='utf-8')
        svc = QQService(cfg, ROOT, sender)
        st = svc.status()
        if st.get('stop') is not True:
            raise AssertionError('STOP 在位时 status().stop=%r，应为 True' % (st.get('stop'),))
        svc.start()
        svc.submit(event)
        time.sleep(2.0)
        if sender.sent:
            raise AssertionError('STOP 在位竟然发送了 %d 条：%r' % (len(sender.sent), sender.sent[:2]))
        if not (tmp / 'status.json').exists():
            raise AssertionError('status.json 没有落盘（契约 §7 要求原子写）')
        (tmp / 'STOP').unlink()
        time.sleep(0.5)
        if svc.status().get('stop') is not False:
            raise AssertionError('删掉 STOP 之后 stop 仍是 True（急停解不掉）')
    finally:
        if svc is not None:
            try:
                svc.stop(timeout=3.0)
            except Exception:                           # noqa: BLE001
                pass
    return 'STOP 在位：不发送 + status.stop=True + status.json 落盘；删除 STOP：stop=False（用临时目录，未碰生产库）'


# ------------------------------------------------------------- 9. 状态目录权限 700
def check_state_dir():
    cfg = load_cfg()
    raw = cfg.get('state_dir') or str(STATE_DEFAULT)
    state = Path(raw).expanduser()
    if not state.exists():
        need_install('状态目录 %s 不存在' % state)
    mode = state.stat().st_mode & 0o777
    if mode != 0o700:
        raise AssertionError('状态目录权限是 %o，必须是 700（里面有 db/media/status.json）' % mode)
    envp = env_file_path()
    if envp.exists():
        emode = envp.stat().st_mode & 0o777
        if emode != 0o600:
            raise AssertionError('%s 权限是 %o，必须是 600（里面有 token）' % (envp, emode))
    extra = ''
    for f in ('status.json', 'STOP'):
        if (state / f).exists():
            extra += ' · 存在 %s' % f
    return '状态目录 %s 权限 700%s' % (state, extra)


# ------------------------------------------ 10. NapCat ⇄ NoneBot 端口/token 一致性
def _pick_onebot_config():
    for d in NAP_CONFIG_DIRS:
        if not d.is_dir():
            continue
        cands = sorted(list(d.glob('onebot11_*.json')) + list(d.glob('onebot11.json')))
        for c in cands:
            data = read_json(c)
            net = (data or {}).get('network') if isinstance(data, dict) else None
            if isinstance(net, dict) and net.get('websocketClients'):
                return c, data
        if cands:
            return cands[0], read_json(cands[0])
    return None, None


def _first_ws_client(data):
    net = (data or {}).get('network') if isinstance(data, dict) else None
    clients = net.get('websocketClients') if isinstance(net, dict) else None
    if isinstance(clients, list) and clients and isinstance(clients[0], dict):
        return clients[0]
    return None


def check_napcat():
    cfg = load_cfg()
    onebot = cfg.get('onebot') if isinstance(cfg.get('onebot'), dict) else {}
    port, path = onebot.get('port'), onebot.get('path') or '/onebot/v11/ws'
    tok, where = effective_token(cfg)

    conf, data = _pick_onebot_config()
    if conf is None:
        raise SkipCheck('没找到 NapCat 配置（找过：%s），NapCat 还没装/还没配就跳过'
                        % '、'.join(str(d) for d in NAP_CONFIG_DIRS))
    client = _first_ws_client(data)
    if client is None:
        raise AssertionError('%s 里没有启用的 websocketClients（反向 WS 没配，NapCat 连不上 NoneBot）' % conf)

    problems, infos = [], []
    url = str(client.get('url') or '')
    parsed = urlparse(url)
    if parsed.port != port:
        problems.append('ws 客户端 url 端口 %r != onebot.port %r（url=%s）' % (parsed.port, port, url))
    if (parsed.path or '') != path:
        problems.append('ws 客户端 url 路径 %r != onebot.path %r' % (parsed.path, path))
    nap_tok = client.get('token')
    nap_tok = nap_tok.strip() if isinstance(nap_tok, str) else ''
    if not nap_tok:
        problems.append('NapCat ws 客户端 token 为空（NoneBot 侧有 token 时会被 403 拒掉）')
    elif not tok:
        problems.append('NoneBot 侧生效 token 为空，但 NapCat 配了 token（%s）' % token_fp(nap_tok))
    elif nap_tok != tok:
        problems.append('token 不一致：NapCat %s / NoneBot（%s）%s（两边都要一样，否则 403）'
                        % (token_fp(nap_tok), where, token_fp(tok)))
    else:
        infos.append('token 一致（%s）' % token_fp(tok))
    if client.get('messagePostFormat') != 'array':
        problems.append('messagePostFormat=%r 必须是 array（string 上报要走 CQ 解析，契约要求 array）'
                        % (client.get('messagePostFormat'),))
    if client.get('reportSelfMessage') is not False:
        problems.append('reportSelfMessage=%r 必须是 false（否则自己的消息也上报，白占额度）'
                        % (client.get('reportSelfMessage'),))
    if client.get('enable') is not True:
        problems.append('ws 客户端没启用（enable=%r）' % (client.get('enable'),))
    infos.append('客户端 %s · url=%s' % (client.get('name') or '?', url))

    webui_path = conf.parent / 'webui.json'
    webui = read_json(webui_path)
    if isinstance(webui, dict):
        if webui.get('host') != '127.0.0.1':
            problems.append('webui.json host=%r 不是 127.0.0.1（把面板暴露出去了，改成回环）'
                            % (webui.get('host'),))
        infos.append('WebUI %s:%s' % (webui.get('host'), webui.get('port')))
    else:
        infos.append('没读到 %s（可选）' % webui_path)

    if problems:
        raise AssertionError('；'.join(problems))
    return '%s · %s' % (conf, ' · '.join(infos))


# --------------------------------------------------------------- 11. venv 与依赖
def check_venv():
    venv = VENV_DEFAULT
    py = venv / 'bin' / 'python'
    if not py.exists():
        need_install('QQ 专用 venv 不存在（%s）' % venv)
    done = subprocess.run([str(py), '-c', 'import nonebot, nonebot.adapters.onebot.v11'],
                          capture_output=True, text=True, timeout=120)
    if done.returncode != 0:
        raise AssertionError('venv 里 import nonebot/onebot 适配器失败：%s'
                             % (done.stderr.strip().splitlines()[-1:] or ['?'])[0][:200])
    ver = subprocess.run([str(py), '-V'], capture_output=True, text=True, timeout=30).stdout.strip()
    return '%s · %s' % (py, ver)


# ------------------------------------------------------------------------ 主流程
def main():
    global ARGS
    ap = argparse.ArgumentParser(description='QQ 侧离线验收（一张表 + 退出码）')
    ap.add_argument('--config', help='qq.json 路径（默认 ~/.config/qq-bot/qq.json）')
    ap.add_argument('--env-file', help='qq.env 路径（默认 ~/.config/qq-bot/qq.env）')
    ap.add_argument('--no-tests', action='store_true', help='跳过 unittest（快跑）')
    ap.add_argument('--allow-uninstalled', action='store_true',
                    help='本机还没安装：配置/状态目录/venv 缺失记 SKIP 而不是 FAIL')
    ap.add_argument('--json', action='store_true', help='输出 JSON 结果而不是表格')
    ARGS = ap.parse_args()

    check('部署物·systemd 单元', check_units)
    check('部署物·install-qq.sh 安全', check_install_script)
    check('部署物·文档与入口', check_docs)
    check('代码齐备性·契约文件', check_files)
    check('离线单测·test_qq_*', check_tests)
    check('配置 schema·qq.json', check_schema)
    check('启动自检·qq.bot --check', check_startup_gate)
    check('STOP 语义·不发送', check_stop)
    check('状态目录·权限 700', check_state_dir)
    check('NapCat⇄NoneBot 一致性', check_napcat)
    check('venv 与依赖·nonebot', check_venv)

    fails = [r for r in RESULTS if r[0] == 'FAIL']
    if ARGS.json:
        print(json.dumps({'results': [{'status': s, 'name': n, 'detail': d} for s, n, d in RESULTS],
                          'ok': not fails}, ensure_ascii=False, indent=2))
    else:
        width = max(len(n) for _, n, _ in RESULTS)
        print('')
        print('QQ 侧离线验收（不连真实 QQ/微信，不碰生产库）')
        print('=' * 96)
        for status, name, detail in RESULTS:
            mark = {'PASS': 'PASS', 'FAIL': 'FAIL', 'SKIP': 'SKIP'}[status]
            print('[%s] %-*s %s' % (mark, width, name, detail))
        print('=' * 96)
        print('合计 %d 项：PASS %d · FAIL %d · SKIP %d'
              % (len(RESULTS), len(RESULTS) - len(fails) - sum(1 for r in RESULTS if r[0] == 'SKIP'),
                 len(fails), sum(1 for r in RESULTS if r[0] == 'SKIP')))
        if fails:
            print('结论：还不能上线。上面 FAIL 的每一项都要先解决。')
        else:
            print('结论：离线闸门全过（SKIP 的项在真机安装后必须复核）。')
    return 1 if fails else 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(130)
