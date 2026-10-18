#!/bin/sh
# 机器人上线排班：早上 8 点起、晚上 10 点停（用户 2026-10-18 要求）。
#
# 由两个 systemd 定时器调用：
#   wechat-bot-start.timer  每天 08:00 -> bot-schedule.sh start
#   wechat-bot-stop.timer   每天 22:00 -> bot-schedule.sh stop
#
# 改作息只改下面两个数，然后：
#   systemctl --user daemon-reload
#   systemctl --user restart wechat-bot-start.timer wechat-bot-stop.timer
# 注意：config/resident.json 的 online_window 是同一套作息，改这里要同步改那边
# （进程内闸门是兜底，定时器是省资源，两边一致才不会互相打脸）。
set -u

START_HOUR=8
STOP_HOUR=22
STATE_DIR="$HOME/.local/state/wechat-bot"
OFFLINE_MARKER="$STATE_DIR/scheduled-offline.json"

case "${1:-}" in
  start)
    hour=$(date +%H)
    if [ "$hour" -ge "$START_HOUR" ] && [ "$hour" -lt "$STOP_HOUR" ]; then
      # 真要启动了才清"到点下班"标记——窗外调用不能把它删掉，
      # 否则 health.py 夜里看到 ok:false 会以为机器人坏了。
      rm -f "$OFFLINE_MARKER"
      systemctl --user start wechat-bot
      echo "$(date "+%F %T") 在上线窗口内，已启动 wechat-bot"
    else
      # 定时器 Persistent=true 会在开机后补跑；不在窗口内就什么都不做，
      # 否则半夜开机会把机器人拉起来。
      echo "$(date "+%F %T") 不在上线窗口内，不启动"
    fi
    ;;
  stop)
    systemctl --user stop wechat-bot
    # 留下"到点下班"的标记，否则 health.py 夜里看到 ok:false 会以为机器人坏了
    printf '{"stopped_at":"%s","resume_at":"明天 %02d:00（wechat-bot-start.timer）"}\n' \
      "$(date "+%F %T")" "$START_HOUR" > "$OFFLINE_MARKER"
    echo "$(date "+%F %T") 到点下班，已停止 wechat-bot"
    ;;
  *)
    echo "usage: $0 start|stop" >&2
    exit 2
    ;;
esac
