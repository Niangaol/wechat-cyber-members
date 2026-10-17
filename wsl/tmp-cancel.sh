#!/bin/bash
export DISPLAY=:99
W=14680150
xdotool windowraise $W
sleep 0.3
xdotool mousemove 700 646
sleep 0.4
xdotool click 1
sleep 2.5
import -window $W /mnt/d/AgentPrograms/wechat-bot/wsl/cal-moments-feed2.png
echo done
