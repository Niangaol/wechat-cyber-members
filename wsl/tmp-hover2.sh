#!/bin/bash
export DISPLAY=:99
xdotool key Escape
sleep 0.5
xdotool windowraise 14680150 2>/dev/null
sleep 0.3
xdotool mousemove 893 474
sleep 1.2
import -window 14680150 /mnt/d/AgentPrograms/wechat-bot/wsl/cal-hover-more2.png
echo done
