#!/usr/bin/env bash
# 独立扫码屏：在一张新的 Xvfb(:98) 上只显示 NapCat 登录二维码（放大版），
# 再用 x11vnc + websockify 暴露成 noVNC 页面 —— 不碰 :99 上的微信，也不遮挡 OCR 取景。
# 用法：bash wsl/qq-qr-vnc.sh        然后浏览器打开 http://localhost:6081/vnc.html
set -u
QR_DISPLAY=${QR_DISPLAY:-:98}
QR_VNC_PORT=${QR_VNC_PORT:-5901}
QR_WEB_PORT=${QR_WEB_PORT:-6081}
QR_PIXELS=${QR_PIXELS:-560}
SRC=$HOME/Napcat/opt/QQ/resources/app/app_launcher/napcat/cache/qrcode.png
BIG=/tmp/qq-qr-vnc.png

[ -f "$SRC" ] || { echo "找不到二维码：$SRC（NapCat 没在等登录？）" >&2; exit 2; }

# 1) 专用屏（已存在就复用）
if ! xdpyinfo -display "$QR_DISPLAY" >/dev/null 2>&1; then
  Xvfb "$QR_DISPLAY" -screen 0 640x640x24 -nolisten tcp >/tmp/qq-qr-xvfb.log 2>&1 &
  sleep 2
fi

# 2) 内容变了就重建大图
screen -S qqqr-vnc-watch -X quit >/dev/null 2>&1
screen -dmS qqqr-vnc-watch bash -c '
  last=""
  while true; do
    if [ -f "$HOME/Napcat/opt/QQ/resources/app/app_launcher/napcat/cache/qrcode.png" ]; then
      now=$(md5sum "$HOME/Napcat/opt/QQ/resources/app/app_launcher/napcat/cache/qrcode.png" | cut -d" " -f1)
      if [ "$now" != "$last" ]; then
        convert "$HOME/Napcat/opt/QQ/resources/app/app_launcher/napcat/cache/qrcode.png" \
          -filter point -resize 560x560 -bordercolor white -border 20 /tmp/qq-qr-vnc.tmp.png \
          && mv /tmp/qq-qr-vnc.tmp.png /tmp/qq-qr-vnc.png
        last="$now"
      fi
    fi
    sleep 2
  done'
for _ in $(seq 1 15); do [ -f "$BIG" ] && break; sleep 1; done

# 3) 全屏显示这张图（-update 1 会跟着刷新）
screen -S qqqr-vnc-view -X quit >/dev/null 2>&1
screen -dmS qqqr-vnc-view env DISPLAY="$QR_DISPLAY" display -update 1 -geometry +0+0 -backdrop "$BIG"
sleep 2

# 4) VNC + noVNC
pkill -f "x11vnc -display $QR_DISPLAY" >/dev/null 2>&1 || true
screen -S qqqr-vnc-serve -X quit >/dev/null 2>&1
screen -dmS qqqr-vnc-serve x11vnc -display "$QR_DISPLAY" -rfbport "$QR_VNC_PORT" -localhost -forever -shared -nopw -quiet
sleep 2
pkill -f "websockify.*$QR_WEB_PORT" >/dev/null 2>&1 || true
screen -S qqqr-websock -X quit >/dev/null 2>&1
screen -dmS qqqr-websock websockify --web /usr/share/novnc "$QR_WEB_PORT" "localhost:$QR_VNC_PORT"
sleep 3

echo "noVNC 扫码页: http://localhost:$QR_WEB_PORT/vnc.html"
ss -ltn | grep -E ":$QR_WEB_PORT|:$QR_VNC_PORT" || echo "端口没起来，检查 /tmp 日志"
DISPLAY=$QR_DISPLAY import -window root /tmp/qq-qr-vnc-shot.png 2>/dev/null \
  && cp /tmp/qq-qr-vnc-shot.png /mnt/d/AgentPrograms/wechat-bot/qq-qr-vnc-shot.png \
  && echo SHOT /mnt/d/AgentPrograms/wechat-bot/qq-qr-vnc-shot.png
