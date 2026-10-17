#!/bin/bash
export DISPLAY=:99
xdotool windowraise 14680150 2>/dev/null
sleep 0.3
xdotool mousemove 883 632
sleep 1.0
import -window 14680150 /mnt/d/AgentPrograms/wechat-bot/wsl/cal-hover-morebtn.png
echo done
