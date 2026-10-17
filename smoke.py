"""一键自检：服务/配置/模块/额度/测试，一眼看全貌。用法：python3 smoke.py"""
import json, subprocess, sys
from pathlib import Path

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT/'src'))


def sh(cmd):
    r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=60)
    return r.stdout.strip()


def in_wsl():
    try:
        v = Path('/proc/version').read_text().lower()
        return 'microsoft' in v or 'wsl' in v
    except Exception:
        return False


def wsl(cmd):
    """在 WSL 里就直接跑；在 Windows/Git Bash 里才套 wsl -d。"""
    return cmd if in_wsl() else 'wsl -d Ubuntu-24.04 -- ' + cmd


def main():
    print('=== wechat-bot 一键自检 ===')
    cfg = json.loads((ROOT/'config'/'resident.json').read_text())
    print('[配置] 目标: %s | 监控: %s | 群白名单: %s' % (
        cfg['target_chat'], cfg.get('watch_chats') or '(仅目标)', cfg.get('group_whitelist') or '(空)'))
    print('[配置] automation=%s moments=%s interact=%s | 额度=%s' % (
        cfg['automation']['enabled'], cfg['moments']['enabled'], cfg['interact']['enabled'], cfg['limits']))
    wl = cfg.get('group_whitelist', []) or []
    missing = [c for c in (cfg.get('watch_chats') or [])
               if c != cfg['target_chat'] and c not in wl]
    if missing:
        print('[警告] 监控群不在 group_whitelist，不会被观察: %s' % missing)
    for svc in ('wechat-stack', 'wechat-bot'):
        st = sh(wsl('systemctl --user is-active ' + svc))
        print('[服务] %s: %s' % (svc, st or '查询失败'))
    win = sh(wsl('env DISPLAY=:99 xwininfo -root -tree | grep Weixin | head -1'))
    print('[微信] %s' % (win or '无窗口'))
    print('[noVNC] %s' % sh('curl -s -o /dev/null -w "HTTP %{http_code}" --max-time 5 http://localhost:6080/vnc.html'))
    print('[状态] %s' % sh(wsl('python3 /mnt/d/AgentPrograms/wechat-bot/check_status.py')))
    print('[暂停] %s' % sh(wsl('test -f ~/.local/state/wechat-bot/STOP && echo 软暂停中 || echo 无')))
    if in_wsl():
        import sqlite3, time
        db = sqlite3.connect(str(Path.home()/'.local'/'state'/'wechat-bot'/'ledger.sqlite'))
        draft = db.execute("SELECT count(*) FROM moments WHERE state='DRAFT'").fetchone()[0]
        ready = db.execute("SELECT count(*) FROM moment_inbox WHERE state='READY'").fetchone()[0]
        used = db.execute('SELECT count(*) FROM usage WHERE created>?', (time.time()-5*3600,)).fetchone()[0]
        print('[待办] 朋友圈草稿 %d 条 | 互动待确认 %d 条 | 5h额度已用 %d/6000' % (draft, ready, used))
    else:
        print('[待办] 在 WSL 内运行 smoke.py 可查看草稿/互动/额度明细')
    print('=== 自检结束 ===')


if __name__ == '__main__':
    main()
