#!/usr/bin/env python3
"""QQ 机器人一键体检：输出一行 JSON，exit 0 = 健康，exit 1 = 不健康。

判据（全部 fail-closed，「活着但没连上 / 没登录」一律 ok:false 并写明原因）：
  1. unit    —— systemd 用户单元 qq-bot 是 active
  2. process —— 进程真的在（服务 active 但进程已死、或手工前台跑，都要能看出来）
  3. heartbeat —— 状态目录里的 status.json 心跳新鲜（默认 <90s）
  4. stop    —— 没有 STOP 急停文件（有 STOP 就是"故意停手"，不算健康）
  5. online  —— 状态里 online 为真（QQ 已登录且适配器在线）
  6. ws      —— 反向 WS 真的连上了：18080 端口既在 LISTEN、又存在 ESTAB 连接（NapCat → NoneBot）
                （探测用 'ss -Htan'：-t 会漏掉 LISTEN，-l 又只剩 LISTEN，见 probe_port_ss 注释）

每项都是独立字段，方便看日志的人一眼分辨"没起来 / 起来了没登录 / 登录了没连上"。

用法：
    python3 wsl/qq-health.py             # 一行 JSON
    python3 wsl/qq-health.py --pretty    # 缩进多行（人看）
环境变量：
    QQ_BOT_CONFIG     覆盖 qq.json 路径（默认 ~/.config/qq-bot/qq.json）
    QQ_BOT_STATE_DIR  覆盖状态目录（默认取 qq.json 的 state_dir，再默认 ~/.local/state/qq-bot）

只读：本脚本不改任何文件、不碰微信、不连外网（ss/pgrep/systemctl 都是本地查询）。
"""
import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

DEFAULT_CONFIG = Path.home() / '.config' / 'qq-bot' / 'qq.json'
DEFAULT_STATE = Path.home() / '.local' / 'state' / 'qq-bot'
DEFAULT_PORT = 18080
HEARTBEAT_MAX_S = 90.0
UNIT = 'qq-bot'


def run(cmd, timeout=10):
    """跑一条只读命令，任何异常都吞掉返回 (None, '')，体检脚本自己不能崩。"""
    try:
        done = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except Exception:                                  # noqa: BLE001
        return None, ''
    return done.returncode, (done.stdout or '') + (done.stderr or '')


def read_json(path):
    try:
        return json.loads(Path(path).read_text(encoding='utf-8'))
    except Exception:                                  # noqa: BLE001
        return None


def load_cfg():
    """读 qq.json 拿端口与状态目录。读不到就用默认值，不因此判不健康（下面 WS 那项会说话）。"""
    cfg_path = Path(os.environ.get('QQ_BOT_CONFIG') or DEFAULT_CONFIG).expanduser()
    cfg = read_json(cfg_path) or {}
    onebot = cfg.get('onebot') if isinstance(cfg.get('onebot'), dict) else {}
    port = onebot.get('port') if isinstance(onebot.get('port'), int) else DEFAULT_PORT
    state = os.environ.get('QQ_BOT_STATE_DIR') or cfg.get('state_dir') or str(DEFAULT_STATE)
    try:
        state_dir = Path(state).expanduser()
    except Exception:                                  # noqa: BLE001
        state_dir = DEFAULT_STATE
    return {'config_path': str(cfg_path), 'port': port, 'state_dir': state_dir}


def unit_state(unit):
    code, out = run(['systemctl', '--user', 'is-active', unit])
    text = out.strip().splitlines()
    return text[0] if text else 'unknown'


def find_bots():
    """找 qq.bot 进程。用 qq[.]bot 避免 . 被当通配符，顺带避开 pgrep 自己。"""
    code, out = run(['pgrep', '-af', r'qq[.]bot'])
    pids, cmds = [], []
    for line in out.splitlines():
        parts = line.split(None, 1)
        if len(parts) == 2 and parts[0].isdigit():
            pids.append(int(parts[0]))
            cmds.append(parts[1].strip())
    return pids, cmds


