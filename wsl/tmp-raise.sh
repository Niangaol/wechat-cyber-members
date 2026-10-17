#!/bin/bash
export DISPLAY=:99
xdotool windowraise 14680150
xdotool windowfocus 14680150 2>/dev/null
sleep 0.5
import -window root /mnt/d/AgentPrograms/wechat-bot/wsl/cal-root-after-raise.png
echo done
