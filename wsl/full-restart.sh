#!/bin/bash
# 全套重启：Xvfb（清僵尸 selection）→ x11vnc → websockify → 微信
unset WAYLAND_DISPLAY
export DISPLAY=:99
export QT_QPA_PLATFORM=xcb

# 杀微信全套
pkill -9 -x wechat 2>/dev/null
pkill -9 -f RadiumWMPF 2>/dev/null
pkill -9 -f "wechat_helper|wechat_agent|WeChatAppEx" 2>/dev/null
sleep 2

# 重启 Xvfb（关键：清掉累积的僵尸 X selection/window）
pkill -9 -f "Xvfb :99" 2>/dev/null
sleep 2
rm -f /tmp/.X99-lock
nohup Xvfb :99 -screen 0 1280x800x24 > /tmp/xvfb.log 2>&1 &
sleep 3
xset q > /dev/null 2>&1 && echo XVFB_OK || { echo XVFB_FAIL; exit 1; }

# x11vnc + websockify
pkill -9 -f "x11vnc -display :99" 2>/dev/null; sleep 1
nohup x11vnc -display :99 -localhost -nopw -forever -shared > /tmp/x11vnc.log 2>&1 &
sleep 2
pkill -9 -f "websockify.*6080" 2>/dev/null; sleep 1
nohup websockify --web=/usr/share/novnc 127.0.0.1:6080 localhost:5900 > /tmp/websockify.log 2>&1 &
sleep 2
ss -tln | grep -q 6080 && echo NOVNC_OK || echo NOVNC_FAIL

# 微信
rm -rf ~/.xwechat/lock/* ~/.xwechat/crashinfo/* 2>/dev/null
nohup /usr/bin/wechat > /tmp/wechat-xvfb.log 2>&1 &
for i in $(seq 1 15); do
    sleep 2
    LINE=$(xwininfo -root -tree 2>/dev/null | grep 'Weixin' | head -1)
    [ -n "$LINE" ] && { echo "WECHAT_WINDOW: $LINE"; WID=$(echo "$LINE" | grep -oE '0x[0-9a-f]+' | head -1); import -window "$WID" /mnt/d/AgentPrograms/wechat-bot/wechat-restart.png && echo SHOT_OK; exit 0; }
done
echo NO_WINDOW
echo "微信日志:"; cat /tmp/wechat-xvfb.log | head -10