def napcat_alive():
    code, out = run(['pgrep', '-af', r'/opt/QQ/qq|napcat'])
    lines = [ln for ln in out.splitlines() if ln.strip() and 'pgrep' not in ln]
    return bool(lines), lines[:2]


def _port_from_addr(addr):
    """'127.0.0.1:18080' / '[::1]:18080' → 18080（拿不到返回 None）。"""
    try:
        return int(addr.rsplit(':', 1)[1])
    except Exception:                                  # noqa: BLE001
        return None


def probe_port_ss(port):
    """用 ss 看端口：既要 LISTEN（NoneBot 在听）也要 ESTAB（NapCat 连上了）。

    2026-10-18 踩坑记录（lead 在真机抓到的）：
      * 'ss -Htn'  不显示 LISTEN 套接字（-t 默认省略 listening）→ 明明在听却报 ws_listen=false；
      * 'ss -Htln' 只显示 listening，ESTAB 又全没了（-l 是"只看监听"）→ 假阴性换个方向而已；
      * 'ss -Htan' 两个都有（-a = 监听 + 非监听），再按状态列过滤，才是对的。
    三种写法实测对照（同一时刻、同一条 ESTAB 连接）：
      -Htn  LISTEN=0 ESTAB=2 · -Htln LISTEN=1 ESTAB=0 · -Htan LISTEN=1 ESTAB=2
    """
    code, out = run(['ss', '-Htan'])
    if code is None:
        return None
    listen, estab, peers = False, 0, []
    for line in out.splitlines():
        cols = line.split()
        if len(cols) < 5:
            continue
        state, local, peer = cols[0], cols[3], cols[4]
        lp, rp = _port_from_addr(local), _port_from_addr(peer)
        if state == 'LISTEN' and lp == port:
            listen = True
        elif state == 'ESTAB' and (lp == port or rp == port):
            estab += 1
            other = peer if lp == port else local
            if len(peers) < 3:
                peers.append(other)
    return {'listen': listen, 'estab': estab, 'peers': peers, 'source': 'ss'}


def probe_port_proc(port):
    """没有 ss 时退回到 /proc/net/tcp（WSL 里 iproute2 一般都在，这里只是兜底）。"""
    hexport = '%04X' % port
    listen, estab, peers = False, 0, []
    for name in ('/proc/net/tcp', '/proc/net/tcp6'):
        try:
            lines = Path(name).read_text().splitlines()[1:]
        except Exception:                              # noqa: BLE001
            continue
        for line in lines:
            cols = line.split()
            if len(cols) < 4:
                continue
            local, peer, st = cols[1], cols[2], cols[3]
            lp = local.rsplit(':', 1)[-1].upper()
            rp = peer.rsplit(':', 1)[-1].upper()
            if st == '0A' and lp == hexport:
                listen = True
            elif st == '01' and (lp == hexport or rp == hexport):
                estab += 1
                if len(peers) < 3:
                    peers.append(peer if lp == hexport else local)
    return {'listen': listen, 'estab': estab, 'peers': peers, 'source': 'proc'}


def probe_port(port):
    info = probe_port_ss(port)
    if info is None:
        info = probe_port_proc(port)
    return info


def age_of(ts):
    try:
        ts = float(ts)
    except Exception:                                  # noqa: BLE001
        return None
    if ts <= 0:
        return None
    return round(time.time() - ts, 1)


