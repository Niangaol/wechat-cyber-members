"""qq-deploy 侧的离线自测：部署脚本、体检脚本、验收脚本本身都得能自证。

覆盖（全部离线：不连 QQ/微信、不出网、不读生产库）：
  - systemd 单元静态契约（ExecStart 走 QQ 专用 venv、EnvironmentFile、Restart=always、
    无 DISPLAY、不依赖微信服务）
  - install-qq.sh 语法与安全边界（不 sudo、不启停服务、不碰微信单元）
  - qq-health.py：一行 JSON 且字段齐全；STOP/心跳/WS 判断按预期
  - qq-acceptance.py：schema 闸门真的会拦下"空 token""缺 groups"，好配置能过

跑法：cd /mnt/d/AgentPrograms/wechat-bot && python3 -m unittest test_qq_deploy -v
"""
import importlib.util
import json
import os
import re
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent
WSL_DIR = ROOT / 'wsl'
BOT_UNIT = WSL_DIR / 'qq-bot.service'
NAP_UNIT = WSL_DIR / 'qq-napcat.service'
INSTALL_SH = WSL_DIR / 'install-qq.sh'
HEALTH_PY = WSL_DIR / 'qq-health.py'
ACCEPT_PY = WSL_DIR / 'qq-acceptance.py'


def unit_lines(path):
    """systemd 眼里算数的行：去掉注释与空行。"""
    out = []
    for line in Path(path).read_text(encoding='utf-8').splitlines():
        s = line.strip()
        if s and not s.startswith('#') and not s.startswith(';'):
            out.append(s)
    return out


def clean_env(**extra):
    """清掉 QQ_BOT_* 泄漏，避免测试误读开发机上的真实配置/token。"""
    env = {k: v for k, v in os.environ.items()
           if not k.startswith('QQ_BOT_')}
    env.update(extra)
    return env


def free_port_env(port):
    return clean_env(QQ_BOT_STATE_DIR='', QQ_BOT_PORT=str(port))


class UnitFilesTest(unittest.TestCase):
    """systemd 单元是运维合同：写在文件里，就别在半夜被人改坏。"""

    def test_both_units_exist(self):
        self.assertTrue(BOT_UNIT.exists(), BOT_UNIT)
        self.assertTrue(NAP_UNIT.exists(), NAP_UNIT)

    def test_bot_unit_execstart_uses_qq_venv(self):
        lines = unit_lines(BOT_UNIT)
        execs = [l for l in lines if l.startswith('ExecStart=')]
        self.assertEqual(len(execs), 1, execs)
        ex = execs[0]
        self.assertIn('/venv/bin/python', ex, ex)
        self.assertIn('-m qq.bot', ex, ex)
        self.assertIn('WorkingDirectory=/mnt/d/AgentPrograms/wechat-bot', lines)

    def test_bot_unit_env_file_and_restart(self):
        lines = unit_lines(BOT_UNIT)
        self.assertTrue(any(l.startswith('EnvironmentFile=') and 'qq.env' in l for l in lines), lines)
        self.assertIn('Restart=always', lines)

    def test_bot_unit_has_no_display(self):
        """QQ 链路走网络协议，不需要 X；更不能误连微信的 :99。"""
        lines = unit_lines(BOT_UNIT)
        for l in lines:
            self.assertFalse(re.match(r'^Environment\s*=.*\bDISPLAY=', l), l)
        self.assertTrue(any(l.startswith('UnsetEnvironment=') and 'DISPLAY' in l for l in lines), lines)

    def test_units_never_depend_on_wechat(self):
        """停 QQ 不许碰微信，重启微信栈也不许带起/带停 QQ。"""
        for unit in (BOT_UNIT, NAP_UNIT):
            for l in unit_lines(unit):
                m = re.match(r'^(PartOf|BindsTo|Requires|Wants|After|Before)\s*=\s*(.+)$', l)
                if m:
                    self.assertNotIn('wechat', m.group(2), '%s: %s' % (unit.name, l))

    def test_napcat_unit_paths_agree(self):
        lines = unit_lines(NAP_UNIT)
        cond = [l for l in lines if l.startswith('ConditionPathExists=')]
        execs = [l for l in lines if l.startswith('ExecStart=')]
        self.assertEqual(len(cond), 1, cond)
        self.assertEqual(len(execs), 1, execs)
        target = cond[0].split('=', 1)[1].strip()
        self.assertTrue(execs[0].endswith('--no-sandbox $QQ_BOT_QQ_ARGS'), execs[0])
        self.assertIn(target.rsplit('/qq', 1)[0], execs[0], '%s vs %s' % (target, execs[0]))


