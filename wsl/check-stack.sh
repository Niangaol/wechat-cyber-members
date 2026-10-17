#!/bin/bash
# 检查并修复 Xvfb/x11vnc/noVNC 三件套；只补缺失，不动微信
unset WAYLAND_DISPLAY
export DISPLAY=:99

have() { pgrep -f "$1" > /dev/null; }

if ! have "Xvfb :99"; then
    rm -f /tmp/.X99-lock
    setsid nohup Xvfb :99 -screen 0 1280x800x24 > /dev/null 2>&1 < /dev/null &
    sleep 3
    echo "Xvfb started"
else
    echo "Xvfb ok"
fi

if ! have "x11vnc -display :99"; then
    setsid nohup x11vnc -display :99 -localhost -nopw -forever -shared > /dev/null 2>&1 < /dev/null &
    sleep 2
    echo "x11vnc started"
else
    echo "x11vnc ok"
fi

if ! have "websockify.*6080"; then
    setsid nohup websockify --web=/usr/share/novnc 127.0.0.1:6080 localhost:5900 > /dev/null 2>&1 < /dev/null &
    sleep 2
    echo "websockify started"
else
    echo "websockify ok"
fi

echo "--- ports"
ss -ltn 2>/dev/null | grep -E ":6080|:5900" || echo "(no listeners)"
echo "--- http"
curl -s -o /dev/null -w "novnc_http=%{http_code}
" --max-time 5 http://127.0.0.1:6080/vnc.html
echo "--- wechat window"
DISPLAY=:99 xwininfo -root -tree 2>/dev/null | grep -E '"Weixin"' || echo "(no Weixin window)"
