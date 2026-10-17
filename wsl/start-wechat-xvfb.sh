#!/bin/bash
# 干净启动微信到 :99（清 lock/crashinfo/net）
unset WAYLAND_DISPLAY
export DISPLAY=:99
export QT_QPA_PLATFORM=xcb
pkill -9 wechat 2>/dev/null; sleep 2
rm -rf ~/.xwechat/lock/* ~/.xwechat/crashinfo/* ~/.xwechat/net/* 2>/dev/null
nohup /usr/bin/wechat > /tmp/wechat-xvfb.log 2>&1 &
for i in $(seq 1 20); do
    sleep 2
    LINE=$(xwininfo -root -tree 2>/dev/null | grep 'Weixin' | head -1)
    [ -n "$LINE" ] && { echo "窗口: $LINE"; WID=$(echo "$LINE" | grep -oE '0x[0-9a-f]+' | head -1); import -window "$WID" /mnt/d/AgentPrograms/wechat-bot/wechat-restart.png && echo SHOT_OK; exit 0; }
    N=$(pgrep -c -f RadiumWMPF || echo 0)
    echo "[$i] RadiumWMPF=$N"
done
echo NO_WINDOW
tail -10 /tmp/wechat-xvfb.log