class InstallScriptTest(unittest.TestCase):
    """安装脚本的安全边界：不 sudo、不启停服务、不碰微信。"""

    def test_syntax(self):
        done = subprocess.run(['bash', '-n', str(INSTALL_SH)], capture_output=True, text=True, timeout=60)
        self.assertEqual(done.returncode, 0, done.stderr)

    def test_no_sudo_execution(self):
        src = INSTALL_SH.read_text(encoding='utf-8')
        hits = re.findall(r'(?m)^\s*sudo\b.*$', src)
        self.assertEqual(hits, [], '安装脚本不该直接执行 sudo：%s' % hits)

    def test_no_service_start_or_enable(self):
        src = INSTALL_SH.read_text(encoding='utf-8')
        hits = re.findall(r'(?m)^\s*systemctl\s+--user\s+(start|stop|restart|enable|disable|kill|reload)\b.*$', src)
        self.assertEqual(hits, [], '安装脚本不该启停/开关服务：%s' % hits)

    def test_never_touches_wechat_units(self):
        src = INSTALL_SH.read_text(encoding='utf-8')
        self.assertIsNone(re.search(r'systemctl[^\n]*wechat', src))
        self.assertIsNone(re.search(r'wechat-(bot|stack|soak)\.service', src))

    def test_dry_run_makes_no_files(self):
        """dry-run 必须真的不落盘：拿假 HOME 跑一遍，然后确认目录没被创建。"""
        with tempfile.TemporaryDirectory() as tmp:
            env = clean_env(HOME=tmp)
            done = subprocess.run(['bash', str(INSTALL_SH), '--dry-run'], cwd=str(ROOT),
                                  capture_output=True, text=True, timeout=120, env=env)
            self.assertEqual(done.returncode, 0, done.stderr)
            self.assertIn('[dry-run]', done.stdout)
            self.assertFalse((Path(tmp) / '.config' / 'qq-bot').exists(), 'dry-run 竟然建了目录')
            self.assertFalse((Path(tmp) / '.local' / 'state' / 'qq-bot').exists(), 'dry-run 竟然建了状态目录')


def load_health_module():
    """把 wsl/qq-health.py 当模块加载，直接测它自己的端口探测（而不是测一份复刻的解析逻辑）。"""
    spec = importlib.util.spec_from_file_location('qq_health_under_test', HEALTH_PY)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class PortProbeTest(unittest.TestCase):
    """端口探测回归：2026-10-18 真机上 ws_listen 恒为 false 的坑。

    根因是 ss 的参数：'-t' 不列 LISTEN，'-l' 又只列 LISTEN。
    所以这里**真起一个 listener、真建一条连接**，两个信号都必须看得见——
    只测解析函数是抓不到这个 bug 的（这正是当初漏掉它的原因）。
    """

    def test_probe_sees_listening_socket(self):
        mod = load_health_module()
        with socket.socket() as srv:
            srv.bind(('127.0.0.1', 0))
            srv.listen(1)
            port = srv.getsockname()[1]
            info = mod.probe_port(port)
        self.assertTrue(info['listen'], '探测不到 LISTEN（ss 参数是不是又漏了 -a？）：%r' % info)

    def test_probe_sees_established_connection(self):
        mod = load_health_module()
        with socket.socket() as srv:
            srv.bind(('127.0.0.1', 0))
            srv.listen(1)
            port = srv.getsockname()[1]
            with socket.create_connection(('127.0.0.1', port)) as cli:
                with srv.accept()[0] as conn:
                    info = mod.probe_port(port)
                    self.assertTrue(info['listen'], 'ESTAB 用例里 LISTEN 丢了：%r' % info)
                    self.assertGreaterEqual(info['estab'], 1,
                                            '探测不到 ESTAB（只加 -l 就会这样）：%r' % info)
                    self.assertTrue(info['peers'], 'ESTAB 存在却没有对端信息：%r' % info)
                cli.close()
        self.assertIn(info['source'], ('ss', 'proc'))

    def test_proc_fallback_also_sees_listen(self):
        """ss 不可用时要走 /proc/net/tcp（只有 st=0A 才是 LISTEN）——兜底路径也得认得出监听。"""
        mod = load_health_module()
        original = mod.run

        def fake_run(cmd, timeout=10):
            if cmd and cmd[0] == 'ss':
                return None, ''                    # 模拟"系统里没有 ss"
            return original(cmd, timeout)

        mod.run = fake_run
        try:
            with socket.socket() as srv:
                srv.bind(('127.0.0.1', 0))
                srv.listen(1)
                port = srv.getsockname()[1]
                info = mod.probe_port(port)
        finally:
            mod.run = original
        self.assertEqual(info['source'], 'proc', '没有回退到 /proc 路径：%r' % info)
        self.assertTrue(info['listen'], '兜底路径认不出 LISTEN：%r' % info)

    def test_probe_reports_nothing_for_idle_port(self):
        """空端口不能误报——否则体检会给出假的"连上了"。"""
        mod = load_health_module()
        with socket.socket() as s:
            s.bind(('127.0.0.1', 0))
            free = s.getsockname()[1]          # 绑完立刻关：这个端口现在没人用
        info = mod.probe_port(free)
        self.assertFalse(info['listen'], '%r' % info)
        self.assertEqual(info['estab'], 0, '%r' % info)


