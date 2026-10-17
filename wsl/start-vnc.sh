#!/bin/bash
# 虚拟显示 + noVNC：微信跑在 :99，浏览器开 localhost:6080 即可查看和操作
set -e
export DISPLAY=:99

# Xvfb（如没起）
if ! pgrep -f "Xvfb :99" > /dev/null; then
    Xvfb :99 -screen 0 1280x800x24 &
    sleep 2
fi

# x11vnc 绑 :99（只监听本机）
if ! pgrep -f "x11vnc -display :99" > /dev/null; then
    x11vnc -display :99 -localhost -nopw -forever -shared -bg -o /tmp/x11vnc.log
fi

# websockify + noVNC（只监听本机 6080）
if ! pgrep -f "websockify.*6080" > /dev/null; then
    websockify --web=/usr/share/novnc 127.0.0.1:6080 localhost:5900 &
    sleep 1
fi

sleep 1
echo "=== 状态 ==="
pgrep -a Xvfb | head -2
pgrep -a x11vnc | head -2
pgrep -a websockify | head -2
ss -tlnp 2>/dev/null | grep -E ":6080|:5900" || netstat -tlnp 2>/dev/null | grep -E ":6080|:5900"
echo "VNC_READY"
