#!/bin/bash
export DISPLAY=:99
xdotool windowraise 14680150 2>/dev/null
sleep 0.3
xdotool mousemove 640 450
sleep 0.3
for i in 1 2 3; do xdotool click 5; sleep 0.4; done
sleep 1.5
import -window 14680150 /mnt/d/AgentPrograms/wechat-bot/wsl/cal-feed-scrolled2.png
echo done