class HealthScriptTest(unittest.TestCase):
    """qq-health.py：一行 JSON，且"活着但没连上"必须 ok:false。"""

    port = 18099

    def run_health(self, state_dir, extra_env=None):
        env = clean_env(QQ_BOT_STATE_DIR=str(state_dir), QQ_BOT_PORT=str(self.port))
        env.update(extra_env or {})
        cfg = Path(state_dir) / 'health-test-qq.json'
        cfg.write_text(json.dumps({'onebot': {'port': self.port}}, ensure_ascii=False), encoding='utf-8')
        env['QQ_BOT_CONFIG'] = str(cfg)
        done = subprocess.run([sys.executable, str(HEALTH_PY)], cwd=str(ROOT),
                              capture_output=True, text=True, timeout=120, env=env)
        lines = [l for l in done.stdout.splitlines() if l.strip()]
        self.assertEqual(len(lines), 1, '健康检查必须是一行 JSON，实际 %d 行' % len(lines))
        return json.loads(lines[0]), done.returncode

    def test_one_line_json_with_required_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            out, rc = self.run_health(tmp)
        for field in ('unit', 'unit_active', 'process_running', 'heartbeat_age_s', 'heartbeat_ok',
                      'online', 'ws_connected', 'last_event_at', 'last_send_ok_at', 'queue_depth',
                      'stop', 'ok', 'reasons'):
            self.assertIn(field, out)
        self.assertFalse(out['ok'], '空状态目录不可能健康')
        self.assertTrue(out['reasons'], 'ok:false 必须说明原因')
        self.assertNotEqual(rc, 0)

    def test_stop_file_is_reported_and_blocks_ok(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp)
            (state / 'STOP').write_text('测试\n', encoding='utf-8')
            (state / 'status.json').write_text(json.dumps({
                'state': 'running', 'heartbeat': time.time(), 'queue_depth': 0,
                'online': True, 'last_event_at': time.time(), 'last_send_ok_at': time.time(),
            }), encoding='utf-8')
            out, _ = self.run_health(state)
        self.assertTrue(out['stop'])
        self.assertTrue(out['stop_file'])
        self.assertTrue(out['heartbeat_ok'], '刚写的心跳不该被判为过期')
        self.assertFalse(out['ok'], 'STOP 在位不许 ok:true')
        self.assertTrue(any('急停' in r for r in out['reasons']), out['reasons'])

    def test_not_connected_is_not_healthy(self):
        """活着、心跳新鲜、QQ 在线，但 WS 没连上 → 仍然 ok:false（这是最容易骗过人的组合）。"""
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp)
            (state / 'status.json').write_text(json.dumps({
                'state': 'running', 'heartbeat': time.time(), 'queue_depth': 3,
                'online': True, 'last_event_at': time.time(), 'last_send_ok_at': time.time(),
            }), encoding='utf-8')
            out, _ = self.run_health(state)
        self.assertFalse(out['ws_connected'])
        self.assertFalse(out['ok'])
        self.assertTrue(any('反向 WS' in r or 'ESTAB' in r for r in out['reasons']), out['reasons'])


