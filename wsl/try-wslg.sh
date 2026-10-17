#!/bin/bash
# 实验：微信起到 WSLg :0，看 Windows 侧是否渲染
export DISPLAY=:0
unset WAYLAND_DISPLAY
export QT_QPA_PLATFORM=xcb

# 停 :99 的微信和保活（避免它把微信拉回 :99）
systemctl --user stop wechat-stack 2>/dev/null
pkill -9 -x wechat 2>/dev/null
pkill -9 -f RadiumWMPF 2>/dev/null
sleep 2
rm -rf ~/.xwechat/lock/* ~/.xwechat/crashinfo/* 2>/dev/null

setsid nohup /usr/bin/wechat > /tmp/wechat-wslg.log 2>&1 < /dev/null &
disown 2>/dev/null
sleep 8
echo "=== :0 窗口 ==="
xwininfo -root -tree 2>/dev/null | grep -E "Weixin" | head -2 || echo ":0 无 Weixin 窗口"
echo "=== :99 还在吗（Xvfb 不动，只是没微信）==="
pgrep -f "Xvfb :99" > /dev/null && echo "Xvfb :99 仍在"
