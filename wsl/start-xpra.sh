#!/bin/bash
# xpra 方案：:100 是 xpra 虚拟显示，Windows 客户端连上后窗口以原生形式呈现
unset WAYLAND_DISPLAY

# 杀 :0 的实验微信和 :99 的保活冲突
systemctl --user stop wechat-stack 2>/dev/null
pkill -9 -x wechat 2>/dev/null
pkill -9 -f RadiumWMPF 2>/dev/null
sleep 2

# 起 xpra（如果没起）
if ! xpra list 2>/dev/null | grep -q ":100"; then
    xpra start :100 --bind-tcp=0.0.0.0:10000 --no-daemon &
    sleep 5
fi
xpra list
echo "---"

# 微信起到 xpra 显示
export DISPLAY=:100
export QT_QPA_PLATFORM=xcb
rm -rf ~/.xwechat/lock/* ~/.xwechat/crashinfo/* 2>/dev/null
setsid nohup /usr/bin/wechat > /tmp/wechat-xpra.log 2>&1 < /dev/null &
disown 2>/dev/null
sleep 8
echo "=== :100 窗口 ==="
xwininfo -root -tree 2>/dev/null | grep Weixin | head -2 || echo "无窗口"
echo "=== 10000 端口 ==="
ss -tln | grep 10000 | head -1
