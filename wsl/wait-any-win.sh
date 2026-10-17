#!/bin/bash
export DISPLAY=:0
for i in $(seq 1 20); do
    LINE=$(xwininfo -root -tree 2>/dev/null | grep 'Weixin' | head -1)
    [ -n "$LINE" ] && { echo "WINDOW: $LINE"; WID=$(echo "$LINE" | grep -oE '0x[0-9a-f]+' | head -1); xdotool windowmove --sync "$WID" 1140 610 2>/dev/null; sleep 1; import -window "$WID" /mnt/d/AgentPrograms/wechat-bot/mirrored-check.png && echo "SHOT_OK"; exit 0; }
    sleep 2
done
echo "NO_WINDOW"
