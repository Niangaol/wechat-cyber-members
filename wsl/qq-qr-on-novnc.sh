#!/usr/bin/env bash
# 把 NapCat 的登录二维码投到 :99（noVNC 那块屏）上，二维码变了就自动刷新。
# 背景：noVNC 那一屏平时被微信窗口占着，直接盖上去会遮挡 OCR 取景，
# 所以默认贴到右侧空白区，并把图放大成整数倍（nearest neighbor，扫码更清楚）。
#
# 用法（WSL 里）：bash wsl/qq-qr-on-novnc.sh [位置] [边长]
#   默认位置 +1029+0、边长 240（1280x800 屏、微信窗口 1021 宽 → 右边剩约 259px）
set -u
DISP=${DISPLAY_NUM:-:99}
POS=${1:-+1029+0}
SIZE=${2:-240}
SRC=$HOME/Napcat/opt/QQ/resources/app/app_launcher/napcat/cache/qrcode.png
BIG=/tmp/qq-qr-live.png
export DISPLAY=$DISP

echo "display: $DISP"
xdotool getdisplaygeometry || true
echo "wechat window:"
for w in $(xdotool search --name wechat 2>/dev/null); do
  xdotool getwindowgeometry --shell "$w" | tr "\n" " "
  echo
done

if [ ! -f "$SRC" ]; then
  echo "找不到二维码文件：$SRC（NapCat 可能没在等登录）" >&2
  exit 2
fi

# 1) 内容变了才重建放大图（避免 display 每秒重载时闪）
screen -S qqqr-watch -X quit >/dev/null 2>&1
screen -dmS qqqr-watch bash -c '
  last=""
  while true; do
    if [ -f "$HOME/Napcat/opt/QQ/resources/app/app_launcher/napcat/cache/qrcode.png" ]; then
      now=$(md5sum "$HOME/Napcat/opt/QQ/resources/app/app_launcher/napcat/cache/qrcode.png" | cut -d" " -f1)
      if [ "$now" != "$last" ]; then
        convert "$HOME/Napcat/opt/QQ/resources/app/app_launcher/napcat/cache/qrcode.png" \
          -filter point -resize 240x240 -bordercolor white -border 8 /tmp/qq-qr-live.tmp.png \
          && mv /tmp/qq-qr-live.tmp.png /tmp/qq-qr-live.png
        last="$now"
      fi
    fi
    sleep 2
  done'

# 2) 等第一张大图出来
for _ in $(seq 1 15); do [ -f /tmp/qq-qr-live.png ] && break; sleep 1; done

# 3) 显示（-update 1：每秒重读文件，二维码换新会自动跟着变）
screen -S qqqr-view -X quit >/dev/null 2>&1
screen -dmS qqqr-view display -update 1 -geometry "$POS" /tmp/qq-qr-live.png
sleep 3

# 4) 抬到最前 + 截图留证
WID=$(xdotool search --name "qq-qr-live" | head -1 || true)
if [ -n "${WID:-}" ]; then
  xdotool windowraise "$WID" 2>/dev/null || true
  xdotool windowmove "$WID" 1029 0 2>/dev/null || true
  echo "viewer window: $WID"
else
  echo "查不到 viewer 窗口（可能还没映射完）"
fi
import -window root /tmp/novnc-qr-check.png && cp /tmp/novnc-qr-check.png /mnt/d/AgentPrograms/wechat-bot/qq-novnc-qr.png
echo SHOT_DONE /mnt/d/AgentPrograms/wechat-bot/qq-novnc-qr.png
