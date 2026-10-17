#!/bin/bash
# 修 X11 socket 目录权限 + 清残留锁，再起 Xvfb :99
rm -f /tmp/.X99-lock /tmp/.X11-unix/X99 2>/dev/null
mkdir -p /tmp/.X11-unix
chmod 1777 /tmp/.X11-unix
# Xvfb
if ! pgrep -f "Xvfb :99" > /dev/null; then
    nohup Xvfb :99 -screen 0 1280x800x24 > /tmp/xvfb.log 2>&1 &
    sleep 2
fi
export DISPLAY=:99
xset q > /dev/null 2>&1 && echo "XVFB_OK" || { echo "XVFB_FAIL"; tail -5 /tmp/xvfb.log; exit 1; }
# x11vnc
pkill -f "x11vnc -display :99" 2>/dev/null; sleep 1
nohup x11vnc -display :99 -localhost -nopw -forever -shared > /tmp/x11vnc.log 2>&1 &
sleep 2
pgrep -f "x11vnc -display :99" > /dev/null && echo "X11VNC_OK" || { echo "X11VNC_FAIL"; tail -5 /tmp/x11vnc.log; exit 1; }
# websockify + noVNC
pkill -f "websockify.*6080" 2>/dev/null; sleep 1
nohup websockify --web=/usr/share/novnc 127.0.0.1:6080 localhost:5900 > /tmp/websockify.log 2>&1 &
sleep 2
pgrep -f "websockify.*6080" > /dev/null && echo "WEBSOCKIFY_OK" || { echo "WEBSOCKIFY_FAIL"; tail -5 /tmp/websockify.log; exit 1; }
echo "VNC_STACK_READY"