def main():
    ap = argparse.ArgumentParser(description='QQ 机器人体检（一行 JSON，exit 0=健康）')
    ap.add_argument('--pretty', action='store_true', help='缩进多行输出，方便人看')
    args = ap.parse_args()

    cfg = load_cfg()
    state_dir = cfg['state_dir']
    port = cfg['port']

    out = {'at': time.strftime('%Y-%m-%d %H:%M:%S'), 'state_dir': str(state_dir), 'port': port}
    reasons = []

    # ---- 1. systemd 单元 ----
    out['unit'] = unit_state(UNIT)
    out['unit_active'] = out['unit'] == 'active'
    if not out['unit_active']:
        reasons.append('qq-bot.service 不是 active（当前 %s）' % out['unit'])

    # ---- 2. 进程 ----
    pids, cmds = find_bots()
    out['process_running'] = bool(pids)
    out['pids'] = pids[:5]
    if pids and not out['unit_active']:
        out['process_hint'] = '有 qq.bot 进程但单元不是 active：可能是手工前台在跑'
    if not pids:
        reasons.append('找不到 qq.bot 进程（服务没起来，或起来就崩了）')

    # ---- 3. 心跳（status.json）----
    status = read_json(state_dir / 'status.json') or {}
    out['status_file'] = (state_dir / 'status.json').exists()
    hb_age = age_of(status.get('heartbeat'))
    out['heartbeat_age_s'] = hb_age
    out['heartbeat_ok'] = bool(hb_age is not None and hb_age < HEARTBEAT_MAX_S)
    if not out['status_file']:
        reasons.append('没有 status.json：服务从没成功跑起来过')
    elif not out['heartbeat_ok']:
        reasons.append('心跳不新鲜（%s 秒未更新，阈值 %ds）：进程卡死或没进主循环'
                       % ('从不' if hb_age is None else hb_age, int(HEARTBEAT_MAX_S)))
    out['state'] = status.get('state')

    # ---- 4. 急停 ----
    out['stop'] = bool(status.get('stop')) or (state_dir / 'STOP').exists()
    out['stop_file'] = (state_dir / 'STOP').exists()
    if out['stop']:
        reasons.append('急停生效（%s 存在）：按设计停手不发送' % (state_dir / 'STOP'))

    # ---- 5. QQ 在线 ----
    online = status.get('online')
    out['online'] = bool(online)
    if not online:
        reasons.append('QQ 未在线（status.online=%r）：多半是掉登录或 NapCat 没连上' % (online,))
    out['self_id'] = status.get('self_id') or ''

    # ---- 6. 反向 WS ----
    ws = probe_port(port)
    out['ws_listen'] = bool(ws['listen'])
    out['ws_estab'] = int(ws['estab'])
    out['ws_connected'] = bool(ws['listen'] and ws['estab'] > 0)
    out['ws_peers'] = ws['peers']
    out['ws_probe'] = ws['source']
    nap_alive, nap_cmds = napcat_alive()
    out['napcat_running'] = nap_alive
    if not out['ws_connected']:
        if not ws['listen']:
            reasons.append('端口 %d 没有监听：NoneBot 侧没起来（反向 WS 无人接）' % port)
        else:
            detail = 'NapCat 进程也在' if nap_alive else 'NapCat 进程没找到'
            reasons.append('端口 %d 有监听但没有 ESTAB 连接：NapCat 没连上来（%s）'
                           % (port, detail))
    if nap_cmds:
        out['napcat_cmd'] = nap_cmds[0][:120]

    # ---- 队列 / 最近活动（信息项，不参与判定）----
    out['queue_depth'] = status.get('queue_depth')
    out['sent_1h'] = status.get('sent_1h')
    out['last_event_at'] = status.get('last_event_at') or None
    out['last_event_age_s'] = age_of(status.get('last_event_at'))
    out['last_send_ok_at'] = status.get('last_send_ok_at') or None
    out['last_send_ok_age_s'] = age_of(status.get('last_send_ok_at'))
    out['last_error'] = (status.get('last_error') or '')[:200]

    out['ok'] = not reasons
    out['reasons'] = reasons
    print(json.dumps(out, ensure_ascii=False, indent=2 if args.pretty else None))
    return 0 if out['ok'] else 1


if __name__ == '__main__':
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(130)
