"""一键健康检查：常驻机器人到底活着没有（给人看，也给 Windows watchdog 用）。

输出一行 JSON，exit 0 = 健康。判据（全部 fail-closed）：
  两个 systemd 服务 active、心跳 <90s、没有 STOP、微信在主窗（不是登录窗）。
"""
import json
import os
import sqlite3
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'src')]
STATE = Path.home() / '.local' / 'state' / 'wechat-bot'


def configured_display():
    """看哪个屏以配置为准，别信环境变量。

    WSL 里 DISPLAY 默认常常是 :0（WSLg），而微信跑在 :99。照抄环境会得到
    假的"没窗口 → ok:false"，今晚已经踩过一次（烤机第一版就是这么误报的）。
    """
    try:
        cfg = json.loads((ROOT / 'config' / 'resident.json').read_text())
        return cfg.get('display') or ':99'
    except Exception:                              # noqa: BLE001
        return ':99'


DISPLAY = os.environ.get('SOAK_DISPLAY') or configured_display()


def probe_wechat():
    try:
        from screen import list_x_windows
        wins = [w for w in list_x_windows(DISPLAY) if w.get('title') == 'Weixin']
    except Exception as exc:                       # noqa: BLE001
        return 'probe-failed:%s' % type(exc).__name__
    if len(wins) != 1:
        return 'no-window(%d)' % len(wins)
    w = wins[0]
    if w['w'] < 600 or w['h'] < 600:               # 登录窗实测 292x396
        return 'logged-out %dx%d' % (w['w'], w['h'])
    return 'main %dx%d' % (w['w'], w['h'])


def wechat_rss_mb():
    """微信客户端全家（主进程 + 小程序容器 + OCR）占多少内存。

    小程序容器会一个个堆着不走（实测 5 个 ~820MB），跑几天要能看到趋势，
    所以只报数、不参与健康判定（内存高不是"不健康"，是"该看一眼"）。
    """
    try:
        import subprocess
        done = subprocess.run(['ps', '-eo', 'rss,comm'], capture_output=True,
                              text=True, timeout=10)
        total = 0
        for line in done.stdout.splitlines()[1:]:
            parts = line.split(None, 1)
            if len(parts) != 2:
                continue
            if parts[1].strip().lower() in ('wechat', 'wechatappex', 'wxocr'):
                total += int(parts[0])
        return round(total / 1024.0, 1) if total else None
    except Exception:                              # noqa: BLE001
        return None


def health_ok(out):
    """健康判据（fail-closed）。

    坑：心跳刚写完时 heartbeat_age_s 正好是 0.0，而 0.0 在 Python 里是假值——
    用 `(age or 9e9) < 90` 这种写法会把"刚刚心跳过"误判成"不健康"
    （2026-10-17 烤机里抓到过一次假警报），所以这里显式判 None。
    """
    age = out.get('heartbeat_age_s')
    # "活着但瞎了"：心跳正常、进程在跑，可是上一轮一个会话都没看成
    # （窗口被浮层盖住/卡在别的页面）。这种状态以前 health 会说 ok:true ✗，
    # 结果是"看起来健康、实际一条都不回"，只能靠人发现。
    observed, configured = out.get('observed_chats'), out.get('configured_chats')
    blind = isinstance(configured, int) and configured > 0 and observed == 0
    return bool(out.get('wechat-bot') == 'active'
                and out.get('wechat-stack') == 'active'
                and isinstance(age, (int, float)) and age < 90
                and not out.get('stop_file')
                and not blind
                and str(out.get('wechat', '')).startswith('main'))


def main():
    out = {'at': time.strftime('%Y-%m-%d %H:%M:%S'), 'display': DISPLAY}
    for unit in ('wechat-stack', 'wechat-bot'):
        try:
            import subprocess
            done = subprocess.run(['systemctl', '--user', 'is-active', unit],
                                  capture_output=True, text=True, timeout=10)
            out[unit] = done.stdout.strip() or 'unknown'
        except Exception as exc:                   # noqa: BLE001
            out[unit] = 'error:%s' % type(exc).__name__

    out['stop_file'] = (STATE / 'STOP').exists()
    try:
        st = json.loads((STATE / 'status.json').read_text())
    except Exception:                              # noqa: BLE001
        st = {}
    out['state'] = st.get('state')
    out['heartbeat_age_s'] = round(time.time() - st.get('heartbeat', 0), 1) if st else None
    out['queue_depth'] = st.get('queue_depth')
    # 模型侧状态（认证失败/熔断）：正式上线后这是"能不能回话"的关键信息
    model = st.get('model') or {}
    if model:
        out['model'] = {'provider': model.get('provider'), 'model': model.get('model'),
                        'key_present': model.get('key_present'),
                        'circuit_open': model.get('circuit_open'),
                        'disabled': model.get('disabled'),
                        'last_error': model.get('last_error')}
    ph = st.get('poll_health') or {}
    out['chats_observed'] = '%s/%s' % (ph.get('observed'), ph.get('configured'))
    out['observed_chats'] = ph.get('observed')
    out['configured_chats'] = ph.get('configured')

    try:
        db = sqlite3.connect(str(STATE / 'ledger.sqlite'))
        row = db.execute("SELECT created FROM turns WHERE role='assistant'"
                         " ORDER BY id DESC LIMIT 1").fetchone()
        out['last_reply_age_s'] = round(time.time() - row[0]) if row else None
        # 队列里最老那条待处理消息等了多久：堆积时最该看的数
        row = db.execute("SELECT min(created) FROM queue WHERE state='PENDING'").fetchone()
        out['queue_oldest_age_s'] = (round(time.time() - row[0]) if row and row[0] else None)
        # 最近一次真正投递出去的消息：区分"没消息可回"和"回不出去"
        row = db.execute("SELECT max(created) FROM deliveries").fetchone()
        out['last_delivery_age_s'] = (round(time.time() - row[0]) if row and row[0] else None)
        db.close()
    except Exception as exc:                       # noqa: BLE001
        out['last_reply_age_s'] = 'error:%s' % type(exc).__name__

    try:
        db = sqlite3.connect(str(STATE / 'ledger.sqlite'))
        row = db.execute("SELECT count(*), min(created) FROM moments WHERE state='DRAFT'"
                         ).fetchone()
        out['moment_drafts_pending'] = row[0] or 0
        # 草稿躺着没人审会**静默卡住整个朋友圈节奏**（有 DRAFT 就不再提新草稿）。
        # 这里只报"最老那条躺了几天"，不下手删——发布是人审环节，不能自动替他决定。
        out['moment_draft_age_days'] = (round((time.time() - row[1]) / 86400.0, 1)
                                        if row[0] and row[1] else None)
        db.close()
    except Exception as exc:                       # noqa: BLE001
        out['moment_drafts_pending'] = 'error:%s' % type(exc).__name__
    out['wechat'] = probe_wechat()
    out['wechat_rss_mb'] = wechat_rss_mb()
    out['ok'] = health_ok(out)
    print(json.dumps(out, ensure_ascii=False))
    return 0 if out['ok'] else 1


if __name__ == '__main__':
    sys.exit(main())
