#!/bin/bash
# 绝对坐标点 Log In（窗口已被挪到 1140,610；按钮相对 140,270）
export DISPLAY=:0
WID=$(xwininfo -root -tree 2>/dev/null | grep 'Weixin' | grep -oE '0x[0-9a-f]+' | head -1)
xwininfo -id "$WID" > /tmp/w.txt 2>/dev/null
WX=$(grep "Absolute upper-left X" /tmp/w.txt | sed 's/[^0-9]//g')
WY=$(grep "Absolute upper-left Y" /tmp/w.txt | sed 's/[^0-9]//g')
echo "窗口位置: $WX,$WY"
BX=$((WX + 140)); BY=$((WY + 270))
echo "按钮绝对坐标: $BX,$BY"
# 先移动再分步点击（press/release 分开，更接近真人）
xdotool mousemove "$BX" "$BY"
sleep 0.5
xdotool mousedown 1
sleep 0.2
xdotool mouseup 1
echo "已点击，等 8 秒"
sleep 8
xwininfo -root -tree 2>/dev/null | grep -E '"Weixin"' | head -2
import -window "$WID" /mnt/d/AgentPrograms/wechat-bot/login-state2.png && echo "截图 OK"
