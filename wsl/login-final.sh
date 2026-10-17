#!/bin/bash
# 登录界面：activate → Return（Log In 是默认焦点，不 Tab）
export DISPLAY=:99
WID=$(xwininfo -root -tree 2>/dev/null | grep 'Weixin' | grep -oE '0x[0-9a-f]+' | head -1)
echo "窗口: $WID"
xdotool windowactivate --sync "$WID" 2>/dev/null
sleep 1.5
xdotool key --window "$WID" --clearmodifiers Return
echo "Return 已发，等 15 秒"
sleep 15
xwininfo -root -tree 2>/dev/null | grep 'Weixin' | head -2
import -window "$WID" /mnt/d/AgentPrograms/wechat-bot/login-final.png 2>/dev/null && echo SHOT_OK
