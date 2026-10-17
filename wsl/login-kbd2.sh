#!/bin/bash
# Esc 关设置 → 直接 Return（不 Tab，赌 Log In 是默认焦点）
export DISPLAY=:99
WID=$(xwininfo -root -tree 2>/dev/null | grep 'Weixin' | grep -oE '0x[0-9a-f]+' | head -1)
xdotool windowactivate --sync "$WID" 2>/dev/null
sleep 1
xdotool key --window "$WID" --clearmodifiers Escape
sleep 1.5
import -window "$WID" /mnt/d/AgentPrograms/wechat-bot/login-back.png 2>/dev/null
echo "--- Esc 后 ---"
xdotool key --window "$WID" --clearmodifiers Return
sleep 10
xwininfo -root -tree 2>/dev/null | grep 'Weixin' | head -2
import -window "$WID" /mnt/d/AgentPrograms/wechat-bot/login-kbd2.png 2>/dev/null && echo SHOT_OK