class AcceptanceScriptTest(unittest.TestCase):
    """qq-acceptance.py 自己也要被验：闸门必须真的拦得住。"""

    def good_config(self, state_dir, token_in_env=True):
        return {
            'state_dir': str(state_dir), 'auto_send': False,
            'onebot': {'host': '127.0.0.1', 'port': 18099, 'path': '/onebot/v11/ws',
                       'token': '' if token_in_env else 'x' * 24,
                       'token_env': 'QQ_BOT_ONEBOT_TOKEN'},
            'napcat': {'webui_host': '127.0.0.1', 'webui_port': 6099},
            'direct_policy': 'blacklist', 'group_policy': 'whitelist',
            'groups': {'123456789': {'plain_mode': 'at_only', 'plain_cooldown_s': 120,
                                     'plain_per_hour': 6, 'followup_window_s': 60}},
            'mention_aliases': ['年糕'], 'limits': {'window_5h': 100, 'window_1d': 500},
            'reply_max_chars': 200,
        }

    def run_acceptance(self, cfg, env_file, extra=()):
        with tempfile.TemporaryDirectory() as tmp:
            cfg_path = Path(tmp) / 'qq.json'
            cfg_path.write_text(json.dumps(cfg, ensure_ascii=False), encoding='utf-8')
            cmd = [sys.executable, str(ACCEPT_PY), '--config', str(cfg_path),
                   '--env-file', str(env_file), '--no-tests', '--json'] + list(extra)
            done = subprocess.run(cmd, cwd=str(ROOT), capture_output=True, text=True,
                                  timeout=300, env=clean_env())
            self.assertTrue(done.stdout.strip(), 'acceptance 没有输出：%s' % done.stderr[-300:])
            data = json.loads(done.stdout)
            return {r['name']: r for r in data['results']}, data, done.returncode

    def make_env_file(self, tmp, token=''):
        path = Path(tmp) / 'qq.env'
        body = 'QQ_BOT_PORT=18099\nQQ_BOT_CONFIG=/tmp/qq.json\n'
        if token:
            body += 'QQ_BOT_ONEBOT_TOKEN=%s\n' % token
        path.write_text(body, encoding='utf-8')
        return path

    def test_empty_token_fails_schema(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp) / 'state'
            state.mkdir(mode=0o700)
            rows, data, rc = self.run_acceptance(self.good_config(state), self.make_env_file(tmp))
        row = rows['配置 schema·qq.json']
        self.assertEqual(row['status'], 'FAIL', row)
        self.assertIn('token', row['detail'])
        self.assertNotEqual(rc, 0)

    def test_missing_groups_fails_schema(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp) / 'state'
            state.mkdir(mode=0o700)
            cfg = self.good_config(state)
            cfg.pop('groups')
            rows, data, rc = self.run_acceptance(cfg, self.make_env_file(tmp, token='t' * 32))
        row = rows['配置 schema·qq.json']
        self.assertEqual(row['status'], 'FAIL', row)
        self.assertIn('groups', row['detail'])

    def test_bad_plain_mode_fails_schema(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp) / 'state'
            state.mkdir(mode=0o700)
            cfg = self.good_config(state)
            cfg['groups']['123456789']['plain_mode'] = 'whatever'
            rows, _, _ = self.run_acceptance(cfg, self.make_env_file(tmp, token='t' * 32))
        row = rows['配置 schema·qq.json']
        self.assertEqual(row['status'], 'FAIL', row)
        self.assertIn('plain_mode', row['detail'])

    def test_good_config_passes_schema(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp) / 'state'
            state.mkdir(mode=0o700)
            rows, _, _ = self.run_acceptance(self.good_config(state), self.make_env_file(tmp, token='t' * 32))
        row = rows['配置 schema·qq.json']
        self.assertEqual(row['status'], 'PASS', row)

    def test_non_loopback_webui_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp) / 'state'
            state.mkdir(mode=0o700)
            cfg = self.good_config(state)
            cfg['napcat']['webui_host'] = '0.0.0.0'
            rows, _, _ = self.run_acceptance(cfg, self.make_env_file(tmp, token='t' * 32))
        row = rows['配置 schema·qq.json']
        self.assertEqual(row['status'], 'FAIL', row)
        self.assertIn('127.0.0.1', row['detail'])

    def test_state_dir_permission_is_checked(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp) / 'state'
            state.mkdir(mode=0o755)
            os.chmod(state, 0o755)
            rows, _, _ = self.run_acceptance(self.good_config(state), self.make_env_file(tmp, token='t' * 32))
        row = rows['状态目录·权限 700']
        self.assertEqual(row['status'], 'FAIL', row)
        self.assertIn('700', row['detail'])

    def test_acceptance_never_touches_wechat_unit(self):
        """静态兜底：验收脚本里不许出现微信单元名（防止以后有人手滑加进去）。"""
        src = ACCEPT_PY.read_text(encoding='utf-8')
        self.assertIsNone(re.search(r'systemctl[^\n]*wechat-(bot|stack|soak)', src))
        self.assertNotIn('wsl/acceptance.py', src)


class DocsTest(unittest.TestCase):
    """部署手册与入口：README 得链得到，手册得写全关键步骤。"""

    def test_docs_qq_exists_with_key_sections(self):
        doc = ROOT / 'docs' / 'QQ.md'
        self.assertTrue(doc.exists(), '缺 docs/QQ.md')
        text = doc.read_text(encoding='utf-8')
        for kw in ('NapCat', '18080', '反向 WS', '回滚', '风控', '6099', '127.0.0.1', 'STOP'):
            self.assertIn(kw, text, 'docs/QQ.md 缺关键内容：%s' % kw)

    def test_readme_links_docs(self):
        text = (ROOT / 'README.md').read_text(encoding='utf-8')
        self.assertIn('docs/QQ.md', text)
        self.assertIn('NapCat', text)
        self.assertIn('微信链路', text)


if __name__ == '__main__':
    unittest.main(verbosity=2)
