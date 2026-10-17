#!/bin/bash
export DISPLAY=:0
WID=$(xwininfo -root -tree 2>/dev/null | grep 'Weixin' | grep -oE '0x[0-9a-f]+' | head -1)
[ -z "$WID" ] && { echo "NO_WINDOW"; exit 1; }
xdotool windowmove --sync "$WID" 200 150 2>/dev/null
xdotool windowactivate --sync "$WID" 2>/dev/null
sleep 1
echo "窗口 $WID 状态:"
xwininfo -id "$WID" 2>/dev/null | grep -E "Absolute upper-left|Width:|Height:|Map State"
import -window "$WID" /mnt/d/AgentPrograms/wechat-bot/mirrored-check2.png && echo "SHOT_OK"
