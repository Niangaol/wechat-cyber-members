#!/bin/bash
# Esc 关代理面板 → 确认二维码界面 → 立即截图
export DISPLAY=:0
WID=$(xwininfo -root -tree 2>/dev/null | grep 'Weixin' | grep -oE '0x[0-9a-f]+' | head -1)
xdotool key --window "$WID" --clearmodifiers Escape
sleep 1.5
import -window "$WID" /mnt/d/AgentPrograms/wechat-bot/wechat-qr.png && echo "QR_CAPTURED"
