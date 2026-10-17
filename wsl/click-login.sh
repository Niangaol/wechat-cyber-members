#!/bin/bash
# 点账号选择界面的 Log In（:99，窗口在 +494+202，按钮相对约 146,302）
export DISPLAY=:99
WID=$(xwininfo -root -tree 2>/dev/null | grep "Weixin" | grep -oE "0x[0-9a-f]+" | head -1)
echo "login wid=$WID"
xdotool windowactivate "$WID" 2>/dev/null
xdotool windowfocus "$WID" 2>/dev/null
sleep 0.6
xdotool mousemove 640 504
sleep 0.3
xdotool click 1
sleep 10
import -window "$WID" /tmp/after-login-click.png 2>/dev/null
xwininfo -root -tree 2>/dev/null | grep -E "Weixin|Moments" | head -3
echo done
