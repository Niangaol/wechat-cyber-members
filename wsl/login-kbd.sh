#!/bin/bash
# 键盘路线登录：activate → Tab×1 → Return（Log In 通常是首个可聚焦控件）
export DISPLAY=:99
WID=$(xwininfo -root -tree 2>/dev/null | grep 'Weixin' | grep -oE '0x[0-9a-f]+' | head -1)
echo "窗口: $WID"
xdotool windowactivate --sync "$WID" 2>/dev/null
sleep 1.5
xdotool key --window "$WID" --clearmodifiers Tab
sleep 0.8
xdotool key --window "$WID" --clearmodifiers Return
echo "Tab+Return 已发，等 12 秒"
sleep 12
xwininfo -root -tree 2>/dev/null | grep 'Weixin' | head -2
import -window "$WID" /mnt/d/AgentPrograms/wechat-bot/login-kbd-result.png 2>/dev/null && echo SHOT_OK
