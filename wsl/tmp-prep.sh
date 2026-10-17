#!/bin/bash
export DISPLAY=:99
curl -s -m 5 http://127.0.0.1:8088/v1/models | head -c 300; echo
xdotool windowraise 14680150 2>/dev/null
sleep 0.5
import -window root /mnt/d/AgentPrograms/wechat-bot/wsl/cal-root-for-uitars.png
echo done
