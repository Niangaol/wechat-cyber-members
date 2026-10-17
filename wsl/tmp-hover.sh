#!/bin/bash
export DISPLAY=:99
xdotool windowraise 14680150 2>/dev/null
xdotool mousemove 540 360
sleep 1.0
import -window 14680150 /mnt/d/AgentPrograms/wechat-bot/wsl/cal-hover-more.png
echo done
