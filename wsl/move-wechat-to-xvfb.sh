#!/bin/bash
# 把微信迁移到虚拟显示 :99（登录态保留）
unset WAYLAND_DISPLAY
export DISPLAY=:99
export QT_QPA_PLATFORM=xcb

pkill -9 wechat 2>/dev/null; sleep 2
rm -rf ~/.xwechat/lock/* ~/.xwechat/crashinfo/* 2>/dev/null
nohup /usr/bin/wechat > /tmp/wechat-xvfb.log 2>&1 &
sleep 5

for i in $(seq 1 15); do
    LINE=$(xwininfo -root -tree 2>/dev/null | grep 'Weixin' | head -1)
    [ -n "$LINE" ] && { echo "窗口出现: $LINE"; WID=$(echo "$LINE" | grep -oE '0x[0-9a-f]+' | head -1); import -window "$WID" /mnt/d/AgentPrograms/wechat-bot/xvfb-wechat.png && echo "截图 OK"; exit 0; }
    sleep 2
done
echo "NO_WINDOW_ON_XVFB"; tail -5 /tmp/wechat-xvfb.log
