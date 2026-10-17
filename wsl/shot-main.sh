#!/bin/bash
export DISPLAY=:99
WID=$(xwininfo -root -tree 2>/dev/null | grep '"Weixin"' | grep -oE '0x[0-9a-f]+' | head -1)
echo "窗口: $WID"
[ -z "$WID" ] && { echo NO_WINDOW; exit 1; }
xwininfo -id "$WID" 2>/dev/null | grep -E "Width|Height|Map"
import -window "$WID" /mnt/d/AgentPrograms/wechat-bot/after-confirm.png && echo SHOT_OK
