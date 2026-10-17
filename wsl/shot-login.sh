#!/bin/bash
export DISPLAY=:0
WID=$(xwininfo -root -tree 2>/dev/null | grep 'Weixin' | grep -oE '0x[0-9a-f]+' | head -1)
[ -z "$WID" ] && { echo "NO_WINDOW"; exit 1; }
import -window "$WID" /mnt/d/AgentPrograms/wechat-bot/after-login.png && echo "SHOT_OK $WID"
