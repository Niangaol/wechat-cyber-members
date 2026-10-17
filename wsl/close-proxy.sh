#!/bin/bash
# Esc 关 Network proxy settings 面板 → 回登录界面 → 点 Log In
export DISPLAY=:99
WID=$(xwininfo -root -tree 2>/dev/null | grep 'Weixin' | grep -oE '0x[0-9a-f]+' | head -1)
echo "窗口: $WID"
xdotool windowactivate --sync "$WID" 2>/dev/null
sleep 1
# Esc 一次
xdotool key --window "$WID" --clearmodifiers Escape
sleep 2
import -window "$WID" /mnt/d/AgentPrograms/wechat-bot/proxy-closed.png 2>/dev/null && echo "Esc 后截图 OK"
xwininfo -id "$WID" 2>/dev/null | grep -E "Width|Height"
