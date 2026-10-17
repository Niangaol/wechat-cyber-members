#!/bin/bash
# 微信崩溃后重拉（保活等不及整点时手动用）
unset WAYLAND_DISPLAY
export DISPLAY=:99
export QT_QPA_PLATFORM=xcb
pkill -9 wechat 2>/dev/null; sleep 2
rm -rf ~/.xwechat/lock/* ~/.xwechat/crashinfo/* 2>/dev/null
nohup /usr/bin/wechat > /tmp/wechat-xvfb.log 2>&1 &
sleep 5
for i in $(seq 1 15); do
    LINE=$(xwininfo -root -tree 2>/dev/null | grep 'Weixin' | head -1)
    [ -n "$LINE" ] && { echo "窗口: $LINE"; WID=$(echo "$LINE" | grep -oE '0x[0-9a-f]+' | head -1); import -window "$WID" /mnt/d/AgentPrograms/wechat-bot/wechat-restart.png && echo SHOT_OK; exit 0; }
    sleep 2
done
echo NO_WINDOW; tail -5 /tmp/wechat-xvfb.log
