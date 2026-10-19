#!/bin/sh
# 机器人手动启停：Windows 侧一键脚本和 WSL 里都走这里（单一实现，别处不要再复制逻辑）。
#
#   botctl.sh start    启动。不受 8-22 点窗口限制——手动点了就是想现在跑。
#   botctl.sh stop     停止，并留下"手动停止"标记，health/watchdog 不会误报机器人坏了。
#   botctl.sh status   人类可读的状态摘要。
#
# 和 bot-schedule.sh 的分工：那个是每天 8 点起、22 点停的排班，由 systemd 定时器调用；
# 这个是手动启停。2026-10-19 用户要求改为手动控制，两个定时器已 disable，
# 想恢复排班跑：
#   systemctl --user enable --now wechat-bot-start.timer wechat-bot-stop.timer
set -u

# 这个脚本只能在 WSL 里跑。从 Git Bash / MSYS 里直接 sh 它，systemctl 和
# ~/.local/state 都不对，会打出一整屏 unknown——不如一句话说清该去哪跑。
if ! command -v systemctl >/dev/null 2>&1; then
  echo "botctl.sh 要在 WSL 里跑（找不到 systemctl）。" >&2
  echo "Windows 上请双击桌面「微信机器人启停」里的 .cmd，或者跑：" >&2
  echo "  wsl.exe -d Ubuntu-24.04 -u niangao -e bash -lc \"sh /mnt/d/AgentPrograms/wechat-bot/wsl/botctl.sh ${1:-status}\"" >&2
  exit 1
fi

HERE=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
STATE_DIR="${HOME}/.local/state/wechat-bot"
OFFLINE_MARKER="${STATE_DIR}/scheduled-offline.json"
STACK=wechat-stack
BOT=wechat-bot
TIMERS="wechat-bot-start.timer wechat-bot-stop.timer"

# is-active 对 inactive 也是「把状态打到 stdout + 退出码 1」，所以不能写
# || echo inactive——那会把 inactive 打两遍。先捕获再兜底。
svc() {
  s=$(systemctl --user is-active "$1" 2>/dev/null)
  printf '%s' "${s:-unknown}"
}

case "${1:-}" in
  start)
    # 先清下班标记：不清的话 health.py 会一直按"计划内离线"汇报，
    # 看状态的人以为机器人没起来。
    rm -f "$OFFLINE_MARKER"
    systemctl --user start "$STACK" >/dev/null 2>&1
    systemctl --user start "$BOT"
    # 主循环要几个周期才建好基线；立刻查会看到 0/1，像坏了。
    sleep 8
    printf '\n启动完成：wechat-bot=%s  wechat-stack=%s\n' "$(svc "$BOT")" "$(svc "$STACK")"
    ;;
  stop)
    systemctl --user stop "$BOT"
    printf '{"stopped_at":"%s","resume_at":"手动停止：双击 启动机器人.cmd 或跑 botctl.sh start"}\n' \
      "$(date '+%F %T')" > "$OFFLINE_MARKER"
    printf '\n已停止：wechat-bot=%s\n' "$(svc "$BOT")"
    printf '微信本体 wechat-stack 仍在跑（要省内存可另行 systemctl --user stop %s）\n' "$STACK"
    armed=no
    for t in $TIMERS; do
      en=$(systemctl --user is-enabled "$t" 2>/dev/null)
      [ "$en" = enabled ] && armed=yes
    done
    if [ "$armed" = yes ]; then
      printf '\n注意：排班定时器还是启用状态，明天 08:00 会自动把机器人拉起来。\n'
      printf '      想彻底改成手动：systemctl --user disable --now %s\n' "$TIMERS"
    fi
    ;;
  status)
    printf '微信机器人状态  %s\n' "$(date '+%F %T')"
    printf '  机器人 wechat-bot    : %s\n' "$(svc "$BOT")"
    printf '  微信栈 wechat-stack  : %s\n' "$(svc "$STACK")"
    for t in $TIMERS; do
      # is-enabled 对 disabled 也返回退出码 1，不能写 || echo unknown（会多打一行）
      en=$(systemctl --user is-enabled "$t" 2>/dev/null)
      [ -n "$en" ] || en=unknown
      printf '  定时器 %-24s: %s\n' "$t" "$en"
    done
    if [ -f "$OFFLINE_MARKER" ]; then
      printf '  下班标记             : 有（%s）\n' "$(tr -d '\n' < "$OFFLINE_MARKER")"
    else
      printf '  下班标记             : 无\n'
    fi
    python3 "${HERE}/health.py" 2>/dev/null | python3 -c '
import json, sys
try:
    h = json.load(sys.stdin)
except Exception as exc:
    print("  health.py 读取失败:", exc)
    sys.exit()
def age(v):
    try:
        return "%.0f 秒前" % float(v)
    except (TypeError, ValueError):
        return "从未"
print("  总体健康             :", "正常" if h.get("ok") else "异常")
print("  状态                 :", h.get("state"))
print("  心跳                 :", age(h.get("heartbeat_age_s")))
print("  已观察会话           :", h.get("chats_observed"))
print("  队列深度             :", h.get("queue_depth"))
print("  最近回复             :", age(h.get("last_reply_age_s")))
print("  微信内存占用         : %.0f MB" % (h.get("wechat_rss_mb") or 0))
'
    ;;
  *)
    echo "usage: $0 start|stop|status" >&2
    exit 2
    ;;
esac
