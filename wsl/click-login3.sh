#!/bin/bash
# 键盘路线：激活窗口 → Tab 巡回 → Return 尝试触发 Log In
export DISPLAY=:0
WID=$(xwininfo -root -tree 2>/dev/null | grep 'Weixin' | grep -oE '0x[0-9a-f]+' | head -1)
xdotool windowactivate --sync "$WID" 2>/dev/null
sleep 1
xdotool key --window "$WID" --clearmodifiers Tab
sleep 0.5
xdotool key --window "$WID" --clearmodifiers Tab
sleep 0.5
xdotool key --window "$WID" --clearmodifiers Return
echo "已发送 Return，等 8 秒"
sleep 8
xwininfo -root -tree 2>/dev/null | grep -E '"Weixin"' | head -2
import -window "$WID" /mnt/d/AgentPrograms/wechat-bot/login-state3.png && echo "截图 OK"
