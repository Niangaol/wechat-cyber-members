"""常驻烤机体检：定时采样 health，把异常落到 JSONL。

正式上线后它是**一直跑**的监测（SOAK_DURATION<=0 表示不停），样本按天切文件、
只留最近 SOAK_KEEP_DAYS 天，避免长年累月堆成几个 G。

用法（WSL 内，服务里就是这么起的）：
    SOAK_TAG=resident SOAK_DURATION=0 python3 wsl/soak.py
环境变量：SOAK_INTERVAL（默认 30 秒）、SOAK_DURATION（默认 3600 秒；<=0 = 一直跑）、
          SOAK_TAG（标签）、SOAK_KEEP_DAYS（默认 14 天）
判异常：服务不 active / STOP 出现 / 心跳超过 60 秒没动 / 队列堆积 > 5 /
        会话观察数掉到 0 / 常驻进程内存 > 500MB / 微信客户端内存 > 3GB。
同一天内重启烤机是**追加**写入，不会丢当天之前的窗口。
"""
import glob, json, os, subprocess, sys, time

ROOT = "/mnt/d/AgentPrograms/wechat-bot"
STATE = os.path.expanduser("~/.local/state/wechat-bot")
INTERVAL = int(os.environ.get("SOAK_INTERVAL", 30))
DURATION = int(os.environ.get("SOAK_DURATION", 3600))
TAG = os.environ.get("SOAK_TAG", "soak")
KEEP_DAYS = int(os.environ.get("SOAK_KEEP_DAYS", 14))


def out_path(now=None):
    """按天切文件：长年运行也不会堆成一个巨型文件。"""
    day = time.strftime("%Y%m%d", time.localtime(now))
    return os.path.join(STATE, "soak-%s-%s.jsonl" % (TAG, day))


def prune(now=None):
    """只留最近 KEEP_DAYS 天的样本文件；删不掉就算了，绝不因为清理失败而中断监测。"""
    now = time.time() if now is None else now
    cutoff = now - KEEP_DAYS * 86400
    removed = []
    for path in glob.glob(os.path.join(STATE, "soak-%s-*.jsonl" % TAG)):
        try:
            if os.path.getmtime(path) < cutoff:
                os.remove(path)
                removed.append(os.path.basename(path))
        except OSError:
            pass
    return removed


def resident_rss_kb():
    """常驻进程的内存占用（KB）。跑通宵最该盯的就是它有没有一路涨。"""
    try:
        pid = subprocess.run(["systemctl", "--user", "show", "wechat-bot",
                              "-p", "MainPID", "--value"],
                             capture_output=True, text=True, timeout=10).stdout.strip()
        if not pid or pid == "0":
            return None
        with open("/proc/%s/status" % pid) as fh:
            for line in fh:
                if line.startswith("VmRSS:"):
                    return int(line.split()[1])
    except Exception:                 # noqa: BLE001
        return None
    return None


def sample():
    # 必须盯对虚拟屏：WSL 里 DISPLAY 可能默认是 :0（没有微信窗口），那样全是误报
    env = dict(os.environ, DISPLAY=os.environ.get("SOAK_DISPLAY", ":99"))
    try:
        raw = subprocess.run([sys.executable, "wsl/health.py"], cwd=ROOT, env=env,
                             capture_output=True, text=True, timeout=60)
        health = json.loads(raw.stdout.strip().splitlines()[-1])
    except Exception as exc:                      # noqa: BLE001
        return {"at": time.time(), "sample_error": type(exc).__name__}
    health["rss_kb"] = resident_rss_kb()
    issues = []
    if (health.get("rss_kb") or 0) > 500000:
        issues.append("resident_memory_high")
    # 客户端全家（主进程+小程序容器+OCR）实测会堆：小程序容器关掉窗口后进程还在。
    # 超 3GB 就记一笔——那是"该重启客户端了"的信号，不是立刻出事。
    if (health.get("wechat_rss_mb") or 0) > 3000:
        issues.append("wechat_memory_high")
    if health.get("wechat-stack") != "active":
        issues.append("stack_down")
    if health.get("wechat-bot") != "active":
        issues.append("bot_down")
    if health.get("stop_file"):
        issues.append("stop_file")
    if (health.get("heartbeat_age_s") or 0) > 60:
        issues.append("heartbeat_stale")
    if (health.get("queue_depth") or 0) > 5:
        issues.append("queue_backlog")
    # 用数值字段判，别硬编码 "0/2"：会话数一变（以后加第三个）就会漏判
    if (isinstance(health.get("configured_chats"), int)
            and health["configured_chats"] > 0
            and health.get("observed_chats") == 0):
        issues.append("no_chat_observed")
    if not health.get("ok"):
        issues.append("not_ok")
    health["issues"] = issues
    return health


def main():
    t0 = time.time()
    n = 0
    bad = 0
    fh = None
    current = None
    last_prune = 0.0
    for name in prune():
        print("SOAK_PRUNE removed=%s" % name, flush=True)
    print("SOAK_START tag=%s interval=%ds duration=%s keep_days=%d"
          % (TAG, INTERVAL, "forever" if DURATION <= 0 else DURATION, KEEP_DAYS), flush=True)
    try:
        while DURATION <= 0 or time.time() - t0 < DURATION:
            s = sample()
            n += 1
            if s.get("issues"):
                bad += 1
                print("ISSUE %s %s" % (time.strftime("%H:%M:%S"), s["issues"]), flush=True)
            path = out_path()
            if path != current:                 # 跨零点自动切到下一天的文件
                if fh:
                    fh.close()
                fh = open(path, "a", encoding="utf-8")
                current = path
                print("SOAK_FILE %s" % path, flush=True)
            fh.write(json.dumps(s, ensure_ascii=False) + "\n")
            fh.flush()
            if time.time() - last_prune > 3600:
                last_prune = time.time()
                for name in prune():
                    print("SOAK_PRUNE removed=%s" % name, flush=True)
            time.sleep(INTERVAL)
    finally:
        if fh:
            fh.close()
    print("SOAK_DONE samples=%d issues=%d file=%s" % (n, bad, current), flush=True)


if __name__ == "__main__":
    main()
