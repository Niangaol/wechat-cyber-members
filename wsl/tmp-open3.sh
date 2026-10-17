#!/bin/bash
export DISPLAY=:99
xdotool windowraise 14680150 2>/dev/null
sleep 0.3
xdotool mousemove 413 479
sleep 0.3
xdotool click 1
sleep 2.5
import -window 14680150 /mnt/d/AgentPrograms/wechat-bot/wsl/cal-detail-try.png
echo done
