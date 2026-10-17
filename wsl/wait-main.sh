#!/bin/bash
# 轮询等微信主界面（980x710）出现，最多 60 秒
export DISPLAY=:0
for i in $(seq 1 20); do
    INFO=$(xwininfo -root -tree 2>/dev/null | grep '"Weixin"' | head -1)
    W=$(echo "$INFO" | grep -oE '[0-9]+x[0-9]+' | head -1 | cut -dx -f1)
    H=$(echo "$INFO" | grep -oE '[0-9]+x[0-9]+' | head -1 | cut -dx -f2)
    echo "[$i] $INFO"
    if [ "$W" = "980" ] && [ "$H" = "710" ]; then
        WID=$(echo "$INFO" | grep -oE '0x[0-9a-f]+' | head -1)
        echo "MAIN_READY $WID"
        xdotool windowmove --sync "$WID" 1140 610 2>/dev/null
        sleep 1
        import -window "$WID" /mnt/d/AgentPrograms/wechat-bot/main-ready.png && echo "截图 OK"
        exit 0
    fi
    sleep 3
done
echo "TIMEOUT"
