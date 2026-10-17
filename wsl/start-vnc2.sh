#!/bin/bash
# VNC 栈（修正版）：unset WAYLAND_DISPLAY，x11vnc 明确只走 X11
unset WAYLAND_DISPLAY
export DISPLAY=:99

# Xvfb
if ! pgrep -f "Xvfb :99" > /dev/null; then
    nohup Xvfb :99 -screen 0 1280x800x24 > /tmp/xvfb.log 2>&1 &
    sleep 2
fi
xset q > /dev/null 2>&1 && echo "XVFB_OK" || { echo "XVFB_FAIL"; tail -5 /tmp/xvfb.log; exit 1; }

# x11vnc（明确 X11，不探测 Wayland）
if ! pgrep -f "x11vnc -display :99" > /dev/null; then
    nohup x11vnc -display :99 -localhost -nopw -forever -shared > /tmp/x11vnc.log 2>&1 &
    sleep 2
fi
pgrep -f "x11vnc -display :99" > /dev/null && echo "X11VNC_OK" || { echo "X11VNC_FAIL"; tail -5 /tmp/x11vnc.log; exit 1; }

# websockify + noVNC
if ! pgrep -f "websockify.*6080" > /dev/null; then
    nohup websockify --web=/usr/share/novnc 127.0.0.1:6080 localhost:5900 > /tmp/websockify.log 2>&1 &
    sleep 2
fi
pgrep -f "websockify.*6080" > /dev/null && echo "WEBSOCKIFY_OK" || { echo "WEBSOCKIFY_FAIL"; tail -5 /tmp/websockify.log; exit 1; }

echo "=== 端口 ==="
ss -tln 2>/dev/null | grep -E ":6080|:5900"
echo "VNC_STACK_READY"
